"""收集并打印代理骨架、网格和调色板矩阵链的调试信息。"""

import json
import os

import bpy
from mathutils import Vector

from ..constants import RESERVED_PALETTE_ROWS
from .context import apply_part_id_layout, find_source_mesh_for_object
from .export import list_exportable_proxy_pose_bones
from .importer import resolve_palette_segment_window
from .io import build_metadata_path_from_binary_path, load_palette_file, read_palette_metadata_from_file
from .layout import build_matrix_from_flat_values, build_matrix_from_palette_rows
from .transform import convert_matrix_from_blender_to_game, convert_matrix_from_game_to_blender


def _vector_to_list(vector):
    """把 Vector 序列化成 JSON 友好的列表。"""
    return [float(component) for component in vector]


def _matrix_to_rows(matrix):
    """把 4x4 矩阵转换成 4 行列表。"""
    return [[float(matrix[row][column]) for column in range(4)] for row in range(4)]


def _build_bounds_from_coordinates(coordinates):
    """根据坐标列表构建包围盒信息。"""
    if not coordinates:
        zero = Vector((0.0, 0.0, 0.0))
        return {
            "min": _vector_to_list(zero),
            "max": _vector_to_list(zero),
            "center": _vector_to_list(zero),
            "diagonal": 0.0,
            "count": 0,
        }

    min_corner = coordinates[0].copy()
    max_corner = coordinates[0].copy()
    for coordinate in coordinates[1:]:
        min_corner.x = min(min_corner.x, coordinate.x)
        min_corner.y = min(min_corner.y, coordinate.y)
        min_corner.z = min(min_corner.z, coordinate.z)
        max_corner.x = max(max_corner.x, coordinate.x)
        max_corner.y = max(max_corner.y, coordinate.y)
        max_corner.z = max(max_corner.z, coordinate.z)

    center = (min_corner + max_corner) * 0.5
    return {
        "min": _vector_to_list(min_corner),
        "max": _vector_to_list(max_corner),
        "center": _vector_to_list(center),
        "diagonal": float((max_corner - min_corner).length),
        "count": len(coordinates),
    }


def _build_raw_mesh_bounds(mesh_obj):
    """统计原始 mesh.data 顶点包围盒。"""
    return _build_bounds_from_coordinates([vertex.co.copy() for vertex in mesh_obj.data.vertices])


