from ..constants import DEFAULT_PART_SIZE, DEFAULT_PREVIOUS_OFFSET, RESERVED_ROWS
from .context import activate_object
from .export import exportable_pose_bones
from .layout import matrix_from_flat, matrix_from_rows
from .models import PaletteImportResult
from .transform import convert_game_matrix_to_blender


def resolve_palette_window(armature_obj, metadata, segment):
    metadata = metadata or {}
    part_base = int(metadata.get("part_base", getattr(armature_obj, "bi_part_base", 0)))
    part_size = int(metadata.get("part_size", getattr(armature_obj, "bi_part_size", DEFAULT_PART_SIZE)))
    previous_offset = int(metadata.get("previous_offset", getattr(armature_obj, "bi_previous_offset", DEFAULT_PREVIOUS_OFFSET)))
    previous_base = int(metadata.get("previous_base", part_base + previous_offset))
    segment_key = str(segment or "CURRENT").upper()
    segment_base = previous_base if segment_key == "PREVIOUS" else part_base
    return {
        "segment": segment_key,
        "segment_base": segment_base,
        "part_base": part_base,
        "part_size": part_size,
        "previous_base": previous_base,
    }


def apply_palette_rows_to_armature(context, armature_obj, rows, binary_path, metadata=None, segment="CURRENT"):
    layout = resolve_palette_window(armature_obj, metadata, segment)
    activate_object(context, armature_obj, mode="POSE")

    imported_bones = 0
    missing_rows = 0
    for pose_bone in exportable_pose_bones(armature_obj):
        slot_id = int(pose_bone.bi_slot_id)
        row_base = layout["segment_base"] + RESERVED_ROWS + slot_id * 3
        if row_base + 2 >= len(rows):
            missing_rows += 1
            continue

        skin_game = matrix_from_rows(rows[row_base : row_base + 3])
        skin_blender = convert_game_matrix_to_blender(skin_game)
        bind_matrix = matrix_from_flat(list(getattr(pose_bone, "bi_bind_matrix", [])))
        if not getattr(pose_bone, "bi_bind_valid", False):
            bind_matrix = pose_bone.bone.matrix_local.copy()

        pose_bone.matrix = skin_blender @ bind_matrix
        imported_bones += 1

    context.view_layer.update()
    return PaletteImportResult(
        armature_name=armature_obj.name,
        binary_path=binary_path,
        imported_bones=imported_bones,
        missing_rows=missing_rows,
        segment=layout["segment"],
        metadata=metadata,
    )
