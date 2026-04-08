"""Scene-evaluated multi-frame animation export using TQ + bind + meta buffers."""

import json
import os
import struct
from array import array

import bpy

from ..constants import RESERVED_PALETTE_ROWS
from .export import build_runtime_export_plan
from .layout import convert_matrix_to_palette_rows
from .models import AnimationExportResult
from .transform import BUFFER_CORRECTION_NONE, build_extra_blender_correction_matrix, get_proxy_buffer_correction_mode


INVALID_SLOT_ID = 0xFFFFFFFF
ANIM_FLAG_PLAYING = 1
ANIM_FLAG_LOOPING = 2


def normalize_animation_frame_range(frame_start, frame_end, frame_step):
    """Return a validated list of exported frames."""
    normalized_start = int(frame_start)
    normalized_end = int(frame_end)
    normalized_step = int(frame_step)
    if normalized_step <= 0:
        raise ValueError("Animation frame step must be greater than zero")
    if normalized_end < normalized_start:
        raise ValueError("Animation frame end must be greater than or equal to frame start")
    return tuple(range(normalized_start, normalized_end + 1, normalized_step))


def build_runtime_export_name_prefix(proxy_armature):
    """Use the first eight characters of the source object name as the runtime file prefix."""
    source_mesh_name = str(getattr(proxy_armature, "bi_source_mesh_name", "")).strip()
    candidate_name = source_mesh_name or str(proxy_armature.name)
    short_name = candidate_name[:8].strip()
    safe_name = short_name.replace(os.sep, "_").replace("/", "_")
    if safe_name:
        return safe_name
    return str(proxy_armature.name).replace(os.sep, "_").replace("/", "_")


def resolve_animation_export_paths(output_directory, proxy_armature):
    """Build animation/bind/meta paths for one proxy armature."""
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    safe_name = build_runtime_export_name_prefix(proxy_armature)
    tqs_path = os.path.join(directory_path, f"{safe_name}_anim_tqs.buf")
    bind_path = os.path.join(directory_path, f"{safe_name}_bind.buf")
    meta_path = os.path.join(directory_path, f"{safe_name}_anim_meta.buf")
    debug_metadata_path = os.path.join(directory_path, f"{safe_name}_anim.json")
    return directory_path, tqs_path, bind_path, meta_path, debug_metadata_path


def pack_slot_ids_uint4_rows(slot_ids):
    """Pack slot ids into uint4 rows for the runtime lookup table."""
    packed_rows = []
    normalized_slot_ids = [int(slot_id) for slot_id in slot_ids]
    for slot_index in range(0, len(normalized_slot_ids), 4):
        packed_chunk = normalized_slot_ids[slot_index:slot_index + 4]
        while len(packed_chunk) < 4:
            packed_chunk.append(INVALID_SLOT_ID)
        packed_rows.append(tuple(packed_chunk))
    return packed_rows


def build_initial_playback_state(frame_count):
    """Return the initial previous/current frame pair expected by the runtime."""
    safe_frame_count = max(int(frame_count), 1)
    if safe_frame_count == 1:
        return 0, 0
    return 0, 1


def build_animation_meta_uint4_rows(proxy_armature, frame_count, slot_ids, presents_per_step=1):
    """Pack runtime constants into uint4 rows for the TQ playback shaders."""
    normalized_slot_ids = tuple(int(slot_id) for slot_id in slot_ids)
    packed_slot_rows = pack_slot_ids_uint4_rows(normalized_slot_ids)
    previous_frame, current_frame = build_initial_playback_state(frame_count)
    safe_frame_count = max(int(frame_count), 1)
    loop_end = safe_frame_count - 1
    header_rows = [
        (
            len(normalized_slot_ids),
            safe_frame_count,
            int(RESERVED_PALETTE_ROWS),
            len(packed_slot_rows),
        ),
        (
            int(getattr(proxy_armature, "bi_part_base", 0)),
            int(getattr(proxy_armature, "bi_previous_offset", 0)),
            int(getattr(proxy_armature, "bi_part_size", 0)),
            int(getattr(proxy_armature, "bi_part_id", 0)),
        ),
        (
            int(previous_frame),
            int(current_frame),
            0,
            int(ANIM_FLAG_PLAYING | ANIM_FLAG_LOOPING),
        ),
        (
            max(int(presents_per_step), 1),
            0,
            int(loop_end),
            0,
        ),
    ]
    return header_rows + packed_slot_rows


