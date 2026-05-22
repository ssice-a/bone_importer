# RX Runtime Data Model

This document records the RX v2 target data structure. Bone Importer exports RX-local geometry buffers when requested, plus animation payloads. The runtime model is intentionally single-path:

```text
Bone animation = one DrawPart-local Bone Payload per IB/injected draw
Morph animation = one DrawPart-local Morph Payload when needed
Action switching = shared active_clip_index applied to every local payload
```

No global bone-pool compatibility path is part of RX v2.

## Design Goals

- Bone Importer exports RX-local geometry buffers when requested, plus Bone Payload and Morph Payload data. It still does not own textures, materials, LOD chains, or full mod packaging.
- An Animation Bank owns one shared playback state.
- An Animation Bank may contain multiple Clips.
- A DrawPart owns runtime targeting: `hash`, `match_index_count`, `first_index`, CB1 profile, route type, and its local Bone Payload.
- The decisive reason for local Bone Payloads is slot isolation: external models, replacement models, injected models, and native game models may all use different meanings for local slot `0`.
- Multi-Clip switching is still supported. The plugin switches every DrawPart-local Bone Payload and Morph Payload by the same `active_clip_index`.
- INI is generated from the Runtime Manifest, not from only the latest export pass.

## Minimal Concepts

```text
Animation Bank   = shared playback + clip table + DrawPart payloads
Clip             = one named playable action inside the bank
DrawPart         = target TextureOverride / IB / injected draw route
Bone Payload     = DrawPart-local, action-indexed TQ and bind data
Morph Payload    = DrawPart-local shape-key animation data
Manifest         = relationship map used to render INI
```

Anything outside those concepts is optional implementation detail.

## Why Local Bone Payloads

RX v2 uses local Bone Payloads instead of a single Global Bone Pool because a global pool solves action switching but creates a worse slot-semantics problem.

Examples:

```text
Native body DrawPart:
  local slot 0 = game numeric bone 0

Injected external model:
  local slot 0 = external armature bone Head

Replacement face model:
  local slot 0 = replacement model face bone 0
```

These meanings should not share one global bone namespace. A DrawPart-local Bone Payload keeps each route isolated:

```text
ResourceBonePalette_<draw_key>
ResourceBoneAnim_<draw_key>
ResourceBoneBind_<draw_key>
ResourceBoneStatic_<draw_key>
```

Action switching is handled by the shared playback state:

```text
active_clip_index = N
all DrawPart-local bone shaders sample clip N
all DrawPart-local morph shaders sample clip N
```

So switching two or more actions does not require a global bone pool. It requires every local payload to store the same Clip table semantics.

## Runtime Coordinate Contract

The Runtime Coordinate Contract is the single rule set that keeps replacement geometry, Bone Payload data, Morph Payload data, and generated HLSL in the same runtime space for the same DrawPart.

Current RX contract:

```text
name = RX_RUNTIME_YV_AXIS
position / normal / tangent = mirror Blender X into game X when Export Mirror X is enabled
UV = export adapter only: mirror U only when the DrawPart explicitly opts in
UV = export adapter only: flip V by default
bitangent sign = flip when exactly one of mirror-X or flip-V is active
skin matrix rows = YV row mapping:
    YV/EFMI axis conversion itself is not a mirror.
    RX-imported geometry mirror metadata belongs to geometry vector export
    and mirror-X skin-row conjugation before YV row mapping.
    game_row_0 =  blender_row_0
    game_row_1 =  blender_row_2
    game_row_2 = -blender_row_1
```

The Python truth source is:

```text
core/coordinate_contract.py
```

Callers must not inline their own copy of these rules. Geometry export uses the contract helpers for position, normal, tangent, UV mirroring/flipping, and bitangent handedness. Runtime HLSL is emitted through `rx_anim_coordinate_contract.hlsli`, generated from the same module. Keep geometry VB conversion, slot binding, and bone palette axis conversion explicit: YV/EFMI's axis change is not a mirror. RX mirror export is controlled by Bone Importer's explicit `bi_export_mirror_x` setting, default enabled. When enabled, geometry vectors are mirrored and final skin rows use `Mx * skin * Mx`; it never changes slot ids.

UV U mirroring is explicit:

```text
default Blender-to-game export: U unchanged, V flipped
explicit UV adapter:           U = 1 - U, V flipped
```

Do not infer U mirroring from `bi_export_mirror_x` or importer metadata. UV export is only a Blender-UV to game-UV adapter. Imported game meshes were already converted once to display correctly in Blender, so export applies the inverse adapter. External authored meshes also start from Blender-correct UVs and use the same game-format adapter.

Explicit Bone Importer export properties are the source of truth for a new
export:

