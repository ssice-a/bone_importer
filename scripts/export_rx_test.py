"""Export the current RX scene into a manifest-driven runtime package.

This script is intentionally scene-specific for the current RX validation pass:
it exports every draw part carried by the shared proxy armature, while using the
prepared RXEXP replacement meshes for the face and eyelash/eyebrow geometry.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

import bpy


REPO_PARENT = r"E:\vscode"
DEFAULT_OUTPUT_DIR = r"E:\XXMI\EFMI\Mods\RX"
OUTPUT_DIR = os.environ.get("RX_EXPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
BMC_CAPTURE_MANIFEST = r"E:\XXMI\EFMI\Mods\lxi\capture_manifest.json"
DEFAULT_FRAME_START = 0
DEFAULT_FRAME_END = 5670
DEFAULT_FRAME_STEP = 1

SOURCE_COLLECTION_NAME = "BMC Export Sources"
PROXY_ARMATURE_NAME = "RX_SharedProxy"
RUNTIME_COLLECTION_NAME = "RX Runtime DrawParts"
GEOMETRY_EXPORT_COLLECTION_NAME = "RX Geometry Export Current"

REPLACEMENT_GEOMETRY = {
    "e78c7068-10590-0": {
        "geometry_object": "RXEXP_e78c7068-10590-0_000_\u9762.001",
        "vb_profile": "PACKED16",
        "cb1": "NONE",
    },
    "2009f0d6-1356-0": {
        "geometry_object": "RXEXP_2009f0d6-1356-0_005_\u776b\u7709.001",
        "vb_profile": "PNTA40",
        "cb1": "EYELASH",
    },
}


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "")
    if not raw_value:
        return int(default)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw_value!r}") from exc


def _write_json(path: str, payload: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as json_file:
        json.dump(payload, json_file, indent=2, ensure_ascii=False)
        json_file.write("\n")


def _register_addon():
    if REPO_PARENT not in sys.path:
        sys.path.insert(0, REPO_PARENT)

    import bone_importer

    try:
        bone_importer.unregister()
    except Exception:
        pass
    bone_importer.register()
    return bone_importer


def _remove_collection(collection_name: str):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        return
    for child in list(collection.children):
        _remove_collection(child.name)
    for obj in list(collection.objects):
        collection.objects.unlink(obj)
    bpy.data.collections.remove(collection)


def _new_collection(name: str, parent=None):
    _remove_collection(name)
    collection = bpy.data.collections.new(name)
    if parent is None:
        bpy.context.scene.collection.children.link(collection)
    else:
        parent.children.link(collection)
    return collection


def _link_object_once(collection, obj):
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def _geometry_key(record: dict) -> str:
    return f"{record.get('ib_hash', '')}-{int(record.get('match_index_count', 0) or 0)}-{int(record.get('match_first_index', 0) or 0)}"


def _collect_runtime_targets():
    from bone_importer.core.draw_part import parse_draw_part_name

    source_collection = bpy.data.collections.get(SOURCE_COLLECTION_NAME)
    if source_collection is None:
        raise RuntimeError(f"Source collection not found: {SOURCE_COLLECTION_NAME}")

    proxy_armature = bpy.data.objects.get(PROXY_ARMATURE_NAME)
    if proxy_armature is None or proxy_armature.type != "ARMATURE":
        raise RuntimeError(f"Proxy armature not found: {PROXY_ARMATURE_NAME}")

    targets = {}
    for obj in source_collection.objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        try:
            parse_draw_part_name(obj.name)
        except ValueError:
            continue
        if obj.parent == proxy_armature or obj.name in REPLACEMENT_GEOMETRY:
            targets[obj.name] = obj

    missing = sorted(set(REPLACEMENT_GEOMETRY) - set(targets))
    if missing:
        raise RuntimeError(f"Replacement target DrawPart(s) not found: {', '.join(missing)}")
    if not targets:
        raise RuntimeError("No RX runtime draw parts found")
    return targets


def _export_geometry_with_rx(runtime_targets: dict):
    from bone_importer.core.rx_geometry_export.prepare import prepare_geometry_export_collection

    root = _new_collection(GEOMETRY_EXPORT_COLLECTION_NAME)
    exported_targets = {}
    for target_name, config in REPLACEMENT_GEOMETRY.items():
        if target_name not in runtime_targets:
            continue
        source = bpy.data.objects.get(config["geometry_object"])
        if source is None or source.type != "MESH":
            raise RuntimeError(f"Replacement geometry mesh not found: {config['geometry_object']}")
        region = bpy.data.collections.new(target_name)
        root.children.link(region)
        _link_object_once(region, source)
        exported_targets[target_name] = source

    result = prepare_geometry_export_collection(
        context=bpy.context,
        source_collection=root,
        output_dir=OUTPUT_DIR,
        capture_manifest_path=BMC_CAPTURE_MANIFEST,
    )
    with open(result["manifest_path"], "r", encoding="utf-8") as manifest_file:
        bmc_manifest = json.load(manifest_file)

    records_by_key = {
        _geometry_key(record): record
        for record in bmc_manifest.get("geometry_buffers", [])
    }
    missing_records = [target_name for target_name in exported_targets if target_name not in records_by_key]
    if missing_records:
        raise RuntimeError(f"BMC geometry export missing target(s): {', '.join(missing_records)}")

    return {
        "result": result,
        "geometry_objects": exported_targets,
        "geometry_records": [records_by_key[target_name] for target_name in exported_targets],
    }


def _configure_geometry_draw_part(target, config, geometry_record, geometry_object):
    vb0_record = dict(geometry_record.get("vertex_buffers", {}).get("vb0", {}) or {})
    if not vb0_record.get("file_path"):
        raise RuntimeError(f"{target.name}: BMC geometry export has no vb0 Position buffer")

    target.bi_morph_enabled = True
    if getattr(target, "bi_morph_source_object", None) is None:
        target.bi_morph_source_object = geometry_object
    target.bi_base_position_path = vb0_record["file_path"]
    target.bi_base_position_stride = int(vb0_record.get("stride", 0) or 0)
    target.bi_vb_layout_profile = config["vb_profile"]
    target.bi_cb1_profile = config["cb1"]

    if not str(getattr(target, "bi_bone_slot_map_json", "") or "").strip():
        raise RuntimeError(
            f"{target.name}: replacement geometry requires an explicit Bone Slot Map JSON "
            "so exported vb2 indices match the exported bone palette"
        )
    target.bi_skin_contract = "EXPLICIT_SLOT_MAP"


def _configure_runtime_draw_parts(geometry_export, runtime_targets: dict):
    scene = bpy.context.scene
    runtime_collection = _new_collection(RUNTIME_COLLECTION_NAME)
    scene.bi_export_collection = runtime_collection
    scene.bi_animation_output_dir = OUTPUT_DIR
    scene.bi_animation_clip_name = "rxanimin"
    scene.bi_animation_clip_id = 0
    scene.bi_animation_frame_start = _env_int("RX_EXPORT_FRAME_START", DEFAULT_FRAME_START)
    scene.bi_animation_frame_end = _env_int("RX_EXPORT_FRAME_END", DEFAULT_FRAME_END)
    scene.bi_animation_frame_step = max(_env_int("RX_EXPORT_FRAME_STEP", DEFAULT_FRAME_STEP), 1)
    scene.bi_animation_fps = float(scene.render.fps or 30)
    scene.bi_morph_include_normals = True
    scene.bi_morph_include_tangents = True

    geometry_by_key = {_geometry_key(record): record for record in geometry_export["geometry_records"]}
    configured = {}
    for target_name, target in sorted(runtime_targets.items()):
        _link_object_once(runtime_collection, target)
        target.bi_bone_enabled = True
        target.bi_match_priority = 50

        if target_name in REPLACEMENT_GEOMETRY:
            config = REPLACEMENT_GEOMETRY[target_name]
            geometry_record = geometry_by_key[target_name]
            geometry_object = geometry_export["geometry_objects"][target_name]
            _configure_geometry_draw_part(target, config, geometry_record, geometry_object)
            geometry_info = {
                "geometry_object": geometry_object.name,
                "base_position": target.bi_base_position_path,
                "base_position_stride": int(target.bi_base_position_stride),
                "index_count": int(geometry_record.get("index_buffer", {}).get("index_count", 0) or 0),
                "vb_slots": sorted(geometry_record.get("vertex_buffers", {}).keys()),
            }
        else:
            target.bi_morph_enabled = False
            target.bi_base_position_path = ""
            target.bi_base_position_stride = 0
            target.bi_vb_layout_profile = "AUTO"
            target.bi_cb1_profile = "NONE"
            geometry_info = {}

        configured[target_name] = {
            "proxy_armature": getattr(target, "bi_proxy_armature_name", ""),
            "bone_source_armature": (
                target.bi_bone_source_armature.name
                if getattr(target, "bi_bone_source_armature", None) is not None
                else ""
            ),
            "skin_contract": str(getattr(target, "bi_skin_contract", "")),
            "morph_enabled": bool(getattr(target, "bi_morph_enabled", False)),
            "morph_source": (
                target.bi_morph_source_object.name
                if getattr(target, "bi_morph_source_object", None) is not None
                else ""
            ),
            "cb1_profile": str(getattr(target, "bi_cb1_profile", "")),
            **geometry_info,
        }
    return configured


def _reset_rx_manifest():
    for file_name in ("rx_export_manifest.json", "rxanimin.ini"):
        path = os.path.join(OUTPUT_DIR, file_name)
        if os.path.exists(path):
            os.remove(path)


def main():
    total_start = time.perf_counter()
    timings = {}
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stage_start = time.perf_counter()
    _reset_rx_manifest()
    _register_addon()
    timings["setup_seconds"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    runtime_targets = _collect_runtime_targets()
    timings["collect_runtime_targets_seconds"] = time.perf_counter() - stage_start
    stage_start = time.perf_counter()
    geometry_export = _export_geometry_with_rx(runtime_targets)
    timings["geometry_export_seconds"] = time.perf_counter() - stage_start
    stage_start = time.perf_counter()
    configured = _configure_runtime_draw_parts(geometry_export, runtime_targets)
    timings["configure_draw_parts_seconds"] = time.perf_counter() - stage_start

    from bone_importer.core.draw_part import build_target_draw_parts
    from bone_importer.core.manifest import write_export_manifest
    from bone_importer.core.workflow import (
        export_bone_payloads_for_selected_draw_parts,
        export_morph_for_selected_proxy_armatures,
    )

    scene = bpy.context.scene
    stage_start = time.perf_counter()
    draw_parts = build_target_draw_parts(bpy.context)
    timings["build_draw_parts_seconds"] = time.perf_counter() - stage_start
    stage_start = time.perf_counter()
    write_export_manifest(
        output_directory=scene.bi_animation_output_dir,
        clip_name=scene.bi_animation_clip_name,
        clip_id=scene.bi_animation_clip_id,
        draw_parts=draw_parts,
        geometry_results=tuple(geometry_export["geometry_records"]),
    )
    timings["seed_manifest_seconds"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    bone_result = export_bone_payloads_for_selected_draw_parts(
        bpy.context,
        output_directory=scene.bi_animation_output_dir,
        clip_name=scene.bi_animation_clip_name,
        clip_id=scene.bi_animation_clip_id,
        frame_start=scene.bi_animation_frame_start,
        frame_end=scene.bi_animation_frame_end,
        frame_step=scene.bi_animation_frame_step,
        fps=scene.bi_animation_fps,
        write_metadata=True,
    )
    timings["bone_export_seconds"] = time.perf_counter() - stage_start
    stage_start = time.perf_counter()
    morph_result = export_morph_for_selected_proxy_armatures(
        bpy.context,
        output_directory=scene.bi_animation_output_dir,
        clip_name=scene.bi_animation_clip_name,
        clip_id=scene.bi_animation_clip_id,
        frame_start=scene.bi_animation_frame_start,
        frame_end=scene.bi_animation_frame_end,
        frame_step=scene.bi_animation_frame_step,
        fps=scene.bi_animation_fps,
        presents_per_step=1,
        default_loop_start=-1,
        default_loop_end=-1,
        write_metadata=True,
    )
    timings["morph_export_seconds"] = time.perf_counter() - stage_start
    total_elapsed = time.perf_counter() - total_start
    timings["total_seconds"] = total_elapsed
    failed = [*list(bone_result.failed_armatures), *list(morph_result.failed_armatures)]
    perf_report_path = os.path.join(OUTPUT_DIR, "rx_export_perf.json")
    perf_report = {
        "format": "rx_export_perf_v1",
        "output_dir": OUTPUT_DIR,
        "clip_name": scene.bi_animation_clip_name,
        "frame_start": int(scene.bi_animation_frame_start),
        "frame_end": int(scene.bi_animation_frame_end),
        "frame_step": int(scene.bi_animation_frame_step),
        "sample_count": int(bone_result.sampled_frames or morph_result.sampled_frames),
        "runtime_targets": len(runtime_targets),
        "draw_parts": len(draw_parts),
        "geometry_records": len(geometry_export["geometry_records"]),
        "exported_bone_parts": bone_result.exported_armatures,
        "total_exported_bones": bone_result.total_exported_bones,
        "exported_morph_meshes": morph_result.exported_morph_meshes,
        "total_morph_channels": morph_result.total_morph_channels,
        "failed": failed,
        "timings_seconds": timings,
        "geometry_performance": dict(geometry_export["result"].get("performance", {}) or {}),
        "bone_performance": dict(bone_result.performance or {}),
        "morph_performance": {
            "elapsed_seconds": float(morph_result.elapsed_seconds),
            "sampled_frames": int(morph_result.sampled_frames),
            "exported_morph_meshes": int(morph_result.exported_morph_meshes),
            "total_morph_channels": int(morph_result.total_morph_channels),
        },
    }
    _write_json(perf_report_path, perf_report)
    payload = {
        "ok": not failed,
        "configured": configured,
        "elapsed_wall": total_elapsed,
        "perf_report": perf_report_path,
        "geometry_manifest": geometry_export["result"]["manifest_path"],
        "geometry_records": len(geometry_export["geometry_records"]),
        "runtime_targets": len(runtime_targets),
        "exported_bone_parts": bone_result.exported_armatures,
        "total_exported_bones": bone_result.total_exported_bones,
        "exported_morph_meshes": morph_result.exported_morph_meshes,
        "total_morph_channels": morph_result.total_morph_channels,
        "sampled_frames": morph_result.sampled_frames,
        "failed": failed,
        "bone_files": list(bone_result.exported_files),
        "morph_files": list(morph_result.exported_files),
        "ini": morph_result.generated_ini_path,
        "timeline": morph_result.timeline_static_path,
        "master": morph_result.master_playback_path,
        "manifest": os.path.join(OUTPUT_DIR, "rx_export_manifest.json"),
    }
    print("RX_EXPORT_RESULT=" + json.dumps(payload, ensure_ascii=False))
    if failed:
        raise RuntimeError("; ".join(failed))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        print("RX_EXPORT_RESULT=" + json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise
