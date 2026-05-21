"""Bone Importer sidebar panel."""

from __future__ import annotations

import bpy

from .core.context import find_proxy_armature_for_object, find_source_mesh_for_object
from .core.rx_export_plan import (
    DEFORM_MORPH,
    DEFORM_MORPH_THEN_PRESKIN_BONE,
    DEFORM_PRESKIN_BONE,
    RXExportPlanError,
    build_rx_export_plan,
)
from .core.rx_mesh_analysis import analyze_mesh_route


def _safe_scene_fps(scene) -> float:
    configured_fps = float(getattr(scene, "bi_rx_source_fps", 0.0) or 0.0)
    if configured_fps > 0.0:
        return configured_fps
    render = getattr(scene, "render", None)
    scene_fps = float(getattr(render, "fps", 0.0) or 0.0)
    return scene_fps if scene_fps > 0.0 else float(getattr(scene, "bi_animation_fps", 60.0) or 60.0)


def _derived_ticks_per_sample(scene) -> int:
    source_fps = max(_safe_scene_fps(scene), 1e-6)
    frame_step = max(int(getattr(scene, "bi_animation_frame_step", 1) or 1), 1)
    sample_fps = source_fps / frame_step
    target_fps = max(float(getattr(scene, "bi_rx_target_game_fps", 120.0) or 120.0), 1.0)
    playback_speed = max(float(getattr(scene, "bi_rx_playback_speed", 1.0) or 1.0), 0.01)
    return max(int(round(target_fps / max(sample_fps * playback_speed, 1e-6))), 1)


def _build_preview_plan(collection):
    if collection is None:
        return None, "Set an RX Export Collection."
    try:
        return build_rx_export_plan(collection, analyze_mesh_route), ""
    except RXExportPlanError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"Preview failed: {exc}"


def _plan_counts(plan) -> dict[str, int]:
    if plan is None:
        return {
            "ib": 0,
            "part": 0,
            "segment": 0,
            "replacement": 0,
            "morph": 0,
            "preskin": 0,
            "own": 0,
            "source": 0,
        }

    counts = {
        "ib": len(plan.draw_parts),
        "part": 0,
        "segment": 0,
        "replacement": 0,
        "morph": 0,
        "preskin": 0,
        "own": 0,
        "source": 0,
    }
    for draw_part in plan.draw_parts:
        counts["part"] += len(draw_part.parts)
        for part in draw_part.parts:
            for segment in part.segments:
                counts["segment"] += 1
                counts["replacement"] += int(bool(segment.geometry_required))
                counts["own"] += int(segment.final_skin_palette == "OWN")
                counts["source"] += int(segment.final_skin_palette == "SOURCE_GAME")
                counts["morph"] += int(segment.deform_chain in {DEFORM_MORPH, DEFORM_MORPH_THEN_PRESKIN_BONE})
                counts["preskin"] += int(segment.deform_chain in {DEFORM_PRESKIN_BONE, DEFORM_MORPH_THEN_PRESKIN_BONE})
    return counts


def _draw_plan_preview(box, scene, plan, error_message: str):
    header = box.row(align=True)
    icon = "TRIA_DOWN" if bool(scene.bi_rx_preview_expanded) else "TRIA_RIGHT"
    header.prop(scene, "bi_rx_preview_expanded", text="", icon=icon, emboss=False)
    header.label(text="IB Preview", icon="OUTLINER_COLLECTION")

    if not bool(scene.bi_rx_preview_expanded):
        return

    if error_message:
        box.label(text=error_message, icon="ERROR")
        box.label(text="Expected child collections: hash-index_count-firstindex, optionally with partNN children.", icon="INFO")
        return

    counts = _plan_counts(plan)
    grid = box.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=True)
    grid.label(text=f"IB Collections: {counts['ib']}", icon="EVENT_I")
    grid.label(text=f"Parts: {counts['part']}", icon="EVENT_P")
    grid.label(text=f"Draw Segments: {counts['segment']}", icon="MESH_DATA")
    grid.label(text=f"Geometry Required: {counts['replacement']}", icon="MOD_BUILD")
    grid.label(text=f"Source Skin: {counts['source']}", icon="LINKED")
    grid.label(text=f"Own Skin: {counts['own']}", icon="ARMATURE_DATA")
    grid.label(text=f"Morph: {counts['morph']}", icon="SHAPEKEY_DATA")
    grid.label(text=f"Pre-Skin Bone: {counts['preskin']}", icon="MOD_ARMATURE")

    shown = 0
    for draw_part in plan.draw_parts:
        if shown >= 8:
            break
        state = "skip original" if draw_part.skip_original else "keep original"
        row = box.row(align=True)
        row.label(text=f"{draw_part.identity.draw_key}: {state}", icon="RESTRICT_VIEW_OFF")
        shown += 1
    hidden = counts["ib"] - shown
    if hidden > 0:
        box.label(text=f"{hidden} more IB collection(s) hidden.", icon="INFO")


