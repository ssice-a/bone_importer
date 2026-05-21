"""RX Export v3 collection planner.

This module is Blender-light on purpose. It accepts collection-like objects
with ``name``, ``objects`` and ``children`` attributes, and mesh-like objects
with ``name`` and ``type`` attributes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable


FINAL_SKIN_SOURCE_GAME = "SOURCE_GAME"
FINAL_SKIN_OWN = "OWN"

DEFORM_NONE = "NONE"
DEFORM_MORPH = "MORPH"
DEFORM_PRESKIN_BONE = "PRESKIN_BONE"
DEFORM_MORPH_THEN_PRESKIN_BONE = "MORPH_THEN_PRESKIN_BONE"


_DRAW_PART_RE = re.compile(r"(?P<hash>[0-9A-Fa-f]{8})[-_](?P<count>\d+)[-_](?P<first>\d+)")
_PART_RE = re.compile(r"^part(?P<index>\d+)(?:\D.*)?$", re.IGNORECASE)


class RXExportPlanError(ValueError):
    """Raised when an RX export collection cannot be represented safely."""


@dataclass(frozen=True)
class MeshRouteAnalysis:
    """Route-relevant data collected from one mesh object."""

    source_slots: tuple[int, ...] = ()
    own_bones: tuple[str, ...] = ()
    morph_payload_enabled: bool = False
    preskin_bone_enabled: bool = False
    force_replace_geometry: bool = False
    final_skin_override: str = ""
    final_armature: str = ""
    final_armature_ref: object | None = None
    preskin_armature: str = ""
    preskin_armature_ref: object | None = None
    preskin_action: str = ""


@dataclass(frozen=True)
class DrawPartIdentity:
    ib_hash: str
    match_index_count: int
    first_index: int
    collection_name: str

    @property
    def draw_key(self) -> str:
        return f"{self.ib_hash}_{self.match_index_count}_{self.first_index}"


@dataclass(frozen=True)
class DrawSegmentPlan:
    object_name: str
    object_ref: object
    segment_index: int
    final_skin_palette: str
    geometry_required: bool
    deform_chain: str = DEFORM_NONE
    source_slots: tuple[int, ...] = ()
    own_bones: tuple[str, ...] = ()
    final_armature: str = ""
    preskin_armature: str = ""
    final_armature_ref: object | None = None
    preskin_armature_ref: object | None = None
    preskin_action: str = ""
    vertex_start: int = 0
    vertex_count: int = 0
    index_start: int = 0
    index_count: int = 0


@dataclass(frozen=True)
class PartPlan:
    identity: DrawPartIdentity
    part_index: int
    source_part_name: str
    segments: tuple[DrawSegmentPlan, ...]
    generated: bool = False
    split_reason: str = ""

    @property
    def part_name(self) -> str:
        return f"part{self.part_index:02d}"


@dataclass(frozen=True)
class DrawPartPlan:
    identity: DrawPartIdentity
    parts: tuple[PartPlan, ...]
    skip_original: bool


@dataclass(frozen=True)
class RXExportPlan:
    root_collection_name: str
    draw_parts: tuple[DrawPartPlan, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _PartSource:
    identity: DrawPartIdentity
    part_index: int
    source_part_name: str
    mesh_objects: tuple[object, ...]


def build_rx_export_plan(
    root_collection,
    analyze_mesh: Callable[[object], MeshRouteAnalysis],
) -> RXExportPlan:
    """Build an RX Export v3 plan from an export collection tree."""

    if root_collection is None:
        raise RXExportPlanError("RX export root collection is not set")

    part_sources: list[_PartSource] = []
    for child in getattr(root_collection, "children", []) or []:
        identity = parse_draw_part_identity(str(getattr(child, "name", "") or ""))
        if identity is None:
            continue
        part_sources.extend(_collect_part_sources(child, identity))

    if not part_sources:
        raise RXExportPlanError("No IB collections found under RX export root")

    parts_by_draw_key: dict[str, list[PartPlan]] = {}
    identity_by_draw_key: dict[str, DrawPartIdentity] = {}
    for source in part_sources:
        part = _part_plan_from_source(source, analyze_mesh)
        parts_by_draw_key.setdefault(source.identity.draw_key, []).append(part)
        identity_by_draw_key[source.identity.draw_key] = source.identity

    draw_parts: list[DrawPartPlan] = []
    for draw_key in sorted(parts_by_draw_key):
        parts = tuple(sorted(parts_by_draw_key[draw_key], key=lambda part: part.part_index))
        skip_original = any(segment.geometry_required for part in parts for segment in part.segments)
        draw_parts.append(DrawPartPlan(identity=identity_by_draw_key[draw_key], parts=parts, skip_original=skip_original))

    return RXExportPlan(
        root_collection_name=str(getattr(root_collection, "name", "") or ""),
        draw_parts=tuple(draw_parts),
    )


def parse_draw_part_identity(collection_name: str) -> DrawPartIdentity | None:
    match = _DRAW_PART_RE.search(str(collection_name or ""))
    if not match:
        return None
    return DrawPartIdentity(
        ib_hash=match.group("hash").lower(),
        match_index_count=int(match.group("count")),
        first_index=int(match.group("first")),
        collection_name=str(collection_name or ""),
    )


def parse_part_index(collection_name: str) -> int | None:
    match = _PART_RE.match(str(collection_name or "").strip())
    if not match:
        return None
    return int(match.group("index"))


def _collect_part_sources(region_collection, identity: DrawPartIdentity) -> list[_PartSource]:
    direct_meshes = tuple(obj for obj in getattr(region_collection, "objects", []) or [] if _is_mesh_object(obj))
    explicit_parts: dict[int, object] = {}
    non_part_children: list[object] = []

    for child in getattr(region_collection, "children", []) or []:
        part_index = parse_part_index(str(getattr(child, "name", "") or ""))
        if part_index is None:
            non_part_children.append(child)
            continue
        if part_index in explicit_parts:
            raise RXExportPlanError(f"{identity.collection_name}: duplicate part{part_index:02d} collection")
        explicit_parts[part_index] = child

    invalid_children = [
        str(getattr(child, "name", "") or "")
        for child in non_part_children
        if any(True for _obj in _iter_meshes_recursive(child))
    ]
    if invalid_children:
        raise RXExportPlanError(
            f"{identity.collection_name}: child collection(s) with meshes must be named partNN: "
            + ", ".join(invalid_children[:5])
        )

    if explicit_parts:
        if direct_meshes:
            names = ", ".join(str(getattr(obj, "name", "") or "") for obj in direct_meshes[:5])
            raise RXExportPlanError(
                f"{identity.collection_name}: direct mesh object(s) are not allowed when partNN collections exist. "
                f"Move them into part00: {names}"
            )
        sources: list[_PartSource] = []
        for part_index, part_collection in sorted(explicit_parts.items()):
            meshes = tuple(_iter_meshes_recursive(part_collection))
            if meshes:
                sources.append(
                    _PartSource(
                        identity=identity,
                        part_index=part_index,
                        source_part_name=str(getattr(part_collection, "name", "") or f"part{part_index:02d}"),
                        mesh_objects=meshes,
                    )
                )
        return sources

    if not direct_meshes:
        return []
    return [
        _PartSource(
            identity=identity,
            part_index=0,
            source_part_name="part00",
            mesh_objects=direct_meshes,
        )
    ]


def _part_plan_from_source(source: _PartSource, analyze_mesh: Callable[[object], MeshRouteAnalysis]) -> PartPlan:
    segments: list[DrawSegmentPlan] = []
    for segment_index, mesh_obj in enumerate(source.mesh_objects):
        analysis = _normalize_analysis(analyze_mesh(mesh_obj))
        final_skin = _resolve_final_skin(mesh_obj, analysis)
        deform_chain = _resolve_deform_chain(analysis)
        geometry_required = (
            final_skin == FINAL_SKIN_OWN
            or bool(analysis.morph_payload_enabled)
            or bool(analysis.preskin_bone_enabled)
            or bool(analysis.force_replace_geometry)
        )
        segments.append(
            DrawSegmentPlan(
                object_name=str(getattr(mesh_obj, "name", "") or ""),
                object_ref=mesh_obj,
                segment_index=segment_index,
                final_skin_palette=final_skin,
                geometry_required=geometry_required,
                deform_chain=deform_chain,
                source_slots=analysis.source_slots,
                own_bones=analysis.own_bones,
                final_armature=analysis.final_armature,
                preskin_armature=analysis.preskin_armature,
                final_armature_ref=analysis.final_armature_ref,
                preskin_armature_ref=analysis.preskin_armature_ref,
                preskin_action=analysis.preskin_action,
            )
        )
    if not segments:
        raise RXExportPlanError(f"{source.identity.collection_name}/{source.source_part_name}: no mesh objects found")
    return PartPlan(
        identity=source.identity,
        part_index=source.part_index,
        source_part_name=source.source_part_name,
        segments=tuple(segments),
    )


def _normalize_analysis(analysis: MeshRouteAnalysis) -> MeshRouteAnalysis:
    return MeshRouteAnalysis(
        source_slots=tuple(sorted({int(slot) for slot in analysis.source_slots if int(slot) >= 0})),
        own_bones=tuple(str(bone) for bone in analysis.own_bones if str(bone)),
        morph_payload_enabled=bool(analysis.morph_payload_enabled),
        preskin_bone_enabled=bool(analysis.preskin_bone_enabled),
        force_replace_geometry=bool(analysis.force_replace_geometry),
        final_skin_override=str(analysis.final_skin_override or "").upper(),
        final_armature=str(analysis.final_armature or ""),
        final_armature_ref=analysis.final_armature_ref,
        preskin_armature=str(analysis.preskin_armature or ""),
        preskin_armature_ref=analysis.preskin_armature_ref,
        preskin_action=str(analysis.preskin_action or ""),
    )


def _resolve_final_skin(mesh_obj, analysis: MeshRouteAnalysis) -> str:
    if analysis.final_skin_override in {FINAL_SKIN_SOURCE_GAME, FINAL_SKIN_OWN}:
        final_skin = analysis.final_skin_override
    elif analysis.source_slots and not analysis.own_bones:
        final_skin = FINAL_SKIN_SOURCE_GAME
    elif analysis.own_bones and not analysis.source_slots:
        final_skin = FINAL_SKIN_OWN
    elif analysis.source_slots and analysis.own_bones:
        raise RXExportPlanError(
            f"{getattr(mesh_obj, 'name', '')}: both SOURCE_GAME and OWN final skin are possible; choose Final Skin explicitly"
        )
    else:
        raise RXExportPlanError(f"{getattr(mesh_obj, 'name', '')}: no usable final skin vertex groups found")

    if analysis.preskin_bone_enabled:
        if final_skin != FINAL_SKIN_SOURCE_GAME:
            raise RXExportPlanError(f"{getattr(mesh_obj, 'name', '')}: PreSkinBone requires SOURCE_GAME final skin")
        if not analysis.source_slots:
            raise RXExportPlanError(f"{getattr(mesh_obj, 'name', '')}: PreSkinBone requires SOURCE_GAME final groups")
    return final_skin


def _resolve_deform_chain(analysis: MeshRouteAnalysis) -> str:
    if analysis.morph_payload_enabled and analysis.preskin_bone_enabled:
        return DEFORM_MORPH_THEN_PRESKIN_BONE
    if analysis.morph_payload_enabled:
        return DEFORM_MORPH
    if analysis.preskin_bone_enabled:
        return DEFORM_PRESKIN_BONE
    return DEFORM_NONE


def _iter_meshes_recursive(collection):
    seen: set[str] = set()

    def walk(current_collection):
        for obj in getattr(current_collection, "objects", []) or []:
            if not _is_mesh_object(obj):
                continue
            name = str(getattr(obj, "name", "") or "")
            if name in seen:
                continue
            seen.add(name)
            yield obj
        for child in getattr(current_collection, "children", []) or []:
            yield from walk(child)

    yield from walk(collection)


def _is_mesh_object(obj) -> bool:
    return str(getattr(obj, "type", "") or "") == "MESH"
