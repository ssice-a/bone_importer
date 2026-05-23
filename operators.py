"""Blender 操作器入口。"""

import json
import os

import bpy

from .core.draw_part import build_target_draw_parts, draw_parts_from_export_collection
from .core.context import find_proxy_armature_for_object, list_selected_proxy_armatures
from .core.manifest import load_export_manifest, write_export_manifest
from .core.runtime_ini import write_runtime_ini_from_manifest
from .core.action_bank_editor import (
    delete_action_at_index,
    list_actions,
    rename_action_at_index,
)
from .core.rx_export_plan import build_rx_export_plan
from .core.rx_geometry_export.prepare import prepare_geometry_export_collection
from .core.rx_mesh_analysis import analyze_mesh_route
from .core.rx_collection_setup import (
    DEFAULT_RX_EXPORT_COLLECTION,
    apply_collection_setup_plan,
    build_collection_setup_plan,
    build_collection_setup_plan_from_capture_manifest,
)
from .core.workflow import (
    clear_previous_palette_for_active_proxy,
    dump_debug_for_active_proxy,
    export_animation_for_selected_proxy_armatures,
    export_morph_for_selected_proxy_armatures,
    export_palette_for_selected_proxy_armatures,
    generate_proxy_rig_from_active_mesh,
    generate_proxy_rigs_from_selected_meshes,
    import_palette_for_active_proxy,
    import_palette_for_selected_proxy_armatures,
    refresh_bind_for_selected_proxy_armatures,
)
from .core.proxy import restore_numeric_vertex_group_names


def _has_export_collection_targets(context) -> bool:
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    export_collection = getattr(scene, "bi_export_collection", None)
    try:
        if draw_parts_from_export_collection(export_collection):
            return True
    except Exception:
        pass
    try:
        return bool(build_rx_export_plan(export_collection, analyze_mesh_route).draw_parts)
    except Exception:
        return False


def _resolve_capture_manifest_path(scene) -> str:
    configured_path = str(getattr(scene, "bi_capture_manifest_path", "") or "").strip()
    if configured_path:
        return bpy.path.abspath(configured_path)
    output_dir = bpy.path.abspath(getattr(scene, "bi_animation_output_dir", "") or "//")
    return os.path.join(output_dir, "capture_manifest.json")


def _read_capture_manifest_for_setup(scene) -> dict:
    manifest_path = _resolve_capture_manifest_path(scene)
    if not manifest_path or not os.path.exists(manifest_path):
        raise ValueError(
            "No runtime manifest draw_parts found. Set Capture Manifest to create IB collections automatically."
        )
    with open(manifest_path, "r", encoding="utf-8-sig") as manifest_file:
        payload = json.load(manifest_file)
    if not isinstance(payload, dict):
        raise ValueError("capture_manifest.json is not an object")
    return payload


def _build_rx_collection_setup_plan_for_scene(scene):
    root_name = (
        getattr(getattr(scene, "bi_export_collection", None), "name", "")
        or DEFAULT_RX_EXPORT_COLLECTION
    )
    manifest = load_export_manifest(scene.bi_animation_output_dir)
    plan = build_collection_setup_plan(manifest, root_collection_name=root_name)
    if plan.draw_parts:
        return plan, "runtime manifest"
    capture_manifest = _read_capture_manifest_for_setup(scene)
    plan = build_collection_setup_plan_from_capture_manifest(capture_manifest, root_collection_name=root_name)
    if not plan.draw_parts:
        raise ValueError("capture_manifest.json has no visible/candidate IBs to create collections from")
    return plan, "capture manifest"


def _read_geometry_records(geometry_manifest_path: str) -> tuple[dict, ...]:
    with open(geometry_manifest_path, "r", encoding="utf-8-sig") as manifest_file:
        geometry_manifest = json.load(manifest_file)
    return tuple(dict(record or {}) for record in geometry_manifest.get("geometry_buffers", []) or [])


