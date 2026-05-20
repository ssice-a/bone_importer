import unittest
from pathlib import Path


RUNTIME_INI_SOURCE = Path(__file__).resolve().parents[1] / "core" / "runtime_ini.py"
COORDINATE_CONTRACT_SOURCE = Path(__file__).resolve().parents[1] / "core" / "coordinate_contract.py"


class RuntimeIniDispatchTests(unittest.TestCase):
    def test_runtime_ini_does_not_emit_rx_anim_enable_guards(self):
        source = RUNTIME_INI_SOURCE.read_text(encoding="utf-8")

        self.assertNotIn("$rx_anim_enable", source)
        self.assertNotIn('_line(lines, "endif")', source)

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
        self.assertIn("RxConvertSkinRowsFromBlenderToGame(skin0, skin1, skin2, out0, out1, out2);", runtime_source)
        self.assertNotIn("void ConvertSkinRowsFromBlenderToGame", runtime_source)

        self.assertIn("RX_RUNTIME_YV_AXIS", contract_source)
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


if __name__ == "__main__":
    unittest.main()
