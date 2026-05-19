"""注册插件在 Blender 中使用的属性。"""

import bpy

from .constants import (
    DEFAULT_BUFFER_ROW_COUNT,
    DEFAULT_PART_ROW_COUNT,
    DEFAULT_PREVIOUS_FRAME_ROW_OFFSET,
)
from .core.collection_plan import CB1_OVERRIDE_INHERIT, CB1_OVERRIDE_ITEMS
from .core.transform import BUFFER_CORRECTION_ITEMS, BUFFER_CORRECTION_NONE


REGISTERED_PROPERTY_PATHS = (
    (bpy.types.PoseBone, "bi_slot_id"),
    (bpy.types.PoseBone, "bi_mesh_key"),
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
    (bpy.types.Object, "bi_base_position_path"),
    (bpy.types.Object, "bi_base_position_stride"),
    (bpy.types.Object, "bi_match_priority"),
    (bpy.types.Object, "bi_bone_enabled"),
    (bpy.types.Object, "bi_bone_source_armature"),
    (bpy.types.Object, "bi_bone_slot_map_json"),
    (bpy.types.Object, "bi_skin_contract"),
    (bpy.types.Object, "bi_morph_enabled"),
    (bpy.types.Object, "bi_morph_source_object"),
    (bpy.types.Object, "bi_vb_layout_profile"),
    (bpy.types.Object, "bi_cb1_profile"),
    (bpy.types.Collection, "bi_cb1_override"),
    (bpy.types.Scene, "bi_output_path"),
    (bpy.types.Scene, "bi_export_collection"),
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
    (bpy.types.Scene, "bi_morph_source_object"),
    (bpy.types.Scene, "bi_morph_target_draw_key"),
    (bpy.types.Scene, "bi_import_path"),
    (bpy.types.Scene, "bi_import_segment"),
    (bpy.types.Scene, "bi_write_metadata"),
)


def _draw_part_enum_items(_self, context):
    """Build the Target Draw Part dropdown from the active manifest source."""
    try:
        from .core.draw_part import build_target_draw_parts

        draw_parts = build_target_draw_parts(context)
    except Exception:
        return [("__NONE__", "No Draw Part", "Set an RX Export Collection or select draw-part objects")]
    if not draw_parts:
        return [("__NONE__", "No Draw Part", "Set an RX Export Collection or select draw-part objects")]
    return [
        (
            draw_part.draw_key,
            draw_part.source_object.name,
            f"{draw_part.hash} | indices={draw_part.match_index_count} | first={draw_part.first_index}",
        )
        for draw_part in draw_parts
    ]