def _draw_active_object_advanced(box, scene, active_object):
    header = box.row(align=True)
    icon = "TRIA_DOWN" if bool(scene.bi_rx_object_advanced_expanded) else "TRIA_RIGHT"
    header.prop(scene, "bi_rx_object_advanced_expanded", text="", icon=icon, emboss=False)
    header.label(text="Active Mesh Advanced", icon="PREFERENCES")

    if not bool(scene.bi_rx_object_advanced_expanded):
        return
    if active_object is None or active_object.type != "MESH":
        box.label(text="Select a mesh inside an IB collection to edit object route settings.", icon="INFO")
        return

    route_box = box.box()
    route_box.label(text="Final Draw Route", icon="MOD_ARMATURE")
    route_box.prop(active_object, "bi_final_skin")
    route_box.prop(active_object, "bi_final_armature")
    route_box.prop(active_object, "bi_force_replace_geometry")

    preskin_box = box.box()
    preskin_box.label(text="Pre-Skin Bone", icon="ARMATURE_DATA")
    preskin_box.prop(active_object, "bi_preskin_bone_enabled")
    preskin_fields = preskin_box.column(align=True)
    preskin_fields.enabled = bool(getattr(active_object, "bi_preskin_bone_enabled", False))
    preskin_fields.prop(active_object, "bi_preskin_armature")
    preskin_fields.prop(active_object, "bi_preskin_action")

    morph_box = box.box()
    morph_box.label(text="Morph", icon="SHAPEKEY_DATA")
    morph_box.prop(active_object, "bi_morph_enabled")
    morph_box.prop(active_object, "bi_morph_source_object")
    morph_box.prop(active_object, "bi_base_position_path")
    morph_box.prop(active_object, "bi_base_position_stride")

    adapter_box = box.box()
    adapter_box.label(text="Runtime Adapters", icon="ORIENTATION_GLOBAL")
    adapter_box.prop(active_object, "bi_match_priority")
    adapter_box.prop(active_object, "bi_cb1_profile")
    adapter_box.prop(active_object, "bi_vb_layout_profile")
    adapter_box.prop(active_object, "bi_buffer_correction_mode")
    adapter_box.prop(active_object, "bi_export_mirror_x")
    adapter_box.prop(active_object, "bi_export_uv_mirror_u")
    adapter_box.prop(active_object, "bi_export_uv_flip_v")

    legacy_box = box.box()
    legacy_box.label(text="Legacy Bone Map", icon="BONE_DATA")
    legacy_box.prop(active_object, "bi_bone_enabled")
    legacy_box.prop(active_object, "bi_bone_source_armature")
    legacy_box.prop(active_object, "bi_bone_slot_map_json")


