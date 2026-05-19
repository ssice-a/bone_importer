"""Per-DrawPart Bone Payload exporter for the RX runtime manifest route."""

from __future__ import annotations

from array import array
import os
from time import perf_counter

import bpy
import numpy as np

from .animation_export import (
    build_master_playback_uint4_rows,
    build_timeline_static_uint4_rows,
    normalize_animation_frame_range,
    normalize_clip_name,
    resolve_animation_loop_settings,
    sanitize_export_name,
    write_json_file,
    write_uint4_buffer_rows,
)
from .models import AnimationExportResult
from .slot_contract import resolve_bone_slot_bindings, serialize_slot_bindings
from .transform import BUFFER_CORRECTION_NONE, build_extra_blender_correction_matrix, get_proxy_buffer_correction_mode
from .layout import build_matrix_from_flat_values, convert_matrix_to_palette_rows


BONE_PAYLOAD_FLAGS_NONE = 0
TQ_FLOATS_PER_BONE = 8


def resolve_bone_payload_paths(output_directory: str, draw_key: str):
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    safe_draw_key = sanitize_export_name(draw_key, "draw_part")
    bone_static_path = os.path.join(directory_path, f"{safe_draw_key}_bone_static.buf")
    bone_anim_path = os.path.join(directory_path, f"{safe_draw_key}_bone_anim.buf")
    bone_bind_path = os.path.join(directory_path, f"{safe_draw_key}_bone_bind.buf")
    bone_metadata_path = os.path.join(directory_path, f"{safe_draw_key}_bone.json")
    return directory_path, bone_static_path, bone_anim_path, bone_bind_path, bone_metadata_path


def _pack_slot_ids_uint4(slot_ids: tuple[int, ...]) -> list[tuple[int, int, int, int]]:
    rows = []
    for start in range(0, len(slot_ids), 4):
        chunk = list(slot_ids[start:start + 4])
        while len(chunk) < 4:
            chunk.append(0xFFFFFFFF)
        rows.append(tuple(int(value) for value in chunk))
    return rows


def build_bone_static_uint4_rows(slot_ids: tuple[int, ...], sample_count: int):
    """Build the fixed Bone Payload static table."""
    normalized_slot_ids = tuple(sorted(int(slot_id) for slot_id in slot_ids))
    slot_rows = _pack_slot_ids_uint4(normalized_slot_ids)
    palette_row_count = (max(normalized_slot_ids) + 1) * 3 if normalized_slot_ids else 0
    previous_palette_base = palette_row_count
    return [
        (
            len(normalized_slot_ids),
            max(int(sample_count), 1),
            0,
            len(slot_rows),
        ),
        (
            int(palette_row_count),
            int(previous_palette_base),
            int(BONE_PAYLOAD_FLAGS_NONE),
            0,
        ),
        *slot_rows,
    ]


def _resolve_bind_matrix(pose_bone):
    if bool(getattr(pose_bone, "bi_bind_valid", False)):
        try:
            bind_matrix = build_matrix_from_flat_values(list(getattr(pose_bone, "bi_bind_matrix", [])))
            bind_matrix.inverted()
            return bind_matrix
        except Exception:
            pass
    return pose_bone.bone.matrix_local.copy()


def _iter_binding_pose_bones(bindings):
    for binding in bindings:
        pose_bone = binding.source_armature.pose.bones.get(binding.source_bone)
        if pose_bone is None:
            raise ValueError(f"Source bone vanished: {binding.source_armature.name}/{binding.source_bone}")
        yield binding, pose_bone


def _binding_correction_matrix(draw_part):
    correction_mode = get_proxy_buffer_correction_mode(draw_part)
    if correction_mode == BUFFER_CORRECTION_NONE:
        return correction_mode, None
    return correction_mode, build_extra_blender_correction_matrix(correction_mode)


def _pose_matrix_for_export(pose_bone, correction_matrix):
    pose_matrix = pose_bone.matrix.copy()
    if correction_matrix is not None:
        pose_matrix = correction_matrix @ pose_matrix
    return pose_matrix


