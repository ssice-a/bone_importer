"""Helpers for creating the RX v3 export collection tree from a manifest."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


DEFAULT_RX_EXPORT_COLLECTION = "RX Export Collection"
_PART_RE = re.compile(r"^part(?P<index>\d+)(?:\D.*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class RXObjectSetup:
    object_name: str
    final_skin: str = "AUTO"
    force_replace_geometry: bool = False
    morph_enabled: bool = False
    bone_enabled: bool = True
    match_priority: int = -1000
    cb1_profile: str = "NONE"
    vb_layout_profile: str = "AUTO"
    buffer_correction_mode: str = "NONE"
    export_mirror_x: bool = True
    export_uv_mirror_u: bool = False
    export_uv_flip_v: bool = True
    base_position_path: str = ""
    base_position_stride: int = 0


@dataclass(frozen=True)
class RXDrawPartSetup:
    draw_key: str
    collection_name: str
    objects: tuple[RXObjectSetup, ...] = ()
    has_geometry: bool = False
    has_morph: bool = False
    has_bone: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RXCollectionSetupPlan:
    root_collection_name: str = DEFAULT_RX_EXPORT_COLLECTION
    draw_parts: tuple[RXDrawPartSetup, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RXCollectionSetupResult:
    root_collection_name: str
    draw_part_count: int
    explicit_part_collection_count: int
    linked_object_count: int
    missing_objects: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def build_collection_setup_plan(
    manifest: dict,
    *,
    root_collection_name: str = DEFAULT_RX_EXPORT_COLLECTION,
) -> RXCollectionSetupPlan:
    """Build a Blender collection setup plan from ``rx_export_manifest.json`` data."""

    draw_parts = dict(manifest.get("draw_parts", {}) or {})
    payloads = dict(manifest.get("payloads", {}) or {})
    setup_parts: list[RXDrawPartSetup] = []
    warnings: list[str] = []

    def sort_key(item):
        _draw_key, draw_part = item
        return (-int(draw_part.get("match_index_count", 0) or 0), str(draw_part.get("object_name", "") or ""))

    for draw_key, draw_part in sorted(draw_parts.items(), key=sort_key):
        payload = dict(payloads.get(draw_key, {}) or {})
        object_names = _object_names_for_draw_part(draw_part, payload)
        if not object_names:
            object_names = (str(draw_part.get("object_name", "") or ""),)
        object_names = tuple(name for name in object_names if name)
        if not object_names:
            warnings.append(f"{draw_key}: no object name available")

        has_geometry = bool(payload.get("geometry"))
        has_morph = bool(payload.get("morph"))
        has_bone = bool(payload.get("bone"))
        morph_payload = dict(payload.get("morph", {}) or {})
        object_settings = tuple(
            RXObjectSetup(
                object_name=object_name,
                final_skin=str(draw_part.get("final_skin", "") or "AUTO"),
                force_replace_geometry=has_geometry,
                morph_enabled=has_morph,
                bone_enabled=bool(draw_part.get("bone_enabled", has_bone)),
                match_priority=int(draw_part.get("match_priority", -1000) or -1000),
                cb1_profile=str(draw_part.get("cb1_profile", "NONE") or "NONE"),
                vb_layout_profile=str(draw_part.get("vb_layout_profile", "AUTO") or "AUTO"),
                buffer_correction_mode=str(draw_part.get("buffer_correction_mode", "NONE") or "NONE"),
                export_mirror_x=bool(draw_part.get("export_mirror_x", True)),
                export_uv_mirror_u=bool(draw_part.get("export_uv_mirror_u", False)),
                export_uv_flip_v=bool(draw_part.get("export_uv_flip_v", True)),
                base_position_path=str(morph_payload.get("base_position_path", draw_part.get("base_position_path", "")) or ""),
                base_position_stride=int(
                    morph_payload.get("base_position_stride", draw_part.get("base_position_stride", 0)) or 0
                ),
            )
            for object_name in object_names
        )
        setup_parts.append(
            RXDrawPartSetup(
                draw_key=str(draw_key),
                collection_name=_draw_part_collection_name(draw_part, draw_key),
                objects=object_settings,
                has_geometry=has_geometry,
                has_morph=has_morph,
                has_bone=has_bone,
            )
        )

    return RXCollectionSetupPlan(
        root_collection_name=root_collection_name,
        draw_parts=tuple(setup_parts),
        warnings=tuple(warnings),
    )


def _draw_part_collection_name(draw_part: dict, draw_key: str) -> str:
    object_name = str(draw_part.get("object_name", "") or "").strip()
    if object_name:
        return object_name
    ib_hash = str(draw_part.get("hash", "") or "").strip()
    match_index_count = int(draw_part.get("match_index_count", 0) or 0)
    first_index = int(draw_part.get("first_index", 0) or 0)
    if ib_hash and match_index_count:
        return f"{ib_hash}-{match_index_count}-{first_index}"
    return str(draw_key).replace("_", "-")


def _object_names_for_draw_part(draw_part: dict, payload: dict) -> tuple[str, ...]:
    names: list[str] = []
    for geometry_payload in list(payload.get("geometry", []) or []):
        for object_name in list(dict(geometry_payload or {}).get("object_names", []) or []):
            _append_unique(names, str(object_name or ""))
    _append_unique(names, str(draw_part.get("object_name", "") or ""))
    return tuple(names)


def _append_unique(values: list[str], value: str):
    value = str(value or "").strip()
    if value and value not in values:
        values.append(value)


def apply_collection_setup_plan(context, plan: RXCollectionSetupPlan) -> RXCollectionSetupResult:
    """Apply a setup plan to the active Blender scene.

    Objects are linked directly into each IB collection. Direct meshes are
    interpreted by the export planner as the implicit part00. Missing objects
    are reported, never created as fake meshes.
    """

    import bpy

    scene = getattr(context, "scene", None)
    if scene is None:
        raise ValueError("No active Blender scene")

    root_collection = _ensure_child_collection(scene.collection, plan.root_collection_name, reuse_global=True)
    linked_object_count = 0
    missing_objects: list[str] = []
    warnings: list[str] = list(plan.warnings)

    for draw_part in plan.draw_parts:
        draw_collection = _ensure_child_collection(root_collection, draw_part.collection_name, reuse_global=True)
        _unlink_existing_part_collections(draw_collection)
        _unlink_direct_meshes(draw_collection)

        for object_setup in draw_part.objects:
            obj = _find_object(bpy, object_setup.object_name)
            if obj is None:
                missing_objects.append(object_setup.object_name)
                continue
            _link_object(draw_collection, obj)
            _apply_object_setup(obj, object_setup)
            linked_object_count += 1

    return RXCollectionSetupResult(
        root_collection_name=root_collection.name,
        draw_part_count=len(plan.draw_parts),
        explicit_part_collection_count=0,
        linked_object_count=linked_object_count,
        missing_objects=tuple(missing_objects),
        warnings=tuple(warnings),
    )


def _ensure_child_collection(parent_collection, child_name: str, *, reuse_global: bool = False):
    import bpy

    existing_child = getattr(parent_collection.children, "get", lambda _name: None)(child_name)
    if existing_child is not None:
        return existing_child
    collection = None
    if reuse_global:
        collection = bpy.data.collections.get(child_name)
    if collection is None:
        collection = bpy.data.collections.new(child_name)
    try:
        parent_collection.children.link(collection)
    except RuntimeError:
        pass
    return collection


def _link_object(collection, obj):
    if getattr(collection.objects, "get", lambda _name: None)(obj.name) is not None:
        return
    collection.objects.link(obj)


def _unlink_direct_meshes(collection):
    for obj in tuple(collection.objects):
        if str(getattr(obj, "type", "") or "") == "MESH":
            collection.objects.unlink(obj)


def _unlink_existing_part_collections(collection):
    """Remove old auto-created partNN children so sync falls back to implicit part00."""

    for child in tuple(collection.children):
        if _parse_part_index(getattr(child, "name", "")) is not None:
            collection.children.unlink(child)


def _parse_part_index(collection_name: str) -> int | None:
    match = _PART_RE.match(str(collection_name or "").strip())
    if match is None:
        return None
    return int(match.group("index"))


def _find_object(bpy_module, object_name: str):
    object_name = str(object_name or "").strip()
    if not object_name:
        return None
    exact = bpy_module.data.objects.get(object_name)
    if exact is not None:
        return exact
    if "." in object_name:
        base_name = object_name.rsplit(".", 1)[0]
        return bpy_module.data.objects.get(base_name)
    return None


def _apply_object_setup(obj, setup: RXObjectSetup):
    assignments = {
        "bi_final_skin": setup.final_skin,
        "bi_force_replace_geometry": setup.force_replace_geometry,
        "bi_morph_enabled": setup.morph_enabled,
        "bi_bone_enabled": setup.bone_enabled,
        "bi_match_priority": setup.match_priority,
        "bi_cb1_profile": setup.cb1_profile,
        "bi_vb_layout_profile": setup.vb_layout_profile,
        "bi_buffer_correction_mode": setup.buffer_correction_mode,
        "bi_export_mirror_x": setup.export_mirror_x,
        "bi_export_uv_mirror_u": setup.export_uv_mirror_u,
        "bi_export_uv_flip_v": setup.export_uv_flip_v,
        "bi_base_position_path": setup.base_position_path,
        "bi_base_position_stride": setup.base_position_stride,
    }
    for property_name, value in assignments.items():
        if hasattr(obj, property_name):
            setattr(obj, property_name, value)
