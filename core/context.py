"""处理对象查找、部位布局和选择状态。"""

import bpy

from ..constants import (
    DEFAULT_BUFFER_ROW_COUNT,
    DEFAULT_PART_ROW_COUNT,
    DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
    PART_ROW_STRIDE,
)


def find_proxy_armature_for_object(obj):
    """返回对象对应的代理骨架。"""
    if obj is None:
        return None
    if obj.type == "ARMATURE" and getattr(obj, "bi_is_proxy_armature", False):
        return obj
    if obj.type != "MESH":
        return None

    proxy_armature_name = getattr(obj, "bi_proxy_armature_name", "").strip()
    if not proxy_armature_name:
        return None

    proxy_armature = bpy.data.objects.get(proxy_armature_name)
    if proxy_armature and proxy_armature.type == "ARMATURE":
        return proxy_armature
    return None


def find_source_mesh_for_object(obj):
    """返回对象对应的源网格。"""
    if obj is None:
        return None
    if obj.type == "MESH":
        return obj
    if obj.type != "ARMATURE" or not getattr(obj, "bi_is_proxy_armature", False):
        return None

    source_mesh_name = getattr(obj, "bi_source_mesh_name", "").strip()
    if not source_mesh_name:
        return None

    source_mesh = bpy.data.objects.get(source_mesh_name)
    if source_mesh and source_mesh.type == "MESH":
        return source_mesh
    return None


def build_part_layout_from_id(part_id):
    """根据部位编号推导固定布局。"""
    normalized_part_id = int(part_id)
    if normalized_part_id < 0:
        raise ValueError("Part Id must be configured before import or export")

    part_base = normalized_part_id * PART_ROW_STRIDE
    return {
        "part_id": normalized_part_id,
        "part_base": part_base,
        "part_size": DEFAULT_PART_ROW_COUNT,
        "previous_offset": DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
        "previous_base": part_base + DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
        "buffer_size": DEFAULT_BUFFER_ROW_COUNT,
    }


def apply_part_id_layout(proxy_armature, require_configured=True):
    """把 part_id 推导出的布局写回代理骨架属性。"""
    if proxy_armature is None:
        raise ValueError("No proxy armature found")

    part_id = int(getattr(proxy_armature, "bi_part_id", -1))
    if part_id < 0:
        if require_configured:
            raise ValueError(f"Proxy armature {proxy_armature.name} has no Part Id")
        proxy_armature.bi_part_base = 0
        proxy_armature.bi_part_size = DEFAULT_PART_ROW_COUNT
        proxy_armature.bi_previous_offset = DEFAULT_PREVIOUS_FRAME_ROW_OFFSET
        proxy_armature.bi_buffer_size = DEFAULT_BUFFER_ROW_COUNT
        return {
            "part_id": -1,
            "part_base": 0,
            "part_size": DEFAULT_PART_ROW_COUNT,
            "previous_offset": DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
            "previous_base": DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
            "buffer_size": DEFAULT_BUFFER_ROW_COUNT,
        }

    layout = build_part_layout_from_id(part_id)
    proxy_armature.bi_part_base = layout["part_base"]
    proxy_armature.bi_part_size = layout["part_size"]
    proxy_armature.bi_previous_offset = layout["previous_offset"]
    proxy_armature.bi_buffer_size = layout["buffer_size"]
    return layout


def list_selected_proxy_armatures(context):
    """列出当前选择集中所有已配置 part_id 的代理骨架。"""
    selected_armatures = {}
    for obj in context.selected_objects:
        proxy_armature = find_proxy_armature_for_object(obj)
        if proxy_armature is None:
            continue
        if int(getattr(proxy_armature, "bi_part_id", -1)) < 0:
            continue
        selected_armatures[proxy_armature.name_full] = proxy_armature
    return tuple(sorted(selected_armatures.values(), key=lambda armature: (armature.bi_part_id, armature.name)))


def make_object_active(context, obj, mode=None):
    """选中对象并设为活动对象；必要时切换模式。"""
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj
    if mode:
        bpy.ops.object.mode_set(mode=mode)


def capture_selection_state(context):
    """记录当前选择集和活动对象，便于批量流程结束后恢复。"""
    active_object_name = context.active_object.name if context.active_object else ""
    selected_object_names = tuple(obj.name for obj in context.selected_objects)
    return {
        "active_object_name": active_object_name,
        "selected_object_names": selected_object_names,
    }


def restore_selection_state(context, selection_state):
    """恢复批量流程执行前的选择集和活动对象。"""
    if not selection_state:
        return

    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.select_all(action="DESELECT")
    for object_name in selection_state.get("selected_object_names", ()):
        obj = bpy.data.objects.get(object_name)
        if obj is not None:
            obj.select_set(True)

    active_object_name = selection_state.get("active_object_name", "")
    active_object = bpy.data.objects.get(active_object_name) if active_object_name else None
    if active_object is not None:
        context.view_layer.objects.active = active_object


def parent_mesh_to_proxy_armature_keep_world(source_mesh_obj, proxy_armature):
    """把源网格设为代理骨架的子对象，并保持世界变换不变。"""
    if source_mesh_obj is None or proxy_armature is None:
        return
    if source_mesh_obj.parent == proxy_armature:
        return

    saved_world_matrix = source_mesh_obj.matrix_world.copy()
    source_mesh_obj.parent = proxy_armature
    source_mesh_obj.parent_type = "OBJECT"
    source_mesh_obj.matrix_parent_inverse = proxy_armature.matrix_world.inverted()
    source_mesh_obj.matrix_world = saved_world_matrix


def ensure_mesh_parented_to_proxy_armature(source_mesh_obj, proxy_armature):
    """确保源网格直接挂在代理骨架下。"""
    if source_mesh_obj is None or proxy_armature is None:
        return None

    parent_mesh_to_proxy_armature_keep_world(source_mesh_obj, proxy_armature)
    return proxy_armature
