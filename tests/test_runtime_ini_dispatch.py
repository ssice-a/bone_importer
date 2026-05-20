import unittest
from pathlib import Path


RUNTIME_INI_SOURCE = Path(__file__).resolve().parents[1] / "core" / "runtime_ini.py"
COORDINATE_CONTRACT_SOURCE = Path(__file__).resolve().parents[1] / "core" / "coordinate_contract.py"
OPERATORS_SOURCE = Path(__file__).resolve().parents[1] / "operators.py"
BONE_PAYLOAD_SOURCE = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"


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
        self.assertIn("_append_constants(lines, _clip_default_ticks_per_sample(manifest, clip_name))", source)
        self.assertIn('global persist $rx_anim_speed = {speed}', source)
        self.assertIn("global persist $rx_anim_speed_default = 0", source)
        self.assertIn('if $rx_anim_speed_default == 0', source)
        self.assertNotIn('_line(lines, "global persist $rx_anim_speed = 1")', source)

    def test_runtime_ini_runs_rx_ui_present_commandlist(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('namespace = RX', source)
        self.assertIn('run = CommandListRXUIPresent', source)
        self.assertIn('"update_rx_panel_state_cs.hlsl"', source)
        self.assertIn('"panel_sprite.hlsl"', source)
        self.assertIn('"panel_digits.hlsl"', source)

    def test_export_buttons_forward_ticks_per_sample_setting(self):
        source = OPERATORS_SOURCE.read_text(encoding="utf-8")

        self.assertIn("presents_per_step=scene.bi_animation_presents_per_step", source)
        self.assertNotIn("presents_per_step=1,", source)

    def test_bone_payload_shared_clip_uses_exported_ticks_per_sample(self):
        source = BONE_PAYLOAD_SOURCE.read_text(encoding="utf-8")

        self.assertIn("resolved_ticks_per_sample = max(int(ticks_per_sample), 1)", source)
        self.assertIn("ticks_per_sample=resolved_ticks_per_sample", source)
        self.assertNotIn("ticks_per_sample=1,\n        write_metadata=write_metadata", source)


if __name__ == "__main__":
    unittest.main()