def _write_bone_anim_frame(binary_file, binding_pose_bones, correction_matrix, frame_buffer):
    buffer_index = 0
    for _binding, pose_bone in binding_pose_bones:
        pose_matrix = _pose_matrix_for_export(pose_bone, correction_matrix)
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
        buffer_index += TQ_FLOATS_PER_BONE
    frame_buffer.tofile(binary_file)


def _write_bone_bind_buffer(path: str, binding_pose_bones):
    flat_values = array("f")
    for _binding, pose_bone in binding_pose_bones:
        bind_inverse = _resolve_bind_matrix(pose_bone).inverted()
        for row in convert_matrix_to_palette_rows(bind_inverse):
            flat_values.extend(row)
    with open(path, "wb") as bind_file:
        flat_values.tofile(bind_file)


def write_shared_clip_buffers(output_directory, clip_name, clip_id, exported_frames, fps, ticks_per_sample=1, write_metadata=True):
    """Write Clip-level timeline/master playback buffers."""
    normalized_clip_name = normalize_clip_name(clip_name)
    safe_clip_name = sanitize_export_name(normalized_clip_name, "rxanimin")
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    timeline_static_path = os.path.join(directory_path, f"{safe_clip_name}_timeline_static.buf")
    master_playback_path = os.path.join(directory_path, f"{safe_clip_name}_master_playback.buf")
    clip_metadata_path = os.path.join(directory_path, f"{safe_clip_name}_clip.json")

    loop_settings = resolve_animation_loop_settings(exported_frames, -1, -1)
    timeline_rows = build_timeline_static_uint4_rows(
        frame_count=len(exported_frames),
        fps=fps,
        presents_per_step=ticks_per_sample,
        loop_start=loop_settings["resolved_loop_start_sample"],
        loop_end=loop_settings["resolved_loop_end_sample"],
    )
    master_rows = build_master_playback_uint4_rows(
        frame_count=len(exported_frames),
        presents_per_step=ticks_per_sample,
        loop_start=loop_settings["resolved_loop_start_sample"],
        loop_end=loop_settings["resolved_loop_end_sample"],
    )
    write_uint4_buffer_rows(timeline_static_path, timeline_rows)
    write_uint4_buffer_rows(master_playback_path, master_rows)

    metadata = {
        "format": "rx_clip_v2",
        "clip_name": normalized_clip_name,
        "clip_id": int(clip_id),
        "frame_start": int(exported_frames[0]),
        "frame_end": int(exported_frames[-1]),
        "frame_step": int(exported_frames[1] - exported_frames[0]) if len(exported_frames) > 1 else 1,
        "frame_count": len(exported_frames),
        "frame_numbers": list(exported_frames),
        "fps": float(fps),
        "default_ticks_per_sample": max(int(ticks_per_sample), 1),
        "default_loop_start_sample": loop_settings["resolved_loop_start_sample"],
        "default_loop_end_sample": loop_settings["resolved_loop_end_sample"],
        "timeline_static_path": timeline_static_path,
        "master_playback_path": master_playback_path,
    }
    if write_metadata:
        write_json_file(clip_metadata_path, metadata)
    return timeline_static_path, master_playback_path, clip_metadata_path if write_metadata else "", metadata


