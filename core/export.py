"""构建 VS-T0 兼容导出缓冲。"""

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
from .transform import convert_matrix_from_blender_to_game, get_proxy_buffer_correction_mode


_cached_previous_palette_segments = {}


def list_exportable_proxy_pose_bones(proxy_armature, bone_namespace=""):
    """返回允许导出的代理 pose bone，并按槽位排序。"""
    exportable_bones = []
    normalized_namespace = str(bone_namespace or "")
    for pose_bone in proxy_armature.pose.bones:
        if not getattr(pose_bone, "bi_export_enabled", False):
            continue
        if not getattr(pose_bone, "bi_is_proxy", False):
            continue
        if normalized_namespace and str(getattr(pose_bone, "bi_mesh_key", "")) != normalized_namespace:
            continue
        slot_id = int(getattr(pose_bone, "bi_slot_id", -1))
        if slot_id < 0:
            continue
        exportable_bones.append(pose_bone)
    return sorted(exportable_bones, key=lambda pose_bone: (pose_bone.bi_slot_id, pose_bone.name))


def build_previous_palette_cache_key(proxy_armature):
    """构建上一帧缓存键，避免不同骨架互相污染。"""
    if getattr(proxy_armature, "draw_key", ""):
        return (
            proxy_armature.draw_key,
            int(getattr(proxy_armature, "part_base", 0)),
            int(getattr(proxy_armature, "part_size", DEFAULT_PART_ROW_COUNT)),
            int(getattr(proxy_armature, "previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET)),
        )
    return (
        proxy_armature.name_full,
        int(getattr(proxy_armature, "bi_part_base", 0)),
        int(getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT)),
        int(getattr(proxy_armature, "bi_previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET)),
    )


def validate_palette_window_settings(proxy_armature):
    """校验当前代理骨架的部位窗口设置。"""
    part_base = int(getattr(proxy_armature, "part_base", getattr(proxy_armature, "bi_part_base", 0)))
    part_row_count = int(getattr(proxy_armature, "part_size", getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT)))
    previous_frame_row_offset = int(
        getattr(proxy_armature, "previous_offset", getattr(proxy_armature, "bi_previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET))
    )
    buffer_row_count = int(getattr(proxy_armature, "buffer_size", getattr(proxy_armature, "bi_buffer_size", DEFAULT_BUFFER_ROW_COUNT)))

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
    """返回导出时使用的 bind 矩阵。"""
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
    """为当前部位构建 current 段。"""
    source_armature = getattr(proxy_armature, "proxy_armature", proxy_armature)
    bone_namespace = str(getattr(proxy_armature, "bone_namespace", "") or "")
    current_palette_segment = build_empty_palette_segment(part_row_count)
    correction_mode = get_proxy_buffer_correction_mode(proxy_armature)
    exported_bone_metadata = []
    overflow_bone_names = []
    bind_fallback_bone_names = []
    used_slot_ids = []

    for pose_bone in list_exportable_proxy_pose_bones(source_armature, bone_namespace):
        slot_id = int(pose_bone.bi_slot_id)
        row_base = RESERVED_PALETTE_ROWS + slot_id * 3
        if row_base + 2 >= part_row_count:
            overflow_bone_names.append(pose_bone.name)
            continue

        bind_matrix = resolve_bind_matrix_for_export(pose_bone, bind_fallback_bone_names)
        skin_matrix = pose_bone.matrix.copy() @ bind_matrix.inverted()
        skin_matrix_in_game_space = convert_matrix_from_blender_to_game(skin_matrix, correction_mode)
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


def build_runtime_export_plan(proxy_armature):
    """Prepare reusable dense runtime-export data for one proxy armature."""
    source_armature = getattr(proxy_armature, "proxy_armature", proxy_armature)
    bone_namespace = str(getattr(proxy_armature, "bone_namespace", "") or "")
    layout_settings = validate_palette_window_settings(proxy_armature)
    runtime_entries = []
    exported_bone_metadata = []
    overflow_bone_names = []
    bind_fallback_bone_names = []
    slot_count = 0
    correction_mode = get_proxy_buffer_correction_mode(proxy_armature)

    for pose_bone in list_exportable_proxy_pose_bones(source_armature, bone_namespace):
        slot_id = int(pose_bone.bi_slot_id)
        row_base = RESERVED_PALETTE_ROWS + slot_id * 3
        if row_base + 2 >= layout_settings["part_row_count"]:
            overflow_bone_names.append(pose_bone.name)
            continue

        bind_matrix = resolve_bind_matrix_for_export(pose_bone, bind_fallback_bone_names)
        bind_inverse = bind_matrix.inverted()
        dense_row_base = slot_id * 3
        slot_count = max(slot_count, slot_id + 1)
        runtime_entries.append(
            {
                "pose_bone": pose_bone,
                "slot_id": slot_id,
                "dense_row_base": dense_row_base,
                "bind_inverse": bind_inverse,
            }
        )
        exported_bone_metadata.append(
            {
                "name": pose_bone.name,
                "slot_id": slot_id,
                "bone_type": getattr(pose_bone, "bi_bone_type", "MAIN"),
                "row_base": dense_row_base,
            }
        )

    return {
        "layout_settings": layout_settings,
        "slot_count": slot_count,
        "frame_template_rows": build_identity_buffer_rows(slot_count * 3),
        "runtime_entries": runtime_entries,
        "correction_mode": correction_mode,
        "exported_bone_metadata": exported_bone_metadata,
        "overflow_bone_names": overflow_bone_names,
        "bind_fallback_bones": bind_fallback_bone_names,
        "used_slot_ids": [entry["slot_id"] for entry in runtime_entries],
    }


def build_dense_runtime_frame_rows(export_plan):
    """Build one dense [slot][row] frame from the current pose using a cached export plan."""
    frame_rows = list(export_plan["frame_template_rows"])
    correction_mode = export_plan.get("correction_mode")
    for runtime_entry in export_plan["runtime_entries"]:
        skin_matrix = runtime_entry["pose_bone"].matrix.copy() @ runtime_entry["bind_inverse"]
        skin_matrix_in_game_space = convert_matrix_from_blender_to_game(skin_matrix, correction_mode)
        dense_row_base = runtime_entry["dense_row_base"]
        frame_rows[dense_row_base:dense_row_base + 3] = convert_matrix_to_palette_rows(skin_matrix_in_game_space)
    return frame_rows


def resolve_previous_palette_segment(proxy_armature, current_palette_segment, part_row_count):
    """返回 previous 段；若无缓存则用 current 初始化。"""
    cache_key = build_previous_palette_cache_key(proxy_armature)
    previous_palette_segment = _cached_previous_palette_segments.get(cache_key)
    if previous_palette_segment is None or len(previous_palette_segment) != part_row_count:
        return list(current_palette_segment)
    return list(previous_palette_segment)


def apply_palette_patch_to_buffer_rows(
    buffer_rows,
    layout_settings,
    current_palette_segment,
    previous_palette_segment,
    used_slot_ids,
):
    """把一个部位已导出的槽位 patch 到大缓冲。"""
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


def build_row_patches_for_palette_patch(patch_package):
    """把单个代理骨架的 patch 转成绝对行写入列表。"""
    layout_settings = patch_package["layout_settings"]
    current_palette_segment = patch_package["current_segment"]
    previous_palette_segment = patch_package["previous_segment"]
    row_patches = []

    for slot_id in sorted(set(int(slot_id) for slot_id in patch_package["used_slot_ids"])):
        row_base = RESERVED_PALETTE_ROWS + slot_id * 3
        current_rows = current_palette_segment[row_base:row_base + 3]
        previous_rows = previous_palette_segment[row_base:row_base + 3]
        if len(current_rows) == 3:
            row_patches.append((layout_settings["part_base"] + row_base, current_rows))
        if len(previous_rows) == 3:
            row_patches.append((layout_settings["previous_part_base"] + row_base, previous_rows))

    return row_patches


def build_palette_export_patch(proxy_armature):
    """构建单个代理骨架的导出 patch。"""
    bpy.context.view_layer.update()

    layout_settings = validate_palette_window_settings(proxy_armature)
    source_armature = getattr(proxy_armature, "proxy_armature", proxy_armature)
    correction_mode = get_proxy_buffer_correction_mode(proxy_armature)
    current_palette_build = build_current_palette_segment(proxy_armature, layout_settings["part_row_count"])
    current_palette_segment = current_palette_build["current_palette_segment"]
    previous_palette_segment = resolve_previous_palette_segment(
        proxy_armature,
        current_palette_segment,
        layout_settings["part_row_count"],
    )

    metadata = {
        "part_id": int(getattr(proxy_armature, "part_id", getattr(proxy_armature, "bi_part_id", -1))),
        "part_base": layout_settings["part_base"],
        "part_size": layout_settings["part_row_count"],
        "previous_base": layout_settings["previous_part_base"],
        "previous_offset": layout_settings["previous_frame_row_offset"],
        "buffer_correction_mode": correction_mode,
        "armature_name": source_armature.name,
        "draw_key": str(getattr(proxy_armature, "draw_key", "")),
        "source_mesh": str(
            getattr(
                getattr(proxy_armature, "source_object", None),
                "name",
                getattr(proxy_armature, "bi_source_mesh_name", ""),
            )
        ),
        "exported_bones": current_palette_build["exported_bone_metadata"],
        "used_slots": sorted(set(current_palette_build["used_slot_ids"])),
        "overflow_bones": current_palette_build["overflow_bone_names"],
        "bind_fallback_bones": current_palette_build["bind_fallback_bones"],
    }
    return {
        "layout_settings": layout_settings,
        "current_segment": current_palette_segment,
        "previous_segment": previous_palette_segment,
        "used_slot_ids": list(current_palette_build["used_slot_ids"]),
        "metadata": metadata,
    }


def build_palette_export_package_for_proxy_armatures(proxy_armatures, base_buffer_rows=None, base_buffer_path=""):
    """把一个或多个代理骨架导出到同一份大缓冲。"""
    normalized_armatures = tuple(proxy_armatures)
    if not normalized_armatures:
        raise ValueError("No proxy armatures to export")

    patch_packages = [build_palette_export_patch(proxy_armature) for proxy_armature in normalized_armatures]
    buffer_row_count = max(
        patch_package["layout_settings"]["buffer_row_count"] for patch_package in patch_packages
    )
    if base_buffer_rows is None:
        buffer_rows = build_identity_buffer_rows(buffer_row_count)
    else:
        buffer_rows = list(base_buffer_rows[:buffer_row_count])
        if len(buffer_rows) < buffer_row_count:
            buffer_rows.extend(build_identity_buffer_rows(buffer_row_count - len(buffer_rows)))
    exported_parts = []
    overflow_bones = []
    bind_fallback_bones = []

    for patch_package in sorted(
        patch_packages,
        key=lambda item: (
            item["layout_settings"]["part_base"],
            item["metadata"]["armature_name"],
        ),
    ):
        apply_palette_patch_to_buffer_rows(
            buffer_rows,
            patch_package["layout_settings"],
            patch_package["current_segment"],
            patch_package["previous_segment"],
            patch_package["used_slot_ids"],
        )
        exported_parts.append(patch_package["metadata"])
        overflow_bones.extend(patch_package["metadata"]["overflow_bones"])
        bind_fallback_bones.extend(patch_package["metadata"]["bind_fallback_bones"])

    metadata = {
        "format": "vs_t0_palette_v1",
        "float4_buffer_size": buffer_row_count,
        "reserved_rows": RESERVED_PALETTE_ROWS,
        "rows_per_bone": 3,
        "frame": bpy.context.scene.frame_current if bpy.context.scene else 0,
        "coordinate_correction": "MATRIX_RX_90_DEG",
        "export_mode": "selected_parts_only",
        "base_buffer_path": base_buffer_path,
        "max_slot_capacity": calculate_slot_capacity_for_part_size(DEFAULT_PART_ROW_COUNT),
        "parts": exported_parts,
        "overflow_bones": overflow_bones,
        "bind_fallback_bones": bind_fallback_bones,
    }
    return {
        "buffer_rows": buffer_rows,
        "metadata": metadata,
        "part_patches": patch_packages,
    }


def build_palette_export_write_plan_for_proxy_armatures(proxy_armatures):
    """把一个或多个代理骨架导出成就地写回计划。"""
    normalized_armatures = tuple(proxy_armatures)
    if not normalized_armatures:
        raise ValueError("No proxy armatures to export")

    patch_packages = [build_palette_export_patch(proxy_armature) for proxy_armature in normalized_armatures]
    buffer_row_count = max(
        patch_package["layout_settings"]["buffer_row_count"] for patch_package in patch_packages
    )
    exported_parts = []
    overflow_bones = []
    bind_fallback_bones = []
    row_patches = []

    for patch_package in sorted(
        patch_packages,
        key=lambda item: (
            item["layout_settings"]["part_base"],
            item["metadata"]["armature_name"],
        ),
    ):
        row_patches.extend(build_row_patches_for_palette_patch(patch_package))
        exported_parts.append(patch_package["metadata"])
        overflow_bones.extend(patch_package["metadata"]["overflow_bones"])
        bind_fallback_bones.extend(patch_package["metadata"]["bind_fallback_bones"])

    metadata = {
        "format": "vs_t0_palette_v1",
        "float4_buffer_size": buffer_row_count,
        "reserved_rows": RESERVED_PALETTE_ROWS,
        "rows_per_bone": 3,
        "frame": bpy.context.scene.frame_current if bpy.context.scene else 0,
        "coordinate_correction": "MATRIX_RX_90_DEG",
        "export_mode": "selected_parts_only",
        "max_slot_capacity": calculate_slot_capacity_for_part_size(DEFAULT_PART_ROW_COUNT),
        "parts": exported_parts,
        "overflow_bones": overflow_bones,
        "bind_fallback_bones": bind_fallback_bones,
    }
    return {
        "buffer_row_count": buffer_row_count,
        "metadata": metadata,
        "part_patches": patch_packages,
        "row_patches": row_patches,
    }


def build_palette_export_package(proxy_armature):
    """兼容单骨架导出入口。"""
    return build_palette_export_package_for_proxy_armatures((proxy_armature,))


def clear_previous_palette_cache(proxy_armature):
    """清空单套代理骨架对应的 previous 缓存。"""
    _cached_previous_palette_segments.pop(build_previous_palette_cache_key(proxy_armature), None)


def cache_current_palette_segment(proxy_armature, segment_rows):
    """把当前帧片段缓存起来，供下一次导出复用为 previous。"""
    _cached_previous_palette_segments[build_previous_palette_cache_key(proxy_armature)] = list(segment_rows)
