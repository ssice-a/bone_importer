"""High-level workflows used by Blender operators."""

from contextlib import ExitStack
import os
from time import perf_counter

import bpy
from mathutils import Matrix

from ..constants import DEFAULT_PART_ROW_COUNT
from .animation_export import (
    build_tqs_frame_buffer,
    finalize_animation_export_job,
    normalize_clip_name,
    prepare_animation_export_job,
    write_clip_sidecar_files,
    write_shared_timeline_sidecar_files,
    write_tqs_animation_frame,
)
from .bind import refresh_bind_for_proxy_armature as capture_bind_for_proxy_armature_internal
from .context import (
    apply_part_id_layout,
    capture_selection_state,
    ensure_mesh_parented_to_proxy_armature,
    find_proxy_armature_for_object,
    find_source_mesh_for_object,
    list_selected_proxy_armatures,
    make_object_active,
    restore_selection_state,
)
from .debug import build_proxy_debug_snapshot, print_debug_snapshot
from .draw_part import build_target_draw_parts
from .export import (
    build_palette_export_write_plan_for_proxy_armatures,
    cache_current_palette_segment,
    clear_previous_palette_cache,
)
from .importer import apply_palette_segment_to_proxy_armature, resolve_palette_segment_window
from .ini_export import write_generated_runtime_ini
from .io import (
    build_metadata_path_from_binary_path,
    load_palette_file,
    read_palette_metadata_from_file,
    write_palette_row_patches_to_disk,
)
from .layout import calculate_slot_capacity_for_part_size
from .manifest import write_export_manifest
from .models import (
    BatchAnimationExportResult,
    BatchBindRefreshResult,
    BatchMorphExportResult,
    BatchPaletteExportResult,
    BatchPaletteImportResult,
    BatchProxyRigGenerationResult,
    DebugDumpResult,
    PaletteImportResult,
    ProxyBindCaptureResult,
    ProxyRigGenerationResult,
)
from .morph_export import (
    MORPH_CHANNEL_MODE_ANIMATED,
    export_morph_mesh_for_proxy_armature,
    write_morph_manifest,
)
from .proxy import (
    build_proxy_bone_definitions,
    capture_proxy_bind_matrices,
    configure_proxy_pose_bones,
    ensure_suffixed_numeric_vertex_groups,
    ensure_proxy_armature_modifier,
    list_other_armature_modifier_names,
    rebuild_proxy_edit_bones,
)


def prepare_proxy_armature(proxy_armature, require_part_id=False):
    """Sync derived layout settings and return the linked source mesh."""
    source_mesh = find_source_mesh_for_object(proxy_armature)
    apply_part_id_layout(proxy_armature, require_configured=require_part_id)
    return source_mesh


def build_proxy_generation_result(source_mesh, proxy_armature, proxy_bone_build, configured_bone_count):
    """Build the result summary for one generated proxy rig."""
    bone_definitions = proxy_bone_build["bone_definitions"]
    max_slot_id = max((bone_definition["slot_id"] for bone_definition in bone_definitions), default=-1)
    slot_capacity = calculate_slot_capacity_for_part_size(
        int(getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT))
    )
    other_armature_modifiers = list_other_armature_modifier_names(source_mesh, proxy_armature)
    return ProxyRigGenerationResult(
        source_mesh_name=source_mesh.name,
        armature_name=proxy_armature.name,
        configured_bones=configured_bone_count,
        max_slot=max_slot_id,
        slot_capacity=slot_capacity,
        skipped_groups=tuple(proxy_bone_build["skipped_group_names"]),
        other_armature_modifiers=other_armature_modifiers,
    )


def _build_shared_proxy_armature_name(context):
    scene = getattr(context, "scene", None)
    export_collection = getattr(scene, "bi_export_collection", None) if scene is not None else None
    if export_collection is not None:
        base_name = str(export_collection.name or "RX")
    else:
        base_name = "RX"
    safe_name = "".join(character if character.isalnum() or character in "._-" else "_" for character in base_name)
    return f"{safe_name}_SharedProxy"


