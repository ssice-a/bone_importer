"""Per-DrawPart Bone Payload exporter for the RX runtime manifest route."""

from __future__ import annotations

from array import array
from contextlib import contextmanager
import hashlib
import json
import os
from time import perf_counter

import bpy
import numpy as np

from ..constants import RESERVED_PALETTE_ROWS
from .bone_sample_bank import build_bone_sample_plan, resolve_sample_cache_directory, select_payload_samples
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
BONE_SAMPLE_CACHE_VERSION = "rx_bone_sample_cache_v3"


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
    palette_row_count = RESERVED_PALETTE_ROWS + ((max(normalized_slot_ids) + 1) * 3 if normalized_slot_ids else 0)
    previous_palette_base = palette_row_count
    return [
        (
            len(normalized_slot_ids),
            max(int(sample_count), 1),
            int(RESERVED_PALETTE_ROWS),
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


def _build_bone_payload_metadata(
    draw_part,
    bindings,
    slot_ids,
    exported_frames,
    frame_step,
    fps,
    clip_name,
    clip_id,
    bone_static_path,
    bone_anim_path,
    bone_bind_path,
    correction_mode,
):
    return {
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
        "slot_bindings": serialize_slot_bindings(tuple(bindings)),
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
        "reserved_rows": int(RESERVED_PALETTE_ROWS),
        "palette_row_count": int(RESERVED_PALETTE_ROWS + ((max(slot_ids) + 1) * 3 if slot_ids else 0)),
        "previous_palette_base": int(RESERVED_PALETTE_ROWS + ((max(slot_ids) + 1) * 3 if slot_ids else 0)),
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

    metadata = _build_bone_payload_metadata(
        draw_part,
        tuple(binding for binding, _pose_bone in binding_pose_bones),
        slot_ids,
        exported_frames,
        frame_step,
        fps,
        clip_name,
        clip_id,
        bone_static_path,
        bone_anim_path,
        bone_bind_path,
        correction_mode,
    )
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


def _binding_sample_key(binding):
    return (id(binding.source_armature), binding.source_armature.name, binding.source_bone)


def _rounded_float_tuple(values, precision=8):
    return tuple(round(float(value), precision) for value in values)


def _matrix_payload(matrix):
    return tuple(_rounded_float_tuple(row) for row in matrix)


def _action_fingerprint(action):
    if action is None:
        return None
    fcurve_rows = []
    for fcurve in sorted(action.fcurves, key=lambda item: (item.data_path, item.array_index)):
        keyframes = []
        for keyframe in fcurve.keyframe_points:
            keyframes.append(
                (
                    round(float(keyframe.co.x), 8),
                    round(float(keyframe.co.y), 8),
                    str(keyframe.interpolation),
                )
            )
        fcurve_rows.append(
            {
                "data_path": str(fcurve.data_path),
                "array_index": int(fcurve.array_index),
                "keyframes": keyframes,
            }
        )
    return {
        "name": action.name,
        "fcurves": fcurve_rows,
    }


def _object_action_fingerprint(obj):
    animation_data = getattr(obj, "animation_data", None)
    return _action_fingerprint(getattr(animation_data, "action", None)) if animation_data else None


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw_value = str(os.environ.get(name, "") or "").strip()
    if not raw_value:
        return int(default)
    try:
        return int(raw_value)
    except ValueError:
        return int(default)


def _iter_driver_target_objects(id_data):
    animation_data = getattr(id_data, "animation_data", None)
    for driver in getattr(animation_data, "drivers", ()) or ():
        for variable in getattr(getattr(driver, "driver", None), "variables", ()) or ():
            for target in getattr(variable, "targets", ()) or ():
                target_id = getattr(target, "id", None)
                if isinstance(target_id, bpy.types.Object):
                    yield target_id


def _iter_constraint_target_objects(owner):
    for constraint in getattr(owner, "constraints", ()) or ():
        target = getattr(constraint, "target", None)
        if isinstance(target, bpy.types.Object):
            yield target


def _target_is_static_world_pin(target) -> bool:
    if target is None:
        return False
    if getattr(target, "parent", None) is not None:
        return False
    animation_data = getattr(target, "animation_data", None)
    if animation_data is not None:
        if getattr(animation_data, "action", None) is not None:
            return False
        if getattr(animation_data, "drivers", None):
            return False
    if getattr(target, "constraints", None):
        return False
    return True


def _is_static_bonex_driver_constraint(constraint) -> bool:
    if str(getattr(constraint, "type", "") or "") != "COPY_TRANSFORMS":
        return False
    constraint_name = str(getattr(constraint, "name", "") or "")
    target = getattr(constraint, "target", None)
    target_name = str(getattr(target, "name", "") or "")
    if constraint_name != "bonex_driver" and not target_name.startswith("bonex_driver_"):
        return False
    return _target_is_static_world_pin(target)


def _iter_static_bonex_driver_constraints(sample_groups):
    seen_constraints = set()
    for group in sample_groups.values():
        for _sample_key, source_armature, source_bone in group["sample_entries_by_key"].values():
            pose_bone = source_armature.pose.bones.get(source_bone)
            if pose_bone is None:
                continue
            for constraint in getattr(pose_bone, "constraints", ()) or ():
                constraint_id = id(constraint)
                if constraint_id in seen_constraints:
                    continue
                seen_constraints.add(constraint_id)
                if _is_static_bonex_driver_constraint(constraint):
                    yield constraint


@contextmanager
def _temporary_static_bonex_driver_mute(context, sample_groups):
    """Let proxy child bones inherit animation instead of static imported pins."""
    static_constraints = tuple(_iter_static_bonex_driver_constraints(sample_groups))
    changed = []
    start = perf_counter()
    info = {
        "enabled": False,
        "static_constraint_count": len(static_constraints),
        "muted_constraint_count": 0,
        "seconds": 0.0,
        "skip_reason": "disabled",
    }
    if not _env_flag("RX_BONE_SAMPLE_MUTE_STATIC_BONEX"):
        yield info
        return

    info["enabled"] = True
    info["skip_reason"] = "active"
    try:
        for constraint in static_constraints:
            changed.append((constraint, bool(getattr(constraint, "mute", False))))
            constraint.mute = True
        info["muted_constraint_count"] = len(changed)
        info["seconds"] = perf_counter() - start
        if changed:
            context.view_layer.update()
        yield info
    finally:
        restore_start = perf_counter()
        for constraint, previous_mute in changed:
            constraint.mute = previous_mute
        if changed:
            context.view_layer.update()
        info["restore_seconds"] = perf_counter() - restore_start


def _collect_bone_sampling_required_objects(sample_groups):
    required = set()
    source_armatures = {}
    for group in sample_groups.values():
        for _sample_key, source_armature, _source_bone in group["sample_entries_by_key"].values():
            source_armatures[source_armature.name] = source_armature
    for source_armature in source_armatures.values():
        obj = source_armature
        while obj is not None:
            required.add(obj)
            obj = getattr(obj, "parent", None)
        for target in _iter_constraint_target_objects(source_armature):
            required.add(target)
        for target in _iter_driver_target_objects(source_armature):
            required.add(target)
        for target in _iter_driver_target_objects(getattr(source_armature, "data", None)):
            required.add(target)
        for pose_bone in getattr(source_armature.pose, "bones", ()) or ():
            for target in _iter_constraint_target_objects(pose_bone):
                required.add(target)
            for target in _iter_driver_target_objects(pose_bone):
                required.add(target)
    return required


@contextmanager
def _temporary_mesh_sampling_isolation(context, sample_groups, sample_count):
    """Hide non-essential meshes while sampling bones so frame_set does less depsgraph work."""
    min_sample_count = max(_env_int("RX_BONE_SAMPLE_HIDE_MESHES_MIN_SAMPLES", 16), 1)
    info = {
        "enabled": False,
        "sample_count": int(sample_count),
        "min_sample_count": int(min_sample_count),
        "hidden_mesh_count": 0,
        "required_object_count": 0,
        "seconds": 0.0,
    }
    if not _env_flag("RX_BONE_SAMPLE_HIDE_MESHES"):
        info["skip_reason"] = "disabled"
        yield info
        return
    if int(sample_count) < min_sample_count:
        info["skip_reason"] = "sample_count_below_threshold"
        yield info
        return

    start = perf_counter()
    required_objects = _collect_bone_sampling_required_objects(sample_groups)
    scene_objects = tuple(getattr(getattr(context, "scene", None), "objects", ()) or ())
    changed = []
    try:
        for obj in scene_objects:
            if getattr(obj, "type", "") != "MESH" or obj in required_objects:
                continue
            changed.append((obj, bool(getattr(obj, "hide_viewport", False))))
            obj.hide_viewport = True
        info.update(
            {
                "enabled": True,
                "hidden_mesh_count": len(changed),
                "required_object_count": len(required_objects),
                "seconds": perf_counter() - start,
                "skip_reason": "active",
            }
        )
        yield info
    finally:
        restore_start = perf_counter()
        for obj, previous_hide_viewport in changed:
            obj.hide_viewport = previous_hide_viewport
        info["restore_seconds"] = perf_counter() - restore_start


def _constraint_payload(constraint, deep=False):
    target = getattr(constraint, "target", None)
    payload = {
        "name": constraint.name,
        "type": constraint.type,
        "mute": bool(getattr(constraint, "mute", False)),
        "influence": round(float(getattr(constraint, "influence", 0.0)), 8),
        "target": target.name if target is not None else "",
        "subtarget": str(getattr(constraint, "subtarget", "") or ""),
        "owner_space": str(getattr(constraint, "owner_space", "") or ""),
        "target_space": str(getattr(constraint, "target_space", "") or ""),
    }
    if deep:
        payload["target_matrix_world"] = _matrix_payload(target.matrix_world) if target is not None else ()
        payload["target_action"] = _object_action_fingerprint(target) if target is not None else None
    return payload


def _armature_fingerprint(armature, deep=False):
    """Build an opt-in cache fingerprint without making cache lookup slower than sampling."""
    pose_rows = []
    for pose_bone in armature.pose.bones:
        pose_rows.append(
            {
                "name": pose_bone.name,
                "parent": pose_bone.parent.name if pose_bone.parent else "",
                "constraints": [_constraint_payload(constraint, deep=deep) for constraint in pose_bone.constraints],
            }
        )
    return {
        "name": armature.name,
        "data_name": armature.data.name,
        "matrix_world": _matrix_payload(armature.matrix_world),
        "action": _object_action_fingerprint(armature),
        "constraint_fingerprint": "deep" if deep else "shallow",
        "pose_bones": pose_rows,
    }


def _blend_file_fingerprint():
    blend_path = str(bpy.data.filepath or "")
    if not blend_path or not os.path.exists(blend_path):
        return {"path": blend_path, "mtime_ns": 0, "size": 0}
    stat = os.stat(blend_path)
    return {
        "path": os.path.abspath(blend_path),
        "mtime_ns": int(stat.st_mtime_ns),
        "size": int(stat.st_size),
    }


def _build_sample_cache_key(context, exported_frames, sample_entries, correction_matrix):
    deep_fingerprint = _env_flag("RX_BONE_SAMPLE_CACHE_DEEP")
    armatures = {}
    for _key, source_armature, _source_bone in sample_entries:
        armatures[source_armature.name] = source_armature
    correction_payload = None
    if correction_matrix is not None:
        correction_payload = _matrix_payload(correction_matrix)
    payload = {
        "format": BONE_SAMPLE_CACHE_VERSION,
        "blend": _blend_file_fingerprint(),
        "scene": getattr(context.scene, "name", ""),
        "frames": list(int(frame) for frame in exported_frames),
        "correction_matrix": correction_payload,
        "sample_entries": [
            (source_armature.name, source_bone)
            for _key, source_armature, source_bone in sample_entries
        ],
        "armatures": [
            _armature_fingerprint(armatures[name], deep=deep_fingerprint)
            for name in sorted(armatures)
        ],
        "fingerprint_mode": "deep" if deep_fingerprint else "shallow",
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def _resolve_sample_cache_dir(output_directory: str) -> str:
    return resolve_sample_cache_directory(
        output_directory=bpy.path.abspath(output_directory or "//"),
        explicit_cache_dir=os.environ.get("RX_BONE_SAMPLE_CACHE_DIR", ""),
        use_cache_flag=os.environ.get("RX_EXPORT_USE_BONE_CACHE", ""),
        path_resolver=bpy.path.abspath,
    )


def _load_sample_cache(cache_dir: str, cache_hash: str, expected_shape: tuple[int, int, int]):
    if not cache_dir:
        return None, 0.0
    cache_path = os.path.join(cache_dir, f"{cache_hash}.npy")
    if not os.path.exists(cache_path):
        return None, 0.0
    start = perf_counter()
    samples = np.load(cache_path, allow_pickle=False)
    load_seconds = perf_counter() - start
    if tuple(samples.shape) != tuple(expected_shape):
        return None, load_seconds
    if str(samples.dtype) != "float32":
        return None, load_seconds
    return np.asarray(samples, dtype="<f4"), load_seconds


def _write_sample_cache(cache_dir: str, cache_hash: str, cache_payload: dict, samples):
    if not cache_dir:
        return "", 0.0
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{cache_hash}.npy")
    metadata_path = os.path.join(cache_dir, f"{cache_hash}.json")
    start = perf_counter()
    np.save(cache_path, np.asarray(samples, dtype="<f4"), allow_pickle=False)
    write_json_file(metadata_path, cache_payload)
    return cache_path, perf_counter() - start


def _sample_pose_tq_group(context, exported_frames, sample_entries, correction_matrix):
    samples = np.empty((len(exported_frames), len(sample_entries), TQ_FLOATS_PER_BONE), dtype="<f4")
    scene = context.scene
    timing = {
        "sample_count": len(exported_frames),
        "unique_bones": len(sample_entries),
        "frame_set_seconds": 0.0,
        "pose_sample_seconds": 0.0,
    }
    total_start = perf_counter()
    for frame_index, frame_number in enumerate(exported_frames):
        frame_set_start = perf_counter()
        scene.frame_set(frame_number)
        timing["frame_set_seconds"] += perf_counter() - frame_set_start
        pose_sample_start = perf_counter()
        for bone_index, (_key, source_armature, source_bone) in enumerate(sample_entries):
            pose_bone = source_armature.pose.bones.get(source_bone)
            if pose_bone is None:
                raise ValueError(f"Source bone vanished: {source_armature.name}/{source_bone}")
            pose_matrix = _pose_matrix_for_export(pose_bone, correction_matrix)
            translation, rotation, _scale = pose_matrix.decompose()
            rotation.normalize()
            samples[frame_index, bone_index, 0] = translation.x
            samples[frame_index, bone_index, 1] = translation.y
            samples[frame_index, bone_index, 2] = translation.z
            samples[frame_index, bone_index, 3] = 1.0
            samples[frame_index, bone_index, 4] = rotation.x
            samples[frame_index, bone_index, 5] = rotation.y
            samples[frame_index, bone_index, 6] = rotation.z
            samples[frame_index, bone_index, 7] = rotation.w
        timing["pose_sample_seconds"] += perf_counter() - pose_sample_start
    timing["total_seconds"] = perf_counter() - total_start
    timing["sample_bone_pairs"] = len(exported_frames) * len(sample_entries)
    return samples, timing


def _write_bone_anim_from_sample_cache(path: str, sample_cache, sample_indices):
    selected_samples = select_payload_samples(sample_cache, sample_indices)
    with open(path, "wb") as binary_file:
        selected_samples.tofile(binary_file)


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
    prepared_payloads = []
    timings = {}
    prepare_start = perf_counter()
    for draw_part in normalized_draw_parts:
        if not bool(getattr(draw_part, "bone_enabled", True)):
            continue
        try:
            bindings = resolve_bone_slot_bindings(draw_part, require_complete=True)
            if not bindings:
                continue
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
            prepared_payloads.append(
                {
                    "draw_part": draw_part,
                    "bindings": tuple(bindings),
                    "binding_pose_bones": binding_pose_bones,
                    "slot_ids": slot_ids,
                    "correction_mode": correction_mode,
                    "correction_matrix": correction_matrix,
                    "bone_static_path": bone_static_path,
                    "bone_anim_path": bone_anim_path,
                    "bone_bind_path": bone_bind_path,
                    "bone_metadata_path": bone_metadata_path,
                }
            )
        except Exception as exc:
            failures.append(f"{draw_part.draw_key}: {exc}")
            continue
    timings["prepare_payloads_seconds"] = perf_counter() - prepare_start

    sample_group_start = perf_counter()
    sample_plan = build_bone_sample_plan(prepared_payloads, _binding_sample_key)
    sample_groups = {
        group_key: {
            "correction_matrix": group.correction_matrix,
            "sample_entries_by_key": {entry[0]: entry for entry in group.sample_entries},
        }
        for group_key, group in sample_plan.groups.items()
    }
    timings["build_sample_groups_seconds"] = perf_counter() - sample_group_start

    original_frame = context.scene.frame_current
    sample_caches = {}
    sample_failures = {}
    sample_group_timings = []
    sample_isolation = {}
    static_bonex_driver_mute = {}
    sample_total_start = perf_counter()
    sample_cache_dir = _resolve_sample_cache_dir(output_directory)
    with _temporary_mesh_sampling_isolation(context, sample_groups, len(exported_frames)) as sample_isolation:
        with _temporary_static_bonex_driver_mute(context, sample_groups) as static_bonex_driver_mute:
            try:
                for group_key, group in sample_groups.items():
                    group_plan = sample_plan.groups[group_key]
                    sample_entries = group_plan.sample_entries
                    try:
                        expected_shape = (len(exported_frames), len(sample_entries), TQ_FLOATS_PER_BONE)
                        cache_hash = ""
                        cache_payload = {"fingerprint_mode": "off"}
                        cache_key_seconds = 0.0
                        cache_load_seconds = 0.0
                        cache_path = ""
                        samples = None
                        if sample_cache_dir:
                            cache_key_start = perf_counter()
                            cache_hash, cache_payload = _build_sample_cache_key(
                                context,
                                exported_frames,
                                sample_entries,
                                group["correction_matrix"],
                            )
                            cache_key_seconds = perf_counter() - cache_key_start
                            samples, cache_load_seconds = _load_sample_cache(
                                sample_cache_dir,
                                cache_hash,
                                expected_shape,
                            )
                            cache_path = os.path.join(sample_cache_dir, f"{cache_hash}.npy")
                        if samples is None:
                            samples, sample_timing = _sample_pose_tq_group(
                                context,
                                exported_frames,
                                sample_entries,
                                group["correction_matrix"],
                            )
                            cache_path, cache_write_seconds = _write_sample_cache(
                                sample_cache_dir,
                                cache_hash,
                                cache_payload,
                                samples,
                            )
                            sample_timing.update(
                                {
                                    "cache_enabled": bool(sample_cache_dir),
                                    "cache_hit": False,
                                    "cache_hash": cache_hash,
                                    "cache_path": cache_path,
                                    "cache_key_seconds": cache_key_seconds,
                                    "cache_fingerprint_mode": cache_payload.get("fingerprint_mode", "shallow"),
                                    "cache_load_seconds": cache_load_seconds,
                                    "cache_write_seconds": cache_write_seconds,
                                }
                            )
                        else:
                            sample_timing = {
                                "sample_count": len(exported_frames),
                                "unique_bones": len(sample_entries),
                                "frame_set_seconds": 0.0,
                                "pose_sample_seconds": 0.0,
                                "total_seconds": cache_load_seconds,
                                "sample_bone_pairs": len(exported_frames) * len(sample_entries),
                                "cache_enabled": True,
                                "cache_hit": True,
                                "cache_hash": cache_hash,
                                "cache_path": cache_path,
                                "cache_key_seconds": cache_key_seconds,
                                "cache_fingerprint_mode": cache_payload.get("fingerprint_mode", "shallow"),
                                "cache_load_seconds": cache_load_seconds,
                                "cache_write_seconds": 0.0,
                            }
                        sample_caches[group_key] = {
                            "index_by_key": group_plan.index_by_key,
                            "samples": samples,
                            "timing": sample_timing,
                        }
                        sample_group_timings.append({"sample_group": group_key, **sample_timing})
                    except Exception as exc:
                        sample_failures[group_key] = str(exc)
            finally:
                timings["sample_total_seconds"] = perf_counter() - sample_total_start
                restore_start = perf_counter()
                context.scene.frame_set(original_frame)
                timings["restore_frame_seconds"] = perf_counter() - restore_start

    write_payloads_start = perf_counter()
    payload_write_timings = []
    for payload in prepared_payloads:
        draw_part = payload["draw_part"]
        try:
            group_key = str(payload["correction_mode"])
            if group_key in sample_failures:
                failures.append(f"{draw_part.draw_key}: {sample_failures[group_key]}")
                continue
            sample_cache = sample_caches[group_key]
            sample_indices = sample_plan.payloads[draw_part.draw_key].sample_indices
            payload_timing = {
                "draw_key": draw_part.draw_key,
                "bone_count": len(payload["bindings"]),
            }
            payload_start = perf_counter()
            _write_bone_anim_from_sample_cache(
                payload["bone_anim_path"],
                sample_cache["samples"],
                sample_indices,
            )
            payload_timing["anim_write_seconds"] = perf_counter() - payload_start
            bind_start = perf_counter()
            _write_bone_bind_buffer(payload["bone_bind_path"], payload["binding_pose_bones"])
            payload_timing["bind_write_seconds"] = perf_counter() - bind_start
            static_start = perf_counter()
            write_uint4_buffer_rows(
                payload["bone_static_path"],
                build_bone_static_uint4_rows(payload["slot_ids"], len(exported_frames)),
            )
            payload_timing["static_write_seconds"] = perf_counter() - static_start
            metadata = _build_bone_payload_metadata(
                draw_part,
                payload["bindings"],
                payload["slot_ids"],
                exported_frames,
                frame_step,
                fps,
                clip_name,
                clip_id,
                payload["bone_static_path"],
                payload["bone_anim_path"],
                payload["bone_bind_path"],
                payload["correction_mode"],
            )
            metadata["sampling_cache"] = {
                "mode": "shared_pose_tq_by_correction_mode",
                "sample_group": group_key,
                "unique_group_bones": int(sample_cache["samples"].shape[1]),
            }
            if write_metadata:
                metadata_start = perf_counter()
                write_json_file(payload["bone_metadata_path"], metadata)
                payload_timing["metadata_write_seconds"] = perf_counter() - metadata_start
            else:
                payload["bone_metadata_path"] = ""
                payload_timing["metadata_write_seconds"] = 0.0
            payload_timing["total_write_seconds"] = sum(
                float(payload_timing.get(key, 0.0))
                for key in (
                    "anim_write_seconds",
                    "bind_write_seconds",
                    "static_write_seconds",
                    "metadata_write_seconds",
                )
            )
            payload_write_timings.append(payload_timing)
            results.append(
                AnimationExportResult(
                    armature_name=", ".join(metadata["source_armatures"]),
                    tqs_path=payload["bone_anim_path"],
                    bind_path=payload["bone_bind_path"],
                    static_clip_path=payload["bone_static_path"],
                    frame_count=len(exported_frames),
                    bone_count=len(payload["bindings"]),
                    metadata=metadata,
                    debug_metadata_path=payload["bone_metadata_path"],
                )
            )
        except Exception as exc:
            failures.append(f"{draw_part.draw_key}: {exc}")
    timings["write_payloads_seconds"] = perf_counter() - write_payloads_start

    shared_clip_start = perf_counter()
    timeline_static_path, master_playback_path, clip_metadata_path, clip_metadata = write_shared_clip_buffers(
        output_directory=output_directory,
        clip_name=clip_name,
        clip_id=clip_id,
        exported_frames=exported_frames,
        fps=fps,
        ticks_per_sample=1,
        write_metadata=write_metadata,
    )
    timings["shared_clip_seconds"] = perf_counter() - shared_clip_start
    elapsed = perf_counter() - start
    timings["total_seconds"] = elapsed
    sample_group_bones = [
        len(group["sample_entries_by_key"])
        for group in sample_groups.values()
    ]
    performance = {
        "format": "rx_bone_payload_perf_v1",
        "draw_part_count": len(normalized_draw_parts),
        "prepared_payload_count": len(prepared_payloads),
        "exported_payload_count": len(results),
        "sample_count": len(exported_frames),
        "sample_group_count": len(sample_groups),
        "sample_cache_dir": sample_cache_dir,
        "sample_cache_enabled": bool(sample_cache_dir),
        "sample_isolation": dict(sample_isolation or {}),
        "static_bonex_driver_mute": dict(static_bonex_driver_mute or {}),
        "unique_sampled_bones_by_group": sample_group_bones,
        "estimated_sample_bone_pairs": sum(len(exported_frames) * count for count in sample_group_bones),
        "total_payload_bone_slots": sum(len(payload["bindings"]) for payload in prepared_payloads),
        "timings_seconds": timings,
        "sample_groups": sample_group_timings,
        "payload_writes": payload_write_timings,
    }
    return {
        "results": tuple(results),
        "failures": tuple(failures),
        "timeline_static_path": timeline_static_path,
        "master_playback_path": master_playback_path,
        "clip_metadata_path": clip_metadata_path,
        "clip_metadata": clip_metadata,
        "elapsed_seconds": elapsed,
        "sampled_frames": len(exported_frames),
        "performance": performance,
    }
