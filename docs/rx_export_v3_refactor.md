# RX Export v3 Refactor

This document records the agreed semantics for the next major RX export
refactor. It is intentionally a planning document: do not treat every section as
already implemented.

## Goal

RX Export v3 should keep the user's mental model small:

```text
Put objects under IB collections -> choose one Export Type -> Export.
```

Bone Importer owns RX-local geometry buffer export, Bone Payload export, Morph
Payload export, Runtime Manifest generation, and runtime INI/HLSL generation.
The user still provides the game `capture_manifest.json` path because it is the
source of truth for runtime vertex layouts.

The bone runtime remains DrawPart-local:

```text
one IB / DrawPart -> one local Bone Payload / palette domain
```

Do not reintroduce a global bone pool in v3. Local payloads avoid slot collisions
between native game models, replacement models, and external mounted models.
Clip switching is handled by generating the same clip table semantics for every
local payload, not by merging all bones into one global namespace.

## Collection Model

Use one root collection:

```text
RX Export Collection
  <hash>-<match_index_count>-<first_index>
    mesh objects...                 -> implicit part00

  <hash>-<match_index_count>-<first_index>
    part00
      mesh objects...
    part01
      mesh objects...
```

Each child collection is one runtime IB / DrawPart. The child collection name is
the runtime identity.

Borrow the BMC export collection convention:

```text
<hash>-<count>-<first>
  direct meshes      -> implicit part00

<hash>-<count>-<first>
  part00
    meshes
  part01
    meshes
```

If explicit `partNN` children exist, direct mesh objects under the IB collection
are not allowed. This keeps collection structure unambiguous.

The IB collection itself carries the runtime context:

```text
hash
match_index_count
first_index
capture layout
slot contract
```

Objects inside the IB collection are export inputs. There is no separate
`Source` / `Attach` / `Reference` child collection in v3.

An IB collection should contain only the visible mesh objects the user intends
to export for that DrawPart. If a mesh needs game-compatible numeric vertex
groups but the visible source mesh keeps authoring names, use a Slot Adapter:

```text
Visible Source Mesh -> geometry, UVs, normals/tangents, shape keys, draw name
Slot Adapter        -> temporary numeric vertex groups / final vb2 mapping
```

The Slot Adapter is an implementation detail. Export may create a temporary
copy of the visible source mesh, copy numeric groups from the adapter, run RX
Geometry Export, then restore the collection to the visible source mesh. Runtime
manifests and generated INI must name the visible source mesh, not the temporary
adapter.

Default geometry layout:

```text
IB collection -> implicit part00 -> one merged VB/IB buffer set
each mesh object -> one draw segment / drawindexed range
```

Explicit `partNN` children create additional buffer sets. Direct mesh objects on
the IB collection are invalid when explicit `partNN` children exist.

Within one part:

- merge mesh objects into one VB/IB set
- keep one draw segment per mesh object
- do not merge vertices across draw segments, because segments may use different
  final palettes
- each draw segment records `vertex_start`, `vertex_count`, `index_start`, and
  `index_count`

Any exported geometry inside an IB collection means the original game draw for
that IB is skipped. If an IB collection has no exported geometry, the original
draw is kept and only Bone Payload data may be updated.

## Draw Stages

Before and After are stage/data-domain semantics, not simple "draw/no draw"
labels.

The stable mental model is:

```text
Before = update / compute stage
After  = late draw / injection stage
```

### Before Stage

Before means update / compute work that must happen before the matched game draw
or replacement draw.

Rules:

- Before uses an early `match_priority`, normally negative.
- Before updates all palettes required by the IB collection's draw segments.
- Before runs all morph and PreSkinBone CS required by the IB collection's draw
  segments.
- Before may keep the original draw when no replacement geometry is exported.
- Before skips the original draw when replacement geometry is exported.
- Pre-Skin deformation runs in Before. This includes morph CS and bone pre-skin
  CS.

### Draw Segments

Draw segments are the runtime replacement draw ranges produced from exported
mesh objects.

