"""Blender-free helpers for merging DrawPart-local Action payload tables."""

from __future__ import annotations

from dataclasses import dataclass
import os

import numpy as np


@dataclass(frozen=True)
class BoneAnimClipMerge:
    """Merged local bone animation rows and the static clip table inputs."""

    anim_rows: np.ndarray
    clip_sample_counts: tuple[int, ...]
    clip_loop_ranges: tuple[tuple[int, int], ...]
    clip_sample_row_bases: tuple[int, ...]


def _as_row_array(rows, dtype, label: str) -> np.ndarray:
    array = np.asarray(rows, dtype=dtype)
    if array.size == 0:
        return np.empty((0, 4), dtype=dtype)
    if array.ndim == 1:
        if array.size % 4 != 0:
            raise ValueError(f"{label} does not contain whole uint4/float4 rows")
        array = array.reshape((-1, 4))
    if array.ndim != 2 or array.shape[1] != 4:
        raise ValueError(f"{label} must have shape (n, 4)")
    return np.ascontiguousarray(array, dtype=dtype)


def read_row_buffer(path: str, dtype, label: str) -> np.ndarray:
    """Read a raw StructuredBuffer into contiguous four-component rows."""

    if not path or not os.path.exists(path):
        return np.empty((0, 4), dtype=dtype)
    flat_values = np.fromfile(path, dtype=dtype)
    return _as_row_array(flat_values, dtype, label)


def write_row_buffer(path: str, rows, dtype, label: str):
    """Write raw four-component rows without pulling Blender into payload code."""

    row_array = _as_row_array(rows, dtype, label)
    with open(path, "wb") as binary_file:
        row_array.tofile(binary_file)


def _extract_bone_clips(existing_static_rows, existing_anim_rows, bone_count: int):
    static_rows = _as_row_array(existing_static_rows, "<u4", "BoneStatic rows")
    anim_rows = _as_row_array(existing_anim_rows, "<f4", "BoneAnim rows")
    if len(static_rows) < 2:
        if len(static_rows) != 0:
            raise ValueError("BoneStatic rows do not contain both header rows")
        return (), (), ()

    static_bone_count = int(static_rows[0, 1])
    if static_bone_count != int(bone_count):
        raise ValueError(f"Bone clip merge bone count changed ({static_bone_count} != {int(bone_count)})")

    clip_count = max(int(static_rows[0, 0]), 1)
    clip_table_base = int(static_rows[1, 3])
    if clip_table_base < 2 or clip_table_base + clip_count > len(static_rows):
        raise ValueError("BoneStatic clip table is truncated")

    clips = []
    sample_counts = []
    loop_ranges = []
    rows_per_sample = max(int(bone_count), 0) * 2
    for clip_row in static_rows[clip_table_base:clip_table_base + clip_count]:
        sample_count = max(int(clip_row[0]), 1)
        sample_row_base = int(clip_row[1])
        row_count = sample_count * rows_per_sample
        sample_row_end = sample_row_base + row_count
        if sample_row_end > len(anim_rows):
            raise ValueError("BoneAnim rows are shorter than the BoneStatic clip table")
        clips.append(np.ascontiguousarray(anim_rows[sample_row_base:sample_row_end], dtype="<f4"))
        sample_counts.append(sample_count)
        loop_ranges.append((int(clip_row[2]), int(clip_row[3])))
    return tuple(clips), tuple(sample_counts), tuple(loop_ranges)


