"""Dense multi-frame animation export for one proxy armature per file."""

import json
import os
import struct
from array import array

import bpy

from ..constants import RESERVED_PALETTE_ROWS
from .export import build_palette_export_patch
from .layout import build_identity_buffer_rows
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


def build_dense_frame_rows_from_patch(patch_package, slot_count):
    """Build one dense frame laid out as [slot][row] with identity-filled gaps."""
    frame_rows = build_identity_buffer_rows(int(slot_count) * 3)
    current_segment = patch_package["current_segment"]
    for slot_id in sorted(set(int(slot_id) for slot_id in patch_package["used_slot_ids"])):
        source_row_base = RESERVED_PALETTE_ROWS + slot_id * 3
        target_row_base = slot_id * 3
        frame_rows[target_row_base:target_row_base + 3] = current_segment[source_row_base:source_row_base + 3]
    return frame_rows


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
    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    if not exported_frames:
        raise ValueError("No animation frames to export")

    directory_path, rows_path, meta_path, debug_metadata_path = resolve_animation_export_paths(
        output_directory,
        proxy_armature,
    )
    original_frame = scene.frame_current

    used_slots = None
    slot_count = 0
    frame_rows = []
    exported_bone_count = 0
    overflow_bones = []
    bind_fallback_bones = []

    try:
        for frame_number in exported_frames:
            scene.frame_set(frame_number)
            bpy.context.view_layer.update()
            patch_package = build_palette_export_patch(proxy_armature)
            current_used_slots = tuple(sorted(set(int(slot_id) for slot_id in patch_package["used_slot_ids"])))
            if used_slots is None:
                used_slots = current_used_slots
                if not used_slots:
                    raise ValueError(
                        f"No exportable slots fit inside the configured part window for {proxy_armature.name}"
                    )
                exported_bone_count = len(used_slots)
                slot_count = max(used_slots) + 1
            elif current_used_slots != used_slots:
                raise ValueError(
                    f"Exportable slot set changed at frame {frame_number}; refresh bind or export settings first"
                )

            frame_rows.extend(build_dense_frame_rows_from_patch(patch_package, slot_count))
            overflow_bones.extend(patch_package["metadata"]["overflow_bones"])
            bind_fallback_bones.extend(patch_package["metadata"]["bind_fallback_bones"])
    finally:
        scene.frame_set(original_frame)
        bpy.context.view_layer.update()

    flat_float_values = array("f")
    for row in frame_rows:
        flat_float_values.extend(row)
    with open(rows_path, "wb") as binary_file:
        flat_float_values.tofile(binary_file)

    meta_rows = build_animation_meta_uint4_rows(
        proxy_armature,
        frame_count=len(exported_frames),
        slot_count=slot_count,
    )
    write_animation_meta_rows(meta_path, meta_rows)

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
        "used_slots": list(used_slots or ()),
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
    if write_metadata:
        with open(debug_metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, indent=2, ensure_ascii=False)
    else:
        debug_metadata_path = ""

    return AnimationExportResult(
        armature_name=proxy_armature.name,
        rows_path=rows_path,
        meta_path=meta_path,
        frame_count=len(exported_frames),
        slot_count=slot_count,
        exported_bones=exported_bone_count,
        metadata=metadata,
        debug_metadata_path=debug_metadata_path,
    )