Rules:

- One mesh object normally becomes one draw segment.
- All draw segments in one part bind the same merged VB/IB buffer set.
- Each draw segment may bind its own `FinalBonePalette` / `FinalFakeCB1`.
- Draw segments issue `drawindexedinstanced` with their own index range.
- If no geometry is exported for an IB collection, no replacement draw segments
  are emitted.

### Pre-Skin Deformer

Pre-Skin Deformer is a v3 route that writes a runtime vertex buffer before the
final skinning/draw step.

Examples:

```text
external-bone pre-skin -> source/game skin -> final draw segment
morph pre-skin         -> source/game skin -> final draw segment
```

All CS deform passes run in Before. Draw segments consume the prepared `DrawVB`.

The fixed order is:

```text
BaseVB -> optional Morph -> optional PreSkinBone -> DrawVB -> Final Skin
```

Morph always runs before PreSkinBone. v3 does not expose an option to reorder
them.

When both morph and PreSkinBone exist, a middle buffer is required:

```text
BaseVB -> MorphTempVB -> DrawVB
```

Do not read and write the same vertex buffer in one deform chain. Replay, seek,
pause, and speed changes must always recompute from a clean base buffer.

## Object Route Resolution

Each mesh object under an IB collection resolves into a draw segment descriptor:

```text
object_id
draw_part_key
part_index
segment_index
vertex_start
vertex_count
index_start
index_count
deform_chain = NONE / MORPH / PRESKIN_BONE / MORPH_THEN_PRESKIN_BONE
final_skin_palette = SOURCE_GAME / OWN
final_armature
preskin_armature
preskin_action
```

Effective vertex groups are scanned after ignoring empty groups. The scan
decides what the segment can bind:

```text
source/game slot groups -> SOURCE_GAME final skin is available
own armature groups     -> OWN final skin is available
PreSkinBone settings    -> PreSkinBone is requested
```

Route resolution:

- If final draw uses source/game slot groups, `final_skin_palette = SOURCE_GAME`.
- If final draw uses an object's own armature groups, `final_skin_palette = OWN`.
- If both are possible and PreSkinBone is disabled, prefer the explicit object
  setting; otherwise report ambiguity.
- If PreSkinBone is enabled, final skin must be `SOURCE_GAME`.
- PreSkinBone without SOURCE_GAME final mapping is an error. Ask the user to add
  target IB-compatible final draw groups or a Final Bone Slot Map.

Geometry requirement:

```text
geometry_required =
  final_skin_palette == OWN
  or morph_payload_enabled
  or preskin_bone_enabled
  or user_force_replace_geometry
```

If no mesh object in the IB collection requires geometry, export only Bone
Payload data and keep the original game draw.

## Export Type

Use one dropdown plus one Export button.

Final v3 export types:

```text
Full RX Package
  Export selected payloads, optional geometry, Runtime Manifest, INI, and HLSL.

Bone Payload Only
  Update bone animation buffers and related manifest entries.

Morph Payload Only
  Update morph buffers and related manifest entries.

INI Only
  Regenerate executable INI/HLSL from the existing Runtime Manifest.
```

There is no standalone `Geometry Only` export type. Geometry export is controlled
by a separate checkbox:

```text
Export Geometry = true by default
```

If an export needs geometry and `Export Geometry` is enabled, geometry is
exported/refreshed. If an export needs geometry and `Export Geometry` is
disabled, the exporter must use existing manifest geometry or report a clear
error.

Every export type must still leave an executable runtime package when possible.
Partial exports merge into the Runtime Manifest and preserve payloads that were
not touched by the current export. A later Bone-only or Morph-only export must
not delete geometry, INI routes, or unrelated payloads from a previous Full
export.

Normal exports do not delete missing DrawParts. Destructive cleanup belongs to a
future explicit `Clean Manifest / Prune Missing` command.

## Required UI Inputs

Global export settings:

