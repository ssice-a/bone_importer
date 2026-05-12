"""Scene-evaluated multi-frame animation export for the RX standalone runtime."""

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
TQ_FLOATS_PER_BONE = 8


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


def sanitize_export_name(name, fallback):
    """Build a safe file-stem for runtime export sidecar files."""
    candidate_name = str(name or "").strip()
    if not candidate_name:
        candidate_name = str(fallback or "").strip()
    safe_name = candidate_name.replace(os.sep, "_").replace("/", "_")
    safe_name = "".join(character if character.isalnum() or character in ("_", "-", ".") else "_" for character in safe_name)
    return safe_name or "rxanimin"


def normalize_clip_name(clip_name):
    """Return a non-empty logical clip name for manifests and defaults."""
    normalized_name = str(clip_name or "").strip()
    if normalized_name:
        return normalized_name
    scene = bpy.context.scene if bpy.context is not None else None
    if scene is not None and str(scene.name).strip():
        return str(scene.name).strip()
    return "rxanimin"


def clamp_loop_sample_range(frame_count, loop_start, loop_end):
    """Clamp loop sample indices to a safe inclusive range."""
    safe_frame_count = max(int(frame_count), 1)
    normalized_loop_start = min(max(int(loop_start), 0), safe_frame_count - 1)
    normalized_loop_end = min(max(int(loop_end), 0), safe_frame_count - 1)
    if normalized_loop_end < normalized_loop_start:
        normalized_loop_start = 0
        normalized_loop_end = safe_frame_count - 1
    return normalized_loop_start, normalized_loop_end


def resolve_animation_loop_settings(exported_frames, default_loop_start, default_loop_end):
    """Resolve source-frame loop requests into sampled loop indices."""
    normalized_frames = tuple(int(frame_number) for frame_number in exported_frames)
    if not normalized_frames:
        raise ValueError("No exported frames are available for loop configuration")

    requested_loop_start = int(default_loop_start)
    requested_loop_end = int(default_loop_end)
    normalized_loop_start_request = normalized_frames[0] if requested_loop_start < 0 else requested_loop_start
    normalized_loop_end_request = normalized_frames[-1] if requested_loop_end < 0 else requested_loop_end

    loop_start_index = 0
    for sample_index, frame_number in enumerate(normalized_frames):
        if frame_number >= normalized_loop_start_request:
            loop_start_index = sample_index
            break
    else:
        loop_start_index = len(normalized_frames) - 1

    loop_end_index = len(normalized_frames) - 1
    for sample_index in range(len(normalized_frames) - 1, -1, -1):
        if normalized_frames[sample_index] <= normalized_loop_end_request:
            loop_end_index = sample_index
            break
    else:
        loop_end_index = 0

    loop_start_index, loop_end_index = clamp_loop_sample_range(
        len(normalized_frames),
        loop_start_index,
        loop_end_index,
    )
    return {
        "requested_loop_start_frame": normalized_loop_start_request,
        "requested_loop_end_frame": normalized_loop_end_request,
        "resolved_loop_start_frame": normalized_frames[loop_start_index],
        "resolved_loop_end_frame": normalized_frames[loop_end_index],
        "resolved_loop_start_sample": loop_start_index,
        "resolved_loop_end_sample": loop_end_index,
    }


def build_runtime_export_name_prefix(proxy_armature):
    """Use the first eight characters of the source object name as the runtime file prefix."""
    source_mesh_name = str(getattr(proxy_armature, "bi_source_mesh_name", "")).strip()
    candidate_name = source_mesh_name or str(proxy_armature.name)
    short_name = candidate_name[:8].strip()
    safe_name = sanitize_export_name(short_name, proxy_armature.name)
    if safe_name:
        return safe_name
    return sanitize_export_name(proxy_armature.name, "proxy_armature")


