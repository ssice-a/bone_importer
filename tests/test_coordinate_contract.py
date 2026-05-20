import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "coordinate_contract.py"
SPEC = importlib.util.spec_from_file_location("coordinate_contract", MODULE_PATH)
coordinate_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coordinate_contract
SPEC.loader.exec_module(coordinate_contract)


class CoordinateContractTests(unittest.TestCase):
    def test_mirror_x_vector_matches_rx_geometry_export(self):
        self.assertEqual(coordinate_contract.mirror_x_vector((1.0, 2.0, 3.0)), (-1.0, 2.0, 3.0))

    def test_bitangent_handedness_flips_when_exactly_one_orientation_rule_changes(self):
        cases = [
            (False, False, False),
            (True, True, False),
            (True, False, True),
            (False, True, True),
        ]
        for mirror_x, uv_flip_v, expected in cases:
            with self.subTest(mirror_x=mirror_x, uv_flip_v=uv_flip_v):
                self.assertEqual(
                    coordinate_contract.bitangent_sign_needs_flip(
                        mirror_x=mirror_x,
                        uv_flip_v=uv_flip_v,
                    ),
                    expected,
                )

    def test_object_metadata_resolves_contract_defaults(self):
        self.assertTrue(coordinate_contract.resolve_object_mirror_x({}, None))
        self.assertFalse(coordinate_contract.resolve_object_uv_mirror_u({}, None))
        self.assertTrue(coordinate_contract.resolve_object_uv_flip_v({}, None))
        self.assertFalse(coordinate_contract.resolve_object_mirror_x({"bmc_mirror_flip": False}, True))
        self.assertTrue(coordinate_contract.resolve_object_mirror_x({"modimp_mirror_flip": True}, False))
        self.assertTrue(coordinate_contract.resolve_object_uv_mirror_u({"bmc_uv_mirror_u": True}, False))
        self.assertFalse(coordinate_contract.resolve_object_uv_mirror_u({"modimp_mirror_uv_u": False}, True))
        self.assertFalse(coordinate_contract.resolve_object_uv_flip_v({"bmc_uv_flip_v": False}, True))
        self.assertTrue(coordinate_contract.resolve_object_uv_flip_v({"modimp_flip_v": True}, False))

    def test_yv_axis_skin_rows_matches_reference_shader(self):
        rows = coordinate_contract.yv_axis_skin_rows(
            (1.0, 2.0, 3.0, 4.0),
            (5.0, 6.0, 7.0, 8.0),
            (9.0, 10.0, 11.0, 12.0),
        )

        self.assertEqual(
            rows,
            (
                (1.0, 2.0, 3.0, 4.0),
                (9.0, 10.0, 11.0, 12.0),
                (-5.0, -6.0, -7.0, -8.0),
            ),
        )

    def test_mirror_x_skin_rows_conjugates_affine_matrix_without_slot_remap(self):
        rows = coordinate_contract.mirror_x_skin_rows(
            (1.0, 2.0, 3.0, 4.0),
            (5.0, 6.0, 7.0, 8.0),
            (9.0, 10.0, 11.0, 12.0),
        )

        self.assertEqual(
            rows,
            (
                (1.0, -2.0, -3.0, -4.0),
                (-5.0, 6.0, 7.0, 8.0),
                (-9.0, 10.0, 11.0, 12.0),
            ),
        )

    def test_yv_axis_skin_rows_can_apply_mirror_x_before_axis_mapping(self):
        rows = coordinate_contract.yv_axis_skin_rows(
            (1.0, 2.0, 3.0, 4.0),
            (5.0, 6.0, 7.0, 8.0),
            (9.0, 10.0, 11.0, 12.0),
            mirror_x=True,
        )

        self.assertEqual(
            rows,
            (
                (1.0, -2.0, -3.0, -4.0),
                (-9.0, 10.0, 11.0, 12.0),
                (5.0, -6.0, -7.0, -8.0),
            ),
        )

    def test_hlsl_contract_contains_same_yv_axis_row_mapping(self):
        hlsl = coordinate_contract.hlsl_coordinate_contract()

        self.assertIn("RX_RUNTIME_YV_AXIS", hlsl)
        self.assertIn("RX_BONE_PAYLOAD_FLAG_MIRROR_X", hlsl)
        self.assertIn("RxMirrorSkinRowsOnX", hlsl)
        self.assertIn("game_row_0 =  blender_row_0", hlsl)
        self.assertIn("uint payload_flags", hlsl)
        self.assertIn("game0 = blender0;", hlsl)
        self.assertIn("game1 = blender2;", hlsl)
        self.assertIn("game2 = -blender1;", hlsl)


if __name__ == "__main__":
    unittest.main()
