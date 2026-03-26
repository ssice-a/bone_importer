import bpy

from ..constants import DEFAULT_BUFFER_SIZE, DEFAULT_PART_SIZE, DEFAULT_PREVIOUS_OFFSET, RESERVED_ROWS
from .layout import empty_segment, identity_buffer, matrix_from_flat, matrix_to_rows, max_slot_count_for_part_size
from .transform import convert_blender_matrix_to_game


_previous_palette_cache = {}


def exportable_pose_bones(armature_obj):
    bones = []
    for pose_bone in armature_obj.pose.bones:
        if not getattr(pose_bone, "bi_export_enabled", False):
            continue
        if not getattr(pose_bone, "bi_is_proxy", False):
            continue
        slot_id = int(getattr(pose_bone, "bi_slot_id", -1))
        if slot_id < 0:
            continue
        bones.append(pose_bone)
    return sorted(bones, key=lambda bone: (bone.bi_slot_id, bone.name))


def cache_key(armature_obj):
    return (
        armature_obj.name_full,
        int(getattr(armature_obj, "bi_part_base", 0)),
        int(getattr(armature_obj, "bi_part_size", DEFAULT_PART_SIZE)),
        int(getattr(armature_obj, "bi_previous_offset", DEFAULT_PREVIOUS_OFFSET)),
    )


def build_vst0_export_package(armature_obj):
    bpy.context.view_layer.update()

    part_base = int(getattr(armature_obj, "bi_part_base", 0))
    part_size = int(getattr(armature_obj, "bi_part_size", DEFAULT_PART_SIZE))
    previous_offset = int(getattr(armature_obj, "bi_previous_offset", DEFAULT_PREVIOUS_OFFSET))
    buffer_size = int(getattr(armature_obj, "bi_buffer_size", DEFAULT_BUFFER_SIZE))

    if part_size <= RESERVED_ROWS:
        raise ValueError("Part size must be larger than the reserved row count")
    if part_base < 0 or previous_offset < 0 or buffer_size <= 0:
        raise ValueError("Part base, previous offset, and buffer size must be non-negative")

    previous_base = part_base + previous_offset
    if part_base + part_size > buffer_size or previous_base + part_size > buffer_size:
        raise ValueError("Current or previous palette window exceeds the configured buffer size")

    current_segment = empty_segment(part_size)

    exported = []
    overflow = []
    bind_fallback = []
    used_slots = []
    for pose_bone in exportable_pose_bones(armature_obj):
        slot_id = int(pose_bone.bi_slot_id)
        row_base = RESERVED_ROWS + slot_id * 3
        if row_base + 2 >= part_size:
            overflow.append(pose_bone.name)
            continue

        bind_matrix = matrix_from_flat(list(getattr(pose_bone, "bi_bind_matrix", [])))
        if not getattr(pose_bone, "bi_bind_valid", False):
            bind_matrix = pose_bone.bone.matrix_local.copy()
            bind_fallback.append(pose_bone.name)
        try:
            bind_inverse = bind_matrix.inverted()
        except Exception:
            bind_inverse = pose_bone.bone.matrix_local.copy().inverted()
            bind_fallback.append(pose_bone.name)

        skin_matrix = pose_bone.matrix.copy() @ bind_inverse
        skin_matrix = convert_blender_matrix_to_game(skin_matrix)
        current_segment[row_base:row_base + 3] = matrix_to_rows(skin_matrix)
        used_slots.append(slot_id)
        exported.append(
            {
                "name": pose_bone.name,
                "slot_id": slot_id,
                "bone_type": getattr(pose_bone, "bi_bone_type", "MAIN"),
                "row_base": row_base,
            }
        )

    previous_segment = _previous_palette_cache.get(cache_key(armature_obj))
    if previous_segment is None or len(previous_segment) != part_size:
        previous_segment = list(current_segment)
    else:
        previous_segment = list(previous_segment)

    buffer_rows = identity_buffer(buffer_size)
    buffer_rows[part_base:part_base + part_size] = current_segment
    buffer_rows[previous_base:previous_base + part_size] = previous_segment

    metadata = {
        "format": "vs_t0_palette_v1",
        "float4_buffer_size": buffer_size,
        "reserved_rows": RESERVED_ROWS,
        "rows_per_bone": 3,
        "part_base": part_base,
        "part_size": part_size,
        "previous_base": previous_base,
        "previous_offset": previous_offset,
        "max_slot_capacity": max_slot_count_for_part_size(part_size),
        "armature_name": armature_obj.name,
        "source_mesh": getattr(armature_obj, "bi_source_mesh_name", ""),
        "frame": bpy.context.scene.frame_current if bpy.context.scene else 0,
        "coordinate_correction": "GAME_TO_BLENDER_RX_PLUS_90 / BLENDER_TO_GAME_RX_MINUS_90",
        "exported_bones": exported,
        "used_slots": sorted(set(used_slots)),
        "overflow_bones": overflow,
        "bind_fallback_bones": bind_fallback,
    }
    return {
        "buffer_rows": buffer_rows,
        "current_segment": current_segment,
        "previous_segment": previous_segment,
        "metadata": metadata,
    }


def clear_cached_previous_palette(armature_obj):
    _previous_palette_cache.pop(cache_key(armature_obj), None)


def store_previous_segment(armature_obj, segment_rows):
    _previous_palette_cache[cache_key(armature_obj)] = list(segment_rows)
