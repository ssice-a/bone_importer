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
BMC_CAPTURE_MANIFEST_CANDIDATES = (
    os.environ.get("RX_BMC_CAPTURE_MANIFEST", ""),
    r"E:\XXMI\EFMI\Mods\DISABLEDlxi\capture_manifest.json",
    r"E:\XXMI\EFMI\Mods\lev\capture_manifest.json",
    r"E:\XXMI\EFMI\Mods\lxi\capture_manifest.json",
)
# The RX validation scene's baked BoneX action is authored on 1..1680.
# Keep these scene-specific defaults out of the stale 0..5670 source action
# range; callers can still override them with RX_EXPORT_FRAME_*.
DEFAULT_FRAME_START = 1
DEFAULT_FRAME_END = 1680
DEFAULT_FRAME_STEP = 1
DEFAULT_TICKS_PER_SAMPLE = 4

SOURCE_COLLECTION_NAME = "BMC Export Sources"
PROXY_ARMATURE_NAME = "RX_SharedProxy"
RUNTIME_COLLECTION_NAME = "RX Runtime DrawParts"
GEOMETRY_EXPORT_COLLECTION_NAME = "RX Geometry Export Current"

REPLACEMENT_GEOMETRY = {
    "e78c7068-10590-0": {
        "geometry_object": "RXEXP_e78c7068-10590-0_000_\u9762.001",
        "morph_source_object": "000_\u9762",
        "vb_profile": "PACKED16",
        "cb1": "NONE",
        "mirror_flip": True,
        "uv_mirror_u": True,
        "uv_flip_v": False,
    },
    "2009f0d6-1356-0": {
        "geometry_object": "RXEXP_2009f0d6-1356-0_005_\u776b\u7709.001",
        "morph_source_object": "005_\u776b\u7709",
        "vb_profile": "PNTA40",
        "cb1": "EYELASH",
        "mirror_flip": True,
        "uv_mirror_u": False,
        "uv_flip_v": False,
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


def _resolve_bmc_capture_manifest() -> str:
    required_layouts = set(REPLACEMENT_GEOMETRY)
    existing_candidates = []
    for candidate in BMC_CAPTURE_MANIFEST_CANDIDATES:
        if not candidate or not os.path.exists(candidate):
            continue
        existing_candidates.append(candidate)
        try:
            with open(candidate, "r", encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
        except Exception:
            continue
        vertex_layout_table = dict(manifest.get("vertex_layout_table", {}) or {})
        if required_layouts.issubset(set(vertex_layout_table)):
            return candidate
    searched = ", ".join(existing_candidates or [candidate for candidate in BMC_CAPTURE_MANIFEST_CANDIDATES if candidate])
    raise RuntimeError(
        "Missing BMC capture_manifest.json with required vertex layouts "
        f"{sorted(required_layouts)}; searched: {searched}"
    )


def _seconds(value) -> str:
    return f"{float(value or 0.0):.3f}s"


def _print_named_timings(title: str, timings: dict, names: tuple[str, ...]):
    print(title)
    for name in names:
        if name in timings:
            print(f"  {name}: {_seconds(timings.get(name))}")


def _print_export_performance(perf_report: dict):
    timings = dict(perf_report.get("timings_seconds", {}) or {})
    bone_perf = dict(perf_report.get("bone_performance", {}) or {})
    bone_timings = dict(bone_perf.get("timings_seconds", {}) or {})
    morph_perf = dict(perf_report.get("morph_performance", {}) or {})

    print("RX_EXPORT_PERFORMANCE_BEGIN")
    print(
        "Summary: "
        f"output={perf_report.get('output_dir', '')} "
        f"frames={perf_report.get('frame_start')}..{perf_report.get('frame_end')} "
        f"step={perf_report.get('frame_step')} "
        f"samples={perf_report.get('sample_count')} "
        f"failed={len(perf_report.get('failed', []) or [])}"
    )
    print(
        "Counts: "
        f"runtime_targets={perf_report.get('runtime_targets')} "
        f"draw_parts={perf_report.get('draw_parts')} "
        f"geometry_records={perf_report.get('geometry_records')} "
        f"bone_parts={perf_report.get('exported_bone_parts')} "
        f"bones={perf_report.get('total_exported_bones')} "
        f"morph_meshes={perf_report.get('exported_morph_meshes')} "
        f"morph_channels={perf_report.get('total_morph_channels')}"
    )
    _print_named_timings(
        "Stages:",
        timings,
        (
            "setup_seconds",
            "collect_runtime_targets_seconds",
            "geometry_export_seconds",
            "configure_draw_parts_seconds",
            "build_draw_parts_seconds",
            "seed_manifest_seconds",
            "bone_export_seconds",
            "morph_export_seconds",
            "total_seconds",
        ),
    )
    _print_named_timings(
        "Bone:",
        bone_timings,
        (
            "prepare_payloads_seconds",
            "bind_auto_refresh_seconds",
            "build_sample_groups_seconds",
            "sample_total_seconds",
            "restore_frame_seconds",
            "write_payloads_seconds",
            "shared_clip_seconds",
            "total_seconds",
        ),
    )
    print(
        "Morph: "
        f"elapsed={_seconds(morph_perf.get('elapsed_seconds'))} "
        f"samples={morph_perf.get('sampled_frames')} "
        f"meshes={morph_perf.get('exported_morph_meshes')} "
        f"channels={morph_perf.get('total_morph_channels')}"
    )
    if bone_perf.get("sample_cache_enabled"):
        print(f"Bone cache: enabled dir={bone_perf.get('sample_cache_dir', '')}")
    else:
        print("Bone cache: disabled")
    sample_isolation = dict(bone_perf.get("sample_isolation", {}) or {})
    print(
        "Bone sampling isolation: "
        f"enabled={bool(sample_isolation.get('enabled', False))} "
        f"reason={sample_isolation.get('skip_reason', '')} "
        f"min_samples={sample_isolation.get('min_sample_count', 0)} "
        f"hidden_meshes={sample_isolation.get('hidden_mesh_count', 0)} "
        f"required_objects={sample_isolation.get('required_object_count', 0)} "
        f"setup={_seconds(sample_isolation.get('seconds'))} "
        f"restore={_seconds(sample_isolation.get('restore_seconds'))}"
    )
    static_bonex_driver_mute = dict(bone_perf.get("static_bonex_driver_mute", {}) or {})
    print(
        "Static Bonex driver mute: "
        f"enabled={bool(static_bonex_driver_mute.get('enabled', False))} "
        f"reason={static_bonex_driver_mute.get('skip_reason', '')} "
        f"static_constraints={static_bonex_driver_mute.get('static_constraint_count', 0)} "
        f"muted={static_bonex_driver_mute.get('muted_constraint_count', 0)} "
        f"setup={_seconds(static_bonex_driver_mute.get('seconds'))} "
        f"restore={_seconds(static_bonex_driver_mute.get('restore_seconds'))}"
    )
    bind_auto_refresh = dict(bone_perf.get("bind_auto_refresh", {}) or {})
    print(
        "Bind auto refresh: "
        f"stale_armatures={bind_auto_refresh.get('stale_armature_count', 0)} "
        f"stale_bones={bind_auto_refresh.get('stale_bone_count', 0)} "
        f"refreshed={len(bind_auto_refresh.get('refreshed_armatures', {}) or {})} "
        f"threshold={bind_auto_refresh.get('threshold', 0)} "
        f"elapsed={_seconds(bind_auto_refresh.get('seconds'))}"
    )
    for group in bone_perf.get("sample_groups", []) or []:
        cache_state = "hit" if group.get("cache_hit") else "miss"
        if not group.get("cache_enabled"):
            cache_state = "off"
        print(
            "Bone sample group: "
            f"name={group.get('sample_group')} "
            f"cache={cache_state} "
            f"mode={group.get('cache_fingerprint_mode', 'off')} "
            f"samples={group.get('sample_count')} "
            f"bones={group.get('unique_bones')} "
            f"pairs={group.get('sample_bone_pairs')} "
            f"frame_set={_seconds(group.get('frame_set_seconds'))} "
            f"pose={_seconds(group.get('pose_sample_seconds'))} "
            f"cache_key={_seconds(group.get('cache_key_seconds'))} "
            f"cache_load={_seconds(group.get('cache_load_seconds'))} "
            f"cache_write={_seconds(group.get('cache_write_seconds'))} "
            f"total={_seconds(group.get('total_seconds'))}"
        )
    print("RX_EXPORT_PERFORMANCE_END")


def _register_addon():
    if REPO_PARENT not in sys.path:
        sys.path.insert(0, REPO_PARENT)

    existing_addon = sys.modules.get("bone_importer")
    if existing_addon is not None:
        try:
            existing_addon.unregister()
        except Exception:
            pass

    for module_name in sorted(
        [name for name in sys.modules if name == "bone_importer" or name.startswith("bone_importer.")],
        key=len,
        reverse=True,
    ):
        sys.modules.pop(module_name, None)

    import bone_importer

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
        source.bi_export_mirror_x = bool(config.get("mirror_flip", True))
        source.bi_export_uv_mirror_u = bool(config.get("uv_mirror_u", False))
        source.bi_export_uv_flip_v = bool(config.get("uv_flip_v", True))
        region = bpy.data.collections.new(target_name)
        root.children.link(region)
        _link_object_once(region, source)
        exported_targets[target_name] = source

    result = prepare_geometry_export_collection(
        context=bpy.context,
        source_collection=root,
        output_dir=OUTPUT_DIR,
        capture_manifest_path=_resolve_bmc_capture_manifest(),
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
    morph_source_name = str(config.get("morph_source_object", "") or "").strip()
    morph_source_object = bpy.data.objects.get(morph_source_name) if morph_source_name else geometry_object
    if morph_source_object is None or morph_source_object.type != "MESH":
        raise RuntimeError(f"{target.name}: morph source mesh not found: {morph_source_name}")

    target.bi_morph_enabled = True
    target.bi_morph_source_object = morph_source_object
    target.bi_base_position_path = vb0_record["file_path"]
    target.bi_base_position_stride = int(vb0_record.get("stride", 0) or 0)
    target.bi_vb_layout_profile = config["vb_profile"]
    target.bi_cb1_profile = config["cb1"]
    target.bi_export_mirror_x = bool(config.get("mirror_flip", True))
    target.bi_export_uv_mirror_u = bool(config.get("uv_mirror_u", False))
    target.bi_export_uv_flip_v = bool(config.get("uv_flip_v", True))

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
    scene.bi_animation_presents_per_step = max(
        _env_int("RX_EXPORT_TICKS_PER_SAMPLE", DEFAULT_TICKS_PER_SAMPLE),
        1,
    )
    scene.bi_morph_include_normals = True
    scene.bi_morph_include_tangents = True
    scene.bi_export_mirror_x = True
    scene.bi_export_uv_mirror_u = False
    scene.bi_export_uv_flip_v = True

    geometry_by_key = {_geometry_key(record): record for record in geometry_export["geometry_records"]}
    configured = {}
    for target_name, target in sorted(runtime_targets.items()):
        _link_object_once(runtime_collection, target)
        target.bi_bone_enabled = True
        target.bi_match_priority = -1000

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
    os.environ.setdefault("RX_BONE_SAMPLE_HIDE_MESHES", "1")
    # BoneX driver constraints are part of the final evaluated pose.  Muting
    # them makes physics bones sample a different rig state than normal bones.
    os.environ["RX_BONE_SAMPLE_MUTE_STATIC_BONEX"] = "0"
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
        presents_per_step=scene.bi_animation_presents_per_step,
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
        presents_per_step=scene.bi_animation_presents_per_step,
        default_loop_start=-1,
        default_loop_end=-1,
        write_metadata=True,
    )
    timings["morph_export_seconds"] = time.perf_counter() - stage_start
    total_elapsed = time.perf_counter() - total_start
    timings["total_seconds"] = total_elapsed
    failed = [*list(bone_result.failed_armatures), *list(morph_result.failed_armatures)]
    perf_report = {
        "format": "rx_export_perf_v1",
        "output_dir": OUTPUT_DIR,
        "clip_name": scene.bi_animation_clip_name,
        "frame_start": int(scene.bi_animation_frame_start),
        "frame_end": int(scene.bi_animation_frame_end),
        "frame_step": int(scene.bi_animation_frame_step),
        "ticks_per_sample": int(scene.bi_animation_presents_per_step),
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
    _print_export_performance(perf_report)
    payload = {
        "ok": not failed,
        "configured": configured,
        "elapsed_wall": total_elapsed,
        "perf_report": "console",
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