def _get_or_create_shared_proxy_armature(context, selected_meshes):
    proxy_armature_name = _build_shared_proxy_armature_name(context)
    proxy_armature = bpy.data.objects.get(proxy_armature_name)
    if proxy_armature and proxy_armature.type != "ARMATURE":
        raise ValueError(f"Object named {proxy_armature_name} exists but is not an armature")

    if proxy_armature is None:
        armature_data = bpy.data.armatures.new(proxy_armature_name)
        proxy_armature = bpy.data.objects.new(proxy_armature_name, armature_data)
        first_mesh = selected_meshes[0]
        target_collection = first_mesh.users_collection[0] if first_mesh.users_collection else context.collection
        target_collection.objects.link(proxy_armature)

    proxy_armature.matrix_world = Matrix.Identity(4)
    proxy_armature.show_in_front = True
    proxy_armature.data.display_type = "STICK"
    proxy_armature.bi_is_proxy_armature = True
    proxy_armature.bi_source_mesh_name = ""
    proxy_armature.bi_part_id = -1
    proxy_armature.bi_part_base = 0
    proxy_armature.bi_part_size = DEFAULT_PART_ROW_COUNT
    return proxy_armature


def _transform_bone_definitions_to_armature_space(mesh_obj, proxy_armature, bone_definitions):
    mesh_to_armature = proxy_armature.matrix_world.inverted() @ mesh_obj.matrix_world
    transformed_definitions = []
    for bone_definition in bone_definitions:
        transformed_definition = dict(bone_definition)
        transformed_definition["head"] = mesh_to_armature @ bone_definition["head"]
        transformed_definition["tail"] = mesh_to_armature @ bone_definition["tail"]
        transformed_definitions.append(transformed_definition)
    return transformed_definitions


def _generate_shared_proxy_rig_for_meshes(context, selected_meshes):
    """Generate one shared proxy armature for all selected draw-part meshes."""
    if not selected_meshes:
        raise ValueError("Select at least one mesh object")

    proxy_armature = _get_or_create_shared_proxy_armature(context, selected_meshes)
    combined_bone_definitions = []
    skipped_mesh_names = []
    skipped_details = []
    generated_meshes = 0
    generated_bones = 0
    max_slot_id = -1
    other_armature_modifier_names = []

    for mesh_obj in selected_meshes:
        if mesh_obj is None or mesh_obj.type != "MESH":
            continue
        if len(mesh_obj.vertex_groups) == 0:
            skipped_mesh_names.append(mesh_obj.name)
            skipped_details.append(f"{mesh_obj.name}: no vertex groups")
            continue
        try:
            ensure_suffixed_numeric_vertex_groups(mesh_obj)
            proxy_bone_build = build_proxy_bone_definitions(mesh_obj)
        except ValueError as exc:
            skipped_mesh_names.append(mesh_obj.name)
            skipped_details.append(f"{mesh_obj.name}: {exc}")
            continue

        bone_definitions = proxy_bone_build["bone_definitions"]
        if not bone_definitions:
            skipped_mesh_names.append(mesh_obj.name)
            skipped_details.append(f"{mesh_obj.name}: no weighted numeric vertex groups")
            continue

        combined_bone_definitions.extend(
            _transform_bone_definitions_to_armature_space(mesh_obj, proxy_armature, bone_definitions)
        )
        generated_meshes += 1
        generated_bones += len(bone_definitions)
        if bone_definitions:
            max_slot_id = max(max_slot_id, max(int(definition["slot_id"]) for definition in bone_definitions))
        other_armature_modifier_names.extend(list_other_armature_modifier_names(mesh_obj, proxy_armature))

    if not combined_bone_definitions:
        raise ValueError("No selected mesh produced proxy bones")

    make_object_active(context, proxy_armature, mode="EDIT")
    rebuild_proxy_edit_bones(proxy_armature, combined_bone_definitions)
    bpy.ops.object.mode_set(mode="POSE")

    configured_bone_count = configure_proxy_pose_bones(proxy_armature)
    capture_proxy_bind_matrices(proxy_armature)
    clear_previous_palette_cache(proxy_armature)
    for mesh_obj in selected_meshes:
        mesh_obj.bi_proxy_armature_name = proxy_armature.name
        ensure_proxy_armature_modifier(mesh_obj, proxy_armature)
        ensure_mesh_parented_to_proxy_armature(mesh_obj, proxy_armature)

    return BatchProxyRigGenerationResult(
        generated_meshes=generated_meshes,
        generated_armatures=1,
        generated_bones=configured_bone_count,
        skipped_meshes=tuple(skipped_mesh_names),
        skipped_details=tuple(skipped_details),
    )


