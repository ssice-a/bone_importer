"""把底层能力组织成 Blender 可直接调用的工作流。"""

import os

import bpy

from ..constants import DEFAULT_PART_ROW_COUNT
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
from .export import (
    build_palette_export_package,
    cache_current_palette_segment,
    clear_previous_palette_cache,
)
from .importer import apply_palette_segment_to_proxy_armature, resolve_palette_segment_window
from .io import (
    build_metadata_path_from_binary_path,
    load_palette_file,
    read_palette_rows_from_file,
    read_palette_metadata_from_file,
    write_palette_package_to_disk,
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
    """同步 part_id 派生布局，并返回代理骨架对应的源网格。"""
    source_mesh = find_source_mesh_for_object(proxy_armature)
    apply_part_id_layout(proxy_armature, require_configured=require_part_id)
    return source_mesh


def build_proxy_generation_result(source_mesh, proxy_armature, proxy_bone_build, configured_bone_count):
    """整理单个网格的代理骨生成结果。"""
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
    """从单个网格的顶点组生成代理骨架。"""
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
    """从当前活动网格生成单个代理骨架。"""
    return generate_proxy_rig_for_mesh(context, context.active_object)


def generate_proxy_rigs_from_selected_meshes(context):
    """为当前选中的多个网格批量生成代理骨架。"""
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
    """为指定代理骨架捕获 bind 矩阵。"""
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
    """为当前对象对应的代理骨架捕获 bind 矩阵。"""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return capture_bind_for_proxy_armature(proxy_armature)


def export_palette_for_proxy_armature(proxy_armature, output_path, write_metadata=True, base_buffer_path=""):
    """把指定代理骨架导出成 VS-T0 调色板文件。"""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    source_mesh = prepare_proxy_armature(proxy_armature, require_part_id=True)
    resolved_base_buffer_path = bpy.path.abspath(base_buffer_path) if base_buffer_path else ""
    base_buffer_rows = None
    if resolved_base_buffer_path and os.path.exists(resolved_base_buffer_path):
        base_buffer_rows = read_palette_rows_from_file(resolved_base_buffer_path)

    export_package = build_palette_export_package(
        proxy_armature,
        base_buffer_rows=base_buffer_rows,
        base_buffer_path=resolved_base_buffer_path,
    )
    binary_path, metadata_path = write_palette_package_to_disk(
        export_package,
        output_path=output_path,
        armature_name=proxy_armature.name,
        write_metadata=write_metadata,
    )
    cache_current_palette_segment(proxy_armature, export_package["current_segment"])

    metadata = export_package["metadata"]
    other_armature_modifiers = ()
    if source_mesh is not None:
        other_armature_modifiers = list_other_armature_modifier_names(source_mesh, proxy_armature)
    return PaletteExportResult(
        armature_name=proxy_armature.name,
        binary_path=binary_path,
        metadata_path=metadata_path,
        exported_bones=len(metadata.get("exported_bones", [])),
        overflow_bones=len(metadata.get("overflow_bones", [])),
        metadata=metadata,
        other_armature_modifiers=other_armature_modifiers,
    )


def export_palette_for_active_proxy(active_object, output_path, write_metadata=True, base_buffer_path=""):
    """把当前对象对应的代理骨架导出成 VS-T0 调色板文件。"""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return export_palette_for_proxy_armature(proxy_armature, output_path, write_metadata, base_buffer_path)


def export_palette_for_selected_proxy_armatures(context, output_path, write_metadata=True, base_buffer_path=""):
    """把当前选中的多个代理骨架合并导出到同一份大缓冲文件。"""
    selected_armatures = list_selected_proxy_armatures(context)
    if not selected_armatures:
        raise ValueError("No selected proxy armatures with Part Id found")

    selection_state = capture_selection_state(context)
    resolved_base_buffer_path = bpy.path.abspath(base_buffer_path) if base_buffer_path else ""
    base_buffer_rows = None
    if resolved_base_buffer_path and os.path.exists(resolved_base_buffer_path):
        base_buffer_rows = read_palette_rows_from_file(resolved_base_buffer_path)

    merged_buffer_rows = base_buffer_rows
    exported_bones = 0
    overflow_bones = 0
    failed_armatures = []
    exported_parts = []

    try:
        for proxy_armature in selected_armatures:
            try:
                prepare_proxy_armature(proxy_armature, require_part_id=True)
                export_package = build_palette_export_package(
                    proxy_armature,
                    base_buffer_rows=merged_buffer_rows,
                    base_buffer_path=resolved_base_buffer_path,
                )
            except Exception as exc:
                failed_armatures.append(f"{proxy_armature.name}: {exc}")
                continue

            merged_buffer_rows = export_package["buffer_rows"]
            cache_current_palette_segment(proxy_armature, export_package["current_segment"])

            part_metadata = export_package["metadata"]
            exported_parts.append(
                {
                    "armature_name": proxy_armature.name,
                    "part_id": int(getattr(proxy_armature, "bi_part_id", -1)),
                    "part_base": int(getattr(proxy_armature, "bi_part_base", 0)),
                    "part_size": int(getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT)),
                    "exported_bones": len(part_metadata.get("exported_bones", [])),
                    "overflow_bones": len(part_metadata.get("overflow_bones", [])),
                    "used_slots": list(part_metadata.get("used_slots", [])),
                }
            )
            exported_bones += len(part_metadata.get("exported_bones", []))
            overflow_bones += len(part_metadata.get("overflow_bones", []))
    finally:
        restore_selection_state(context, selection_state)

    if not exported_parts:
        raise ValueError("No selected proxy armatures could be exported")

    merged_metadata = {
        "format": "vs_t0_palette_batch_v1",
        "export_mode": "patch_selected_parts",
        "base_buffer_path": resolved_base_buffer_path,
        "selected_armatures": len(selected_armatures),
        "exported_armatures": len(exported_parts),
        "buffer_row_count": len(merged_buffer_rows or []),
        "parts": exported_parts,
    }
    merged_package = {
        "buffer_rows": merged_buffer_rows,
        "metadata": merged_metadata,
    }
    binary_path, metadata_path = write_palette_package_to_disk(
        merged_package,
        output_path=output_path,
        armature_name="selected_parts",
        write_metadata=write_metadata,
    )

    return BatchPaletteExportResult(
        binary_path=binary_path,
        metadata_path=metadata_path,
        selected_armatures=len(selected_armatures),
        exported_armatures=len(exported_parts),
        exported_bones=exported_bones,
        overflow_bones=overflow_bones,
        failed_armatures=tuple(failed_armatures),
        metadata=merged_metadata,
    )