```text
Output Dir
Capture Manifest
RX Export Collection
Export Type
Export Geometry
Frame Start
Frame End
Frame Step
Source FPS
Target Game FPS
Playback Speed
```

Defaults:

```text
Frame Start / End = Blender scene frame range
Frame Step        = 1
Source FPS        = scene.render.fps
Target Game FPS   = 120
Playback Speed    = 1.0
Export Geometry   = enabled
```

Preview-only UI:

```text
IB Collection Preview
  part count
  draw segment count
  geometry_required yes/no
  original draw keep/skip
  palette count
  morph segment count
  PreSkinBone segment count
```

The preview lists should be collapsible. Show simple counts by default; expose
per-object classification and manual overrides only inside the folded details.

Avoid exposing route names such as `Bone Only`, `Morph Only`, `Replace Model`, or
`Inject Model` as primary user choices.

Object advanced settings:

```text
Final Skin:
  Auto / Source Game / Own

Pre-Skin Bone:
  Disabled / Enabled

Pre-Skin Armature:
  Armature picker

Pre-Skin Action:
  Auto Current / Action picker
```

`Overlay On Game Skeleton` is the user-facing mode for bone pre-skin:

```text
selected action -> PreSkinBone CS -> DrawVB -> SOURCE_GAME final skin
```

PreSkinBone is explicit and advanced. It is never inferred merely from an object
having an armature.

## Playback Timing

The user-facing control should be intuitive:

```text
Playback Speed = 1.0  -> normal speed
Playback Speed = 2.0  -> 2x speed
Playback Speed = 1.5  -> 1.5x speed
Playback Speed = 0.5  -> half speed
```

The exporter converts Blender samples into runtime game-frame stepping.

Recommended conversion:

```text
source_sample_fps = Source FPS / Frame Step
sample_step_per_game_frame = source_sample_fps * Playback Speed / Target Game FPS
sample_step_q16 = round(sample_step_per_game_frame * 65536)
```

Example:

```text
Source FPS = 30
Frame Step = 1
Target Game FPS = 120
Playback Speed = 1.0

sample_step_per_game_frame = 30 * 1.0 / 120 = 0.25
sample_step_q16 = 16384
```

This replaces the old integer-only `ticks_per_sample` mental model. The v3
runtime should use a fixed-point sample cursor so 1.5x and 0.5x speeds behave
directly instead of forcing users to reason about tick counts.

Loop UI is not exposed in v3. The default loop is:

```text
loop_start_sample = 0
loop_end_sample = sample_count - 1
```

## Multi-Clip Direction

The first v3 refactor implements one active Clip in the UI/export flow.

However, file layouts, manifests, and shader terminology should leave space for
future multi-clip support:

```text
clip_index
active_clip_index
clip table
```

Do not hardcode names or layouts that make adding a second Clip require another
format rewrite.

## Part Splitting

Part splitting follows the BMC collection model.

Rules:

- Direct mesh objects under an IB collection form implicit `part00`.
- Explicit `partNN` collections create explicit parts and separate buffer sets.
- Mixing direct mesh objects with explicit `partNN` children is invalid.
- Within one part, each mesh object remains a separate draw segment.
- If a part's `OWN` final palette would exceed the VS palette limit, split by
  object first.
- If one mesh object exceeds the VS palette limit by itself, report a clear
  error in v3. Triangle-level splitting can be a later enhancement.

When a region is split into parts:

- each part gets its own geometry buffers
- each part gets its own local Bone Payload when needed
- each part gets its own Morph Payload when needed
- morph data must follow the split part's final vertex order

`Final OWN` uses the game VS palette path and therefore participates in the
normal 256-slot constraint. If a part's OWN final bones exceed 256, use the same
partitioning idea as BMC:

```text
object-level split first
single object over 256 bones -> clear error in v3
```

PreSkinBone uses CS-owned buffers and is not constrained by the final VS 256-slot
limit. If PreSkinBone uses more than 256 bones, export it and show a performance
warning instead of splitting by the VS limit.

## Geometry And Morph Ownership