def generate_proxy_rig_for_mesh(context, source_mesh):
    """Generate the shared proxy armature from one mesh."""
    if source_mesh is None or source_mesh.type != "MESH":
        raise ValueError("Active object must be a mesh")

    result = _generate_shared_proxy_rig_for_meshes(context, [source_mesh])
    proxy_armature = find_proxy_armature_for_object(source_mesh)
    proxy_bone_build = build_proxy_bone_definitions(source_mesh)
    return ProxyRigGenerationResult(
        source_mesh_name=source_mesh.name,
        armature_name=proxy_armature.name if proxy_armature else "",
        configured_bones=result.generated_bones,
        max_slot=max((definition["slot_id"] for definition in proxy_bone_build["bone_definitions"]), default=-1),
        slot_capacity=calculate_slot_capacity_for_part_size(DEFAULT_PART_ROW_COUNT),
        skipped_groups=tuple(proxy_bone_build["skipped_group_names"]),
        other_armature_modifiers=list_other_armature_modifier_names(source_mesh, proxy_armature),
    )


def generate_proxy_rig_from_active_mesh(context):
    """Generate a proxy armature from the active mesh."""
    return generate_proxy_rig_for_mesh(context, context.active_object)


def generate_proxy_rigs_from_selected_meshes(context):
    """Generate one shared proxy armature for all selected meshes."""
    selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if not selected_meshes:
        raise ValueError("Select at least one mesh object")

    selection_state = capture_selection_state(context)

    try:
        result = _generate_shared_proxy_rig_for_meshes(context, selected_meshes)
    finally:
        restore_selection_state(context, selection_state)

    return result


def build_target_proxy_armatures(context):
    """Resolve proxy armatures that should have bind data refreshed."""
    scene = getattr(context, "scene", None)
    export_collection = getattr(scene, "bi_export_collection", None) if scene is not None else None
    if export_collection is not None:
        collection_armatures = {
            draw_part.proxy_armature.name_full: draw_part.proxy_armature
            for draw_part in build_target_draw_parts(context)
        }
        if collection_armatures:
            return tuple(collection_armatures.values())
        raise ValueError(f"RX Export Collection '{export_collection.name}' has no linked proxy armatures")

    directly_selected_armatures = tuple(
        obj for obj in context.selected_objects
        if obj.type == "ARMATURE" and getattr(obj, "bi_is_proxy_armature", False)
    )
    if directly_selected_armatures:
        return directly_selected_armatures

    active_proxy_armature = find_proxy_armature_for_object(context.active_object)
    if active_proxy_armature is not None:
        return (active_proxy_armature,)

    selected_armatures = {
        draw_part.proxy_armature.name_full: draw_part.proxy_armature
        for draw_part in build_target_draw_parts(context)
    }
    if selected_armatures:
        return tuple(selected_armatures.values())

    raise ValueError("No selected proxy armatures found")


def refresh_bind_for_proxy_armature(proxy_armature):
    """Refresh bind matrices for one proxy armature."""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    source_mesh = prepare_proxy_armature(proxy_armature, require_part_id=False)
    captured_bones = capture_bind_for_proxy_armature_internal(proxy_armature)
    other_armature_modifiers = ()
    if source_mesh is not None:
        other_armature_modifiers = list_other_armature_modifier_names(source_mesh, proxy_armature)
    return ProxyBindCaptureResult(
        armature_name=proxy_armature.name,
        captured_bones=captured_bones,
        other_armature_modifiers=other_armature_modifiers,
    )


def refresh_bind_for_active_proxy(active_object):
    """Refresh bind matrices for the active proxy armature."""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return refresh_bind_for_proxy_armature(proxy_armature)


def refresh_bind_for_selected_proxy_armatures(context):
    """Refresh bind matrices for the current target proxy armature set."""
    target_armatures = build_target_proxy_armatures(context)
    selection_state = capture_selection_state(context)
    refreshed_armatures = 0
    refreshed_bones = 0
    failed_armatures = []

    try:
        for proxy_armature in target_armatures:
            try:
                result = refresh_bind_for_proxy_armature(proxy_armature)
            except Exception as exc:
                failed_armatures.append(f"{proxy_armature.name}: {exc}")
                continue

            refreshed_armatures += 1
            refreshed_bones += result.captured_bones
    finally:
        restore_selection_state(context, selection_state)

    return BatchBindRefreshResult(
        selected_armatures=len(target_armatures),
        refreshed_armatures=refreshed_armatures,
        refreshed_bones=refreshed_bones,
        failed_armatures=tuple(failed_armatures),
    )