def merge_bone_anim_clip(
    existing_static_rows,
    existing_anim_rows,
    incoming_anim_rows,
    *,
    clip_index: int,
    bone_count: int,
    sample_count: int,
    loop_range: tuple[int, int] | None = None,
) -> BoneAnimClipMerge:
    """Append or replace one local Action in a Bone Payload."""

    safe_clip_index = int(clip_index)
    if safe_clip_index < 0:
        raise ValueError("Bone clip index must not be negative")
    safe_bone_count = max(int(bone_count), 0)
    safe_sample_count = max(int(sample_count), 1)
    incoming_rows = _as_row_array(incoming_anim_rows, "<f4", "Incoming BoneAnim rows")
    expected_rows = safe_sample_count * safe_bone_count * 2
    if len(incoming_rows) != expected_rows:
        raise ValueError(f"Incoming BoneAnim row count changed ({len(incoming_rows)} != {expected_rows})")

    clips, sample_counts, loop_ranges = _extract_bone_clips(
        existing_static_rows,
        existing_anim_rows,
        safe_bone_count,
    )
    clips = list(clips)
    sample_counts = list(sample_counts)
    loop_ranges = list(loop_ranges)
    if safe_clip_index > len(clips):
        raise ValueError(
            "Bone Payload local clip table cannot skip Action indices; "
            f"export clip {len(clips)} before clip {safe_clip_index}"
        )

    safe_loop_start, safe_loop_end = loop_range or (0, safe_sample_count - 1)
    safe_loop_start = min(max(int(safe_loop_start), 0), safe_sample_count - 1)
    safe_loop_end = min(max(int(safe_loop_end), 0), safe_sample_count - 1)
    if safe_loop_end < safe_loop_start:
        safe_loop_start, safe_loop_end = 0, safe_sample_count - 1

    if safe_clip_index == len(clips):
        clips.append(incoming_rows)
        sample_counts.append(safe_sample_count)
        loop_ranges.append((safe_loop_start, safe_loop_end))
    else:
        clips[safe_clip_index] = incoming_rows
        sample_counts[safe_clip_index] = safe_sample_count
        loop_ranges[safe_clip_index] = (safe_loop_start, safe_loop_end)

    sample_row_bases = []
    row_base = 0
    for clip_rows in clips:
        sample_row_bases.append(row_base)
        row_base += len(clip_rows)

    return BoneAnimClipMerge(
        anim_rows=np.vstack(clips) if clips else np.empty((0, 4), dtype="<f4"),
        clip_sample_counts=tuple(int(value) for value in sample_counts),
        clip_loop_ranges=tuple((int(start), int(end)) for start, end in loop_ranges),
        clip_sample_row_bases=tuple(sample_row_bases),
    )


def _build_bone_merge_from_clips(clips, sample_counts, loop_ranges) -> BoneAnimClipMerge:
    sample_row_bases = []
    row_base = 0
    for clip_rows in clips:
        sample_row_bases.append(row_base)
        row_base += len(clip_rows)
    return BoneAnimClipMerge(
        anim_rows=np.vstack(clips) if clips else np.empty((0, 4), dtype="<f4"),
        clip_sample_counts=tuple(int(value) for value in sample_counts),
        clip_loop_ranges=tuple((int(start), int(end)) for start, end in loop_ranges),
        clip_sample_row_bases=tuple(sample_row_bases),
    )


def delete_bone_anim_clip(existing_static_rows, existing_anim_rows, *, clip_index: int, bone_count: int) -> BoneAnimClipMerge:
    """Remove one local Action from a Bone Payload and compact row bases."""

    clips, sample_counts, loop_ranges = _extract_bone_clips(
        existing_static_rows,
        existing_anim_rows,
        max(int(bone_count), 0),
    )
    safe_clip_index = int(clip_index)
    if safe_clip_index < 0 or safe_clip_index >= len(clips):
        raise ValueError(f"Bone clip index out of range: {safe_clip_index}")
    clips = list(clips)
    sample_counts = list(sample_counts)
    loop_ranges = list(loop_ranges)
    del clips[safe_clip_index]
    del sample_counts[safe_clip_index]
    del loop_ranges[safe_clip_index]
    return _build_bone_merge_from_clips(clips, sample_counts, loop_ranges)


