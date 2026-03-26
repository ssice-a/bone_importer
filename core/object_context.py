"""Helpers for resolving the active mesh/proxy pair and syncing layout settings."""

import bpy

from ..addon_constants import (
    DEFAULT_BUFFER_ROW_COUNT,
    DEFAULT_PART_ROW_COUNT,
    DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
)


def find_proxy_armature_for_object(obj):
    """Return the linked proxy armature for a mesh, or the armature itself when already selected."""
    if not obj:
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
    """Return the source mesh for the selected mesh or generated proxy armature."""
    if not obj:
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


def find_layout_settings_owner(obj):
    """Return the object that should expose part layout settings in the UI."""
    if not obj:
        return None
    if obj.type == "MESH":
        return obj
    if obj.type == "ARMATURE" and getattr(obj, "bi_is_proxy_armature", False):
        return obj
    return None


def copy_layout_settings(source_obj, target_obj):
    """Copy palette layout settings from one Blender object to another."""
    for attribute_name, default_value in (
        ("bi_part_base", 0),
        ("bi_part_size", DEFAULT_PART_ROW_COUNT),
        ("bi_previous_offset", DEFAULT_PREVIOUS_FRAME_ROW_OFFSET),
        ("bi_buffer_size", DEFAULT_BUFFER_ROW_COUNT),
    ):
        setattr(target_obj, attribute_name, int(getattr(source_obj, attribute_name, default_value)))


def make_object_active(context, obj, mode=None):
    """Select an object, make it active, and optionally switch it into a target mode."""
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj
    if mode:
        bpy.ops.object.mode_set(mode=mode)
