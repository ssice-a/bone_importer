"""Background Blender export script for the current RX test scene."""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
import traceback

import bpy


REPO_PARENT = r"E:\vscode"
OUTPUT_DIR = r"E:\XXMI\EFMI\Mods\RX"
BMC_CAPTURE_MANIFEST = r"E:\XXMI\EFMI\Mods\lxi\capture_manifest.json"


TARGETS = {
    "e78c7068-10590-0": {
        "source": "000_面",
        "vb_profile": "PACKED16",
        "cb1": "NONE",
    },
    "2009f0d6-1356-0": {
        "source": "005_睫眉",
        "vb_profile": "PNTA40",
        "cb1": "EYELASH",
    },
}


def _register_addons():
    if REPO_PARENT not in sys.path:
        sys.path.insert(0, REPO_PARENT)

    import bone_importer

    try:
        bone_importer.unregister()
    except Exception:
        pass
    bone_importer.register()

    try:
        bone_merge = importlib.import_module("3dmigoto_bone_merge")
        for module_name in (
            "3dmigoto_bone_merge.core.export_buffers",
            "3dmigoto_bone_merge.core.export_prepare",
        ):
            loaded = sys.modules.get(module_name)
            if loaded is not None:
                importlib.reload(loaded)
        try:
            bone_merge.unregister()
        except Exception:
            pass
        try:
            bone_merge.register()
        except Exception:
            pass
    except Exception:
        bone_merge = None

    return bone_importer, bone_merge


def _remove_collection(collection_name: str):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        return
    for child in list(collection.children):
        _remove_collection(child.name)
    for obj in list(collection.objects):
        collection.objects.unlink(obj)
        if obj.name.startswith("RXEXP_"):
            data = getattr(obj, "data", None)
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
    bpy.data.collections.remove(collection)


def _new_collection(name: str, parent=None):
    _remove_collection(name)
    collection = bpy.data.collections.new(name)
    if parent is None:
        bpy.context.scene.collection.children.link(collection)
    else:
        parent.children.link(collection)
    return collection


def _weighted_group_indices(mesh_obj) -> set[int]:
    used = set()
    for vertex in mesh_obj.data.vertices:
        for group_element in vertex.groups:
            if float(group_element.weight) > 0.0:
                used.add(int(group_element.group))
    return used


def _source_armature_for_mesh(mesh_obj):
    parent = getattr(mesh_obj, "parent", None)
    if parent is not None and getattr(parent, "type", "") == "ARMATURE":
        return parent
    for modifier in mesh_obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return modifier.object
    return None


def _remove_unmapped_vertex_groups(mesh_obj, keep_group_indices: set[int]) -> int:
    removed_count = 0
    for group_index in range(len(mesh_obj.vertex_groups) - 1, -1, -1):
        if group_index in keep_group_indices:
            continue
        mesh_obj.vertex_groups.remove(mesh_obj.vertex_groups[group_index])
        removed_count += 1
    return removed_count


def _build_numeric_export_duplicate(source_mesh, target_name: str, collection):
    source_armature = _source_armature_for_mesh(source_mesh)
    if source_armature is None:
        raise RuntimeError(f"{source_mesh.name}: source armature not found")

    used_group_indices = _weighted_group_indices(source_mesh)
    original_group_names = [vertex_group.name for vertex_group in source_mesh.vertex_groups]
    mapped_groups = []
    missing_bones = []
    for group_index, group_name in enumerate(original_group_names):
        if group_index not in used_group_indices:
            continue
        if group_name in source_armature.pose.bones:
            mapped_groups.append((group_index, group_name))
        else:
            missing_bones.append(group_name)
    if not mapped_groups:
        raise RuntimeError(f"{source_mesh.name}: no weighted vertex groups map to {source_armature.name} bones")

    duplicate = source_mesh.copy()
    duplicate.data = source_mesh.data.copy()
    duplicate.animation_data_clear()
    duplicate.name = f"RXEXP_{target_name}_{source_mesh.name}"
    duplicate.parent = None
    duplicate.matrix_world = source_mesh.matrix_world.copy()
    for modifier in duplicate.modifiers:
        if modifier.type == "ARMATURE":
            modifier.show_viewport = False
            modifier.show_render = False

    kept_group_indices = {group_index for group_index, _group_name in mapped_groups}
    removed_group_count = _remove_unmapped_vertex_groups(duplicate, kept_group_indices)

    collection.objects.link(duplicate)
    if len(duplicate.vertex_groups) != len(mapped_groups):
        raise RuntimeError(
            f"{duplicate.name}: mapped vertex group cleanup mismatch "
            f"({len(duplicate.vertex_groups)} groups != {len(mapped_groups)} mappings)"
        )
    for slot_id, vertex_group in enumerate(duplicate.vertex_groups):
        vertex_group.name = str(slot_id)

    slot_bindings = [
        {
            "slot_id": slot_id,
            "source_armature": source_armature.name,
            "source_bone": group_name,
            "target_name": f"{slot_id}:{group_name}",
        }
        for slot_id, (_group_index, group_name) in enumerate(mapped_groups)
    ]
    return {
        "duplicate": duplicate,
        "source_armature": source_armature,
        "slot_bindings": slot_bindings,
        "missing_bones": missing_bones,
        "removed_group_count": removed_group_count,
    }


def _geometry_key(record: dict) -> str:
    return f"{record.get('ib_hash', '')}-{int(record.get('match_index_count', 0) or 0)}-{int(record.get('match_first_index', 0) or 0)}"