Bone Importer must be able to export RX-local geometry buffers. This is not full
mod packaging: materials, textures, LOD chains, and unrelated mod files remain
outside the plugin's scope.

Geometry export serves the final draw layout. Pre-skin weights serve CS only.

```text
Final draw VB slots:
  follow the target DrawPart / capture_manifest layout
  contain the final draw weights for SOURCE_GAME or OWN

PreSkin weights:
  exported separately
  mapped to the selected PreSkin Armature
  never written into final draw vb2/vb3
```

Every exported model draw binds the complete set of VB/IB slots required by the
target VS. Only slots changed by the deform chain are runtime UAVs. Unchanged
slots are still exported and bound as `DrawVBn` resources.

The generated INI must annotate every replacement draw with the visible source
mesh identity:

```ini
; draw segment: 005_睫眉
drawindexedinstanced = ...
```

The final draw always consumes `DrawVB` resources:

```text
BaseVB    = CS read-only input
TempVB    = optional middle buffer for multi-pass deformation
DrawVB    = final draw input, always bound by draw
DrawIB    = final draw index buffer
```

If no dynamic deformation exists, `DrawVB` is initialized from the exported
static geometry. Do not make INI choose between static and runtime VB at draw
time.

Morph Payload belongs to the vertex buffer it writes, not to the armature.

Current settled route:

```text
Morph -> optional PreSkinBone -> DrawVB
```

Morph uses the same file format and same HLSL pass for every draw segment.
Shader variants are selected by vertex layout, not by draw stage:

```text
CustomShader_ApplyMorph_Packed16
CustomShader_ApplyMorph_PNTA40
```

Do not create `BeforeMorph` / `AfterMorph` shader variants.

Static shape keys that have already been applied into the mesh are geometry, not
Morph Payload. Morph Payload exports animated or explicitly selected shape-key
channels only.

### Geometry Mesh State

Geometry export uses Blender evaluated mesh data while excluding Armature
deformation from the exported base. The goal is:

```text
apply non-armature modifiers
do not bake the current bone pose into BaseVB
preserve shape-key/morph semantics explicitly
```

Morph base and target normals/tangents should use Blender evaluated split
normal/tangent data in the final exported unique-vertex order.

Default morph normal mode:

```text
KEY_TARGETS
```

Reserved mode:

```text
SAMPLE_EVALUATED
```

`KEY_TARGETS` stores per-key target normals/tangents and blends them at runtime.
It is smaller and is the v3 default. `SAMPLE_EVALUATED` is reserved for stricter
per-sample WYSIWYG normals at much higher storage cost.

## Bone Payloads And Palettes

`FinalBonePalette` is the semantic name for the palette consumed by the final VS
draw. It is the v3 name for the existing "replace skin palette" resource.

Final skin palette modes:

```text
SOURCE_GAME
OWN
```

`SOURCE_GAME` means final draw weights map to the target DrawPart's source/game
slots. It is used for original game bone replacement, source replacement
geometry, and external objects that intentionally follow the game/source slots.

`OWN` means final draw weights map to the object's own exported armature slots.
It is used for independent external models that borrow the game's VS/PS but use
their own bone palette.

Do not expose a third no-op/identity mode in v3. If a model needs no-op final
skinning, the user must provide explicit final draw vertex groups and matching
palette semantics. The exporter must not secretly create identity matrices or
invent final weights.

`PreSkinBonePalette` is separate from `FinalBonePalette`. It is consumed only by
CS pre-skin and must never be bound as the final VS palette.

### PreSkinBone

PreSkinBone is explicit and object-level.

User configuration:

```text
Pre-Skin Bone = Enabled
Pre-Skin Armature = selected armature
Pre-Skin Action = explicit action, default selected armature current action
```

PreSkinBone is for overlaying a selected armature action onto a mesh before final
source/game skinning. v3 rules:

```text
PreSkinBone + Final OWN = forbidden
PreSkinBone + Final SOURCE_GAME = supported
```

