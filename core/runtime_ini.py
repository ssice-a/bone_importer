"""Manifest-driven RX runtime INI and HLSL writers."""

from __future__ import annotations

import os

from .animation_export import normalize_clip_name, sanitize_export_name
from .coordinate_contract import hlsl_coordinate_contract
from .draw_part import DEFAULT_MATCH_PRIORITY
from .manifest import load_export_manifest


# XXMI rejects copying a compute-written RWStructuredBuffer into a fresh vertex
# Buffer (d3d11_log reports 0x80070057). Use the proven TheHerta-style path:
# copy an immutable base VB into a compute UAV register, write morph results
# into that register, then ref the draw's live vb0 resource to the UAV result.
ENABLE_RUNTIME_MORPH_REF_BINDING = True


def _line(lines: list[str], value: str = ""):
    lines.append(value)


def _basename(path: str) -> str:
    return os.path.basename(str(path or ""))


def _ini_filename(path: str, output_directory: str = "") -> str:
    raw_path = str(path or "")
    if not raw_path:
        return ""
    absolute_path = os.path.abspath(raw_path)
    if output_directory:
        absolute_root = os.path.abspath(output_directory)
        try:
            relative_path = os.path.relpath(absolute_path, absolute_root)
        except ValueError:
            relative_path = ""
        if relative_path and not relative_path.startswith(".."):
            return relative_path.replace("/", "\\")
    return raw_path.replace("/", "\\")


def _resource_key(draw_key: str) -> str:
    return sanitize_export_name(draw_key, "draw_part")


def _geometry_resource_suffix(record: dict) -> str:
    return sanitize_export_name(str(record.get("resource_suffix", "") or ""), "geometry")


def resolve_runtime_ini_path(output_directory: str, clip_name: str) -> str:
    safe_clip_name = sanitize_export_name(normalize_clip_name(clip_name), "rxanimin")
    return os.path.join(os.path.abspath(output_directory or "."), f"{safe_clip_name}.ini")


def _clip_default_ticks_per_sample(manifest: dict, clip_name: str) -> int:
    clip = manifest.get("clips", {}).get(normalize_clip_name(clip_name), {})
    return max(int(clip.get("default_ticks_per_sample", 1) or 1), 1)


def _append_constants(lines: list[str], default_ticks_per_sample: int = 1):
    speed = max(int(default_ticks_per_sample), 1)
    _line(lines, "[Constants]")
    _line(lines, "global persist $rx_anim_play = 1")
    _line(lines, "global persist $rx_anim_control_token = 0")
    _line(lines, "global persist $rx_anim_control_value = 0")
    _line(lines, f"global persist $rx_anim_speed = {speed}")
    _line(lines, f"global persist $rx_anim_speed_default = {speed}")
    _line(lines, "global $rx_anim_seek_active = 0")
    _line(lines, "global $rx_anim_seek_norm = 0.0")
    _line(lines)
    _line(lines, "global persist $rx_ui_open = 0")
    _line(lines, "global persist $rx_ui_tab = 0")
    _line(lines, "global persist $rx_ui_x = 0.05")
    _line(lines, "global persist $rx_ui_y = 0.12")
    _line(lines)
    _line(lines, "global $rx_ui_hold = 0")
    _line(lines, "global $rx_ui_hover = 0")
    _line(lines, "global $rx_ui_drag = 0")
    _line(lines, "global $rx_ui_drag_dx = 0.0")
    _line(lines, "global $rx_ui_drag_dy = 0.0")
    _line(lines, "global $rx_ui_seek_hold = 0")
    _line(lines, "global $rx_ui_cursor_x = 0.0")
    _line(lines, "global $rx_ui_cursor_y = 0.0")
    _line(lines)
    _line(lines, "[Present]")
    _line(lines, f"if $rx_anim_speed_default != {speed}")
    _line(lines, f"    $rx_anim_speed = {speed}")
    _line(lines, f"    $rx_anim_speed_default = {speed}")
    _line(lines, "endif")
    _line(lines, "x = $rx_anim_play")
    _line(lines, "y = $rx_anim_control_token")
    _line(lines, "z = $rx_anim_control_value")
    _line(lines, "w = $rx_anim_seek_active")
    _line(lines, "x1 = $rx_anim_speed")
    _line(lines, "y1 = $rx_anim_seek_norm")
    _line(lines, "run = CustomShader_UpdateMasterPlayback")
    _line(lines, "run = CommandListRXUIPresent")
    _line(lines)


