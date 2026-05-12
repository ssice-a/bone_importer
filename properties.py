"""注册插件在 Blender 中使用的属性。"""

import bpy

from .constants import (
    DEFAULT_BUFFER_ROW_COUNT,
    DEFAULT_PART_ROW_COUNT,
    DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
)
from .core.transform import BUFFER_CORRECTION_ITEMS, BUFFER_CORRECTION_NONE


REGISTERED_PROPERTY_PATHS = (
    (bpy.types.PoseBone, "bi_slot_id"),
    (bpy.types.PoseBone, "bi_export_enabled"),
    (bpy.types.PoseBone, "bi_is_proxy"),
    (bpy.types.PoseBone, "bi_bone_type"),
    (bpy.types.PoseBone, "bi_bind_matrix"),
    (bpy.types.PoseBone, "bi_bind_valid"),
    (bpy.types.Object, "bi_is_proxy_armature"),
    (bpy.types.Object, "bi_part_id"),
    (bpy.types.Object, "bi_source_mesh_name"),
    (bpy.types.Object, "bi_proxy_armature_name"),
    (bpy.types.Object, "bi_part_base"),
    (bpy.types.Object, "bi_part_size"),
    (bpy.types.Object, "bi_previous_offset"),
    (bpy.types.Object, "bi_buffer_size"),
    (bpy.types.Object, "bi_buffer_correction_mode"),
    (bpy.types.Scene, "bi_output_path"),
    (bpy.types.Scene, "bi_animation_output_dir"),
    (bpy.types.Scene, "bi_animation_clip_name"),
    (bpy.types.Scene, "bi_animation_clip_id"),
    (bpy.types.Scene, "bi_animation_frame_start"),
    (bpy.types.Scene, "bi_animation_frame_end"),
    (bpy.types.Scene, "bi_animation_frame_step"),
    (bpy.types.Scene, "bi_animation_fps"),
    (bpy.types.Scene, "bi_animation_presents_per_step"),
    (bpy.types.Scene, "bi_animation_loop_start"),
    (bpy.types.Scene, "bi_animation_loop_end"),
    (bpy.types.Scene, "bi_morph_include_normals"),
    (bpy.types.Scene, "bi_morph_include_tangents"),
    (bpy.types.Scene, "bi_morph_channel_mode"),
    (bpy.types.Scene, "bi_import_path"),
    (bpy.types.Scene, "bi_import_segment"),
    (bpy.types.Scene, "bi_write_metadata"),
)


def register_addon_properties():
    """注册插件需要的 Object、PoseBone 和 Scene 属性。"""
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
    bpy.types.Object.bi_part_id = bpy.props.IntProperty(
        name="Part Id",
        default=-1,
        min=-1,
        description="Part window id used to derive the VS-T0 buffer offset automatically.",
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
    bpy.types.Object.bi_buffer_correction_mode = bpy.props.EnumProperty(
        name="Buffer Correction",
        items=BUFFER_CORRECTION_ITEMS,
        default=BUFFER_CORRECTION_NONE,
        description="Optional extra correction used by special buffers such as eyelashes.",
    )

    bpy.types.Scene.bi_output_path = bpy.props.StringProperty(
        name="Output Path",
        default="//vst0_palette.bin",
        subtype="FILE_PATH",
        description="Binary output path for the exported VS-T0 palette.",
    )
    bpy.types.Scene.bi_animation_output_dir = bpy.props.StringProperty(
        name="Animation Dir",
        default="E:\\XXMI\\EFMI\\Mods\\RXanimin",
        subtype="DIR_PATH",
        description="Directory used to export standalone RX runtime clip files, manifests, shared timeline defaults, and the master playback buffer.",
    )
    bpy.types.Scene.bi_animation_clip_name = bpy.props.StringProperty(
        name="Clip Name",
        default="rxanimin",
        description="Logical clip name written into the exported clip manifest, shared timeline defaults, and master playback sidecars. Keep rxanimin if you want the bundled RXanimin.ini to pick it up directly.",
    )
    bpy.types.Scene.bi_animation_clip_id = bpy.props.IntProperty(
        name="Clip Id",
        default=0,
        min=0,
        description="Stable numeric clip id written into per-part static clip data and shared sidecar metadata. The shared timeline buffer itself does not carry clip identity.",
    )
    bpy.types.Scene.bi_animation_frame_start = bpy.props.IntProperty(
        name="Frame Start",
        default=1,
        description="First frame sampled into the exported runtime buffers. Set it equal to Frame End to export one frame.",
    )
    bpy.types.Scene.bi_animation_frame_end = bpy.props.IntProperty(
        name="Frame End",
        default=250,
        description="Last frame sampled into the exported runtime buffers.",
    )
    bpy.types.Scene.bi_animation_frame_step = bpy.props.IntProperty(
        name="Frame Step",
        default=1,
        min=1,
        description="Frame step used while sampling scene-evaluated TQ data.",
    )
    bpy.types.Scene.bi_animation_fps = bpy.props.FloatProperty(
        name="FPS",
        default=60.0,
        min=1.0,
        description="Clip sample rate stored inside the exported static clip metadata.",
    )
    bpy.types.Scene.bi_animation_presents_per_step = bpy.props.IntProperty(
        name="Ticks / Sample",
        default=1,
        min=1,
        description="Default runtime tick count spent inside one exported sample. This value seeds the shared timeline defaults buffer and the initial master playback buffer. Smaller values play faster.",
    )
    bpy.types.Scene.bi_animation_loop_start = bpy.props.IntProperty(
        name="Loop Start",
        default=-1,
        min=-1,
        description="Preferred loop start source frame. Use -1 to default to the first exported frame.",
    )
    bpy.types.Scene.bi_animation_loop_end = bpy.props.IntProperty(
        name="Loop End",
        default=-1,
        min=-1,
        description="Preferred loop end source frame. Use -1 to default to the last exported frame.",
    )
    bpy.types.Scene.bi_morph_include_normals = bpy.props.BoolProperty(
        name="Morph Normals",
        default=True,
        description="Export per-channel key=1 target normals and re-encode EFMI vb0 packed normals at runtime.",
    )
    bpy.types.Scene.bi_morph_include_tangents = bpy.props.BoolProperty(
        name="Morph Tangents",
        default=False,
        description="Export per-channel key=1 target tangents when the resolved base Position buffer stores explicit tangent data such as EFMI P12+N12+TA16 layouts. Disabled by default because most meshes use packed-normal Position buffers that do not need tangent targets.",
    )
    bpy.types.Scene.bi_morph_channel_mode = bpy.props.EnumProperty(
        name="Morph Channels",
        items=[
            ("ANIMATED", "Animated Channels", "Export only shape keys whose evaluated weights actually change across the sampled clip"),
            ("ALL", "All Channels", "Export every non-basis shape key channel, even if it stays static over the sampled clip"),
        ],
        default="ANIMATED",
        description="Choose whether morph export only writes animated channels or all available shape-key channels.",
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
    """卸载插件创建过的 Blender 属性。"""
    for owner, attribute_name in REGISTERED_PROPERTY_PATHS:
        if hasattr(owner, attribute_name):
            delattr(owner, attribute_name)
