"""Bone Importer 侧边栏面板。"""

import bpy
from .core.collection_plan import count_collection_meshes
from .core.context import (
    find_proxy_armature_for_object,
    find_source_mesh_for_object,
    list_directly_selected_proxy_armatures,
    list_selected_proxy_armatures,
)
from .core.draw_part import count_collection_draw_parts, draw_parts_from_selected_objects, parse_draw_part_name


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
        export_collection = getattr(scene, "bi_export_collection", None)
        try:
            collection_draw_part_count = count_collection_draw_parts(export_collection)
        except Exception:
            collection_draw_part_count = 0
        try:
            selected_draw_part_count = len(draw_parts_from_selected_objects(context))
        except Exception:
            selected_draw_part_count = 0
        selected_proxy_armature_count = len(selected_proxy_armatures)
        direct_proxy_armature_count = len(directly_selected_proxy_armatures)

        workflow_box = layout.box()
        workflow_box.label(text="VS-T0 Proxy Workflow", icon="ARMATURE_DATA")

        if active_object is None and export_collection is None:
            workflow_box.label(text="Select a mesh/proxy armature or set an RX Export Collection.", icon="INFO")
            return

        info_box = workflow_box.box()
        info_box.label(text=f"Source Mesh: {source_mesh.name if source_mesh else 'None'}", icon="MESH_DATA")
        info_box.label(text=f"Proxy Armature: {proxy_armature.name if proxy_armature else 'None'}", icon="ARMATURE_DATA")

        collection_box = workflow_box.box()
        collection_box.label(text="RX Export Collection", icon="OUTLINER_COLLECTION")
        collection_box.prop(scene, "bi_export_collection", text="Collection")
        if export_collection is not None:
            collection_box.prop(export_collection, "bi_cb1_override", text="Root CB1 Override")
            collection_box.label(
                text=f"Meshes: {count_collection_meshes(export_collection)} | Draw Parts: {collection_draw_part_count}",
                icon="INFO",
            )
            collection_box.label(text="Object names define DrawParts: hash-index_count-firstindex.", icon="INFO")
            child_collections = tuple(getattr(export_collection, "children", []) or ())
            if child_collections:
                child_box = collection_box.box()
                child_box.label(text="Child CB1 Overrides", icon="OUTLINER_COLLECTION")
                for child_collection in child_collections[:8]:
                    child_box.prop(child_collection, "bi_cb1_override", text=child_collection.name)
                if len(child_collections) > 8:
                    child_box.label(text=f"{len(child_collections) - 8} more child collection(s) hidden.", icon="INFO")

        generate_row = workflow_box.row(align=True)
        generate_row.operator("object.bi_generate_proxy_rig", icon="ARMATURE_DATA")
        generate_row.operator("object.bi_restore_numeric_vertex_groups", icon="SORTSIZE")
        generate_row.enabled = selected_mesh_count > 0
        if selected_mesh_count > 1:
            workflow_box.label(text=f"Selected Meshes: {selected_mesh_count}", icon="INFO")

        if proxy_armature is not None:
            binding_box = workflow_box.box()
            binding_box.label(text="DrawPart Binding", icon="LINKED")
            binding_box.label(text="Part Id is assigned automatically by index_count descending.", icon="INFO")
            if active_object is not None and active_object.type == "MESH":
                try:
                    draw_payload = parse_draw_part_name(active_object.name)
                except ValueError:
                    binding_box.label(text="Active mesh name is not hash-index_count-firstindex.", icon="ERROR")
                else:
                    binding_box.label(
                        text=(
                            f"hash={draw_payload['hash']} | "
                            f"indices={draw_payload['match_index_count']} | "
                            f"first={draw_payload['first_index']}"
                        ),
                        icon="INFO",
                    )
                binding_box.prop(active_object, "bi_buffer_correction_mode")
            else:
                binding_box.label(text="Select a draw-part mesh to edit per-IB settings.", icon="INFO")

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
            selected_proxy_armature_count > 0
            or selected_draw_part_count > 0
            or collection_draw_part_count > 0
        )
        static_box.prop(scene, "bi_import_path")
        static_box.prop(scene, "bi_import_segment")

        animation_box = workflow_box.box()
        animation_box.label(text="RX Clip Settings", icon="ACTION")
        animation_box.label(
            text="Shared clip range/output settings used by both bone and morph export.",
            icon="INFO",
        )
        animation_box.prop(scene, "bi_animation_output_dir")
        clip_row = animation_box.row(align=True)
        clip_row.prop(scene, "bi_animation_clip_name")
        clip_row.prop(scene, "bi_animation_clip_id")
        frame_row = animation_box.row(align=True)
        frame_row.prop(scene, "bi_animation_frame_start")
        frame_row.prop(scene, "bi_animation_frame_end")
        animation_box.prop(scene, "bi_animation_frame_step")
        animation_box.prop(scene, "bi_animation_fps")
        animation_button_row = animation_box.row(align=True)
        animation_button_row.operator("object.bi_export_animation", icon="EXPORT")
        animation_box.label(
            text="Ticks/Sample and Loop Start/End now use automatic defaults.",
            icon="INFO",
        )
        animation_box.enabled = (
            selected_proxy_armature_count > 0
            or selected_draw_part_count > 0
            or collection_draw_part_count > 0
        )

        morph_box = workflow_box.box()
        morph_box.label(text="RX Morph Export", icon="SHAPEKEY_DATA")
        morph_box.label(
            text="Exports per-mesh morph_static + morph_anim sidecars that share the RX clip timeline/master playback buffers.",
            icon="INFO",
        )
        morph_box.prop(scene, "bi_morph_include_normals")
        tangent_row = morph_box.row()
        tangent_row.enabled = bool(scene.bi_morph_include_normals)
        tangent_row.prop(scene, "bi_morph_include_tangents")
        morph_box.prop(scene, "bi_morph_channel_mode")
        morph_box.prop(scene, "bi_morph_source_object")
        morph_box.prop(scene, "bi_morph_target_draw_key")
        if active_object is not None and active_object.type == "MESH":
            morph_box.prop(active_object, "bi_base_position_path")
            morph_box.prop(active_object, "bi_base_position_stride")
        morph_button_row = morph_box.row(align=True)
        morph_button_row.operator("object.bi_export_morph", icon="EXPORT")
        morph_button_row.enabled = (
            selected_proxy_armature_count > 0
            or selected_draw_part_count > 0
            or collection_draw_part_count > 0
        )

        debug_box = workflow_box.box()
        debug_box.label(text="Debug", icon="TEXT")
        debug_box.operator("object.bi_dump_debug", icon="FILE_TEXT")
        debug_box.enabled = proxy_armature is not None

        if direct_proxy_armature_count > 1:
            workflow_box.label(text=f"Direct Proxy Selection: {direct_proxy_armature_count}", icon="INFO")
        elif collection_draw_part_count > 0:
            workflow_box.label(text=f"Collection Draw Parts: {collection_draw_part_count}", icon="INFO")
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
            active_bone_box.prop(active_proxy_bone, "bi_mesh_key")
            active_bone_box.prop(active_proxy_bone, "bi_bone_type")
            active_bone_box.prop(active_proxy_bone, "bi_export_enabled")
            active_bone_box.prop(active_proxy_bone, "bi_bind_valid", text="Bind Captured")