def _append_global_resources(lines: list[str], manifest: dict, clip_name: str, output_directory: str):
    clip = manifest.get("clips", {}).get(normalize_clip_name(clip_name), {})
    timeline_path = clip.get("timeline_static", "") or f"{sanitize_export_name(clip_name, 'rxanimin')}_timeline_static.buf"
    master_path = clip.get("master_playback", "") or f"{sanitize_export_name(clip_name, 'rxanimin')}_master_playback.buf"

    _line(lines, "[ResourceTimelineStatic]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(timeline_path, output_directory)}")
    _line(lines)
    _line(lines, "[ResourceMasterPlayback]")
    _line(lines, "type = RWStructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(master_path, output_directory)}")
    _line(lines)
    _line(lines, "[ResourceMasterPlayback_SRV]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(master_path, output_directory)}")
    _line(lines)
    _line(lines, "[ResourceCB1Flag_Eyelash]")
    _line(lines, "type = Buffer")
    _line(lines, "format = R32_FLOAT")
    _line(lines, "; cb1[4].w bitfield value used by eyelash/eye VS branches")
    _line(lines, "data = 33.0")
    _line(lines)
    _line(lines, "[ResourceDumpedCB1_UAV]")
    _line(lines, "type = RWStructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, "array = 4096")
    _line(lines)
    _line(lines, "[ResourceDumpedCB1_SRV]")
    _line(lines, "type = Buffer")
    _line(lines, "stride = 16")
    _line(lines, "array = 4096")
    _line(lines)
    _line(lines, "[CustomShader_ExtractCB1]")
    _line(lines, "vs = hlsl\\extract_cb1_vs.hlsl")
    _line(lines, "ps = hlsl\\extract_cb1_ps.hlsl")
    _line(lines, "ps-u7 = ResourceDumpedCB1_UAV")
    _line(lines, "depth_enable = false")
    _line(lines, "blend = ADD SRC_ALPHA INV_SRC_ALPHA")
    _line(lines, "cull = none")
    _line(lines, "topology = point_list")
    _line(lines, "draw = 4096, 0")
    _line(lines, "ps-u7 = null")
    _line(lines, "ResourceDumpedCB1_SRV = copy ResourceDumpedCB1_UAV")
    _line(lines)
    _line(lines, "[CustomShader_UpdateMasterPlayback]")
    _line(lines, "cs = hlsl\\update_master_playback_cs.hlsl")
    _line(lines, "cs-u0 = ResourceMasterPlayback")
    _line(lines, "dispatch = 1, 1, 1")
    _line(lines, "cs-u0 = null")
    _line(lines, "ResourceMasterPlayback_SRV = copy ResourceMasterPlayback")
    _line(lines)
    _line(lines, "[CustomShader_UpdateBonePaletteTQ]")
    _line(lines, "cs = hlsl\\update_bone_palette_tq_cs.hlsl")
    _line(lines, "cs-u1 = ResourceMasterPlayback")
    # Over-dispatching is intentional: each draw part is capped to 256 bone slots,
    # and the shader exits once dispatch_id.x reaches the payload bone count.
    _line(lines, "dispatch = 256, 1, 1")
    _line(lines, "cs-t0 = null")
    _line(lines, "cs-t1 = null")
    _line(lines, "cs-t2 = null")
    _line(lines, "cs-u0 = null")
    _line(lines, "cs-u1 = null")
    _line(lines)
    _line(lines, "[CustomShader_RedirectCB1LocalPalette]")
    _line(lines, "cs = hlsl\\redirect_cb1_local_palette_cs.hlsl")
    _line(lines, "dispatch = 4, 1, 1")
    _line(lines, "cs-u0 = null")
    _line(lines, "cs-t0 = null")
    _line(lines, "cs-t2 = null")
    _line(lines, "cs-t3 = null")
    _line(lines)
    if ENABLE_RUNTIME_MORPH_REF_BINDING:
        _line(lines, "[CustomShader_ApplyMorph]")
        _line(lines, "cs = hlsl\\apply_morph_to_vb_cs.hlsl")
        _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
        _line(lines)
        _line(lines, "[CustomShader_ApplyMorph_PNTA40]")
        _line(lines, "cs = hlsl\\apply_morph_to_vb_pnta40_cs.hlsl")
        _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
        _line(lines)


def _append_bone_resources(lines: list[str], draw_key: str, payload: dict, output_directory: str):
    key = _resource_key(draw_key)
    _line(lines, f"[ResourceBoneStatic_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(payload.get('static', ''), output_directory)}")
    _line(lines)
    _line(lines, f"[ResourceBoneAnim_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(payload.get('anim', ''), output_directory)}")
    _line(lines)
    _line(lines, f"[ResourceBoneBind_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(payload.get('bind', ''), output_directory)}")
    _line(lines)
    palette_rows = max(int(payload.get("palette_row_count", 0) or 0), 3)
    _line(lines, f"[ResourceBonePalette_{key}_UAV]")
    _line(lines, "type = RWStructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"array = {palette_rows * 2}")
    _line(lines)
    _line(lines, f"[ResourceBonePalette_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"array = {palette_rows * 2}")
    _line(lines)
    _line(lines, f"[ResourceFakeCB1_{key}_UAV]")
    _line(lines, "type = RWStructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, "array = 4096")
    _line(lines)
    _line(lines, f"[ResourceFakeCB1_{key}]")
    _line(lines, "type = Buffer")
    _line(lines, "stride = 16")
    _line(lines, "format = R32G32B32A32_UINT")
    _line(lines, "array = 4096")
    _line(lines)


def _append_morph_resources(lines: list[str], draw_key: str, payload: dict, output_directory: str):
    key = _resource_key(draw_key)
    if payload.get("base_position_path"):
        stride = int(payload.get("base_position_stride", 16) or 16)
        _line(lines, f"[ResourceMorphBaseVB_{key}]")
        _line(lines, "type = Buffer")
        _line(lines, f"stride = {stride}")
        _line(lines, f"filename = {_ini_filename(payload.get('base_position_path', ''), output_directory)}")
        _line(lines)
        _line(lines, f"[ResourceMorphBaseVB_{key}_SRV]")
        _line(lines, "type = StructuredBuffer")
        _line(lines, f"stride = {stride}")
        _line(lines, f"filename = {_ini_filename(payload.get('base_position_path', ''), output_directory)}")
        _line(lines)
    _line(lines, f"[ResourceMorphStatic_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(payload.get('static', ''), output_directory)}")
    _line(lines)
    _line(lines, f"[ResourceMorphAnim_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_ini_filename(payload.get('anim', ''), output_directory)}")
    _line(lines)


def _append_geometry_resources(lines: list[str], draw_key: str, records: list[dict], output_directory: str):
    for record in records:
        suffix = _geometry_resource_suffix(record)
        if not suffix:
            suffix = _resource_key(draw_key)
        index_buffer = dict(record.get("index_buffer", {}) or {})
        index_path = index_buffer.get("file_path", "") or index_buffer.get("filename", "") or index_buffer.get("file_name", "")
        _line(lines, f"[ResourceGeometryIndex_{suffix}]")
        _line(lines, "type = Buffer")
        _line(lines, "format = R32_UINT")
        _line(lines, f"filename = {_ini_filename(index_path, output_directory)}")
        _line(lines)

        vertex_buffers = dict(record.get("vertex_buffers", {}) or {})
        for slot_name, vertex_buffer in sorted(vertex_buffers.items(), key=lambda item: item[0]):
            slot = str(slot_name or "").lower()
            buffer_payload = dict(vertex_buffer or {})
            stride = int(buffer_payload.get("stride", 0) or 0)
            buffer_path = (
                buffer_payload.get("file_path", "")
                or buffer_payload.get("filename", "")
                or buffer_payload.get("file_name", "")
            )
            resource_name = f"ResourceGeometry_{suffix}_{slot}"
            _line(lines, f"[{resource_name}]")
            _line(lines, "type = Buffer")
            _line(lines, f"stride = {stride}")
            _line(lines, f"filename = {_ini_filename(buffer_path, output_directory)}")
            _line(lines)
            if slot == "vb0":
                _line(lines, f"[{resource_name}_SRV]")
                _line(lines, "type = StructuredBuffer")
                _line(lines, f"stride = {stride}")
                _line(lines, f"filename = {_ini_filename(buffer_path, output_directory)}")
                _line(lines)


def _append_resources(lines: list[str], manifest: dict, output_directory: str):
    for draw_key, payload in manifest.get("payloads", {}).items():
        if "geometry" in payload:
            _append_geometry_resources(lines, draw_key, list(payload["geometry"]), output_directory)
        if "bone" in payload:
            _append_bone_resources(lines, draw_key, payload["bone"], output_directory)
        if "morph" in payload:
            _append_morph_resources(lines, draw_key, payload["morph"], output_directory)


def _append_texture_override(lines: list[str], draw_key: str, draw_part: dict, payload: dict):
    key = _resource_key(draw_key)
    bone_payload = payload.get("bone")
    morph_payload = payload.get("morph")
    geometry_records = list(payload.get("geometry", []) or [])
    geometry_record = geometry_records[0] if geometry_records else None
    geometry_suffix = _geometry_resource_suffix(geometry_record or {}) if geometry_record is not None else ""
    geometry_vertex_buffers = dict((geometry_record or {}).get("vertex_buffers", {}) or {})
    match_priority = int(draw_part.get("match_priority", DEFAULT_MATCH_PRIORITY) or DEFAULT_MATCH_PRIORITY)
    _line(lines, f"[TextureOverride_RX_{key}]")
    _line(lines, "; RX manifest-driven animation entry")
    _line(lines, f"hash = {draw_part.get('hash', '')}")
    _line(lines, f"match_index_count = {int(draw_part.get('match_index_count', 0) or 0)}")
    first_index = int(draw_part.get("first_index", 0) or 0)
    if first_index:
        _line(lines, f"match_first_index = {first_index}")
    _line(lines, f"match_priority = {match_priority}")
    if geometry_record is not None:
        _line(lines, "handling = skip")
    use_runtime_morph = (
        morph_payload is not None
        and ENABLE_RUNTIME_MORPH_REF_BINDING
        and geometry_record is not None
        and "vb0" in geometry_vertex_buffers
    )
    if use_runtime_morph:
        shader = "CustomShader_ApplyMorph_PNTA40" if str(morph_payload.get("base_position_layout", "")).endswith("PNTA40") else "CustomShader_ApplyMorph"
        base_srv_resource = f"ResourceMorphBaseVB_{key}_SRV" if morph_payload.get("base_position_path") else f"ResourceGeometry_{geometry_suffix}_vb0_SRV"
        base_copy_resource = f"ResourceMorphBaseVB_{key}" if morph_payload.get("base_position_path") else f"ResourceGeometry_{geometry_suffix}_vb0"
        live_position_resource = f"ResourceGeometry_{geometry_suffix}_vb0"
        _line(lines, f"cs-t0 = {base_srv_resource}")
        _line(lines, f"cs-t1 = ResourceMorphStatic_{key}")
        _line(lines, f"cs-t2 = ResourceMorphAnim_{key}")
        _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
        _line(lines, f"cs-u5 = copy {base_copy_resource}")
        _line(lines, f"dispatch = {(int(morph_payload.get('vertex_count', 0) or 0) + 63) // 64}, 1, 1")
        _line(lines, f"run = {shader}")
        _line(lines, f"{live_position_resource} = ref cs-u5")
        _line(lines, "cs-t0 = null")
        _line(lines, "cs-t1 = null")
        _line(lines, "cs-t2 = null")
        _line(lines, "cs-t3 = null")
        _line(lines, "cs-u5 = null")
    if bone_payload is not None:
        _line(lines, "run = CustomShader_ExtractCB1")
        _line(lines, f"cs-t0 = ResourceBoneAnim_{key}")
        _line(lines, f"cs-t1 = ResourceBoneBind_{key}")
        _line(lines, f"cs-t2 = ResourceBoneStatic_{key}")
        _line(lines, f"cs-u0 = ResourceBonePalette_{key}_UAV")
        _line(lines, "run = CustomShader_UpdateBonePaletteTQ")
        _line(lines, f"ResourceBonePalette_{key} = copy ResourceBonePalette_{key}_UAV")
        _line(lines, f"cs-u0 = ResourceFakeCB1_{key}_UAV")
        _line(lines, "cs-t0 = ResourceDumpedCB1_SRV")
        _line(lines, f"cs-t2 = ResourceBoneStatic_{key}")
        if str(draw_part.get("cb1_profile", "") or "").upper() == "EYELASH":
            _line(lines, "cs-t3 = ResourceCB1Flag_Eyelash")
        else:
            _line(lines, "cs-t3 = null")
        _line(lines, "run = CustomShader_RedirectCB1LocalPalette")
        _line(lines, f"ResourceFakeCB1_{key} = copy ResourceFakeCB1_{key}_UAV")
        _line(lines, f"vs-t0 = ResourceBonePalette_{key}")
        _line(lines, f"vs-cb1 = ResourceFakeCB1_{key}")
    if geometry_record is not None:
        _line(lines, f"ib = ref ResourceGeometryIndex_{geometry_suffix}")
        for slot_name, _vertex_buffer in sorted(geometry_vertex_buffers.items(), key=lambda item: item[0]):
            slot = str(slot_name or "").lower()
            _line(lines, f"{slot} = ref ResourceGeometry_{geometry_suffix}_{slot}")
        if "vb0" in geometry_vertex_buffers and "vb3" not in geometry_vertex_buffers:
            _line(lines, f"vb3 = ref ResourceGeometry_{geometry_suffix}_vb0")
        index_buffer = dict(geometry_record.get("index_buffer", {}) or {})
        index_count = int(index_buffer.get("index_count", geometry_record.get("index_count", 0)) or 0)
        _line(lines, f"drawindexedinstanced = {index_count},INSTANCE_COUNT,0,0,FIRST_INSTANCE")
    _line(lines)


def build_runtime_ini(manifest: dict, clip_name: str, output_directory: str = "") -> str:
    lines: list[str] = []
    _line(lines, "namespace = RX")
    _line(lines)
    _line(lines, "; Auto-generated by bone_importer RX runtime manifest renderer.")
    _line(lines, "; Do not edit generated resource names by hand; update rx_export_manifest.json instead.")
    _line(lines)
    _append_constants(lines, _clip_default_ticks_per_sample(manifest, clip_name))
    _append_global_resources(lines, manifest, clip_name, output_directory)
    _append_resources(lines, manifest, output_directory)
    for draw_key, draw_part in manifest.get("draw_parts", {}).items():
        payload = manifest.get("payloads", {}).get(draw_key, {})
        if not payload:
            continue
        _append_texture_override(lines, draw_key, draw_part, payload)
    return "\n".join(lines).rstrip() + "\n"


def write_runtime_ini_from_manifest(output_directory: str, clip_name: str) -> str:
    manifest = load_export_manifest(output_directory)
    output_path = resolve_runtime_ini_path(output_directory, clip_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as ini_file:
        ini_file.write(build_runtime_ini(manifest, clip_name, output_directory))
    write_runtime_hlsl_files(output_directory)
    return output_path


HLSL_FILES = {
    "rx_anim_coordinate_contract.hlsli": hlsl_coordinate_contract(),
    "extract_cb1_vs.hlsl": r"""struct V2P
{
    float4 pos : SV_Position;
    nointerpolation uint id : TEXCOORD0;
    nointerpolation uint4 raw_bits : TEXCOORD1;
};

cbuffer CB1 : register(b1)
{
    float4 cb1_data[4096];
};

V2P main(uint id : SV_VertexID)
{
    V2P output;
    float x = -0.98 + (id % 64) * 0.03;
    float y = -0.98 + (id / 64) * 0.03;
    output.pos = float4(x, y, 0.5, 1.0);
    output.id = id;
    output.raw_bits = asuint(cb1_data[id]);
    return output;
}
""",
    "extract_cb1_ps.hlsl": r"""struct V2P
{
    float4 pos : SV_Position;
    nointerpolation uint id : TEXCOORD0;
    nointerpolation uint4 raw_bits : TEXCOORD1;
};

RWStructuredBuffer<uint4> DumpedCB1 : register(u7);

float4 main(V2P input) : SV_Target
{
    DumpedCB1[input.id] = input.raw_bits;
    return float4(0.0, 0.0, 0.0, 0.0);
}
""",
    "update_master_playback_cs.hlsl": r"""Texture1D<float4> IniParams : register(t120);
RWStructuredBuffer<uint4> MasterPlayback : register(u0);

static const uint RX_ANIM_FLAG_PLAYING = 1u;

int RoundToInt(float value)
{
    return (value >= 0.0) ? (int)(value + 0.5) : (int)(value - 0.5);
}

[numthreads(1, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint4 playback0 = MasterPlayback[0];
    uint4 playback1 = MasterPlayback[1];
    uint4 playback2 = MasterPlayback[2];
    float4 control0 = IniParams[0];
    float4 control1 = IniParams[1];

    uint flags = playback0.x;
    uint playback_tick = playback0.w;
    uint ticks_per_sample = max(playback1.x, 1u);
    uint loop_start = playback1.y;
    uint loop_end = playback1.z;
    uint last_control_token = playback2.y;

    uint speed_override = (uint)max(control1.x, 0.0);
    if (speed_override > 0u)
    {
        ticks_per_sample = speed_override;
    }

    uint requested_playing = (uint)max(control0.x, 0.0);
    uint control_token = (uint)max(control0.y, 0.0);
    int control_value = RoundToInt(control0.z);
    uint seek_active = (uint)max(control0.w, 0.0);
    float seek_norm = saturate(control1.y);

    if (requested_playing != 0u)
    {
        flags |= RX_ANIM_FLAG_PLAYING;
    }
    else
    {
        flags &= ~RX_ANIM_FLAG_PLAYING;
    }

    uint loop_min = min(loop_start, loop_end);
    uint loop_max = max(loop_start, loop_end);
    uint loop_sample_count = max(loop_max - loop_min + 1u, 1u);
    uint max_tick = (loop_sample_count > 1u) ? ((loop_sample_count - 1u) * ticks_per_sample) : 0u;

    bool restarted = false;
    if (control_token != last_control_token)
    {
        if (control_value != 0)
        {
            playback_tick = 0u;
            restarted = true;
        }
        last_control_token = control_token;
    }

    if (seek_active != 0u)
    {
        playback_tick = (max_tick > 0u) ? (uint)RoundToInt(seek_norm * (float)max_tick) : 0u;
    }
    else if (!restarted && ((flags & RX_ANIM_FLAG_PLAYING) != 0u))
    {
        playback_tick += 1u;
    }

    uint current_tick = playback_tick;
    uint previous_tick = current_tick;
    if (seek_active == 0u && !restarted && ((flags & RX_ANIM_FLAG_PLAYING) != 0u))
    {
        previous_tick = (current_tick > 0u) ? (current_tick - 1u) : 0u;
    }

    MasterPlayback[0] = uint4(flags, previous_tick, current_tick, playback_tick);
    MasterPlayback[1] = uint4(ticks_per_sample, loop_start, loop_end, playback1.w);
    MasterPlayback[2] = uint4(seek_active, last_control_token, 0u, 0u);
}
""",
    "rx_anim_sampling.hlsli": r"""#ifndef RX_ANIM_SAMPLING_HLSLI
#define RX_ANIM_SAMPLING_HLSLI

static const uint RX_ANIM_FLAG_PLAYING = 1;
static const uint RX_ANIM_FLAG_LOOPING = 2;

uint ClampLoopSample(uint sample_id, uint loop_start, uint loop_end)
{
    return clamp(sample_id, min(loop_start, loop_end), max(loop_start, loop_end));
}

void ResolveTickToSampleWindow(uint tick, uint sample_count, uint ticks_per_sample, uint loop_start, uint loop_end, out uint sample_a, out uint sample_b, out float sample_alpha)
{
    ticks_per_sample = max(ticks_per_sample, 1);
    sample_count = max(sample_count, 1);
    uint local_sample = tick / ticks_per_sample;
    sample_alpha = (float)(tick % ticks_per_sample) / (float)ticks_per_sample;
    uint loop_min = min(loop_start, loop_end);
    uint loop_max = max(loop_start, loop_end);
    if (loop_max >= sample_count) loop_max = sample_count - 1;
    if (loop_min >= sample_count) loop_min = 0;
    uint loop_len = max(loop_max - loop_min + 1, 1);
    sample_a = loop_min + (local_sample % loop_len);
    sample_b = loop_min + ((local_sample + 1) % loop_len);
}

#endif
""",
    "update_rx_panel_state_cs.hlsl": r"""StructuredBuffer<uint4> TimelineStatic : register(t0);
StructuredBuffer<uint4> MasterPlayback : register(t1);
RWStructuredBuffer<float4> PanelState : register(u0);

[numthreads(1, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    uint4 timeline0 = TimelineStatic[0];
    uint4 timeline1 = TimelineStatic[1];
    uint4 playback0 = MasterPlayback[0];
    uint4 playback1 = MasterPlayback[1];

    uint sample_count = max(timeline0.x, 1u);
    uint current_tick = playback0.z;
    uint ticks_per_sample = max(playback1.x, 1u);
    uint loop_start = min(playback1.y, sample_count - 1u);
    uint loop_end = min(playback1.z, sample_count - 1u);

    if (loop_end < loop_start)
    {
        loop_start = min(timeline1.x, sample_count - 1u);
        loop_end = min(timeline1.y, sample_count - 1u);
    }
    if (loop_end < loop_start)
    {
        loop_start = 0u;
        loop_end = sample_count - 1u;
    }

    uint loop_sample_count = loop_end - loop_start + 1u;
    uint max_tick = (loop_sample_count > 1u) ? ((loop_sample_count - 1u) * ticks_per_sample) : 0u;

    float progress_norm = 0.0;
    if (max_tick > 0u)
    {
        progress_norm = saturate((float)min(current_tick, max_tick) / (float)max_tick);
    }

    PanelState[0] = float4(progress_norm, (float)current_tick, (float)max_tick, (float)ticks_per_sample);
}
""",
    "panel_digits.hlsl": r"""Texture1D<float4> IniParams : register(t120);
Texture2D<float4> DigitsAtlas : register(t100);

#define RECT IniParams[87]
#define TINT IniParams[89]

static const uint GLYPH_COUNT = 13u; // 0-9, colon, slash, space

SamplerState LinearSampler
{
    Filter = MIN_MAG_MIP_LINEAR;
    AddressU = Clamp;
    AddressV = Clamp;
};

struct VsOut
{
    float4 pos : SV_Position0;
    float2 uv : TEXCOORD0;
};

uint SpeedGlyphIndex(uint slot)
{
    uint speed = (uint)max(IniParams[1].x, 0.0);
    speed = min(max(speed, 1u), 6u);
    return (slot == 0u) ? speed : 12u;
}

#ifdef VERTEX_SHADER
void main(out VsOut output, uint vertex : SV_VertexID)
{
    float width = RECT.x;
    float height = RECT.y;
    float pos_x = RECT.z;
    float pos_y = RECT.w;

    float left = pos_x * 2.0 - 1.0;
    float right = (pos_x + width) * 2.0 - 1.0;
    float top = 1.0 - pos_y * 2.0;
    float bottom = 1.0 - (pos_y + height) * 2.0;

    switch (vertex)
    {
    case 0:
        output.pos.xy = float2(left, bottom);
        output.uv = float2(0.0, 1.0);
        break;
    case 1:
        output.pos.xy = float2(left, top);
        output.uv = float2(0.0, 0.0);
        break;
    case 2:
        output.pos.xy = float2(right, bottom);
        output.uv = float2(1.0, 1.0);
        break;
    default:
        output.pos.xy = float2(right, top);
        output.uv = float2(1.0, 0.0);
        break;
    }

    output.pos.zw = float2(0.0, 1.0);
}
#endif

#ifdef PIXEL_SHADER
float4 main(VsOut input) : SV_Target0
{
    uint atlas_width;
    uint atlas_height;
    DigitsAtlas.GetDimensions(atlas_width, atlas_height);
    if (!atlas_width || !atlas_height)
    {
        discard;
    }

    float glyph_left = (float)SpeedGlyphIndex(0u) / (float)GLYPH_COUNT;
    float glyph_right = glyph_left + (1.0 / (float)GLYPH_COUNT);
    float2 atlas_uv = float2(lerp(glyph_left, glyph_right, input.uv.x), input.uv.y);
    float4 result = DigitsAtlas.SampleLevel(LinearSampler, atlas_uv, 0.0);
    result *= TINT;
    if (result.a <= 1e-4)
    {
        discard;
    }
    return result;
}
#endif
""",
    "panel_sprite.hlsl": r"""Texture1D<float4> IniParams : register(t120);
Texture2D<float4> Sprite : register(t100);
StructuredBuffer<float4> PanelState : register(t101);

SamplerState LinearSampler
{
    Filter = MIN_MAG_MIP_LINEAR;
    AddressU = Clamp;
    AddressV = Clamp;
};

#define RECT IniParams[87]
#define PARAMS IniParams[88]
#define TINT IniParams[89]

struct VsOut
{
    float4 pos : SV_Position0;
    float2 uv : TEXCOORD0;
};

float ResolveProgressNorm()
{
    float progress_norm = 0.0;
    if (IniParams[2].y > 0.5)
    {
        progress_norm = IniParams[2].x;
    }
    else
    {
        progress_norm = PanelState[0].x;
    }
    return saturate(progress_norm);
}

#ifdef VERTEX_SHADER
void main(out VsOut output, uint vertex : SV_VertexID)
{
    float width = RECT.x;
    float height = RECT.y;
    float pos_x = RECT.z;
    float pos_y = RECT.w;

    float left = pos_x * 2.0 - 1.0;
    float right = (pos_x + width) * 2.0 - 1.0;
    float top = 1.0 - pos_y * 2.0;
    float bottom = 1.0 - (pos_y + height) * 2.0;

    switch (vertex)
    {
    case 0:
        output.pos.xy = float2(left, bottom);
        output.uv = float2(0.0, 1.0);
        break;
    case 1:
        output.pos.xy = float2(left, top);
        output.uv = float2(0.0, 0.0);
        break;
    case 2:
        output.pos.xy = float2(right, bottom);
        output.uv = float2(1.0, 1.0);
        break;
    default:
        output.pos.xy = float2(right, top);
        output.uv = float2(1.0, 0.0);
        break;
    }

    output.pos.zw = float2(0.0, 1.0);
}
#endif

#ifdef PIXEL_SHADER
float4 main(VsOut input) : SV_Target0
{
    uint width;
    uint height;
    Sprite.GetDimensions(width, height);
    if (!width || !height)
    {
        discard;
    }

    float2 sprite_uv = input.uv;
    uint mode = (uint)PARAMS.x;
    float progress_norm = 1.0;

    if (mode == 1u || mode == 2u)
    {
        progress_norm = ResolveProgressNorm();
    }

    if (mode == 1u && input.uv.x > progress_norm)
    {
        discard;
    }

    if (mode == 2u)
    {
        float half_width = max(PARAMS.y, 0.0025);
        float left = progress_norm - half_width;
        float right = progress_norm + half_width;
        if (input.uv.x < left || input.uv.x > right)
        {
            discard;
        }

        sprite_uv.x = saturate((input.uv.x - left) / max(right - left, 1e-5));
    }

    float4 result = Sprite.SampleLevel(LinearSampler, sprite_uv, 0.0);
    result *= TINT;
    if (result.a <= 1e-4)
    {
        discard;
    }
    return result;
}
#endif
""",
    "rx_anim_efmi_normal.hlsli": r"""#ifndef RX_ANIM_EFMI_NORMAL_HLSLI
#define RX_ANIM_EFMI_NORMAL_HLSLI

static const uint RX_MORPH_FLAG_HAS_POSITION_DELTAS = 1u;
static const uint RX_MORPH_FLAG_HAS_NORMAL_TARGETS = 2u;
static const uint RX_MORPH_FLAG_HAS_TANGENT_TARGETS = 4u;

int DecodeSigned10(uint raw_value)
{
    uint value = raw_value & 0x3ffu;
    return (value >= 512u) ? ((int)value - 1024) : (int)value;
}

float3 NormalizeOrFallback(float3 value, float3 fallback_value)
{
    float value_length = length(value);
    return (value_length > 1e-8) ? (value / value_length) : fallback_value;
}

float3 DecodeEFMIPackedNormal(uint packed_normal)
{
    float encoded_x = (float)DecodeSigned10(packed_normal) / 511.0;
    float encoded_y = (float)DecodeSigned10(packed_normal >> 10u) / 511.0;
    float encoded_z = 1.0 - abs(encoded_x) - abs(encoded_y);
    if (encoded_z < 0.0)
    {
        float old_x = encoded_x;
        encoded_x = (1.0 - abs(encoded_y)) * ((old_x >= 0.0) ? 1.0 : -1.0);
        encoded_y = (1.0 - abs(old_x)) * ((encoded_y >= 0.0) ? 1.0 : -1.0);
    }
    return NormalizeOrFallback(float3(encoded_x, encoded_y, encoded_z), float3(0.0, 0.0, 1.0));
}

float DecodeEFMIPackedTangentScalar(uint packed_normal)
{
    return clamp((float)DecodeSigned10(packed_normal >> 20u) / 511.0, -1.0, 1.0);
}

float DecodeEFMIPackedBitangentSign(uint packed_normal)
{
    return ((packed_normal >> 31u) & 1u) != 0u ? 1.0 : -1.0;
}

uint PackSigned10(float value)
{
    int signed_value = (int)round(clamp(value, -1.0, 1.0) * 511.0);
    return ((uint)signed_value) & 0x3ffu;
}

uint EncodeEFMIPackedNormal(float3 normal_value, float tangent_scalar, float bitangent_sign)
{
    float3 normal = NormalizeOrFallback(normal_value, float3(0.0, 0.0, 1.0));
    float l1_norm = abs(normal.x) + abs(normal.y) + abs(normal.z);
    float encoded_x = 0.0;
    float encoded_y = 0.0;
    if (l1_norm > 1e-8)
    {
        float3 encoded = normal / l1_norm;
        encoded_x = encoded.x;
        encoded_y = encoded.y;
        if (encoded.z < 0.0)
        {
            float old_x = encoded_x;
            encoded_x = (1.0 - abs(encoded_y)) * ((old_x >= 0.0) ? 1.0 : -1.0);
            encoded_y = (1.0 - abs(old_x)) * ((encoded_y >= 0.0) ? 1.0 : -1.0);
        }
    }

    uint packed_x = PackSigned10(encoded_x);
    uint packed_y = PackSigned10(encoded_y);
    uint packed_tangent = PackSigned10(tangent_scalar);
    uint packed_flag = 1u << 30u;
    uint sign_flag = (bitangent_sign >= 0.0) ? (1u << 31u) : 0u;
    return packed_x | (packed_y << 10u) | (packed_tangent << 20u) | packed_flag | sign_flag;
}

float2 UnpackHalf2(uint packed_value)
{
    return float2(
        f16tof32(packed_value & 0xffffu),
        f16tof32((packed_value >> 16u) & 0xffffu)
    );
}

#endif
""",
    "rx_anim_morph_common.hlsli": r"""#ifndef RX_ANIM_MORPH_COMMON_HLSLI
#define RX_ANIM_MORPH_COMMON_HLSLI

uint RxReadUint4Component(uint4 row, uint component_index)
{
    if (component_index == 0u) return row.x;
    if (component_index == 1u) return row.y;
    if (component_index == 2u) return row.z;
    return row.w;
}

uint RxMorphRowsPerSample(uint channel_count)
{
    uint weights_per_row = max(MorphAnim[0].w, 1u);
    return max((max(channel_count, 1u) + weights_per_row - 1u) / weights_per_row, 1u);
}

float RxLoadMorphWeight(uint channel_index, uint sample_index)
{
    uint4 anim_header = MorphAnim[0];
    uint channel_count = anim_header.x;
    uint sample_count = max(anim_header.y, 1u);
    uint weights_per_row = max(anim_header.w, 1u);
    if (channel_index >= channel_count) return 0.0;

    sample_index = min(sample_index, sample_count - 1u);
    uint rows_per_sample = RxMorphRowsPerSample(channel_count);
    uint row_index = 2u + sample_index * rows_per_sample + channel_index / weights_per_row;
    uint packed_pair = RxReadUint4Component(MorphAnim[row_index], (channel_index % weights_per_row) / 2u);
    uint half_bits = ((channel_index & 1u) == 0u) ? (packed_pair & 0xffffu) : ((packed_pair >> 16u) & 0xffffu);
    return f16tof32(half_bits);
}

void RxResolveMorphSampleWindow(out uint sample_a, out uint sample_b, out float sample_alpha)
{
    uint sample_count = max(MorphAnim[0].y, 1u);
    uint4 playback0 = MasterPlayback[0];
    uint4 playback1 = MasterPlayback[1];
    ResolveTickToSampleWindow(
        playback0.z,
        sample_count,
        max(playback1.x, 1u),
        playback1.y,
        playback1.z,
        sample_a,
        sample_b,
        sample_alpha
    );
}

float RxSampleMorphWeight(uint channel_index, uint sample_a, uint sample_b, float sample_alpha)
{
    float weight_a = RxLoadMorphWeight(channel_index, sample_a);
    float weight_b = RxLoadMorphWeight(channel_index, sample_b);
    return lerp(weight_a, weight_b, sample_alpha);
}

#endif
""",
    "update_bone_palette_tq_cs.hlsl": r"""#include "rx_anim_sampling.hlsli"
#include "rx_anim_coordinate_contract.hlsli"

StructuredBuffer<float4> BoneAnim : register(t0);
StructuredBuffer<float4> BoneBind : register(t1);
StructuredBuffer<uint4> BoneStatic : register(t2);
RWStructuredBuffer<float4> BonePalette : register(u0);
RWStructuredBuffer<uint4> MasterPlayback : register(u1);

float4 QuatNormalize(float4 q)
{
    float q_len = length(q);
    if (q_len <= 1e-8) return float4(0.0, 0.0, 0.0, 1.0);
    return q / q_len;
}

float4 QuatNlerp(float4 a, float4 b, float t)
{
    if (dot(a, b) < 0.0) b = -b;
    return QuatNormalize(lerp(a, b, t));
}

void BuildPoseRows(float3 t, float4 q, out float4 row0, out float4 row1, out float4 row2)
{
    float x = q.x, y = q.y, z = q.z, w = q.w;
    float xx = x * x, yy = y * y, zz = z * z;
    float xy = x * y, xz = x * z, yz = y * z;
    float wx = w * x, wy = w * y, wz = w * z;
    row0 = float4(1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), t.x);
    row1 = float4(2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), t.y);
    row2 = float4(2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), t.z);
}

void MultiplyAffineRows(
    float4 l0,
    float4 l1,
    float4 l2,
    float4 r0,
    float4 r1,
    float4 r2,
    out float4 o0,
    out float4 o1,
    out float4 o2
)
{
    o0 = float4(
        dot(l0.xyz, float3(r0.x, r1.x, r2.x)),
        dot(l0.xyz, float3(r0.y, r1.y, r2.y)),
        dot(l0.xyz, float3(r0.z, r1.z, r2.z)),
        dot(l0.xyz, float3(r0.w, r1.w, r2.w)) + l0.w
    );
    o1 = float4(
        dot(l1.xyz, float3(r0.x, r1.x, r2.x)),
        dot(l1.xyz, float3(r0.y, r1.y, r2.y)),
        dot(l1.xyz, float3(r0.z, r1.z, r2.z)),
        dot(l1.xyz, float3(r0.w, r1.w, r2.w)) + l1.w
    );
    o2 = float4(
        dot(l2.xyz, float3(r0.x, r1.x, r2.x)),
        dot(l2.xyz, float3(r0.y, r1.y, r2.y)),
        dot(l2.xyz, float3(r0.z, r1.z, r2.z)),
        dot(l2.xyz, float3(r0.w, r1.w, r2.w)) + l2.w
    );
}

float4 BuildIdentityRow(uint row_index)
{
    if (row_index == 0u) return float4(1.0, 0.0, 0.0, 0.0);
    if (row_index == 1u) return float4(0.0, 1.0, 0.0, 0.0);
    return float4(0.0, 0.0, 1.0, 0.0);
}

uint LoadSlotId(uint bone_index)
{
    uint4 row = BoneStatic[2 + bone_index / 4];
    return row[bone_index & 3];
}

void LoadPose(uint sample_id, uint bone_index, uint bone_count, out float3 t, out float4 q)
{
    uint base_row = (sample_id * bone_count + bone_index) * 2;
    t = BoneAnim[base_row].xyz;
    q = BoneAnim[base_row + 1];
}

[numthreads(1, 1, 1)]
void main(uint3 dispatch_id : SV_DispatchThreadID)
{
    uint bone_index = dispatch_id.x;
    uint4 header0 = BoneStatic[0];
    uint4 header1 = BoneStatic[1];
    uint bone_count = header0.x;
    uint sample_count = header0.y;
    uint reserved_rows = header0.z;
    uint payload_flags = header1.z;
    if (bone_index >= bone_count) return;

    uint4 playback0 = MasterPlayback[0];
    uint4 playback1 = MasterPlayback[1];
    uint current_tick = playback0.z;
    uint previous_tick = playback0.y;
    uint ticks_per_sample = playback1.x;
    uint loop_start = playback1.y;
    uint loop_end = playback1.z;

    uint sample_a, sample_b;
    float alpha;
    ResolveTickToSampleWindow(current_tick, sample_count, ticks_per_sample, loop_start, loop_end, sample_a, sample_b, alpha);

    float3 ta, tb;
    float4 qa, qb;
    LoadPose(sample_a, bone_index, bone_count, ta, qa);
    LoadPose(sample_b, bone_index, bone_count, tb, qb);
    float3 t = lerp(ta, tb, alpha);
    float4 q = QuatNlerp(qa, qb, alpha);

    uint bind_row = bone_index * 3;
    float4 b0 = BoneBind[bind_row + 0];
    float4 b1 = BoneBind[bind_row + 1];
    float4 b2 = BoneBind[bind_row + 2];

    float4 pose0, pose1, pose2;
    BuildPoseRows(t, q, pose0, pose1, pose2);

    float4 skin0, skin1, skin2;
    MultiplyAffineRows(pose0, pose1, pose2, b0, b1, b2, skin0, skin1, skin2);

    float4 out0, out1, out2;
    RxConvertSkinRowsFromBlenderToGame(skin0, skin1, skin2, payload_flags, out0, out1, out2);

    uint slot_id = LoadSlotId(bone_index);
    uint row_base = reserved_rows + slot_id * 3;
    if (bone_index == 0u)
    {
        uint reserved_limit = min(reserved_rows, 3u);
        [unroll]
        for (uint reserved_row = 0u; reserved_row < 3u; reserved_row += 1u)
        {
            if (reserved_row < reserved_limit)
            {
                float4 identity_row = BuildIdentityRow(reserved_row);
                BonePalette[reserved_row] = identity_row;
                BonePalette[header1.y + reserved_row] = identity_row;
            }
        }
    }
    BonePalette[row_base + 0] = out0;
    BonePalette[row_base + 1] = out1;
    BonePalette[row_base + 2] = out2;

    uint previous_base = header1.y;
    ResolveTickToSampleWindow(previous_tick, sample_count, ticks_per_sample, loop_start, loop_end, sample_a, sample_b, alpha);
    LoadPose(sample_a, bone_index, bone_count, ta, qa);
    LoadPose(sample_b, bone_index, bone_count, tb, qb);
    t = lerp(ta, tb, alpha);
    q = QuatNlerp(qa, qb, alpha);
    BuildPoseRows(t, q, pose0, pose1, pose2);
    MultiplyAffineRows(pose0, pose1, pose2, b0, b1, b2, skin0, skin1, skin2);
    RxConvertSkinRowsFromBlenderToGame(skin0, skin1, skin2, payload_flags, out0, out1, out2);
    BonePalette[previous_base + row_base + 0] = out0;
    BonePalette[previous_base + row_base + 1] = out1;
    BonePalette[previous_base + row_base + 2] = out2;
}
""",
    "redirect_cb1_local_palette_cs.hlsl": r"""StructuredBuffer<uint4> DumpedCB1 : register(t0);
StructuredBuffer<uint4> BoneStatic : register(t2);
Buffer<float> CB1FlagValue : register(t3);
RWStructuredBuffer<uint4> FakeCB1 : register(u0);

[numthreads(1024, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint row_id = id.x;
    if (row_id >= 4096u) return;

    uint4 cb_data = DumpedCB1[row_id];
    uint block_row = row_id & 15u;

    if (block_row == 4u)
    {
        uint flag_count = 0u;
        CB1FlagValue.GetDimensions(flag_count);
        if (flag_count > 0u)
        {
            cb_data.w = (uint)CB1FlagValue[0];
        }
    }

    if (block_row == 5u)
    {
        uint4 static_header1 = BoneStatic[1];
        // Match the native/YV contract: cb1 points to the start of the palette
        // window, including its reserved identity rows. The game VS applies its
        // own reserved-row addressing when reading blend-index matrices.
        cb_data.x = 0u;
        cb_data.y = static_header1.y;
    }

    FakeCB1[row_id] = cb_data;
}
""",
    "apply_morph_to_vb_cs.hlsl": r"""#include "rx_anim_sampling.hlsli"
#include "rx_anim_efmi_normal.hlsli"

struct MorphVB16
{
    float3 position;
    uint packed_normal;
};

StructuredBuffer<MorphVB16> BaseVB : register(t0);
StructuredBuffer<uint4> MorphStatic : register(t1);
StructuredBuffer<uint4> MorphAnim : register(t2);
StructuredBuffer<uint4> MasterPlayback : register(t3);
RWStructuredBuffer<MorphVB16> RuntimeVB : register(u5);

#include "rx_anim_morph_common.hlsli"

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint vertex_id = id.x;
    uint4 static_header0 = MorphStatic[0];
    uint4 static_header1 = MorphStatic[1];
    uint vertex_count = static_header0.y;
    if (vertex_id >= vertex_count) return;

    uint span_row_count = static_header1.z;
    uint influence_row_stride = max(MorphStatic[2].y, 1u);
    uint influence_base_row = 3u + span_row_count;
    uint4 span = MorphStatic[3u + vertex_id];

    MorphVB16 base_vertex = BaseVB[vertex_id];
    MorphVB16 output_vertex = base_vertex;
    float3 base_normal = DecodeEFMIPackedNormal(base_vertex.packed_normal);
    float3 normal_acc = base_normal;
    float base_tangent = DecodeEFMIPackedTangentScalar(base_vertex.packed_normal);
    float tangent_acc = base_tangent;
    float base_sign = DecodeEFMIPackedBitangentSign(base_vertex.packed_normal);
    float sign_acc = base_sign;
    bool has_normals = (static_header1.x & RX_MORPH_FLAG_HAS_NORMAL_TARGETS) != 0u;

    uint sample_a;
    uint sample_b;
    float sample_alpha;
    RxResolveMorphSampleWindow(sample_a, sample_b, sample_alpha);

    for (uint local_index = 0u; local_index < span.y; ++local_index)
    {
        uint influence_index = span.x + local_index;
        uint4 influence_row = MorphStatic[influence_base_row + influence_index * influence_row_stride];
        uint channel_index = influence_row.x & 0xffffu;
        float weight = RxSampleMorphWeight(channel_index, sample_a, sample_b, sample_alpha);
        if (abs(weight) <= 1e-8) continue;

        float2 delta_xy = UnpackHalf2(influence_row.y);
        float2 delta_z0 = UnpackHalf2(influence_row.z);
        output_vertex.position += weight * float3(delta_xy.x, delta_xy.y, delta_z0.x);

        if (has_normals)
        {
            uint target_packed = influence_row.w;
            float3 target_normal = DecodeEFMIPackedNormal(target_packed);
            normal_acc += weight * (target_normal - base_normal);
            tangent_acc += weight * (DecodeEFMIPackedTangentScalar(target_packed) - base_tangent);
            sign_acc += weight * (DecodeEFMIPackedBitangentSign(target_packed) - base_sign);
        }
    }

    if (has_normals)
    {
        output_vertex.packed_normal = EncodeEFMIPackedNormal(
            NormalizeOrFallback(normal_acc, base_normal),
            tangent_acc,
            sign_acc >= 0.0 ? 1.0 : -1.0
        );
    }

    RuntimeVB[vertex_id] = output_vertex;
}
""",
    "apply_morph_to_vb_pnta40_cs.hlsl": r"""#include "rx_anim_sampling.hlsli"
#include "rx_anim_efmi_normal.hlsli"

struct MorphVB40
{
    float3 position;
    float3 normal;
    float4 tangent;
};

StructuredBuffer<MorphVB40> BaseVB : register(t0);
StructuredBuffer<uint4> MorphStatic : register(t1);
StructuredBuffer<uint4> MorphAnim : register(t2);
StructuredBuffer<uint4> MasterPlayback : register(t3);
RWStructuredBuffer<MorphVB40> RuntimeVB : register(u5);

#include "rx_anim_morph_common.hlsli"

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint vertex_id = id.x;
    uint4 static_header0 = MorphStatic[0];
    uint4 static_header1 = MorphStatic[1];
    uint vertex_count = static_header0.y;
    if (vertex_id >= vertex_count) return;

    uint span_row_count = static_header1.z;
    uint influence_row_stride = max(MorphStatic[2].y, 1u);
    uint influence_base_row = 3u + span_row_count;
    uint4 span = MorphStatic[3u + vertex_id];

    MorphVB40 base_vertex = BaseVB[vertex_id];
    MorphVB40 output_vertex = base_vertex;
    float3 base_normal = NormalizeOrFallback(base_vertex.normal, float3(0.0, 0.0, 1.0));
    float3 normal_acc = base_normal;
    float4 tangent_acc = base_vertex.tangent;
    bool has_normals = (static_header1.x & RX_MORPH_FLAG_HAS_NORMAL_TARGETS) != 0u;
    bool has_tangents = ((static_header1.x & RX_MORPH_FLAG_HAS_TANGENT_TARGETS) != 0u) && influence_row_stride >= 2u;

    uint sample_a;
    uint sample_b;
    float sample_alpha;
    RxResolveMorphSampleWindow(sample_a, sample_b, sample_alpha);

    for (uint local_index = 0u; local_index < span.y; ++local_index)
    {
        uint influence_index = span.x + local_index;
        uint influence_row_index = influence_base_row + influence_index * influence_row_stride;
        uint4 influence_row = MorphStatic[influence_row_index];
        uint channel_index = influence_row.x & 0xffffu;
        float weight = RxSampleMorphWeight(channel_index, sample_a, sample_b, sample_alpha);
        if (abs(weight) <= 1e-8) continue;

        float2 delta_xy = UnpackHalf2(influence_row.y);
        float2 delta_z0 = UnpackHalf2(influence_row.z);
        output_vertex.position += weight * float3(delta_xy.x, delta_xy.y, delta_z0.x);

        if (has_normals)
        {
            float3 target_normal = DecodeEFMIPackedNormal(influence_row.w);
            normal_acc += weight * (target_normal - base_normal);
        }

        if (has_tangents)
        {
            uint4 tangent_row = MorphStatic[influence_row_index + 1u];
            float2 tangent_xy = UnpackHalf2(tangent_row.x);
            float2 tangent_zw = UnpackHalf2(tangent_row.y);
            float4 target_tangent = float4(tangent_xy.x, tangent_xy.y, tangent_zw.x, tangent_zw.y);
            tangent_acc += weight * (target_tangent - base_vertex.tangent);
        }
    }

    if (has_normals)
    {
        output_vertex.normal = NormalizeOrFallback(normal_acc, base_normal);
    }
    if (has_tangents)
    {
        output_vertex.tangent.xyz = NormalizeOrFallback(tangent_acc.xyz, base_vertex.tangent.xyz);
        output_vertex.tangent.w = tangent_acc.w >= 0.0 ? 1.0 : -1.0;
    }

    RuntimeVB[vertex_id] = output_vertex;
}
""",
}


def write_runtime_hlsl_files(output_directory: str) -> tuple[str, ...]:
    hlsl_dir = os.path.join(os.path.abspath(output_directory or "."), "hlsl")
    os.makedirs(hlsl_dir, exist_ok=True)
    paths = []
    hlsl_files = dict(HLSL_FILES)
    # Keep the coordinate contract fresh even in long-lived Blender sessions
    # where runtime_ini may outlive a reloaded coordinate_contract module.
    hlsl_files["rx_anim_coordinate_contract.hlsli"] = hlsl_coordinate_contract()
    for file_name, content in hlsl_files.items():
        if not str(content or "").strip():
            raise RuntimeError(f"Refusing to write empty runtime HLSL file: {file_name}")
        path = os.path.join(hlsl_dir, file_name)
        with open(path, "w", encoding="utf-8", newline="\n") as hlsl_file:
            hlsl_file.write(content.strip() + "\n")
        paths.append(path)
    return tuple(paths)
