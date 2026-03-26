import bpy

from ..constants import DEFAULT_PART_SIZE
from .context import activate_object, proxy_armature_for_object, source_mesh_for_object, sync_layout_settings
from .export import build_vst0_export_package, clear_cached_previous_palette, store_previous_segment
from .importer import apply_palette_rows_to_armature
from .io import read_palette_file, write_palette_package
from .layout import max_slot_count_for_part_size
from .models import BindCaptureResult, PaletteExportResult, ProxyRigBuildResult
from .proxy import (
    build_proxy_bone_specs,
    capture_bind_matrices,
    configure_proxy_pose_bones,
    create_or_reuse_proxy_armature,
    ensure_proxy_armature_modifier,
    populate_proxy_armature_edit_bones,
)


def generate_proxy_rig(context):
    mesh_obj = context.active_object
    spec_package = build_proxy_bone_specs(mesh_obj)
    specs = spec_package["specs"]
    if not specs:
        raise ValueError("No numeric vertex groups with weighted vertices were found")

    armature_obj = create_or_reuse_proxy_armature(context, mesh_obj)
    sync_layout_settings(mesh_obj, armature_obj)

    activate_object(context, armature_obj, mode="EDIT")
    populate_proxy_armature_edit_bones(armature_obj, specs)
    bpy.ops.object.mode_set(mode="POSE")

    configured = configure_proxy_pose_bones(armature_obj)
    capture_bind_matrices(armature_obj)
    clear_cached_previous_palette(armature_obj)
    ensure_proxy_armature_modifier(mesh_obj, armature_obj)

    max_slot = max((spec["slot_id"] for spec in specs), default=-1)
    slot_capacity = max_slot_count_for_part_size(int(getattr(armature_obj, "bi_part_size", DEFAULT_PART_SIZE)))
    return ProxyRigBuildResult(
        source_mesh_name=mesh_obj.name,
        armature_name=armature_obj.name,
        configured_bones=configured,
        max_slot=max_slot,
        slot_capacity=slot_capacity,
        skipped_groups=tuple(spec_package["skipped_groups"]),
    )


def capture_active_bind(active_object):
    armature_obj = proxy_armature_for_object(active_object)
    if armature_obj is None:
        raise ValueError("No proxy armature found")

    mesh_obj = source_mesh_for_object(active_object)
    if mesh_obj is not None and active_object == mesh_obj:
        sync_layout_settings(mesh_obj, armature_obj)

    captured = capture_bind_matrices(armature_obj)
    clear_cached_previous_palette(armature_obj)
    return BindCaptureResult(armature_name=armature_obj.name, captured_bones=captured)


def export_active_palette(active_object, output_path, write_metadata=True):
    armature_obj = proxy_armature_for_object(active_object)
    if armature_obj is None:
        raise ValueError("No proxy armature found")

    mesh_obj = source_mesh_for_object(active_object)
    if mesh_obj is not None and active_object == mesh_obj:
        sync_layout_settings(mesh_obj, armature_obj)

    package = build_vst0_export_package(armature_obj)
    binary_path, metadata_path = write_palette_package(
        package,
        output_path=output_path,
        armature_name=armature_obj.name,
        write_metadata=write_metadata,
    )
    store_previous_segment(armature_obj, package["current_segment"])

    metadata = package["metadata"]
    return PaletteExportResult(
        armature_name=armature_obj.name,
        binary_path=binary_path,
        metadata_path=metadata_path,
        exported_bones=len(metadata.get("exported_bones", [])),
        overflow_bones=len(metadata.get("overflow_bones", [])),
        metadata=metadata,
    )


def import_active_palette(context, active_object, binary_path, segment="CURRENT"):
    armature_obj = proxy_armature_for_object(active_object)
    if armature_obj is None:
        raise ValueError("No proxy armature found")

    mesh_obj = source_mesh_for_object(active_object)
    if mesh_obj is not None and active_object == mesh_obj:
        sync_layout_settings(mesh_obj, armature_obj)

    palette_file = read_palette_file(binary_path)
    return apply_palette_rows_to_armature(
        context,
        armature_obj,
        rows=palette_file.rows,
        binary_path=palette_file.binary_path,
        metadata=palette_file.metadata,
        segment=segment,
    )


def clear_active_previous_cache(active_object):
    armature_obj = proxy_armature_for_object(active_object)
    if armature_obj is None:
        raise ValueError("No proxy armature found")
    clear_cached_previous_palette(armature_obj)
    return armature_obj.name
