import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


def _load_local_clip_payload_module():
    source_path = Path(__file__).resolve().parents[1] / "core" / "local_clip_payload.py"
    spec = importlib.util.spec_from_file_location("local_clip_payload_under_test", source_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


local_clip_payload = _load_local_clip_payload_module()


class LocalClipPayloadTests(unittest.TestCase):
    def test_bone_clip_append_keeps_existing_anim_rows_and_builds_next_row_base(self):
        existing_static_rows = np.asarray(
            (
                (1, 2, 3, 1),
                (9, 9, 0, 2),
                (2, 0, 0, 1),
                (0, 1, 0xFFFFFFFF, 0xFFFFFFFF),
            ),
            dtype="<u4",
        )
        existing_anim_rows = np.arange(8 * 4, dtype="<f4").reshape((8, 4))
        incoming_anim_rows = np.arange(12 * 4, dtype="<f4").reshape((12, 4)) + 1000.0

        merge = local_clip_payload.merge_bone_anim_clip(
            existing_static_rows,
            existing_anim_rows,
            incoming_anim_rows,
            clip_index=1,
            bone_count=2,
            sample_count=3,
            loop_range=(1, 2),
        )

        self.assertEqual(merge.clip_sample_counts, (2, 3))
        self.assertEqual(merge.clip_loop_ranges, ((0, 1), (1, 2)))
        self.assertEqual(merge.clip_sample_row_bases, (0, 8))
        np.testing.assert_array_equal(merge.anim_rows[:8], existing_anim_rows)
        np.testing.assert_array_equal(merge.anim_rows[8:], incoming_anim_rows)

    def test_morph_clip_append_rebases_local_payload_rows(self):
        existing_rows = np.asarray(
            (
                (1, 2, 8, 0),
                (2, 2, 10, 1),
                (101, 102, 103, 104),
                (105, 106, 107, 108),
            ),
            dtype="<u4",
        )
        incoming_rows = np.asarray(
            (
                (1, 2, 8, 0),
                (3, 2, 30, 2),
                (201, 202, 203, 204),
                (205, 206, 207, 208),
                (209, 210, 211, 212),
            ),
            dtype="<u4",
        )

        merged_rows = local_clip_payload.merge_morph_anim_clip(existing_rows, incoming_rows, clip_index=1)

        self.assertEqual(tuple(int(value) for value in merged_rows[0]), (2, 2, 8, 0))
        self.assertEqual(tuple(int(value) for value in merged_rows[1]), (2, 3, 10, 1))
        self.assertEqual(tuple(int(value) for value in merged_rows[2]), (3, 5, 30, 2))
        np.testing.assert_array_equal(merged_rows[3:5], existing_rows[2:])
        np.testing.assert_array_equal(merged_rows[5:], incoming_rows[2:])

    def test_bone_clip_delete_rebases_remaining_rows(self):
        existing_static_rows = np.asarray(
            (
                (2, 2, 3, 1),
                (9, 9, 0, 2),
                (2, 0, 0, 1),
                (3, 8, 1, 2),
                (0, 1, 0xFFFFFFFF, 0xFFFFFFFF),
            ),
            dtype="<u4",
        )
        existing_anim_rows = np.arange(20 * 4, dtype="<f4").reshape((20, 4))

        deleted = local_clip_payload.delete_bone_anim_clip(
            existing_static_rows,
            existing_anim_rows,
            clip_index=0,
            bone_count=2,
        )

        self.assertEqual(deleted.clip_sample_counts, (3,))
        self.assertEqual(deleted.clip_loop_ranges, ((1, 2),))
        self.assertEqual(deleted.clip_sample_row_bases, (0,))
        np.testing.assert_array_equal(deleted.anim_rows, existing_anim_rows[8:20])

    def test_morph_clip_delete_rebases_remaining_payload(self):
        rows = np.asarray(
            (
                (2, 2, 8, 0),
                (2, 3, 10, 1),
                (3, 5, 30, 2),
                (101, 102, 103, 104),
                (105, 106, 107, 108),
                (201, 202, 203, 204),
                (205, 206, 207, 208),
                (209, 210, 211, 212),
            ),
            dtype="<u4",
        )

        deleted = local_clip_payload.delete_morph_anim_clip(rows, clip_index=0)

        self.assertEqual(tuple(int(value) for value in deleted[0]), (1, 2, 8, 0))
        self.assertEqual(tuple(int(value) for value in deleted[1]), (3, 2, 30, 2))
        np.testing.assert_array_equal(deleted[2:], rows[5:])


if __name__ == "__main__":
    unittest.main()
