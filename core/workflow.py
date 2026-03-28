"""High-level workflows used by Blender operators."""

import bpy

from ..constants import DEFAULT_PART_ROW_COUNT
from .context import (
    apply_part_id_layout,
    capture_selection_state,
    ensure_mesh_parented_to_proxy_armature,
    find_proxy_armature_for_object,
    find_source_mesh_for_object,
    list_directly_selected_proxy_armatures,
    list_selected_proxy_armatures,
    make_object_active,
    restore_selection_state,
)
from .debug import build_proxy_debug_snapshot, print_debug_snapshot
from .export import (
    build_palette_export_write_plan_for_proxy_armatures,
    cache_current_palette_segment,
    clear_previous_palette_cache,
)
from .importer import apply_palette_segment_to_proxy_armature, resolve_palette_segment_window
from .io import (
    build_metadata_path_from_binary_path,
    load_palette_file,
    read_palette_metadata_from_file,
    write_palette_row_patches_to_disk,
)
from .layout import calculate_slot_capacity_for_part_size
from .models import (
    BatchPaletteExportResult,
    BatchPaletteImportResult,
    BatchProxyRigGenerationResult,
    DebugDumpResult,
    PaletteExportResult,
    PaletteImportResult,
    ProxyBindCaptureResult,
    ProxyRigGenerationResult,
)
from .proxy import (
    build_proxy_bone_definitions,
    capture_proxy_bind_matrices,
    configure_proxy_pose_bones,
    ensure_proxy_armature_modifier,
    get_or_create_proxy_armature,
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


def generate_proxy_rig_for_mesh(context, source_mesh):
    """Generate a proxy armature for one mesh."""
    if source_mesh is None or source_mesh.type != "MESH":
        raise ValueError("Active object must be a mesh")

    proxy_bone_build = build_proxy_bone_definitions(source_mesh)
    bone_definitions = proxy_bone_build["bone_definitions"]
    if not bone_definitions:
        raise ValueError(f"No numeric vertex groups with weighted vertices were found on {source_mesh.name}")

    proxy_armature = get_or_create_proxy_armature(context, source_mesh)
    apply_part_id_layout(proxy_armature, require_configured=False)

    make_object_active(context, proxy_armature, mode="EDIT")
    rebuild_proxy_edit_bones(proxy_armature, bone_definitions)
    bpy.ops.object.mode_set(mode="POSE")

    configured_bone_count = configure_proxy_pose_bones(proxy_armature)
    capture_proxy_bind_matrices(proxy_armature)
    clear_previous_palette_cache(proxy_armature)
    ensure_proxy_armature_modifier(source_mesh, proxy_armature)
    ensure_mesh_parented_to_proxy_armature(source_mesh, proxy_armature)
    return build_proxy_generation_result(source_mesh, proxy_armature, proxy_bone_build, configured_bone_count)


def generate_proxy_rig_from_active_mesh(context):
    """Generate a proxy armature from the active mesh."""
    return generate_proxy_rig_for_mesh(context, context.active_object)


def generate_proxy_rigs_from_selected_meshes(context):
    """Generate proxy armatures for all selected meshes."""
    selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if not selected_meshes:
        raise ValueError("Select at least one mesh object")

    selection_state = capture_selection_state(context)
    generated_meshes = 0
    generated_armatures = set()
    generated_bones = 0
    skipped_mesh_names = []
    skipped_details = []

    try:
        for mesh_obj in selected_meshes:
            if len(mesh_obj.vertex_groups) == 0:
                skipped_mesh_names.append(mesh_obj.name)
                skipped_details.append(f"{mesh_obj.name}: no vertex groups")
                continue
            try:
                result = generate_proxy_rig_for_mesh(context, mesh_obj)
            except ValueError as exc:
                skipped_mesh_names.append(mesh_obj.name)
                skipped_details.append(f"{mesh_obj.name}: {exc}")
                continue

            generated_meshes += 1
            generated_armatures.add(result.armature_name)
            generated_bones += result.configured_bones
    finally:
        restore_selection_state(context, selection_state)

    if generated_meshes == 0:
        raise ValueError("No selected mesh produced proxy bones")

    return BatchProxyRigGenerationResult(
        generated_meshes=generated_meshes,
        generated_armatures=len(generated_armatures),
        generated_bones=generated_bones,
        skipped_meshes=tuple(skipped_mesh_names),
        skipped_details=tuple(skipped_details),
    )


def capture_bind_for_proxy_armature(proxy_armature):
    """Capture bind matrices for one proxy armature."""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    source_mesh = prepare_proxy_armature(proxy_armature, require_part_id=False)
    captured_bone_count = capture_proxy_bind_matrices(proxy_armature)
    clear_previous_palette_cache(proxy_armature)

    other_armature_modifiers = ()
    if source_mesh is not None:
        other_armature_modifiers = list_other_armature_modifier_names(source_mesh, proxy_armature)
    return ProxyBindCaptureResult(
        armature_name=proxy_armature.name,
        captured_bones=captured_bone_count,
        other_armature_modifiers=other_armature_modifiers,
    )


def capture_bind_for_active_proxy(active_object):
    """Capture bind matrices for the active proxy armature."""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return capture_bind_for_proxy_armature(proxy_armature)


def build_export_target_proxy_armatures(context):
    """Resolve which proxy armatures should be exported."""
    directly_selected_armatures = list_directly_selected_proxy_armatures(context)
    if len(directly_selected_armatures) > 1:
        return directly_selected_armatures

    active_proxy_armature = find_proxy_armature_for_object(context.active_object)
    if active_proxy_armature is not None:
        return (active_proxy_armature,)

    selected_armatures = list_selected_proxy_armatures(context)
    if selected_armatures:
        return (selected_armatures[0],)

    raise ValueError("No selected proxy armatures with Part Id found")


def export_palette_for_proxy_armatures(context, proxy_armatures, output_path, write_metadata=True):
    """Export one or more proxy armatures into a single buffer file."""
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
    """Export the current target proxy armature set."""
    return export_palette_for_proxy_armatures(
        context,
        build_export_target_proxy_armatures(context),
        output_path,
        write_metadata,
    )


def export_palette_for_proxy_armature(proxy_armature, output_path, write_metadata=True):
    """Compatibility wrapper for exporting one proxy armature."""
    return export_palette_for_proxy_armatures(bpy.context, (proxy_armature,), output_path, write_metadata)


def export_palette_for_active_proxy(active_object, output_path, write_metadata=True):
    """Compatibility wrapper for exporting the active proxy armature."""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return export_palette_for_proxy_armature(proxy_armature, output_path, write_metadata)


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
        other_armature_modifiers=list_other_armature_modifier_names(source_mesh, proxy_armature),
    )


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
        raise ValueError("No selected proxy armatures with Part Id found")

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