def _apply_geometry_records_to_scene_objects(geometry_records):
    for geometry_record in geometry_records:
        vb0_record = dict(geometry_record.get("vertex_buffers", {}).get("vb0", {}) or {})
        base_position_path = str(vb0_record.get("file_path", "") or "")
        base_position_stride = int(vb0_record.get("stride", 0) or 0)
        if not base_position_path or base_position_stride <= 0:
            continue
        for object_name in list(geometry_record.get("object_names", []) or []):
            obj = bpy.data.objects.get(str(object_name or ""))
            if obj is None:
                continue
            if hasattr(obj, "bi_base_position_path"):
                obj.bi_base_position_path = base_position_path
            if hasattr(obj, "bi_base_position_stride"):
                obj.bi_base_position_stride = base_position_stride
            if hasattr(obj, "bi_force_replace_geometry"):
                obj.bi_force_replace_geometry = True


def _export_geometry_if_requested(context, export_type: str):
    scene = context.scene
    if export_type == "INI" or not bool(getattr(scene, "bi_rx_export_geometry", True)):
        return None
    geometry_result = prepare_geometry_export_collection(
        context=context,
        source_collection=getattr(scene, "bi_export_collection", None),
        output_dir=scene.bi_animation_output_dir,
        capture_manifest_path=str(getattr(scene, "bi_capture_manifest_path", "") or ""),
    )
    geometry_records = _read_geometry_records(geometry_result["manifest_path"])
    _apply_geometry_records_to_scene_objects(geometry_records)
    draw_parts = build_target_draw_parts(context)
    write_export_manifest(
        output_directory=scene.bi_animation_output_dir,
        clip_name=scene.bi_animation_clip_name,
        clip_id=scene.bi_animation_clip_id,
        draw_parts=draw_parts,
        geometry_results=geometry_records,
    )
    return {
        "result": geometry_result,
        "geometry_records": geometry_records,
    }


def _resolve_rx_source_fps(scene) -> float:
    configured_fps = float(getattr(scene, "bi_rx_source_fps", 0.0) or 0.0)
    if configured_fps > 0.0:
        return configured_fps
    render = getattr(scene, "render", None)
    scene_fps = float(getattr(render, "fps", 0.0) or 0.0)
    return scene_fps if scene_fps > 0.0 else float(getattr(scene, "bi_animation_fps", 60.0) or 60.0)


def _resolve_rx_ticks_per_sample(scene) -> int:
    source_fps = max(_resolve_rx_source_fps(scene), 1e-6)
    frame_step = max(int(getattr(scene, "bi_animation_frame_step", 1) or 1), 1)
    sample_fps = source_fps / frame_step
    target_fps = max(float(getattr(scene, "bi_rx_target_game_fps", 120.0) or 120.0), 1.0)
    playback_speed = max(float(getattr(scene, "bi_rx_playback_speed", 1.0) or 1.0), 0.01)
    return max(int(round(target_fps / max(sample_fps * playback_speed, 1e-6))), 1)


def _sync_rx_timing_to_legacy_fields(scene) -> tuple[float, int]:
    """Bridge the v3 intuitive UI to the current integer-tick backend."""

    source_fps = _resolve_rx_source_fps(scene)
    ticks_per_sample = _resolve_rx_ticks_per_sample(scene)
    scene.bi_animation_fps = source_fps
    scene.bi_animation_presents_per_step = ticks_per_sample
    return source_fps, ticks_per_sample


def _selected_rx_action_index(scene) -> int:
    raw_value = str(getattr(scene, "bi_rx_action_name", "") or "").strip()
    if raw_value in {"", "__NONE__"}:
        raise ValueError("No exported Action is selected")
    return int(raw_value)


def _sync_scene_clip_to_action(scene, action: dict):
    scene.bi_animation_clip_name = str(action.get("name", "") or scene.bi_animation_clip_name)
    scene.bi_animation_clip_id = int(action.get("clip_id", scene.bi_animation_clip_id) or 0)