def _export_geometry_with_bmc():
    from importlib import import_module

    prepare_export_collection = import_module("3dmigoto_bone_merge.core.export_prepare").prepare_export_collection

    root = _new_collection("RX BMC Temp Export")
    target_builds = {}
    for target_name, config in TARGETS.items():
        source = bpy.data.objects.get(config["source"])
        if source is None:
            raise RuntimeError(f"Morph/source mesh not found: {config['source']}")
        region = bpy.data.collections.new(target_name)
        root.children.link(region)
        target_builds[target_name] = _build_numeric_export_duplicate(source, target_name, region)

    result = prepare_export_collection(
        context=bpy.context,
        source_collection=root,
        build_collection=None,
        output_dir=OUTPUT_DIR,
        internal_manifest_dir=None,
        capture_manifest_path=BMC_CAPTURE_MANIFEST,
        generate_ini=False,
        simple_override=False,
        filter_residual=False,
    )
    with open(result["manifest_path"], "r", encoding="utf-8") as manifest_file:
        bmc_manifest = json.load(manifest_file)

    records_by_key = {
        _geometry_key(record): record
        for record in bmc_manifest.get("geometry_buffers", [])
    }
    missing_records = [target_name for target_name in TARGETS if target_name not in records_by_key]
    if missing_records:
        raise RuntimeError(f"BMC geometry export missing target(s): {', '.join(missing_records)}")

    return {
        "result": result,
        "target_builds": target_builds,
        "geometry_records": [records_by_key[target_name] for target_name in TARGETS],
    }


def _configure_runtime_draw_parts(geometry_export):
    scene = bpy.context.scene
    runtime_collection = _new_collection("RX Runtime DrawParts")
    scene.bi_export_collection = runtime_collection
    scene.bi_animation_output_dir = OUTPUT_DIR
    scene.bi_animation_clip_name = "rxanimin"
    scene.bi_animation_clip_id = 0
    scene.bi_animation_frame_start = 0
    scene.bi_animation_frame_end = 5670
    scene.bi_animation_frame_step = 1
    scene.bi_animation_fps = float(scene.render.fps or 30)
    scene.bi_morph_include_normals = True
    scene.bi_morph_include_tangents = True

    geometry_by_key = {_geometry_key(record): record for record in geometry_export["geometry_records"]}
    configured = {}
    for target_name, config in TARGETS.items():
        target = bpy.data.objects.get(target_name)
        source = bpy.data.objects.get(config["source"])
        if target is None:
            raise RuntimeError(f"Target DrawPart not found: {target_name}")
        if source is None:
            raise RuntimeError(f"Morph/source mesh not found: {config['source']}")
        if target.name not in runtime_collection.objects:
            runtime_collection.objects.link(target)

        geometry_record = geometry_by_key[target_name]
        vb0_record = dict(geometry_record.get("vertex_buffers", {}).get("vb0", {}) or {})
        if not vb0_record.get("file_path"):
            raise RuntimeError(f"{target_name}: BMC geometry export has no vb0 Position buffer")
        build = geometry_export["target_builds"][target_name]
        slot_bindings = build["slot_bindings"]

        target.bi_bone_enabled = True
        target.bi_bone_source_armature = build["source_armature"]
        target.bi_bone_slot_map_json = json.dumps(slot_bindings, ensure_ascii=False)
        target.bi_skin_contract = "EXPLICIT_SLOT_MAP"
        target.bi_morph_enabled = True
        target.bi_morph_source_object = source
        target.bi_base_position_path = vb0_record["file_path"]
        target.bi_base_position_stride = int(vb0_record.get("stride", 0) or 0)
        target.bi_vb_layout_profile = config["vb_profile"]
        target.bi_cb1_profile = config["cb1"]
        target.bi_match_priority = 50
        configured[target_name] = {
            "source": source.name,
            "source_armature": build["source_armature"].name,
            "bone_slots": len(slot_bindings),
            "base_position": vb0_record["file_path"],
            "base_position_stride": int(vb0_record.get("stride", 0) or 0),
            "index_count": int(geometry_record.get("index_buffer", {}).get("index_count", 0) or 0),
            "vb_slots": sorted(geometry_record.get("vertex_buffers", {}).keys()),
            "missing_weighted_bones": list(build["missing_bones"]),
            "removed_vertex_groups": int(build["removed_group_count"]),
        }
    return configured


def _reset_rx_manifest():
    for file_name in ("rx_export_manifest.json", "rxanimin.ini"):
        path = os.path.join(OUTPUT_DIR, file_name)
        if os.path.exists(path):
            os.remove(path)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _reset_rx_manifest()
    _register_addons()

    geometry_export = _export_geometry_with_bmc()
    configured = _configure_runtime_draw_parts(geometry_export)

    from bone_importer.core.draw_part import build_target_draw_parts
    from bone_importer.core.manifest import write_export_manifest
    from bone_importer.core.workflow import (
        export_bone_payloads_for_selected_draw_parts,
        export_morph_for_selected_proxy_armatures,
    )

    scene = bpy.context.scene
    draw_parts = build_target_draw_parts(bpy.context)
    write_export_manifest(
        output_directory=scene.bi_animation_output_dir,
        clip_name=scene.bi_animation_clip_name,
        clip_id=scene.bi_animation_clip_id,
        draw_parts=draw_parts,
        geometry_results=tuple(geometry_export["geometry_records"]),
    )

    start = time.time()
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
    failed = [*list(bone_result.failed_armatures), *list(morph_result.failed_armatures)]
    payload = {
        "ok": not failed,
        "configured": configured,
        "elapsed_wall": time.time() - start,
        "geometry_manifest": geometry_export["result"]["manifest_path"],
        "geometry_records": len(geometry_export["geometry_records"]),
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
