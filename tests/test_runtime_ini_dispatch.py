import unittest
import importlib
import re
import sys
import tempfile
import types
from pathlib import Path


RUNTIME_INI_SOURCE = Path(__file__).resolve().parents[1] / "core" / "runtime_ini.py"
COORDINATE_CONTRACT_SOURCE = Path(__file__).resolve().parents[1] / "core" / "coordinate_contract.py"
OPERATORS_SOURCE = Path(__file__).resolve().parents[1] / "operators.py"
BONE_PAYLOAD_SOURCE = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"
RX_EXPORT_TEST_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_rx_test.py"


def _load_runtime_ini_module():
    core_package = types.ModuleType("core")
    core_package.__path__ = [str(RUNTIME_INI_SOURCE.parent)]
    sys.modules.setdefault("core", core_package)
    animation_stub = types.ModuleType("core.animation_export")
    animation_stub.normalize_clip_name = lambda value: str(value or "rxanimin")
    animation_stub.sanitize_export_name = lambda value, fallback: re.sub(r"[^0-9A-Za-z_]+", "_", str(value or fallback)).strip("_") or fallback
    sys.modules["core.animation_export"] = animation_stub
    draw_part_stub = types.ModuleType("core.draw_part")
    draw_part_stub.DEFAULT_MATCH_PRIORITY = -1000
    sys.modules["core.draw_part"] = draw_part_stub
    manifest_stub = types.ModuleType("core.manifest")
    manifest_stub.load_export_manifest = lambda _output_directory: {}
    sys.modules["core.manifest"] = manifest_stub
    return importlib.import_module("core.runtime_ini")


def _load_runtime_ini_builder():
    return _load_runtime_ini_module().build_runtime_ini