def resolve_animation_export_paths(output_directory, proxy_armature):
    """Build animation/bind/static paths for one proxy armature."""
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    safe_name = build_runtime_export_name_prefix(proxy_armature)
    tqs_path = os.path.join(directory_path, f"{safe_name}_clip_tqs.buf")
    bind_path = os.path.join(directory_path, f"{safe_name}_clip_bind.buf")
    static_clip_path = os.path.join(directory_path, f"{safe_name}_clip_static.buf")
    debug_metadata_path = os.path.join(directory_path, f"{safe_name}_clip.json")
    return directory_path, tqs_path, bind_path, static_clip_path, debug_metadata_path


def resolve_clip_export_paths(output_directory, clip_name):
    """Build shared manifest/master-control paths for one exported logical clip."""
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    safe_clip_name = sanitize_export_name(clip_name, "rxanimin")
    clip_manifest_path = os.path.join(directory_path, f"{safe_clip_name}_clip_manifest.json")
    timeline_static_path = os.path.join(directory_path, f"{safe_clip_name}_timeline_static.buf")
    master_playback_path = os.path.join(directory_path, f"{safe_clip_name}_master_playback.buf")
    return directory_path, clip_manifest_path, timeline_static_path, master_playback_path


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


def build_animation_static_uint4_rows(
    proxy_armature,
    frame_count,
    slot_ids,
    fps,
    clip_id,
    presents_per_step=1,
    loop_start=0,
    loop_end=None,
):
    """Pack static clip metadata for future master-playback control buffers."""
    normalized_slot_ids = tuple(int(slot_id) for slot_id in slot_ids)
    packed_slot_rows = pack_slot_ids_uint4_rows(normalized_slot_ids)
    safe_frame_count = max(int(frame_count), 1)
    normalized_loop_start, normalized_loop_end = clamp_loop_sample_range(
        safe_frame_count,
        loop_start,
        safe_frame_count - 1 if loop_end is None else loop_end,
    )
    clip_fps = max(int(round(float(fps))), 1)
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
            clip_fps,
        ),
        (
            int(clip_id),
            max(int(presents_per_step), 1),
            int(normalized_loop_start),
            int(normalized_loop_end),
        ),
    ]
    return header_rows + packed_slot_rows


def write_uint4_buffer_rows(buffer_path, uint4_rows):
    """Write uint4 rows to disk for StructuredBuffer/RWStructuredBuffer use."""
    with open(buffer_path, "wb") as buffer_file:
        for row in uint4_rows:
            buffer_file.write(struct.pack("<4I", *(int(value) for value in row)))


