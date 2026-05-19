# RX Runtime Data Model

This document records the target data structure for the Bone Importer refactor. The goal is to support Bone-Only Animation, Replacement Skinned Model animation, and Morph-Only Animation without making model export part of this plugin.

## Design Goals

- Bone Importer exports animation data, not replacement mesh data.
- A Clip owns time only.
- A DrawPart owns runtime targeting only.
- Bone Payload and Morph Payload are independent data payloads.
- INI is generated from the Runtime Manifest, not from only the latest export pass.
- The default bone runtime uses one local bone palette per DrawPart, not one global FakeT0 buffer sliced by `part_id`.

## Minimal Concepts

```text
Clip          = shared time
DrawPart      = target TextureOverride / IB
Bone Payload  = per-DrawPart TQ animation and bind data
Morph Payload = per-DrawPart shape-key data
Manifest      = relationship map used to render INI
```

Anything outside those concepts is optional implementation detail.

## Clip Control

The Clip is shared by every Bone Payload and Morph Payload in one exported animation.

Files:

```text
<clip>_timeline_static.buf
<clip>_master_playback.buf
```

`timeline_static.buf` uses `uint4` rows:

```text
row 0 = { sample_count, clip_fps, default_ticks_per_sample, 0 }
row 1 = { default_loop_start_sample, default_loop_end_sample, 0, 0 }
```

`master_playback.buf` uses `uint4` rows:

```text
row 0 = { flags, previous_tick, current_tick, playback_tick }
row 1 = { ticks_per_sample, loop_start_sample, loop_end_sample, seek_tick }
row 2 = { seek_active, last_control_token, 0, 0 }
```

Runtime shaders resolve time through `ResolveTickToSampleWindow(...)`.

## DrawPart

A DrawPart is the runtime target matched by a TextureOverride.

Required manifest fields:

```json
{
  "draw_key": "c3806ef1_8322_0",
  "hash": "c3806ef1",
  "match_index_count": 8322,
  "first_index": 0,
  "match_priority": -1000,
  "cb1_profile": "NONE"
}
```

`match_priority` defaults to `-1000` so the RX animation entry runs before later replacement/draw overrides. `draw_key` is the stable identity for resources and manifest entries. `part_id`, `part_base`, and global palette slice offsets are not part of the default design.

## Bone Payload

Bone Payload is local to one DrawPart.

Files:

```text
<draw_key>_bone_static.buf
<draw_key>_bone_anim.buf
<draw_key>_bone_bind.buf
```

Runtime resource:

```text
ResourceBonePalette_<draw_key>_UAV
ResourceBonePalette_<draw_key>
```

`bone_static.buf` uses `uint4` rows:

```text
row 0 = { bone_count, sample_count, reserved_rows, slot_map_row_count }
row 1 = { palette_row_count, previous_palette_base, flags, 0 }
row 2+ = packed slot ids, four slot ids per row
```

`previous_palette_base` is local to the DrawPart buffer. The default value is `palette_row_count`, so the runtime palette layout is:

```text
current palette  = rows 0 .. palette_row_count - 1
previous palette = rows palette_row_count .. palette_row_count * 2 - 1
```

`bone_anim.buf` uses `float4` rows:

```text
[sample][bone][2 rows]
row 0 = translation.xyz, 1
row 1 = quaternion.xyzw
```

`bone_bind.buf` uses `float4` rows:

```text
[bone][3 rows] = inverse bind affine rows
```

Runtime shader flow:

```text
sample_a / sample_b / sample_alpha from MasterPlayback
T = lerp(T_a, T_b, sample_alpha)
Q = normalized shortest-path lerp(Q_a, Q_b, sample_alpha)
pose = matrix_from_TQ(T, Q)
skin = pose * inverse_bind
write current and previous local palette rows
```

The shader should be named `update_bone_palette_tq_cs.hlsl`. It replaces the old global-slice `copy_clip_to_faket0_cs.hlsl` path.

Exporter flow:

```text
DrawParts -> BoneSampleBank -> per-DrawPart Bone Payload files
```

`BoneSampleBank` is the exporter-side sampling module. It groups DrawParts by compatible correction mode, deduplicates source bones inside each group, samples each unique source bone once per Clip sample, then slices the shared sample matrix back into each DrawPart's slot order. This preserves local Bone Payload files while avoiding repeated Blender `frame_set`/pose evaluation for the same source bones.

Performance rule:

```text
sample once by source-bone group, write many DrawPart payloads
```

## Morph Payload

Morph Payload is local to one DrawPart and independent from Bone Payload.

Files:

```text
<draw_key>_morph_static.buf
<draw_key>_morph_anim.buf
```

Runtime resource:

```text
ResourceMorphRuntimeVB_<draw_key>_UAV
ResourceMorphRuntimeVB_<draw_key>
```

`morph_static.buf` uses `uint4` rows:

```text
row 0 = { channel_count, vertex_count, span_count, influence_count }
row 1 = { flags, normal_mode, span_row_count, influence_row_count }
row 2 = { max_influences_per_vertex, influence_row_stride, 0, 0 }
row 3+ = span rows
after spans = influence rows
```

Each influence stores:

