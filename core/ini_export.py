"""Helpers for writing RX runtime ini snippets next to exported clips."""

from __future__ import annotations

import os
import re

from .animation_export import normalize_clip_name, sanitize_export_name
from .collection_plan import CB1_OVERRIDE_EYELASH, CB1_OVERRIDE_NONE, normalize_cb1_override


_RESOURCE_POSITION_RE = re.compile(
    r"^(?P<prefix>Resource_(?P<hash>[0-9A-Fa-f]{8})_(?P<index_count>\d+)_\d+)_Position$"
)
_SOURCE_MESH_RE = re.compile(r"(?P<hash>[0-9A-Fa-f]{8})[-_](?P<index_count>\d+)(?:[-_]\d+)?")
DEFAULT_REPLACEMENT_MATCH_PRIORITY = -1000


def resolve_generated_ini_path(output_directory: str, clip_name: str) -> str:
    directory_path = os.path.abspath(output_directory or ".")
    safe_clip_name = sanitize_export_name(normalize_clip_name(clip_name), "rxanimin")
    return os.path.join(directory_path, f"{safe_clip_name}_generated_overrides.ini")


def _infer_mesh_key_from_clip_path(path: str) -> str:
    file_name = os.path.basename(path)
    for suffix in ("_clip_static.buf", "_clip_tqs.buf", "_clip_bind.buf"):
        if file_name.endswith(suffix):
            return file_name[: -len(suffix)]
    return os.path.splitext(file_name)[0]


def _build_position_resource_bundle(resource_name: str):
    if not resource_name:
        return None
    match = _RESOURCE_POSITION_RE.match(resource_name)
    if not match:
        return None
    prefix = match.group("prefix")
    return {
        "hash": match.group("hash").lower(),
        "match_index_count": int(match.group("index_count")),
        "position": f"{prefix}_Position",
        "texcoord": f"{prefix}_Texcoord",
        "blend": f"{prefix}_Blend",
        "index": f"{prefix}_Index",
    }


def _infer_match_index_count_from_source_mesh_name(source_mesh_name: str):
    if not source_mesh_name:
        return None
    match = _SOURCE_MESH_RE.search(str(source_mesh_name))
    if not match:
        return None
    return int(match.group("index_count"))


def _write_line(lines: list[str], value: str = ""):
    lines.append(value)


def _resolve_cb1_override_resource(cb1_override: str) -> str:
    normalized_override = normalize_cb1_override(cb1_override, CB1_OVERRIDE_NONE)
    if normalized_override == CB1_OVERRIDE_EYELASH:
        return "ResourceCB1Flag_Eyelash"
    return ""


def _append_cb1_override_binding(lines: list[str], cb1_override: str):
    resource_name = _resolve_cb1_override_resource(cb1_override)
    if resource_name:
        _write_line(lines, f"    cs-t3 = {resource_name}")


def _append_clip_resource_sections(lines: list[str], export_results):
    seen_mesh_keys = set()
    for export_result in export_results:
        mesh_key = _infer_mesh_key_from_clip_path(export_result.static_clip_path)
        if mesh_key in seen_mesh_keys:
            continue
        seen_mesh_keys.add(mesh_key)
        _write_line(lines, f"[ResourceClipTQS_{mesh_key}]")
        _write_line(lines, "type = StructuredBuffer")
        _write_line(lines, "stride = 16")
        _write_line(lines, f"filename = {os.path.basename(export_result.tqs_path)}")
        _write_line(lines)
        _write_line(lines, f"[ResourceClipBind_{mesh_key}]")
        _write_line(lines, "type = StructuredBuffer")
        _write_line(lines, "stride = 16")
        _write_line(lines, f"filename = {os.path.basename(export_result.bind_path)}")
        _write_line(lines)
        _write_line(lines, f"[ResourceClipStatic_{mesh_key}]")
        _write_line(lines, "type = StructuredBuffer")
        _write_line(lines, "stride = 16")
        _write_line(lines, f"filename = {os.path.basename(export_result.static_clip_path)}")
        _write_line(lines)


