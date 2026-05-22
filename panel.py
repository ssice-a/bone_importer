"""Bone Importer sidebar panel."""

from __future__ import annotations

import bpy

from .core.context import find_proxy_armature_for_object, find_source_mesh_for_object
from .core.i18n import tr
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
        return None, "preview.no_collection"
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
    header.label(text=tr(scene, "preview.title"), icon="OUTLINER_COLLECTION")

    if not bool(scene.bi_rx_preview_expanded):
        return

    if error_message:
        label_key = error_message if error_message.startswith("preview.") else ""
        box.label(text=tr(scene, label_key) if label_key else error_message, icon="ERROR")
        box.label(text=tr(scene, "preview.expected"), icon="INFO")
        return

    counts = _plan_counts(plan)
    grid = box.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=True)
    grid.label(text=tr(scene, "preview.ib", count=counts["ib"]), icon="EVENT_I")
    grid.label(text=tr(scene, "preview.parts", count=counts["part"]), icon="EVENT_P")
    grid.label(text=tr(scene, "preview.segments", count=counts["segment"]), icon="MESH_DATA")
    grid.label(text=tr(scene, "preview.geometry", count=counts["replacement"]), icon="MOD_BUILD")
    grid.label(text=tr(scene, "preview.source", count=counts["source"]), icon="LINKED")
    grid.label(text=tr(scene, "preview.own", count=counts["own"]), icon="ARMATURE_DATA")
    grid.label(text=tr(scene, "preview.morph", count=counts["morph"]), icon="SHAPEKEY_DATA")
    grid.label(text=tr(scene, "preview.preskin", count=counts["preskin"]), icon="MOD_ARMATURE")

    shown = 0
    for draw_part in plan.draw_parts:
        if shown >= 8:
            break
        state_key = "preview.skip" if draw_part.skip_original else "preview.keep"
        row = box.row(align=True)
        row.label(text=tr(scene, state_key, key=draw_part.identity.draw_key), icon="RESTRICT_VIEW_OFF")
        shown += 1
    hidden = counts["ib"] - shown
    if hidden > 0:
        box.label(text=tr(scene, "preview.more", count=hidden), icon="INFO")


def _draw_action_bank(box, scene):
    header = box.row(align=True)
    icon = "TRIA_DOWN" if bool(scene.bi_rx_action_panel_expanded) else "TRIA_RIGHT"
    header.prop(scene, "bi_rx_action_panel_expanded", text="", icon=icon, emboss=False)
    header.label(text=tr(scene, "action_bank.title"), icon="ACTION")

    if not bool(scene.bi_rx_action_panel_expanded):
        return

    try:
        from .core.action_bank_editor import list_actions

        actions = list_actions(scene.bi_animation_output_dir)
    except Exception as exc:
        box.label(text=f"No Action Bank: {exc}", icon="INFO")
        return

    if not actions:
        box.label(text="No exported Action yet.", icon="INFO")
        return

    box.label(text=tr(scene, "action_bank.help"), icon="INFO")
    row = box.row(align=True)
    row.prop(scene, "bi_rx_action_name", text=tr(scene, "action_bank.selected"))
    row.operator("object.bi_rx_use_action_for_export", text=tr(scene, "action_bank.use"), icon="IMPORT")

    rename_row = box.row(align=True)
    rename_row.prop(scene, "bi_rx_action_new_name", text=tr(scene, "action_bank.new_name"))
    rename_row.operator("object.bi_rx_rename_action", text=tr(scene, "action_bank.rename"), icon="GREASEPENCIL")

    delete_row = box.row(align=True)
    delete_row.alert = True
    delete_row.operator("object.bi_rx_delete_action", text=tr(scene, "action_bank.delete"), icon="TRASH")

    for action in actions[:8]:
        action_row = box.row(align=True)
        action_row.label(
            text=(
                f"{int(action.get('clip_index', 0))}: {action.get('name', 'action')} "
                f"({int(action.get('sample_count', 0) or 0)} samples)"
            ),
            icon="SEQUENCE",
        )


