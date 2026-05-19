# Bone Importer Context

Bone Importer exports runtime animation data for EFMI/3DMigoto mods. It does not own replacement mesh export; it connects Blender-evaluated animation data to runtime draw targets.

## Language

**Clip**:
A shared runtime timeline used by every animation payload in one exported animation.
_Avoid_: animation file, mesh animation

**DrawPart**:
One runtime draw target matched by a TextureOverride, normally identified by `hash`, `match_index_count`, and `first_index`.
_Avoid_: mesh, object, part id

**Bone Payload**:
The per-DrawPart bone animation data that updates the local runtime bone palette.
_Avoid_: FakeT0 slice, global palette segment

**Morph Payload**:
The per-DrawPart shape-key animation data that updates a target vertex buffer before skinning.
_Avoid_: mesh export, model export

**Runtime Manifest**:
The persistent relationship map between a Clip, DrawParts, and their Bone Payload or Morph Payload files.
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

- A **Clip** has one shared playback state.
- A **DrawPart** may have zero or one **Bone Payload** for a Clip.
- A **DrawPart** may have zero or one **Morph Payload** for a Clip.
- A **Runtime Manifest** records many **DrawParts** under one **Clip**.
- A **Replacement Skinned Model** is exported by an external model tool, not by Bone Importer.
- A **Morph Payload** may coexist with a **Bone Payload**, but does not depend on one.

## Example Dialogue

> **Dev:** "This object needs shape keys but no game bone override. Is it a DrawPart?"
> **Domain expert:** "Yes. It still needs a DrawPart because the Morph Payload must know which TextureOverride receives the runtime vertex buffer."

## Flagged Ambiguities

- "part" previously meant both global palette slice and draw target. Resolved: use **DrawPart** for the draw target, and avoid global slice terminology in the new design.
- "mesh key" previously identified both Blender source objects and runtime resources. Resolved: use **DrawPart** for runtime identity and explicit source objects for Blender authoring inputs.