def _morph_rows_per_sample(channel_count: int, weights_per_row: int) -> int:
    safe_weights_per_row = max(int(weights_per_row), 1)
    return max((max(int(channel_count), 1) + safe_weights_per_row - 1) // safe_weights_per_row, 1)


def _extract_morph_clips(rows, label: str):
    anim_rows = _as_row_array(rows, "<u4", label)
    if len(anim_rows) == 0:
        return 0, 8, 0, (), (), ()
    clip_count = max(int(anim_rows[0, 0]), 1)
    channel_count = int(anim_rows[0, 1])
    weights_per_row = max(int(anim_rows[0, 2]), 1)
    flags = int(anim_rows[0, 3])
    if 1 + clip_count > len(anim_rows):
        raise ValueError(f"{label} clip table is truncated")

    rows_per_sample = _morph_rows_per_sample(channel_count, weights_per_row)
    clips = []
    clip_rows = []
    for clip_row in anim_rows[1:1 + clip_count]:
        sample_count = max(int(clip_row[0]), 1)
        row_base = int(clip_row[1])
        row_end = row_base + sample_count * rows_per_sample
        if row_base < 1 + clip_count or row_end > len(anim_rows):
            raise ValueError(f"{label} payload rows are shorter than its clip table")
        clips.append(np.ascontiguousarray(anim_rows[row_base:row_end], dtype="<u4"))
        clip_rows.append((sample_count, int(clip_row[2]), max(int(clip_row[3]), 1)))
    return channel_count, weights_per_row, flags, tuple(clips), tuple(clip_rows), anim_rows


def merge_morph_anim_clip(existing_rows, incoming_rows, *, clip_index: int) -> np.ndarray:
    """Append or replace one local Action in a Morph Payload."""

    safe_clip_index = int(clip_index)
    if safe_clip_index < 0:
        raise ValueError("Morph clip index must not be negative")

    existing_channels, existing_weights, existing_flags, existing_clips, existing_clip_rows, _existing_rows = _extract_morph_clips(
        existing_rows,
        "MorphAnim rows",
    )
    incoming_channels, incoming_weights, incoming_flags, incoming_clips, incoming_clip_rows, incoming_array = _extract_morph_clips(
        incoming_rows,
        "Incoming MorphAnim rows",
    )
    if len(incoming_clips) != 1:
        raise ValueError("Incoming MorphAnim rows must describe exactly one Action")

    if existing_clips:
        if existing_channels != incoming_channels or existing_weights != incoming_weights:
            raise ValueError(
                "Morph Payload channel layout changed between Actions "
                f"(({existing_channels}, {existing_weights}) != ({incoming_channels}, {incoming_weights}))"
            )
        channel_count = existing_channels
        weights_per_row = existing_weights
        flags = existing_flags
    else:
        if safe_clip_index != 0:
            raise ValueError(
                "Morph Payload local clip table cannot skip Action indices; "
                f"export clip 0 before clip {safe_clip_index}"
            )
        return incoming_array

    clips = list(existing_clips)
    clip_rows = list(existing_clip_rows)
    if safe_clip_index > len(clips):
        raise ValueError(
            "Morph Payload local clip table cannot skip Action indices; "
            f"export clip {len(clips)} before clip {safe_clip_index}"
        )
    if safe_clip_index == len(clips):
        clips.append(incoming_clips[0])
        clip_rows.append(incoming_clip_rows[0])
    else:
        clips[safe_clip_index] = incoming_clips[0]
        clip_rows[safe_clip_index] = incoming_clip_rows[0]

    merged_rows = [(len(clips), channel_count, weights_per_row, flags)]
    row_base = 1 + len(clips)
    for clip_payload, (sample_count, source_frame_start, source_frame_step) in zip(clips, clip_rows):
        merged_rows.append((sample_count, row_base, source_frame_start, source_frame_step))
        row_base += len(clip_payload)
    row_blocks = [np.asarray(merged_rows, dtype="<u4"), *clips]
    return np.vstack(row_blocks)


def delete_morph_anim_clip(existing_rows, *, clip_index: int) -> np.ndarray:
    """Remove one local Action from a Morph Payload and compact row bases."""

    channel_count, weights_per_row, flags, clips, clip_rows, _anim_rows = _extract_morph_clips(
        existing_rows,
        "MorphAnim rows",
    )
    safe_clip_index = int(clip_index)
    if safe_clip_index < 0 or safe_clip_index >= len(clips):
        raise ValueError(f"Morph clip index out of range: {safe_clip_index}")
    clips = list(clips)
    clip_rows = list(clip_rows)
    del clips[safe_clip_index]
    del clip_rows[safe_clip_index]
    if not clips:
        return np.empty((0, 4), dtype="<u4")

    merged_rows = [(len(clips), channel_count, weights_per_row, flags)]
    row_base = 1 + len(clips)
    for clip_payload, (sample_count, source_frame_start, source_frame_step) in zip(clips, clip_rows):
        merged_rows.append((sample_count, row_base, source_frame_start, source_frame_step))
        row_base += len(clip_payload)
    return np.vstack([np.asarray(merged_rows, dtype="<u4"), *clips])
