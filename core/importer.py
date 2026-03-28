"""把 VS-T0 调色板缓冲区导回 Blender 并应用到代理骨架。"""

from ..constants import DEFAULT_PART_ROW_COUNT, DEFAULT_PREVIOUS_FRAME_ROW_OFFSET, RESERVED_PALETTE_ROWS
from .context import make_object_active
from .export import list_exportable_proxy_pose_bones
from .layout import build_matrix_from_flat_values, build_matrix_from_palette_rows
from .models import PaletteImportResult
from .transform import convert_matrix_from_game_to_blender


def resolve_palette_segment_window(proxy_armature, metadata, segment_name):
    """确定导入时应该读取当前帧窗口还是上一帧窗口。"""
    metadata = metadata or {}
    part_base = int(metadata.get("part_base", getattr(proxy_armature, "bi_part_base", 0)))
    part_row_count = int(metadata.get("part_size", getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT)))
    previous_frame_row_offset = int(
        metadata.get("previous_offset", getattr(proxy_armature, "bi_previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET))
    )
    previous_part_base = int(metadata.get("previous_base", part_base + previous_frame_row_offset))
    normalized_segment_name = str(segment_name or "CURRENT").upper()
    segment_base = previous_part_base if normalized_segment_name == "PREVIOUS" else part_base
    return {
        "segment": normalized_segment_name,
        "segment_base": segment_base,
        "part_base": part_base,
        "part_size": part_row_count,
        "previous_base": previous_part_base,
    }


def apply_palette_segment_to_proxy_armature(
    context,
    proxy_armature,
    rows,
    binary_path,
    row_start=0,
    metadata=None,
    segment="CURRENT",
):
    """把磁盘中的一个调色板片段应用到代理骨架的 pose bone。"""
    palette_window = resolve_palette_segment_window(proxy_armature, metadata, segment)
    make_object_active(context, proxy_armature, mode="POSE")

    imported_bone_count = 0
    missing_row_count = 0
    for pose_bone in list_exportable_proxy_pose_bones(proxy_armature):
        slot_id = int(pose_bone.bi_slot_id)
        row_base = palette_window["segment_base"] + RESERVED_PALETTE_ROWS + slot_id * 3
        local_row_base = row_base - int(row_start)
        if local_row_base < 0 or local_row_base + 2 >= len(rows):
            missing_row_count += 1
            continue

        skin_matrix_in_game_space = build_matrix_from_palette_rows(rows[local_row_base:local_row_base + 3])
        skin_matrix_in_blender_space = convert_matrix_from_game_to_blender(skin_matrix_in_game_space)
        bind_matrix = build_matrix_from_flat_values(list(getattr(pose_bone, "bi_bind_matrix", [])))
        if not getattr(pose_bone, "bi_bind_valid", False):
            bind_matrix = pose_bone.bone.matrix_local.copy()

        # 对应导出时的 pose @ bind^-1 语义，这里按 skin @ bind 恢复 pose。
        pose_bone.matrix = skin_matrix_in_blender_space @ bind_matrix
        imported_bone_count += 1

    context.view_layer.update()
    return PaletteImportResult(
        armature_name=proxy_armature.name,
        binary_path=binary_path,
        imported_bones=imported_bone_count,
        missing_rows=missing_row_count,
        segment=palette_window["segment"],
        metadata=metadata,
    )
