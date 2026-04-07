"""Sparse multi-frame animation export for one proxy armature per file."""

import json
import os
from array import array

import bpy

from .export import build_palette_export_patch
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


def build_sparse_frame_rows_from_patch(patch_package):
    """Extract compact rows for one frame in slot order."""
    frame_rows = []
    current_segment = patch_package["current_segment"]
    for slot_id in sorted(set(int(slot_id) for slot_id in patch_package["used_slot_ids"])):
        row_base = 3 + slot_id * 3
        frame_rows.extend(current_segment[row_base:row_base + 3])
    return frame_rows


def resolve_animation_export_paths(output_directory, armature_name):
    """Build binary and metadata paths for one proxy armature animation clip."""
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    safe_name = armature_name.replace(os.sep, "_").replace("/", "_")
    binary_path = os.path.join(directory_path, f"{safe_name}_clip.bin")
    metadata_path = os.path.join(directory_path, f"{safe_name}_clip.json")
    return directory_path, binary_path, metadata_path


def export_animation_clip_for_proxy_armature(
    proxy_armature,
    output_directory,
    frame_start,
    frame_end,
    frame_step,
    fps,
    write_metadata=True,
):
    """Export one sparse animation clip for one proxy armature."""
    scene = bpy.context.scene
    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    if not exported_frames:
        raise ValueError("No animation frames to export")

    directory_path, binary_path, metadata_path = resolve_animation_export_paths(output_directory, proxy_armature.name)
    original_frame = scene.frame_current

    slot_ids = None
    frame_rows = []
    exported_bone_count = 0
    overflow_bones = []
    bind_fallback_bones = []

    try:
        for frame_number in exported_frames:
            scene.frame_set(frame_number)
            bpy.context.view_layer.update()
            patch_package = build_palette_export_patch(proxy_armature)
            current_slot_ids = tuple(sorted(set(int(slot_id) for slot_id in patch_package["used_slot_ids"])))
            if slot_ids is None:
                slot_ids = current_slot_ids
                exported_bone_count = len(slot_ids)
            elif current_slot_ids != slot_ids:
                raise ValueError(
                    f"Exportable slot set changed at frame {frame_number}; refresh bind or export settings first"
                )

            frame_rows.extend(build_sparse_frame_rows_from_patch(patch_package))
            overflow_bones.extend(patch_package["metadata"]["overflow_bones"])
            bind_fallback_bones.extend(patch_package["metadata"]["bind_fallback_bones"])
    finally:
        scene.frame_set(original_frame)
        bpy.context.view_layer.update()

    flat_float_values = array("f")
    for row in frame_rows:
        flat_float_values.extend(row)
    with open(binary_path, "wb") as binary_file:
        flat_float_values.tofile(binary_file)

    metadata = {
        "format": "vs_t0_animation_clip_v1",
        "armature_name": proxy_armature.name,
        "source_mesh": getattr(proxy_armature, "bi_source_mesh_name", ""),
        "part_id": int(getattr(proxy_armature, "bi_part_id", -1)),
        "fps": float(fps),
        "frame_start": exported_frames[0],
        "frame_end": exported_frames[-1],
        "frame_step": int(frame_step),
        "frame_count": len(exported_frames),
        "frame_numbers": list(exported_frames),
        "bone_count": exported_bone_count,
        "rows_per_bone": 3,
        "rows_per_frame": exported_bone_count * 3,
        "slot_ids": list(slot_ids or ()),
        "coordinate_correction": "MATRIX_RX_90_DEG",
        "overflow_bones": overflow_bones,
        "bind_fallback_bones": bind_fallback_bones,
    }
    if write_metadata:
        with open(metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, indent=2, ensure_ascii=False)

    return AnimationExportResult(
        armature_name=proxy_armature.name,
        binary_path=binary_path,
        metadata_path=metadata_path,
        frame_count=len(exported_frames),
        exported_bones=exported_bone_count,
        metadata=metadata,
    )
