"""Blender-light mesh route analysis for RX Export v3.

The analyzer intentionally only depends on Blender-like object attributes. It
can run in unit tests with small fakes and in Blender with real mesh objects.
"""

from __future__ import annotations

import re

try:  # Blender package import.
    from .rx_export_plan import FINAL_SKIN_OWN, FINAL_SKIN_SOURCE_GAME, MeshRouteAnalysis
except ImportError:  # Standalone unit-test import.
    from rx_export_plan import FINAL_SKIN_OWN, FINAL_SKIN_SOURCE_GAME, MeshRouteAnalysis


_SLOT_GROUP_RE = re.compile(r"^\s*(?P<slot>\d+)(?:__(?P<suffix>.*))?\s*$")
_VALID_FINAL_SKIN_OVERRIDES = {"", "AUTO", FINAL_SKIN_SOURCE_GAME, FINAL_SKIN_OWN}


def analyze_mesh_route(mesh_obj) -> MeshRouteAnalysis:
    """Classify one mesh object's weighted groups into RX route inputs.

    Weighted numeric groups (``12`` or ``12__suffix``) are source/game slots.
    Weighted non-numeric groups are treated as OWN armature bone names.
    Empty vertex groups are ignored and the Blender scene is not mutated.
    """

    weighted_group_names = tuple(_weighted_vertex_group_names(mesh_obj))
    source_slots: set[int] = set()
    own_bones: set[str] = set()
    for group_name in weighted_group_names:
        slot_id = _parse_source_slot(group_name)
        if slot_id is None:
            own_bones.add(group_name)
        else:
            source_slots.add(slot_id)

    final_override = _final_skin_override(mesh_obj)
    final_armature_ref = _object_ref(mesh_obj, "bi_final_armature")
    preskin_armature_ref = _object_ref(mesh_obj, "bi_preskin_armature")

    return MeshRouteAnalysis(
        source_slots=tuple(sorted(source_slots)),
        own_bones=tuple(sorted(own_bones)),
        morph_payload_enabled=bool(getattr(mesh_obj, "bi_morph_enabled", False)),
        preskin_bone_enabled=bool(getattr(mesh_obj, "bi_preskin_bone_enabled", False)),
        force_replace_geometry=bool(getattr(mesh_obj, "bi_force_replace_geometry", False)),
        final_skin_override=final_override if final_override != "AUTO" else "",
        final_armature=_object_name(final_armature_ref),
        final_armature_ref=final_armature_ref,
        preskin_armature=_object_name(preskin_armature_ref),
        preskin_armature_ref=preskin_armature_ref,
        preskin_action=_preskin_action_name(mesh_obj, preskin_armature_ref),
    )


def _weighted_vertex_group_names(mesh_obj) -> list[str]:
    group_names_by_index = {
        int(getattr(vertex_group, "index", -1)): str(getattr(vertex_group, "name", "") or "").strip()
        for vertex_group in getattr(mesh_obj, "vertex_groups", []) or []
    }
    weighted_indices: set[int] = set()
    mesh_data = getattr(mesh_obj, "data", None)
    for vertex in getattr(mesh_data, "vertices", []) or []:
        for group_element in getattr(vertex, "groups", []) or []:
            group_index = int(getattr(group_element, "group", -1))
            weight = float(getattr(group_element, "weight", 0.0) or 0.0)
            if weight > 0.0 and group_index in group_names_by_index:
                weighted_indices.add(group_index)

    names = [group_names_by_index[index] for index in sorted(weighted_indices)]
    return [name for name in names if name]


def _parse_source_slot(group_name: str) -> int | None:
    match = _SLOT_GROUP_RE.match(str(group_name or ""))
    if match is None:
        return None
    return int(match.group("slot"))


def _final_skin_override(mesh_obj) -> str:
    raw_value = str(getattr(mesh_obj, "bi_final_skin", "AUTO") or "AUTO").upper()
    if raw_value not in _VALID_FINAL_SKIN_OVERRIDES:
        return ""
    return raw_value


def _object_ref(owner, property_name: str):
    value = getattr(owner, property_name, None)
    if value is None:
        return None
    if str(getattr(value, "type", "") or "") and str(getattr(value, "type", "") or "") != "ARMATURE":
        return None
    return value


def _object_name(value) -> str:
    return str(getattr(value, "name", "") or "") if value is not None else ""


def _preskin_action_name(mesh_obj, preskin_armature_ref) -> str:
    explicit_action = str(getattr(mesh_obj, "bi_preskin_action", "") or "").strip()
    if explicit_action:
        return explicit_action
    animation_data = getattr(preskin_armature_ref, "animation_data", None)
    action = getattr(animation_data, "action", None)
    return str(getattr(action, "name", "") or "")
