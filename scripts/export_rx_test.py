"""Background Blender export script for the current RX test scene."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

import bpy


REPO_PARENT = r"E:\vscode"
OUTPUT_DIR = r"E:\XXMI\EFMI\Mods\RX"


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


def _configure_scene():
    scene = bpy.context.scene
    scene.bi_export_collection = bpy.data.collections.get("BMC Export Sources")
    scene.bi_animation_output_dir = OUTPUT_DIR
    scene.bi_animation_clip_name = "rxanimin"
    scene.bi_animation_clip_id = 0
    scene.bi_animation_frame_start = 0
    scene.bi_animation_frame_end = 5670
    scene.bi_animation_frame_step = 1
    scene.bi_animation_fps = float(scene.render.fps or 60)
    scene.bi_morph_include_normals = True
    scene.bi_morph_include_tangents = True

    configs = {
        "e78c7068-10590-0": {
            "source": "000_面",
            "base": r"E:\XXMI\cache\WorkSpace\EFMI\Default\LOD0\e78c7068-10590-0\TYPE_GPU_P12_N4_T8_C4_BW8_BI4_\e78c7068-10590-0-Position.buf",
            "stride": 16,
            "profile": "PACKED16",
            "cb1": "NONE",
        },
        "2009f0d6-1356-0": {
            "source": "005_睫眉",
            "base": r"E:\XXMI\cache\WorkSpace\EFMI\Default\LOD0\2009f0d6-1356-0\TYPE_GPU_P12_N12_TA16_T8_BW16_BI16_\2009f0d6-1356-0-Position.buf",
            "stride": 40,
            "profile": "PNTA40",
            "cb1": "EYELASH",
        },
    }

    collection = bpy.data.collections.get("BMC Export Sources")
    if collection is None:
        raise RuntimeError("Collection not found: BMC Export Sources")
    for obj in collection.objects:
        if obj.type != "MESH":
            continue
        obj.bi_bone_enabled = False
        obj.bi_morph_enabled = False

    configured = {}
    for target_name, config in configs.items():
        obj = bpy.data.objects.get(target_name)
        source = bpy.data.objects.get(config["source"])
        if obj is None:
            raise RuntimeError(f"Target DrawPart not found: {target_name}")
        if source is None:
            raise RuntimeError(f"Morph source not found: {config['source']}")
        if not os.path.exists(config["base"]):
            raise RuntimeError(f"Base Position buffer does not exist: {config['base']}")
        obj.bi_bone_enabled = False
        obj.bi_morph_enabled = True
        obj.bi_morph_source_object = source
        obj.bi_base_position_path = config["base"]
        obj.bi_base_position_stride = int(config["stride"])
        obj.bi_vb_layout_profile = config["profile"]
        obj.bi_cb1_profile = config["cb1"]
        obj.bi_match_priority = 50
        configured[target_name] = {
            "source": source.name,
            "base": config["base"],
            "stride": config["stride"],
        }
    return configured


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _register_addon()
    configured = _configure_scene()

    from bone_importer.core.workflow import export_morph_for_selected_proxy_armatures

    scene = bpy.context.scene
    start = time.time()
    result = export_morph_for_selected_proxy_armatures(
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
    payload = {
        "ok": True,
        "configured": configured,
        "elapsed_wall": time.time() - start,
        "exported_morph_meshes": result.exported_morph_meshes,
        "total_morph_channels": result.total_morph_channels,
        "sampled_frames": result.sampled_frames,
        "failed": list(result.failed_armatures),
        "files": list(result.exported_files),
        "ini": result.generated_ini_path,
        "timeline": result.timeline_static_path,
        "master": result.master_playback_path,
        "manifest": os.path.join(OUTPUT_DIR, "rx_export_manifest.json"),
    }
    print("RX_EXPORT_RESULT=" + json.dumps(payload, ensure_ascii=False))
    if result.failed_armatures:
        raise RuntimeError("; ".join(result.failed_armatures))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        print("RX_EXPORT_RESULT=" + json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise
