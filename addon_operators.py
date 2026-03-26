"""Thin Blender operator entry points for the addon workflows."""

import bpy

from .core.object_context import find_proxy_armature_for_object
from .core.workflow_steps import (
    capture_bind_for_active_proxy,
    clear_previous_palette_for_active_proxy,
    export_palette_for_active_proxy,
    generate_proxy_rig_from_active_mesh,
    import_palette_for_active_proxy,
)


class BI_OT_generate_proxy_rig(bpy.types.Operator):
    bl_idname = "object.bi_generate_proxy_rig"
    bl_label = "Generate Proxy Rig"
    bl_description = "Generate a vertical VS-T0 proxy armature from numeric mesh vertex groups"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        active_object = context.active_object
        return bool(active_object and active_object.type == "MESH" and len(active_object.vertex_groups) > 0)

    def execute(self, context):
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
            return {"FINISHED"}

        message = f"Generated {result.configured_bones} proxy bones from {result.source_mesh_name}"
        if result.skipped_groups:
            message += f"; skipped {len(result.skipped_groups)} empty groups"
        self.report({"INFO"}, message)
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
        return {"FINISHED"}


class BI_OT_export_palette(bpy.types.Operator):
    bl_idname = "object.bi_export_palette"
    bl_label = "Export Palette"
    bl_description = "Export a VS-T0-compatible palette buffer with current and previous windows"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene and find_proxy_armature_for_object(context.active_object) is not None)

    def execute(self, context):
        try:
            result = export_palette_for_active_proxy(
                context.active_object,
                output_path=context.scene.bi_output_path,
                write_metadata=bool(context.scene.bi_write_metadata),
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
        return {"FINISHED"}


class BI_OT_import_palette(bpy.types.Operator):
    bl_idname = "object.bi_import_palette"
    bl_label = "Import Palette"
    bl_description = "Import a VS-T0 palette buffer and apply it onto the proxy armature"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene and find_proxy_armature_for_object(context.active_object) is not None)

    def execute(self, context):
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