class RuntimeIniDispatchTests(unittest.TestCase):
    def test_runtime_ini_does_not_emit_rx_anim_enable_guards(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertNotIn("$rx_anim_enable", source)

    def test_bone_palette_dispatch_lives_inside_custom_shader(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('[CustomShader_UpdateBonePaletteTQ]', source)
        self.assertIn('_line(lines, "dispatch = 256, 1, 1")', source)
        self.assertNotIn('_line(lines, f"    dispatch = {bone_count}, 1, 1")', source)

    def test_cb1_redirect_dispatch_lives_inside_custom_shader(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('[CustomShader_RedirectCB1LocalPalette]', source)
        self.assertIn('_line(lines, "dispatch = 4, 1, 1")', source)
        self.assertNotIn('_line(lines, "    dispatch = 4, 1, 1")', source)

    def test_bone_palette_uses_rx_yv_basis_conversion(self):
        runtime_source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")
        contract_source = COORDINATE_CONTRACT_SOURCE.read_text(encoding="utf-8")

        self.assertIn('"rx_anim_coordinate_contract.hlsli": hlsl_coordinate_contract()', runtime_source)
        self.assertIn('#include "rx_anim_coordinate_contract.hlsli"', runtime_source)
        self.assertIn("uint payload_flags = header1.z;", runtime_source)
        self.assertIn("RxConvertSkinRowsFromBlenderToGame(skin0, skin1, skin2, payload_flags, out0, out1, out2);", runtime_source)
        self.assertNotIn("void ConvertSkinRowsFromBlenderToGame", runtime_source)

        self.assertIn("RX_RUNTIME_YV_AXIS", contract_source)
        self.assertIn("RX_BONE_PAYLOAD_FLAG_MIRROR_X", contract_source)
        self.assertIn("game_row_0 =  blender_row_0", contract_source)
        self.assertIn("game0 = blender0;", contract_source)
        self.assertIn("game1 = blender2;", contract_source)
        self.assertIn("game2 = -blender1;", contract_source)
        self.assertNotIn("game0 = float4(blender0.x, -blender0.y, -blender0.z, -blender0.w);", contract_source)

    def test_runtime_hlsl_writer_outputs_coordinate_contract_include_body(self):
        runtime_ini = _load_runtime_ini_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_ini.write_runtime_hlsl_files(temp_dir)
            contract_path = Path(temp_dir) / "hlsl" / "rx_anim_coordinate_contract.hlsli"
            contract_hlsl = contract_path.read_text(encoding="utf-8")

        self.assertIn("RxConvertSkinRowsFromBlenderToGame", contract_hlsl)
        self.assertIn("RxMirrorSkinRowsOnX", contract_hlsl)
        self.assertGreater(len(contract_hlsl.strip()), 200)

    def test_cb1_redirect_points_to_palette_window_start_like_yv(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("cb_data.x = 0u;", source)
        self.assertIn("cb_data.y = static_header1.y;", source)
        self.assertNotIn("cb_data.x = reserved_rows;", source)
        self.assertNotIn("cb_data.y = static_header1.y + reserved_rows;", source)

    def test_bone_palette_reads_master_playback_directly_as_uav(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('_line(lines, "cs-u1 = ResourceMasterPlayback")', source)
        self.assertIn('_line(lines, "cs-u1 = null")', source)
        self.assertIn("RWStructuredBuffer<uint4> MasterPlayback : register(u1);", source)
        self.assertNotIn("StructuredBuffer<uint4> MasterPlayback : register(t3);\nRWStructuredBuffer<float4> BonePalette", source)

    def test_runtime_speed_default_comes_from_clip_metadata(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("def _clip_default_ticks_per_sample", source)
        self.assertIn("_append_constants(lines, _clip_default_ticks_per_sample(manifest, clip_name), _clip_count(manifest))", source)
        self.assertIn('global persist $rx_anim_speed = {speed}', source)
        self.assertIn('global persist $rx_anim_speed_default = {speed}', source)
        self.assertIn('if $rx_anim_speed_default != {speed}', source)
        self.assertNotIn('_line(lines, "global persist $rx_anim_speed = 1")', source)

    def test_runtime_ini_runs_rx_ui_present_commandlist(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('namespace = RX', source)
        self.assertIn('run = CommandListRXUIPresent', source)
        self.assertIn('"update_rx_panel_state_cs.hlsl"', source)
        self.assertIn('"panel_sprite.hlsl"', source)
        self.assertIn('"panel_digits.hlsl"', source)

    def test_runtime_present_forwards_action_index_to_master_playback(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("global persist $rx_anim_action_index = 0", source)
        self.assertIn("global $rx_anim_action_count = {action_count}", source)
        self.assertIn('_line(lines, "z1 = $rx_anim_action_index")', source)
        self.assertIn('_line(lines, "w1 = $rx_anim_action_count")', source)
        self.assertIn("uint requested_clip_index = (uint)max(control1.z, 0.0);", source)
        self.assertIn("uint clip_count = max((uint)max(control1.w, 1.0), 1u);", source)
        self.assertIn("MasterPlayback[2] = uint4(seek_active, last_control_token, active_clip_index, queued_clip_index);", source)

    def test_runtime_ui_has_player_hotkey_and_action_tabs(self):
        runtime_ini = _load_runtime_ini_module()
        manifest = {
            "clips": {
                "idle": {"default_ticks_per_sample": 4},
                "wave": {"default_ticks_per_sample": 4},
                "blink": {"default_ticks_per_sample": 4},
            }
        }

        ui_ini = runtime_ini.build_runtime_ui_ini(manifest, "idle")

        self.assertIn("[CommandListRXNextAction]", ui_ini)
        self.assertIn("[ResourceRXTabActions]", ui_ini)
        self.assertIn("[ResourceRXActionPage]", ui_ini)
        self.assertIn("elif $rx_ui_hover == 4\n    $rx_ui_tab = 2", ui_ini)
        self.assertIn("run = CommandListRXSelectAction0", ui_ini)
        self.assertIn("run = CommandListRXSelectAction1", ui_ini)
        self.assertIn("run = CommandListRXSelectAction2", ui_ini)
        self.assertNotIn("run = CommandListRXSelectAction4", ui_ini)

    def test_export_buttons_forward_ticks_per_sample_setting(self):
        source = OPERATORS_SOURCE.read_text(encoding="utf-8")

        self.assertIn("presents_per_step=scene.bi_animation_presents_per_step", source)
        self.assertNotIn("presents_per_step=1,", source)

    def test_rx_validation_export_defaults_to_four_ticks_per_sample(self):
        source = RX_EXPORT_TEST_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("DEFAULT_TICKS_PER_SAMPLE = 4", source)
        self.assertIn('_env_int("RX_EXPORT_TICKS_PER_SAMPLE", DEFAULT_TICKS_PER_SAMPLE)', source)

    def test_bone_payload_shared_clip_uses_exported_ticks_per_sample(self):
        source = BONE_PAYLOAD_SOURCE.read_text(encoding="utf-8")

        self.assertIn("resolved_ticks_per_sample = max(int(ticks_per_sample), 1)", source)
        self.assertIn("ticks_per_sample=resolved_ticks_per_sample", source)
        self.assertNotIn("ticks_per_sample=1,\n        write_metadata=write_metadata", source)

    def test_morph_draw_part_uses_base_copy_ref_binding_without_runtime_vb_copy(self):
        manifest = {
            "clips": {
                "rxanimin": {
                    "timeline_static": "rxanimin_timeline_static.buf",
                    "master_playback": "rxanimin_master_playback.buf",
                    "default_ticks_per_sample": 4,
                }
            },
            "draw_parts": {
                "e78c7068-10590-0": {
                    "hash": "e78c7068",
                    "match_index_count": 10590,
                    "match_priority": -1000,
                },
                "2009f0d6-1356-0": {
                    "hash": "2009f0d6",
                    "match_index_count": 1356,
                    "match_priority": -1000,
                    "cb1_profile": "EYELASH",
                },
            },
            "payloads": {
                "e78c7068-10590-0": {
                    "bone": {
                        "static": "e78c7068_static.buf",
                        "anim": "e78c7068_anim.buf",
                        "bind": "e78c7068_bind.buf",
                        "palette_row_count": 3,
                    },
                    "morph": {
                        "static": "e78c7068_morph_static.buf",
                        "anim": "e78c7068_morph_anim.buf",
                        "base_position_path": "Buffer/e78c7068-10590-0_part00-Position.buf",
                        "base_position_stride": 16,
                        "base_position_layout": "EFMI_PACKED16",
                        "vertex_count": 10590,
                    },
                    "geometry": [
                        {
                            "resource_suffix": "e78c7068_10590_0_part00",
                            "object_names": ["000_面"],
                            "index_buffer": {"file_path": "Buffer/e78c7068-10590-0_part00-Index.buf", "index_count": 10590},
                            "vertex_buffers": {
                                "vb0": {"file_path": "Buffer/e78c7068-10590-0_part00-Position.buf", "stride": 16},
                                "vb1": {"file_path": "Buffer/e78c7068-10590-0_part00-Texcoord.buf", "stride": 12},
                                "vb2": {"file_path": "Buffer/e78c7068-10590-0_part00-Blend.buf", "stride": 12},
                            },
                        }
                    ],
                },
                "2009f0d6-1356-0": {
                    "morph": {
                        "static": "2009f0d6_morph_static.buf",
                        "anim": "2009f0d6_morph_anim.buf",
                        "base_position_path": "Buffer/2009f0d6-1356-0_part00-Position.buf",
                        "base_position_stride": 40,
                        "base_position_layout": "EFMI_PNTA40",
                        "vertex_count": 1356,
                    },
                    "geometry": [
                        {
                            "resource_suffix": "2009f0d6_1356_0_part00",
                            "object_names": ["005_睫眉"],
                            "index_buffer": {"file_path": "Buffer/2009f0d6-1356-0_part00-Index.buf", "index_count": 1356},
                            "vertex_buffers": {
                                "vb0": {"file_path": "Buffer/2009f0d6-1356-0_part00-Position.buf", "stride": 40},
                                "vb1": {"file_path": "Buffer/2009f0d6-1356-0_part00-Texcoord.buf", "stride": 8},
                                "vb2": {"file_path": "Buffer/2009f0d6-1356-0_part00-Blend.buf", "stride": 32},
                                "vb3": {"file_path": "Buffer/2009f0d6-1356-0_part00-VB3.buf", "stride": 40},
                            },
                        }
                    ],
                },
            },
        }

        ini = _load_runtime_ini_builder()(manifest, "rxanimin", r"E:\XXMI\EFMI\Mods\RX")

        self.assertNotIn("ResourceMorphRuntimeVB_e78c7068_10590_0 = copy ResourceMorphRuntimeVB_e78c7068_10590_0_UAV", ini)
        self.assertNotIn("ResourceMorphRuntimeVB_2009f0d6_1356_0 = copy ResourceMorphRuntimeVB_2009f0d6_1356_0_UAV", ini)
        self.assertNotIn("vb0 = ref ResourceMorphRuntimeVB_e78c7068_10590_0", ini)
        self.assertNotIn("vb0 = ref ResourceMorphRuntimeVB_2009f0d6_1356_0", ini)
        morph_run_index = ini.index("run = CustomShader_ApplyMorph\n")
        bone_run_index = ini.index("run = CustomShader_UpdateBonePaletteTQ")
        self.assertLess(morph_run_index, bone_run_index)
        self.assertIn("[CustomShader_ApplyMorph]", ini)
        self.assertIn("[CustomShader_ApplyMorph_PNTA40]", ini)
        self.assertIn("[ResourceMorphBaseVB_e78c7068_10590_0]\ntype = Buffer\nstride = 16", ini)
        self.assertIn("[ResourceMorphBaseVB_2009f0d6_1356_0]\ntype = Buffer\nstride = 40", ini)
        self.assertIn("cs-t0 = ResourceMorphBaseVB_e78c7068_10590_0_SRV", ini)
        self.assertIn("cs-u5 = copy ResourceMorphBaseVB_e78c7068_10590_0", ini)
        self.assertIn("ResourceGeometry_e78c7068_10590_0_part00_vb0 = ref cs-u5", ini)
        self.assertIn(
            "cs-u5 = copy ResourceMorphBaseVB_e78c7068_10590_0\n"
            "ResourceGeometry_e78c7068_10590_0_part00_vb0 = ref cs-u5\n"
            "run = CustomShader_ApplyMorph",
            ini,
        )
        self.assertIn("cs-t0 = ResourceMorphBaseVB_2009f0d6_1356_0_SRV", ini)
        self.assertIn("cs-u5 = copy ResourceMorphBaseVB_2009f0d6_1356_0", ini)
        self.assertIn("ResourceGeometry_2009f0d6_1356_0_part00_vb0 = ref cs-u5", ini)
        self.assertIn(
            "cs-u5 = copy ResourceMorphBaseVB_2009f0d6_1356_0\n"
            "ResourceGeometry_2009f0d6_1356_0_part00_vb0 = ref cs-u5\n"
            "run = CustomShader_ApplyMorph_PNTA40",
            ini,
        )
        self.assertIn("[CustomShader_ApplyMorph]\ncs = hlsl\\apply_morph_to_vb_cs.hlsl\ncs-t3 = ResourceMasterPlayback_SRV\ndispatch = 166, 1, 1", ini)
        self.assertIn("[CustomShader_ApplyMorph_PNTA40]\ncs = hlsl\\apply_morph_to_vb_pnta40_cs.hlsl\ncs-t3 = ResourceMasterPlayback_SRV\ndispatch = 22, 1, 1", ini)
        self.assertIn("run = CustomShader_UpdateBonePaletteTQ", ini)
        self.assertIn("vb0 = ref ResourceGeometry_e78c7068_10590_0_part00_vb0", ini)
        self.assertIn("vb3 = ref ResourceGeometry_e78c7068_10590_0_part00_vb0", ini)
        self.assertIn("vb0 = ref ResourceGeometry_2009f0d6_1356_0_part00_vb0", ini)
        self.assertIn("vb3 = ref ResourceGeometry_2009f0d6_1356_0_part00_vb3", ini)
        self.assertIn("; draw segment: 005_睫眉", ini)
        self.assertIn(
            "; draw segment: 005_睫眉\n"
            "drawindexedinstanced = 1356,INSTANCE_COUNT,0,0,FIRST_INSTANCE",
            ini,
        )

    def test_runtime_morph_shaders_write_to_u5_to_avoid_bone_chain_u0_collision(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("RWStructuredBuffer<MorphVB16> RuntimeVB : register(u5);", source)
        self.assertIn("RWStructuredBuffer<MorphVB40> RuntimeVB : register(u5);", source)
        self.assertIn('_line(lines, "cs-u5 = null")', source)


if __name__ == "__main__":
    unittest.main()
