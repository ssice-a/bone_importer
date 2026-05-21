# Bone Importer Context

Bone Importer exports RX runtime packages for EFMI/3DMigoto mods: replacement geometry buffers when requested, Blender-evaluated Bone Payload data, Morph Payload data, and generated runtime INI/HLSL. External tools or frame analysis still provide game capture metadata such as vertex layouts.

## Language

**Clip**:
A named playable action inside an Animation Bank. Every DrawPart-local Bone Payload and Morph Payload uses the same Clip index so UI action switching stays synchronized.
_Avoid_: animation file, mesh animation

**Animation Bank**:
The exported runtime package that contains one or more Clips, one shared playback state, DrawPart-local Bone Payloads, and DrawPart-local Morph Payloads.
_Avoid_: single animation, ini package

**DrawPart**:
One runtime draw target matched by a TextureOverride, normally identified by `hash`, `match_index_count`, and `first_index`.
_Avoid_: mesh, object, part id

**DrawPart Bone Pool**:
The per-DrawPart runtime bone palette for one IB or injected draw route. It keeps local slot semantics isolated, so external-model slots never collide with native game-model slots.
_Avoid_: global bone namespace, shared slot semantics

**Bone Payload**:
The per-DrawPart, action-indexed TQ and bind data that updates that DrawPart's Bone Pool.
_Avoid_: global palette segment, shared bone file

**Morph Payload**:
The per-DrawPart shape-key animation data that updates a target vertex buffer before skinning.
_Avoid_: mesh export, model export

**Runtime Coordinate Contract**:
The shared Blender-to-game coordinate rules that must be used by replacement geometry export, Bone Payload runtime HLSL, and Morph Payload runtime HLSL for the same DrawPart.
_Avoid_: local mirror fix, one-off axis conversion

UV mirroring belongs to this contract too. U mirroring is explicit metadata for replacement geometry; it is not inferred from X-axis mesh mirroring because imported game meshes must round-trip without changing UV identity.

UV export is a game-format adapter, not a Blender display preference. The exported `vb1` values must match the target game's captured UV convention for that DrawPart. Importer metadata such as `bmc_uv_flip_v` is only a fallback for old scenes; explicit Bone Importer export properties such as `bi_export_uv_flip_v` are the source of truth for a new export.

**Slot Contract**:
The DrawPart-local runtime slot namespace that decides which source bone writes each game palette slot. Runtime slot ids always keep their numeric meaning; BMC-imported mirror metadata is handled by the Runtime Coordinate Contract, not by automatic source-bone matching. Explicit Bone Slot Map entries are the only supported way to make a non-identity source binding.
_Avoid_: global slot namespace, hidden cross-DrawPart slot sharing

**IB Collection**:
The Blender collection named `<hash>-<match_index_count>-<first_index>` that carries one runtime DrawPart context. Mesh objects placed directly inside it form implicit `part00`; explicit `partNN` children create separate part buffer sets.
_Avoid_: source folder, attach folder, object-name routing

An IB Collection should contain only the mesh objects the user intends to export for that DrawPart. Prepared helper meshes may be used internally as Slot Adapters, but they should not be part of the user's visible export collection unless the user is intentionally exporting that helper mesh.

**Draw Segment**:
One runtime `drawindexed` range inside an exported part. A mesh object normally becomes one Draw Segment; segments in the same part share the merged VB/IB but may bind different final palettes.
_Avoid_: separate object buffer, global part id

**Before Stage**:
The update/compute portion of the target TextureOverride. It updates every palette and runs every morph/pre-skin CS needed by the IB Collection before any replacement Draw Segment is issued or the original draw is kept.
_Avoid_: source-only route, object identity classifier

**After Stage**:
A legacy/internal timing label for late replacement draw emission. RX Export v3 user-facing design should prefer Draw Segment and IB Collection terminology instead of asking users to classify objects as After.
_Avoid_: attach route, external object classifier

**Pre-Skin Deformer**:
A Before Stage compute route that writes a runtime vertex buffer before final skinning and Draw Segment emission. Morph and bone pre-skin both write into the exported DrawVB chain.
_Avoid_: implicit morph-before-bone behavior, ad-hoc pre-skin compute passes