If PreSkinBone is enabled but the object cannot provide final SOURCE_GAME
mapping for the target DrawPart, report a clear error and ask the user to add or
map final draw vertex groups. Do not auto-create 0-weight data, auto-create
bone0 weight1 data, or silently downgrade to OWN.

PreSkinBone weights:

```text
source = object's vertex groups mapped to PreSkin Armature bones
format = separate preskin_weights buffer
not stored in final draw vb2/vb3
```

Default mapping is strict `vertex group name == armature bone name`. Special
naming is handled by an explicit object-level PreSkin Bone Map.

PreSkinBone action sampling may be shared across many IBs when they use the same
armature/action/timing/coordinate contract:

```text
sample cache key = armature_id + action_id + frame_range + frame_step + coordinate_contract
```

Final payloads, weights, and draw resources remain DrawPart/object local even
when sampling is shared.

### Final Weight Mapping

`SOURCE_GAME` final mapping:

```text
explicit Bone Slot Map wins
otherwise numeric vertex group names or numeric prefixes map to source slots
```

`OWN` final mapping:

```text
Armature order filtered to used bones
then generate local remap for the exported object/part
```

`OWN` armature resolution:

```text
Auto from object armature modifier
if missing or ambiguous, require explicit Final Armature selection
```

The proxy-rig generation/renaming flow must also write explicit export slot map
metadata. Exporters must trust the slot map, not display bone names.

Bone Map storage:

```text
external JSON may be imported
imported maps are written to collection/object custom properties
export does not depend on the original path
```

## Capture Manifest Dependency

`capture_manifest.json` is an intentional required dependency for geometry
export. It provides the game vertex layout table.

The path must be explicit:

```text
Scene.bi_capture_manifest_path
```

Automation may override it with:

```text
RX_CAPTURE_MANIFEST
```

Do not silently scan unrelated mod folders for layout data.

## Coordinate And Slot Contracts

Mirror and axis conversion are Runtime Coordinate Contract concerns. Slot ids are
Slot Contract concerns.

Rules:

- Export mirror is an explicit setting, default enabled.
- Mirror export changes vectors and skin-row conversion; it does not rename or
  remap bone slots.
- UV export is an adapter from Blender-correct UVs to game-format UVs.
- Explicit Bone Importer export properties such as `bi_export_uv_flip_v` win
  over imported-helper metadata such as `bmc_uv_flip_v`.
- Source/game slot ids keep their numeric meaning unless an explicit Bone Slot
  Map says otherwise.

Avoid "fixing" mirror issues by matching left/right bones heuristically. If a
mesh was imported mirrored, the exporter must apply the corresponding coordinate
contract consistently across geometry, bone matrices, morph data, and HLSL.

Imported game meshes were already transformed once so they display correctly in
Blender. Export must apply the inverse game-format adapter. External authored
meshes also start from Blender-correct UVs, so they use the same explicit export
adapter instead of inheriting stale importer flags.

## Implementation Boundaries

In scope for v3:

- collection-driven export
- IB collection -> part -> draw segment export planning
- local Bone Payloads per DrawPart
- optional RX-local geometry export
- Morph Payload export for draw objects, with morph CS executed in Before
- Before-stage morph and PreSkinBone compute chains that prepare DrawVB
- fixed-point playback speed metadata
- manifest-preserving partial exports
- executable INI/HLSL generation for every export type
- explicit PreSkinBone object settings, including armature/action selection
- empty vertex group cleanup button; export itself ignores empties without
  mutating the scene

Reserved / not yet decided:

- single-object triangle-level splitting when one mesh object exceeds 256 bones

Rejected for v3:

- global bone pool replacing DrawPart-local payloads
- standalone `Geometry Only` export type
- silently deleting manifest entries on partial export
- hidden capture-manifest folder scanning
- automatic left/right bone matching as a mirror fix
- PreSkinBone + Final OWN
- morph or pre-skin CS execution outside the IB update stage
- automatic identity/no-op palette generation
