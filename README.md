# Bone Importer

Standalone Blender addon for the VS-T0 proxy workflow.

## Layout
- `__init__.py`: addon entrypoint and registration
- `constants.py`: shared constants
- `properties.py`: Blender property registration
- `operators.py`: thin Blender operator entrypoints
- `panel.py`: sidebar panel
- `core/layout.py`: buffer layout and matrix packing helpers
- `core/proxy.py`: proxy-rig generation and bind capture
- `core/context.py`: active-object resolution and context helpers
- `core/export.py`: palette assembly and previous-frame cache management
- `core/importer.py`: palette-to-armature application logic
- `core/io.py`: palette file read/write helpers
- `core/transform.py`: game/blender coordinate conversion helpers
- `core/workflow.py`: high-level reusable operations called by operators
- `core/models.py`: typed result models shared across modules

## Current scope
- Generate one proxy bone per numeric vertex group.
- Bind each proxy armature to a fixed `part_id`.
- Place each bone from weighted centroid plus inward inset.
- Keep all proxy bones parentless and vertical in local `+Z`.
- Capture bind matrices from the proxy armature.
- Export final skinning matrices as VS-T0-compatible `3 x float4` rows.
- Import palette buffers back onto the proxy armature for preview and verification.
- Write both current and previous windows into one float4 buffer.
- Import one palette file to all selected proxy armatures with one click.
- Generate proxy rigs for multiple selected meshes in one pass.

## Default layout
- Reserved rows: `3`
- Part stride: `1000`
- `part_id` starts at `0`
- `part_base = part_id * 1000`
- Current part window: `part_base .. part_base + 999`
- Previous part window: `part_base + 100000 .. part_base + 100999`
- Row formula per slot: `base + 3 + slot_id * 3 + {0,1,2}`

## Coordinate conversion
- The imported mesh is treated as already standing in correct Blender space.
- Proxy bones are generated directly from that standing mesh without extra coordinate adjustment.
- Raw game `vs-t0` matrices are converted with a unified `X +90 deg` matrix correction.
- Export applies the exact inverse correction, so import and export stay symmetric.
- No object-level preview rotation or rest-pose migration is involved in the workflow.

## Import performance
- Import now reads only the selected current/previous window from disk instead of the full buffer.
- This keeps repeated pose checks faster when the binary file contains a full `200000`-row palette.

## Blender workflow
1. Select a mesh with numeric vertex groups such as `0`, `1`, `2`.
2. Click `Generate Proxy Rig`.
3. Assign a `Part Id` to the generated proxy armature.
4. Pose or animate the generated proxy armature.
5. Click `Capture Bind` after the proxy rig layout is finalized.
6. Click `Export Palette` to write the `.bin` and optional `.json`.
7. Click `Import Palette` to apply a saved palette back onto the proxy armature.
8. Select multiple configured proxy armatures and click `Import Palette` to batch-apply one palette file.

## Notes
- V1 assumes `slot_id = vertex group name`.
- V1 exports final skinning matrices: `M_pose * inverse(M_bind)`.
- No parent hierarchy is required for the proxy armature.
- Operators stay thin by delegating to `core/workflow.py`.
- Palette assembly, file IO, coordinate conversion, and armature application are intentionally separated for reuse.