def _build_evaluated_mesh_bounds(mesh_obj):
    """统计当前可见评估网格包围盒。"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = mesh_obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_object.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        coordinates = [vertex.co.copy() for vertex in evaluated_mesh.vertices]
        return _build_bounds_from_coordinates(coordinates)
    finally:
        evaluated_object.to_mesh_clear()


def _build_modifier_summary(mesh_obj):
    """汇总网格上的 Armature Modifier。"""
    modifiers = []
    for modifier in mesh_obj.modifiers:
        if modifier.type != "ARMATURE":
            continue
        modifiers.append(
            {
                "name": modifier.name,
                "object": modifier.object.name if modifier.object else "",
                "show_viewport": bool(modifier.show_viewport),
                "show_render": bool(modifier.show_render),
                "show_in_editmode": bool(getattr(modifier, "show_in_editmode", False)),
            }
        )
    return modifiers


def _build_pose_bone_debug_entry(pose_bone):
    """收集单根代理骨的静态与姿态信息。"""
    bind_matrix = build_matrix_from_flat_values(list(getattr(pose_bone, "bi_bind_matrix", [])))
    bone = pose_bone.bone
    return {
        "name": pose_bone.name,
        "slot_id": int(getattr(pose_bone, "bi_slot_id", -1)),
        "bind_valid": bool(getattr(pose_bone, "bi_bind_valid", False)),
        "export_enabled": bool(getattr(pose_bone, "bi_export_enabled", False)),
        "head_local": _vector_to_list(bone.head_local.copy()),
        "tail_local": _vector_to_list(bone.tail_local.copy()),
        "rest_matrix": _matrix_to_rows(bone.matrix_local.copy()),
        "bind_matrix": _matrix_to_rows(bind_matrix),
        "pose_matrix": _matrix_to_rows(pose_bone.matrix.copy()),
    }


def _build_import_debug_entry(pose_bone, rows, row_start, segment_base):
    """收集单根骨从调色板到姿态矩阵的导入链。"""
    slot_id = int(getattr(pose_bone, "bi_slot_id", -1))
    absolute_row_base = segment_base + RESERVED_PALETTE_ROWS + slot_id * 3
    local_row_base = absolute_row_base - int(row_start)
    bind_matrix = build_matrix_from_flat_values(list(getattr(pose_bone, "bi_bind_matrix", [])))
    if not getattr(pose_bone, "bi_bind_valid", False):
        bind_matrix = pose_bone.bone.matrix_local.copy()

    entry = {
        "name": pose_bone.name,
        "slot_id": slot_id,
        "absolute_row_base": absolute_row_base,
        "local_row_base": local_row_base,
        "bind_matrix": _matrix_to_rows(bind_matrix),
    }
    if local_row_base < 0 or local_row_base + 2 >= len(rows):
        entry["missing_rows"] = True
        return entry

    palette_rows = rows[local_row_base:local_row_base + 3]
    game_skin = build_matrix_from_palette_rows(palette_rows)
    blender_skin = convert_matrix_from_game_to_blender(game_skin)
    entry.update(
        {
            "missing_rows": False,
            "palette_rows": [[float(value) for value in row] for row in palette_rows],
            "game_skin_matrix": _matrix_to_rows(game_skin),
            "blender_skin_matrix": _matrix_to_rows(blender_skin),
            "reconstructed_pose_matrix": _matrix_to_rows(blender_skin @ bind_matrix),
        }
    )
    return entry


def _build_export_debug_entry(pose_bone):
    """收集单根骨从姿态矩阵回写到游戏调色板的导出链。"""
    bind_matrix = build_matrix_from_flat_values(list(getattr(pose_bone, "bi_bind_matrix", [])))
    if not getattr(pose_bone, "bi_bind_valid", False):
        bind_matrix = pose_bone.bone.matrix_local.copy()

    bind_inverse = bind_matrix.inverted()
    blender_skin = pose_bone.matrix.copy() @ bind_inverse
    return {
        "name": pose_bone.name,
        "slot_id": int(getattr(pose_bone, "bi_slot_id", -1)),
        "pose_matrix": _matrix_to_rows(pose_bone.matrix.copy()),
        "bind_matrix": _matrix_to_rows(bind_matrix),
        "bind_inverse": _matrix_to_rows(bind_inverse),
        "blender_skin_matrix": _matrix_to_rows(blender_skin),
        "game_skin_matrix": _matrix_to_rows(convert_matrix_from_blender_to_game(blender_skin)),
    }


def build_proxy_debug_snapshot(context, proxy_armature, binary_path="", segment="CURRENT", sample_count=4):
    """构建当前代理骨架的调试快照。"""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    source_mesh = find_source_mesh_for_object(proxy_armature)
    if source_mesh is None:
        raise ValueError("No source mesh linked to the proxy armature")

    layout = apply_part_id_layout(proxy_armature, require_configured=False)
    proxy_bones = list_exportable_proxy_pose_bones(proxy_armature)
    sampled_bones = proxy_bones[: max(1, int(sample_count))]

    snapshot = {
        "armature": {
            "name": proxy_armature.name,
            "matrix_world": _matrix_to_rows(proxy_armature.matrix_world.copy()),
            "part_id": int(getattr(proxy_armature, "bi_part_id", -1)),
            "part_base": int(getattr(proxy_armature, "bi_part_base", 0)),
            "part_size": int(getattr(proxy_armature, "bi_part_size", 0)),
            "previous_offset": int(getattr(proxy_armature, "bi_previous_offset", 0)),
            "buffer_size": int(getattr(proxy_armature, "bi_buffer_size", 0)),
        },
        "layout": layout,
        "source_mesh": {
            "name": source_mesh.name,
            "matrix_world": _matrix_to_rows(source_mesh.matrix_world.copy()),
            "raw_bounds": _build_raw_mesh_bounds(source_mesh),
            "evaluated_bounds": _build_evaluated_mesh_bounds(source_mesh),
            "armature_modifiers": _build_modifier_summary(source_mesh),
        },
        "sampled_proxy_bones": [_build_pose_bone_debug_entry(pose_bone) for pose_bone in sampled_bones],
        "export_debug": [_build_export_debug_entry(pose_bone) for pose_bone in sampled_bones],
        "import_debug": None,
        "scene": {
            "frame_current": int(context.scene.frame_current) if context.scene else 0,
            "active_object": context.active_object.name if context.active_object else "",
            "selected_objects": [obj.name for obj in context.selected_objects],
        },
    }

    resolved_binary_path = bpy.path.abspath(binary_path) if binary_path else ""
    if resolved_binary_path and os.path.exists(resolved_binary_path):
        metadata_path = build_metadata_path_from_binary_path(resolved_binary_path)
        metadata = read_palette_metadata_from_file(metadata_path)
        palette_window = resolve_palette_segment_window(proxy_armature, metadata, segment)
        loaded_palette = load_palette_file(
            resolved_binary_path,
            metadata_path=metadata_path,
            row_start=palette_window["segment_base"],
            row_count=palette_window["part_size"],
        )
        snapshot["import_debug"] = {
            "binary_path": resolved_binary_path,
            "metadata_path": metadata_path,
            "segment": palette_window["segment"],
            "segment_base": palette_window["segment_base"],
            "row_start": loaded_palette.row_start,
            "row_count": len(loaded_palette.rows),
            "metadata": loaded_palette.metadata,
            "sampled_bones": [
                _build_import_debug_entry(
                    pose_bone,
                    loaded_palette.rows,
                    loaded_palette.row_start,
                    palette_window["segment_base"],
                )
                for pose_bone in sampled_bones
            ],
        }

    return snapshot


def print_debug_snapshot(snapshot):
    """把调试快照打印到 Blender 调试控制台。"""
    print("===== Bone Importer Debug Begin =====")
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print("===== Bone Importer Debug End =====")