def _append_morph_resource_sections(lines: list[str], morph_results):
    for morph_result in morph_results:
        mesh_key = morph_result.mesh_key
        if str(morph_result.base_position_resource_name).startswith("ResourceBasePosition_"):
            _write_line(lines, f"[{morph_result.base_position_resource_name}]")
            _write_line(lines, "type = Buffer")
            _write_line(lines, f"stride = {int(morph_result.base_position_stride)}")
            _write_line(lines, f"filename = {morph_result.base_position_path}")
            _write_line(lines)
        _write_line(lines, f"[ResourceMorphStatic_{mesh_key}]")
        _write_line(lines, "type = StructuredBuffer")
        _write_line(lines, "stride = 16")
        _write_line(lines, f"filename = {os.path.basename(morph_result.morph_static_path)}")
        _write_line(lines)
        _write_line(lines, f"[ResourceMorphAnim_{mesh_key}]")
        _write_line(lines, "type = StructuredBuffer")
        _write_line(lines, "stride = 16")
        _write_line(lines, f"filename = {os.path.basename(morph_result.morph_anim_path)}")
        _write_line(lines)
        _write_line(lines, f"[ResourceMorphRuntimeVB_{mesh_key}_UAV]")
        _write_line(lines, "type = RWStructuredBuffer")
        _write_line(lines, f"stride = {int(morph_result.base_position_stride)}")
        _write_line(lines, f"array = {int(morph_result.vertex_count)}")
        _write_line(lines)
        _write_line(lines, f"[ResourceMorphRuntimeVB_{mesh_key}]")
        _write_line(lines, "type = Buffer")
        _write_line(lines, f"stride = {int(morph_result.base_position_stride)}")
        _write_line(lines, f"array = {int(morph_result.vertex_count)}")
        _write_line(lines)


def _append_bone_texture_override(lines: list[str], export_result, cb1_override=CB1_OVERRIDE_NONE):
    mesh_key = _infer_mesh_key_from_clip_path(export_result.static_clip_path)
    part_id = int(export_result.metadata.get("part_id", -1))
    hash_value = str(export_result.metadata.get("hash", "") or mesh_key)
    inferred_match_index_count = int(export_result.metadata.get("match_index_count", 0) or 0)
    _write_line(lines, f"[TextureOverride_RX_{mesh_key}]")
    _write_line(lines, "; RX bone animation entry")
    _write_line(lines, f"; part_id = {part_id}")
    _write_line(lines, f"hash = {hash_value}")
    if inferred_match_index_count <= 0:
        _write_line(lines, "; match_index_count = ???")
    else:
        _write_line(lines, f"match_index_count = {inferred_match_index_count}")
    _write_line(lines, f"match_priority = {DEFAULT_REPLACEMENT_MATCH_PRIORITY}")
    _write_line(lines, "if $rx_anim_enable == 1")
    _write_line(lines, "    run = CustomShader_ExtractCB1")
    _write_line(lines, f"    cs-t2 = ResourceClipStatic_{mesh_key}")
    _append_cb1_override_binding(lines, cb1_override)
    _write_line(lines, "    run = CustomShader_RedirectCB1")
    _write_line(lines, "    if vs == 200")
    _write_line(lines, f"        cs-t0 = ResourceClipTQS_{mesh_key}")
    _write_line(lines, f"        cs-t1 = ResourceClipBind_{mesh_key}")
    _write_line(lines, f"        cs-t2 = ResourceClipStatic_{mesh_key}")
    _write_line(lines, "        run = CustomShader_CopyClipToFakeT0")
    _write_line(lines, "    endif")
    _write_line(lines, "    vs-t0 = ResourceFakeT0_SRV")
    _write_line(lines, "    vs-cb1 = ResourceFakeCB1")
    _write_line(lines, "endif")
    _write_line(lines)