```text
bi_export_uv_flip_v    wins over bmc_uv_flip_v
bi_export_uv_mirror_u  wins over bmc_uv_mirror_u
bi_export_mirror_x     wins over bmc_mirror_flip
```

Importer metadata is only fallback data for old scenes. The exporter must not
let stale helper flags override the values selected for the current RX package.

## Capture Manifest Dependency

RX Geometry Export depends on a user-provided `capture_manifest.json` for the game vertex layout table:

```text
Scene.bi_capture_manifest_path -> capture_manifest.json -> vertex_layout_table
```

This dependency is intentional. The manifest tells the exporter which VB slots, strides, semantics, and DXGI formats the target DrawPart expects. The path must be explicit UI configuration or an explicit automation override; it should not be inferred from hidden external-plugin state.

Slot ids are governed by the Slot Contract:

```text
target slot 0 writes runtime palette slot 0
target slot 1 writes runtime palette slot 1
...
```

For automatic Target Numeric Groups on BMC-imported mirrored meshes, the runtime slot remains unchanged and samples the same numeric source slot. Example: target runtime slot `0` writes palette slot `0` and samples source bone `0__<DrawPart>` when no explicit map is present.

3dmigoto-bone-merge mirrors imported vertex positions, normals, tangents, winding/handedness, and UV rules, but it preserves BLENDINDICES as numeric vertex groups. Bone Importer follows that contract: mirror import is a coordinate transform, not a vertex-group or bone-slot transform.

Explicit Bone Slot Map JSON always wins. Use it for replacement/external models or any DrawPart where the source rig intentionally differs from the target numeric slot namespace.

## Animation Bank Control

The bank owns shared time and active action selection.

Files:

```text
<bank>_timeline_static.buf
<bank>_master_playback.buf
```

`timeline_static.buf` uses `uint4` rows:

```text
row 0 = { clip_count, draw_part_count, default_clip_index, flags }
row 1..N = clip table, one row per Clip:
          { sample_count, default_ticks_per_sample, loop_start_sample, loop_end_sample }
```

`master_playback.buf` uses `uint4` rows:

```text
row 0 = { flags, previous_tick, current_tick, playback_tick }
row 1 = { ticks_per_sample, loop_start_sample, loop_end_sample, seek_tick }
row 2 = { seek_active, last_control_token, active_clip_index, queued_clip_index }
```

Runtime shaders resolve time from `active_clip_index` plus `current_tick`. When the UI switches Clip, it changes `active_clip_index` and resets or preserves tick according to the control command.

## DrawPart

A DrawPart is the runtime target matched by a TextureOverride or an injected draw route.

Required manifest fields:

```json
{
  "draw_key": "c3806ef1_8322_0",
  "hash": "c3806ef1",
  "match_index_count": 8322,
  "first_index": 0,
  "match_priority": -1000,
  "route": "REPLACE_MODEL",
  "cb1_profile": "NONE"
}
```

`route` defines how the TextureOverride behaves:

```text
PASSTHROUGH
  Do not bind RX bone data, geometry, or morph data. Let the game draw normally.

BONE_ONLY
  Keep the game model, but replace its bone palette through this DrawPart's Bone Payload.

REPLACE_MODEL
  Skip the original draw and draw replacement geometry with this DrawPart's Bone Payload.

INJECT_MODEL
  Do not skip the original draw. Draw extra replacement geometry with this DrawPart's Bone Payload.

MORPH_ONLY
  Apply morph data to a target VB without requiring a Bone Payload.
```

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
row 0 = { clip_count, bone_count, reserved_rows, slot_map_row_count }
row 1 = { palette_row_count, previous_palette_base, flags, clip_table_base }
row 2.. = clip table, one row per Clip:
          { sample_count, sample_row_base, loop_start_sample, loop_end_sample }
after clip table = packed local slot ids, four slot ids per row
```

`bone_anim.buf` uses `float4` rows and is action-indexed:

```text
[clip][sample][bone][2 rows]
row 0 = translation.xyz, 1
row 1 = quaternion.xyzw
```

`bone_bind.buf` uses `float4` rows:

```text
[bone][3 rows] = inverse bind affine rows
```

Runtime shader flow:

```text
active_clip_index from MasterPlayback
local clip row from BoneStatic
sample_a / sample_b / sample_alpha from local clip row + MasterPlayback
T = lerp(T_a, T_b, sample_alpha)
Q = normalized shortest-path lerp(Q_a, Q_b, sample_alpha)
pose = matrix_from_TQ(T, Q)
skin = pose * inverse_bind
skin = Runtime Coordinate Contract conversion
write current and previous local palette rows
```

The shader remains DrawPart-local:

```text
update_bone_palette_tq_cs.hlsl
```

It reads `active_clip_index` and samples the DrawPart-local clip table before loading TQ rows.

Exporter flow:

```text
DrawParts -> BoneSampleBank -> one Bone Payload per DrawPart
```

Performance rule:

```text
sample once by source-bone group, write many DrawPart-local payloads
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