def _draw_active_object_advanced(box, scene, active_object):
    header = box.row(align=True)
    icon = "TRIA_DOWN" if bool(scene.bi_rx_object_advanced_expanded) else "TRIA_RIGHT"
    header.prop(scene, "bi_rx_object_advanced_expanded", text="", icon=icon, emboss=False)
    header.label(text=tr(scene, "advanced.title"), icon="PREFERENCES")

    if not bool(scene.bi_rx_object_advanced_expanded):
        return
    if active_object is None or active_object.type != "MESH":
        box.label(text=tr(scene, "advanced.no_mesh"), icon="INFO")
        return

    route_box = box.box()
    route_box.label(text=tr(scene, "advanced.final_route"), icon="MOD_ARMATURE")
    route_box.prop(active_object, "bi_final_skin")
    route_box.prop(active_object, "bi_final_armature")
    route_box.prop(active_object, "bi_force_replace_geometry")

    preskin_box = box.box()
    preskin_box.label(text=tr(scene, "advanced.preskin"), icon="ARMATURE_DATA")
    preskin_box.prop(active_object, "bi_preskin_bone_enabled")
    preskin_fields = preskin_box.column(align=True)
    preskin_fields.enabled = bool(getattr(active_object, "bi_preskin_bone_enabled", False))
    preskin_fields.prop(active_object, "bi_preskin_armature")
    preskin_fields.prop(active_object, "bi_preskin_action")

    morph_box = box.box()
    morph_box.label(text=tr(scene, "advanced.morph"), icon="SHAPEKEY_DATA")
    morph_box.prop(active_object, "bi_morph_enabled")
    morph_box.prop(active_object, "bi_morph_source_object")
    morph_box.prop(active_object, "bi_base_position_path")
    morph_box.prop(active_object, "bi_base_position_stride")

    adapter_box = box.box()
    adapter_box.label(text=tr(scene, "advanced.adapters"), icon="ORIENTATION_GLOBAL")
    adapter_box.prop(active_object, "bi_match_priority")
    adapter_box.prop(active_object, "bi_cb1_profile")
    adapter_box.prop(active_object, "bi_vb_layout_profile")
    adapter_box.prop(active_object, "bi_buffer_correction_mode")
    adapter_box.prop(active_object, "bi_export_mirror_x")
    adapter_box.prop(active_object, "bi_export_uv_mirror_u")
    adapter_box.prop(active_object, "bi_export_uv_flip_v")

    legacy_box = box.box()
    legacy_box.label(text=tr(scene, "advanced.legacy_bone"), icon="BONE_DATA")
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
        workflow_box.label(text=tr(scene, "panel.title"), icon="ARMATURE_DATA")

        setup_box = workflow_box.box()
        setup_box.label(text=tr(scene, "setup.title"), icon="EXPORT")
        setup_box.prop(scene, "bi_ui_language", text="Language / 语言")
        setup_box.prop(scene, "bi_animation_output_dir", text=tr(scene, "setup.output_dir"))
        setup_box.prop(scene, "bi_capture_manifest_path", text=tr(scene, "setup.capture_manifest"))
        setup_box.prop(scene, "bi_export_collection", text=tr(scene, "setup.collection"))
        setup_box.operator("object.bi_create_rx_export_collection", text=tr(scene, "setup.create_collection"), icon="OUTLINER_COLLECTION")
        setup_box.prop(scene, "bi_rx_export_type")
        setup_box.prop(scene, "bi_rx_export_geometry")
        export_row = setup_box.row(align=True)
        export_row.operator("object.bi_export_rx_package", text=tr(scene, "setup.export"), icon="EXPORT")
        export_row.enabled = bool(has_plan)

        timing_box = workflow_box.box()
        timing_box.label(text=tr(scene, "timeline.title"), icon="ACTION")
        clip_row = timing_box.row(align=True)
        clip_row.prop(scene, "bi_animation_clip_name", text=tr(scene, "timeline.clip"))
        clip_row.prop(scene, "bi_animation_clip_id", text=tr(scene, "timeline.id"))
        frame_row = timing_box.row(align=True)
        frame_row.prop(scene, "bi_animation_frame_start", text=tr(scene, "timeline.start"))
        frame_row.prop(scene, "bi_animation_frame_end", text=tr(scene, "timeline.end"))
        timing_box.prop(scene, "bi_animation_frame_step", text=tr(scene, "timeline.frame_step"))
        fps_row = timing_box.row(align=True)
        fps_row.prop(scene, "bi_rx_source_fps")
        fps_row.prop(scene, "bi_rx_target_game_fps")
        timing_box.prop(scene, "bi_rx_playback_speed")
        timing_box.label(
            text=tr(scene, "timeline.derived_step", fps=_safe_scene_fps(scene), step=_derived_ticks_per_sample(scene)),
            icon="INFO",
        )

        _draw_action_bank(workflow_box.box(), scene)

        route_box = workflow_box.box()
        _draw_plan_preview(route_box, scene, plan, preview_error)

        active_info_box = workflow_box.box()
        active_info_box.label(text=tr(scene, "active.title"), icon="VIEWZOOM")
        active_info_box.label(
            text=tr(scene, "active.source_mesh", name=source_mesh.name if source_mesh else "None"),
            icon="MESH_DATA",
        )
        active_info_box.label(
            text=tr(scene, "active.proxy_armature", name=proxy_armature.name if proxy_armature else "None"),
            icon="ARMATURE_DATA",
        )

        _draw_active_object_advanced(workflow_box.box(), scene, active_object)

        defaults_box = workflow_box.box()
        defaults_box.label(text=tr(scene, "defaults.title"), icon="ORIENTATION_GLOBAL")
        defaults_box.prop(scene, "bi_export_mirror_x")
        defaults_box.prop(scene, "bi_export_uv_mirror_u")
        defaults_box.prop(scene, "bi_export_uv_flip_v")

        morph_defaults_box = workflow_box.box()
        morph_defaults_box.label(text=tr(scene, "morph_defaults.title"), icon="SHAPEKEY_DATA")
        morph_defaults_box.prop(scene, "bi_morph_include_normals")
        tangent_row = morph_defaults_box.row()
        tangent_row.enabled = bool(scene.bi_morph_include_normals)
        tangent_row.prop(scene, "bi_morph_include_tangents")
        morph_defaults_box.prop(scene, "bi_morph_channel_mode")

        utilities_box = workflow_box.box()
        utilities_box.label(text=tr(scene, "utilities.title"), icon="TOOL_SETTINGS")
        selected_mesh_count = sum(
            1 for obj in context.selected_objects if obj.type == "MESH" and len(obj.vertex_groups) > 0
        )
        utility_row = utilities_box.row(align=True)
        utility_row.operator("object.bi_generate_proxy_rig", text=tr(scene, "utilities.generate_proxy"), icon="ARMATURE_DATA")
        utility_row.operator("object.bi_restore_numeric_vertex_groups", text=tr(scene, "utilities.restore_groups"), icon="SORTSIZE")
        utility_row.enabled = selected_mesh_count > 0
        debug_row = utilities_box.row(align=True)
        debug_row.operator("object.bi_dump_debug", icon="FILE_TEXT")
        debug_row.enabled = proxy_armature is not None

        if proxy_armature is not None:
            proxy_bone_count = sum(1 for pose_bone in proxy_armature.pose.bones if getattr(pose_bone, "bi_is_proxy", False))
            workflow_box.label(text=tr(scene, "proxy.count", count=proxy_bone_count), icon="INFO")

        active_proxy_bone = context.active_pose_bone if context.active_object == proxy_armature else None
        if active_proxy_bone and getattr(active_proxy_bone, "bi_is_proxy", False):
            active_bone_box = workflow_box.box()
            active_bone_box.label(text=tr(scene, "proxy.active", name=active_proxy_bone.name), icon="BONE_DATA")
            active_bone_box.prop(active_proxy_bone, "bi_slot_id")
            active_bone_box.prop(active_proxy_bone, "bi_mesh_key")
            active_bone_box.prop(active_proxy_bone, "bi_bone_type")
            active_bone_box.prop(active_proxy_bone, "bi_export_enabled")
            active_bone_box.prop(active_proxy_bone, "bi_bind_valid", text="Bind Captured")