def register_addon_properties():
    """注册插件需要的 Object、PoseBone 和 Scene 属性。"""
    bpy.types.PoseBone.bi_slot_id = bpy.props.IntProperty(
        name="Slot Id",
        default=-1,
        min=-1,
        description="VS-T0 slot id. V1 expects the proxy bone name and vertex group name to match this slot.",
    )
    bpy.types.PoseBone.bi_mesh_key = bpy.props.StringProperty(
        name="Mesh Key",
        default="",
        description="Mesh/part suffix parsed from names like 0__Body. Export uses it to split shared rigs into local slot groups.",
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
    bpy.types.Object.bi_base_position_path = bpy.props.StringProperty(
        name="Base Position VB",
        default="",
        subtype="FILE_PATH",
        description="Explicit base Position buffer used by morph export for this draw part.",
    )
    bpy.types.Object.bi_base_position_stride = bpy.props.IntProperty(
        name="Base Position Stride",
        default=0,
        min=0,
        description="Stride of the explicit base Position buffer. Use 16 for packed EFMI vb0 or 40 for PNTA40.",
    )
    bpy.types.Object.bi_match_priority = bpy.props.IntProperty(
        name="Match Priority",
        default=50,
        description="TextureOverride match_priority emitted for this DrawPart.",
    )
    bpy.types.Object.bi_bone_enabled = bpy.props.BoolProperty(
        name="Bone Payload",
        default=True,
        description="Export a Bone Payload for this DrawPart when a valid Bone Source and Bone Slot Map are available.",
    )
    bpy.types.Object.bi_bone_source_armature = bpy.props.PointerProperty(
        name="Bone Source",
        type=bpy.types.Object,
        description="Armature sampled for this DrawPart's Bone Payload. If unset, the linked proxy armature is used.",
    )
    bpy.types.Object.bi_bone_slot_map_json = bpy.props.StringProperty(
        name="Bone Slot Map JSON",
        default="",
        description=(
            "Optional JSON list mapping target slots to source bones. "
            "Example: [{\"slot_id\":0,\"source_bone\":\"Head\"}]. "
            "If empty, the exporter only auto-maps numeric/proxy bone names."
        ),
    )
    bpy.types.Object.bi_skin_contract = bpy.props.EnumProperty(
        name="Skin Contract",
        items=[
            ("TARGET_NUMERIC_GROUPS", "Target Numeric Groups", "Target DrawPart numeric vertex groups define the runtime slot order"),
            ("SOURCE_ARMATURE_SLOTS", "Source Armature Slots", "Source armature proxy slot metadata defines the runtime slot order"),
            ("EXPLICIT_SLOT_MAP", "Explicit Slot Map", "Bone Slot Map JSON defines the runtime slot order"),
        ],
        default="TARGET_NUMERIC_GROUPS",
        description="Defines which slot namespace is the runtime truth for this DrawPart.",
    )
    bpy.types.Object.bi_morph_enabled = bpy.props.BoolProperty(
        name="Morph Payload",
        default=False,
        description="Export a Morph Payload for this DrawPart.",
    )
    bpy.types.Object.bi_morph_source_object = bpy.props.PointerProperty(
        name="Morph Source",
        type=bpy.types.Object,
        description="Shape-key source object for this DrawPart. If unset, the DrawPart object is used.",
    )
    bpy.types.Object.bi_vb_layout_profile = bpy.props.EnumProperty(
        name="VB Layout",
        items=[
            ("AUTO", "Auto", "Infer the base Position layout from stride"),
            ("PACKED16", "Packed16", "EFMI packed Position buffer: float3 position + packed normal"),
            ("PNTA40", "PNTA40", "Explicit position/normal/tangent layout with stride 40"),
        ],
        default="AUTO",
        description="Runtime base Position layout profile used by morph INI generation.",
    )
    bpy.types.Object.bi_cb1_profile = bpy.props.EnumProperty(
        name="CB1 Profile",
        items=[
            ("INHERIT", "Inherit", "Inherit the collection CB1 profile"),
            ("NONE", "None", "No special CB1 patch"),
            ("EYELASH", "Eyelash", "Patch the eyelash/eye CB1 branch before redirecting CB1"),
        ],
        default="INHERIT",
        description="Per-DrawPart CB1 profile. Inherit uses the collection profile.",
    )
    bpy.types.Collection.bi_cb1_override = bpy.props.EnumProperty(
        name="RX CB1 Override",
        items=CB1_OVERRIDE_ITEMS,
        default=CB1_OVERRIDE_INHERIT,
        description=(
            "Collection-level special cb1 flag override used by generated RX ini snippets. "
            "Use Eyelash only for collection-backed eyelash/eye draw groups that need cb1[4].w patched."
        ),
    )

    bpy.types.Scene.bi_output_path = bpy.props.StringProperty(
        name="Output Path",
        default="//vst0_palette.bin",
        subtype="FILE_PATH",
        description="Binary output path for the exported VS-T0 palette.",
    )
    bpy.types.Scene.bi_export_collection = bpy.props.PointerProperty(
        name="RX Export Collection",
        type=bpy.types.Collection,
        description=(
            "Optional collection used as the export target source. Objects inside it resolve to their linked "
            "proxy armatures; configured proxy parts and resolved base Position buffers define the exported resources."
        ),
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
        description="Export per-channel key=1 target normals and re-encode EFMI vb0 packed TBN normals at runtime, including the tangent/sign payload used by packed-normal layouts.",
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
    bpy.types.Scene.bi_morph_source_object = bpy.props.PointerProperty(
        name="Shape Key Source",
        type=bpy.types.Object,
        description="Optional external object to export shape-key animation from. If unset, each draw part's own object is used.",
    )
    bpy.types.Scene.bi_morph_target_draw_key = bpy.props.EnumProperty(
        name="Target Draw Part",
        items=_draw_part_enum_items,
        description="Draw part/IB that receives the selected external shape-key source.",
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
