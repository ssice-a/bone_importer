# Bone Importer Context

Bone Importer exports runtime animation data for EFMI/3DMigoto mods. It does not own replacement mesh export; it connects Blender-evaluated animation data to runtime draw targets.

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

**Slot Contract**:
The DrawPart-local runtime slot namespace that decides which source bone writes each game palette slot. Coordinate mirror flags do not alter slot ids; non-identity slot binding must be authored as an explicit Bone Slot Map.
_Avoid_: inferred mirror slot swap, centroid-based slot guess

**Runtime Manifest**:
The persistent relationship map between an Animation Bank, its Clips, DrawParts, DrawPart-local Bone Payloads, and DrawPart-local Morph Payloads.
_Avoid_: generated ini, clip manifest

**Bone-Only Animation**:
An animation route that only replaces runtime bone data for an existing GPU-skinned draw.
_Avoid_: model animation

**Replacement Skinned Model**:
An animation route where an externally exported replacement model uses Bone Payload data, and optionally Morph Payload data, at runtime.
_Avoid_: CPU skinning export

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
- A **Slot Contract** is separate from the **Runtime Coordinate Contract**: geometry mirror changes coordinates, not bone slot identity.
- A **Replacement Skinned Model** is exported by an external model tool, not by Bone Importer.
- A **Morph Payload** may coexist with a **DrawPart Bone Pool**, but does not depend on one.

## Example Dialogue

> **Dev:** "This object needs shape keys but no game bone override. Is it a DrawPart?"
> **Domain expert:** "Yes. It still needs a DrawPart because the Morph Payload must know which TextureOverride receives the runtime vertex buffer."

## Flagged Ambiguities

- "part" previously meant both global palette slice and draw target. Resolved: use **DrawPart** for the draw target, and avoid global slice terminology in the new design.
- "mesh key" previously identified both Blender source objects and runtime resources. Resolved: use **DrawPart** for runtime identity and explicit source objects for Blender authoring inputs.
- A global bone pool was considered and rejected for RX v2. The decisive reason is slot semantics: external models, replacement models, and native game models may all use different local slot meanings, so one IB should own one Bone Payload. Multi-Clip switching is handled by giving every DrawPart-local Bone Payload the same `active_clip_index`.
