"""Slot contract and Bone Slot Map resolution for RX DrawParts.

Slot ids are runtime namespace ids.  Imported game meshes may be mirrored in
Blender for editing, so automatic Target Numeric Groups must adapt from runtime
slots to mirrored source bones.  Explicit Bone Slot Map JSON always wins.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

import bpy

from .coordinate_contract import resolve_object_mirror_x


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


def _vertex_group_slot_centroids(obj, slot_ids: tuple[int, ...]) -> dict[int, object]:
    if obj is None or getattr(obj, "type", "") != "MESH":
        return {}
    try:
        from mathutils import Vector
    except Exception:
        return {}

    wanted = {int(slot_id) for slot_id in slot_ids}
    group_indices_by_slot: dict[int, set[int]] = {}
    for vertex_group in getattr(obj, "vertex_groups", []) or ():
        try:
            slot_id = parse_slot_id(vertex_group.name)
        except ValueError:
            continue
        if slot_id not in wanted:
            continue
        group_indices_by_slot.setdefault(slot_id, set()).add(int(vertex_group.index))

    if not group_indices_by_slot:
        return {}

    matrix_world = getattr(obj, "matrix_world", None)
    centroids = {}
    vertices = getattr(getattr(obj, "data", None), "vertices", []) or ()
    for slot_id, group_indices in group_indices_by_slot.items():
        total_weight = 0.0
        weighted_sum = Vector((0.0, 0.0, 0.0))
        for vertex in vertices:
            weight = 0.0
            for group_element in getattr(vertex, "groups", []) or ():
                if int(group_element.group) in group_indices:
                    weight += float(group_element.weight)
            if weight <= 0.0:
                continue
            co = vertex.co
            if matrix_world is not None:
                co = matrix_world @ co
            weighted_sum += co * weight
            total_weight += weight
        if total_weight > 1e-8:
            centroids[slot_id] = weighted_sum / total_weight
    return centroids


def _centroid_bounds_diagonal(centroids: dict[int, object]) -> float:
    if not centroids:
        return 0.0
    values = list(centroids.values())
    min_x = min(float(value.x) for value in values)
    min_y = min(float(value.y) for value in values)
    min_z = min(float(value.z) for value in values)
    max_x = max(float(value.x) for value in values)
    max_y = max(float(value.y) for value in values)
    max_z = max(float(value.z) for value in values)
    dx = max_x - min_x
    dy = max_y - min_y
    dz = max_z - min_z
    return float((dx * dx + dy * dy + dz * dz) ** 0.5)


def _should_adapt_import_mirrored_numeric_slots(draw_part, slot_contract: SlotContract) -> bool:
    if slot_contract.source != "target_numeric_groups":
        return False
    if str(getattr(draw_part, "bone_slot_map_json", "") or "").strip():
        return False
    source_object = getattr(draw_part, "source_object", None)
    return bool(resolve_object_mirror_x(source_object, False))


def _build_import_mirror_slot_map(draw_part, slot_contract: SlotContract) -> dict[int, int]:
    """Map runtime target slots to the mirrored Blender-side source slots.

    This is not a runtime slot-id semantic swap.  It is an importer adapter:
    BMC-style imports mirror vertex positions on Blender X, so the Blender bone
    carrying a target slot's authored motion may live on the opposite side.
    """

    if not _should_adapt_import_mirrored_numeric_slots(draw_part, slot_contract):
        return {}

    centroids = _vertex_group_slot_centroids(getattr(draw_part, "source_object", None), slot_contract.slot_ids)
    if len(centroids) <= 1:
        return {}

    diagonal = _centroid_bounds_diagonal(centroids)
    max_distance = max(0.025, diagonal * 0.045)
    candidates = []
    for target_slot, target_centroid in centroids.items():
        mirrored_x = -float(target_centroid.x)
        mirrored_y = float(target_centroid.y)
        mirrored_z = float(target_centroid.z)
        for source_slot, source_centroid in centroids.items():
            dx = float(source_centroid.x) - mirrored_x
            dy = float(source_centroid.y) - mirrored_y
            dz = float(source_centroid.z) - mirrored_z
            distance = float((dx * dx + dy * dy + dz * dz) ** 0.5)
            candidates.append((distance, int(target_slot), int(source_slot)))

    candidates.sort(key=lambda item: item[0])
    used_targets = set()
    used_sources = set()
    mapping: dict[int, int] = {}
    for distance, target_slot, source_slot in candidates:
        if target_slot in used_targets or source_slot in used_sources:
            continue
        if target_slot != source_slot and distance > max_distance:
            continue
        used_targets.add(target_slot)
        used_sources.add(source_slot)
        mapping[target_slot] = source_slot

    return {
        int(slot_id): int(mapping.get(int(slot_id), int(slot_id)))
        for slot_id in slot_contract.slot_ids
    }


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
    mirror_slot_map = _build_import_mirror_slot_map(draw_part, slot_contract)

    bindings = []
    missing_slots = []
    for slot_id in slot_contract.slot_ids:
        explicit_binding = explicit_by_slot.get(slot_id)
        if explicit_binding is not None:
            bindings.append(explicit_binding)
            continue
        source_slot_id = mirror_slot_map.get(int(slot_id), int(slot_id))
        source_bone = _find_source_bone_for_slot(source_armature, draw_part, int(source_slot_id))
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