**Runtime Manifest**:
The persistent relationship map between an Animation Bank, its Clips, DrawParts, DrawPart-local Bone Payloads, and DrawPart-local Morph Payloads.
_Avoid_: generated ini, clip manifest

**Bone-Only Animation**:
An animation route that only replaces runtime bone data for an existing GPU-skinned draw.
_Avoid_: model animation

**Replacement Skinned Model**:
An animation route where replacement geometry buffers use Bone Payload data, and optionally Morph Payload data, at runtime. Bone Importer may export the RX-local IB/VB buffers, but it does not own materials, textures, LOD chains, or full mod packaging.
_Avoid_: CPU skinning export

**Capture Manifest**:
The user-supplied `capture_manifest.json` that provides the game vertex layout table used by RX Geometry Export. It is a required dependency for writing game-compatible VB/IB buffers, and its path should be explicit UI configuration.
_Avoid_: hidden hardcoded layout path, implicit external-plugin state

**Slot Adapter**:
A temporary or helper mesh that supplies game-compatible numeric vertex groups for RX Geometry Export while the visible source mesh supplies the actual geometry, UVs, and shape keys.
_Avoid_: user-facing duplicate export mesh, hidden replacement object

**Morph-Only Animation**:
An animation route that only applies Morph Payload data to a target vertex buffer while sharing the Clip timeline.
_Avoid_: shape-key mesh export

## Relationships

- An **Animation Bank** has one shared playback state.
- An **Animation Bank** may contain one or more **Clips**.
- A **DrawPart** may have zero or one **DrawPart Bone Pool** for the **Animation Bank**.
- A **DrawPart Bone Pool** is action-indexed by the shared Clip index.
- A **DrawPart** may have zero or one **Morph Payload** for the **Animation Bank**.
- A **Runtime Manifest** records many **DrawParts** under one **Animation Bank**.
- A **Runtime Coordinate Contract** must be shared by every runtime payload and any replacement geometry bound to the same **DrawPart**.
- A **Slot Contract** is separate from the **Runtime Coordinate Contract**: geometry mirror changes vector values and final skin rows, while slot ids remain semantic ids.
- A **Replacement Skinned Model** may be exported through Bone Importer's RX Geometry Export, using a user-supplied **Capture Manifest** for game layout semantics.
- A **Morph Payload** may coexist with a **DrawPart Bone Pool**, but does not depend on one.
- An **IB Collection** owns one runtime **DrawPart** context.
- An **IB Collection** may export zero or more **Draw Segments**.
- If an **IB Collection** exports any geometry, the original game draw for that **DrawPart** is skipped.
- A **Draw Segment** consumes the final DrawVB/DrawIB range and whichever final palette its vertex weights target.
- A **Pre-Skin Deformer** always runs in the **Before Stage** and prepares DrawVB ranges for later **Draw Segments**.
- A **Slot Adapter** may be used to write `vb2` correctly, but the visible source mesh remains the Draw Segment identity and morph source.

## Example Dialogue

> **Dev:** "This object needs shape keys but no game bone override. Is it a DrawPart?"
> **Domain expert:** "Yes. It still needs a DrawPart because the Morph Payload must know which TextureOverride receives the runtime vertex buffer."

## Flagged Ambiguities

- "part" previously meant both global palette slice and draw target. Resolved: use **DrawPart** for the draw target, and avoid global slice terminology in the new design.
- "mesh key" previously identified both Blender source objects and runtime resources. Resolved: use **DrawPart** for runtime identity and explicit source objects for Blender authoring inputs.
- A global bone pool was considered and rejected for RX v2. The decisive reason is slot semantics: external models, replacement models, and native game models may all use different local slot meanings, so one IB should own one Bone Payload. Multi-Clip switching is handled by giving every DrawPart-local Bone Payload the same `active_clip_index`.
- Before/After previously meant "bone-only before" and "draw-only after". Resolved for RX Export v3: user-facing routing is no longer Before/After. Use **IB Collection**, **partNN**, and **Draw Segment**. The Before Stage is only the update/compute phase.
