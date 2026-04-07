"""Dense multi-frame animation export for one proxy armature per file."""

import json
import os
import struct
from array import array

import bpy

from ..constants import RESERVED_PALETTE_ROWS
from .export import build_dense_runtime_frame_rows, build_runtime_export_plan
from .models import AnimationExportResult


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
    """Build dense animation rows/meta paths for one proxy armature."""
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    safe_name = build_runtime_export_name_prefix(proxy_armature)
    rows_path = os.path.join(directory_path, f"{safe_name}_anim_rows.buf")
    meta_path = os.path.join(directory_path, f"{safe_name}_anim_meta.buf")
    debug_metadata_path = os.path.join(directory_path, f"{safe_name}_anim.json")
    return directory_path, rows_path, meta_path, debug_metadata_path


def build_animation_meta_uint4_rows(proxy_armature, frame_count, slot_count):
    """Pack the mutable runtime constants into uint4 rows for HLSL access."""
    rows_per_frame = int(slot_count) * 3
    return [
        (
            int(slot_count),
            int(frame_count),
            int(rows_per_frame),
            int(RESERVED_PALETTE_ROWS),
        ),
        (
            int(getattr(proxy_armature, "bi_part_base", 0)),
            int(getattr(proxy_armature, "bi_previous_offset", 0)),
            0,
            int(getattr(proxy_armature, "bi_part_id", 0)),
        ),
    ]


def write_animation_meta_rows(meta_path, meta_rows):
    """Write uint4 meta rows to disk for RWStructuredBuffer/StructuredBuffer use."""
    with open(meta_path, "wb") as meta_file:
        for row in meta_rows:
            meta_file.write(struct.pack("<4I", *(int(value) for value in row)))


def flatten_dense_runtime_frame_rows(frame_rows):
    """Pack one dense [slot][row] frame into a contiguous float array."""
    flat_float_values = array("f")
    for row in frame_rows:
        flat_float_values.extend(row)
    return flat_float_values


def write_dense_runtime_frame(binary_file, export_plan):
    """Build and stream one dense animation frame into the open rows file."""
    flatten_dense_runtime_frame_rows(build_dense_runtime_frame_rows(export_plan)).tofile(binary_file)


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

    _directory_path, rows_path, meta_path, debug_metadata_path = resolve_animation_export_paths(
        output_directory,
        proxy_armature,
    )
    export_plan = build_runtime_export_plan(proxy_armature)
    used_slots = tuple(sorted(set(int(slot_id) for slot_id in export_plan["used_slot_ids"])))
    if not used_slots:
        raise ValueError(f"No exportable slots fit inside the configured part window for {proxy_armature.name}")

    slot_count = int(export_plan["slot_count"])
    exported_bone_count = len(used_slots)
    overflow_bones = list(export_plan["overflow_bone_names"])
    bind_fallback_bones = list(export_plan["bind_fallback_bones"])
    meta_rows = build_animation_meta_uint4_rows(
        proxy_armature,
        frame_count=len(exported_frames),
        slot_count=slot_count,
    )
    metadata = {
        "format": "vs_t0_dense_animation_v1",
        "armature_name": proxy_armature.name,
        "source_mesh": getattr(proxy_armature, "bi_source_mesh_name", ""),
        "part_id": int(getattr(proxy_armature, "bi_part_id", -1)),
        "part_base": int(getattr(proxy_armature, "bi_part_base", 0)),
        "previous_offset": int(getattr(proxy_armature, "bi_previous_offset", 0)),
        "fps": float(fps),
        "frame_start": exported_frames[0],
        "frame_end": exported_frames[-1],
        "frame_step": int(frame_step),
        "frame_count": len(exported_frames),
        "frame_numbers": list(exported_frames),
        "slot_count": int(slot_count),
        "bone_count": exported_bone_count,
        "rows_per_slot": 3,
        "rows_per_frame": int(slot_count) * 3,
        "used_slots": list(used_slots),
        "storage_layout": "[frame][slot][row]",
        "meta_layout_uint4": [
            ["slot_count", "frame_count", "rows_per_frame", "reserved_rows"],
            ["part_base", "previous_offset", "current_frame", "part_id"],
        ],
        "initial_current_frame": 0,
        "rows_path": rows_path,
        "meta_path": meta_path,
        "coordinate_correction": "MATRIX_RX_90_DEG",
        "overflow_bones": overflow_bones,
        "bind_fallback_bones": bind_fallback_bones,
    }
    return {
        "proxy_armature": proxy_armature,
        "export_plan": export_plan,
        "exported_frames": exported_frames,
        "rows_path": rows_path,
        "meta_path": meta_path,
        "debug_metadata_path": debug_metadata_path,
        "meta_rows": meta_rows,
        "metadata": metadata,
        "write_metadata": bool(write_metadata),
        "frame_count": len(exported_frames),
        "slot_count": slot_count,
        "exported_bones": exported_bone_count,
    }


def finalize_animation_export_job(export_job):
    """Write meta/debug files and return the public export summary."""
    write_animation_meta_rows(export_job["meta_path"], export_job["meta_rows"])

    debug_metadata_path = export_job["debug_metadata_path"]
    if export_job["write_metadata"]:
        with open(debug_metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(export_job["metadata"], metadata_file, indent=2, ensure_ascii=False)
    else:
        debug_metadata_path = ""

    return AnimationExportResult(
        armature_name=export_job["proxy_armature"].name,
        rows_path=export_job["rows_path"],
        meta_path=export_job["meta_path"],
        frame_count=export_job["frame_count"],
        slot_count=export_job["slot_count"],
        exported_bones=export_job["exported_bones"],
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
    """Export one dense animation rows buffer plus one mutable meta buffer."""
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
        with open(export_job["rows_path"], "wb") as binary_file:
            for frame_number in export_job["exported_frames"]:
                scene.frame_set(frame_number)
                write_dense_runtime_frame(binary_file, export_job["export_plan"])
    finally:
        scene.frame_set(original_frame)

    return finalize_animation_export_job(export_job)
