"""Persistent RX export manifest helpers."""

from __future__ import annotations

import json
import os

from ..constants import RESERVED_PALETTE_ROWS
from .animation_bank import (
    RUNTIME_MANIFEST_FORMAT,
    ClipSpec,
    merge_clip_into_manifest,
    normalize_clip_name,
)
from .draw_part import build_draw_key, draw_part_manifest_rows


MANIFEST_FILE_NAME = "rx_export_manifest.json"
MANIFEST_DIR_NAME = os.path.join("Meta", "Manifest")
DEFAULT_BANK_NAME = "rxanimin"


def _empty_runtime_manifest() -> dict:
    return {
        "format": RUNTIME_MANIFEST_FORMAT,
        "animation_bank": {
            "name": DEFAULT_BANK_NAME,
            "default_clip_index": 0,
            "flags": 0,
        },
        "clips": [],
        "draw_parts": {},
        "bone_exports": {},
        "morph_exports": {},
        "geometry_exports": {},
        "payloads": {},
    }


def normalize_runtime_manifest(payload: dict | None) -> dict:
    """Return the current Runtime Manifest shape, migrating legacy clip maps."""

    normalized = dict(payload or {})
    normalized["format"] = RUNTIME_MANIFEST_FORMAT
    animation_bank = dict(normalized.get("animation_bank", {}) or {})
    animation_bank.setdefault("name", DEFAULT_BANK_NAME)
    animation_bank.setdefault("default_clip_index", 0)
    animation_bank.setdefault("flags", 0)
    normalized["animation_bank"] = animation_bank

    raw_clips = normalized.get("clips", [])
    if isinstance(raw_clips, dict):
        clips = []
        for clip_index, (clip_name, clip_payload) in enumerate(raw_clips.items()):
            clip = dict(clip_payload or {})
            clip.setdefault("name", normalize_clip_name(clip_name))
            clip.setdefault("clip_name", clip["name"])
            clip.setdefault("clip_index", clip_index)
            clip.setdefault("clip_id", clip_index)
            sample_count = int(clip.get("sample_count", clip.get("frame_count", 1)) or 1)
            clip.setdefault("sample_count", sample_count)
            clip.setdefault("frame_start", 0)
            clip.setdefault("frame_end", max(sample_count - 1, 0))
            clip.setdefault("frame_step", 1)
            clip.setdefault("fps", 30.0)
            clip.setdefault("source_fps", clip.get("fps", 30.0))
            clip.setdefault("target_game_fps", 120.0)
            clip.setdefault("playback_speed", 1.0)
            clip.setdefault("default_ticks_per_sample", 1)
            clip.setdefault("default_loop_start_sample", 0)
            clip.setdefault("default_loop_end_sample", max(sample_count - 1, 0))
            clips.append(clip)
        raw_clips = clips
    normalized["clips"] = list(raw_clips or [])

    normalized.setdefault("draw_parts", {})
    normalized.setdefault("bone_exports", {})
    normalized.setdefault("morph_exports", {})
    normalized.setdefault("geometry_exports", {})
    normalized.setdefault("payloads", {})
    return normalized


def resolve_export_manifest_path(output_directory: str) -> str:
    return os.path.join(os.path.abspath(output_directory or "."), MANIFEST_DIR_NAME, MANIFEST_FILE_NAME)


def load_export_manifest(output_directory: str) -> dict:
    manifest_path = resolve_export_manifest_path(output_directory)
    if not os.path.exists(manifest_path):
        legacy_manifest_path = os.path.join(os.path.abspath(output_directory or "."), MANIFEST_FILE_NAME)
        if os.path.exists(legacy_manifest_path):
            manifest_path = legacy_manifest_path
    if not os.path.exists(manifest_path):
        return _empty_runtime_manifest()
    with open(manifest_path, "r", encoding="utf-8-sig") as manifest_file:
        payload = json.load(manifest_file)
    return normalize_runtime_manifest(payload)


def _clip_payload_from_metadata(clip_name: str, clip_id: int, metadata: dict) -> dict:
    return {
        "name": normalize_clip_name(clip_name),
        "clip_name": normalize_clip_name(clip_name),
        "clip_id": int(clip_id),
        "frame_start": int(metadata["frame_start"]),
        "frame_end": int(metadata["frame_end"]),
        "frame_step": int(metadata["frame_step"]),
        "sample_count": int(metadata["frame_count"]),
        "fps": float(metadata["fps"]),
        "default_ticks_per_sample": int(metadata["default_ticks_per_sample"]),
        "default_loop_start_sample": int(metadata["default_loop_start_sample"]),
        "default_loop_end_sample": int(metadata["default_loop_end_sample"]),
        "timeline_static": metadata.get("timeline_static_path", metadata.get("timeline_static", "")),
        "master_playback": metadata.get("master_playback_path", metadata.get("master_playback", "")),
    }


def _merge_clip(manifest: dict, clip_name: str, clip_id: int, metadata: dict):
    clip_key = normalize_clip_name(clip_name)
    incoming_clip = _clip_payload_from_metadata(clip_key, clip_id, metadata)
    clip_spec = ClipSpec(
        name=clip_key,
        clip_id=int(clip_id),
        clip_index=int(incoming_clip.get("clip_index", 0) or 0),
        frame_start=int(incoming_clip["frame_start"]),
        frame_end=int(incoming_clip["frame_end"]),
        frame_step=int(incoming_clip["frame_step"]),
        sample_count=int(incoming_clip["sample_count"]),
        source_fps=float(incoming_clip.get("source_fps", incoming_clip.get("fps", 30.0)) or 30.0),
        target_game_fps=float(incoming_clip.get("target_game_fps", 120.0) or 120.0),
        playback_speed=float(incoming_clip.get("playback_speed", 1.0) or 1.0),
        default_ticks_per_sample=int(incoming_clip["default_ticks_per_sample"]),
        default_loop_start_sample=int(incoming_clip["default_loop_start_sample"]),
        default_loop_end_sample=int(incoming_clip["default_loop_end_sample"]),
    )
    merge_clip_into_manifest(manifest, clip_spec, DEFAULT_BANK_NAME)
    manifest["animation_bank"]["timeline_static"] = incoming_clip.get("timeline_static", "")
    manifest["animation_bank"]["master_playback"] = incoming_clip.get("master_playback", "")


