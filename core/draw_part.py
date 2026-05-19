"""Runtime draw-part discovery and naming helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re

import bpy
from .collection_plan import (
    CB1_OVERRIDE_NONE,
    normalize_cb1_override,
)
from .context import build_part_layout_from_id, find_proxy_armature_for_object


DRAW_PART_NAME_RE = re.compile(
    r"^(?P<hash>[0-9A-Fa-f]{8})[-_](?P<index_count>\d+)(?:[-_](?P<first_index>\d+))?$"
)


@dataclass(frozen=True)
class RuntimeDrawPart:
    """One runtime TextureOverride/IB target assembled from a Blender object."""

    draw_key: str
    source_object: bpy.types.Object
    proxy_armature: bpy.types.Object
    hash: str
    match_index_count: int
    first_index: int
    part_id: int
    part_base: int
    part_size: int
    previous_offset: int
    previous_base: int
    buffer_size: int
    bone_namespace: str
    cb1_override: str = CB1_OVERRIDE_NONE
    buffer_correction_mode: str = ""
    base_position_path: str = ""
    base_position_stride: int = 0


def parse_draw_part_name(name: str) -> dict:
    """Parse the required '<hash>-<index_count>-<first_index>' object-name protocol."""
    text = str(name or "").strip()
    match = DRAW_PART_NAME_RE.match(text)
    if match is None:
        raise ValueError(
            f"Draw part object name must be '<hash>-<index_count>-<first_index>': {name}"
        )
    first_index = match.group("first_index")
    return {
        "hash": match.group("hash").lower(),
        "match_index_count": int(match.group("index_count")),
        "first_index": int(first_index) if first_index is not None else 0,
    }


def build_draw_key(hash_value: str, match_index_count: int, first_index: int) -> str:
    """Build the stable manifest/resource key for a draw part."""
    return f"{str(hash_value).lower()}_{int(match_index_count)}_{int(first_index)}"


def draw_part_sort_key_from_payload(payload: dict) -> tuple:
    """Sort larger IBs first, then use stable tie-breakers."""
    return (
        -int(payload["match_index_count"]),
        int(payload["first_index"]),
        str(payload["hash"]),
        str(payload.get("object_name", "")),
    )


def iter_collection_objects_recursive(collection):
    """Yield unique objects stored under an export collection tree."""
    if collection is None:
        return
    seen_names: set[str] = set()

    def walk(current_collection):
        for obj in getattr(current_collection, "objects", []) or []:
            object_name = str(getattr(obj, "name_full", getattr(obj, "name", "")) or "")
            if object_name in seen_names:
                continue
            seen_names.add(object_name)
            yield obj
        for child in getattr(current_collection, "children", []) or []:
            yield from walk(child)

    yield from walk(collection)


def _iter_collection_objects_with_cb1(collection):
    if collection is None:
        return

    def walk(current_collection, inherited_override: str):
        raw_override = getattr(current_collection, "bi_cb1_override", CB1_OVERRIDE_NONE)
        effective_override = normalize_cb1_override(raw_override, inherited_override)
        for obj in getattr(current_collection, "objects", []) or []:
            yield obj, effective_override
        for child in getattr(current_collection, "children", []) or []:
            yield from walk(child, effective_override)

    yield from walk(collection, CB1_OVERRIDE_NONE)


def _build_runtime_draw_part(obj, proxy_armature, part_id: int, cb1_override: str) -> RuntimeDrawPart:
    payload = parse_draw_part_name(obj.name)
    layout = build_part_layout_from_id(part_id)
    hash_value = payload["hash"]
    match_index_count = payload["match_index_count"]
    first_index = payload["first_index"]
    draw_key = build_draw_key(hash_value, match_index_count, first_index)
    return RuntimeDrawPart(
        draw_key=draw_key,
        source_object=obj,
        proxy_armature=proxy_armature,
        hash=hash_value,
        match_index_count=match_index_count,
        first_index=first_index,
        part_id=int(part_id),
        part_base=layout["part_base"],
        part_size=layout["part_size"],
        previous_offset=layout["previous_offset"],
        previous_base=layout["previous_base"],
        buffer_size=layout["buffer_size"],
        bone_namespace=str(getattr(obj, "name", "")),
        cb1_override=normalize_cb1_override(cb1_override, CB1_OVERRIDE_NONE),
        buffer_correction_mode=str(getattr(obj, "bi_buffer_correction_mode", "")),
        base_position_path=str(getattr(obj, "bi_base_position_path", "") or ""),
        base_position_stride=int(getattr(obj, "bi_base_position_stride", 0) or 0),
    )


def _build_draw_parts_from_candidates(candidates: list[tuple[bpy.types.Object, bpy.types.Object, str]]):
    payloads = []
    seen_draw_keys = set()
    for obj, proxy_armature, cb1_override in candidates:
        payload = parse_draw_part_name(obj.name)
        payload["object_name"] = obj.name
        payload["object"] = obj
        payload["proxy_armature"] = proxy_armature
        payload["cb1_override"] = cb1_override
        draw_key = build_draw_key(payload["hash"], payload["match_index_count"], payload["first_index"])
        if draw_key in seen_draw_keys:
            raise ValueError(f"Duplicate draw part key {draw_key}; object names must be unique")
        seen_draw_keys.add(draw_key)
        payloads.append(payload)

    sorted_payloads = sorted(payloads, key=draw_part_sort_key_from_payload)
    return tuple(
        _build_runtime_draw_part(
            payload["object"],
            payload["proxy_armature"],
            part_id,
            payload["cb1_override"],
        )
        for part_id, payload in enumerate(sorted_payloads)
    )


def draw_parts_from_export_collection(collection) -> tuple[RuntimeDrawPart, ...]:
    """Resolve draw parts from collection objects that follow the draw-part naming protocol."""
    candidates = []
    for obj, cb1_override in _iter_collection_objects_with_cb1(collection):
        if getattr(obj, "type", "") != "MESH":
            continue
        proxy_armature = find_proxy_armature_for_object(obj)
        if proxy_armature is None:
            continue
        candidates.append((obj, proxy_armature, cb1_override))
    return _build_draw_parts_from_candidates(candidates)


def draw_parts_from_selected_objects(context) -> tuple[RuntimeDrawPart, ...]:
    """Resolve draw parts from the current selection."""
    candidates = []
    for obj in getattr(context, "selected_objects", []) or []:
        if getattr(obj, "type", "") != "MESH":
            continue
        proxy_armature = find_proxy_armature_for_object(obj)
        if proxy_armature is None:
            continue
        candidates.append((obj, proxy_armature, CB1_OVERRIDE_NONE))
    return _build_draw_parts_from_candidates(candidates)


def build_target_draw_parts(context) -> tuple[RuntimeDrawPart, ...]:
    """Resolve runtime draw parts from the export collection, then from selection."""
    scene = getattr(context, "scene", None)
    export_collection = getattr(scene, "bi_export_collection", None) if scene is not None else None
    if export_collection is not None:
        draw_parts = draw_parts_from_export_collection(export_collection)
        if draw_parts:
            return draw_parts
        raise ValueError(
            f"RX Export Collection '{export_collection.name}' has no draw-part objects "
            "named '<hash>-<index_count>-<first_index>' with linked proxy armatures"
        )

    draw_parts = draw_parts_from_selected_objects(context)
    if draw_parts:
        return draw_parts
    raise ValueError("No draw-part objects named '<hash>-<index_count>-<first_index>' found")


def count_collection_draw_parts(collection) -> int:
    """Count collection objects that can become runtime draw parts."""
    return len(draw_parts_from_export_collection(collection)) if collection is not None else 0


def draw_part_manifest_rows(draw_parts) -> list[dict]:
    """Serialize draw-part metadata for manifests."""
    return [
        {
            "draw_key": draw_part.draw_key,
            "object_name": draw_part.source_object.name,
            "proxy_armature": draw_part.proxy_armature.name,
            "hash": draw_part.hash,
            "match_index_count": int(draw_part.match_index_count),
            "first_index": int(draw_part.first_index),
            "part_id": int(draw_part.part_id),
            "part_base": int(draw_part.part_base),
            "part_size": int(draw_part.part_size),
            "previous_offset": int(draw_part.previous_offset),
            "cb1_override": draw_part.cb1_override,
            "buffer_correction_mode": draw_part.buffer_correction_mode,
            "base_position_path": draw_part.base_position_path,
            "base_position_stride": int(draw_part.base_position_stride),
        }
        for draw_part in draw_parts
    ]