def _append_morph_texture_override(lines: list[str], export_result, morph_result, cb1_override=CB1_OVERRIDE_NONE):
    mesh_key = morph_result.mesh_key
    bundle = _build_position_resource_bundle(morph_result.base_position_resource_name)
    hash_value = str(export_result.metadata.get("hash", "") or mesh_key)
    inferred_match_index_count = int(export_result.metadata.get("match_index_count", 0) or 0)
    shader_name = (
        "CustomShader_ApplyMorph_PNTA40"
        if str(morph_result.base_position_layout) == "EFMI_PNTA40"
        else "CustomShader_ApplyMorph"
    )
    part_id = int(export_result.metadata.get("part_id", -1))

    _write_line(lines, f"[TextureOverride_RX_{mesh_key}]")
    _write_line(lines, "; RX bone + morph animation entry")
    _write_line(lines, f"; part_id = {part_id}")
    _write_line(lines, f"hash = {hash_value}")
    if bundle is not None:
        _write_line(lines, f"match_index_count = {bundle['match_index_count']}")
    elif inferred_match_index_count > 0:
        _write_line(lines, f"match_index_count = {inferred_match_index_count}")
    else:
        _write_line(lines, "; match_index_count = ???")
    _write_line(lines, f"match_priority = {DEFAULT_REPLACEMENT_MATCH_PRIORITY}")
    _write_line(lines, "if $rx_anim_enable == 1")
    if bundle is not None:
        _write_line(lines, "    handling = skip")
        _write_line(lines, f"    ib = ref {bundle['index']}")
        _write_line(lines, f"    vb1 = ref {bundle['texcoord']}")
        _write_line(lines, f"    vb2 = ref {bundle['blend']}")
        _write_line(lines, f"    cs-t0 = {bundle['position']}")
    elif morph_result.base_position_resource_name:
        _write_line(lines, f"    cs-t0 = {morph_result.base_position_resource_name}")
    else:
        _write_line(lines, "    ; TODO: bind base Position/Texcoord/Blend/Index resources for this mesh.")
        _write_line(lines, "    ; cs-t0 = Resource_<hash>_<indexcount>_0_Position")
        _write_line(lines, "    ; vb1 = ref Resource_<hash>_<indexcount>_0_Texcoord")
        _write_line(lines, "    ; vb2 = ref Resource_<hash>_<indexcount>_0_Blend")
        _write_line(lines, "    ; ib = ref Resource_<hash>_<indexcount>_0_Index")
    _write_line(lines, f"    cs-t1 = ResourceMorphStatic_{mesh_key}")
    _write_line(lines, f"    cs-t2 = ResourceMorphAnim_{mesh_key}")
    _write_line(lines, f"    cs-u0 = ResourceMorphRuntimeVB_{mesh_key}_UAV")
    _write_line(lines, f"    run = {shader_name}")
    _write_line(lines, f"    ResourceMorphRuntimeVB_{mesh_key} = copy ResourceMorphRuntimeVB_{mesh_key}_UAV")
    _write_line(lines, f"    vb0 = ref ResourceMorphRuntimeVB_{mesh_key}")
    _write_line(lines, f"    vb3 = ref ResourceMorphRuntimeVB_{mesh_key}")
    _write_line(lines, "    run = CustomShader_ExtractCB1")
    _write_line(lines, f"    cs-t2 = ResourceClipStatic_{mesh_key}")
    _append_cb1_override_binding(lines, cb1_override)
    _write_line(lines, "    run = CustomShader_RedirectCB1")
    _write_line(lines, "    if vs == 200")
    _write_line(lines, f"        cs-t0 = ResourceClipTQS_{mesh_key}")
    _write_line(lines, f"        cs-t1 = ResourceClipBind_{mesh_key}")
    _write_line(lines, f"        cs-t2 = ResourceClipStatic_{mesh_key}")
    _write_line(lines, "        run = CustomShader_CopyClipToFakeT0")
    _write_line(lines, "    endif")
    _write_line(lines, "    vs-t0 = ResourceFakeT0_SRV")
    _write_line(lines, "    vs-cb1 = ResourceFakeCB1")
    resolved_draw_count = bundle["match_index_count"] if bundle is not None else inferred_match_index_count
    if resolved_draw_count:
        _write_line(lines, f"    drawindexedinstanced = {resolved_draw_count},INSTANCE_COUNT,0,0,FIRST_INSTANCE")
    else:
        _write_line(lines, "    ; drawindexedinstanced = <match_index_count>,INSTANCE_COUNT,0,0,FIRST_INSTANCE")
    _write_line(lines, "endif")
    _write_line(lines)


