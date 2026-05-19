import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "bone_sample_bank.py"
SPEC = importlib.util.spec_from_file_location("bone_sample_bank", MODULE_PATH)
bone_sample_bank = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bone_sample_bank
SPEC.loader.exec_module(bone_sample_bank)

build_bone_sample_plan = bone_sample_bank.build_bone_sample_plan
resolve_sample_cache_directory = bone_sample_bank.resolve_sample_cache_directory
select_payload_samples = bone_sample_bank.select_payload_samples


class BoneSampleBankTests(unittest.TestCase):
    def test_deduplicates_group_samples_and_preserves_payload_slot_order(self):
        armature = SimpleNamespace(name="ArmatureA")
        bone_a = SimpleNamespace(source_armature=armature, source_bone="0")
        bone_b = SimpleNamespace(source_armature=armature, source_bone="1")
        bone_c = SimpleNamespace(source_armature=armature, source_bone="2")
        payloads = (
            {
                "draw_key": "face",
                "correction_mode": "NONE",
                "correction_matrix": None,
                "bindings": (bone_a, bone_b),
            },
            {
                "draw_key": "lashes",
                "correction_mode": "NONE",
                "correction_matrix": None,
                "bindings": (bone_b, bone_c, bone_a),
            },
        )

        plan = build_bone_sample_plan(
            payloads,
            lambda binding: (binding.source_armature.name, binding.source_bone),
        )

        self.assertEqual(tuple(plan.groups), ("NONE",))
        self.assertEqual(
            plan.groups["NONE"].sample_keys,
            (("ArmatureA", "0"), ("ArmatureA", "1"), ("ArmatureA", "2")),
        )
        self.assertEqual(plan.payloads["face"].sample_indices, (0, 1))
        self.assertEqual(plan.payloads["lashes"].sample_indices, (1, 2, 0))

        sample_cache = np.arange(2 * 3 * 8, dtype=np.float32).reshape((2, 3, 8))
        selected = select_payload_samples(sample_cache, plan.payloads["lashes"].sample_indices)

        np.testing.assert_array_equal(selected[:, 0, :], sample_cache[:, 1, :])
        np.testing.assert_array_equal(selected[:, 1, :], sample_cache[:, 2, :])
        np.testing.assert_array_equal(selected[:, 2, :], sample_cache[:, 0, :])

    def test_keeps_correction_groups_separate(self):
        armature = SimpleNamespace(name="ArmatureA")
        binding = SimpleNamespace(source_armature=armature, source_bone="0")
        payloads = (
            {
                "draw_key": "packed16",
                "correction_mode": "NONE",
                "correction_matrix": None,
                "bindings": (binding,),
            },
            {
                "draw_key": "pnta40",
                "correction_mode": "MATRIX_RX_90_DEG",
                "correction_matrix": "rx90",
                "bindings": (binding,),
            },
        )

        plan = build_bone_sample_plan(
            payloads,
            lambda item: (item.source_armature.name, item.source_bone),
        )

        self.assertEqual(set(plan.groups), {"NONE", "MATRIX_RX_90_DEG"})
        self.assertEqual(plan.payloads["packed16"].group_key, "NONE")
        self.assertEqual(plan.payloads["pnta40"].group_key, "MATRIX_RX_90_DEG")

    def test_resolves_opt_in_cache_directory_from_export_flag(self):
        cache_dir = resolve_sample_cache_directory(
            r"E:\Out",
            explicit_cache_dir="",
            use_cache_flag="1",
            path_resolver=lambda value: value.replace("\\", "/"),
        )

        self.assertEqual(cache_dir, "E:/Out/.rx_bone_sample_cache")

    def test_explicit_cache_directory_overrides_export_flag(self):
        cache_dir = resolve_sample_cache_directory(
            r"E:\Out",
            explicit_cache_dir=r"D:\Cache",
            use_cache_flag="1",
            path_resolver=lambda value: value.replace("\\", "/"),
        )

        self.assertEqual(cache_dir, "D:/Cache")


if __name__ == "__main__":
    unittest.main()