def export_bone_payload_for_draw_part(
    context,
    draw_part,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    write_metadata=True,
):
    """Export one DrawPart-local Bone Payload."""
    bindings = resolve_bone_slot_bindings(draw_part, require_complete=True)
    if not bindings:
        return None

    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    if not exported_frames:
        raise ValueError("No animation frames to export")

    (
        _directory_path,
        bone_static_path,
        bone_anim_path,
        bone_bind_path,
        bone_metadata_path,
    ) = resolve_bone_payload_paths(output_directory, draw_part.draw_key)

    binding_pose_bones = tuple(_iter_binding_pose_bones(bindings))
    slot_ids = tuple(binding.slot_id for binding, _pose_bone in binding_pose_bones)
    correction_mode, correction_matrix = _binding_correction_matrix(draw_part)
    frame_buffer = array("f", [0.0]) * (len(binding_pose_bones) * TQ_FLOATS_PER_BONE)

    scene = context.scene
    original_frame = scene.frame_current
    try:
        with open(bone_anim_path, "wb") as binary_file:
            for frame_number in exported_frames:
                scene.frame_set(frame_number)
                _write_bone_anim_frame(binary_file, binding_pose_bones, correction_matrix, frame_buffer)
    finally:
        scene.frame_set(original_frame)

    _write_bone_bind_buffer(bone_bind_path, binding_pose_bones)
    write_uint4_buffer_rows(bone_static_path, build_bone_static_uint4_rows(slot_ids, len(exported_frames)))

    metadata = {
        "format": "rx_bone_payload_v1",
        "clip_name": normalize_clip_name(clip_name),
        "clip_id": int(clip_id),
        "draw_key": draw_part.draw_key,
        "draw_object_name": draw_part.source_object.name,
        "hash": draw_part.hash,
        "match_index_count": int(draw_part.match_index_count),
        "first_index": int(draw_part.first_index),
        "match_priority": int(draw_part.match_priority),
        "skin_contract": draw_part.skin_contract,
        "source_armatures": sorted({binding.source_armature.name for binding in bindings}),
        "bone_count": len(bindings),
        "slot_ids": list(slot_ids),
        "slot_bindings": serialize_slot_bindings(tuple(binding for binding, _pose_bone in binding_pose_bones)),
        "frame_start": exported_frames[0],
        "frame_end": exported_frames[-1],
        "frame_step": int(frame_step),
        "frame_count": len(exported_frames),
        "frame_numbers": list(exported_frames),
        "fps": float(fps),
        "clip_fps": max(int(round(float(fps))), 1),
        "default_ticks_per_sample": 1,
        "default_presents_per_step": 1,
        "default_loop_start_sample": 0,
        "default_loop_end_sample": max(len(exported_frames) - 1, 0),
        "rows_per_bone": 2,
        "storage_layout": "[sample][bone][row]",
        "bone_static_path": bone_static_path,
        "bone_anim_path": bone_anim_path,
        "bone_bind_path": bone_bind_path,
        "tqs_path": bone_anim_path,
        "bind_path": bone_bind_path,
        "static_clip_path": bone_static_path,
        "buffer_correction_mode": correction_mode,
        "coordinate_space": "blender_armature_space",
        "coordinate_correction_runtime": "baked_in_export_tq",
    }
    if write_metadata:
        write_json_file(bone_metadata_path, metadata)
    else:
        bone_metadata_path = ""

    return AnimationExportResult(
        armature_name=", ".join(metadata["source_armatures"]),
        tqs_path=bone_anim_path,
        bind_path=bone_bind_path,
        static_clip_path=bone_static_path,
        frame_count=len(exported_frames),
        bone_count=len(bindings),
        metadata=metadata,
        debug_metadata_path=bone_metadata_path,
    )


def export_bone_payloads_for_draw_parts(
    context,
    draw_parts,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    write_metadata=True,
):
    """Export all enabled DrawPart Bone Payloads and shared Clip buffers."""
    start = perf_counter()
    normalized_draw_parts = tuple(draw_parts)
    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    results = []
    failures = []
    for draw_part in normalized_draw_parts:
        if not bool(getattr(draw_part, "bone_enabled", True)):
            continue
        try:
            result = export_bone_payload_for_draw_part(
                context=context,
                draw_part=draw_part,
                output_directory=output_directory,
                clip_name=clip_name,
                clip_id=clip_id,
                frame_start=frame_start,
                frame_end=frame_end,
                frame_step=frame_step,
                fps=fps,
                write_metadata=write_metadata,
            )
        except Exception as exc:
            failures.append(f"{draw_part.draw_key}: {exc}")
            continue
        if result is not None:
            results.append(result)

    timeline_static_path, master_playback_path, clip_metadata_path, clip_metadata = write_shared_clip_buffers(
        output_directory=output_directory,
        clip_name=clip_name,
        clip_id=clip_id,
        exported_frames=exported_frames,
        fps=fps,
        ticks_per_sample=1,
        write_metadata=write_metadata,
    )
    elapsed = perf_counter() - start
    return {
        "results": tuple(results),
        "failures": tuple(failures),
        "timeline_static_path": timeline_static_path,
        "master_playback_path": master_playback_path,
        "clip_metadata_path": clip_metadata_path,
        "clip_metadata": clip_metadata,
        "elapsed_seconds": elapsed,
        "sampled_frames": len(exported_frames),
    }
