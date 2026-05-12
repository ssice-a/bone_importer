# RX Morph v1

This document records the current `v1` implementation direction for shape-key export in `bone_importer`.

## Goals

Morph export follows the same family as the RX bone-animation sidecars:

- fixed `uint4` header rows
- mesh-local static payload buffers
- no per-mesh playback state
- one shared actor-level playback source
- one shared tick-to-sample helper for bone and morph shaders

## Scope

- `TheHerta3` remains responsible for the replacement mesh, VB, and IB.
- `bone_importer` exports only morph-specific sidecars.
- Bone animation and morph animation stay data-level decoupled.
- Both systems share:
  - `<clip>_timeline_static.buf`
  - `<clip>_master_playback.buf`

Morph buffers do not duplicate playback flags, loop state, or current-time state.
Those semantics live only in the shared RX timeline/master-playback pair.

## Terms

The runtime now treats these words as distinct:

- `source_frame`: Blender authoring-frame number used only for export metadata
- `sample`: one exported discrete animation sample
- `tick`: one runtime Present step
- `ticks_per_sample`: how many runtime ticks are spent inside one exported sample
- `sample_a / sample_b / sample_alpha`: the interpolated sample window resolved from the current tick

Bone and morph both resolve time through `rx_anim_sampling.hlsli`.

## File Set

The morph exporter writes one shared manifest plus two mesh-specific buffers:

- `<clip>_morph_manifest.json`
- `<mesh_key>_morph_static.buf`
- `<mesh_key>_morph_anim.buf`
- `<clip>_generated_overrides.ini`

`mesh_key` must match the `TheHerta3` export grouping unit, not a raw Blender object name.
For EFMI, that means the effective export unit is the final `unique_str`-style submesh grouping.

## Vertex Order Contract

`bone_importer` must match `TheHerta3`'s final unique-vertex order.

Important consequences:

- do not assume exported vertices are plain Blender `mesh.vertices` order
- follow loop-based extraction
- match the `(vertex_bytes + vertex_index)` uniqueness rule closely enough to align with the exported base buffer
- keep shape-key extraction aligned to the final unique vertex order used by `TheHerta3`

This is the contract that lets us avoid writing a separate remap file.

## Generated INI Snippet

Animation export also writes a best-effort RX runtime snippet:

- `<clip>_generated_overrides.ini`

It contains:

- `ResourceClipTQS_* / ResourceClipBind_* / ResourceClipStatic_*`
- `ResourceMorphStatic_* / ResourceMorphAnim_* / ResourceMorphRuntimeVB_*` when morph data exists
- one `TextureOverride_RX_*` block per exported mesh key

The file is meant to be merged into a hand-maintained runtime ini.
Common shared resources and global shaders still live in the main runtime package.

## Morph Static Buffer

`<mesh_key>_morph_static.buf` is the mesh-specific shape-key payload.

It uses the same `uint4` header style as the bone clip sidecars:

```text
row 0: { channel_count, vertex_count, span_count, influence_count }
row 1: { flags, normal_mode, span_row_count, influence_row_count }
row 2: { max_influences_per_vertex, influence_row_stride, reserved, reserved }
```

Current flag plan:

- bit `0`: position deltas present
- bit `1`: normal targets present

Current encoding plan:

- `normal_mode = 1`: EFMI `vb0` normal uses octahedral-encoded `R32_UINT`
- `v1` can additionally carry `key=1` tangent targets for explicit `P12+N12+TA16`-style Position layouts
- tangent targets are only emitted when normal targets are also enabled

Rows after the header are:

- one span row per exported vertex
- one or two influence rows per active channel/vertex pair, depending on whether tangent targets are present

The runtime model is fixed:

- one thread per exported unique vertex
- read the base vertex from `TheHerta3`'s Position buffer
- accumulate all active shape-key influences for that vertex
- rewrite the runtime VB using the layout required by that mesh's Position buffer

## Morph Animation Buffer

`<mesh_key>_morph_anim.buf` stores only shape-key weights, not per-frame geometry.

The header also follows the same `uint4` style:

```text
row 0: { channel_count, sample_count, baked_weight_row_count, weights_per_row }
row 1: { clip_id, source_frame_start, source_frame_step, reserved }
```

`v1` sampling mode is:

- bake evaluated shape-key weights per exported sample
- do not trust raw FCurves
- treat drivers, NLA, and other evaluation layers as part of the final result
- default export mode is `Animated Channels`, which only keeps channels whose evaluated weights actually change across the sampled clip
- `All Channels` can be used when every non-basis shape key should be exported regardless of animation activity

Playback still comes from the shared actor-level buffer, not from the morph buffer itself:

- `current_tick` is read from `<clip>_master_playback.buf`
- `ResolveTickToSampleWindow(...)` resolves `sample_a / sample_b / sample_alpha`
- morph weights are interpolated exactly like the bone clip timing path

This keeps morph and bone synchronized under play, pause, replay, seek, and different `ticks_per_sample` values.

## Normal Strategy

The working plan is:

- read base normal from the exported base Position buffer
- export one `key=1` normal target per active shape-key influence
- mix normals in morph CS using the interpolated shape-key weights
- normalize the final normal and encode it back into EFMI packed-normal form

This is a high-quality runtime approximation that keeps the format compact while staying much closer to Blender than a pure position-only path.

For explicit `P12+N12+TA16` layouts such as eyelashes, the exporter can also write `key=1` tangent targets.
That route is selected in runtime by binding a different morph shader in the target `TextureOverride`, not by adding a game-format enum to `bone_importer`.
Because explicit tangent layouts are rarer than packed-normal layouts, tangent target export stays disabled by default and is only enabled manually when a mesh actually needs it.

## Shared HLSL Helpers

Shared runtime helpers are centralized so bone and morph do not drift:

- `rx_anim_sampling.hlsli`
  - flag constants
  - loop clamping
  - tick-to-sample window resolution
- `rx_anim_efmi_normal.hlsli`
  - EFMI packed-normal decode/encode

`copy_clip_to_faket0_cs.hlsl` and `apply_morph_to_vb_cs.hlsl` include these helpers rather than duplicating logic.

## Previous-Frame Policy

`v1` does not require a dedicated previous-frame morph VB.

We still keep `previous_tick/current_tick` in the shared playback buffer, but the first implementation can:

- evaluate current-frame morph deformation only
- rely on the existing previous-bone palette path for the current game-side TAA behavior
- revisit a dedicated previous morph path later if expression-heavy shots show obvious ghosting

## Runtime Order

The intended runtime order remains:

1. sample morph weights from `<mesh_key>_morph_anim.buf`
2. deform the base mesh from `TheHerta3`
3. bind the deformed VB back to the game draw
4. apply the existing bone skinning path through `FakeT0/FakeCB1`

This keeps shape keys in pre-skin local space, which matches standard authoring semantics.
