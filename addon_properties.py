"""Registration of Blender properties used by the addon."""

import bpy

from .addon_constants import (
    DEFAULT_BUFFER_ROW_COUNT,
    DEFAULT_PART_ROW_COUNT,
    DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
)


REGISTERED_PROPERTY_PATHS = (
    (bpy.types.PoseBone, "bi_slot_id"),
    (bpy.types.PoseBone, "bi_export_enabled"),
    (bpy.types.PoseBone, "bi_is_proxy"),
    (bpy.types.PoseBone, "bi_bone_type"),
    (bpy.types.PoseBone, "bi_bind_matrix"),
    (bpy.types.PoseBone, "bi_bind_valid"),
    (bpy.types.Object, "bi_is_proxy_armature"),
    (bpy.types.Object, "bi_source_mesh_name"),
    (bpy.types.Object, "bi_proxy_armature_name"),
    (bpy.types.Object, "bi_part_base"),
    (bpy.types.Object, "bi_part_size"),
    (bpy.types.Object, "bi_previous_offset"),
    (bpy.types.Object, "bi_buffer_size"),
    (bpy.types.Scene, "bi_output_path"),
    (bpy.types.Scene, "bi_import_path"),
    (bpy.types.Scene, "bi_import_segment"),
    (bpy.types.Scene, "bi_write_metadata"),
)


def register_addon_properties():
    """Register all Object, PoseBone, and Scene properties used by the addon."""
    bpy.types.PoseBone.bi_slot_id = bpy.props.IntProperty(
        name="Slot Id",
        default=-1,
        min=-1,
        description="VS-T0 slot id. V1 expects the proxy bone name and vertex group name to match this slot.",
    )
    bpy.types.PoseBone.bi_export_enabled = bpy.props.BoolProperty(
        name="Export Enabled",
        default=True,
        description="Include this proxy bone in the exported VS-T0 palette.",
    )
    bpy.types.PoseBone.bi_is_proxy = bpy.props.BoolProperty(
        name="Is Proxy Bone",
        default=False,
        description="Marks this pose bone as part of the generated proxy rig.",
    )
    bpy.types.PoseBone.bi_bone_type = bpy.props.EnumProperty(
        name="Bone Type",
        items=[
            ("MAIN", "Main", "Main exported animation bone"),
            ("HELPER", "Helper", "Helper or corrective exported bone"),
            ("PHYSICS", "Physics", "Physics-driven exported bone"),
        ],
        default="MAIN",
    )
    bpy.types.PoseBone.bi_bind_matrix = bpy.props.FloatVectorProperty(
        name="Bind Matrix",
        size=16,
        default=(
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ),
        description="Captured bind matrix used when exporting the final skinning matrix.",
    )
    bpy.types.PoseBone.bi_bind_valid = bpy.props.BoolProperty(
        name="Bind Valid",
        default=False,
        description="Whether this proxy bone has a captured bind matrix.",
    )

    bpy.types.Object.bi_is_proxy_armature = bpy.props.BoolProperty(
        name="Is Proxy Armature",
        default=False,
        description="Marks this object as a generated VS-T0 proxy armature.",
    )
    bpy.types.Object.bi_source_mesh_name = bpy.props.StringProperty(
        name="Source Mesh",
        default="",
        description="Source mesh used to build this proxy armature.",
    )
    bpy.types.Object.bi_proxy_armature_name = bpy.props.StringProperty(
        name="Proxy Armature",
        default="",
        description="Generated proxy armature linked to this mesh.",
    )
    bpy.types.Object.bi_part_base = bpy.props.IntProperty(
        name="Part Base",
        default=0,
        min=0,
        description="Current-frame float4 row base for this mesh part.",
    )
    bpy.types.Object.bi_part_size = bpy.props.IntProperty(
        name="Part Size",
        default=DEFAULT_PART_ROW_COUNT,
        min=4,
        description="Current-frame float4 row count reserved for this mesh part.",
    )
    bpy.types.Object.bi_previous_offset = bpy.props.IntProperty(
        name="Previous Offset",
        default=DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
        min=0,
        description="Float4 row offset from current palette to the previous-frame palette.",
    )
    bpy.types.Object.bi_buffer_size = bpy.props.IntProperty(
        name="Buffer Size",
        default=DEFAULT_BUFFER_ROW_COUNT,
        min=1,
        description="Total exported buffer size measured in float4 rows.",
    )

    bpy.types.Scene.bi_output_path = bpy.props.StringProperty(
        name="Output Path",
        default="//vst0_palette.bin",
        subtype="FILE_PATH",
        description="Binary output path for the exported VS-T0 palette.",
    )
    bpy.types.Scene.bi_import_path = bpy.props.StringProperty(
        name="Import Path",
        default="//vst0_palette.bin",
        subtype="FILE_PATH",
        description="Binary palette path to import back onto the proxy armature.",
    )
    bpy.types.Scene.bi_import_segment = bpy.props.EnumProperty(
        name="Import Segment",
        items=[
            ("CURRENT", "Current", "Apply the current palette window"),
            ("PREVIOUS", "Previous", "Apply the previous-frame palette window"),
        ],
        default="CURRENT",
        description="Choose whether import reads the current or previous palette window.",
    )
    bpy.types.Scene.bi_write_metadata = bpy.props.BoolProperty(
        name="Write Metadata",
        default=True,
        description="Write a JSON metadata file next to the exported palette.",
    )


def unregister_addon_properties():
    """Unregister all Blender properties created by the addon."""
    for owner, attribute_name in REGISTERED_PROPERTY_PATHS:
        if hasattr(owner, attribute_name):
            delattr(owner, attribute_name)