def write_animation_meta_rows(meta_path, meta_rows):
    """Write uint4 meta rows to disk for RWStructuredBuffer use."""
    with open(meta_path, "wb") as meta_file:
        for row in meta_rows:
            meta_file.write(struct.pack("<4I", *(int(value) for value in row)))


def build_bind_inverse_rows(export_entries):
    """Flatten cached bind-inverse matrices into float4 rows."""
    flat_float_values = array("f")
    for export_entry in export_entries:
        for row in convert_matrix_to_palette_rows(export_entry["bind_inverse"]):
            flat_float_values.extend(row)
    return flat_float_values


def write_bind_inverse_buffer(bind_path, export_entries):
    """Write bind-inverse rows once for one proxy armature."""
    bind_rows = build_bind_inverse_rows(export_entries)
    with open(bind_path, "wb") as bind_file:
        bind_rows.tofile(bind_file)


def flatten_tqs_frame_rows(export_entries):
    """Pack one frame of evaluated proxy pose into contiguous TQ float rows."""
    flat_float_values = array("f")
    extend_values = flat_float_values.extend
    for export_entry in export_entries:
        pose_matrix = export_entry["corrected_pose_matrix_getter"]()
        translation, rotation, scale = pose_matrix.decompose()
        rotation.normalize()
        extend_values((translation.x, translation.y, translation.z, 1.0))
        extend_values((rotation.x, rotation.y, rotation.z, rotation.w))
    return flat_float_values


def build_tqs_frame_buffer(export_entries):
    """Allocate one reusable per-frame float buffer for TQ export."""
    return array("f", [0.0]) * (len(export_entries) * 8)


def fill_tqs_frame_buffer(export_entries, frame_buffer):
    """Fill one reusable float buffer with the current frame's TQ values."""
    buffer_index = 0
    for export_entry in export_entries:
        pose_matrix = export_entry["corrected_pose_matrix_getter"]()
        translation, rotation, _scale = pose_matrix.decompose()
        rotation.normalize()

        frame_buffer[buffer_index] = translation.x
        frame_buffer[buffer_index + 1] = translation.y
        frame_buffer[buffer_index + 2] = translation.z
        frame_buffer[buffer_index + 3] = 1.0

        frame_buffer[buffer_index + 4] = rotation.x
        frame_buffer[buffer_index + 5] = rotation.y
        frame_buffer[buffer_index + 6] = rotation.z
        frame_buffer[buffer_index + 7] = rotation.w
        buffer_index += 8

    return frame_buffer


def write_tqs_animation_frame(binary_file, export_entries, frame_buffer=None):
    """Write one scene-evaluated TQ frame into the open animation file."""
    if frame_buffer is None:
        flatten_tqs_frame_rows(export_entries).tofile(binary_file)
        return
    fill_tqs_frame_buffer(export_entries, frame_buffer).tofile(binary_file)


