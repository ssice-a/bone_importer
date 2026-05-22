"""Manifest-driven RX runtime INI and HLSL writers."""

from __future__ import annotations

import os
import shutil

from .animation_bank import build_animation_bank_from_manifest
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


def _morph_dispatch_groups_by_shader(manifest: dict) -> dict[str, int]:
    groups = {
        "CustomShader_ApplyMorph": 1,
        "CustomShader_ApplyMorph_PNTA40": 1,
    }
    for payload in (manifest.get("payloads", {}) or {}).values():
        morph_payload = dict(payload.get("morph", {}) or {})
        if not morph_payload:
            continue
        shader = (
            "CustomShader_ApplyMorph_PNTA40"
            if str(morph_payload.get("base_position_layout", "")).endswith("PNTA40")
            else "CustomShader_ApplyMorph"
        )
        vertex_count = int(morph_payload.get("vertex_count", 0) or 0)
        groups[shader] = max(groups[shader], (vertex_count + 63) // 64)
    return groups


def _resource_key(draw_key: str) -> str:
    return sanitize_export_name(draw_key, "draw_part")


def _mesh_resource_suffix(record: dict) -> str:
    return sanitize_export_name(str(record.get("resource_suffix", "") or ""), "mesh")


def _draw_segment_comment(record: dict) -> str:
    object_names = [
        str(object_name or "").strip()
        for object_name in list(record.get("object_names", []) or [])
        if str(object_name or "").strip()
    ]
    if object_names:
        return ", ".join(object_names)
    resource_suffix = str(record.get("resource_suffix", "") or "").strip()
    return resource_suffix or "unknown"


def resolve_runtime_ini_path(output_directory: str, clip_name: str) -> str:
    safe_clip_name = sanitize_export_name(normalize_clip_name(clip_name), "rxanimin")
    return os.path.join(os.path.abspath(output_directory or "."), f"{safe_clip_name}.ini")


def _clip_default_ticks_per_sample(manifest: dict, clip_name: str) -> int:
    bank = build_animation_bank_from_manifest(manifest, normalize_clip_name(clip_name))
    clip_key = normalize_clip_name(clip_name)
    for clip in bank.clips:
        if clip.name == clip_key:
            return max(int(clip.default_ticks_per_sample), 1)
    return max(int(bank.default_clip.default_ticks_per_sample), 1)


def _clip_count(manifest: dict) -> int:
    bank = build_animation_bank_from_manifest(manifest)
    return max(len(bank.clips), 1)


def _append_constants(lines: list[str], default_ticks_per_sample: int = 1, clip_count: int = 1):
    speed = max(int(default_ticks_per_sample), 1)
    action_count = max(int(clip_count), 1)
    _line(lines, "[Constants]")
    _line(lines, "global persist $rx_anim_play = 1")
    _line(lines, "global persist $rx_anim_control_token = 0")
    _line(lines, "global persist $rx_anim_control_value = 0")
    _line(lines, f"global persist $rx_anim_speed = {speed}")
    _line(lines, f"global persist $rx_anim_speed_default = {speed}")
    _line(lines, "global persist $rx_anim_action_index = 0")
    _line(lines, f"global $rx_anim_action_count = {action_count}")
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
    _line(lines, f"$rx_anim_action_count = {action_count}")
    _line(lines, "if $rx_anim_action_index >= $rx_anim_action_count")
    _line(lines, "    $rx_anim_action_index = 0")
    _line(lines, "endif")
    _line(lines, "x = $rx_anim_play")
    _line(lines, "y = $rx_anim_control_token")
    _line(lines, "z = $rx_anim_control_value")
    _line(lines, "w = $rx_anim_seek_active")
    _line(lines, "x1 = $rx_anim_speed")
    _line(lines, "y1 = $rx_anim_seek_norm")
    _line(lines, "z1 = $rx_anim_action_index")
    _line(lines, "w1 = $rx_anim_action_count")
    _line(lines, "run = CustomShader_UpdateMasterPlayback")
    _line(lines, "run = CommandListRXUIPresent")
    _line(lines)


def _append_global_resources(lines: list[str], manifest: dict, clip_name: str, output_directory: str):
    bank = build_animation_bank_from_manifest(manifest, normalize_clip_name(clip_name))
    morph_dispatch_groups = _morph_dispatch_groups_by_shader(manifest)
    timeline_path = bank.timeline_static_path or f"{sanitize_export_name(clip_name, 'rxanimin')}_timeline_static.buf"
    master_path = bank.master_playback_path or f"{sanitize_export_name(clip_name, 'rxanimin')}_master_playback.buf"

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
    _line(lines, "cs-t0 = ResourceTimelineStatic")
    _line(lines, "cs-u0 = ResourceMasterPlayback")
    _line(lines, "dispatch = 1, 1, 1")
    _line(lines, "cs-t0 = null")
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
        _line(lines, f"dispatch = {morph_dispatch_groups['CustomShader_ApplyMorph']}, 1, 1")
        _line(lines, "cs-t0 = null")
        _line(lines, "cs-t1 = null")
        _line(lines, "cs-t2 = null")
        _line(lines, "cs-t3 = null")
        _line(lines, "cs-u5 = null")
        _line(lines)
        _line(lines, "[CustomShader_ApplyMorph_PNTA40]")
        _line(lines, "cs = hlsl\\apply_morph_to_vb_pnta40_cs.hlsl")
        _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
        _line(lines, f"dispatch = {morph_dispatch_groups['CustomShader_ApplyMorph_PNTA40']}, 1, 1")
        _line(lines, "cs-t0 = null")
        _line(lines, "cs-t1 = null")
        _line(lines, "cs-t2 = null")
        _line(lines, "cs-t3 = null")
        _line(lines, "cs-u5 = null")
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
        suffix = _mesh_resource_suffix(record)
        if not suffix:
            suffix = _resource_key(draw_key)
        index_buffer = dict(record.get("index_buffer", {}) or {})
        index_path = index_buffer.get("file_path", "") or index_buffer.get("filename", "") or index_buffer.get("file_name", "")
        _line(lines, f"[ResourceMeshIndex_{suffix}]")
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
            resource_name = f"ResourceMesh_{suffix}_{slot}"
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
    geometry_suffix = _mesh_resource_suffix(geometry_record or {}) if geometry_record is not None else ""
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
        base_srv_resource = f"ResourceMorphBaseVB_{key}_SRV" if morph_payload.get("base_position_path") else f"ResourceMesh_{geometry_suffix}_vb0_SRV"
        base_copy_resource = f"ResourceMorphBaseVB_{key}" if morph_payload.get("base_position_path") else f"ResourceMesh_{geometry_suffix}_vb0"
        live_position_resource = f"ResourceMesh_{geometry_suffix}_vb0"
        _line(lines, f"cs-t0 = {base_srv_resource}")
        _line(lines, f"cs-t1 = ResourceMorphStatic_{key}")
        _line(lines, f"cs-t2 = ResourceMorphAnim_{key}")
        _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
        _line(lines, f"cs-u5 = copy {base_copy_resource}")
        _line(lines, f"{live_position_resource} = ref cs-u5")
        _line(lines, f"run = {shader}")
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
        _line(lines, f"ib = ref ResourceMeshIndex_{geometry_suffix}")
        for slot_name, _vertex_buffer in sorted(geometry_vertex_buffers.items(), key=lambda item: item[0]):
            slot = str(slot_name or "").lower()
            _line(lines, f"{slot} = ref ResourceMesh_{geometry_suffix}_{slot}")
        if "vb0" in geometry_vertex_buffers and "vb3" not in geometry_vertex_buffers:
            _line(lines, f"vb3 = ref ResourceMesh_{geometry_suffix}_vb0")
        index_buffer = dict(geometry_record.get("index_buffer", {}) or {})
        index_count = int(index_buffer.get("index_count", geometry_record.get("index_count", 0)) or 0)
        _line(lines, f"; draw segment: {_draw_segment_comment(geometry_record)}")
        _line(lines, f"drawindexedinstanced = {index_count},INSTANCE_COUNT,0,0,FIRST_INSTANCE")
    _line(lines)


def build_runtime_ini(manifest: dict, clip_name: str, output_directory: str = "") -> str:
    lines: list[str] = []
    _line(lines, "namespace = RX")
    _line(lines)
    _line(lines, "; Auto-generated by bone_importer RX runtime manifest renderer.")
    _line(lines, "; Do not edit generated resource names by hand; update rx_export_manifest.json instead.")
    _line(lines)
    _append_constants(lines, _clip_default_ticks_per_sample(manifest, clip_name), _clip_count(manifest))
    _append_global_resources(lines, manifest, clip_name, output_directory)
    _append_resources(lines, manifest, output_directory)
    for draw_key, draw_part in manifest.get("draw_parts", {}).items():
        payload = manifest.get("payloads", {}).get(draw_key, {})
        if not payload:
            continue
        _append_texture_override(lines, draw_key, draw_part, payload)
    return "\n".join(lines).rstrip() + "\n"


def _append_ui_resource(lines: list[str], resource_name: str, file_name: str):
    _line(lines, f"[{resource_name}]")
    _line(lines, f"filename = ui\\{file_name}")
    _line(lines)


def _append_select_action_command(lines: list[str], action_index: int):
    _line(lines, f"[CommandListRXSelectAction{action_index}]")
    _line(lines, f"if $rx_anim_action_count > {action_index}")
    _line(lines, f"    $rx_anim_action_index = {action_index}")
    _line(lines, "    $rx_anim_control_value = 2")
    _line(lines, "    $rx_anim_control_token = $rx_anim_control_token + 1")
    _line(lines, "endif")
    _line(lines)


def build_runtime_ui_ini(manifest: dict | None = None, clip_name: str = "rxanimin") -> str:
    """Build the YV-style RX panel with player, hotkey, and action tabs."""
    del clip_name
    manifest = manifest or {}
    action_button_count = min(max(_clip_count(manifest), 1), 4)
    lines: list[str] = []
    _line(lines, "namespace = RX")
    _line(lines)
    _line(lines, "; Auto-generated RX UI split-out file.")
    _line(lines, "; Tabs: player controls, hotkeys, action selection.")
    _line(lines)
    _line(lines, "[KeyToggleRXPanel]")
    _line(lines, "key = ctrl alt /")
    _line(lines, "type = cycle")
    _line(lines, "$rx_ui_open = 0,1")
    _line(lines)
    _line(lines, "[KeyRXPanelHold]")
    _line(lines, "condition = $rx_ui_open == 1")
    _line(lines, "key = no_ctrl no_shift VK_LBUTTON")
    _line(lines, "type = hold")
    _line(lines, "$rx_ui_hold = 1")
    _line(lines)
    _line(lines, "[KeyRXPanelClick]")
    _line(lines, "condition = $rx_ui_open == 1 && $rx_ui_hover > 1 && $rx_ui_hover < 24")
    _line(lines, "key = no_ctrl no_shift VK_LBUTTON")
    _line(lines, "run = CommandListRXPanelClick")
    _line(lines)
    _line(lines, "[KeyRXPlayPause]")
    _line(lines, "key = ctrl alt VK_SPACE")
    _line(lines, "run = CommandListRXTogglePlay")
    _line(lines)
    _line(lines, "[KeyRXReplay]")
    _line(lines, "key = ctrl alt r")
    _line(lines, "run = CommandListRXReplayAnimation")
    _line(lines)
    _line(lines, "[KeyRXNextAction]")
    _line(lines, "key = ctrl alt n")
    _line(lines, "run = CommandListRXNextAction")
    _line(lines)
    _line(lines, "[KeyRXSpeed]")
    _line(lines, "key = ctrl alt s")
    _line(lines, "run = CommandListRXCycleAnimationSpeed")
    _line(lines)
    for action_index in range(4):
        _line(lines, f"[KeyRXAction{action_index + 1}]")
        _line(lines, f"key = ctrl alt {action_index + 1}")
        _line(lines, f"run = CommandListRXSelectAction{action_index}")
        _line(lines)
    _line(lines, "[CommandListRXTogglePlay]")
    _line(lines, "$rx_anim_play = 1 - $rx_anim_play")
    _line(lines)
    _line(lines, "[CommandListRXReplayAnimation]")
    _line(lines, "$rx_anim_control_value = 1")
    _line(lines, "$rx_anim_control_token = $rx_anim_control_token + 1")
    _line(lines)
    _line(lines, "[CommandListRXNextAction]")
    _line(lines, "$rx_anim_action_index = $rx_anim_action_index + 1")
    _line(lines, "if $rx_anim_action_index >= $rx_anim_action_count")
    _line(lines, "    $rx_anim_action_index = 0")
    _line(lines, "endif")
    _line(lines, "$rx_anim_control_value = 2")
    _line(lines, "$rx_anim_control_token = $rx_anim_control_token + 1")
    _line(lines)
    _line(lines, "[CommandListRXCycleAnimationSpeed]")
    _line(lines, "$rx_anim_speed = $rx_anim_speed + 1")
    _line(lines, "if $rx_anim_speed > 6")
    _line(lines, "    $rx_anim_speed = 1")
    _line(lines, "endif")
    _line(lines)
    for action_index in range(4):
        _append_select_action_command(lines, action_index)

    _line(lines, "[ResourceRXPanelState_UAV]")
    _line(lines, "type = RWStructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, "array = 1")
    _line(lines)
    _line(lines, "[ResourceRXPanelState_SRV]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, "array = 1")
    _line(lines)
    for resource_name, file_name in (
        ("ResourceRXPanelBG", "panel_bg.dds"),
        ("ResourceRXTitleBadge", "title_badge.dds"),
        ("ResourceRXTabControls", "tab_controls.dds"),
        ("ResourceRXTabControlsActive", "tab_controls_active.dds"),
        ("ResourceRXTabHotkeys", "tab_hotkeys.dds"),
        ("ResourceRXTabHotkeysActive", "tab_hotkeys_active.dds"),
        ("ResourceRXTabActions", "tab_actions.dds"),
        ("ResourceRXTabActionsActive", "tab_actions_active.dds"),
        ("ResourceRXBtnPlay", "btn_play.dds"),
        ("ResourceRXBtnPlayHover", "btn_play_hover.dds"),
        ("ResourceRXBtnPause", "btn_pause.dds"),
        ("ResourceRXBtnPauseHover", "btn_pause_hover.dds"),
        ("ResourceRXBtnReplay", "btn_replay.dds"),
        ("ResourceRXBtnReplayHover", "btn_replay_hover.dds"),
        ("ResourceRXBtnNextAction", "btn_next_action.dds"),
        ("ResourceRXBtnNextActionHover", "btn_next_action_hover.dds"),
        ("ResourceRXBtnSpeed", "btn_speed.dds"),
        ("ResourceRXBtnSpeedHover", "btn_speed_hover.dds"),
        ("ResourceRXBtnAction", "btn_action.dds"),
        ("ResourceRXBtnActionHover", "btn_action_hover.dds"),
        ("ResourceRXProgressTrack", "progress_track.dds"),
        ("ResourceRXProgressFill", "progress_fill.dds"),
        ("ResourceRXProgressHandle", "progress_handle.dds"),
        ("ResourceRXWatermark", "watermark_patreon.dds"),
        ("ResourceRXHotkeysPage", "hotkeys_page.dds"),
        ("ResourceRXActionPage", "actions_page.dds"),
        ("ResourceRXDigitsAtlas", "digits_atlas.dds"),
    ):
        _append_ui_resource(lines, resource_name, file_name)

    _line(lines, "[CustomShader_RXPanelSprite]")
    _line(lines, "vs = hlsl\\panel_sprite.hlsl")
    _line(lines, "ps = hlsl\\panel_sprite.hlsl")
    _line(lines, "cull = none")
    _line(lines, "blend = ADD SRC_ALPHA INV_SRC_ALPHA")
    _line(lines, "topology = triangle_strip")
    _line(lines, "o0 = set_viewport bb")
    _line(lines, "draw = 4, 0")
    _line(lines, "ps-t100 = null")
    _line(lines)
    _line(lines, "[CustomShader_RXPanelDigits]")
    _line(lines, "vs = hlsl\\panel_digits.hlsl")
    _line(lines, "ps = hlsl\\panel_digits.hlsl")
    _line(lines, "cull = none")
    _line(lines, "blend = ADD SRC_ALPHA INV_SRC_ALPHA")
    _line(lines, "topology = triangle_strip")
    _line(lines, "o0 = set_viewport bb")
    _line(lines, "draw = 4, 0")
    _line(lines, "ps-t100 = null")
    _line(lines)
    _line(lines, "[CustomShader_UpdateRXPanelState]")
    _line(lines, "cs = hlsl\\update_rx_panel_state_cs.hlsl")
    _line(lines, "dispatch = 1, 1, 1")
    _line(lines, "ResourceRXPanelState_SRV = copy ResourceRXPanelState_UAV")
    _line(lines)
    _line(lines, "[CommandListRXUIPresent]")
    _line(lines, "cs-t0 = ResourceTimelineStatic")
    _line(lines, "cs-t1 = ResourceMasterPlayback_SRV")
    _line(lines, "cs-u0 = ResourceRXPanelState_UAV")
    _line(lines, "run = CustomShader_UpdateRXPanelState")
    _line(lines, "cs-t0 = null")
    _line(lines, "cs-t1 = null")
    _line(lines, "cs-u0 = null")
    _line(lines, "if $rx_ui_open == 1")
    _line(lines, "    run = CommandListRXPanelFrame")
    _line(lines, "else")
    _line(lines, "    $rx_ui_hover = 0")
    _line(lines, "    $rx_ui_drag = 0")
    _line(lines, "    $rx_ui_seek_hold = 0")
    _line(lines, "    $rx_anim_seek_active = 0")
    _line(lines, "endif")
    _line(lines)
    _line(lines, "[CommandListRXPanelResolveCursor]")
    _line(lines, "local $ww = window_width")
    _line(lines, "local $wh = window_height")
    _line(lines, "if $ww == 0")
    _line(lines, "    if rt_width != 0")
    _line(lines, "        $ww = rt_width")
    _line(lines, "        $wh = rt_height")
    _line(lines, "    else")
    _line(lines, "        $ww = res_width")
    _line(lines, "        $wh = res_height")
    _line(lines, "    endif")
    _line(lines, "endif")
    _line(lines, "if cursor_x > 0 && cursor_x < 1 && cursor_y > 0 && cursor_y < 1")
    _line(lines, "    $rx_ui_cursor_x = cursor_x")
    _line(lines, "    $rx_ui_cursor_y = cursor_y")
    _line(lines, "elif $ww > 0 && cursor_window_x > 0 && cursor_window_x < $ww && cursor_window_y > 0 && cursor_window_y < $wh")
    _line(lines, "    $rx_ui_cursor_x = cursor_window_x / $ww")
    _line(lines, "    $rx_ui_cursor_y = cursor_window_y / $wh")
    _line(lines, "else")
    _line(lines, "    $rx_ui_cursor_x = cursor_screen_x / $ww")
    _line(lines, "    $rx_ui_cursor_y = cursor_screen_y / $wh")
    _line(lines, "endif")
    _line(lines)
    _line(lines, "[CommandListRXPanelInput]")
    _line(lines, "run = CommandListRXPanelResolveCursor")
    _line(lines, "local $ww = window_width")
    _line(lines, "local $wh = window_height")
    _line(lines, "if $ww == 0")
    _line(lines, "    if rt_width != 0")
    _line(lines, "        $ww = rt_width")
    _line(lines, "        $wh = rt_height")
    _line(lines, "    else")
    _line(lines, "        $ww = res_width")
    _line(lines, "        $wh = res_height")
    _line(lines, "    endif")
    _line(lines, "endif")
    _line(lines, "local $aspect_fix = 1.0")
    _line(lines, "if $ww > 0")
    _line(lines, "    $aspect_fix = $wh / $ww")
    _line(lines, "endif")
    _line(lines, "local $panel_h = 0.38")
    _line(lines, "local $panel_w = $panel_h * 1024.0 / 756.0 * $aspect_fix")
    _line(lines, "local $title_h = 0.04")
    _line(lines, "local $inner_x = $rx_ui_x + 0.02")
    _line(lines, "local $inner_w = $panel_w - 0.04")
    _line(lines, "local $tab_gap = 0.010")
    _line(lines, "local $button_gap = 0.008")
    _line(lines, "local $tab_y = $rx_ui_y + $title_h + 0.01")
    _line(lines, "local $tab_w = ($inner_w - $tab_gap * 2.0) / 3.0")
    _line(lines, "local $tab_h = $tab_w / (260.0 / 56.0 * $aspect_fix)")
    _line(lines, "local $button_y = $tab_y + $tab_h + 0.02")
    _line(lines, "local $button_w = ($inner_w - $button_gap * 3.0) / 4.0")
    _line(lines, "local $button_h = $button_w / (180.0 / 72.0 * $aspect_fix)")
    _line(lines, "local $play_x = $inner_x")
    _line(lines, "local $replay_x = $play_x + $button_w + $button_gap")
    _line(lines, "local $next_x = $replay_x + $button_w + $button_gap")
    _line(lines, "local $speed_x = $next_x + $button_w + $button_gap")
    _line(lines, "local $bar_x = $inner_x")
    _line(lines, "local $bar_y = $button_y + $button_h + 0.025")
    _line(lines, "local $bar_w = $inner_w")
    _line(lines, "local $bar_h = $bar_w * 56.0 / 1024.0 / $aspect_fix")
    _line(lines, "local $action_gap = 0.006")
    _line(lines, "local $action_button_w = $inner_w * 0.33")
    _line(lines, "local $action_button_h = $action_button_w / (360.0 / 72.0 * $aspect_fix)")
    _line(lines, "local $action_x0 = $inner_x + 0.014")
    _line(lines, "local $action_y0 = $rx_ui_y + 0.142")
    _line(lines, "local $action_y1 = $action_y0 + $action_button_h + $action_gap")
    _line(lines, "local $action_y2 = $action_y1 + $action_button_h + $action_gap")
    _line(lines, "local $action_y3 = $action_y2 + $action_button_h + $action_gap")
    _line(lines)
    _line(lines, "if $rx_ui_drag == 1")
    _line(lines, "    if $rx_ui_hold == 1")
    _line(lines, "        $rx_ui_x = $rx_ui_cursor_x - $rx_ui_drag_dx")
    _line(lines, "        $rx_ui_y = $rx_ui_cursor_y - $rx_ui_drag_dy")
    _line(lines, "        if $rx_ui_x < 0.01")
    _line(lines, "            $rx_ui_x = 0.01")
    _line(lines, "        endif")
    _line(lines, "        if $rx_ui_y < 0.01")
    _line(lines, "            $rx_ui_y = 0.01")
    _line(lines, "        endif")
    _line(lines, "        if $rx_ui_x > 0.99 - $panel_w")
    _line(lines, "            $rx_ui_x = 0.99 - $panel_w")
    _line(lines, "        endif")
    _line(lines, "        if $rx_ui_y > 0.99 - $panel_h")
    _line(lines, "            $rx_ui_y = 0.99 - $panel_h")
    _line(lines, "        endif")
    _line(lines, "    else")
    _line(lines, "        $rx_ui_drag = 0")
    _line(lines, "    endif")
    _line(lines, "endif")
    _line(lines)
    _line(lines, "$rx_ui_hover = 0")
    _line(lines, "if $rx_ui_drag == 0 && $rx_ui_seek_hold == 0")
    _line(lines, "    if $rx_ui_cursor_x > $rx_ui_x && $rx_ui_cursor_x < $rx_ui_x + $panel_w && $rx_ui_cursor_y > $rx_ui_y && $rx_ui_cursor_y < $rx_ui_y + $title_h")
    _line(lines, "        $rx_ui_hover = 1")
    _line(lines, "    elif $rx_ui_cursor_x > $inner_x && $rx_ui_cursor_x < $inner_x + $tab_w && $rx_ui_cursor_y > $tab_y && $rx_ui_cursor_y < $tab_y + $tab_h")
    _line(lines, "        $rx_ui_hover = 2")
    _line(lines, "    elif $rx_ui_cursor_x > $inner_x + $tab_w + $tab_gap && $rx_ui_cursor_x < $inner_x + $tab_w + $tab_gap + $tab_w && $rx_ui_cursor_y > $tab_y && $rx_ui_cursor_y < $tab_y + $tab_h")
    _line(lines, "        $rx_ui_hover = 3")
    _line(lines, "    elif $rx_ui_cursor_x > $inner_x + ($tab_w + $tab_gap) * 2.0 && $rx_ui_cursor_x < $inner_x + ($tab_w + $tab_gap) * 2.0 + $tab_w && $rx_ui_cursor_y > $tab_y && $rx_ui_cursor_y < $tab_y + $tab_h")
    _line(lines, "        $rx_ui_hover = 4")
    _line(lines, "    elif $rx_ui_tab == 0 && $rx_ui_cursor_x > $play_x && $rx_ui_cursor_x < $play_x + $button_w && $rx_ui_cursor_y > $button_y && $rx_ui_cursor_y < $button_y + $button_h")
    _line(lines, "        $rx_ui_hover = 5")
    _line(lines, "    elif $rx_ui_tab == 0 && $rx_ui_cursor_x > $replay_x && $rx_ui_cursor_x < $replay_x + $button_w && $rx_ui_cursor_y > $button_y && $rx_ui_cursor_y < $button_y + $button_h")
    _line(lines, "        $rx_ui_hover = 6")
    _line(lines, "    elif $rx_ui_tab == 0 && $rx_ui_cursor_x > $next_x && $rx_ui_cursor_x < $next_x + $button_w && $rx_ui_cursor_y > $button_y && $rx_ui_cursor_y < $button_y + $button_h")
    _line(lines, "        $rx_ui_hover = 7")
    _line(lines, "    elif $rx_ui_tab == 0 && $rx_ui_cursor_x > $speed_x && $rx_ui_cursor_x < $speed_x + $button_w && $rx_ui_cursor_y > $button_y && $rx_ui_cursor_y < $button_y + $button_h")
    _line(lines, "        $rx_ui_hover = 8")
    _line(lines, "    elif $rx_ui_tab == 0 && $rx_ui_cursor_x > $bar_x && $rx_ui_cursor_x < $bar_x + $bar_w && $rx_ui_cursor_y > $bar_y && $rx_ui_cursor_y < $bar_y + $bar_h")
    _line(lines, "        $rx_ui_hover = 9")
    for action_index, (x_name, y_name) in enumerate((
        ("$action_x0", "$action_y0"),
        ("$action_x0", "$action_y1"),
        ("$action_x0", "$action_y2"),
        ("$action_x0", "$action_y3"),
    )):
        _line(lines, f"    elif $rx_ui_tab == 2 && $rx_anim_action_count > {action_index} && $rx_ui_cursor_x > {x_name} && $rx_ui_cursor_x < {x_name} + $action_button_w && $rx_ui_cursor_y > {y_name} && $rx_ui_cursor_y < {y_name} + $action_button_h")
        _line(lines, f"        $rx_ui_hover = {20 + action_index}")
    _line(lines, "    endif")
    _line(lines, "endif")
    _line(lines)
    _line(lines, "if $rx_ui_drag == 0 && $rx_ui_seek_hold == 0 && $rx_ui_hold == 1 && $rx_ui_hover == 1")
    _line(lines, "    $rx_ui_drag = 1")
    _line(lines, "    $rx_ui_drag_dx = $rx_ui_cursor_x - $rx_ui_x")
    _line(lines, "    $rx_ui_drag_dy = $rx_ui_cursor_y - $rx_ui_y")
    _line(lines, "endif")
    _line(lines)
    _line(lines, "if $rx_ui_seek_hold == 1")
    _line(lines, "    if $rx_ui_hold == 1")
    _line(lines, "        $rx_anim_seek_norm = ($rx_ui_cursor_x - $bar_x) / $bar_w")
    _line(lines, "        if $rx_anim_seek_norm < 0")
    _line(lines, "            $rx_anim_seek_norm = 0")
    _line(lines, "        endif")
    _line(lines, "        if $rx_anim_seek_norm > 1")
    _line(lines, "            $rx_anim_seek_norm = 1")
    _line(lines, "        endif")
    _line(lines, "        $rx_anim_seek_active = 1")
    _line(lines, "        $rx_ui_hover = 9")
    _line(lines, "    else")
    _line(lines, "        $rx_ui_seek_hold = 0")
    _line(lines, "        $rx_anim_seek_active = 0")
    _line(lines, "    endif")
    _line(lines, "elif $rx_ui_drag == 0 && $rx_ui_hold == 1 && $rx_ui_hover == 9")
    _line(lines, "    $rx_ui_seek_hold = 1")
    _line(lines, "    $rx_anim_seek_norm = ($rx_ui_cursor_x - $bar_x) / $bar_w")
    _line(lines, "    if $rx_anim_seek_norm < 0")
    _line(lines, "        $rx_anim_seek_norm = 0")
    _line(lines, "    endif")
    _line(lines, "    if $rx_anim_seek_norm > 1")
    _line(lines, "        $rx_anim_seek_norm = 1")
    _line(lines, "    endif")
    _line(lines, "    $rx_anim_seek_active = 1")
    _line(lines, "else")
    _line(lines, "    $rx_anim_seek_active = 0")
    _line(lines, "endif")
    _line(lines)
    _line(lines, "[CommandListRXPanelClick]")
    _line(lines, "if $rx_ui_hover == 2")
    _line(lines, "    $rx_ui_tab = 0")
    _line(lines, "elif $rx_ui_hover == 3")
    _line(lines, "    $rx_ui_tab = 1")
    _line(lines, "elif $rx_ui_hover == 4")
    _line(lines, "    $rx_ui_tab = 2")
    _line(lines, "elif $rx_ui_hover == 5")
    _line(lines, "    $rx_anim_play = 1 - $rx_anim_play")
    _line(lines, "elif $rx_ui_hover == 6")
    _line(lines, "    run = CommandListRXReplayAnimation")
    _line(lines, "elif $rx_ui_hover == 7")
    _line(lines, "    run = CommandListRXNextAction")
    _line(lines, "elif $rx_ui_hover == 8")
    _line(lines, "    run = CommandListRXCycleAnimationSpeed")
    for action_index in range(4):
        _line(lines, f"elif $rx_ui_hover == {20 + action_index}")
        _line(lines, f"    run = CommandListRXSelectAction{action_index}")
    _line(lines, "endif")
    _line(lines)

    _append_ui_draw_command(lines, action_button_count)
    _append_ui_frame_command(lines)
    return "\n".join(lines).rstrip() + "\n"


def _append_ui_draw_command(lines: list[str], action_button_count: int):
    _line(lines, "[CommandListRXPanelDraw]")
    _line(lines, "local $ww = window_width")
    _line(lines, "local $wh = window_height")
    _line(lines, "if $ww == 0")
    _line(lines, "    if rt_width != 0")
    _line(lines, "        $ww = rt_width")
    _line(lines, "        $wh = rt_height")
    _line(lines, "    else")
    _line(lines, "        $ww = res_width")
    _line(lines, "        $wh = res_height")
    _line(lines, "    endif")
    _line(lines, "endif")
    _line(lines, "local $aspect_fix = 1.0")
    _line(lines, "if $ww > 0")
    _line(lines, "    $aspect_fix = $wh / $ww")
    _line(lines, "endif")
    _line(lines, "local $panel_h = 0.38")
    _line(lines, "local $panel_w = $panel_h * 1024.0 / 756.0 * $aspect_fix")
    _line(lines, "local $title_h = 0.04")
    _line(lines, "local $inner_x = $rx_ui_x + 0.02")
    _line(lines, "local $inner_w = $panel_w - 0.04")
    _line(lines, "local $tab_gap = 0.010")
    _line(lines, "local $button_gap = 0.008")
    _line(lines, "local $tab_y = $rx_ui_y + $title_h + 0.01")
    _line(lines, "local $tab_w = ($inner_w - $tab_gap * 2.0) / 3.0")
    _line(lines, "local $tab_h = $tab_w / (260.0 / 56.0 * $aspect_fix)")
    _line(lines, "local $button_y = $tab_y + $tab_h + 0.02")
    _line(lines, "local $button_w = ($inner_w - $button_gap * 3.0) / 4.0")
    _line(lines, "local $button_h = $button_w / (180.0 / 72.0 * $aspect_fix)")
    _line(lines, "local $play_x = $inner_x")
    _line(lines, "local $replay_x = $play_x + $button_w + $button_gap")
    _line(lines, "local $next_x = $replay_x + $button_w + $button_gap")
    _line(lines, "local $speed_x = $next_x + $button_w + $button_gap")
    _line(lines, "local $bar_x = $inner_x")
    _line(lines, "local $bar_y = $button_y + $button_h + 0.025")
    _line(lines, "local $bar_w = $inner_w")
    _line(lines, "local $bar_h = $bar_w * 56.0 / 1024.0 / $aspect_fix")
    _line(lines, "local $handle_h = 0.018")
    _line(lines, "local $handle_w = $handle_h * $aspect_fix")
    _line(lines, "local $handle_half_norm = $handle_w / (2.0 * $bar_w)")
    _line(lines, "local $hotkeys_h = $inner_w * 400.0 / 940.0 / $aspect_fix")
    _line(lines, "local $digit_h = $button_h * 0.42")
    _line(lines, "local $digit_w = $digit_h * 48.0 / 64.0 * $aspect_fix")
    _line(lines, "local $digit_x = $speed_x + $button_w - $digit_w - 0.006")
    _line(lines, "local $digit_y = $button_y + ($button_h - $digit_h) * 0.5")
    _line(lines, "local $watermark_h = 0.035")
    _line(lines, "local $watermark_w = $watermark_h * 1024.0 / 64.0 * $aspect_fix")
    _line(lines, "local $watermark_x = $inner_x + ($inner_w - $watermark_w) * 0.5")
    _line(lines, "local $watermark_y = $bar_y + $bar_h + 0.014")
    _line(lines, "local $action_gap = 0.006")
    _line(lines, "local $action_button_w = $inner_w * 0.33")
    _line(lines, "local $action_button_h = $action_button_w / (360.0 / 72.0 * $aspect_fix)")
    _line(lines, "local $action_digit_h = $action_button_h * 0.42")
    _line(lines, "local $action_digit_w = $action_digit_h * 48.0 / 64.0 * $aspect_fix")
    _line(lines, "local $action_x0 = $inner_x + 0.014")
    _line(lines, "local $action_y0 = $rx_ui_y + 0.142")
    _line(lines, "local $action_y1 = $action_y0 + $action_button_h + $action_gap")
    _line(lines, "local $action_y2 = $action_y1 + $action_button_h + $action_gap")
    _line(lines, "local $action_y3 = $action_y2 + $action_button_h + $action_gap")
    _line(lines)
    _line(lines, "x89 = 1.0")
    _line(lines, "y89 = 1.0")
    _line(lines, "z89 = 1.0")
    _line(lines, "w89 = 1.0")
    _line(lines, "ps-t101 = ResourceRXPanelState_SRV")
    _line(lines, "x2 = $rx_anim_seek_norm")
    _line(lines, "y2 = $rx_anim_seek_active")
    _line(lines, "z2 = 0")
    _line(lines, "w2 = 0")
    _line(lines)
    _line(lines, "x87 = $panel_w")
    _line(lines, "y87 = $panel_h")
    _line(lines, "z87 = $rx_ui_x")
    _line(lines, "w87 = $rx_ui_y")
    _line(lines, "x88 = 0")
    _line(lines, "y88 = 0")
    _line(lines, "ps-t100 = ResourceRXPanelBG")
    _line(lines, "run = CustomShader_RXPanelSprite")
    _line(lines)
    _line(lines, "x87 = 0.028 * 360.0 / 56.0 * $aspect_fix")
    _line(lines, "y87 = 0.028")
    _line(lines, "z87 = $rx_ui_x + 0.018")
    _line(lines, "w87 = $rx_ui_y + 0.008")
    _line(lines, "x88 = 0")
    _line(lines, "ps-t100 = ResourceRXTitleBadge")
    _line(lines, "run = CustomShader_RXPanelSprite")
    _line(lines)
    for tab_index, (name, hover, resource, active_resource) in enumerate(
        (
            ("controls", 2, "ResourceRXTabControls", "ResourceRXTabControlsActive"),
            ("hotkeys", 3, "ResourceRXTabHotkeys", "ResourceRXTabHotkeysActive"),
            ("actions", 4, "ResourceRXTabActions", "ResourceRXTabActionsActive"),
        )
    ):
        del name
        x_expr = "$inner_x" if tab_index == 0 else f"$inner_x + ($tab_w + $tab_gap) * {float(tab_index):.1f}"
        _line(lines, "x87 = $tab_w")
        _line(lines, "y87 = $tab_h")
        _line(lines, f"z87 = {x_expr}")
        _line(lines, "w87 = $tab_y")
        _line(lines, "x88 = 0")
        _line(lines, f"if $rx_ui_tab == {tab_index} || $rx_ui_hover == {hover}")
        _line(lines, f"    ps-t100 = {active_resource}")
        _line(lines, "else")
        _line(lines, f"    ps-t100 = {resource}")
        _line(lines, "endif")
        _line(lines, "run = CustomShader_RXPanelSprite")
        _line(lines)
    _line(lines, "if $rx_ui_tab == 0")
    for button_resource, hover_resource, hover_code, x_name in (
        ("ResourceRXBtnPause", "ResourceRXBtnPauseHover", 5, "$play_x"),
        ("ResourceRXBtnReplay", "ResourceRXBtnReplayHover", 6, "$replay_x"),
        ("ResourceRXBtnNextAction", "ResourceRXBtnNextActionHover", 7, "$next_x"),
        ("ResourceRXBtnSpeed", "ResourceRXBtnSpeedHover", 8, "$speed_x"),
    ):
        _line(lines, "    x87 = $button_w")
        _line(lines, "    y87 = $button_h")
        _line(lines, f"    z87 = {x_name}")
        _line(lines, "    w87 = $button_y")
        _line(lines, "    x88 = 0")
        if hover_code == 5:
            _line(lines, "    if $rx_anim_play == 1")
            _line(lines, "        if $rx_ui_hover == 5")
            _line(lines, "            ps-t100 = ResourceRXBtnPauseHover")
            _line(lines, "        else")
            _line(lines, "            ps-t100 = ResourceRXBtnPause")
            _line(lines, "        endif")
            _line(lines, "    else")
            _line(lines, "        if $rx_ui_hover == 5")
            _line(lines, "            ps-t100 = ResourceRXBtnPlayHover")
            _line(lines, "        else")
            _line(lines, "            ps-t100 = ResourceRXBtnPlay")
            _line(lines, "        endif")
            _line(lines, "    endif")
        else:
            _line(lines, f"    if $rx_ui_hover == {hover_code}")
            _line(lines, f"        ps-t100 = {hover_resource}")
            _line(lines, "    else")
            _line(lines, f"        ps-t100 = {button_resource}")
            _line(lines, "    endif")
        _line(lines, "    run = CustomShader_RXPanelSprite")
        _line(lines)
    _line(lines, "    x87 = $digit_w")
    _line(lines, "    y87 = $digit_h")
    _line(lines, "    z87 = $digit_x")
    _line(lines, "    w87 = $digit_y")
    _line(lines, "    x88 = 0")
    _line(lines, "    ps-t100 = ResourceRXDigitsAtlas")
    _line(lines, "    run = CustomShader_RXPanelDigits")
    _line(lines)
    _line(lines, "    x87 = $bar_w")
    _line(lines, "    y87 = $bar_h")
    _line(lines, "    z87 = $bar_x")
    _line(lines, "    w87 = $bar_y")
    _line(lines, "    x88 = 0")
    _line(lines, "    ps-t100 = ResourceRXProgressTrack")
    _line(lines, "    run = CustomShader_RXPanelSprite")
    _line(lines)
    _line(lines, "    x87 = $bar_w")
    _line(lines, "    y87 = $bar_h")
    _line(lines, "    z87 = $bar_x")
    _line(lines, "    w87 = $bar_y")
    _line(lines, "    x88 = 1")
    _line(lines, "    y88 = 0")
    _line(lines, "    ps-t100 = ResourceRXProgressFill")
    _line(lines, "    run = CustomShader_RXPanelSprite")
    _line(lines)
    _line(lines, "    x87 = $bar_w")
    _line(lines, "    y87 = $handle_h")
    _line(lines, "    z87 = $bar_x")
    _line(lines, "    w87 = $bar_y + 0.0003")
    _line(lines, "    x88 = 2")
    _line(lines, "    y88 = $handle_half_norm")
    _line(lines, "    ps-t100 = ResourceRXProgressHandle")
    _line(lines, "    run = CustomShader_RXPanelSprite")
    _line(lines)
    _line(lines, "    x87 = $watermark_w")
    _line(lines, "    y87 = $watermark_h")
    _line(lines, "    z87 = $watermark_x")
    _line(lines, "    w87 = $watermark_y")
    _line(lines, "    x88 = 0")
    _line(lines, "    w89 = 0.82")
    _line(lines, "    ps-t100 = ResourceRXWatermark")
    _line(lines, "    run = CustomShader_RXPanelSprite")
    _line(lines, "    w89 = 1.0")
    _line(lines, "elif $rx_ui_tab == 1")
    _line(lines, "    x87 = $inner_w")
    _line(lines, "    y87 = $hotkeys_h")
    _line(lines, "    z87 = $inner_x")
    _line(lines, "    w87 = $rx_ui_y + 0.095")
    _line(lines, "    x88 = 0")
    _line(lines, "    ps-t100 = ResourceRXHotkeysPage")
    _line(lines, "    run = CustomShader_RXPanelSprite")
    _line(lines, "else")
    _line(lines, "    x87 = $inner_w")
    _line(lines, "    y87 = $hotkeys_h")
    _line(lines, "    z87 = $inner_x")
    _line(lines, "    w87 = $rx_ui_y + 0.095")
    _line(lines, "    x88 = 0")
    _line(lines, "    ps-t100 = ResourceRXActionPage")
    _line(lines, "    run = CustomShader_RXPanelSprite")
    for action_index, (x_name, y_name) in enumerate((
        ("$action_x0", "$action_y0"),
        ("$action_x0", "$action_y1"),
        ("$action_x0", "$action_y2"),
        ("$action_x0", "$action_y3"),
    )):
        if action_index >= action_button_count:
            continue
        hover_code = 20 + action_index
        _line(lines, f"    if $rx_anim_action_count > {action_index}")
        _line(lines, "        x87 = $action_button_w")
        _line(lines, "        y87 = $action_button_h")
        _line(lines, f"        z87 = {x_name}")
        _line(lines, f"        w87 = {y_name}")
        _line(lines, "        x88 = 0")
        _line(lines, f"        if $rx_ui_hover == {hover_code} || $rx_anim_action_index == {action_index}")
        _line(lines, "            ps-t100 = ResourceRXBtnActionHover")
        _line(lines, "        else")
        _line(lines, "            ps-t100 = ResourceRXBtnAction")
        _line(lines, "        endif")
        _line(lines, "        run = CustomShader_RXPanelSprite")
        _line(lines, "        x87 = $action_digit_w")
        _line(lines, "        y87 = $action_digit_h")
        _line(lines, f"        z87 = {x_name} + $action_button_w - $action_digit_w - 0.010")
        _line(lines, f"        w87 = {y_name} + ($action_button_h - $action_digit_h) * 0.5")
        _line(lines, "        x88 = 1")
        _line(lines, f"        y88 = {action_index + 1}")
        _line(lines, "        ps-t100 = ResourceRXDigitsAtlas")
        _line(lines, "        run = CustomShader_RXPanelDigits")
        _line(lines, "    endif")
    _line(lines, "endif")
    _line(lines)


def _append_ui_frame_command(lines: list[str]):
    _line(lines, "[CommandListRXPanelFrame]")
    for name in ("x87", "y87", "z87", "w87", "x2", "y2", "z2", "w2", "x88", "y88", "z88", "w88", "x89", "y89", "z89", "w89", "x90", "y90", "z90", "w90"):
        _line(lines, f"local $bak_{name} = {name}")
    _line(lines, "run = CommandListRXPanelInput")
    _line(lines, "run = CommandListRXPanelDraw")
    _line(lines, "ps-t100 = null")
    _line(lines, "ps-t101 = null")
    for name in ("x87", "y87", "z87", "w87", "x2", "y2", "z2", "w2", "x88", "y88", "z88", "w88", "x89", "y89", "z89", "w89", "x90", "y90", "z90", "w90"):
        _line(lines, f"{name} = $bak_{name}")


def _copy_ui_asset_if_possible(ui_dir: str, target_name: str, fallback_name: str):
    target_path = os.path.join(ui_dir, target_name)
    if os.path.exists(target_path):
        return
    fallback_path = os.path.join(ui_dir, fallback_name)
    if os.path.exists(fallback_path):
        shutil.copyfile(fallback_path, target_path)


def write_runtime_ui_assets(output_directory: str):
    ui_dir = os.path.join(os.path.abspath(output_directory or "."), "ui")
    os.makedirs(ui_dir, exist_ok=True)
    generated = False
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

        def font(size: int):
            for path in (
                r"C:\Windows\Fonts\bahnschrift.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\seguisb.ttf",
                r"C:\Windows\Fonts\segoeui.ttf",
                r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\arial.ttf",
            ):
                if os.path.exists(path):
                    return ImageFont.truetype(path, size)
            return ImageFont.load_default()

        neon_blue = (72, 236, 255, 255)
        neon_purple = (132, 86, 255, 255)
        neon_pink = (255, 82, 218, 255)
        neon_gold = (255, 206, 82, 255)
        neon_stops = (neon_blue, neon_purple, neon_pink, neon_gold, neon_blue)
        amber_soft = (214, 146, 40, 205)
        cyan = neon_blue
        cyan_dim = (36, 136, 168, 205)
        glass_light = (26, 30, 45, 190)
        text_main = (250, 250, 255, 255)
        text_muted = (182, 190, 216, 235)

        def text_center(draw, rect, text, text_font, fill=text_main):
            bbox = draw.textbbox((0, 0), text, font=text_font)
            x = rect[0] + (rect[2] - rect[0] - (bbox[2] - bbox[0])) * 0.5 - bbox[0]
            y = rect[1] + (rect[3] - rect[1] - (bbox[3] - bbox[1])) * 0.5 - bbox[1]
            draw.text((x, y), text, font=text_font, fill=fill)

        def text_left(draw, xy, text, text_font, fill=text_main):
            draw.text(xy, text, font=text_font, fill=fill)

        def save(image: Image.Image, file_name: str):
            image.save(os.path.join(ui_dir, file_name))

        def lerp_channel(a: int, b: int, t: float) -> int:
            return int(a + (b - a) * t)

        def lerp_color(a: tuple[int, int, int, int], b: tuple[int, int, int, int], t: float) -> tuple[int, int, int, int]:
            return (
                lerp_channel(a[0], b[0], t),
                lerp_channel(a[1], b[1], t),
                lerp_channel(a[2], b[2], t),
                lerp_channel(a[3], b[3], t),
            )

        def spectrum_color(t: float) -> tuple[int, int, int, int]:
            t = t % 1.0
            scaled = t * (len(neon_stops) - 1)
            index = min(int(scaled), len(neon_stops) - 2)
            return lerp_color(neon_stops[index], neon_stops[index + 1], scaled - index)

        def neon_gradient(size: tuple[int, int], offset: float = 0.0) -> Image.Image:
            width, height = size
            image = Image.new("RGBA", size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            denom = max(width + height, 1)
            for x in range(width):
                color = spectrum_color((x + height * 0.35) / denom + offset)
                draw.line((x, 0, x, height), fill=color)
            return image

        def rounded_mask(size: tuple[int, int], rect: tuple[int, int, int, int], radius: int) -> Image.Image:
            mask = Image.new("L", size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle(rect, radius=radius, fill=255)
            return mask

        def neon_card(
            size: tuple[int, int],
            fill: tuple[int, int, int, int],
            radius: int = 22,
            border: int = 4,
            glow: int = 16,
            offset: float = 0.0,
            shine: bool = True,
        ) -> Image.Image:
            width, height = size
            margin = max(glow + border, 8)
            outer_rect = (margin, margin, width - margin - 1, height - margin - 1)
            inner_rect = (
                margin + border,
                margin + border,
                width - margin - border - 1,
                height - margin - border - 1,
            )
            outer = rounded_mask(size, outer_rect, radius)
            inner = rounded_mask(size, inner_rect, max(radius - border, 1))
            border_mask = ImageChops.subtract(outer, inner)
            gradient = neon_gradient(size, offset)

            image = Image.new("RGBA", size, (0, 0, 0, 0))
            for blur, alpha_scale in ((glow, 0.34), (max(glow // 2, 1), 0.50), (max(glow // 4, 1), 0.78)):
                glow_mask = border_mask.filter(ImageFilter.GaussianBlur(blur))
                glow_mask = glow_mask.point(lambda value, scale=alpha_scale: int(value * scale))
                glow_layer = gradient.copy()
                glow_layer.putalpha(glow_mask)
                image.alpha_composite(glow_layer)

            fill_layer = Image.new("RGBA", size, (0, 0, 0, 0))
            fill_draw = ImageDraw.Draw(fill_layer)
            fill_draw.rounded_rectangle(inner_rect, radius=max(radius - border, 1), fill=fill)
            if shine:
                fill_draw.rounded_rectangle(
                    (inner_rect[0] + 8, inner_rect[1] + 8, inner_rect[2] - 8, inner_rect[1] + max(10, height // 6)),
                    radius=max(radius // 2, 1),
                    fill=(255, 255, 255, 18),
                )
            image.alpha_composite(fill_layer)

            border_layer = gradient.copy()
            border_layer.putalpha(border_mask)
            image.alpha_composite(border_layer)

            detail = ImageDraw.Draw(image)
            for dash in range(0, width, 84):
                x0 = dash + int((width * offset) % 84)
                detail.line(
                    (x0, margin + 2, min(x0 + 34, width - margin - 2), margin + 2),
                    fill=(255, 255, 255, 130),
                    width=1,
                )
            return image

        def paste_neon_card(
            base: Image.Image,
            xy: tuple[int, int],
            size: tuple[int, int],
            fill: tuple[int, int, int, int],
            radius: int = 20,
            border: int = 3,
            glow: int = 10,
            offset: float = 0.0,
        ):
            base.alpha_composite(neon_card(size, fill, radius=radius, border=border, glow=glow, offset=offset), xy)

        def tab_asset(file_name: str, text: str, active: bool = False):
            size = (260, 56)
            image = neon_card(
                size,
                (18, 20, 38, 210) if active else (10, 13, 28, 184),
                radius=17,
                border=3,
                glow=7 if active else 5,
                offset=0.14 if active else 0.02,
            )
            draw = ImageDraw.Draw(image)
            if active:
                draw.rounded_rectangle((38, 45, 222, 49), radius=2, fill=neon_gold)
            text_center(draw, (0, 0, size[0], size[1] - 2), text, font(20), text_main if active else text_muted)
            save(image, file_name)

        def button_asset(file_name: str, size: tuple[int, int], text: str, active: bool = False, list_row: bool = False):
            image = neon_card(
                size,
                (35, 22, 52, 210) if active else glass_light,
                radius=18 if list_row else 15,
                border=3,
                glow=9 if active else 6,
                offset=0.42 if active else 0.18,
            )
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (20, 18, 27, size[1] - 19),
                radius=3,
                fill=neon_gold if active else cyan_dim,
            )
            if list_row:
                text_left(draw, (48, 18), text, font(24), text_main)
                draw.line((size[0] - 88, 18, size[0] - 88, size[1] - 19), fill=(255, 255, 255, 42), width=1)
            else:
                text_center(draw, (12, 0, size[0], size[1]), text, font(22), text_main)
            save(image, file_name)

        panel_bg = neon_card((1024, 756), fill=(8, 10, 24, 208), radius=34, border=5, glow=24, offset=0.08)
        draw = ImageDraw.Draw(panel_bg)
        for center, color, radius in (
            ((190, 110), (80, 220, 255, 34), 150),
            ((760, 90), (255, 82, 218, 28), 210),
            ((874, 650), (255, 206, 82, 22), 180),
        ):
            orb = Image.new("RGBA", (1024, 756), (0, 0, 0, 0))
            orb_draw = ImageDraw.Draw(orb)
            orb_draw.ellipse(
                (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
                fill=color,
            )
            panel_bg.alpha_composite(orb.filter(ImageFilter.GaussianBlur(radius // 2)))
        draw = ImageDraw.Draw(panel_bg)
        draw.rounded_rectangle((46, 44, 978, 126), radius=22, fill=(12, 15, 34, 130), outline=(255, 255, 255, 34), width=1)
        draw.line((58, 148, 966, 148), fill=neon_blue, width=1)
        draw.line((58, 152, 966, 152), fill=neon_pink, width=1)
        draw.rectangle((64, 704, 310, 710), fill=(255, 206, 82, 155))
        draw.rectangle((326, 704, 958, 707), fill=(135, 86, 255, 110))
        save(panel_bg, "panel_bg.dds")

        title = neon_card((360, 56), (10, 14, 36, 210), radius=19, border=3, glow=8, offset=0.00)
        draw = ImageDraw.Draw(title)
        draw.ellipse((23, 14, 48, 39), fill=(80, 220, 218, 44), outline=cyan, width=2)
        draw.polygon((33, 20, 33, 34, 45, 27), fill=cyan)
        text_left(draw, (64, 12), "RX MOTION", font(24), text_main)
        save(title, "title_badge.dds")

        tab_asset("tab_controls.dds", "PLAYER")
        tab_asset("tab_controls_active.dds", "PLAYER", active=True)
        tab_asset("tab_hotkeys.dds", "HOTKEYS")
        tab_asset("tab_hotkeys_active.dds", "HOTKEYS", active=True)
        tab_asset("tab_actions.dds", "ACTIONS")
        tab_asset("tab_actions_active.dds", "ACTIONS", active=True)

        for file_name, hover_name, label in (
            ("btn_play.dds", "btn_play_hover.dds", "PLAY"),
            ("btn_pause.dds", "btn_pause_hover.dds", "PAUSE"),
            ("btn_replay.dds", "btn_replay_hover.dds", "REPLAY"),
            ("btn_next_action.dds", "btn_next_action_hover.dds", "NEXT"),
            ("btn_speed.dds", "btn_speed_hover.dds", "SPEED"),
        ):
            button_asset(file_name, (180, 72), label)
            button_asset(hover_name, (180, 72), label, active=True)
        button_asset("btn_action.dds", (360, 72), "ACTION", list_row=True)
        button_asset("btn_action_hover.dds", (360, 72), "ACTION", active=True, list_row=True)

        track = neon_card((1024, 56), (8, 10, 22, 210), radius=18, border=2, glow=6, offset=0.25, shine=False)
        draw = ImageDraw.Draw(track)
        draw.rounded_rectangle((38, 24, 986, 32), radius=4, fill=(255, 255, 255, 42))
        save(track, "progress_track.dds")

        fill = Image.new("RGBA", (1024, 56), (0, 0, 0, 0))
        draw = ImageDraw.Draw(fill)
        fill_gradient = neon_gradient((1024, 56), 0.30)
        fill_mask = Image.new("L", (1024, 56), 0)
        fill_mask_draw = ImageDraw.Draw(fill_mask)
        fill_mask_draw.rounded_rectangle((38, 20, 986, 36), radius=8, fill=255)
        fill = fill_gradient
        fill.putalpha(fill_mask)
        save(fill, "progress_fill.dds")

        handle = neon_card((48, 48), (18, 12, 34, 230), radius=16, border=3, glow=7, offset=0.46, shine=False)
        draw = ImageDraw.Draw(handle)
        draw.rectangle((21, 13, 27, 35), fill=neon_gold)
        save(handle, "progress_handle.dds")

        watermark = Image.new("RGBA", (1024, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        draw.line((92, 32, 812, 32), fill=(190, 220, 255, 54), width=1)
        draw.rectangle((820, 26, 930, 38), fill=(255, 82, 218, 108))
        text_left(draw, (96, 18), "LOCAL ANIMATION CONTROL", font(22), (214, 222, 246, 220))
        save(watermark, "watermark_patreon.dds")

        digits = Image.new("RGBA", (624, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(digits)
        glyphs = "0123456789:/ "
        digit_font = font(42)
        for index, glyph in enumerate(glyphs):
            text_center(draw, (index * 48, 0, (index + 1) * 48, 64), glyph, digit_font, text_main)
        save(digits, "digits_atlas.dds")

        def page_asset(file_name: str, title_text: str, lines: tuple[str, ...]):
            page = neon_card((940, 400), (8, 11, 28, 166), radius=26, border=3, glow=12, offset=0.14)
            draw = ImageDraw.Draw(page)
            draw.rounded_rectangle((42, 42, 898, 82), radius=13, fill=(255, 255, 255, 18))
            draw.rectangle((52, 86, 888, 90), fill=amber_soft if file_name == "actions_page.dds" else cyan_dim)
            text_left(draw, (34, 18), title_text, font(28), text_main)
            y = 86
            for line in lines:
                text_left(draw, (44, y), line, font(22), text_muted)
                y += 36
            save(page, file_name)

        page_asset(
            "hotkeys_page.dds",
            "Hotkeys",
            (
                "Ctrl + Alt + /        Toggle panel",
                "Ctrl + Alt + Space    Play / Pause",
                "Ctrl + Alt + R        Replay",
                "Ctrl + Alt + S        Cycle speed",
                "Ctrl + Alt + N        Next action",
                "Ctrl + Alt + 1-4      Select action",
                "Drag progress bar     Seek",
            ),
        )
        actions = neon_card((940, 400), (8, 11, 28, 166), radius=26, border=3, glow=12, offset=0.32)
        draw = ImageDraw.Draw(actions)
        draw.rounded_rectangle((42, 42, 898, 82), radius=13, fill=(255, 255, 255, 18))
        draw.rectangle((52, 86, 888, 90), fill=amber_soft)
        text_left(draw, (34, 18), "Actions", font(28), text_main)
        paste_neon_card(actions, (30, 88), (388, 268), (10, 13, 30, 118), radius=18, border=2, glow=8, offset=0.10)
        paste_neon_card(actions, (448, 88), (458, 268), (10, 13, 30, 106), radius=18, border=2, glow=8, offset=0.48)
        draw = ImageDraw.Draw(actions)
        draw.rectangle((52, 112, 154, 116), fill=neon_gold)
        draw.rectangle((472, 112, 570, 116), fill=cyan)
        text_left(draw, (472, 122), "CLIP DETAIL", font(22), text_main)
        text_left(draw, (472, 158), "Shared timeline: bone / morph / UI", font(20), text_muted)
        text_left(draw, (472, 194), "Next Action cycles exported clips.", font(20), text_muted)
        text_left(draw, (472, 230), "Replay returns to the loop start.", font(20), text_muted)
        draw.line((472, 292, 860, 292), fill=(255, 255, 255, 36), width=1)
        text_left(draw, (472, 312), "No clip thumbnails yet. Kept clean on purpose.", font(18), (134, 145, 145, 210))
        save(actions, "actions_page.dds")
        generated = True
    except Exception:
        generated = False

    if not generated:
        for target_name, fallback_name in (
            ("tab_actions.dds", "tab_hotkeys.dds"),
            ("tab_actions_active.dds", "tab_hotkeys_active.dds"),
            ("btn_next_action.dds", "btn_replay.dds"),
            ("btn_next_action_hover.dds", "btn_replay_hover.dds"),
            ("btn_action.dds", "btn_speed.dds"),
            ("btn_action_hover.dds", "btn_speed_hover.dds"),
            ("actions_page.dds", "hotkeys_page.dds"),
        ):
            _copy_ui_asset_if_possible(ui_dir, target_name, fallback_name)


def write_runtime_ui_ini_from_manifest(output_directory: str, clip_name: str, manifest: dict | None = None) -> str:
    manifest = load_export_manifest(output_directory) if manifest is None else manifest
    safe_clip_name = sanitize_export_name(normalize_clip_name(clip_name), "rxanimin")
    output_path = os.path.join(os.path.abspath(output_directory or "."), f"{safe_clip_name}_UI.ini")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_runtime_ui_assets(output_directory)
    with open(output_path, "w", encoding="utf-8", newline="\n") as ini_file:
        ini_file.write(build_runtime_ui_ini(manifest, clip_name))
    return output_path


def write_runtime_ini_from_manifest(output_directory: str, clip_name: str) -> str:
    manifest = load_export_manifest(output_directory)
    output_path = resolve_runtime_ini_path(output_directory, clip_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as ini_file:
        ini_file.write(build_runtime_ini(manifest, clip_name, output_directory))
    write_runtime_ui_ini_from_manifest(output_directory, clip_name, manifest)
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
StructuredBuffer<uint4> TimelineStatic : register(t0);
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
    uint4 timeline_header = TimelineStatic[0];
    float4 control0 = IniParams[0];
    float4 control1 = IniParams[1];

    uint flags = playback0.x;
    uint playback_tick = playback0.w;
    uint last_control_token = playback2.y;
    uint active_clip_index = playback2.z;
    uint queued_clip_index = playback2.w;

    uint requested_playing = (uint)max(control0.x, 0.0);
    uint control_token = (uint)max(control0.y, 0.0);
    int control_value = RoundToInt(control0.z);
    uint seek_active = (uint)max(control0.w, 0.0);
    float seek_norm = saturate(control1.y);
    uint requested_clip_index = (uint)max(control1.z, 0.0);
    uint clip_count = max(timeline_header.x, 1u);
    requested_clip_index = min(requested_clip_index, clip_count - 1u);
    queued_clip_index = requested_clip_index;
    active_clip_index = min(active_clip_index, clip_count - 1u);

    if (requested_playing != 0u)
    {
        flags |= RX_ANIM_FLAG_PLAYING;
    }
    else
    {
        flags &= ~RX_ANIM_FLAG_PLAYING;
    }

    bool restarted = false;
    if (control_token != last_control_token)
    {
        if (control_value == 2)
        {
            active_clip_index = requested_clip_index;
        }
        if (control_value != 0)
        {
            playback_tick = 0u;
            restarted = true;
        }
        last_control_token = control_token;
    }
    else
    {
        active_clip_index = requested_clip_index;
    }

    uint4 clip_row = TimelineStatic[1u + active_clip_index];
    uint sample_count = max(clip_row.x, 1u);
    uint ticks_per_sample = max(clip_row.y, 1u);
    uint loop_start = min(clip_row.z, sample_count - 1u);
    uint loop_end = min(clip_row.w, sample_count - 1u);
    uint speed_override = (uint)max(control1.x, 0.0);
    if (speed_override > 0u)
    {
        ticks_per_sample = speed_override;
    }

    uint loop_min = min(loop_start, loop_end);
    uint loop_max = max(loop_start, loop_end);
    uint loop_sample_count = max(loop_max - loop_min + 1u, 1u);
    uint max_tick = (loop_sample_count > 1u) ? ((loop_sample_count - 1u) * ticks_per_sample) : 0u;

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
    MasterPlayback[2] = uint4(seek_active, last_control_token, active_clip_index, queued_clip_index);
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
    uint4 playback0 = MasterPlayback[0];
    uint4 playback1 = MasterPlayback[1];
    uint4 playback2 = MasterPlayback[2];

    uint clip_count = max(timeline0.x, 1u);
    uint active_clip_index = min(playback2.z, clip_count - 1u);
    uint4 clip_row = TimelineStatic[1u + active_clip_index];
    uint sample_count = max(clip_row.x, 1u);
    uint current_tick = playback0.z;
    uint ticks_per_sample = max(playback1.x, 1u);
    uint loop_start = min(playback1.y, sample_count - 1u);
    uint loop_end = min(playback1.z, sample_count - 1u);

    if (loop_end < loop_start)
    {
        loop_start = min(clip_row.z, sample_count - 1u);
        loop_end = min(clip_row.w, sample_count - 1u);
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
#define PARAMS IniParams[88]
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

uint ResolveGlyphIndex(uint slot)
{
    uint glyph_index = SpeedGlyphIndex(slot);
    uint mode = (uint)PARAMS.x;
    if (mode == 1u)
    {
        uint action_label = (uint)max(PARAMS.y, 0.0);
        action_label = min(action_label, 9u);
        glyph_index = (slot == 0u) ? action_label : 12u;
    }
    return glyph_index;
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

    float glyph_left = (float)ResolveGlyphIndex(0u) / (float)GLYPH_COUNT;
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

uint RxMorphRowsPerSample(uint channel_count, uint weights_per_row)
{
    weights_per_row = max(weights_per_row, 1u);
    return max((max(channel_count, 1u) + weights_per_row - 1u) / weights_per_row, 1u);
}

float RxLoadMorphWeight(uint channel_index, uint sample_index)
{
    uint4 anim_header = MorphAnim[0];
    uint clip_count = max(anim_header.x, 1u);
    uint channel_count = anim_header.y;
    uint weights_per_row = max(anim_header.z, 1u);
    if (channel_index >= channel_count) return 0.0;

    uint4 playback2 = MasterPlayback[2];
    uint active_clip_index = min(playback2.z, clip_count - 1u);
    uint4 clip_row = MorphAnim[1u + active_clip_index];
    uint sample_count = max(clip_row.x, 1u);
    uint sample_row_base = clip_row.y;
    sample_index = min(sample_index, sample_count - 1u);
    uint rows_per_sample = RxMorphRowsPerSample(channel_count, weights_per_row);
    uint row_index = sample_row_base + sample_index * rows_per_sample + channel_index / weights_per_row;
    uint packed_pair = RxReadUint4Component(MorphAnim[row_index], (channel_index % weights_per_row) / 2u);
    uint half_bits = ((channel_index & 1u) == 0u) ? (packed_pair & 0xffffu) : ((packed_pair >> 16u) & 0xffffu);
    return f16tof32(half_bits);
}

void RxResolveMorphSampleWindow(out uint sample_a, out uint sample_b, out float sample_alpha)
{
    uint4 anim_header = MorphAnim[0];
    uint clip_count = max(anim_header.x, 1u);
    uint4 playback2 = MasterPlayback[2];
    uint active_clip_index = min(playback2.z, clip_count - 1u);
    uint4 clip_row = MorphAnim[1u + active_clip_index];
    uint sample_count = max(clip_row.x, 1u);
    uint4 playback0 = MasterPlayback[0];
    uint4 playback1 = MasterPlayback[1];
    uint loop_start = min(playback1.y, sample_count - 1u);
    uint loop_end = min(playback1.z, sample_count - 1u);
    if (loop_end < loop_start)
    {
        loop_start = 0u;
        loop_end = sample_count - 1u;
    }
    ResolveTickToSampleWindow(
        playback0.z,
        sample_count,
        max(playback1.x, 1u),
        loop_start,
        loop_end,
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

uint LoadSlotId(uint bone_index, uint slot_map_base)
{
    uint4 row = BoneStatic[slot_map_base + bone_index / 4u];
    return row[bone_index & 3u];
}

void LoadPose(uint sample_id, uint sample_row_base, uint bone_index, uint bone_count, out float3 t, out float4 q)
{
    uint base_row = sample_row_base + (sample_id * bone_count + bone_index) * 2u;
    t = BoneAnim[base_row].xyz;
    q = BoneAnim[base_row + 1];
}

[numthreads(1, 1, 1)]
void main(uint3 dispatch_id : SV_DispatchThreadID)
{
    uint bone_index = dispatch_id.x;
    uint4 header0 = BoneStatic[0];
    uint4 header1 = BoneStatic[1];
    uint clip_count = max(header0.x, 1u);
    uint bone_count = header0.y;
    uint reserved_rows = header0.z;
    uint payload_flags = header1.z;
    uint clip_table_base = header1.w;
    if (bone_index >= bone_count) return;

    uint4 playback0 = MasterPlayback[0];
    uint4 playback1 = MasterPlayback[1];
    uint4 playback2 = MasterPlayback[2];
    uint current_tick = playback0.z;
    uint previous_tick = playback0.y;
    uint ticks_per_sample = playback1.x;
    uint active_clip_index = min(playback2.z, clip_count - 1u);
    uint slot_map_base = clip_table_base + clip_count;
    uint4 clip_row = BoneStatic[clip_table_base + active_clip_index];
    uint sample_count = max(clip_row.x, 1u);
    uint sample_row_base = clip_row.y;
    uint loop_start = min(playback1.y, sample_count - 1u);
    uint loop_end = min(playback1.z, sample_count - 1u);
    if (loop_end < loop_start)
    {
        loop_start = min(clip_row.z, sample_count - 1u);
        loop_end = min(clip_row.w, sample_count - 1u);
    }

    uint sample_a, sample_b;
    float alpha;
    ResolveTickToSampleWindow(current_tick, sample_count, ticks_per_sample, loop_start, loop_end, sample_a, sample_b, alpha);

    float3 ta, tb;
    float4 qa, qb;
    LoadPose(sample_a, sample_row_base, bone_index, bone_count, ta, qa);
    LoadPose(sample_b, sample_row_base, bone_index, bone_count, tb, qb);
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

    uint slot_id = LoadSlotId(bone_index, slot_map_base);
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
    LoadPose(sample_a, sample_row_base, bone_index, bone_count, ta, qa);
    LoadPose(sample_b, sample_row_base, bone_index, bone_count, tb, qb);
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