class BI_OT_generate_proxy_rig(bpy.types.Operator):
    """为选中的网格生成代理骨架。"""

    bl_idname = "object.bi_generate_proxy_rig"
    bl_label = "Generate Proxy Rig"
    bl_description = "Generate a VS-T0 proxy armature from numeric mesh vertex groups"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(obj.type == "MESH" and len(obj.vertex_groups) > 0 for obj in context.selected_objects)

    def execute(self, context):
        selected_mesh_objects = [obj for obj in context.selected_objects if obj.type == "MESH"]
        selected_meshes = [obj for obj in selected_mesh_objects if len(obj.vertex_groups) > 0]
        if len(selected_meshes) > 1:
            try:
                result = generate_proxy_rigs_from_selected_meshes(context)
            except ValueError as exc:
                self.report({"WARNING"}, str(exc))
                return {"CANCELLED"}

            message = (
                f"Generated shared proxy armature for {result.generated_meshes} mesh(es)"
                f"; total bones {result.generated_bones}"
            )
            if result.skipped_meshes:
                message += f"; skipped {len(result.skipped_meshes)} mesh(es)"
            self.report({"INFO"}, message)
            if result.skipped_details:
                self.report({"WARNING"}, " | ".join(result.skipped_details))
            return {"FINISHED"}

        if len(selected_mesh_objects) > 1 and len(selected_meshes) <= 1:
            skipped_names = [obj.name for obj in selected_mesh_objects if len(obj.vertex_groups) == 0]
            if skipped_names:
                self.report(
                    {"WARNING"},
                    "Only one selected mesh has vertex groups; ignored: " + ", ".join(skipped_names),
                )

        try:
            result = generate_proxy_rig_from_active_mesh(context)
        except ValueError as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

        if result.max_slot >= result.slot_capacity:
            self.report(
                {"WARNING"},
                f"Generated {result.configured_bones} bones, but max slot {result.max_slot} exceeds capacity {result.slot_capacity}",
            )
        else:
            message = f"Generated {result.configured_bones} proxy bones from {result.source_mesh_name}"
            if result.skipped_groups:
                message += f"; skipped {len(result.skipped_groups)} empty groups"
            self.report({"INFO"}, message)

        if result.other_armature_modifiers:
            modifier_names = ", ".join(result.other_armature_modifiers)
            self.report(
                {"WARNING"},
                f"Other armature modifiers are still active on the mesh: {modifier_names}. This can cause double deformation.",
            )
        return {"FINISHED"}


class BI_OT_restore_numeric_vertex_groups(bpy.types.Operator):
    """Restore suffixed proxy vertex groups back to pure numeric names."""

    bl_idname = "object.bi_restore_numeric_vertex_groups"
    bl_label = "Restore Numeric Groups"
    bl_description = "Rename selected mesh vertex groups like 0__Body back to 0 for external model export"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(obj.type == "MESH" and len(obj.vertex_groups) > 0 for obj in context.selected_objects)

    def execute(self, context):
        renamed_count = 0
        failed_meshes = []
        for mesh_obj in [obj for obj in context.selected_objects if obj.type == "MESH"]:
            try:
                renamed_count += len(restore_numeric_vertex_group_names(mesh_obj))
            except ValueError as exc:
                failed_meshes.append(f"{mesh_obj.name}: {exc}")
        if failed_meshes:
            self.report({"WARNING"}, " | ".join(failed_meshes))
        self.report({"INFO"}, f"Restored {renamed_count} vertex group name(s)")
        return {"FINISHED"}


class BI_OT_refresh_bind(bpy.types.Operator):
    """刷新当前选中代理骨架的 bind 矩阵。"""

    bl_idname = "object.bi_refresh_bind"
    bl_label = "Refresh Bind"
    bl_description = "Capture the current proxy armature rest state as the new bind"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if find_proxy_armature_for_object(context.active_object) is not None:
            return True
        return bool(list_selected_proxy_armatures(context)) or _has_export_collection_targets(context)

    def execute(self, context):
        try:
            result = refresh_bind_for_selected_proxy_armatures(context)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Refresh bind failed: {exc}")
            return {"CANCELLED"}

        message = (
            f"Refreshed bind for {result.refreshed_armatures}/{result.selected_armatures} armatures"
            f"; captured {result.refreshed_bones} bones"
        )
        self.report({"INFO"}, message)
        if result.failed_armatures:
            self.report({"WARNING"}, "; ".join(result.failed_armatures))
        return {"FINISHED"}


