"""Persistent RX export manifest helpers."""

from __future__ import annotations

import json
import os

from .animation_export import normalize_clip_name
from .draw_part import draw_part_manifest_rows


MANIFEST_FILE_NAME = "rx_export_manifest.json"


def resolve_export_manifest_path(output_directory: str) -> str:
    return os.path.join(os.path.abspath(output_directory or "."), MANIFEST_FILE_NAME)


def load_export_manifest(output_directory: str) -> dict:
    manifest_path = resolve_export_manifest_path(output_directory)
    if not os.path.exists(manifest_path):
        return {
            "format": "rx_export_manifest_v1",
            "clips": {},
            "draw_parts": {},
            "bone_exports": {},
            "morph_exports": {},
        }
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        payload = json.load(manifest_file)
    payload.setdefault("format", "rx_export_manifest_v1")
    payload.setdefault("clips", {})
    payload.setdefault("draw_parts", {})
    payload.setdefault("bone_exports", {})
    payload.setdefault("morph_exports", {})
    return payload


def _clip_payload_from_metadata(clip_name: str, clip_id: int, metadata: dict) -> dict:
    return {
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
    }


def _merge_clip(manifest: dict, clip_name: str, clip_id: int, metadata: dict):
    clip_key = normalize_clip_name(clip_name)
    incoming_clip = _clip_payload_from_metadata(clip_key, clip_id, metadata)
    existing_clip = manifest["clips"].get(clip_key)
    if existing_clip is not None:
        comparable_keys = ("frame_start", "frame_end", "frame_step", "sample_count", "fps")
        for key in comparable_keys:
            if existing_clip.get(key) != incoming_clip.get(key):
                raise ValueError(
                    f"Clip '{clip_key}' already exists with different {key}: "
                    f"{existing_clip.get(key)} != {incoming_clip.get(key)}"
                )
    manifest["clips"][clip_key] = {**(existing_clip or {}), **incoming_clip}


def write_export_manifest(
    output_directory: str,
    clip_name: str,
    clip_id: int,
    draw_parts=(),
    export_results=(),
    morph_results=(),
    clip_metadata=None,
) -> str:
    """Merge the current export pass into the persistent RX manifest."""
    manifest = load_export_manifest(output_directory)
    normalized_clip_name = normalize_clip_name(clip_name)

    for draw_part_row in draw_part_manifest_rows(draw_parts):
        manifest["draw_parts"][draw_part_row["draw_key"]] = draw_part_row

    primary_metadata = dict(clip_metadata) if clip_metadata is not None else None
    for export_result in export_results:
        metadata = export_result.metadata
        primary_metadata = primary_metadata or metadata
        draw_key = str(metadata.get("draw_key") or "")
        manifest["bone_exports"][draw_key] = {
            "clip_name": normalized_clip_name,
            "clip_id": int(clip_id),
            "draw_key": draw_key,
            "source_armature": metadata.get("armature_name", ""),
            "bone_namespace": manifest["draw_parts"].get(draw_key, {}).get("object_name", ""),
            "part_id": int(metadata.get("part_id", -1)),
            "slot_ids": list(metadata.get("slot_ids", [])),
            "tqs_path": export_result.tqs_path,
            "bind_path": export_result.bind_path,
            "static_clip_path": export_result.static_clip_path,
        }

    for morph_result in morph_results:
        draw_key = morph_result.mesh_key
        manifest["morph_exports"][draw_key] = {
            "clip_name": normalized_clip_name,
            "clip_id": int(clip_id),
            "draw_key": draw_key,
            "source_object": "",
            "channel_names": list(morph_result.channel_names),
            "sample_count": int(morph_result.sample_count),
            "vertex_count": int(morph_result.vertex_count),
            "morph_static_path": morph_result.morph_static_path,
            "morph_anim_path": morph_result.morph_anim_path,
            "base_position_path": morph_result.base_position_path,
            "base_position_stride": int(morph_result.base_position_stride),
        }

    if primary_metadata is not None:
        _merge_clip(manifest, normalized_clip_name, clip_id, primary_metadata)

    manifest_path = resolve_export_manifest_path(output_directory)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as manifest_file:
        json.dump(manifest, manifest_file, indent=2, ensure_ascii=False)
        manifest_file.write("\n")
    return manifest_path