def write_export_manifest(
    output_directory: str,
    clip_name: str,
    clip_id: int,
    draw_parts=(),
    export_results=(),
    morph_results=(),
    geometry_results=(),
    clip_metadata=None,
) -> str:
    """Merge the current export pass into the persistent RX manifest."""
    manifest = normalize_runtime_manifest(load_export_manifest(output_directory))
    normalized_clip_name = normalize_clip_name(clip_name)

    for draw_part_row in draw_part_manifest_rows(draw_parts):
        manifest["draw_parts"][draw_part_row["draw_key"]] = draw_part_row
        manifest["payloads"].setdefault(draw_part_row["draw_key"], {})

    primary_metadata = dict(clip_metadata) if clip_metadata is not None else None
    for export_result in export_results:
        metadata = export_result.metadata
        primary_metadata = primary_metadata or metadata
        draw_key = str(metadata.get("draw_key") or "")
        bone_payload = {
            "clip_name": normalized_clip_name,
            "clip_id": int(clip_id),
            "draw_key": draw_key,
            "format": metadata.get("format", "rx_bone_payload_v1"),
            "source_armatures": list(metadata.get("source_armatures", []))
            or ([metadata.get("armature_name", "")] if metadata.get("armature_name", "") else []),
            "skin_contract": metadata.get("skin_contract", manifest["draw_parts"].get(draw_key, {}).get("skin_contract", "")),
            "slot_ids": list(metadata.get("slot_ids", [])),
            "slot_bindings": list(metadata.get("slot_bindings", [])),
            "static": metadata.get("bone_static_path", export_result.static_clip_path),
            "anim": metadata.get("bone_anim_path", export_result.tqs_path),
            "bind": metadata.get("bone_bind_path", export_result.bind_path),
            "palette_row_count": int(
                metadata.get(
                    "palette_row_count",
                    RESERVED_PALETTE_ROWS + ((max(metadata.get("slot_ids", [0])) + 1) * 3 if metadata.get("slot_ids") else 0),
                )
            ),
        }
        manifest["bone_exports"][draw_key] = bone_payload
        manifest["payloads"].setdefault(draw_key, {})["bone"] = bone_payload

    for morph_result in morph_results:
        draw_key = morph_result.mesh_key
        morph_payload = {
            "clip_name": normalized_clip_name,
            "clip_id": int(clip_id),
            "draw_key": draw_key,
            "format": "rx_morph_payload_v1",
            "source_object": getattr(morph_result, "source_object", ""),
            "channel_names": list(morph_result.channel_names),
            "sample_count": int(morph_result.sample_count),
            "vertex_count": int(morph_result.vertex_count),
            "static": morph_result.morph_static_path,
            "anim": morph_result.morph_anim_path,
            "base_position_path": morph_result.base_position_path,
            "base_position_stride": int(morph_result.base_position_stride),
            "base_position_resource_name": getattr(morph_result, "base_position_resource_name", ""),
            "base_position_layout": getattr(morph_result, "base_position_layout", ""),
        }
        manifest["morph_exports"][draw_key] = morph_payload
        manifest["payloads"].setdefault(draw_key, {})["morph"] = morph_payload

    for geometry_result in geometry_results:
        draw_key = build_draw_key(
            geometry_result.get("ib_hash", ""),
            int(geometry_result.get("match_index_count", 0) or 0),
            int(geometry_result.get("match_first_index", 0) or 0),
        )
        if not draw_key:
            continue
        part_name = str(geometry_result.get("part_name", "part00") or "part00")
        geometry_payload = {
            "format": "bmc_geometry_v1",
            "draw_key": draw_key,
            "part_name": part_name,
            "resource_suffix": geometry_result.get("resource_suffix", f"{draw_key}_{part_name}"),
            "object_names": list(geometry_result.get("object_names", [])),
            "object_draws": list(geometry_result.get("object_draws", [])),
            "hash": str(geometry_result.get("ib_hash", "") or ""),
            "match_index_count": int(geometry_result.get("match_index_count", 0) or 0),
            "first_index": int(geometry_result.get("match_first_index", 0) or 0),
            "index_buffer": dict(geometry_result.get("index_buffer", {}) or {}),
            "vertex_buffers": dict(geometry_result.get("vertex_buffers", {}) or {}),
        }
        geometry_bucket = manifest["geometry_exports"].setdefault(draw_key, [])
        geometry_bucket = [
            existing
            for existing in geometry_bucket
            if str(existing.get("part_name", "")) != part_name
        ]
        geometry_bucket.append(geometry_payload)
        manifest["geometry_exports"][draw_key] = geometry_bucket
        manifest["payloads"].setdefault(draw_key, {})["geometry"] = geometry_bucket

    if primary_metadata is not None:
        _merge_clip(manifest, normalized_clip_name, clip_id, primary_metadata)

    manifest_path = resolve_export_manifest_path(output_directory)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as manifest_file:
        json.dump(manifest, manifest_file, indent=2, ensure_ascii=False)
        manifest_file.write("\n")
    return manifest_path
