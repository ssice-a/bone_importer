"""代理骨架生成与 bind 捕获相关的辅助函数。"""

import bpy
from mathutils import Vector

from ..constants import (
    DEFAULT_BUFFER_ROW_COUNT,
    DEFAULT_PART_ROW_COUNT,
    DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
    DEFAULT_PROXY_BONE_DIRECTION,
    FLOAT_COMPARISON_EPSILON,
)
from .layout import flatten_matrix_to_list


def parse_slot_id_from_name(name):
    """从顶点组名或代理骨名中解析槽位编号。"""
    return int(str(name).strip())


def build_proxy_armature_name(mesh_obj):
    """根据网格对象生成代理骨架名称。"""
    return f"{mesh_obj.name}_VST0Proxy"


def capture_proxy_bind_matrices(armature_obj):
    """记录每根代理骨当前的 bind/rest 矩阵。"""
    captured_bone_count = 0
    for pose_bone in armature_obj.pose.bones:
        if not getattr(pose_bone, "bi_is_proxy", False):
            continue
        pose_bone.bi_bind_matrix = flatten_matrix_to_list(pose_bone.bone.matrix_local.copy())
        pose_bone.bi_bind_valid = True
        captured_bone_count += 1
    return captured_bone_count


def normalize_with_fallback(vector, fallback_vector):
    """优先归一化主方向；失败时回退到备用方向。"""
    if vector.length > FLOAT_COMPARISON_EPSILON:
        return vector.normalized()
    if fallback_vector.length > FLOAT_COMPARISON_EPSILON:
        return fallback_vector.normalized()
    return DEFAULT_PROXY_BONE_DIRECTION.copy()


def calculate_aabb_center_and_diagonal(min_corner, max_corner):
    """计算包围盒中心点和对角线长度。"""
    center = (min_corner + max_corner) * 0.5
    diagonal_length = (max_corner - min_corner).length
    return center, diagonal_length


