import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load_static_row_builder():
    source_path = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {"_pack_slot_ids_uint4", "build_bone_static_uint4_rows"}
    selected = [node for node in module_ast.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {"RESERVED_PALETTE_ROWS": 3, "BONE_PAYLOAD_FLAGS_NONE": 0, "TQ_FLOATS_PER_BONE": 8}
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec")
    exec(compiled, namespace)
    return namespace["build_bone_static_uint4_rows"]


def _load_bonex_driver_helpers():
    source_path = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {
        "_target_is_static_world_pin",
        "_is_static_bonex_driver_constraint",
        "_iter_static_bonex_driver_constraints",
    }
    selected = [node for node in module_ast.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {}
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec")
    exec(compiled, namespace)
    return namespace["_is_static_bonex_driver_constraint"], namespace["_iter_static_bonex_driver_constraints"]


def _load_bind_stale_helpers():
    source_path = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {
        "_flat_matrix_rest_delta",
        "_pose_bone_bind_rest_delta",
    }
    selected = [node for node in module_ast.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {}
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec")
    exec(compiled, namespace)
    return namespace["_flat_matrix_rest_delta"], namespace["_pose_bone_bind_rest_delta"]


class MatrixRows:
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, index):
        return self.rows[index]


class BonePayloadLayoutTests(unittest.TestCase):
    def test_bone_static_reserves_three_rows_before_slot_zero(self):
        build_bone_static_uint4_rows = _load_static_row_builder()

        rows = build_bone_static_uint4_rows((0, 2), sample_count=5)

        self.assertEqual(rows[0], (1, 2, 3, 1))
        self.assertEqual(rows[1], (12, 12, 0, 2))
        self.assertEqual(rows[2], (5, 0, 0, 4))
        self.assertEqual(rows[3], (0, 2, 0xFFFFFFFF, 0xFFFFFFFF))

    def test_bone_static_stores_payload_flags(self):
        build_bone_static_uint4_rows = _load_static_row_builder()

        rows = build_bone_static_uint4_rows((0,), sample_count=5, flags=1)

        self.assertEqual(rows[1], (6, 6, 1, 2))

    def test_bone_static_can_store_multiple_local_clip_rows(self):
        build_bone_static_uint4_rows = _load_static_row_builder()

        rows = build_bone_static_uint4_rows(
            (0, 1),
            sample_count=5,
            clip_sample_counts=(5, 7),
            clip_loop_ranges=((0, 4), (1, 6)),
        )

        self.assertEqual(rows[0], (2, 2, 3, 1))
        self.assertEqual(rows[1], (9, 9, 0, 2))
        self.assertEqual(rows[2], (5, 0, 0, 4))
        self.assertEqual(rows[3], (7, 20, 1, 6))
        self.assertEqual(rows[4], (0, 1, 0xFFFFFFFF, 0xFFFFFFFF))

    def test_bind_stale_detection_compares_cached_bind_to_current_rest(self):
        flat_delta, pose_delta = _load_bind_stale_helpers()
        rest = MatrixRows(
            (
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0, 1.0),
            )
        )
        stale_bind = (
            1.0, 0.0, 0.0, 2.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        )
        pose_bone = SimpleNamespace(
            bi_bind_valid=True,
            bi_bind_matrix=stale_bind,
            bone=SimpleNamespace(matrix_local=rest),
        )

        self.assertEqual(flat_delta(stale_bind, rest), 2.0)
        self.assertEqual(pose_delta(pose_bone), 2.0)

    def test_rx_export_auto_refreshes_stale_proxy_binds_before_sampling(self):
        source_path = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"
        source = source_path.read_text(encoding="utf-8")

        self.assertIn("BIND_REST_STALE_EPSILON", source)
        self.assertIn("def _auto_refresh_stale_proxy_binds", source)
        self.assertIn("capture_proxy_bind_matrices(armature)", source)
        self.assertIn('"bind_auto_refresh"', source)

    def test_static_bonex_driver_world_pin_is_muted_during_sampling(self):
        is_static_bonex_driver, _iter_static_bonex_driver_constraints = _load_bonex_driver_helpers()
        target = SimpleNamespace(name="bonex_driver_deadbeef", parent=None, animation_data=None, constraints=[])
        constraint = SimpleNamespace(type="COPY_TRANSFORMS", name="bonex_driver", target=target)

        self.assertTrue(is_static_bonex_driver(constraint))

    def test_animated_bonex_driver_target_is_not_muted(self):
        is_static_bonex_driver, _iter_static_bonex_driver_constraints = _load_bonex_driver_helpers()
        animation_data = SimpleNamespace(action=object(), drivers=[])
        target = SimpleNamespace(name="bonex_driver_deadbeef", parent=None, animation_data=animation_data, constraints=[])
        constraint = SimpleNamespace(type="COPY_TRANSFORMS", name="bonex_driver", target=target)

        self.assertFalse(is_static_bonex_driver(constraint))

    def test_static_bonex_driver_constraints_are_counted_without_muting(self):
        _is_static_bonex_driver, iter_static_bonex_driver_constraints = _load_bonex_driver_helpers()
        target = SimpleNamespace(name="bonex_driver_deadbeef", parent=None, animation_data=None, constraints=[])
        constraint = SimpleNamespace(type="COPY_TRANSFORMS", name="bonex_driver", target=target)
        pose_bone = SimpleNamespace(constraints=[constraint])
        source_armature = SimpleNamespace(pose=SimpleNamespace(bones={"0": pose_bone}))
        sample_groups = {"NONE": {"sample_entries_by_key": {"0": ("0", source_armature, "0")}}}

        self.assertEqual(tuple(iter_static_bonex_driver_constraints(sample_groups)), (constraint,))

    def test_static_bonex_driver_mute_is_explicit_opt_in(self):
        source_path = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"
        source = source_path.read_text(encoding="utf-8")

        self.assertIn("RX_BONE_SAMPLE_MUTE_STATIC_BONEX", source)
        self.assertIn('"enabled": False', source)
        self.assertIn('"static_constraint_count": len(static_constraints)', source)
        self.assertIn('"skip_reason": "disabled"', source)

    def test_rx_validation_export_forces_bonex_constraints_enabled(self):
        source_path = Path(__file__).resolve().parents[1] / "scripts" / "export_rx_test.py"
        source = source_path.read_text(encoding="utf-8")

        self.assertIn('os.environ["RX_BONE_SAMPLE_MUTE_STATIC_BONEX"] = "0"', source)


if __name__ == "__main__":
    unittest.main()