def _append_morph_only_texture_override(lines: list[str], morph_result):
    mesh_key = morph_result.mesh_key
    bundle = _build_position_resource_bundle(morph_result.base_position_resource_name)
    hash_value = str(getattr(morph_result, "draw_hash", "") or mesh_key)
    match_index_count = int(getattr(morph_result, "match_index_count", 0) or 0)
    shader_name = (
        "CustomShader_ApplyMorph_PNTA40"
        if str(morph_result.base_position_layout) == "EFMI_PNTA40"
        else "CustomShader_ApplyMorph"
    )

    _write_line(lines, f"[TextureOverride_RXMorph_{mesh_key}]")
    _write_line(lines, "; RX morph-only snippet")
    _write_line(lines, "; Merge this block into the matching bone TextureOverride if the draw also uses RX bone animation.")
    _write_line(lines, f"hash = {hash_value}")
    if bundle is not None:
        _write_line(lines, f"match_index_count = {bundle['match_index_count']}")
    elif match_index_count > 0:
        _write_line(lines, f"match_index_count = {match_index_count}")
    else:
        _write_line(lines, "; match_index_count = ???")
    _write_line(lines, f"match_priority = {DEFAULT_REPLACEMENT_MATCH_PRIORITY}")
    _write_line(lines, "if $rx_anim_enable == 1")
    if bundle is not None:
        _write_line(lines, "    handling = skip")
        _write_line(lines, f"    ib = ref {bundle['index']}")
        _write_line(lines, f"    vb1 = ref {bundle['texcoord']}")
        _write_line(lines, f"    vb2 = ref {bundle['blend']}")
        _write_line(lines, f"    cs-t0 = {bundle['position']}")
    elif morph_result.base_position_resource_name:
        _write_line(lines, f"    cs-t0 = {morph_result.base_position_resource_name}")
    else:
        _write_line(lines, "    ; TODO: bind base Position/Texcoord/Blend/Index resources for this mesh.")
        _write_line(lines, "    ; cs-t0 = Resource_<hash>_<indexcount>_0_Position")
        _write_line(lines, "    ; vb1 = ref Resource_<hash>_<indexcount>_0_Texcoord")
        _write_line(lines, "    ; vb2 = ref Resource_<hash>_<indexcount>_0_Blend")
        _write_line(lines, "    ; ib = ref Resource_<hash>_<indexcount>_0_Index")
    _write_line(lines, f"    cs-t1 = ResourceMorphStatic_{mesh_key}")
    _write_line(lines, f"    cs-t2 = ResourceMorphAnim_{mesh_key}")
    _write_line(lines, f"    cs-u0 = ResourceMorphRuntimeVB_{mesh_key}_UAV")
    _write_line(lines, f"    run = {shader_name}")
    _write_line(lines, f"    ResourceMorphRuntimeVB_{mesh_key} = copy ResourceMorphRuntimeVB_{mesh_key}_UAV")
    _write_line(lines, f"    vb0 = ref ResourceMorphRuntimeVB_{mesh_key}")
    _write_line(lines, f"    vb3 = ref ResourceMorphRuntimeVB_{mesh_key}")
    if bundle is not None:
        _write_line(lines, f"    drawindexedinstanced = {bundle['match_index_count']},INSTANCE_COUNT,0,0,FIRST_INSTANCE")
    else:
        _write_line(lines, "    ; drawindexedinstanced = <match_index_count>,INSTANCE_COUNT,0,0,FIRST_INSTANCE")
    _write_line(lines, "endif")
    _write_line(lines)


def write_generated_runtime_ini(
    output_directory: str,
    clip_name: str,
    export_results,
    morph_results=(),
    cb1_override_by_mesh_key=None,
    draw_parts=(),
):
    normalized_export_results = tuple(export_results)
    normalized_morph_results = tuple(morph_results)
    if not normalized_export_results and not normalized_morph_results:
        return ""

    morph_by_mesh_key = {result.mesh_key: result for result in normalized_morph_results}
    normalized_cb1_overrides = {
        str(mesh_key): normalize_cb1_override(override, CB1_OVERRIDE_NONE)
        for mesh_key, override in dict(cb1_override_by_mesh_key or {}).items()
    }
    output_path = resolve_generated_ini_path(output_directory, clip_name)
    lines: list[str] = []
    _write_line(lines, "; Auto-generated by bone_importer")
    _write_line(lines, "; This file contains RX-style resource and TextureOverride snippets for the exported clip.")
    _write_line(lines, "; Merge the pieces you need into your runtime ini instead of editing this file by hand.")
    _write_line(lines)

    _append_clip_resource_sections(lines, normalized_export_results)
    if normalized_morph_results:
        _append_morph_resource_sections(lines, normalized_morph_results)

    if normalized_export_results:
        for export_result in normalized_export_results:
            mesh_key = _infer_mesh_key_from_clip_path(export_result.static_clip_path)
            morph_result = morph_by_mesh_key.get(mesh_key)
            cb1_override = normalized_cb1_overrides.get(mesh_key, CB1_OVERRIDE_NONE)
            if morph_result is None:
                _append_bone_texture_override(lines, export_result, cb1_override=cb1_override)
            else:
                _append_morph_texture_override(lines, export_result, morph_result, cb1_override=cb1_override)
    else:
        for morph_result in normalized_morph_results:
            _append_morph_only_texture_override(lines, morph_result)

    with open(output_path, "w", encoding="utf-8", newline="\n") as ini_file:
        ini_file.write("\n".join(lines).rstrip() + "\n")
    return output_path
