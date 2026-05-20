"""Minimal RX geometry export wrapper around the vendored buffer writer."""

from __future__ import annotations

import os
import time

from .export_buffers import write_part_geometry_buffers
from .export_package import BI4_MAX_BONE_COUNT, build_export_plan, write_part_palette_files
from .io import ensure_directory, read_json, write_json
from .vertex_groups import collect_weighted_numeric_vertex_groups


BUFFER_EXPORT_DIR_NAME = "Buffer"
CAPTURE_MANIFEST_FILE_NAME = "capture_manifest.json"
EXPORT_MANIFEST_FILE_NAME = "export_manifest.json"


def prepare_geometry_export_collection(
    context,
    source_collection,
    output_dir: str,
    capture_manifest_path: str | None = None,
    *,
    max_bones_per_part: int = BI4_MAX_BONE_COUNT,
):
    """Export only RX-needed ib/vb geometry buffers from a region collection tree."""
    if source_collection is None:
        raise ValueError("Export source collection is not set")

    total_start = time.perf_counter()
    timings: dict[str, float] = {}

    stage_start = time.perf_counter()
    normalized_output_dir = ensure_directory(output_dir)
    buffer_dir = ensure_directory(os.path.join(normalized_output_dir, BUFFER_EXPORT_DIR_NAME))
    timings["setup"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    export_plan = build_export_plan(
        source_collection,
        _collect_used_numeric_vertex_groups,
        max_bones_per_part=max_bones_per_part,
    )
    timings["plan"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    capture_manifest = _read_capture_manifest_for_export(normalized_output_dir, capture_manifest_path)
    timings["capture_manifest"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    palette_records = write_part_palette_files(buffer_dir, export_plan)
    timings["palettes"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    geometry_records = write_part_geometry_buffers(
        buffer_dir,
        export_plan.parts,
        dict(capture_manifest.get("vertex_layout_table", {}) or {}),
        mirror_flip_default=bool(getattr(context.scene, "bmc_mirror_flip", True)),
        uv_mirror_u_default=bool(getattr(context.scene, "bmc_uv_mirror_u", False)),
        uv_flip_v_default=bool(getattr(context.scene, "bmc_uv_flip_v", True)),
    )
    timings["geometry"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    object_records = []
    for part in export_plan.parts:
        for usage in part.object_usages:
            object_records.append(
                {
                    "object": usage.name,
                    "region_collection": part.region.collection_name,
                    "part_name": part.part_name,
                    "host_ib_hash": part.region.ib_hash,
                    "host_match_first_index": part.region.match_first_index,
                    "host_match_index_count": part.region.match_index_count,
                    "part_index": part.part_index,
                    "palette_file": part.palette_file_name,
                    "local_bone_count": len(part.palette_values),
                    "used_global_groups": list(usage.used_global_groups),
                }
            )

    manifest = {
        "format": "rx_geometry_export_v1",
        "export_source_collection": source_collection.name,
        "export_collection": source_collection.name,
        "buffer_dir": buffer_dir,
        "palettes": palette_records,
        "geometry_buffers": _public_geometry_records(geometry_records),
        "export_options": {
            "mirror_flip": bool(getattr(context.scene, "bmc_mirror_flip", True)),
            "uv_mirror_u": bool(getattr(context.scene, "bmc_uv_mirror_u", False)),
            "uv_flip_v": bool(getattr(context.scene, "bmc_uv_flip_v", True)),
            "max_bones_per_part": int(max_bones_per_part),
        },
        "objects": object_records,
        "warnings": list(export_plan.warnings),
        "note": (
            "RX-local geometry export writes ib/vb buffers only. Runtime INI, "
            "materials, LOD chains, and toggle draw sets are intentionally omitted."
        ),
    }
    manifest_path = write_json(os.path.join(normalized_output_dir, EXPORT_MANIFEST_FILE_NAME), manifest, compact=True)
    timings["manifest"] = time.perf_counter() - stage_start

    timings["total"] = time.perf_counter() - total_start
    return {
        "manifest_path": manifest_path,
        "export_collection_name": source_collection.name,
        "output_dir": normalized_output_dir,
        "buffer_dir": buffer_dir,
        "objects": len(object_records),
        "palettes": len(palette_records),
        "warnings": list(export_plan.warnings),
        "timings": {name: round(seconds, 3) for name, seconds in timings.items()},
        "performance": {
            "geometry": _geometry_performance_summary(geometry_records),
        },
    }


def _read_capture_manifest_for_export(output_dir: str, capture_manifest_path: str | None) -> dict:
    manifest_path = os.path.abspath(capture_manifest_path or "") if capture_manifest_path else ""
    if not manifest_path or not os.path.exists(manifest_path):
        manifest_path = os.path.join(output_dir, CAPTURE_MANIFEST_FILE_NAME)
    if not os.path.exists(manifest_path):
        raise ValueError("Missing capture_manifest.json; run Analyze Main/Build Pool before export")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("capture_manifest.json is not an object")
    return manifest


def _collect_used_numeric_vertex_groups(mesh_obj) -> set[int]:
    used_groups = collect_weighted_numeric_vertex_groups(mesh_obj)
    if not used_groups:
        raise ValueError(f"{mesh_obj.name}: no weighted numeric vertex groups found")
    return used_groups


def _public_geometry_records(geometry_records: list[dict]) -> list[dict]:
    public_records: list[dict] = []
    for record in geometry_records:
        public_record = dict(record)
        public_record.pop("stats", None)
        public_record.pop("timings", None)
        public_record.pop("slot_timings", None)
        public_records.append(public_record)
    return public_records


def _geometry_performance_summary(geometry_records: list[dict]) -> dict:
    loop_vertex_count = 0
    index_count = 0
    vb_slot_count = 0
    slot_totals: dict[str, float] = {}
    slowest_parts: list[dict] = []
    for record in geometry_records:
        stats = dict(record.get("stats", {}) or {})
        timings = dict(record.get("timings", {}) or {})
        slot_timings = dict(record.get("slot_timings", {}) or {})
        loop_vertex_count += int(stats.get("loop_vertex_count", 0) or 0)
        index_count += int(stats.get("index_count", 0) or 0)
        vb_slot_count += int(stats.get("vb_slot_count", 0) or 0)
        for slot_name, seconds in slot_timings.items():
            slot_totals[str(slot_name)] = slot_totals.get(str(slot_name), 0.0) + float(seconds or 0.0)
        slowest_parts.append(
            {
                "part": f"{record.get('ib_hash', '')}-{record.get('match_index_count', 0)}-{record.get('match_first_index', 0)}:{record.get('part_name', '')}",
                "objects": list(record.get("object_names", []) or []),
                "loop_vertex_count": int(stats.get("loop_vertex_count", 0) or 0),
                "vb_slot_count": int(stats.get("vb_slot_count", 0) or 0),
                "total_seconds": float(timings.get("total", 0.0) or 0.0),
                "write_vb_seconds": float(timings.get("write_vb", 0.0) or 0.0),
                "collect_loops_seconds": float(timings.get("collect_loops", 0.0) or 0.0),
                "slot_timings": {name: float(value or 0.0) for name, value in slot_timings.items()},
            }
        )
    slowest_parts.sort(key=lambda item: float(item.get("total_seconds", 0.0)), reverse=True)
    sorted_slot_totals = dict(sorted(slot_totals.items(), key=lambda item: item[1], reverse=True))
    return {
        "part_count": len(geometry_records),
        "loop_vertex_count": loop_vertex_count,
        "index_count": index_count,
        "vb_slot_count": vb_slot_count,
        "slot_totals": sorted_slot_totals,
        "slowest_parts": slowest_parts[:10],
    }