def import_palette_for_proxy_armature(context, proxy_armature, binary_path, segment="CURRENT"):
    """从磁盘读取调色板，并把一个片段应用到指定代理骨架。"""
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
    """把调色板导入到当前对象对应的代理骨架。"""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return import_palette_for_proxy_armature(context, proxy_armature, binary_path, segment)


def import_palette_for_selected_proxy_armatures(context, binary_path, segment="CURRENT"):
    """把同一份调色板应用到当前选中的多个代理骨架。"""
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
    """清空当前对象对应代理骨架的上一帧缓存。"""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    clear_previous_palette_cache(proxy_armature)
    return proxy_armature.name


def dump_debug_for_proxy_armature(context, proxy_armature, binary_path="", segment="CURRENT"):
    """把当前代理骨架的调试快照打印到控制台。"""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    snapshot = build_proxy_debug_snapshot(
        context,
        proxy_armature,
        binary_path=binary_path,
        segment=segment,
    )
    print_debug_snapshot(snapshot)
    return DebugDumpResult(
        armature_name=proxy_armature.name,
        sampled_bones=len(snapshot.get("sampled_proxy_bones", ())),
        has_import_data=bool(snapshot.get("import_debug")),
    )


def dump_debug_for_active_proxy(context, active_object, binary_path="", segment="CURRENT"):
    """为当前对象对应的代理骨架打印调试快照。"""
    proxy_armature = find_proxy_armature_for_object(active_object)
    if proxy_armature is None:
        raise ValueError("No proxy armature found")
    return dump_debug_for_proxy_armature(context, proxy_armature, binary_path, segment)