def write_json_file(json_path, payload):
    """Write a UTF-8 JSON sidecar with stable formatting."""
    with open(json_path, "w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, indent=2, ensure_ascii=False)


def build_timeline_static_uint4_rows(frame_count, fps, presents_per_step, loop_start, loop_end):
    """Build one shared timeline-static buffer initialized from export defaults."""
    safe_frame_count = max(int(frame_count), 1)
    normalized_loop_start, normalized_loop_end = clamp_loop_sample_range(
        safe_frame_count,
        loop_start,
        loop_end,
    )
    clip_fps = max(int(round(float(fps))), 1)
    return [
        (
            safe_frame_count,
            clip_fps,
            max(int(presents_per_step), 1),
            0,
        ),
        (
            int(normalized_loop_start),
            int(normalized_loop_end),
            0,
            0,
        ),
    ]


def build_master_playback_uint4_rows(frame_count, presents_per_step, loop_start, loop_end):
    """Build one shared master-playback buffer initialized from exported timeline defaults."""
    safe_frame_count = max(int(frame_count), 1)
    normalized_loop_start, normalized_loop_end = clamp_loop_sample_range(
        safe_frame_count,
        loop_start,
        loop_end,
    )
    return [
        (
            int(ANIM_FLAG_PLAYING | ANIM_FLAG_LOOPING),
            0,
            0,
            0,
        ),
        (
            max(int(presents_per_step), 1),
            int(normalized_loop_start),
            int(normalized_loop_end),
            0,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    ]


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
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    presents_per_step=1,
    default_loop_start=-1,
    default_loop_end=-1,
    write_metadata=True,
):
    """Resolve reusable export state for one proxy armature."""
    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    if not exported_frames:
        raise ValueError("No animation frames to export")

    normalized_clip_name = normalize_clip_name(clip_name)
    (
        _directory_path,
        tqs_path,
        bind_path,
        static_clip_path,
        debug_metadata_path,
    ) = resolve_animation_export_paths(
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
    loop_settings = resolve_animation_loop_settings(
        exported_frames,
        default_loop_start,
        default_loop_end,
    )
    static_clip_rows = build_animation_static_uint4_rows(
        proxy_armature,
        frame_count=len(exported_frames),
        slot_ids=slot_ids,
        fps=fps,
        clip_id=clip_id,
        presents_per_step=presents_per_step,
        loop_start=loop_settings["resolved_loop_start_sample"],
        loop_end=loop_settings["resolved_loop_end_sample"],
    )
    metadata = {
        "format": "rx_anim_clip_part_v1",
        "clip_name": normalized_clip_name,
        "clip_id": int(clip_id),
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
        "clip_fps": max(int(round(float(fps))), 1),
        "default_presents_per_step": max(int(presents_per_step), 1),
        "default_ticks_per_sample": max(int(presents_per_step), 1),
        "default_loop_start_source_frame": loop_settings["resolved_loop_start_frame"],
        "default_loop_end_source_frame": loop_settings["resolved_loop_end_frame"],
        "requested_loop_start_source_frame": loop_settings["requested_loop_start_frame"],
        "requested_loop_end_source_frame": loop_settings["requested_loop_end_frame"],
        "default_loop_start_sample": loop_settings["resolved_loop_start_sample"],
        "default_loop_end_sample": loop_settings["resolved_loop_end_sample"],
        "static_format": "rx_anim_static_clip_v1",
        "timeline_static_format": "rx_anim_timeline_static_v1",
        "master_playback_format": "rx_anim_master_playback_v2",
        "static_clip_layout_uint4": [
            ["bone_count", "sample_count", "reserved_rows", "slot_map_row_count"],
            ["part_base", "previous_offset", "part_size", "clip_fps"],
            ["clip_id", "default_ticks_per_sample", "default_loop_start_sample", "default_loop_end_sample"],
            ["packed_slot_ids...", "...", "...", "..."],
        ],
        "static_clip_id": static_clip_rows[2][0],
        "static_default_presents_per_step": static_clip_rows[2][1],
        "static_default_ticks_per_sample": static_clip_rows[2][1],
        "static_default_loop_start_sample": static_clip_rows[2][2],
        "static_default_loop_end_sample": static_clip_rows[2][3],
        "coordinate_space": "blender_armature_space",
        "coordinate_correction_runtime": "baked_in_export_tq",
        "tqs_path": tqs_path,
        "bind_path": bind_path,
        "static_clip_path": static_clip_path,
        "overflow_bones": overflow_bones,
        "bind_fallback_bones": bind_fallback_bones,
    }
    return {
        "clip_name": normalized_clip_name,
        "clip_id": int(clip_id),
        "proxy_armature": proxy_armature,
        "export_entries": export_entries,
        "exported_frames": exported_frames,
        "slot_ids": slot_ids,
        "tqs_path": tqs_path,
        "bind_path": bind_path,
        "static_clip_path": static_clip_path,
        "debug_metadata_path": debug_metadata_path,
        "static_clip_rows": static_clip_rows,
        "metadata": metadata,
        "write_metadata": bool(write_metadata),
        "frame_count": len(exported_frames),
        "bone_count": bone_count,
    }


def finalize_animation_export_job(export_job):
    """Write bind/static/debug files and return the public export summary."""
    write_bind_inverse_buffer(export_job["bind_path"], export_job["export_entries"])
    write_uint4_buffer_rows(export_job["static_clip_path"], export_job["static_clip_rows"])

    debug_metadata_path = export_job["debug_metadata_path"]
    if export_job["write_metadata"]:
        write_json_file(debug_metadata_path, export_job["metadata"])
    else:
        debug_metadata_path = ""

    return AnimationExportResult(
        armature_name=export_job["proxy_armature"].name,
        tqs_path=export_job["tqs_path"],
        bind_path=export_job["bind_path"],
        static_clip_path=export_job["static_clip_path"],
        frame_count=export_job["frame_count"],
        bone_count=export_job["bone_count"],
        metadata=export_job["metadata"],
        debug_metadata_path=debug_metadata_path,
    )


def build_animation_clip_manifest(clip_name, clip_id, export_results, timeline_static_path="", master_playback_path=""):
    """Build one logical-clip manifest from per-part animation exports."""
    normalized_results = tuple(export_results)
    if not normalized_results:
        raise ValueError("No animation export results are available for the clip manifest")

    primary_metadata = normalized_results[0].metadata
    return {
        "format": "rx_anim_clip_manifest_v1",
        "clip_name": str(clip_name),
        "clip_id": int(clip_id),
        "frame_start": primary_metadata["frame_start"],
        "frame_end": primary_metadata["frame_end"],
        "frame_step": primary_metadata["frame_step"],
        "frame_count": primary_metadata["frame_count"],
        "frame_numbers": list(primary_metadata["frame_numbers"]),
        "fps": primary_metadata["fps"],
        "default_presents_per_step": primary_metadata["default_presents_per_step"],
        "default_ticks_per_sample": primary_metadata["default_ticks_per_sample"],
        "default_loop_start_source_frame": primary_metadata["default_loop_start_source_frame"],
        "default_loop_end_source_frame": primary_metadata["default_loop_end_source_frame"],
        "default_loop_start_sample": primary_metadata["default_loop_start_sample"],
        "default_loop_end_sample": primary_metadata["default_loop_end_sample"],
        "timeline_static_path": timeline_static_path,
        "master_playback_path": master_playback_path,
        "parts": [
            {
                "armature_name": export_result.armature_name,
                "source_mesh": export_result.metadata["source_mesh"],
                "part_id": export_result.metadata["part_id"],
                "part_base": export_result.metadata["part_base"],
                "part_size": export_result.metadata["part_size"],
                "previous_offset": export_result.metadata["previous_offset"],
                "buffer_correction_mode": export_result.metadata["buffer_correction_mode"],
                "bone_count": export_result.bone_count,
                "slot_ids": list(export_result.metadata["slot_ids"]),
                "tqs_path": export_result.tqs_path,
                "bind_path": export_result.bind_path,
                "static_clip_path": export_result.static_clip_path,
            }
            for export_result in normalized_results
        ],
    }


def build_timeline_static_metadata(clip_name, clip_id, export_results):
    """Build one metadata sidecar describing the exported shared timeline defaults."""
    normalized_results = tuple(export_results)
    if not normalized_results:
        raise ValueError("No animation export results are available for the timeline static buffer")

    primary_metadata = normalized_results[0].metadata
    return {
        "format": "rx_anim_timeline_static_v1",
        "clip_name": str(clip_name),
        "clip_id": int(clip_id),
        "frame_start": primary_metadata["frame_start"],
        "frame_end": primary_metadata["frame_end"],
        "frame_step": primary_metadata["frame_step"],
        "frame_count": primary_metadata["frame_count"],
        "frame_numbers": list(primary_metadata["frame_numbers"]),
        "clip_fps": primary_metadata["clip_fps"],
        "default_presents_per_step": primary_metadata["default_presents_per_step"],
        "default_ticks_per_sample": primary_metadata["default_ticks_per_sample"],
        "default_loop_start_sample": primary_metadata["default_loop_start_sample"],
        "default_loop_end_sample": primary_metadata["default_loop_end_sample"],
        "default_loop_start_source_frame": primary_metadata["default_loop_start_source_frame"],
        "default_loop_end_source_frame": primary_metadata["default_loop_end_source_frame"],
        "timeline_static_layout_uint4": [
            ["sample_count", "clip_fps", "default_ticks_per_sample", "reserved"],
            ["default_loop_start_sample", "default_loop_end_sample", "reserved", "reserved"],
        ],
    }


def build_master_playback_metadata(clip_name, clip_id, export_results):
    """Build one metadata sidecar describing the exported master-playback buffer."""
    normalized_results = tuple(export_results)
    if not normalized_results:
        raise ValueError("No animation export results are available for the master playback buffer")

    primary_metadata = normalized_results[0].metadata
    return {
        "format": "rx_anim_master_playback_v2",
        "clip_name": str(clip_name),
        "clip_id": int(clip_id),
        "shared_semantics": "timeline_only",
        "default_playing": True,
        "default_looping": True,
        "default_presents_per_step": primary_metadata["default_presents_per_step"],
        "default_ticks_per_sample": primary_metadata["default_ticks_per_sample"],
        "default_loop_start_sample": primary_metadata["default_loop_start_sample"],
        "default_loop_end_sample": primary_metadata["default_loop_end_sample"],
        "default_loop_start_source_frame": primary_metadata["default_loop_start_source_frame"],
        "default_loop_end_source_frame": primary_metadata["default_loop_end_source_frame"],
        "frame_count": primary_metadata["frame_count"],
        "frame_numbers": list(primary_metadata["frame_numbers"]),
        "control_buffer_layout_uint4": [
            ["flags", "previous_tick", "current_tick", "playback_tick"],
            ["ticks_per_sample", "loop_start_sample", "loop_end_sample", "seek_tick"],
            ["seek_active", "last_control_token", "reserved", "reserved"],
        ],
        "control_flag_bits": {
            "playing": 1,
            "looping": 2,
        },
    }


def write_clip_sidecar_files(output_directory, clip_name, clip_id, export_results, write_metadata):
    """Write shared clip manifest and master-playback files."""
    if not export_results:
        return "", "", "", "", ""

    (
        _directory_path,
        clip_manifest_path,
        timeline_static_path,
        master_playback_path,
    ) = resolve_clip_export_paths(output_directory, clip_name)
    primary_metadata = export_results[0].metadata
    timeline_static_rows = build_timeline_static_uint4_rows(
        frame_count=primary_metadata["frame_count"],
        fps=primary_metadata["clip_fps"],
        presents_per_step=primary_metadata["default_presents_per_step"],
        loop_start=primary_metadata["default_loop_start_sample"],
        loop_end=primary_metadata["default_loop_end_sample"],
    )
    write_uint4_buffer_rows(timeline_static_path, timeline_static_rows)
    master_playback_rows = build_master_playback_uint4_rows(
        frame_count=primary_metadata["frame_count"],
        presents_per_step=primary_metadata["default_presents_per_step"],
        loop_start=primary_metadata["default_loop_start_sample"],
        loop_end=primary_metadata["default_loop_end_sample"],
    )
    write_uint4_buffer_rows(master_playback_path, master_playback_rows)
    write_json_file(
        clip_manifest_path,
        build_animation_clip_manifest(
            clip_name,
            clip_id,
            export_results,
            timeline_static_path=timeline_static_path,
            master_playback_path=master_playback_path,
        ),
    )
    if write_metadata:
        timeline_static_metadata_path = timeline_static_path.replace(".buf", ".json")
        master_playback_metadata_path = master_playback_path.replace(".buf", ".json")
        write_json_file(
            timeline_static_metadata_path,
            build_timeline_static_metadata(clip_name, clip_id, export_results),
        )
        write_json_file(master_playback_metadata_path, build_master_playback_metadata(clip_name, clip_id, export_results))
        return (
            clip_manifest_path,
            timeline_static_path,
            master_playback_path,
            timeline_static_metadata_path,
            master_playback_metadata_path,
        )
    return clip_manifest_path, timeline_static_path, master_playback_path, "", ""


def write_shared_timeline_sidecar_files(
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    presents_per_step=1,
    default_loop_start=-1,
    default_loop_end=-1,
    write_metadata=True,
):
    """Write shared timeline/master buffers without requiring bone clip results."""
    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    if not exported_frames:
        raise ValueError("No animation frames are available for shared timeline export")

    normalized_clip_name = normalize_clip_name(clip_name)
    loop_settings = resolve_animation_loop_settings(
        exported_frames,
        default_loop_start,
        default_loop_end,
    )
    (
        _directory_path,
        _clip_manifest_path,
        timeline_static_path,
        master_playback_path,
    ) = resolve_clip_export_paths(output_directory, normalized_clip_name)
    timeline_static_rows = build_timeline_static_uint4_rows(
        frame_count=len(exported_frames),
        fps=fps,
        presents_per_step=presents_per_step,
        loop_start=loop_settings["resolved_loop_start_sample"],
        loop_end=loop_settings["resolved_loop_end_sample"],
    )
    write_uint4_buffer_rows(timeline_static_path, timeline_static_rows)
    master_playback_rows = build_master_playback_uint4_rows(
        frame_count=len(exported_frames),
        presents_per_step=presents_per_step,
        loop_start=loop_settings["resolved_loop_start_sample"],
        loop_end=loop_settings["resolved_loop_end_sample"],
    )
    write_uint4_buffer_rows(master_playback_path, master_playback_rows)

    timeline_static_metadata_path = ""
    master_playback_metadata_path = ""
    if write_metadata:
        common_payload = {
            "clip_name": normalized_clip_name,
            "clip_id": int(clip_id),
            "frame_start": exported_frames[0],
            "frame_end": exported_frames[-1],
            "frame_step": int(frame_step),
            "frame_count": len(exported_frames),
            "frame_numbers": list(exported_frames),
            "clip_fps": max(int(round(float(fps))), 1),
            "default_presents_per_step": max(int(presents_per_step), 1),
            "default_ticks_per_sample": max(int(presents_per_step), 1),
            "default_loop_start_source_frame": loop_settings["resolved_loop_start_frame"],
            "default_loop_end_source_frame": loop_settings["resolved_loop_end_frame"],
            "default_loop_start_sample": loop_settings["resolved_loop_start_sample"],
            "default_loop_end_sample": loop_settings["resolved_loop_end_sample"],
        }
        timeline_static_metadata_path = timeline_static_path.replace(".buf", ".json")
        master_playback_metadata_path = master_playback_path.replace(".buf", ".json")
        write_json_file(
            timeline_static_metadata_path,
            {
                "format": "rx_anim_timeline_static_v1",
                **common_payload,
                "timeline_static_layout_uint4": [
                    ["sample_count", "clip_fps", "default_ticks_per_sample", "reserved"],
                    ["default_loop_start_sample", "default_loop_end_sample", "reserved", "reserved"],
                ],
            },
        )
        write_json_file(
            master_playback_metadata_path,
            {
                "format": "rx_anim_master_playback_v2",
                **common_payload,
                "master_playback_layout_uint4": [
                    ["flags", "previous_tick", "current_tick", "playback_tick"],
                    ["ticks_per_sample", "loop_start_sample", "loop_end_sample", "seek_tick"],
                    ["seek_active", "last_control_token", "reserved", "reserved"],
                ],
            },
        )

    return (
        timeline_static_path,
        master_playback_path,
        timeline_static_metadata_path,
        master_playback_metadata_path,
    )


def export_animation_clip_for_proxy_armature(
    proxy_armature,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    presents_per_step=1,
    default_loop_start=-1,
    default_loop_end=-1,
    write_metadata=True,
):
    """Export one scene-evaluated TQ animation set for one proxy armature."""
    scene = bpy.context.scene
    export_job = prepare_animation_export_job(
        proxy_armature=proxy_armature,
        output_directory=output_directory,
        clip_name=clip_name,
        clip_id=clip_id,
        frame_start=frame_start,
        frame_end=frame_end,
        frame_step=frame_step,
        fps=fps,
        presents_per_step=presents_per_step,
        default_loop_start=default_loop_start,
        default_loop_end=default_loop_end,
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