def export_palette_for_proxy_armatures(context, proxy_armatures, output_path, write_metadata=True):
    """Export one or more proxy armatures into a single static buffer file."""
    normalized_armatures = tuple(proxy_armatures)
    if not normalized_armatures:
        raise ValueError("No proxy armatures to export")

    selection_state = capture_selection_state(context)
    try:
        for proxy_armature in normalized_armatures:
            prepare_proxy_armature(proxy_armature, require_part_id=True)
        write_plan = build_palette_export_write_plan_for_proxy_armatures(normalized_armatures)
        for proxy_armature, part_patch in zip(normalized_armatures, write_plan["part_patches"]):
            cache_current_palette_segment(proxy_armature, part_patch["current_segment"])
    finally:
        restore_selection_state(context, selection_state)

    binary_path, metadata_path = write_palette_row_patches_to_disk(
        write_plan["row_patches"],
        output_path=output_path,
        armature_name="selected_parts",
        buffer_row_count=write_plan["buffer_row_count"],
        metadata=write_plan["metadata"],
        write_metadata=write_metadata,
    )

    parts_metadata = write_plan["metadata"].get("parts", [])
    return BatchPaletteExportResult(
        binary_path=binary_path,
        metadata_path=metadata_path,
        selected_armatures=len(normalized_armatures),
        exported_armatures=len(parts_metadata),
        exported_bones=sum(len(part.get("exported_bones", ())) for part in parts_metadata),
        overflow_bones=len(write_plan["metadata"].get("overflow_bones", ())),
        failed_armatures=(),
        metadata=write_plan["metadata"],
    )


def export_palette_for_selected_proxy_armatures(context, output_path, write_metadata=True):
    """Export the current target draw-part set as a static palette file."""
    return export_palette_for_proxy_armatures(
        context,
        build_target_draw_parts(context),
        output_path,
        write_metadata,
    )


def export_palette_for_proxy_armature(proxy_armature, output_path, write_metadata=True):
    """Compatibility wrapper for exporting one static palette."""
    return export_palette_for_proxy_armatures(bpy.context, (proxy_armature,), output_path, write_metadata)


def export_palette_for_active_proxy(active_object, output_path, write_metadata=True):
    """Compatibility wrapper for exporting the active proxy armature."""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return export_palette_for_proxy_armature(proxy_armature, output_path, write_metadata)