def build_visible_vertex_samples(mesh_obj):
    """采样当前可见网格的局部顶点数据，包含坐标与顶点组权重。"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = mesh_obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_object.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        vertex_samples = []
        for vertex in evaluated_mesh.vertices:
            vertex_samples.append(
                {
                    "co": vertex.co.copy(),
                    "groups": tuple(
                        (assignment.group, float(assignment.weight))
                        for assignment in vertex.groups
                        if float(assignment.weight) > 0.0
                    ),
                }
            )
        return vertex_samples
    finally:
        evaluated_object.to_mesh_clear()


def calculate_mesh_local_bounds(vertex_samples):
    """计算当前可见网格在局部空间中的包围盒、中点和对角线长度。"""
    if not vertex_samples:
        zero_vector = Vector((0.0, 0.0, 0.0))
        return zero_vector, zero_vector, 0.0

    min_corner = vertex_samples[0]["co"].copy()
    max_corner = vertex_samples[0]["co"].copy()
    for vertex_sample in vertex_samples[1:]:
        coordinate = vertex_sample["co"]
        min_corner.x = min(min_corner.x, coordinate.x)
        min_corner.y = min(min_corner.y, coordinate.y)
        min_corner.z = min(min_corner.z, coordinate.z)
        max_corner.x = max(max_corner.x, coordinate.x)
        max_corner.y = max(max_corner.y, coordinate.y)
        max_corner.z = max(max_corner.z, coordinate.z)
    center, diagonal_length = calculate_aabb_center_and_diagonal(min_corner, max_corner)
    return min_corner, center, diagonal_length


def collect_vertex_group_statistics(mesh_obj, vertex_samples):
    """统计数字顶点组在当前可见网格上的加权质心、包围盒和采样信息。"""
    group_statistics = {}
    for vertex_group in mesh_obj.vertex_groups:
        try:
            slot_id = parse_slot_id_from_name(vertex_group.name)
        except ValueError:
            continue
        group_statistics[vertex_group.index] = {
            "group": vertex_group,
            "slot_id": slot_id,
            "weight_sum": 0.0,
            "weighted_sum": Vector((0.0, 0.0, 0.0)),
            "min_corner": None,
            "max_corner": None,
            "sample_count": 0,
        }

    for vertex_sample in vertex_samples:
        coordinate = vertex_sample["co"]
        for group_index, weight in vertex_sample["groups"]:
            statistics = group_statistics.get(group_index)
            if statistics is None:
                continue
            statistics["weight_sum"] += weight
            statistics["weighted_sum"] += coordinate * weight
            if statistics["min_corner"] is None:
                statistics["min_corner"] = coordinate.copy()
                statistics["max_corner"] = coordinate.copy()
            else:
                statistics["min_corner"].x = min(statistics["min_corner"].x, coordinate.x)
                statistics["min_corner"].y = min(statistics["min_corner"].y, coordinate.y)
                statistics["min_corner"].z = min(statistics["min_corner"].z, coordinate.z)
                statistics["max_corner"].x = max(statistics["max_corner"].x, coordinate.x)
                statistics["max_corner"].y = max(statistics["max_corner"].y, coordinate.y)
                statistics["max_corner"].z = max(statistics["max_corner"].z, coordinate.z)
            statistics["sample_count"] += 1
    return group_statistics


def build_proxy_bone_definition(group_statistics, object_diagonal_length):
    """把单个顶点组的统计结果转换成一根代理骨定义。"""
    if (
        group_statistics["weight_sum"] <= FLOAT_COMPARISON_EPSILON
        or group_statistics["min_corner"] is None
        or group_statistics["max_corner"] is None
    ):
        return None

    centroid = group_statistics["weighted_sum"] / group_statistics["weight_sum"]
    _box_center, group_diagonal_length = calculate_aabb_center_and_diagonal(
        group_statistics["min_corner"],
        group_statistics["max_corner"],
    )
    bone_length = max(min(0.08 * group_diagonal_length, 0.03 * object_diagonal_length), 0.005 * object_diagonal_length)
    # Use the weighted centroid directly so ring-shaped joint weights land in
    # the middle of their coverage instead of snapping to the nearest surface vertex.
    head_position = centroid
    tail_position = head_position + DEFAULT_PROXY_BONE_DIRECTION * bone_length
    return {
        "name": group_statistics["group"].name,
        "slot_id": group_statistics["slot_id"],
        "head": head_position,
        "tail": tail_position,
        "sample_count": group_statistics["sample_count"],
        "weight_sum": group_statistics["weight_sum"],
    }


def build_proxy_bone_definitions(mesh_obj):
    """根据数字顶点组生成代理骨摆放数据。"""
    vertex_samples = build_visible_vertex_samples(mesh_obj)
    _object_min_corner, object_center, object_diagonal_length = calculate_mesh_local_bounds(vertex_samples)
    object_diagonal_length = max(object_diagonal_length, 1e-5)

    group_statistics_by_index = collect_vertex_group_statistics(mesh_obj, vertex_samples)
    proxy_bone_definitions = []
    skipped_group_names = []

    for group_statistics in group_statistics_by_index.values():
        proxy_bone_definition = build_proxy_bone_definition(
            group_statistics,
            object_diagonal_length,
        )
        if proxy_bone_definition is None:
            skipped_group_names.append(group_statistics["group"].name)
            continue
        proxy_bone_definitions.append(proxy_bone_definition)

    proxy_bone_definitions.sort(key=lambda definition: (definition["slot_id"], definition["name"]))
    return {
        "bone_definitions": proxy_bone_definitions,
        "skipped_group_names": skipped_group_names,
        "object_center": object_center,
        "object_diagonal_length": object_diagonal_length,
    }


def get_or_create_proxy_armature(context, mesh_obj):
    """获取网格对应的代理骨架；若不存在则创建。"""
    proxy_armature_name = build_proxy_armature_name(mesh_obj)
    proxy_armature = bpy.data.objects.get(proxy_armature_name)
    if proxy_armature and proxy_armature.type != "ARMATURE":
        raise ValueError(f"Object named {proxy_armature_name} exists but is not an armature")

    if proxy_armature is None:
        armature_data = bpy.data.armatures.new(proxy_armature_name)
        proxy_armature = bpy.data.objects.new(proxy_armature_name, armature_data)
        target_collection = mesh_obj.users_collection[0] if mesh_obj.users_collection else context.collection
        target_collection.objects.link(proxy_armature)

    proxy_armature.matrix_world = mesh_obj.matrix_world.copy()
    proxy_armature.show_in_front = True
    proxy_armature.data.display_type = "STICK"
    proxy_armature.bi_is_proxy_armature = True
    proxy_armature.bi_source_mesh_name = mesh_obj.name
    proxy_armature.bi_part_id = int(getattr(proxy_armature, "bi_part_id", -1))
    proxy_armature.bi_part_base = int(getattr(proxy_armature, "bi_part_base", 0))
    proxy_armature.bi_part_size = int(getattr(proxy_armature, "bi_part_size", DEFAULT_PART_ROW_COUNT))
    proxy_armature.bi_previous_offset = int(
        getattr(proxy_armature, "bi_previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET)
    )
    proxy_armature.bi_buffer_size = int(getattr(proxy_armature, "bi_buffer_size", DEFAULT_BUFFER_ROW_COUNT))
    mesh_obj.bi_proxy_armature_name = proxy_armature.name
    return proxy_armature


def rebuild_proxy_edit_bones(proxy_armature, bone_definitions):
    """重建编辑骨骼，直接沿用当前可见网格所在的 Blender 局部空间。"""
    edit_bones = proxy_armature.data.edit_bones
    while edit_bones:
        edit_bones.remove(edit_bones[0])

    for bone_definition in bone_definitions:
        edit_bone = edit_bones.new(bone_definition["name"])
        edit_bone.head = bone_definition["head"]
        edit_bone.tail = bone_definition["tail"]
        edit_bone.roll = 0.0
        edit_bone.parent = None
        edit_bone.use_connect = False
        edit_bone.use_deform = True


def configure_proxy_pose_bones(proxy_armature):
    """给生成出来的代理 pose bone 写入导出相关属性。"""
    configured_bone_count = 0
    for pose_bone in proxy_armature.pose.bones:
        try:
            slot_id = parse_slot_id_from_name(pose_bone.name)
        except ValueError:
            continue
        pose_bone.bi_slot_id = slot_id
        pose_bone.bi_export_enabled = True
        pose_bone.bi_is_proxy = True
        pose_bone.bi_bone_type = "MAIN"
        pose_bone.bi_bind_matrix = flatten_matrix_to_list(pose_bone.bone.matrix_local.copy())
        pose_bone.bi_bind_valid = True
        configured_bone_count += 1
    return configured_bone_count


def ensure_proxy_armature_modifier(mesh_obj, proxy_armature):
    """确保源网格已经挂上指向代理骨架的 Armature 修改器。"""
    armature_modifier = None
    for modifier in mesh_obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object == proxy_armature:
            armature_modifier = modifier
            break
    if armature_modifier is None:
        armature_modifier = mesh_obj.modifiers.new(name="VS-T0 Proxy Armature", type="ARMATURE")
    armature_modifier.object = proxy_armature
    armature_modifier.use_vertex_groups = True
    armature_modifier.show_in_editmode = True
    return armature_modifier


def list_other_armature_modifier_names(mesh_obj, proxy_armature=None):
    """列出源网格上除代理骨架以外的 Armature 修改器对象名。"""
    modifier_names = []
    for modifier in mesh_obj.modifiers:
        if modifier.type != "ARMATURE":
            continue
        if proxy_armature is not None and modifier.object == proxy_armature:
            continue
        modifier_names.append(modifier.object.name if modifier.object else modifier.name)
    return tuple(modifier_names)
