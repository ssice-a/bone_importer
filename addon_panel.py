"""Sidebar panel for the Bone Importer addon."""

import bpy

from .addon_constants import DEFAULT_PART_ROW_COUNT, RESERVED_PALETTE_ROWS
from .core.coordinate_conversion import describe_coordinate_conversion
from .core.object_context import (
    find_layout_settings_owner,
    find_proxy_armature_for_object,
    find_source_mesh_for_object,
)
from .core.palette_layout import calculate_slot_capacity_for_part_size


class VIEW3D_PT_bone_importer(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bone Importer"
    bl_label = "Bone Importer"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active_object = context.active_object
        source_mesh = find_source_mesh_for_object(active_object)
        proxy_armature = find_proxy_armature_for_object(active_object)
        settings_owner = find_layout_settings_owner(active_object)

        workflow_box = layout.box()
        workflow_box.label(text="VS-T0 Proxy Workflow", icon="ARMATURE_DATA")

        if settings_owner is None:
            workflow_box.label(text="Select a mesh with numeric vertex groups", icon="INFO")
            workflow_box.label(text="or its generated proxy armature.", icon="INFO")
            return

        info_box = workflow_box.box()
        info_box.label(text=f"Source Mesh: {source_mesh.name if source_mesh else 'None'}", icon="MESH_DATA")
        info_box.label(text=f"Proxy Armature: {proxy_armature.name if proxy_armature else 'None'}", icon="ARMATURE_DATA")
        info_box.label(text=describe_coordinate_conversion(), icon="INFO")

        generate_row = workflow_box.row(align=True)
        generate_row.enabled = active_object is not None and active_object.type == "MESH"
        generate_row.operator("object.bi_generate_proxy_rig", icon="ARMATURE_DATA")

        action_row = workflow_box.row(align=True)
        action_row.enabled = proxy_armature is not None
        action_row.operator("object.bi_capture_bind", icon="BONE_DATA")
        action_row.operator("object.bi_export_palette", icon="EXPORT")
        action_row.operator("object.bi_import_palette", icon="IMPORT")
        action_row.operator("object.bi_clear_previous_cache", icon="FILE_REFRESH")

        layout_box = workflow_box.box()
        layout_box.label(text="Part Layout", icon="NLA")
        layout_box.prop(settings_owner, "bi_part_base")
        layout_box.prop(settings_owner, "bi_part_size")
        layout_box.prop(settings_owner, "bi_previous_offset")
        layout_box.prop(settings_owner, "bi_buffer_size")
        slot_capacity = calculate_slot_capacity_for_part_size(getattr(settings_owner, "bi_part_size", DEFAULT_PART_ROW_COUNT))
        layout_box.label(
            text=f"Reserved rows: {RESERVED_PALETTE_ROWS} | Slot capacity: {slot_capacity}",
            icon="INFO",
        )

        export_box = workflow_box.box()
        export_box.label(text="Export", icon="EXPORT")
        export_box.prop(scene, "bi_output_path")
        export_box.prop(scene, "bi_write_metadata")

        import_box = workflow_box.box()
        import_box.label(text="Import", icon="IMPORT")
        import_box.prop(scene, "bi_import_path")
        import_box.prop(scene, "bi_import_segment")

        if proxy_armature is None:
            workflow_box.label(text="No proxy armature generated yet.", icon="INFO")
            return

        proxy_bone_count = sum(1 for pose_bone in proxy_armature.pose.bones if getattr(pose_bone, "bi_is_proxy", False))
        workflow_box.label(text=f"Proxy bones: {proxy_bone_count}", icon="INFO")

        active_proxy_bone = context.active_pose_bone if context.active_object == proxy_armature else None
        if active_proxy_bone and getattr(active_proxy_bone, "bi_is_proxy", False):
            active_bone_box = workflow_box.box()
            active_bone_box.label(text=f"Active Proxy Bone: {active_proxy_bone.name}", icon="BONE_DATA")
            active_bone_box.prop(active_proxy_bone, "bi_slot_id")
            active_bone_box.prop(active_proxy_bone, "bi_bone_type")
            active_bone_box.prop(active_proxy_bone, "bi_export_enabled")
            active_bone_box.prop(active_proxy_bone, "bi_bind_valid", text="Bind Captured")