```text
channel_index
delta_position packed as fp16
normal_at_1 packed as EFMI R32_UINT when enabled
optional tangent target rows for explicit PNTA40 layouts
```

`morph_anim.buf` uses `uint4` rows:

```text
row 0 = { channel_count, sample_count, baked_weight_row_count, weights_per_row }
row 1 = { 0, source_frame_start, source_frame_step, 0 }
payload = sample-major fp16 weights
```

The base vertex buffer is not exported by Bone Importer. It is an explicit DrawPart setting supplied by the user or external model export workflow.

## Runtime Manifest

The Runtime Manifest is the only source used to render INI. It must survive partial exports.

Example:

```json
{
  "format": "rx_runtime_manifest_v1",
  "clip": {
    "name": "rxanimin",
    "sample_count": 120,
    "fps": 60,
    "timeline_static": "rxanimin_timeline_static.buf",
    "master_playback": "rxanimin_master_playback.buf"
  },
  "draw_parts": {
    "c3806ef1_8322_0": {
      "hash": "c3806ef1",
      "match_index_count": 8322,
      "first_index": 0,
      "match_priority": -1000,
      "cb1_profile": "NONE"
    }
  },
  "payloads": {
    "c3806ef1_8322_0": {
      "bone": {
        "static": "c3806ef1_8322_0_bone_static.buf",
        "anim": "c3806ef1_8322_0_bone_anim.buf",
        "bind": "c3806ef1_8322_0_bone_bind.buf",
        "palette_row_count": 96
      },
      "morph": {
        "static": "c3806ef1_8322_0_morph_static.buf",
        "anim": "c3806ef1_8322_0_morph_anim.buf",
        "base_vb": "Buffer/c3806ef1-8322-0-Position.buf",
        "base_stride": 16
      }
    }
  }
}
```

When a later export adds or replaces one payload, it updates only that `draw_key` entry.

## INI Rendering

Generated INI must be manifest-driven.

Global resources:

```ini
ResourceTimelineStatic
ResourceMasterPlayback
ResourceMasterPlayback_SRV
CustomShader_UpdateMasterPlayback
CustomShader_UpdateRXPanelState
```

Per-DrawPart resources are emitted only when the payload exists.

Bone route:

```ini
ResourceBoneStatic_<draw_key>
ResourceBoneAnim_<draw_key>
ResourceBoneBind_<draw_key>
ResourceBonePalette_<draw_key>_UAV
ResourceBonePalette_<draw_key>
ResourceFakeCB1_<draw_key>_UAV
ResourceFakeCB1_<draw_key>
```

Morph route:

```ini
ResourceMorphStatic_<draw_key>
ResourceMorphAnim_<draw_key>
ResourceMorphRuntimeVB_<draw_key>_UAV
ResourceMorphRuntimeVB_<draw_key>
```

TextureOverride order:

```text
1. if Morph Payload exists, run morph pass and bind runtime VB
2. if Bone Payload exists, run local bone palette pass
3. if Bone Payload exists, redirect cb1 to local palette offsets
4. bind local bone palette to vs-t0 and local fake cb1 to vs-cb1
5. draw
```

TextureOverride blocks should not rely on global `part_id` or global FakeT0 slices.

## HLSL Changes

Keep:

```text
rx_anim_sampling.hlsli
rx_anim_efmi_normal.hlsli
rx_anim_morph_common.hlsli
update_master_playback_cs.hlsl
update_panel_state_cs.hlsl
apply_morph_to_vb_cs.hlsl
apply_morph_to_vb_pnta40_cs.hlsl
panel_sprite.hlsl
panel_digits.hlsl
```

Replace:

```text
copy_clip_to_faket0_cs.hlsl -> update_bone_palette_tq_cs.hlsl
redirect_cb1_with_static_clip_cs.hlsl -> redirect_cb1_local_palette_cs.hlsl
```

Remove from the default route:

```text
global FakeT0 buffer
part_base
previous_offset as global buffer offset
part_id based global slicing
```

## UI Requirements

The UI controls only `MasterPlayback`. It must not know how many DrawParts, Bone Payloads, or Morph Payloads exist.

Required UI behavior:

```text
enable / disable animation
play / pause
replay
cycle speed
drag seek bar
show progress from MasterPlayback
```

YV-style panel input and drawing can be reused, but the state shader must read:

```text
ResourceTimelineStatic
ResourceMasterPlayback_SRV
```

It must not read a per-part animation metadata buffer.

## Not In Scope

- exporting replacement meshes, IBs, VBs, textures, or materials
- automatic base VB inference from TheHerta INI
- global palette slice management as the default route
- using Blender mesh object names as runtime identity except through DrawPart parsing
- duplicating playback state inside Bone Payload or Morph Payload files

## Migration Plan

1. Add Runtime Manifest read/write as the source of truth.
2. Replace proxy-armature-shaped export targets with DrawPart-shaped targets.
3. Change bone export to write per-DrawPart `bone_static`, `bone_anim`, and `bone_bind`.
4. Add local bone palette HLSL and local cb1 redirect HLSL.
5. Change INI generation to render from the Runtime Manifest.
6. Keep morph buffers independent and bind them by DrawPart.
7. Move old palette import/export into Debug or Legacy tools.