def prepare_animation_export_job(
    proxy_armature,
    output_directory,
    frame_start,
    frame_end,
    frame_step,
    fps,
    write_metadata=True,
):
    """Resolve reusable export state for one proxy armature."""
    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    if not exported_frames:
        raise ValueError("No animation frames to export")

    _directory_path, tqs_path, bind_path, meta_path, debug_metadata_path = resolve_animation_export_paths(
        output_directory,
        proxy_armature,
    )
    export_plan = build_runtime_export_plan(proxy_armature)
    correction_mode = get_proxy_buffer_correction_mode(proxy_armature)
    extra_correction_matrix = build_extra_blender_correction_matrix(correction_mode)
    export_entries = tuple(
        {
            **export_entry,
            "corrected_pose_matrix_getter": (
                (lambda pose_bone=export_entry["pose_bone"]: pose_bone.matrix.copy())
                if correction_mode == BUFFER_CORRECTION_NONE
                else (
                    lambda pose_bone=export_entry["pose_bone"], correction_matrix=extra_correction_matrix:
                    correction_matrix @ pose_bone.matrix
                )
            ),
        }
        for export_entry in export_plan["runtime_entries"]
    )
    slot_ids = tuple(int(export_entry["slot_id"]) for export_entry in export_entries)
    if not slot_ids:
        raise ValueError(f"No exportable slots fit inside the configured part window for {proxy_armature.name}")

    bone_count = len(export_entries)
    overflow_bones = list(export_plan["overflow_bone_names"])
    bind_fallback_bones = list(export_plan["bind_fallback_bones"])
    meta_rows = build_animation_meta_uint4_rows(
        proxy_armature,
        frame_count=len(exported_frames),
        slot_ids=slot_ids,
        presents_per_step=1,
    )
    metadata = {
        "format": "vs_t0_tq_animation_v1",
        "armature_name": proxy_armature.name,
        "source_mesh": getattr(proxy_armature, "bi_source_mesh_name", ""),
        "part_id": int(getattr(proxy_armature, "bi_part_id", -1)),
        "part_base": int(getattr(proxy_armature, "bi_part_base", 0)),
        "part_size": int(getattr(proxy_armature, "bi_part_size", 0)),
        "buffer_correction_mode": get_proxy_buffer_correction_mode(proxy_armature),
        "previous_offset": int(getattr(proxy_armature, "bi_previous_offset", 0)),
        "fps": float(fps),
        "frame_start": exported_frames[0],
        "frame_end": exported_frames[-1],
        "frame_step": int(frame_step),
        "frame_count": len(exported_frames),
        "frame_numbers": list(exported_frames),
        "bone_count": bone_count,
        "slot_ids": list(slot_ids),
        "rows_per_bone": 2,
        "storage_layout": "[frame][bone][row]",
        "row_semantics": [
            "translation_xyz",
            "rotation_quaternion_xyzw",
        ],
        "meta_layout_uint4": [
            ["bone_count", "frame_count", "reserved_rows", "slot_map_row_count"],
            ["part_base", "previous_offset", "part_size", "part_id"],
            ["previous_frame", "current_frame", "playback_tick", "flags"],
            ["presents_per_step", "loop_start", "loop_end", "reserved"],
            ["packed_slot_ids...", "...", "...", "..."],
        ],
        "initial_previous_frame": meta_rows[2][0],
        "initial_current_frame": meta_rows[2][1],
        "initial_playback_tick": meta_rows[2][2],
        "initial_flags": meta_rows[2][3],
        "presents_per_step": meta_rows[3][0],
        "loop_start": meta_rows[3][1],
        "loop_end": meta_rows[3][2],
        "coordinate_space": "blender_armature_space",
        "coordinate_correction_runtime": "baked_in_export_tq",
        "tqs_path": tqs_path,
        "bind_path": bind_path,
        "meta_path": meta_path,
        "overflow_bones": overflow_bones,
        "bind_fallback_bones": bind_fallback_bones,
    }
    return {
        "proxy_armature": proxy_armature,
        "export_entries": export_entries,
        "exported_frames": exported_frames,
        "tqs_path": tqs_path,
        "bind_path": bind_path,
        "meta_path": meta_path,
        "debug_metadata_path": debug_metadata_path,
        "meta_rows": meta_rows,
        "metadata": metadata,
        "write_metadata": bool(write_metadata),
        "frame_count": len(exported_frames),
        "bone_count": bone_count,
    }


def finalize_animation_export_job(export_job):
    """Write bind/meta/debug files and return the public export summary."""
    write_bind_inverse_buffer(export_job["bind_path"], export_job["export_entries"])
    write_animation_meta_rows(export_job["meta_path"], export_job["meta_rows"])

    debug_metadata_path = export_job["debug_metadata_path"]
    if export_job["write_metadata"]:
        with open(debug_metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(export_job["metadata"], metadata_file, indent=2, ensure_ascii=False)
    else:
        debug_metadata_path = ""

    return AnimationExportResult(
        armature_name=export_job["proxy_armature"].name,
        tqs_path=export_job["tqs_path"],
        bind_path=export_job["bind_path"],
        meta_path=export_job["meta_path"],
        frame_count=export_job["frame_count"],
        bone_count=export_job["bone_count"],
        metadata=export_job["metadata"],
        debug_metadata_path=debug_metadata_path,
    )


def export_animation_clip_for_proxy_armature(
    proxy_armature,
    output_directory,
    frame_start,
    frame_end,
    frame_step,
    fps,
    write_metadata=True,
):
    """Export one scene-evaluated TQ animation set for one proxy armature."""
    scene = bpy.context.scene
    export_job = prepare_animation_export_job(
        proxy_armature=proxy_armature,
        output_directory=output_directory,
        frame_start=frame_start,
        frame_end=frame_end,
        frame_step=frame_step,
        fps=fps,
        write_metadata=write_metadata,
    )
    original_frame = scene.frame_current

    try:
        with open(export_job["tqs_path"], "wb") as binary_file:
            for frame_number in export_job["exported_frames"]:
                scene.frame_set(frame_number)
                write_tqs_animation_frame(binary_file, export_job["export_entries"])
    finally:
        scene.frame_set(original_frame)

    return finalize_animation_export_job(export_job)
