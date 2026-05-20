"""Slot contract and Bone Slot Map resolution for RX DrawParts.

Slot ids are runtime namespace ids.  Blender import/export coordinate adapters
must not rewrite slot semantics.  Non-identity source binding belongs to an
explicit Bone Slot Map.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

import bpy


INVALID_SLOT_ID = 0xFFFFFFFF
SLOT_NAME_RE = re.compile(r"^\s*(?P<slot>\d+)(?:__(?P<suffix>.*))?\s*$")


@dataclass(frozen=True)
class BoneSlotBinding:
    """One final runtime slot bound to one source pose bone."""

    slot_id: int
    source_armature: bpy.types.Object
    source_bone: str
    target_name: str = ""


@dataclass(frozen=True)
class SlotContract:
    """Runtime slot namespace for one DrawPart."""

    draw_key: str
    slot_ids: tuple[int, ...]
    source: str


def parse_slot_id(name: str) -> int:
    match = SLOT_NAME_RE.match(str(name or ""))
    if match is None:
        raise ValueError(f"Name does not start with a numeric slot id: {name}")
    return int(match.group("slot"))


def _slot_ids_from_vertex_groups(obj) -> tuple[int, ...]:
    slot_ids = set()
    for vertex_group in getattr(obj, "vertex_groups", []) or []:
        try:
            slot_ids.add(parse_slot_id(vertex_group.name))
        except ValueError:
            continue
    return tuple(sorted(slot_ids))


def _slot_ids_from_pose_bones(armature, draw_part=None) -> tuple[int, ...]:
    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        return ()
    draw_suffixes = set()
    if draw_part is not None:
        draw_suffixes.add(str(getattr(draw_part.source_object, "name", "") or ""))
        draw_suffixes.add(str(getattr(draw_part, "draw_key", "") or "").replace("_", "-"))
    slot_ids = set()
    for pose_bone in armature.pose.bones:
        explicit_slot = int(getattr(pose_bone, "bi_slot_id", -1))
        explicit_mesh_key = str(getattr(pose_bone, "bi_mesh_key", "") or "")
        if explicit_slot >= 0:
            if not draw_suffixes or not explicit_mesh_key or explicit_mesh_key in draw_suffixes:
                slot_ids.add(explicit_slot)
                continue
        try:
            slot_id = parse_slot_id(pose_bone.name)
        except ValueError:
            continue
        if not draw_suffixes:
            slot_ids.add(slot_id)
            continue
        _slot, suffix = _split_slot_name(pose_bone.name)
        if not suffix or suffix in draw_suffixes:
            slot_ids.add(slot_id)
    return tuple(sorted(slot_ids))


def _slot_ids_from_explicit_slot_map_payload(draw_part) -> tuple[int, ...]:
    raw_json = str(getattr(draw_part, "bone_slot_map_json", "") or "").strip()
    if not raw_json:
        return ()
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Bone Slot Map JSON for {draw_part.draw_key}: {exc}") from exc
    if isinstance(payload, dict):
        payload = payload.get("bindings", [])
    if not isinstance(payload, list):
        raise ValueError(f"Bone Slot Map for {draw_part.draw_key} must be a JSON list or an object with bindings")

    slot_ids = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError(f"Bone Slot Map row for {draw_part.draw_key} must be an object")
        slot_id = int(row.get("slot_id", row.get("slot", -1)))
        if slot_id < 0:
            raise ValueError(f"Bone Slot Map row for {draw_part.draw_key} is missing slot_id")
        slot_ids.append(slot_id)
    return tuple(sorted(set(slot_ids)))


def _split_slot_name(name: str) -> tuple[int, str]:
    match = SLOT_NAME_RE.match(str(name or ""))
    if match is None:
        raise ValueError(f"Name does not start with a numeric slot id: {name}")
    return int(match.group("slot")), match.group("suffix") or ""


def resolve_slot_contract(draw_part) -> SlotContract:
    """Resolve the final slot order for a DrawPart."""
    explicit_slot_ids = _slot_ids_from_explicit_slot_map_payload(draw_part)
    if explicit_slot_ids:
        return SlotContract(
            draw_key=str(draw_part.draw_key),
            slot_ids=explicit_slot_ids,
            source="explicit_slot_map",
        )

    skin_contract = str(getattr(draw_part, "skin_contract", "TARGET_NUMERIC_GROUPS") or "TARGET_NUMERIC_GROUPS")
    if skin_contract == "SOURCE_ARMATURE_SLOTS":
        slot_ids = _slot_ids_from_pose_bones(getattr(draw_part, "bone_source_armature", None), draw_part)
        source = "source_armature_slots"
    else:
        slot_ids = _slot_ids_from_vertex_groups(getattr(draw_part, "source_object", None))
        source = "target_numeric_groups"
        if not slot_ids:
            slot_ids = _slot_ids_from_pose_bones(getattr(draw_part, "proxy_armature", None), draw_part)
            source = "linked_proxy_slots"

    if not slot_ids:
        raise ValueError(
            f"DrawPart {draw_part.draw_key} has no target slots. "
            "Use numeric vertex groups or configure Source Armature Slots."
        )
    return SlotContract(
        draw_key=str(draw_part.draw_key),
        slot_ids=tuple(sorted(set(int(slot_id) for slot_id in slot_ids))),
        source=source,
    )


def _pose_bone_exists(armature, bone_name: str) -> bool:
    return (
        armature is not None
        and getattr(armature, "type", "") == "ARMATURE"
        and str(bone_name or "") in armature.pose.bones
    )


def _find_source_bone_for_slot(source_armature, draw_part, slot_id: int) -> str:
    if source_armature is None or getattr(source_armature, "type", "") != "ARMATURE":
        return ""
    draw_object_name = str(getattr(draw_part.source_object, "name", "") or "")
    candidates = (
        f"{int(slot_id)}__{draw_object_name}",
        str(int(slot_id)),
    )
    for candidate in candidates:
        if _pose_bone_exists(source_armature, candidate):
            return candidate

    for pose_bone in source_armature.pose.bones:
        explicit_slot = int(getattr(pose_bone, "bi_slot_id", -1))
        explicit_mesh_key = str(getattr(pose_bone, "bi_mesh_key", "") or "")
        if explicit_slot != int(slot_id):
            continue
        if explicit_mesh_key and explicit_mesh_key != draw_object_name:
            continue
        return pose_bone.name

    return ""


def _parse_explicit_slot_map(draw_part, fallback_armature) -> tuple[BoneSlotBinding, ...]:
    raw_json = str(getattr(draw_part, "bone_slot_map_json", "") or "").strip()
    if not raw_json:
        return ()
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Bone Slot Map JSON for {draw_part.draw_key}: {exc}") from exc
    if isinstance(payload, dict):
        payload = payload.get("bindings", [])
    if not isinstance(payload, list):
        raise ValueError(f"Bone Slot Map for {draw_part.draw_key} must be a JSON list or an object with bindings")

    bindings = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError(f"Bone Slot Map row for {draw_part.draw_key} must be an object")
        slot_id = int(row.get("slot_id", row.get("slot", -1)))
        if slot_id < 0:
            raise ValueError(f"Bone Slot Map row for {draw_part.draw_key} is missing slot_id")
        source_armature_name = str(row.get("source_armature", "") or "")
        source_armature = bpy.data.objects.get(source_armature_name) if source_armature_name else fallback_armature
        source_bone = str(row.get("source_bone", row.get("bone_name", "")) or "")
        if not source_bone:
            raise ValueError(f"Bone Slot Map slot {slot_id} for {draw_part.draw_key} is missing source_bone")
        if not _pose_bone_exists(source_armature, source_bone):
            source_name = source_armature.name if source_armature is not None else "<none>"
            raise ValueError(f"Source bone not found for {draw_part.draw_key} slot {slot_id}: {source_name}/{source_bone}")
        bindings.append(
            BoneSlotBinding(
                slot_id=slot_id,
                source_armature=source_armature,
                source_bone=source_bone,
                target_name=str(row.get("target_name", "") or ""),
            )
        )
    return tuple(sorted(bindings, key=lambda item: item.slot_id))


def resolve_bone_slot_bindings(draw_part, require_complete: bool = True) -> tuple[BoneSlotBinding, ...]:
    """Resolve final target-slot to source-bone bindings for a DrawPart."""
    if not bool(getattr(draw_part, "bone_enabled", True)):
        return ()
    slot_contract = resolve_slot_contract(draw_part)
    source_armature = getattr(draw_part, "bone_source_armature", None) or getattr(draw_part, "proxy_armature", None)
    explicit_bindings = _parse_explicit_slot_map(draw_part, source_armature)
    explicit_by_slot = {binding.slot_id: binding for binding in explicit_bindings}

    bindings = []
    missing_slots = []
    for slot_id in slot_contract.slot_ids:
        explicit_binding = explicit_by_slot.get(slot_id)
        if explicit_binding is not None:
            bindings.append(explicit_binding)
            continue
        source_bone = _find_source_bone_for_slot(source_armature, draw_part, int(slot_id))
        if not source_bone:
            missing_slots.append(slot_id)
            continue
        bindings.append(
            BoneSlotBinding(
                slot_id=int(slot_id),
                source_armature=source_armature,
                source_bone=source_bone,
                target_name=f"{slot_id}__{draw_part.source_object.name}",
            )
        )

    if require_complete and missing_slots:
        source_name = source_armature.name if source_armature is not None else "<none>"
        preview = ", ".join(str(slot_id) for slot_id in missing_slots[:16])
        if len(missing_slots) > 16:
            preview += ", ..."
        raise ValueError(
            f"DrawPart {draw_part.draw_key} has no source bone for slot(s): {preview}. "
            f"Bone Source: {source_name}. Configure Bone Slot Map JSON or use a matching proxy armature."
        )
    return tuple(sorted(bindings, key=lambda item: item.slot_id))


def serialize_slot_bindings(bindings: tuple[BoneSlotBinding, ...]) -> list[dict]:
    return [
        {
            "slot_id": int(binding.slot_id),
            "source_armature": binding.source_armature.name,
            "source_bone": binding.source_bone,
            "target_name": binding.target_name,
        }
        for binding in bindings
    ]
