"""Manifest-driven RX runtime INI and HLSL writers."""

from __future__ import annotations

import os

from .animation_export import normalize_clip_name, sanitize_export_name
from .manifest import load_export_manifest


def _line(lines: list[str], value: str = ""):
    lines.append(value)


def _basename(path: str) -> str:
    return os.path.basename(str(path or ""))


def _resource_key(draw_key: str) -> str:
    return sanitize_export_name(draw_key, "draw_part")


def resolve_runtime_ini_path(output_directory: str, clip_name: str) -> str:
    safe_clip_name = sanitize_export_name(normalize_clip_name(clip_name), "rxanimin")
    return os.path.join(os.path.abspath(output_directory or "."), f"{safe_clip_name}.ini")


def _append_global_resources(lines: list[str], manifest: dict, clip_name: str):
    clip = manifest.get("clips", {}).get(normalize_clip_name(clip_name), {})
    timeline_path = clip.get("timeline_static", "") or f"{sanitize_export_name(clip_name, 'rxanimin')}_timeline_static.buf"
    master_path = clip.get("master_playback", "") or f"{sanitize_export_name(clip_name, 'rxanimin')}_master_playback.buf"

    _line(lines, "[ResourceTimelineStatic]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(timeline_path)}")
    _line(lines)
    _line(lines, "[ResourceMasterPlayback]")
    _line(lines, "type = RWStructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(master_path)}")
    _line(lines)
    _line(lines, "[ResourceMasterPlayback_SRV]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(master_path)}")
    _line(lines)
    _line(lines, "[CustomShader_UpdateBonePaletteTQ]")
    _line(lines, "cs = hlsl\\update_bone_palette_tq_cs.hlsl")
    _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
    _line(lines)
    _line(lines, "[CustomShader_RedirectCB1LocalPalette]")
    _line(lines, "cs = hlsl\\redirect_cb1_local_palette_cs.hlsl")
    _line(lines)
    _line(lines, "[CustomShader_ApplyMorph]")
    _line(lines, "cs = hlsl\\apply_morph_to_vb_cs.hlsl")
    _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
    _line(lines)
    _line(lines, "[CustomShader_ApplyMorph_PNTA40]")
    _line(lines, "cs = hlsl\\apply_morph_to_vb_pnta40_cs.hlsl")
    _line(lines, "cs-t3 = ResourceMasterPlayback_SRV")
    _line(lines)


def _append_bone_resources(lines: list[str], draw_key: str, payload: dict):
    key = _resource_key(draw_key)
    _line(lines, f"[ResourceBoneStatic_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(payload.get('static', ''))}")
    _line(lines)
    _line(lines, f"[ResourceBoneAnim_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(payload.get('anim', ''))}")
    _line(lines)
    _line(lines, f"[ResourceBoneBind_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(payload.get('bind', ''))}")
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
    _line(lines, "array = 32")
    _line(lines)
    _line(lines, f"[ResourceFakeCB1_{key}]")
    _line(lines, "type = Buffer")
    _line(lines, "stride = 16")
    _line(lines, "array = 32")
    _line(lines)


def _append_morph_resources(lines: list[str], draw_key: str, payload: dict):
    key = _resource_key(draw_key)
    base_resource = payload.get("base_position_resource_name", "") or f"ResourceBasePosition_{key}"
    if payload.get("base_position_path"):
        _line(lines, f"[{base_resource}]")
        _line(lines, "type = Buffer")
        _line(lines, f"stride = {int(payload.get('base_position_stride', 16) or 16)}")
        _line(lines, f"filename = {payload.get('base_position_path')}")
        _line(lines)
    _line(lines, f"[ResourceMorphStatic_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(payload.get('static', ''))}")
    _line(lines)
    _line(lines, f"[ResourceMorphAnim_{key}]")
    _line(lines, "type = StructuredBuffer")
    _line(lines, "stride = 16")
    _line(lines, f"filename = {_basename(payload.get('anim', ''))}")
    _line(lines)
    vertex_count = int(payload.get("vertex_count", 0) or 0)
    stride = int(payload.get("base_position_stride", 16) or 16)
    _line(lines, f"[ResourceMorphRuntimeVB_{key}_UAV]")
    _line(lines, "type = RWStructuredBuffer")
    _line(lines, f"stride = {stride}")
    _line(lines, f"array = {vertex_count}")
    _line(lines)
    _line(lines, f"[ResourceMorphRuntimeVB_{key}]")
    _line(lines, "type = Buffer")
    _line(lines, f"stride = {stride}")
    _line(lines, f"array = {vertex_count}")
    _line(lines)


