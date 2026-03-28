"""从代理骨架姿态构建 VS-T0 兼容的调色板缓冲区。"""

import bpy

from ..constants import (
    DEFAULT_BUFFER_ROW_COUNT,
    DEFAULT_PART_ROW_COUNT,
    DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
    RESERVED_PALETTE_ROWS,
)
from .layout import (
    build_empty_palette_segment,
    build_identity_buffer_rows,
    build_matrix_from_flat_values,
    calculate_slot_capacity_for_part_size,
    convert_matrix_to_palette_rows,
)
from .transform import convert_matrix_from_blender_to_game


_cached_previous_palette_segments = {}


def list_exportable_proxy_pose_bones(proxy_armature):
    """返回允许导出的代理 pose bone，并按槽位排序。"""
    exportable_bones = []
    for pose_bone in proxy_armature.pose.bones:
        if not getattr(pose_bone, "bi_export_enabled", False):
            continue
        if not getattr(pose_bone, "bi_is_proxy", False):
            continue
        slot_id = int(getattr(pose_bone, "bi_slot_id", -1))
        if slot_id < 0:
            continue
        exportable_bones.append(pose_bone)
    return sorted(exportable_bones, key=lambda pose_bone: (pose_bone.bi_slot_id, pose_bone.name))


def build_previous_palette_cache_key(proxy_armature):
    """构建上一帧缓存键，避免不同骨架之间相互污染。"""
    return (
        proxy_armature.name_full,
        int(getattr(proxy_armature, "bi_part_base", 0)),
        int(getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT)),
        int(getattr(proxy_armature, "bi_previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET)),
    )


def validate_palette_window_settings(proxy_armature):
    """校验部位窗口设置，并返回标准化后的布局参数。"""
    part_base = int(getattr(proxy_armature, "bi_part_base", 0))
    part_row_count = int(getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT))
    previous_frame_row_offset = int(getattr(proxy_armature, "bi_previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET))
    buffer_row_count = int(getattr(proxy_armature, "bi_buffer_size", DEFAULT_BUFFER_ROW_COUNT))

    if part_row_count <= RESERVED_PALETTE_ROWS:
        raise ValueError("Part size must be larger than the reserved row count")
    if part_base < 0 or previous_frame_row_offset < 0 or buffer_row_count <= 0:
        raise ValueError("Part base, previous offset, and buffer size must be non-negative")

    previous_part_base = part_base + previous_frame_row_offset
    if part_base + part_row_count > buffer_row_count or previous_part_base + part_row_count > buffer_row_count:
        raise ValueError("Current or previous palette window exceeds the configured buffer size")

    return {
        "part_base": part_base,
        "part_row_count": part_row_count,
        "previous_part_base": previous_part_base,
        "previous_frame_row_offset": previous_frame_row_offset,
        "buffer_row_count": buffer_row_count,
    }


def resolve_bind_matrix_for_export(pose_bone, bind_fallback_bone_names):
    """返回导出时使用的 bind 矩阵，必要时回退到 rest 矩阵。"""
    bind_matrix = build_matrix_from_flat_values(list(getattr(pose_bone, "bi_bind_matrix", [])))
    if not getattr(pose_bone, "bi_bind_valid", False):
        bind_fallback_bone_names.append(pose_bone.name)
        return pose_bone.bone.matrix_local.copy()

    try:
        bind_matrix.inverted()
    except Exception:
        bind_fallback_bone_names.append(pose_bone.name)
        return pose_bone.bone.matrix_local.copy()
    return bind_matrix


def build_current_palette_segment(proxy_armature, part_row_count):
    """为当前部位构建 current 窗口。"""
    current_palette_segment = build_empty_palette_segment(part_row_count)
    exported_bone_metadata = []
    overflow_bone_names = []
    bind_fallback_bone_names = []
    used_slot_ids = []

    for pose_bone in list_exportable_proxy_pose_bones(proxy_armature):
        slot_id = int(pose_bone.bi_slot_id)
        row_base = RESERVED_PALETTE_ROWS + slot_id * 3
        if row_base + 2 >= part_row_count:
            overflow_bone_names.append(pose_bone.name)
            continue

        bind_matrix = resolve_bind_matrix_for_export(pose_bone, bind_fallback_bone_names)
        skin_matrix = pose_bone.matrix.copy() @ bind_matrix.inverted()
        skin_matrix_in_game_space = convert_matrix_from_blender_to_game(skin_matrix)
        current_palette_segment[row_base:row_base + 3] = convert_matrix_to_palette_rows(skin_matrix_in_game_space)
        used_slot_ids.append(slot_id)
        exported_bone_metadata.append(
            {
                "name": pose_bone.name,
                "slot_id": slot_id,
                "bone_type": getattr(pose_bone, "bi_bone_type", "MAIN"),
                "row_base": row_base,
            }
        )

    return {
        "current_palette_segment": current_palette_segment,
        "exported_bone_metadata": exported_bone_metadata,
        "overflow_bone_names": overflow_bone_names,
        "bind_fallback_bones": bind_fallback_bone_names,
        "used_slot_ids": used_slot_ids,
    }


def resolve_previous_palette_segment(proxy_armature, current_palette_segment, part_row_count):
    """返回 previous 窗口；若没有缓存则先用 current 初始化。"""
    cache_key = build_previous_palette_cache_key(proxy_armature)
    previous_palette_segment = _cached_previous_palette_segments.get(cache_key)
    if previous_palette_segment is None or len(previous_palette_segment) != part_row_count:
        return list(current_palette_segment)
    return list(previous_palette_segment)


def build_export_buffer_rows(
    layout_settings,
    current_palette_segment,
    previous_palette_segment,
    used_slot_ids,
    base_buffer_rows=None,
):
    """以现有大缓冲为底，只回填当前部位中已导出槽位对应的 3 行。"""
    buffer_row_count = layout_settings["buffer_row_count"]
    if base_buffer_rows is None:
        buffer_rows = build_identity_buffer_rows(buffer_row_count)
    else:
        buffer_rows = list(base_buffer_rows[:buffer_row_count])
        if len(buffer_rows) < buffer_row_count:
            missing_row_count = buffer_row_count - len(buffer_rows)
            buffer_rows.extend(build_identity_buffer_rows(missing_row_count))

    current_part_base = layout_settings["part_base"]
    previous_part_base = layout_settings["previous_part_base"]
    for slot_id in sorted(set(int(slot_id) for slot_id in used_slot_ids)):
        row_base = RESERVED_PALETTE_ROWS + slot_id * 3
        current_rows = current_palette_segment[row_base:row_base + 3]
        previous_rows = previous_palette_segment[row_base:row_base + 3]
        if len(current_rows) == 3:
            buffer_rows[current_part_base + row_base:current_part_base + row_base + 3] = current_rows
        if len(previous_rows) == 3:
            buffer_rows[previous_part_base + row_base:previous_part_base + row_base + 3] = previous_rows
    return buffer_rows


def build_palette_export_package(proxy_armature, base_buffer_rows=None, base_buffer_path=""):
    """构建完整缓冲区、当前片段、上一帧片段与元数据。"""
    bpy.context.view_layer.update()

    layout_settings = validate_palette_window_settings(proxy_armature)
    current_palette_build = build_current_palette_segment(proxy_armature, layout_settings["part_row_count"])
    current_palette_segment = current_palette_build["current_palette_segment"]
    previous_palette_segment = resolve_previous_palette_segment(
        proxy_armature,
        current_palette_segment,
        layout_settings["part_row_count"],
    )
    buffer_rows = build_export_buffer_rows(
        layout_settings,
        current_palette_segment,
        previous_palette_segment,
        current_palette_build["used_slot_ids"],
        base_buffer_rows=base_buffer_rows,
    )

    metadata = {
        "format": "vs_t0_palette_v1",
        "float4_buffer_size": layout_settings["buffer_row_count"],
        "reserved_rows": RESERVED_PALETTE_ROWS,
        "rows_per_bone": 3,
        "part_base": layout_settings["part_base"],
        "part_size": layout_settings["part_row_count"],
        "previous_base": layout_settings["previous_part_base"],
        "previous_offset": layout_settings["previous_frame_row_offset"],
        "max_slot_capacity": calculate_slot_capacity_for_part_size(layout_settings["part_row_count"]),
        "armature_name": proxy_armature.name,
        "source_mesh": getattr(proxy_armature, "bi_source_mesh_name", ""),
        "frame": bpy.context.scene.frame_current if bpy.context.scene else 0,
        "coordinate_correction": "MATRIX_RX_90_DEG",
        "export_mode": "patch_exported_slots",
        "base_buffer_path": base_buffer_path,
        "exported_bones": current_palette_build["exported_bone_metadata"],
        "used_slots": sorted(set(current_palette_build["used_slot_ids"])),
        "overflow_bones": current_palette_build["overflow_bone_names"],
        "bind_fallback_bones": current_palette_build["bind_fallback_bones"],
    }
    return {
        "buffer_rows": buffer_rows,
        "current_segment": current_palette_segment,
        "previous_segment": previous_palette_segment,
        "metadata": metadata,
    }


def clear_previous_palette_cache(proxy_armature):
    """清空一套代理骨架对应的上一帧缓存。"""
    _cached_previous_palette_segments.pop(build_previous_palette_cache_key(proxy_armature), None)


def cache_current_palette_segment(proxy_armature, segment_rows):
    """把当前帧片段存起来，供下一次导出复用为上一帧。"""
    _cached_previous_palette_segments[build_previous_palette_cache_key(proxy_armature)] = list(segment_rows)