class BI_OT_export_palette(bpy.types.Operator):
    """导出当前静态姿态到 VS-T0 工作缓冲。"""

    bl_idname = "object.bi_export_palette"
    bl_label = "Export Palette"
    bl_description = "Export current VS-T0-compatible palette rows for the selected proxy armatures"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if not context.scene:
            return False
        if find_proxy_armature_for_object(context.active_object) is not None:
            return True
        return bool(list_selected_proxy_armatures(context)) or _has_export_collection_targets(context)

    def execute(self, context):
        try:
            result = export_palette_for_selected_proxy_armatures(
                context,
                output_path=context.scene.bi_output_path,
                write_metadata=bool(context.scene.bi_write_metadata),
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Export failed: {exc}")
            return {"CANCELLED"}

        message = (
            f"Exported {result.exported_bones} bones from {result.exported_armatures}"
            f"/{result.selected_armatures} armatures to {result.binary_path}"
        )
        if result.overflow_bones:
            message += f"; {result.overflow_bones} overflowed the part window"
        self.report({"INFO"}, message)
        if result.failed_armatures:
            self.report({"WARNING"}, "; ".join(result.failed_armatures))
        return {"FINISHED"}


class BI_OT_create_rx_export_collection(bpy.types.Operator):
    """Create or sync the RX v3 collection tree from runtime or capture manifests."""

    bl_idname = "object.bi_create_rx_export_collection"
    bl_label = "Create/Sync RX Collections"
    bl_description = "Create the RX Export Collection and IB child collections automatically"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "scene", None))

    def execute(self, context):
        scene = context.scene
        try:
            plan, source_name = _build_rx_collection_setup_plan_for_scene(scene)
            result = apply_collection_setup_plan(context, plan)
            scene.bi_export_collection = bpy.data.collections[result.root_collection_name]
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Create RX collections failed: {exc}")
            return {"CANCELLED"}

        message = (
            f"Synced {result.draw_part_count} IB collection(s) from {source_name}, "
            f"linked {result.linked_object_count} object(s)"
        )
        self.report({"INFO"}, message)
        if result.missing_objects:
            self.report({"WARNING"}, "Missing scene object(s): " + ", ".join(result.missing_objects[:8]))
        if result.warnings:
            self.report({"WARNING"}, " | ".join(result.warnings[:4]))
        return {"FINISHED"}