def export_animation_for_draw_parts(
    context,
    draw_parts,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    presents_per_step=1,
    default_loop_start=-1,
    default_loop_end=-1,
    write_metadata=True,
):
    """Export one scene-evaluated TQS animation set per runtime draw part."""
    normalized_draw_parts = tuple(draw_parts)
    if not normalized_draw_parts:
        raise ValueError("No draw parts to export")

    normalized_clip_name = normalize_clip_name(clip_name)
    selection_state = capture_selection_state(context)
    exported_armatures = 0
    total_frames = 0
    total_exported_bones = 0
    failed_armatures = []
    exported_files = []
    completed_results = []
    export_jobs = []
    scene = context.scene
    original_frame = scene.frame_current if scene is not None else 0
    elapsed_seconds = 0.0
    frame_set_seconds = 0.0
    frame_write_seconds = 0.0
    finalize_seconds = 0.0
    other_seconds = 0.0
    progress_started = False
    progress_total = 0
    progress_step = 0
    progress_stride = 1
    sampled_frames = 0
    clip_manifest_path = ""
    timeline_static_path = ""
    master_playback_path = ""
    morph_manifest_path = ""
    generated_ini_path = ""
    export_manifest_path = ""
    exported_morph_meshes = 0
    total_morph_channels = 0
    morph_results = []
    cb1_override_by_mesh_key = {
        draw_part.draw_key: draw_part.cb1_override
        for draw_part in normalized_draw_parts
    }
    total_start_time = perf_counter()
    window_manager = context.window_manager if context is not None else None

    try:
        for draw_part in normalized_draw_parts:
            try:
                export_jobs.append(
                    prepare_animation_export_job(
                        proxy_armature=draw_part,
                        output_directory=output_directory,
                        clip_name=normalized_clip_name,
                        clip_id=clip_id,
                        frame_start=frame_start,
                        frame_end=frame_end,
                        frame_step=frame_step,
                        fps=fps,
                        presents_per_step=presents_per_step,
                        default_loop_start=default_loop_start,
                        default_loop_end=default_loop_end,
                        write_metadata=write_metadata,
                    )
                )
            except Exception as exc:
                failed_armatures.append(f"{draw_part.draw_key}: {exc}")
                continue

        if export_jobs and scene is not None:
            exported_frames = export_jobs[0]["exported_frames"]
            sampled_frames = len(exported_frames)
            progress_total = max(len(exported_frames), 1)
            progress_stride = max(1, progress_total // 200)
            if window_manager is not None:
                window_manager.progress_begin(0, progress_total)
                progress_started = True
            with ExitStack() as stack:
                active_jobs = []
                for export_job in export_jobs:
                    export_job["binary_file"] = stack.enter_context(open(export_job["tqs_path"], "wb"))
                    export_job["frame_buffer"] = build_tqs_frame_buffer(export_job["export_entries"])
                    active_jobs.append(export_job)

                for frame_number in exported_frames:
                    frame_set_start_time = perf_counter()
                    scene.frame_set(frame_number)
                    frame_set_seconds += perf_counter() - frame_set_start_time
                    progress_step += 1
                    if progress_started and (
                        progress_step == progress_total
                        or progress_step == 1
                        or (progress_step % progress_stride) == 0
                    ):
                        window_manager.progress_update(progress_step)

                    frame_write_start_time = perf_counter()
                    next_active_jobs = []
                    for export_job in active_jobs:
                        try:
                            write_tqs_animation_frame(
                                export_job["binary_file"],
                                export_job["export_entries"],
                                export_job["frame_buffer"],
                            )
                        except Exception as exc:
                            failed_armatures.append(f"{export_job['metadata'].get('draw_key', export_job['proxy_armature'].name)}: {exc}")
                            for cleanup_path in (
                                export_job["tqs_path"],
                                export_job["bind_path"],
                                export_job["static_clip_path"],
                                export_job["debug_metadata_path"],
                            ):
                                if cleanup_path and os.path.exists(cleanup_path):
                                    os.remove(cleanup_path)
                            continue
                        next_active_jobs.append(export_job)
                    frame_write_seconds += perf_counter() - frame_write_start_time
                    active_jobs = next_active_jobs
                    if not active_jobs:
                        break

            export_jobs = active_jobs

        for export_job in export_jobs:
            finalize_start_time = perf_counter()
            try:
                result = finalize_animation_export_job(export_job)
            except Exception as exc:
                failed_armatures.append(f"{export_job['metadata'].get('draw_key', export_job['proxy_armature'].name)}: {exc}")
                for cleanup_path in (
                    export_job["tqs_path"],
                    export_job["bind_path"],
                    export_job["static_clip_path"],
                    export_job["debug_metadata_path"],
                ):
                    if cleanup_path and os.path.exists(cleanup_path):
                        os.remove(cleanup_path)
                continue
            finally:
                finalize_seconds += perf_counter() - finalize_start_time

            exported_armatures += 1
            total_frames += result.frame_count
            total_exported_bones += result.bone_count
            completed_results.append(result)
            exported_files += [result.tqs_path, result.bind_path, result.static_clip_path]
            if result.debug_metadata_path:
                exported_files.append(result.debug_metadata_path)

        try:
            (
                clip_manifest_path,
                timeline_static_path,
                master_playback_path,
                timeline_static_metadata_path,
                master_playback_metadata_path,
            ) = write_clip_sidecar_files(
                output_directory=output_directory,
                clip_name=normalized_clip_name,
                clip_id=clip_id,
                export_results=completed_results,
                write_metadata=write_metadata,
            )
        except Exception as exc:
            failed_armatures.append(f"{normalized_clip_name} manifest: {exc}")
            clip_manifest_path = ""
            timeline_static_path = ""
            master_playback_path = ""
        else:
            for shared_path in (
                clip_manifest_path,
                timeline_static_path,
                master_playback_path,
                timeline_static_metadata_path,
                master_playback_metadata_path,
            ):
                if shared_path:
                    exported_files.append(shared_path)

        try:
            generated_ini_path = write_generated_runtime_ini(
                output_directory=output_directory,
                clip_name=normalized_clip_name,
                export_results=tuple(completed_results),
                morph_results=tuple(morph_results),
                cb1_override_by_mesh_key=cb1_override_by_mesh_key,
                draw_parts=normalized_draw_parts,
            )
        except Exception as exc:
            failed_armatures.append(f"{normalized_clip_name} generated ini: {exc}")
            generated_ini_path = ""
        else:
            if generated_ini_path:
                exported_files.append(generated_ini_path)

        try:
            export_manifest_path = write_export_manifest(
                output_directory=output_directory,
                clip_name=normalized_clip_name,
                clip_id=clip_id,
                draw_parts=normalized_draw_parts,
                export_results=tuple(completed_results),
                morph_results=tuple(morph_results),
            )
        except Exception as exc:
            failed_armatures.append(f"{normalized_clip_name} export manifest: {exc}")
        else:
            if export_manifest_path:
                exported_files.append(export_manifest_path)
    finally:
        if scene is not None:
            scene.frame_set(original_frame)
        if progress_started:
            window_manager.progress_end()
        restore_selection_state(context, selection_state)
        elapsed_seconds = perf_counter() - total_start_time
        other_seconds = max(
            0.0,
            elapsed_seconds - frame_set_seconds - frame_write_seconds - finalize_seconds,
        )

    print(
        "[Bone Importer] Animation export finished in "
        f"{elapsed_seconds:.2f}s | frame_set={frame_set_seconds:.2f}s"
        f" | frame_write={frame_write_seconds:.2f}s | finalize={finalize_seconds:.2f}s"
        f" | other={other_seconds:.2f}s | sampled_frames={sampled_frames}"
        f" | selected={len(normalized_draw_parts)} | exported={exported_armatures}"
    )

    return BatchAnimationExportResult(
        output_directory=bpy.path.abspath(output_directory or "//"),
        clip_name=normalized_clip_name,
        clip_id=int(clip_id),
        selected_armatures=len(normalized_draw_parts),
        exported_armatures=exported_armatures,
        total_frames=total_frames,
        total_exported_bones=total_exported_bones,
        sampled_frames=sampled_frames,
        elapsed_seconds=elapsed_seconds,
        frame_set_seconds=frame_set_seconds,
        frame_write_seconds=frame_write_seconds,
        finalize_seconds=finalize_seconds,
        other_seconds=other_seconds,
        failed_armatures=tuple(failed_armatures),
        exported_files=tuple(exported_files),
        clip_manifest_path=clip_manifest_path,
        timeline_static_path=timeline_static_path,
        master_playback_path=master_playback_path,
        exported_morph_meshes=exported_morph_meshes,
        total_morph_channels=total_morph_channels,
        morph_manifest_path=morph_manifest_path,
        generated_ini_path=generated_ini_path,
    )


def export_morph_for_draw_parts(
    context,
    draw_parts,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    presents_per_step=1,
    default_loop_start=-1,
    default_loop_end=-1,
    write_metadata=True,
):
    """Export only RX morph buffers while still seeding the shared timeline sidecars."""
    normalized_draw_parts = tuple(draw_parts)
    if not normalized_draw_parts:
        raise ValueError("No draw parts to export")

    normalized_clip_name = normalize_clip_name(clip_name)
    selection_state = capture_selection_state(context)
    failed_armatures = []
    exported_files = []
    exported_morph_meshes = 0
    total_morph_channels = 0
    morph_manifest_path = ""
    generated_ini_path = ""
    export_manifest_path = ""
    timeline_static_path = ""
    master_playback_path = ""
    sampled_frames = 0
    morph_results = []
    cb1_override_by_mesh_key = {
        draw_part.draw_key: draw_part.cb1_override
        for draw_part in normalized_draw_parts
    }
    total_start_time = perf_counter()
    scene = context.scene if context is not None else None
    original_frame = scene.frame_current if scene is not None else 0

    try:
        if scene is not None:
            exported_frames = tuple(range(int(frame_start), int(frame_end) + 1, max(int(frame_step), 1)))
            sampled_frames = len(exported_frames)
            morph_channel_mode = getattr(scene, "bi_morph_channel_mode", MORPH_CHANNEL_MODE_ANIMATED)
            morph_include_normals = bool(getattr(scene, "bi_morph_include_normals", True))
            morph_include_tangents = bool(getattr(scene, "bi_morph_include_tangents", False))
            external_morph_source = getattr(scene, "bi_morph_source_object", None)
            target_draw_key = str(getattr(scene, "bi_morph_target_draw_key", "") or "")
            if target_draw_key == "__NONE__":
                target_draw_key = ""

            try:
                (
                    timeline_static_path,
                    master_playback_path,
                    timeline_static_metadata_path,
                    master_playback_metadata_path,
                ) = write_shared_timeline_sidecar_files(
                    output_directory=output_directory,
                    clip_name=normalized_clip_name,
                    clip_id=clip_id,
                    frame_start=frame_start,
                    frame_end=frame_end,
                    frame_step=frame_step,
                    fps=fps,
                    presents_per_step=presents_per_step,
                    default_loop_start=default_loop_start,
                    default_loop_end=default_loop_end,
                    write_metadata=write_metadata,
                )
            except Exception as exc:
                failed_armatures.append(f"{normalized_clip_name} shared timeline: {exc}")
            else:
                for shared_path in (
                    timeline_static_path,
                    master_playback_path,
                    timeline_static_metadata_path,
                    master_playback_metadata_path,
                ):
                    if shared_path:
                        exported_files.append(shared_path)

            morph_draw_parts = normalized_draw_parts
            if external_morph_source is not None:
                if not target_draw_key:
                    raise ValueError("Choose a Target Draw Part when exporting an external Shape Key Source")
                morph_draw_parts = tuple(
                    draw_part for draw_part in normalized_draw_parts if draw_part.draw_key == target_draw_key
                )
                if not morph_draw_parts:
                    raise ValueError(f"Target Draw Part not found: {target_draw_key}")

            for draw_part in morph_draw_parts:
                try:
                    source_mesh = external_morph_source if external_morph_source is not None else draw_part.source_object
                    morph_result = export_morph_mesh_for_proxy_armature(
                        context=context,
                        proxy_armature=draw_part.proxy_armature,
                        source_mesh=source_mesh,
                        output_directory=output_directory,
                        clip_name=normalized_clip_name,
                        clip_id=clip_id,
                        frame_start=frame_start,
                        frame_end=frame_end,
                        frame_step=frame_step,
                        include_normals=morph_include_normals,
                        include_tangents=morph_include_tangents,
                        channel_mode=morph_channel_mode,
                        write_metadata=write_metadata,
                        draw_part=draw_part,
                        mesh_key=draw_part.draw_key,
                    )
                except Exception as exc:
                    failed_armatures.append(f"{draw_part.draw_key} morph: {exc}")
                    continue

                if morph_result is None:
                    continue

                morph_results.append(morph_result)
                exported_morph_meshes += 1
                total_morph_channels += len(morph_result.channel_names)
                exported_files.extend(
                    path
                    for path in (
                        morph_result.morph_static_path,
                        morph_result.morph_anim_path,
                        morph_result.metadata_path,
                    )
                    if path
                )

            try:
                morph_manifest_path = write_morph_manifest(
                    output_directory=output_directory,
                    clip_name=normalized_clip_name,
                    clip_id=clip_id,
                    mesh_results=tuple(morph_results),
                )
            except Exception as exc:
                failed_armatures.append(f"{normalized_clip_name} morph manifest: {exc}")
                morph_manifest_path = ""
            else:
                if morph_manifest_path:
                    exported_files.append(morph_manifest_path)

            try:
                generated_ini_path = write_generated_runtime_ini(
                    output_directory=output_directory,
                    clip_name=normalized_clip_name,
                    export_results=(),
                    morph_results=tuple(morph_results),
                    cb1_override_by_mesh_key=cb1_override_by_mesh_key,
                    draw_parts=normalized_draw_parts,
                )
            except Exception as exc:
                failed_armatures.append(f"{normalized_clip_name} generated ini: {exc}")
                generated_ini_path = ""
            else:
                if generated_ini_path:
                    exported_files.append(generated_ini_path)

            try:
                export_manifest_path = write_export_manifest(
                    output_directory=output_directory,
                    clip_name=normalized_clip_name,
                    clip_id=clip_id,
                    draw_parts=normalized_draw_parts,
                export_results=(),
                morph_results=tuple(morph_results),
                clip_metadata={
                    "frame_start": int(frame_start),
                    "frame_end": int(frame_end),
                    "frame_step": int(frame_step),
                    "frame_count": int(sampled_frames),
                    "fps": float(fps),
                    "default_ticks_per_sample": max(int(presents_per_step), 1),
                    "default_loop_start_sample": 0,
                    "default_loop_end_sample": max(int(sampled_frames) - 1, 0),
                },
            )
            except Exception as exc:
                failed_armatures.append(f"{normalized_clip_name} export manifest: {exc}")
            else:
                if export_manifest_path:
                    exported_files.append(export_manifest_path)
    finally:
        if scene is not None:
            scene.frame_set(original_frame)
        restore_selection_state(context, selection_state)

    elapsed_seconds = perf_counter() - total_start_time
    return BatchMorphExportResult(
        output_directory=bpy.path.abspath(output_directory or "//"),
        clip_name=normalized_clip_name,
        clip_id=int(clip_id),
        selected_armatures=len(normalized_draw_parts),
        exported_morph_meshes=exported_morph_meshes,
        total_morph_channels=total_morph_channels,
        sampled_frames=sampled_frames,
        elapsed_seconds=elapsed_seconds,
        failed_armatures=tuple(failed_armatures),
        exported_files=tuple(exported_files),
        timeline_static_path=timeline_static_path,
        master_playback_path=master_playback_path,
        morph_manifest_path=morph_manifest_path,
        generated_ini_path=generated_ini_path,
    )


def export_animation_for_selected_proxy_armatures(
    context,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    presents_per_step=1,
    default_loop_start=-1,
    default_loop_end=-1,
    write_metadata=True,
):
    """Export standalone RX clip buffers for the current target draw-part set."""
    return export_animation_for_draw_parts(
        context,
        build_target_draw_parts(context),
        output_directory,
        clip_name,
        clip_id,
        frame_start,
        frame_end,
        frame_step,
        fps,
        presents_per_step,
        default_loop_start,
        default_loop_end,
        write_metadata,
    )


def export_morph_for_selected_proxy_armatures(
    context,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    fps,
    presents_per_step=1,
    default_loop_start=-1,
    default_loop_end=-1,
    write_metadata=True,
):
    """Export standalone RX morph buffers for the current target draw-part set."""
    return export_morph_for_draw_parts(
        context,
        build_target_draw_parts(context),
        output_directory,
        clip_name,
        clip_id,
        frame_start,
        frame_end,
        frame_step,
        fps,
        presents_per_step,
        default_loop_start,
        default_loop_end,
        write_metadata,
    )


def import_palette_for_proxy_armature(context, proxy_armature, binary_path, segment="CURRENT"):
    """Import one palette segment onto one proxy armature."""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    source_mesh = prepare_proxy_armature(proxy_armature, require_part_id=True)
    metadata_path = build_metadata_path_from_binary_path(binary_path)
    metadata = read_palette_metadata_from_file(metadata_path)
    palette_window = resolve_palette_segment_window(proxy_armature, metadata, segment)
    loaded_palette_file = load_palette_file(
        binary_path,
        metadata_path=metadata_path,
        row_start=palette_window["segment_base"],
        row_count=palette_window["part_size"],
    )
    import_result = apply_palette_segment_to_proxy_armature(
        context,
        proxy_armature,
        rows=loaded_palette_file.rows,
        binary_path=loaded_palette_file.binary_path,
        row_start=loaded_palette_file.row_start,
        metadata=loaded_palette_file.metadata,
        segment=segment,
    )

    if source_mesh is None:
        return import_result
    return PaletteImportResult(
        armature_name=import_result.armature_name,
        binary_path=import_result.binary_path,
        imported_bones=import_result.imported_bones,
        missing_rows=import_result.missing_rows,
        segment=import_result.segment,
        metadata=import_result.metadata,
        other_armature_modifiers=list_other_armature_mod_names(source_mesh, proxy_armature),
    )


def list_other_armature_mod_names(source_mesh, proxy_armature):
    """Small wrapper to keep import/export call sites compact."""
    return list_other_armature_modifier_names(source_mesh, proxy_armature)


def import_palette_for_active_proxy(context, active_object, binary_path, segment="CURRENT"):
    """Import a palette onto the active proxy armature."""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return import_palette_for_proxy_armature(context, proxy_armature, binary_path, segment)


def import_palette_for_selected_proxy_armatures(context, binary_path, segment="CURRENT"):
    """Import the same palette into all selected proxy armatures."""
    selected_armatures = list_selected_proxy_armatures(context)
    if not selected_armatures:
        raise ValueError("No selected proxy armatures found")

    selection_state = capture_selection_state(context)
    imported_armatures = 0
    imported_bones = 0
    failed_armatures = []

    try:
        for proxy_armature in selected_armatures:
            try:
                import_result = import_palette_for_proxy_armature(context, proxy_armature, binary_path, segment)
            except Exception as exc:
                failed_armatures.append(f"{proxy_armature.name}: {exc}")
                continue

            imported_armatures += 1
            imported_bones += import_result.imported_bones
    finally:
        restore_selection_state(context, selection_state)

    return BatchPaletteImportResult(
        binary_path=binary_path,
        selected_armatures=len(selected_armatures),
        imported_armatures=imported_armatures,
        imported_bones=imported_bones,
        failed_armatures=tuple(failed_armatures),
    )


def clear_previous_palette_for_active_proxy(active_object):
    """Clear the cached previous palette for the active proxy armature."""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    clear_previous_palette_cache(proxy_armature)
    return proxy_armature.name


def dump_debug_for_proxy_armature(context, proxy_armature, binary_path="", segment="CURRENT"):
    """Print a debug snapshot for one proxy armature."""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    snapshot = build_proxy_debug_snapshot(context, proxy_armature, binary_path=binary_path, segment=segment)
    print_debug_snapshot(snapshot)
    return DebugDumpResult(
        armature_name=proxy_armature.name,
        sampled_bones=len(snapshot.get("sampled_proxy_bones", ())),
        has_import_data=bool(snapshot.get("import_debug")),
    )


def dump_debug_for_active_proxy(context, active_object, binary_path="", segment="CURRENT"):
    """Print a debug snapshot for the active proxy armature."""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return dump_debug_for_proxy_armature(context, proxy_armature, binary_path, segment)
