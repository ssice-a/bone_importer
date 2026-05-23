"""Runtime draw-part discovery and naming helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re

import bpy
from .collection_plan import (
    CB1_OVERRIDE_NONE,
    normalize_cb1_override,
)
from .context import find_proxy_armature_for_object


DRAW_PART_NAME_RE = re.compile(
    r"^(?P<hash>[0-9A-Fa-f]{8})[-_](?P<index_count>\d+)(?:[-_](?P<first_index>\d+))?$"
)

DEFAULT_MATCH_PRIORITY = -1000


@dataclass(frozen=True)
class RuntimeDrawPart:
    """One runtime TextureOverride/IB target assembled from a Blender object."""

    draw_key: str
    source_object: bpy.types.Object
    proxy_armature: bpy.types.Object | None
    hash: str
    match_index_count: int
    first_index: int
    bone_namespace: str
    match_priority: int = DEFAULT_MATCH_PRIORITY
    bone_enabled: bool = True
    bone_source_armature: bpy.types.Object | None = None
    bone_slot_map_json: str = ""
    skin_contract: str = "TARGET_NUMERIC_GROUPS"
    morph_enabled: bool = False
    morph_source_object: bpy.types.Object | None = None
    cb1_override: str = CB1_OVERRIDE_NONE
    cb1_profile: str = "NONE"
    vb_layout_profile: str = "AUTO"
    buffer_correction_mode: str = ""
    base_position_path: str = ""
    base_position_stride: int = 0
    source_objects: tuple[bpy.types.Object, ...] = ()


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


def _resolve_object_cb1_profile(obj, inherited_override: str) -> str:
    raw_profile = str(getattr(obj, "bi_cb1_profile", "INHERIT") or "INHERIT").upper()
    if raw_profile == "INHERIT":
        return normalize_cb1_override(inherited_override, CB1_OVERRIDE_NONE)
    return normalize_cb1_override(raw_profile, CB1_OVERRIDE_NONE)


def _build_runtime_draw_part(obj, proxy_armature, _part_id: int, cb1_override: str) -> RuntimeDrawPart:
    payload = parse_draw_part_name(obj.name)
    hash_value = payload["hash"]
    match_index_count = payload["match_index_count"]
    first_index = payload["first_index"]
    draw_key = build_draw_key(hash_value, match_index_count, first_index)
    explicit_bone_source = getattr(obj, "bi_bone_source_armature", None)
    if explicit_bone_source is not None and getattr(explicit_bone_source, "type", "") != "ARMATURE":
        explicit_bone_source = None
    return RuntimeDrawPart(
        draw_key=draw_key,
        source_object=obj,
        proxy_armature=proxy_armature,
        hash=hash_value,
        match_index_count=match_index_count,
        first_index=first_index,
        bone_namespace=str(getattr(obj, "name", "")),
        match_priority=int(getattr(obj, "bi_match_priority", DEFAULT_MATCH_PRIORITY) or DEFAULT_MATCH_PRIORITY),
        bone_enabled=bool(getattr(obj, "bi_bone_enabled", True)),
        bone_source_armature=explicit_bone_source or proxy_armature,
        bone_slot_map_json=str(getattr(obj, "bi_bone_slot_map_json", "") or ""),
        skin_contract=str(getattr(obj, "bi_skin_contract", "TARGET_NUMERIC_GROUPS") or "TARGET_NUMERIC_GROUPS"),
        morph_enabled=bool(getattr(obj, "bi_morph_enabled", False)),
        morph_source_object=getattr(obj, "bi_morph_source_object", None),
        cb1_override=normalize_cb1_override(cb1_override, CB1_OVERRIDE_NONE),
        cb1_profile=_resolve_object_cb1_profile(obj, cb1_override),
        vb_layout_profile=str(getattr(obj, "bi_vb_layout_profile", "AUTO") or "AUTO"),
        buffer_correction_mode=str(getattr(obj, "bi_buffer_correction_mode", "")),
        base_position_path=str(getattr(obj, "bi_base_position_path", "") or ""),
        base_position_stride=int(getattr(obj, "bi_base_position_stride", 0) or 0),
        source_objects=(obj,),
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
        try:
            parse_draw_part_name(obj.name)
        except ValueError:
            continue
        proxy_armature = find_proxy_armature_for_object(obj)
        candidates.append((obj, proxy_armature, cb1_override))
    if candidates:
        return _build_draw_parts_from_candidates(candidates)
    return _build_draw_parts_from_region_collections(collection)


def _build_draw_parts_from_region_collections(collection) -> tuple[RuntimeDrawPart, ...]:
    candidates = []
    for region_collection, cb1_override in _iter_region_collections_with_cb1(collection):
        try:
            payload = parse_draw_part_name(getattr(region_collection, "name", ""))
        except ValueError:
            continue
        mesh_objects = tuple(_mesh_objects_for_region_collection(region_collection))
        if not mesh_objects:
            continue
        representative = mesh_objects[0]
        proxy_armature = _find_proxy_armature_for_meshes(mesh_objects)
        draw_key = build_draw_key(payload["hash"], payload["match_index_count"], payload["first_index"])
        candidates.append(
            {
                **payload,
                "draw_key": draw_key,
                "object": representative,
                "objects": mesh_objects,
                "proxy_armature": proxy_armature,
                "cb1_override": cb1_override,
            }
        )
    sorted_payloads = sorted(candidates, key=draw_part_sort_key_from_payload)
    seen_draw_keys = set()
    draw_parts = []
    for payload in sorted_payloads:
        draw_key = payload["draw_key"]
        if draw_key in seen_draw_keys:
            raise ValueError(f"Duplicate draw part key {draw_key}; IB collection names must be unique")
        seen_draw_keys.add(draw_key)
        draw_parts.append(_build_runtime_draw_part_from_collection_payload(payload))
    return tuple(draw_parts)


def _iter_region_collections_with_cb1(collection):
    if collection is None:
        return
    inherited_override = CB1_OVERRIDE_NONE
    raw_override = getattr(collection, "bi_cb1_override", CB1_OVERRIDE_NONE)
    inherited_override = normalize_cb1_override(raw_override, inherited_override)
    for child in getattr(collection, "children", []) or []:
        child_override = normalize_cb1_override(getattr(child, "bi_cb1_override", CB1_OVERRIDE_NONE), inherited_override)
        yield child, child_override


def _mesh_objects_for_region_collection(region_collection):
    part_children = [
        child
        for child in getattr(region_collection, "children", []) or []
        if _parse_part_collection_index(getattr(child, "name", "")) is not None
    ]
    if part_children:
        for part_collection in sorted(part_children, key=lambda child: _parse_part_collection_index(getattr(child, "name", "")) or 0):
            yield from _iter_meshes_recursive(part_collection)
        return
    for obj in getattr(region_collection, "objects", []) or []:
        if getattr(obj, "type", "") == "MESH":
            yield obj


def _parse_part_collection_index(collection_name: str) -> int | None:
    match = re.match(r"^part(?P<index>\d+)(?:\D.*)?$", str(collection_name or "").strip(), re.IGNORECASE)
    if match is None:
        return None
    return int(match.group("index"))


def _iter_meshes_recursive(collection):
    seen_names: set[str] = set()

    def walk(current_collection):
        for obj in getattr(current_collection, "objects", []) or []:
            if getattr(obj, "type", "") != "MESH":
                continue
            object_name = str(getattr(obj, "name_full", getattr(obj, "name", "")) or "")
            if object_name in seen_names:
                continue
            seen_names.add(object_name)
            yield obj
        for child in getattr(current_collection, "children", []) or []:
            yield from walk(child)

    yield from walk(collection)


def _find_proxy_armature_for_meshes(mesh_objects):
    for mesh_obj in mesh_objects:
        proxy_armature = find_proxy_armature_for_object(mesh_obj)
        if proxy_armature is not None:
            return proxy_armature
    return None


def _build_runtime_draw_part_from_collection_payload(payload: dict) -> RuntimeDrawPart:
    obj = payload["object"]
    proxy_armature = payload.get("proxy_armature")
    cb1_override = payload.get("cb1_override", CB1_OVERRIDE_NONE)
    explicit_bone_source = getattr(obj, "bi_bone_source_armature", None)
    if explicit_bone_source is not None and getattr(explicit_bone_source, "type", "") != "ARMATURE":
        explicit_bone_source = None
    return RuntimeDrawPart(
        draw_key=payload["draw_key"],
        source_object=obj,
        proxy_armature=proxy_armature,
        hash=payload["hash"],
        match_index_count=int(payload["match_index_count"]),
        first_index=int(payload["first_index"]),
        bone_namespace=str(payload["draw_key"]),
        match_priority=int(getattr(obj, "bi_match_priority", DEFAULT_MATCH_PRIORITY) or DEFAULT_MATCH_PRIORITY),
        bone_enabled=bool(getattr(obj, "bi_bone_enabled", True)),
        bone_source_armature=explicit_bone_source or proxy_armature,
        bone_slot_map_json=str(getattr(obj, "bi_bone_slot_map_json", "") or ""),
        skin_contract=str(getattr(obj, "bi_skin_contract", "TARGET_NUMERIC_GROUPS") or "TARGET_NUMERIC_GROUPS"),
        morph_enabled=bool(getattr(obj, "bi_morph_enabled", False)),
        morph_source_object=getattr(obj, "bi_morph_source_object", None),
        cb1_override=normalize_cb1_override(cb1_override, CB1_OVERRIDE_NONE),
        cb1_profile=_resolve_object_cb1_profile(obj, cb1_override),
        vb_layout_profile=str(getattr(obj, "bi_vb_layout_profile", "AUTO") or "AUTO"),
        buffer_correction_mode=str(getattr(obj, "bi_buffer_correction_mode", "")),
        base_position_path=str(getattr(obj, "bi_base_position_path", "") or ""),
        base_position_stride=int(getattr(obj, "bi_base_position_stride", 0) or 0),
        source_objects=tuple(payload.get("objects", ()) or (obj,)),
    )


def draw_parts_from_selected_objects(context) -> tuple[RuntimeDrawPart, ...]:
    """Resolve draw parts from the current selection."""
    candidates = []
    for obj in getattr(context, "selected_objects", []) or []:
        if getattr(obj, "type", "") != "MESH":
            continue
        try:
            parse_draw_part_name(obj.name)
        except ValueError:
            continue
        proxy_armature = find_proxy_armature_for_object(obj)
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
            "named '<hash>-<index_count>-<first_index>'"
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
            "proxy_armature": draw_part.proxy_armature.name if draw_part.proxy_armature else "",
            "hash": draw_part.hash,
            "match_index_count": int(draw_part.match_index_count),
            "first_index": int(draw_part.first_index),
            "cb1_override": draw_part.cb1_override,
            "cb1_profile": draw_part.cb1_profile,
            "match_priority": int(draw_part.match_priority),
            "bone_enabled": bool(draw_part.bone_enabled),
            "bone_source_armature": draw_part.bone_source_armature.name if draw_part.bone_source_armature else "",
            "bone_slot_map_json": draw_part.bone_slot_map_json,
            "skin_contract": draw_part.skin_contract,
            "morph_enabled": bool(draw_part.morph_enabled),
            "morph_source_object": draw_part.morph_source_object.name if draw_part.morph_source_object else "",
            "vb_layout_profile": draw_part.vb_layout_profile,
            "buffer_correction_mode": draw_part.buffer_correction_mode,
            "export_mirror_x": bool(getattr(draw_part.source_object, "bi_export_mirror_x", True)),
            "export_uv_mirror_u": bool(getattr(draw_part.source_object, "bi_export_uv_mirror_u", False)),
            "export_uv_flip_v": bool(getattr(draw_part.source_object, "bi_export_uv_flip_v", True)),
            "base_position_path": draw_part.base_position_path,
            "base_position_stride": int(draw_part.base_position_stride),
        }
        for draw_part in draw_parts
    ]