class VIEW3D_PT_bone_importer(bpy.types.Panel):
    """Show the Bone Importer workflow in the 3D View sidebar."""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bone Importer"
    bl_label = "Bone Importer"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active_object = context.active_object
        export_collection = getattr(scene, "bi_export_collection", None)
        source_mesh = find_source_mesh_for_object(active_object)
        proxy_armature = find_proxy_armature_for_object(active_object)
        plan, preview_error = _build_preview_plan(export_collection)
        has_plan = plan is not None

        workflow_box = layout.box()
        workflow_box.label(text="RX Export v3", icon="ARMATURE_DATA")

        setup_box = workflow_box.box()
        setup_box.label(text="Export Setup", icon="EXPORT")
        setup_box.prop(scene, "bi_animation_output_dir", text="Output Dir")
        setup_box.prop(scene, "bi_capture_manifest_path", text="Capture Manifest")
        setup_box.prop(scene, "bi_export_collection", text="RX Export Collection")
        setup_box.prop(scene, "bi_rx_export_type")
        setup_box.prop(scene, "bi_rx_export_geometry")
        export_row = setup_box.row(align=True)
        export_row.operator("object.bi_export_rx_package", text="Export RX Package", icon="EXPORT")
        export_row.enabled = bool(has_plan)

        timing_box = workflow_box.box()
        timing_box.label(text="Timeline", icon="ACTION")
        clip_row = timing_box.row(align=True)
        clip_row.prop(scene, "bi_animation_clip_name", text="Clip")
        clip_row.prop(scene, "bi_animation_clip_id", text="ID")
        frame_row = timing_box.row(align=True)
        frame_row.prop(scene, "bi_animation_frame_start", text="Start")
        frame_row.prop(scene, "bi_animation_frame_end", text="End")
        timing_box.prop(scene, "bi_animation_frame_step", text="Frame Step")
        fps_row = timing_box.row(align=True)
        fps_row.prop(scene, "bi_rx_source_fps")
        fps_row.prop(scene, "bi_rx_target_game_fps")
        timing_box.prop(scene, "bi_rx_playback_speed")
        timing_box.label(
            text=(
                f"Scene FPS source: {_safe_scene_fps(scene):g}; "
                f"derived runtime step: {_derived_ticks_per_sample(scene)} present(s)"
            ),
            icon="INFO",
        )

        route_box = workflow_box.box()
        _draw_plan_preview(route_box, scene, plan, preview_error)

        active_info_box = workflow_box.box()
        active_info_box.label(text="Active Context", icon="VIEWZOOM")
        active_info_box.label(text=f"Source Mesh: {source_mesh.name if source_mesh else 'None'}", icon="MESH_DATA")
        active_info_box.label(text=f"Proxy Armature: {proxy_armature.name if proxy_armature else 'None'}", icon="ARMATURE_DATA")

        _draw_active_object_advanced(workflow_box.box(), scene, active_object)

        defaults_box = workflow_box.box()
        defaults_box.label(text="Default Export Adapters", icon="ORIENTATION_GLOBAL")
        defaults_box.prop(scene, "bi_export_mirror_x")
        defaults_box.prop(scene, "bi_export_uv_mirror_u")
        defaults_box.prop(scene, "bi_export_uv_flip_v")

        morph_defaults_box = workflow_box.box()
        morph_defaults_box.label(text="Morph Defaults", icon="SHAPEKEY_DATA")
        morph_defaults_box.prop(scene, "bi_morph_include_normals")
        tangent_row = morph_defaults_box.row()
        tangent_row.enabled = bool(scene.bi_morph_include_normals)
        tangent_row.prop(scene, "bi_morph_include_tangents")
        morph_defaults_box.prop(scene, "bi_morph_channel_mode")

        utilities_box = workflow_box.box()
        utilities_box.label(text="Utilities", icon="TOOL_SETTINGS")
        selected_mesh_count = sum(
            1 for obj in context.selected_objects if obj.type == "MESH" and len(obj.vertex_groups) > 0
        )
        utility_row = utilities_box.row(align=True)
        utility_row.operator("object.bi_generate_proxy_rig", text="Generate Slot Proxy", icon="ARMATURE_DATA")
        utility_row.operator("object.bi_restore_numeric_vertex_groups", text="Restore Numeric Groups", icon="SORTSIZE")
        utility_row.enabled = selected_mesh_count > 0
        debug_row = utilities_box.row(align=True)
        debug_row.operator("object.bi_dump_debug", icon="FILE_TEXT")
        debug_row.enabled = proxy_armature is not None

        if proxy_armature is not None:
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
