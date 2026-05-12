"""Blender 操作器入口。"""

import bpy

from .core.collection_plan import proxy_armatures_from_export_collection
from .core.context import find_proxy_armature_for_object, list_selected_proxy_armatures
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


def _has_export_collection_targets(context) -> bool:
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    return bool(proxy_armatures_from_export_collection(getattr(scene, "bi_export_collection", None)))


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
                f"Generated {result.generated_armatures} armatures for {result.generated_meshes} meshes"
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
                presents_per_step=1,
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
                presents_per_step=1,
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