def _append_resources(lines: list[str], manifest: dict):
    for draw_key, payload in manifest.get("payloads", {}).items():
        if "bone" in payload:
            _append_bone_resources(lines, draw_key, payload["bone"])
        if "morph" in payload:
            _append_morph_resources(lines, draw_key, payload["morph"])


def _append_texture_override(lines: list[str], draw_key: str, draw_part: dict, payload: dict):
    key = _resource_key(draw_key)
    bone_payload = payload.get("bone")
    morph_payload = payload.get("morph")
    match_priority = int(draw_part.get("match_priority", 50) or 50)
    _line(lines, f"[TextureOverride_RX_{key}]")
    _line(lines, "; RX manifest-driven animation entry")
    _line(lines, f"hash = {draw_part.get('hash', '')}")
    _line(lines, f"match_index_count = {int(draw_part.get('match_index_count', 0) or 0)}")
    first_index = int(draw_part.get("first_index", 0) or 0)
    if first_index:
        _line(lines, f"match_first_index = {first_index}")
    _line(lines, f"match_priority = {match_priority}")
    _line(lines, "if $rx_anim_enable == 1")
    if morph_payload is not None:
        shader = "CustomShader_ApplyMorph_PNTA40" if str(morph_payload.get("base_position_layout", "")).endswith("PNTA40") else "CustomShader_ApplyMorph"
        base_resource = morph_payload.get("base_position_resource_name", "") or f"ResourceBasePosition_{key}"
        _line(lines, f"    cs-t0 = {base_resource}")
        _line(lines, f"    cs-t1 = ResourceMorphStatic_{key}")
        _line(lines, f"    cs-t2 = ResourceMorphAnim_{key}")
        _line(lines, f"    cs-u0 = ResourceMorphRuntimeVB_{key}_UAV")
        _line(lines, f"    dispatch = {(int(morph_payload.get('vertex_count', 0) or 0) + 63) // 64}, 1, 1")
        _line(lines, f"    run = {shader}")
        _line(lines, f"    ResourceMorphRuntimeVB_{key} = copy ResourceMorphRuntimeVB_{key}_UAV")
        _line(lines, f"    vb0 = ref ResourceMorphRuntimeVB_{key}")
        _line(lines, f"    vb3 = ref ResourceMorphRuntimeVB_{key}")
    if bone_payload is not None:
        bone_count = max(len(bone_payload.get("slot_ids", [])), 1)
        _line(lines, f"    cs-t0 = ResourceBoneAnim_{key}")
        _line(lines, f"    cs-t1 = ResourceBoneBind_{key}")
        _line(lines, f"    cs-t2 = ResourceBoneStatic_{key}")
        _line(lines, f"    cs-u0 = ResourceBonePalette_{key}_UAV")
        _line(lines, f"    dispatch = {bone_count}, 1, 1")
        _line(lines, "    run = CustomShader_UpdateBonePaletteTQ")
        _line(lines, f"    ResourceBonePalette_{key} = copy ResourceBonePalette_{key}_UAV")
        _line(lines, f"    cs-u0 = ResourceFakeCB1_{key}_UAV")
        _line(lines, "    run = CustomShader_RedirectCB1LocalPalette")
        _line(lines, f"    ResourceFakeCB1_{key} = copy ResourceFakeCB1_{key}_UAV")
        _line(lines, f"    vs-t0 = ResourceBonePalette_{key}")
        _line(lines, f"    vs-cb1 = ResourceFakeCB1_{key}")
    _line(lines, "endif")
    _line(lines)


def build_runtime_ini(manifest: dict, clip_name: str) -> str:
    lines: list[str] = []
    _line(lines, "; Auto-generated by bone_importer RX runtime manifest renderer.")
    _line(lines, "; Do not edit generated resource names by hand; update rx_export_manifest.json instead.")
    _line(lines)
    _append_global_resources(lines, manifest, clip_name)
    _append_resources(lines, manifest)
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
        ini_file.write(build_runtime_ini(manifest, clip_name))
    write_runtime_hlsl_files(output_directory)
    return output_path


