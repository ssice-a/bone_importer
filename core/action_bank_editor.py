"""On-disk Action Bank editing helpers for RX exports.

This module deliberately avoids Blender imports. Operators can call it safely,
and tests can exercise the destructive buffer rewrites without a running
Blender session.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os

import numpy as np

from .animation_bank import (
    DEFAULT_BANK_NAME,
    RUNTIME_MANIFEST_FORMAT,
    build_animation_bank_from_manifest,
    build_master_playback_rows,
    build_timeline_static_rows,
    normalize_clip_name,
)
from .local_clip_payload import (
    delete_bone_anim_clip,
    delete_morph_anim_clip,
    read_row_buffer,
    write_row_buffer,
)


MANIFEST_FILE_NAME = "rx_export_manifest.json"
MANIFEST_DIR_NAME = os.path.join("Meta", "Manifest")
INVALID_SLOT_ID = 0xFFFFFFFF
DEFAULT_RESERVED_PALETTE_ROWS = 3


@dataclass(frozen=True)
class ActionBankEditResult:
    action_count: int
    deleted_name: str = ""
    renamed_name: str = ""
    manifest_path: str = ""
    rewritten_bone_payloads: int = 0
    rewritten_morph_payloads: int = 0


def resolve_manifest_path(output_directory: str) -> str:
    root = os.path.abspath(output_directory or ".")
    meta_path = os.path.join(root, MANIFEST_DIR_NAME, MANIFEST_FILE_NAME)
    if os.path.exists(meta_path):
        return meta_path
    legacy_path = os.path.join(root, MANIFEST_FILE_NAME)
    if os.path.exists(legacy_path):
        return legacy_path
    return meta_path


def load_runtime_manifest_for_edit(output_directory: str) -> dict:
    manifest_path = resolve_manifest_path(output_directory)
    if not os.path.exists(manifest_path):
        raise ValueError(f"Runtime manifest does not exist: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8-sig") as manifest_file:
        manifest = json.load(manifest_file)
    return _normalize_manifest(manifest)


def write_runtime_manifest_for_edit(output_directory: str, manifest: dict) -> str:
    manifest_path = resolve_manifest_path(output_directory)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as manifest_file:
        json.dump(_normalize_manifest(manifest), manifest_file, indent=2, ensure_ascii=False)
        manifest_file.write("\n")
    return manifest_path


def list_actions(output_directory: str) -> tuple[dict, ...]:
    manifest = load_runtime_manifest_for_edit(output_directory)
    return tuple(dict(clip) for clip in manifest.get("clips", ()) or ())


def rename_action_at_index(output_directory: str, clip_index: int, new_name: str) -> ActionBankEditResult:
    manifest = load_runtime_manifest_for_edit(output_directory)
    clips = _sorted_clips(manifest)
    index = int(clip_index)
    if index < 0 or index >= len(clips):
        raise ValueError(f"Action index out of range: {index}")
    normalized_name = normalize_clip_name(new_name)
    if not normalized_name:
        raise ValueError("Action name must not be empty")
    if any(clip["name"] == normalized_name for clip in clips if int(clip["clip_index"]) != index):
        raise ValueError(f"Action name already exists: {normalized_name}")
    clips[index]["name"] = normalized_name
    clips[index]["clip_name"] = normalized_name
    manifest["clips"] = clips
    manifest_path = write_runtime_manifest_for_edit(output_directory, manifest)
    return ActionBankEditResult(
        action_count=len(clips),
        renamed_name=normalized_name,
        manifest_path=manifest_path,
    )


def delete_action_at_index(output_directory: str, clip_index: int) -> ActionBankEditResult:
    manifest = load_runtime_manifest_for_edit(output_directory)
    clips = _sorted_clips(manifest)
    index = int(clip_index)
    if index < 0 or index >= len(clips):
        raise ValueError(f"Action index out of range: {index}")
    if len(clips) <= 1:
        raise ValueError("Cannot delete the last Action. Re-export with the same Clip Name to overwrite it.")

    deleted_name = str(clips[index].get("name", f"action_{index}"))
    del clips[index]
    for new_index, clip in enumerate(clips):
        clip["clip_index"] = int(new_index)
    manifest["clips"] = clips
    bank = dict(manifest.get("animation_bank", {}) or {})
    default_index = int(bank.get("default_clip_index", 0) or 0)
    if default_index == index or default_index >= len(clips):
        bank["default_clip_index"] = 0
    elif default_index > index:
        bank["default_clip_index"] = default_index - 1
    manifest["animation_bank"] = bank

    rewritten_bone_payloads = 0
    rewritten_morph_payloads = 0
    for payload in dict(manifest.get("payloads", {}) or {}).values():
        bone_payload = dict(payload.get("bone", {}) or {})
        if _delete_bone_payload_clip(output_directory, bone_payload, index):
            rewritten_bone_payloads += 1
        morph_payload = dict(payload.get("morph", {}) or {})
        if _delete_morph_payload_clip(output_directory, morph_payload, index):
            rewritten_morph_payloads += 1

    _rewrite_timeline_buffers(output_directory, manifest)
    manifest_path = write_runtime_manifest_for_edit(output_directory, manifest)
    return ActionBankEditResult(
        action_count=len(clips),
        deleted_name=deleted_name,
        manifest_path=manifest_path,
        rewritten_bone_payloads=rewritten_bone_payloads,
        rewritten_morph_payloads=rewritten_morph_payloads,
    )


def _normalize_manifest(manifest: dict) -> dict:
    normalized = dict(manifest or {})
    normalized["format"] = RUNTIME_MANIFEST_FORMAT
    normalized.setdefault("animation_bank", {"name": DEFAULT_BANK_NAME, "default_clip_index": 0})
    normalized.setdefault("payloads", {})
    normalized.setdefault("draw_parts", {})
    normalized.setdefault("bone_exports", {})
    normalized.setdefault("morph_exports", {})
    normalized.setdefault("geometry_exports", {})
    raw_clips = normalized.get("clips", []) or []
    if isinstance(raw_clips, dict):
        raw_clips = [
            {
                **dict(payload or {}),
                "name": normalize_clip_name(name),
                "clip_name": normalize_clip_name(name),
                "clip_index": index,
            }
            for index, (name, payload) in enumerate(raw_clips.items())
        ]
    normalized["clips"] = _sorted_clips({"clips": raw_clips})
    return normalized


def _sorted_clips(manifest: dict) -> list[dict]:
    clips = []
    for index, clip in enumerate(list(manifest.get("clips", []) or [])):
        row = dict(clip or {})
        row.setdefault("name", normalize_clip_name(row.get("clip_name", row.get("name", f"action_{index}"))))
        row["name"] = normalize_clip_name(row["name"])
        row.setdefault("clip_name", row["name"])
        row.setdefault("clip_index", index)
        row.setdefault("clip_id", index)
        row.setdefault("sample_count", 1)
        row.setdefault("frame_start", 0)
        row.setdefault("frame_end", max(int(row.get("sample_count", 1) or 1) - 1, 0))
        row.setdefault("frame_step", 1)
        row.setdefault("fps", 30.0)
        row.setdefault("default_ticks_per_sample", 1)
        row.setdefault("default_loop_start_sample", 0)
        row.setdefault("default_loop_end_sample", max(int(row.get("sample_count", 1) or 1) - 1, 0))
        clips.append(row)
    clips.sort(key=lambda item: int(item.get("clip_index", 0) or 0))
    return clips


def _resolve_export_path(output_directory: str, path_value: str) -> str:
    path = str(path_value or "")
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(output_directory or ".", path))


def _write_uint4_rows(path: str, rows):
    write_row_buffer(path, rows, "<u4", "uint4 rows")


def _delete_bone_payload_clip(output_directory: str, bone_payload: dict, clip_index: int) -> bool:
    static_path = _resolve_export_path(output_directory, bone_payload.get("static", ""))
    anim_path = _resolve_export_path(output_directory, bone_payload.get("anim", ""))
    if not static_path or not anim_path or not os.path.exists(static_path) or not os.path.exists(anim_path):
        return False
    static_rows = read_row_buffer(static_path, "<u4", "BoneStatic file")
    anim_rows = read_row_buffer(anim_path, "<f4", "BoneAnim file")
    bone_count = int(static_rows[0, 1]) if len(static_rows) else len(bone_payload.get("slot_ids", []) or [])
    deleted = delete_bone_anim_clip(
        static_rows,
        anim_rows,
        clip_index=int(clip_index),
        bone_count=bone_count,
    )
    slot_ids = tuple(int(value) for value in (bone_payload.get("slot_ids", []) or ()))
    if not slot_ids:
        slot_ids = _read_slot_ids_from_static(static_rows)
    flags = int(static_rows[1, 2]) if len(static_rows) > 1 else 0
    reserved_rows = int(static_rows[0, 2]) if len(static_rows) else DEFAULT_RESERVED_PALETTE_ROWS
    write_row_buffer(anim_path, deleted.anim_rows, "<f4", "BoneAnim rows")
    _write_uint4_rows(
        static_path,
        _build_bone_static_rows(
            slot_ids,
            deleted.clip_sample_counts,
            deleted.clip_loop_ranges,
            flags=flags,
            reserved_rows=reserved_rows,
        ),
    )
    return True


def _delete_morph_payload_clip(output_directory: str, morph_payload: dict, clip_index: int) -> bool:
    anim_path = _resolve_export_path(output_directory, morph_payload.get("anim", ""))
    if not anim_path or not os.path.exists(anim_path):
        return False
    deleted = delete_morph_anim_clip(
        read_row_buffer(anim_path, "<u4", "MorphAnim file"),
        clip_index=int(clip_index),
    )
    _write_uint4_rows(anim_path, deleted)
    return True


def _read_slot_ids_from_static(static_rows) -> tuple[int, ...]:
    rows = np.asarray(static_rows, dtype="<u4").reshape((-1, 4))
    if len(rows) < 2:
        return ()
    bone_count = int(rows[0, 1])
    clip_count = max(int(rows[0, 0]), 1)
    slot_row_count = int(rows[0, 3])
    slot_map_base = int(rows[1, 3]) + clip_count
    slot_ids = []
    for row in rows[slot_map_base:slot_map_base + slot_row_count]:
        for value in row:
            if int(value) == INVALID_SLOT_ID:
                continue
            slot_ids.append(int(value))
            if len(slot_ids) >= bone_count:
                return tuple(slot_ids)
    return tuple(slot_ids)


def _build_bone_static_rows(slot_ids, sample_counts, loop_ranges, *, flags: int, reserved_rows: int):
    normalized_slot_ids = tuple(sorted(int(slot_id) for slot_id in slot_ids))
    slot_rows = []
    for start in range(0, len(normalized_slot_ids), 4):
        chunk = list(normalized_slot_ids[start:start + 4])
        while len(chunk) < 4:
            chunk.append(INVALID_SLOT_ID)
        slot_rows.append(tuple(chunk))
    clip_rows = []
    sample_row_base = 0
    bone_count = len(normalized_slot_ids)
    for sample_count, (loop_start, loop_end) in zip(sample_counts, loop_ranges):
        sample_count = max(int(sample_count), 1)
        clip_rows.append((sample_count, sample_row_base, int(loop_start), int(loop_end)))
        sample_row_base += sample_count * bone_count * 2
    palette_row_count = int(reserved_rows) + ((max(normalized_slot_ids) + 1) * 3 if normalized_slot_ids else 0)
    return [
        (len(clip_rows), bone_count, int(reserved_rows), len(slot_rows)),
        (palette_row_count, palette_row_count, int(flags), 2),
        *clip_rows,
        *slot_rows,
    ]


def _rewrite_timeline_buffers(output_directory: str, manifest: dict):
    bank = build_animation_bank_from_manifest(manifest, DEFAULT_BANK_NAME)
    bank_payload = dict(manifest.get("animation_bank", {}) or {})
    timeline_path = _resolve_export_path(output_directory, bank_payload.get("timeline_static", ""))
    master_path = _resolve_export_path(output_directory, bank_payload.get("master_playback", ""))
    if not timeline_path:
        timeline_path = os.path.join(output_directory, "Buffer", "Timeline", "rxanimin_timeline_static.buf")
        bank_payload["timeline_static"] = timeline_path
    if not master_path:
        master_path = os.path.join(output_directory, "Buffer", "Timeline", "rxanimin_master_playback.buf")
        bank_payload["master_playback"] = master_path
    os.makedirs(os.path.dirname(timeline_path), exist_ok=True)
    os.makedirs(os.path.dirname(master_path), exist_ok=True)
    _write_uint4_rows(timeline_path, build_timeline_static_rows(bank))
    _write_uint4_rows(master_path, build_master_playback_rows(bank))
    manifest["animation_bank"] = bank_payload