class BI_OT_export_rx_package(bpy.types.Operator):
    """Unified RX v3 export entry used by the sidebar."""

    bl_idname = "object.bi_export_rx_package"
    bl_label = "Export RX Package"
    bl_description = "Export the selected RX v3 package type using one consistent timeline and UI contract"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene and _has_export_collection_targets(context))

    def execute(self, context):
        scene = context.scene
        export_type = str(getattr(scene, "bi_rx_export_type", "FULL") or "FULL").upper()
        source_fps, ticks_per_sample = _sync_rx_timing_to_legacy_fields(scene)

        try:
            if export_type == "INI":
                ini_path = write_runtime_ini_from_manifest(
                    scene.bi_animation_output_dir,
                    scene.bi_animation_clip_name,
                )
                self.report({"INFO"}, f"Generated RX INI/HLSL: {ini_path}")
                return {"FINISHED"}

            bone_result = None
            morph_result = None
            geometry_export = _export_geometry_if_requested(context, export_type)
            if export_type in {"FULL", "BONE"}:
                bone_result = export_animation_for_selected_proxy_armatures(
                    context,
                    output_directory=scene.bi_animation_output_dir,
                    clip_name=scene.bi_animation_clip_name,
                    clip_id=scene.bi_animation_clip_id,
                    frame_start=scene.bi_animation_frame_start,
                    frame_end=scene.bi_animation_frame_end,
                    frame_step=scene.bi_animation_frame_step,
                    fps=source_fps,
                    presents_per_step=ticks_per_sample,
                    default_loop_start=-1,
                    default_loop_end=-1,
                    write_metadata=bool(scene.bi_write_metadata),
                )
            if export_type in {"FULL", "MORPH"}:
                morph_result = export_morph_for_selected_proxy_armatures(
                    context,
                    output_directory=scene.bi_animation_output_dir,
                    clip_name=scene.bi_animation_clip_name,
                    clip_id=scene.bi_animation_clip_id,
                    frame_start=scene.bi_animation_frame_start,
                    frame_end=scene.bi_animation_frame_end,
                    frame_step=scene.bi_animation_frame_step,
                    fps=source_fps,
                    presents_per_step=ticks_per_sample,
                    default_loop_start=-1,
                    default_loop_end=-1,
                    write_metadata=bool(scene.bi_write_metadata),
                )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"RX v3 export failed: {exc}")
            return {"CANCELLED"}

        messages = [
            f"RX {export_type} exported",
            f"source_fps={source_fps:g}",
            f"runtime_step={ticks_per_sample} present(s)",
        ]
        if bool(getattr(scene, "bi_rx_export_geometry", True)):
            mesh_count = len(geometry_export["geometry_records"]) if geometry_export is not None else 0
            messages.append(f"mesh={mesh_count}")
        else:
            messages.append("mesh=reuse")
        if bone_result is not None:
            messages.append(
                f"bone parts={bone_result.exported_armatures}/{bone_result.selected_armatures}"
            )
            messages.append(f"bone frames={bone_result.sampled_frames}")
        if morph_result is not None:
            messages.append(f"morph meshes={morph_result.exported_morph_meshes}")
            messages.append(f"morph channels={morph_result.total_morph_channels}")
        self.report({"INFO"}, "; ".join(messages))
        return {"FINISHED"}


class BI_OT_rx_use_action_for_export(bpy.types.Operator):
    """Copy the selected exported Action into the export Clip fields."""

    bl_idname = "object.bi_rx_use_action_for_export"
    bl_label = "Use Action Name"
    bl_description = "Copy the selected exported Action name/id into Clip Name/Clip Id so the next export overwrites it"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "scene", None))

    def execute(self, context):
        scene = context.scene
        try:
            action_index = _selected_rx_action_index(scene)
            actions = list_actions(scene.bi_animation_output_dir)
            action = next(action for action in actions if int(action.get("clip_index", -1)) == action_index)
            _sync_scene_clip_to_action(scene, action)
        except StopIteration:
            self.report({"ERROR"}, "Selected Action no longer exists")
            return {"CANCELLED"}
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Clip fields now target Action {action_index}: {scene.bi_animation_clip_name}")
        return {"FINISHED"}


class BI_OT_rx_rename_action(bpy.types.Operator):
    """Rename one exported Action in the Runtime Manifest."""

    bl_idname = "object.bi_rx_rename_action"
    bl_label = "Rename Action"
    bl_description = "Rename the selected exported Action without changing its payload index"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "scene", None))

    def execute(self, context):
        scene = context.scene
        try:
            action_index = _selected_rx_action_index(scene)
            new_name = str(getattr(scene, "bi_rx_action_new_name", "") or "").strip()
            if not new_name:
                raise ValueError("New Action Name is empty")
            result = rename_action_at_index(scene.bi_animation_output_dir, action_index, new_name)
            scene.bi_animation_clip_name = result.renamed_name
            scene.bi_rx_action_name = str(action_index)
            scene.bi_rx_action_new_name = ""
            write_runtime_ini_from_manifest(scene.bi_animation_output_dir, scene.bi_animation_clip_name)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Rename Action failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed Action {action_index} to {result.renamed_name}")
        return {"FINISHED"}


