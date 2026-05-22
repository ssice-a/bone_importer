import json
import importlib.util
import sys
import types
import tempfile
import unittest
from pathlib import Path

import numpy as np


def _load_action_bank_editor():
    root = Path(__file__).resolve().parents[1]
    core_pkg = sys.modules.get("core")
    if core_pkg is None:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["core"] = core_pkg
    source_path = root / "core" / "action_bank_editor.py"
    spec = importlib.util.spec_from_file_location("core.action_bank_editor", source_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


action_bank_editor = _load_action_bank_editor()
delete_action_at_index = action_bank_editor.delete_action_at_index
rename_action_at_index = action_bank_editor.rename_action_at_index


def _write_uint4(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.asarray(rows, dtype="<u4").reshape((-1, 4)).tofile(path)


def _write_float4(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.asarray(rows, dtype="<f4").reshape((-1, 4)).tofile(path)


def _read_uint4(path: Path):
    return np.fromfile(path, dtype="<u4").reshape((-1, 4))


def _read_float4(path: Path):
    return np.fromfile(path, dtype="<f4").reshape((-1, 4))


class ActionBankEditorTests(unittest.TestCase):
    def test_delete_action_rewrites_manifest_timeline_bone_and_morph_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "Meta" / "Manifest" / "rx_export_manifest.json"
            timeline_path = root / "Buffer" / "Timeline" / "rxanimin_timeline_static.buf"
            master_path = root / "Buffer" / "Timeline" / "rxanimin_master_playback.buf"
            bone_static = root / "Buffer" / "Bone" / "face_bone_static.buf"
            bone_anim = root / "Buffer" / "Bone" / "face_bone_anim.buf"
            morph_anim = root / "Buffer" / "Morph" / "face_morph_anim.buf"
            manifest = {
                "format": "rx_runtime_manifest_v3",
                "animation_bank": {
                    "name": "rxanimin",
                    "default_clip_index": 0,
                    "timeline_static": str(timeline_path),
                    "master_playback": str(master_path),
                },
                "clips": [
                    {"name": "idle", "clip_index": 0, "clip_id": 0, "sample_count": 2, "frame_start": 0, "frame_end": 1, "frame_step": 1, "fps": 30, "default_ticks_per_sample": 4, "default_loop_start_sample": 0, "default_loop_end_sample": 1},
                    {"name": "dance", "clip_index": 1, "clip_id": 1, "sample_count": 3, "frame_start": 0, "frame_end": 2, "frame_step": 1, "fps": 30, "default_ticks_per_sample": 4, "default_loop_start_sample": 0, "default_loop_end_sample": 2},
                ],
                "payloads": {
                    "face": {
                        "bone": {
                            "static": str(bone_static),
                            "anim": str(bone_anim),
                            "slot_ids": [0, 1],
                        },
                        "morph": {
                            "anim": str(morph_anim),
                        },
                    }
                },
                "bone_exports": {},
                "morph_exports": {},
                "draw_parts": {},
                "geometry_exports": {},
            }
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            _write_uint4(
                bone_static,
                (
                    (2, 2, 3, 1),
                    (9, 9, 0, 2),
                    (2, 0, 0, 1),
                    (3, 8, 0, 2),
                    (0, 1, 0xFFFFFFFF, 0xFFFFFFFF),
                ),
            )
            _write_float4(bone_anim, np.arange(20 * 4, dtype="<f4").reshape((20, 4)))
            _write_uint4(
                morph_anim,
                (
                    (2, 2, 8, 0),
                    (2, 3, 0, 1),
                    (3, 5, 0, 1),
                    (101, 102, 103, 104),
                    (105, 106, 107, 108),
                    (201, 202, 203, 204),
                    (205, 206, 207, 208),
                    (209, 210, 211, 212),
                ),
            )

            result = delete_action_at_index(temp_dir, 0)

            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(result.deleted_name, "idle")
            self.assertEqual([clip["name"] for clip in updated["clips"]], ["dance"])
            self.assertEqual(updated["clips"][0]["clip_index"], 0)
            self.assertEqual(tuple(int(value) for value in _read_uint4(timeline_path)[0]), (1, 0, 0, 0))
            self.assertEqual(tuple(int(value) for value in _read_uint4(timeline_path)[1]), (3, 4, 0, 2))
            self.assertEqual(tuple(int(value) for value in _read_uint4(bone_static)[0]), (1, 2, 3, 1))
            np.testing.assert_array_equal(_read_float4(bone_anim), np.arange(20 * 4, dtype="<f4").reshape((20, 4))[8:])
            self.assertEqual(tuple(int(value) for value in _read_uint4(morph_anim)[0]), (1, 2, 8, 0))
            np.testing.assert_array_equal(_read_uint4(morph_anim)[2:], np.asarray(((201, 202, 203, 204), (205, 206, 207, 208), (209, 210, 211, 212)), dtype="<u4"))

    def test_rename_action_updates_manifest_without_reindexing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "Meta" / "Manifest" / "rx_export_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "format": "rx_runtime_manifest_v3",
                        "animation_bank": {"name": "rxanimin", "default_clip_index": 0},
                        "clips": [
                            {"name": "idle", "clip_index": 0, "clip_id": 0, "sample_count": 2},
                            {"name": "dance", "clip_index": 1, "clip_id": 1, "sample_count": 3},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rename_action_at_index(temp_dir, 1, "Attack")

            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual([clip["name"] for clip in updated["clips"]], ["idle", "attack"])
            self.assertEqual([clip["clip_index"] for clip in updated["clips"]], [0, 1])


if __name__ == "__main__":
    unittest.main()