HLSL_FILES = {
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
    "update_bone_palette_tq_cs.hlsl": r"""#include "rx_anim_sampling.hlsli"

StructuredBuffer<float4> BoneAnim : register(t0);
StructuredBuffer<float4> BoneBind : register(t1);
StructuredBuffer<uint4> BoneStatic : register(t2);
StructuredBuffer<uint4> MasterPlayback : register(t3);
RWStructuredBuffer<float4> BonePalette : register(u0);

float4 QuatNormalize(float4 q) { return normalize(q); }

float4 QuatNlerp(float4 a, float4 b, float t)
{
    if (dot(a, b) < 0.0) b = -b;
    return normalize(lerp(a, b, t));
}

float3x3 MatrixFromQuat(float4 q)
{
    float x = q.x, y = q.y, z = q.z, w = q.w;
    float xx = x * x, yy = y * y, zz = z * z;
    float xy = x * y, xz = x * z, yz = y * z;
    float wx = w * x, wy = w * y, wz = w * z;
    return float3x3(
        1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy),
        2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx),
        2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)
    );
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

    float3x3 r = MatrixFromQuat(q);
    uint bind_row = bone_index * 3;
    float4 b0 = BoneBind[bind_row + 0];
    float4 b1 = BoneBind[bind_row + 1];
    float4 b2 = BoneBind[bind_row + 2];

    float4 row0 = float4(r[0].x, r[0].y, r[0].z, t.x);
    float4 row1 = float4(r[1].x, r[1].y, r[1].z, t.y);
    float4 row2 = float4(r[2].x, r[2].y, r[2].z, t.z);

    float4 out0 = float4(dot(row0, float4(b0.x, b1.x, b2.x, 0)), dot(row0, float4(b0.y, b1.y, b2.y, 0)), dot(row0, float4(b0.z, b1.z, b2.z, 0)), row0.w + b0.w);
    float4 out1 = float4(dot(row1, float4(b0.x, b1.x, b2.x, 0)), dot(row1, float4(b0.y, b1.y, b2.y, 0)), dot(row1, float4(b0.z, b1.z, b2.z, 0)), row1.w + b1.w);
    float4 out2 = float4(dot(row2, float4(b0.x, b1.x, b2.x, 0)), dot(row2, float4(b0.y, b1.y, b2.y, 0)), dot(row2, float4(b0.z, b1.z, b2.z, 0)), row2.w + b2.w);

    uint slot_id = LoadSlotId(bone_index);
    uint row_base = slot_id * 3;
    BonePalette[row_base + 0] = out0;
    BonePalette[row_base + 1] = out1;
    BonePalette[row_base + 2] = out2;

    uint previous_base = header1.y;
    ResolveTickToSampleWindow(previous_tick, sample_count, ticks_per_sample, loop_start, loop_end, sample_a, sample_b, alpha);
    LoadPose(sample_a, bone_index, bone_count, ta, qa);
    LoadPose(sample_b, bone_index, bone_count, tb, qb);
    t = lerp(ta, tb, alpha);
    q = QuatNlerp(qa, qb, alpha);
    r = MatrixFromQuat(q);
    BonePalette[previous_base + row_base + 0] = float4(r[0], t.x);
    BonePalette[previous_base + row_base + 1] = float4(r[1], t.y);
    BonePalette[previous_base + row_base + 2] = float4(r[2], t.z);
}
""",
    "redirect_cb1_local_palette_cs.hlsl": r"""RWStructuredBuffer<float4> FakeCB1 : register(u0);

[numthreads(1, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    if (id.x != 0) return;
    // The final project-specific CB1 extraction shader can fill the rest.
    // Local palette route keeps offsets at zero because each DrawPart owns its palette.
    FakeCB1[0] = float4(0, 0, 0, 0);
}
""",
    "apply_morph_to_vb_cs.hlsl": r"""// Placeholder runtime morph shader generated by Bone Importer.
// The project-specific build should replace this with the EFMI packed-normal implementation.
StructuredBuffer<uint4> BaseVB : register(t0);
StructuredBuffer<uint4> MorphStatic : register(t1);
StructuredBuffer<uint4> MorphAnim : register(t2);
StructuredBuffer<uint4> MasterPlayback : register(t3);
RWStructuredBuffer<uint4> RuntimeVB : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint vertex_id = id.x;
    uint vertex_count = MorphStatic[0].y;
    if (vertex_id >= vertex_count) return;
    RuntimeVB[vertex_id] = BaseVB[vertex_id];
}
""",
    "apply_morph_to_vb_pnta40_cs.hlsl": r"""#include "apply_morph_to_vb_cs.hlsl"
""",
}


def write_runtime_hlsl_files(output_directory: str) -> tuple[str, ...]:
    hlsl_dir = os.path.join(os.path.abspath(output_directory or "."), "hlsl")
    os.makedirs(hlsl_dir, exist_ok=True)
    paths = []
    for file_name, content in HLSL_FILES.items():
        path = os.path.join(hlsl_dir, file_name)
        with open(path, "w", encoding="utf-8", newline="\n") as hlsl_file:
            hlsl_file.write(content.strip() + "\n")
        paths.append(path)
    return tuple(paths)