class BI_OT_rx_delete_action(bpy.types.Operator):
    """Delete one exported Action and compact local payload clip tables."""

    bl_idname = "object.bi_rx_delete_action"
    bl_label = "Delete Action"
    bl_description = "Delete the selected Action from manifest, timeline, bone payloads, and morph payloads"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "scene", None))

    def execute(self, context):
        scene = context.scene
        try:
            action_index = _selected_rx_action_index(scene)
            result = delete_action_at_index(scene.bi_animation_output_dir, action_index)
            actions = list_actions(scene.bi_animation_output_dir)
            if actions:
                next_index = min(action_index, len(actions) - 1)
                _sync_scene_clip_to_action(scene, actions[next_index])
                scene.bi_rx_action_name = str(next_index)
            write_runtime_ini_from_manifest(scene.bi_animation_output_dir, scene.bi_animation_clip_name)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Delete Action failed: {exc}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            (
                f"Deleted Action {action_index}: {result.deleted_name}; "
                f"bone payloads={result.rewritten_bone_payloads}; "
                f"morph payloads={result.rewritten_morph_payloads}"
            ),
        )
        return {"FINISHED"}


class BI_OT_export_animation(bpy.types.Operator):
    """导出稀疏多帧动画 clip。"""

    bl_idname = "object.bi_export_animation"
    bl_label = "Export Bone Clip"
    bl_description = (
        "Export scene-evaluated TQ, bind, static clip, shared timeline defaults, and master playback data for the selected frame range"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if not context.scene:
            return False
        if find_proxy_armature_for_object(context.active_object) is not None:
            return True
        return bool(list_selected_proxy_armatures(context)) or _has_export_collection_targets(context)

    def execute(self, context):
        scene = context.scene
        try:
            result = export_animation_for_selected_proxy_armatures(
                context,
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
                write_metadata=bool(scene.bi_write_metadata),
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Animation export failed: {exc}")
            return {"CANCELLED"}

        if scene.bi_animation_frame_start == scene.bi_animation_frame_end:
            message = (
                f"Exported {result.exported_armatures}/{result.selected_armatures} single-frame TQ set(s)"
                f"; total bones {result.total_exported_bones}; time {result.elapsed_seconds:.2f}s"
            )
        else:
            message = (
                f"Exported {result.exported_armatures}/{result.selected_armatures} frame-range TQ set(s)"
                f"; sampled frames {result.sampled_frames}; aggregate frames {result.total_frames}"
                f"; total bones {result.total_exported_bones}"
                f"; time {result.elapsed_seconds:.2f}s"
            )
        if result.exported_morph_meshes:
            message += (
                f"; morph meshes {result.exported_morph_meshes}"
                f"; morph channels {result.total_morph_channels}"
            )
        message += f"; clip {result.clip_name}#{result.clip_id}"
        self.report({"INFO"}, message)
        self.report(
            {"INFO"},
            "frame_set "
            f"{result.frame_set_seconds:.2f}s | frame_write {result.frame_write_seconds:.2f}s"
            f" | finalize {result.finalize_seconds:.2f}s | other {result.other_seconds:.2f}s",
        )
        if result.generated_ini_path:
            self.report({"INFO"}, f"Generated ini snippet: {result.generated_ini_path}")
        if result.failed_armatures:
            self.report({"WARNING"}, "; ".join(result.failed_armatures))
        return {"FINISHED"}


class BI_OT_export_morph(bpy.types.Operator):
    """导出稀疏 shape key runtime clip。"""

    bl_idname = "object.bi_export_morph"
    bl_label = "Export Morph Clip"
    bl_description = "Export scene-evaluated morph_static, morph_anim, and shared timeline/master playback sidecars for the selected frame range"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if not context.scene:
            return False
        if find_proxy_armature_for_object(context.active_object) is not None:
            return True
        return bool(list_selected_proxy_armatures(context)) or _has_export_collection_targets(context)

    def execute(self, context):
        scene = context.scene
        try:
            result = export_morph_for_selected_proxy_armatures(
                context,
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
                write_metadata=bool(scene.bi_write_metadata),
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Morph export failed: {exc}")
            return {"CANCELLED"}

        message = (
            f"Exported {result.exported_morph_meshes} morph mesh(es)"
            f"; morph channels {result.total_morph_channels}"
            f"; sampled frames {result.sampled_frames}"
            f"; clip {result.clip_name}#{result.clip_id}"
            f"; time {result.elapsed_seconds:.2f}s"
        )
        self.report({"INFO"}, message)
        if result.generated_ini_path:
            self.report({"INFO"}, f"Generated ini snippet: {result.generated_ini_path}")
        if result.failed_armatures:
            self.report({"WARNING"}, "; ".join(result.failed_armatures))
        return {"FINISHED"}


class BI_OT_import_palette(bpy.types.Operator):
    """导入静态姿态到代理骨架。"""

    bl_idname = "object.bi_import_palette"
    bl_label = "Import Palette"
    bl_description = "Import a VS-T0 palette buffer and apply it onto the proxy armature"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not context.scene:
            return False
        if find_proxy_armature_for_object(context.active_object) is not None:
            return True
        return bool(list_selected_proxy_armatures(context))

    def execute(self, context):
        selected_armatures = list_selected_proxy_armatures(context)
        if len(selected_armatures) > 1:
            try:
                result = import_palette_for_selected_proxy_armatures(
                    context,
                    binary_path=context.scene.bi_import_path,
                    segment=context.scene.bi_import_segment,
                )
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            except Exception as exc:
                self.report({"ERROR"}, f"Import failed: {exc}")
                return {"CANCELLED"}

            message = (
                f"Imported {result.imported_bones} bones to {result.imported_armatures}"
                f"/{result.selected_armatures} selected armatures"
            )
            self.report({"INFO"}, message)
            if result.failed_armatures:
                self.report({"WARNING"}, "; ".join(result.failed_armatures))
            return {"FINISHED"}

        try:
            result = import_palette_for_active_proxy(
                context,
                context.active_object,
                binary_path=context.scene.bi_import_path,
                segment=context.scene.bi_import_segment,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Import failed: {exc}")
            return {"CANCELLED"}

        message = f"Imported {result.imported_bones} bones from {result.binary_path} ({result.segment.lower()})"
        if result.missing_rows:
            message += f"; {result.missing_rows} bone(s) were out of range"
        self.report({"INFO"}, message)
        if result.other_armature_modifiers:
            modifier_names = ", ".join(result.other_armature_modifiers)
            self.report(
                {"WARNING"},
                f"Other armature modifiers are still active on the source mesh: {modifier_names}. This can twist the imported deformation.",
            )
        return {"FINISHED"}


class BI_OT_clear_previous_cache(bpy.types.Operator):
    """清理 previous 缓存。"""

    bl_idname = "object.bi_clear_previous_cache"
    bl_label = "Clear Previous"
    bl_description = "Clear the cached previous-frame palette"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return find_proxy_armature_for_object(context.active_object) is not None

    def execute(self, context):
        try:
            armature_name = clear_previous_palette_for_active_proxy(context.active_object)
        except ValueError as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Cleared previous-frame cache for {armature_name}")
        return {"FINISHED"}


class BI_OT_dump_debug(bpy.types.Operator):
    """把当前调试信息打印到 Blender 控制台。"""

    bl_idname = "object.bi_dump_debug"
    bl_label = "Dump Debug"
    bl_description = "Print proxy rig, bind and palette debug information to the Blender console"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene and find_proxy_armature_for_object(context.active_object) is not None)

    def execute(self, context):
        try:
            result = dump_debug_for_active_proxy(
                context,
                context.active_object,
                binary_path=context.scene.bi_import_path,
                segment=context.scene.bi_import_segment,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Debug dump failed: {exc}")
            return {"CANCELLED"}

        message = f"Printed debug info for {result.armature_name} to the Blender console"
        if result.has_import_data:
            message += f"; sampled {result.sampled_bones} bones with palette data"
        else:
            message += f"; sampled {result.sampled_bones} bones without palette data"
        self.report({"INFO"}, message)
        return {"FINISHED"}
