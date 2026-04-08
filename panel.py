"""Bone Importer 侧边栏面板。"""

import bpy

from .constants import RESERVED_PALETTE_ROWS
from .core.context import (
    build_part_layout_from_id,
    find_proxy_armature_for_object,
    find_source_mesh_for_object,
    list_directly_selected_proxy_armatures,
    list_selected_proxy_armatures,
)
from .core.layout import calculate_slot_capacity_for_part_size


class VIEW3D_PT_bone_importer(bpy.types.Panel):
    """在 3D 视图侧边栏显示 Bone Importer 工作流。"""

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
        selected_mesh_count = sum(1 for obj in context.selected_objects if obj.type == "MESH" and len(obj.vertex_groups) > 0)
        selected_proxy_armatures = list_selected_proxy_armatures(context)
        directly_selected_proxy_armatures = list_directly_selected_proxy_armatures(context)
        selected_proxy_armature_count = len(selected_proxy_armatures)
        direct_proxy_armature_count = len(directly_selected_proxy_armatures)

        workflow_box = layout.box()
        workflow_box.label(text="VS-T0 Proxy Workflow", icon="ARMATURE_DATA")

        if active_object is None:
            workflow_box.label(text="Select a mesh or proxy armature.", icon="INFO")
            return

        info_box = workflow_box.box()
        info_box.label(text=f"Source Mesh: {source_mesh.name if source_mesh else 'None'}", icon="MESH_DATA")
        info_box.label(text=f"Proxy Armature: {proxy_armature.name if proxy_armature else 'None'}", icon="ARMATURE_DATA")

        generate_row = workflow_box.row(align=True)
        generate_row.operator("object.bi_generate_proxy_rig", icon="ARMATURE_DATA")
        generate_row.enabled = selected_mesh_count > 0
        if selected_mesh_count > 1:
            workflow_box.label(text=f"Selected Meshes: {selected_mesh_count}", icon="INFO")

        if proxy_armature is not None:
            binding_box = workflow_box.box()
            binding_box.label(text="Part Binding", icon="LINKED")
            binding_box.prop(proxy_armature, "bi_part_id")
            binding_box.prop(proxy_armature, "bi_buffer_correction_mode")
            if proxy_armature.bi_part_id >= 0:
                part_layout = build_part_layout_from_id(proxy_armature.bi_part_id)
                slot_capacity = calculate_slot_capacity_for_part_size(part_layout["part_size"])
                binding_box.label(text=f"Current Base: {part_layout['part_base']}", icon="INFO")
                binding_box.label(
                    text=f"Current Rows: {part_layout['part_base']} - {part_layout['part_base'] + part_layout['part_size'] - 1}",
                    icon="INFO",
                )
                binding_box.label(text=f"Previous Base: {part_layout['previous_base']}", icon="INFO")
                binding_box.label(
                    text=f"Reserved Rows: {RESERVED_PALETTE_ROWS} | Slot Capacity: {slot_capacity}",
                    icon="INFO",
                )
            else:
                binding_box.label(text="Set Part Id before import or export.", icon="ERROR")

            bind_row = binding_box.row(align=True)
            bind_row.operator("object.bi_refresh_bind", icon="FILE_REFRESH")
            bind_row.operator("object.bi_clear_previous_cache", icon="TRASH")

        static_box = workflow_box.box()
        static_box.label(text="Palette Roundtrip", icon="EXPORT")
        static_box.label(text="Use this path for VS-T0 patch import/export.", icon="INFO")
        static_box.prop(scene, "bi_output_path")
        static_box.prop(scene, "bi_write_metadata")
        static_button_row = static_box.row(align=True)
        static_button_row.operator("object.bi_export_palette", icon="EXPORT")
        static_button_row.operator("object.bi_import_palette", icon="IMPORT")
        static_button_row.enabled = (
            (proxy_armature is not None and proxy_armature.bi_part_id >= 0)
            or selected_proxy_armature_count > 0
        )
        static_box.prop(scene, "bi_import_path")
        static_box.prop(scene, "bi_import_segment")

        animation_box = workflow_box.box()
        animation_box.label(text="Runtime TQ Export", icon="ACTION")
        animation_box.label(text="Uses scene.frame_set() per frame and exports TQ + bind + meta.", icon="INFO")
        animation_box.prop(scene, "bi_animation_output_dir")
        frame_row = animation_box.row(align=True)
        frame_row.prop(scene, "bi_animation_frame_start")
        frame_row.prop(scene, "bi_animation_frame_end")
        animation_box.prop(scene, "bi_animation_frame_step")
        animation_box.prop(scene, "bi_animation_fps")
        animation_box.operator("object.bi_export_animation", icon="EXPORT")
        animation_box.enabled = (
            (proxy_armature is not None and proxy_armature.bi_part_id >= 0)
            or selected_proxy_armature_count > 0
        )

        debug_box = workflow_box.box()
        debug_box.label(text="Debug", icon="TEXT")
        debug_box.operator("object.bi_dump_debug", icon="FILE_TEXT")
        debug_box.enabled = proxy_armature is not None

        if direct_proxy_armature_count > 1:
            workflow_box.label(text=f"Direct Proxy Selection: {direct_proxy_armature_count}", icon="INFO")
        elif selected_proxy_armature_count > 1:
            workflow_box.label(text=f"Resolved Proxy Selection: {selected_proxy_armature_count}", icon="INFO")

        if proxy_armature is None:
            workflow_box.label(text="No proxy armature generated yet.", icon="INFO")
            return

        proxy_bone_count = sum(1 for pose_bone in proxy_armature.pose.bones if getattr(pose_bone, "bi_is_proxy", False))
        workflow_box.label(text=f"Proxy Bones: {proxy_bone_count}", icon="INFO")

        active_proxy_bone = context.active_pose_bone if context.active_object == proxy_armature else None
        if active_proxy_bone and getattr(active_proxy_bone, "bi_is_proxy", False):
            active_bone_box = workflow_box.box()
            active_bone_box.label(text=f"Active Proxy Bone: {active_proxy_bone.name}", icon="BONE_DATA")
            active_bone_box.prop(active_proxy_bone, "bi_slot_id")
            active_bone_box.prop(active_proxy_bone, "bi_bone_type")
            active_bone_box.prop(active_proxy_bone, "bi_export_enabled")
            active_bone_box.prop(active_proxy_bone, "bi_bind_valid", text="Bind Captured")