`morph_anim.buf` must use the same `active_clip_index` as the Bone Payload:

```text
row 0 = { clip_count, channel_count, weights_per_row, flags }
row 1..N = clip table, one row per Clip:
          { sample_count, sample_row_base, source_frame_start, source_frame_step }
payload = [clip][sample][channel] fp16 weights, sample-major within each Clip
```

If a DrawPart has no morph for a Clip, either omit the Morph Payload for that DrawPart or write a clip-table entry with zero channels/effective zero weights.

The base vertex buffer is not exported by Bone Importer. It is an explicit DrawPart setting supplied by the user or external model export workflow.

## Runtime Manifest

The Runtime Manifest is the only source used to render INI. It must survive partial exports.

Example:

```json
{
  "format": "rx_runtime_manifest_v3",
  "animation_bank": {
    "name": "rxanimin",
    "timeline_static": "rxanimin_timeline_static.buf",
    "master_playback": "rxanimin_master_playback.buf"
  },
  "clips": [
    {
      "name": "idle",
      "clip_index": 0,
      "sample_count": 120,
      "fps": 30,
      "default_ticks_per_sample": 1
    },
    {
      "name": "dance",
      "clip_index": 1,
      "sample_count": 5671,
      "fps": 30,
      "default_ticks_per_sample": 1
    }
  ],
  "draw_parts": {
    "c3806ef1_8322_0": {
      "hash": "c3806ef1",
      "match_index_count": 8322,
      "first_index": 0,
      "match_priority": -1000,
      "route": "REPLACE_MODEL",
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

When a later export adds a Clip, it appends that Clip into each selected DrawPart-local payload. When a later export adds Morph Payload data, it updates only that DrawPart's morph entry.

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
5. draw, skip original draw only for REPLACE_MODEL
```

TextureOverride blocks must not bind unrelated DrawPart Bone Payloads.

## HLSL Changes

Keep:

```text
rx_anim_sampling.hlsli
rx_anim_coordinate_contract.hlsli
rx_anim_efmi_normal.hlsli
rx_anim_morph_common.hlsli
update_master_playback_cs.hlsl
update_bone_palette_tq_cs.hlsl
redirect_cb1_local_palette_cs.hlsl
update_panel_state_cs.hlsl
apply_morph_to_vb_cs.hlsl
apply_morph_to_vb_pnta40_cs.hlsl
panel_sprite.hlsl
panel_digits.hlsl
```

Modify:

```text
update_bone_palette_tq_cs.hlsl
  read active_clip_index
  read local clip table from bone_static
  sample [clip][sample][bone]

apply_morph_to_vb_cs.hlsl / apply_morph_to_vb_pnta40_cs.hlsl
  read active_clip_index
  read local clip table from morph_anim
  sample [clip][sample][channel]

update_master_playback_cs.hlsl
  preserve and update active_clip_index in row2.z
```

Remove from RX v2:

```text
global bone pool
shared bone namespace across DrawParts
part_id as authoring input
```

## UI Requirements

The UI controls only the Animation Bank playback state.

Required UI behavior:

```text
enable / disable animation
play / pause
replay
cycle speed
drag seek bar
switch active Clip
show progress from MasterPlayback
```

YV-style panel input and drawing can be reused, but the state shader must read:

```text
ResourceTimelineStatic
ResourceMasterPlayback_SRV
```

The UI must not know how many DrawParts, Bone Payloads, or Morph Payloads exist.

## Not In Scope

- automatic base VB inference from TheHerta INI
- global bone pool
- using Blender mesh object names as runtime identity except through DrawPart parsing
- duplicating playback state inside Bone Payload or Morph Payload files
- exporting textures, materials, LOD chains, or complete mod packaging

## Migration Plan

1. Done: keep one Bone Payload per DrawPart as the RX v2 bone route.
2. Done: upgrade Bone Payload files from single-Clip headers to local multi-Clip table layout.
3. Done: upgrade TimelineStatic and MasterPlayback with `active_clip_index`.
4. Done: extend `update_bone_palette_tq_cs.hlsl` to sample local multi-Clip payloads.
5. Next: extend Morph Payload animation to the same multi-Clip model.
6. Keep INI resource generation DrawPart-local for bone and morph resources.
7. Add route handling for `PASSTHROUGH`, `BONE_ONLY`, `REPLACE_MODEL`, `INJECT_MODEL`, and `MORPH_ONLY`.
8. Delete any new global-pool implementation work from the RX v2 route.
