# Bone Importer

Standalone Blender addon for the VS-T0 proxy workflow.

## Layout
- `__init__.py`: addon entrypoint and registration
- `addon_constants.py`: shared constants
- `addon_properties.py`: Blender property registration
- `addon_operators.py`: thin Blender operator entrypoints
- `addon_panel.py`: sidebar panel
- `core/palette_layout.py`: buffer layout and matrix packing helpers
- `core/proxy_rig.py`: proxy-rig generation and bind capture
- `core/object_context.py`: active-object resolution and context helpers
- `core/palette_export.py`: palette assembly and previous-frame cache management
- `core/palette_import.py`: palette-to-armature application logic
- `core/palette_file_io.py`: palette file read/write helpers
- `core/coordinate_conversion.py`: game/blender coordinate conversion helpers
- `core/workflow_steps.py`: high-level reusable operations called by operators
- `core/result_models.py`: typed result models shared across modules

## Current scope
- Generate one proxy bone per numeric vertex group.
- Place each bone from weighted centroid plus inward inset.
- Keep all proxy bones parentless and vertical in local `+Z`.
- Capture bind matrices from the proxy armature.
- Export final skinning matrices as VS-T0-compatible `3 x float4` rows.
- Import palette buffers back onto the proxy armature for preview and verification.
- Write both current and previous windows into one float4 buffer.

## Default layout
- Reserved rows: `3`
- Current part window: `part_base .. part_base + 999`
- Previous part window: `part_base + 100000 .. part_base + 100999`
- Row formula per slot: `base + 3 + slot_id * 3 + {0,1,2}`

## Coordinate conversion
- Game to Blender: rotate `+90 deg` around the `X` axis.
- Blender to Game export: apply the inverse `-90 deg` `X` rotation.

## Blender workflow
1. Select a mesh with numeric vertex groups such as `0`, `1`, `2`.
2. Click `Generate Proxy Rig`.
3. Pose or animate the generated proxy armature.
4. Click `Capture Bind` after the proxy rig layout is finalized.
5. Click `Export Palette` to write the `.bin` and optional `.json`.
6. Click `Import Palette` to apply a saved palette back onto the proxy armature.

## Notes
- V1 assumes `slot_id = vertex group name`.
- V1 exports final skinning matrices: `M_pose * inverse(M_bind)`.
- No parent hierarchy is required for the proxy armature.
- Operators stay thin by delegating to `core/workflow_steps.py`.
- Palette assembly, file IO, coordinate conversion, and armature application are intentionally separated for reuse.
