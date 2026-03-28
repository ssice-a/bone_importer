"""Blender 操作器入口，尽量只做参数收集和流程转发。"""

import bpy

from .core.context import find_proxy_armature_for_object, list_selected_proxy_armatures
from .core.workflow import (
    capture_bind_for_active_proxy,
    clear_previous_palette_for_active_proxy,
    dump_debug_for_active_proxy,
    export_palette_for_active_proxy,
    export_palette_for_selected_proxy_armatures,
    generate_proxy_rig_from_active_mesh,
    generate_proxy_rigs_from_selected_meshes,
    import_palette_for_active_proxy,
    import_palette_for_selected_proxy_armatures,
)


class BI_OT_generate_proxy_rig(bpy.types.Operator):
    bl_idname = "object.bi_generate_proxy_rig"
    bl_label = "Generate Proxy Rig"
    bl_description = "Generate a vertical VS-T0 proxy armature from numeric mesh vertex groups"
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


class BI_OT_capture_bind(bpy.types.Operator):
    bl_idname = "object.bi_capture_bind"
    bl_label = "Capture Bind"
    bl_description = "Capture bind matrices from the current proxy armature"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return find_proxy_armature_for_object(context.active_object) is not None

    def execute(self, context):
        try:
            result = capture_bind_for_active_proxy(context.active_object)
        except ValueError as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Captured bind matrices for {result.captured_bones} proxy bones")
        if result.other_armature_modifiers:
            modifier_names = ", ".join(result.other_armature_modifiers)
            self.report(
                {"WARNING"},
                f"Other armature modifiers are still active on the source mesh: {modifier_names}.",
            )
        return {"FINISHED"}


class BI_OT_export_palette(bpy.types.Operator):
    bl_idname = "object.bi_export_palette"
    bl_label = "Export Palette"
    bl_description = "Export a VS-T0-compatible palette buffer with current and previous windows"
    bl_options = {"REGISTER"}

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
                result = export_palette_for_selected_proxy_armatures(
                    context,
                    output_path=context.scene.bi_output_path,
                    write_metadata=bool(context.scene.bi_write_metadata),
                    base_buffer_path=context.scene.bi_import_path,
                )
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            except Exception as exc:
                self.report({"ERROR"}, f"Export failed: {exc}")
                return {"CANCELLED"}

            message = (
                f"Exported {result.exported_bones} bones from {result.exported_armatures}"
                f"/{result.selected_armatures} selected armatures to {result.binary_path}"
            )
            if result.overflow_bones:
                message += f"; {result.overflow_bones} overflowed the part window"
            self.report({"INFO"}, message)
            if result.failed_armatures:
                self.report({"WARNING"}, "; ".join(result.failed_armatures))
            return {"FINISHED"}

        try:
            result = export_palette_for_active_proxy(
                context.active_object,
                output_path=context.scene.bi_output_path,
                write_metadata=bool(context.scene.bi_write_metadata),
                base_buffer_path=context.scene.bi_import_path,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Export failed: {exc}")
            return {"CANCELLED"}

        message = f"Exported {result.exported_bones} bones to {result.binary_path}"
        if result.overflow_bones:
            message += f"; {result.overflow_bones} overflowed the part window"
        self.report({"INFO"}, message)
        if result.other_armature_modifiers:
            modifier_names = ", ".join(result.other_armature_modifiers)
            self.report(
                {"WARNING"},
                f"Other armature modifiers are still active on the source mesh: {modifier_names}.",
            )
        return {"FINISHED"}


class BI_OT_import_palette(bpy.types.Operator):
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
