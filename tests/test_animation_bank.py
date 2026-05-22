import unittest
import importlib.util
import sys
from pathlib import Path


def _load_animation_bank_module():
    source_path = Path(__file__).resolve().parents[1] / "core" / "animation_bank.py"
    spec = importlib.util.spec_from_file_location("animation_bank_under_test", source_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


animation_bank = _load_animation_bank_module()
AnimationBank = animation_bank.AnimationBank
ClipSpec = animation_bank.ClipSpec
build_clip_spec = animation_bank.build_clip_spec
build_master_playback_rows = animation_bank.build_master_playback_rows
build_timeline_static_rows = animation_bank.build_timeline_static_rows
build_animation_bank_for_export = animation_bank.build_animation_bank_for_export
merge_clip_into_manifest = animation_bank.merge_clip_into_manifest


class AnimationBankTests(unittest.TestCase):
    def test_build_clip_spec_derives_ticks_from_source_and_target_fps(self):
        clip = build_clip_spec(
            name="Dance",
            clip_id=7,
            frame_start=0,
            frame_end=1680,
            frame_step=1,
            source_fps=30.0,
            target_game_fps=120.0,
            playback_speed=1.0,
        )

        self.assertEqual(clip.name, "dance")
        self.assertEqual(clip.sample_count, 1681)
        self.assertEqual(clip.default_ticks_per_sample, 4)
        self.assertEqual(clip.default_loop_start_sample, 0)
        self.assertEqual(clip.default_loop_end_sample, 1680)

    def test_build_clip_spec_uses_intuitive_playback_speed(self):
        faster = build_clip_spec("fast", 0, 0, 30, 1, source_fps=30.0, target_game_fps=120.0, playback_speed=2.0)
        slower = build_clip_spec("slow", 1, 0, 30, 1, source_fps=30.0, target_game_fps=120.0, playback_speed=0.5)

        self.assertEqual(faster.default_ticks_per_sample, 2)
        self.assertEqual(slower.default_ticks_per_sample, 8)

    def test_timeline_static_rows_store_clip_table(self):
        bank = AnimationBank(
            name="rxanimin",
            clips=(
                ClipSpec(name="idle", clip_id=0, clip_index=0, frame_start=0, frame_end=9, frame_step=1, sample_count=10, source_fps=30.0, target_game_fps=120.0, playback_speed=1.0, default_ticks_per_sample=4, default_loop_start_sample=0, default_loop_end_sample=9),
                ClipSpec(name="dance", clip_id=1, clip_index=1, frame_start=0, frame_end=19, frame_step=1, sample_count=20, source_fps=30.0, target_game_fps=120.0, playback_speed=1.0, default_ticks_per_sample=4, default_loop_start_sample=2, default_loop_end_sample=18),
            ),
        )

        rows = build_timeline_static_rows(bank)

        self.assertEqual(rows[0], (2, 0, 0, 0))
        self.assertEqual(rows[1], (10, 4, 0, 9))
        self.assertEqual(rows[2], (20, 4, 2, 18))

    def test_master_playback_rows_seed_from_default_clip(self):
        bank = AnimationBank(
            name="rxanimin",
            default_clip_index=1,
            clips=(
                ClipSpec(name="idle", clip_id=0, clip_index=0, frame_start=0, frame_end=9, frame_step=1, sample_count=10, source_fps=30.0, target_game_fps=120.0, playback_speed=1.0, default_ticks_per_sample=4, default_loop_start_sample=0, default_loop_end_sample=9),
                ClipSpec(name="dance", clip_id=1, clip_index=1, frame_start=0, frame_end=19, frame_step=1, sample_count=20, source_fps=30.0, target_game_fps=120.0, playback_speed=1.0, default_ticks_per_sample=3, default_loop_start_sample=2, default_loop_end_sample=18),
            ),
        )

        rows = build_master_playback_rows(bank)

        self.assertEqual(rows[0], (3, 0, 0, 0))
        self.assertEqual(rows[1], (3, 2, 18, 0))
        self.assertEqual(rows[2], (0, 0, 1, 1))

    def test_merge_clip_into_manifest_keeps_stable_indices(self):
        manifest = {}
        idle = build_clip_spec("Idle", 0, 0, 9, 1, source_fps=30.0, target_game_fps=120.0)
        dance = build_clip_spec("Dance", 1, 0, 19, 1, source_fps=30.0, target_game_fps=120.0)

        merge_clip_into_manifest(manifest, idle)
        merge_clip_into_manifest(manifest, dance)
        replacement_idle = build_clip_spec("Idle", 0, 0, 29, 1, source_fps=30.0, target_game_fps=120.0)
        merge_clip_into_manifest(manifest, replacement_idle)

        self.assertEqual(manifest["format"], "rx_runtime_manifest_v3")
        self.assertEqual([clip["name"] for clip in manifest["clips"]], ["idle", "dance"])
        self.assertEqual([clip["clip_index"] for clip in manifest["clips"]], [0, 1])
        self.assertEqual(manifest["clips"][0]["sample_count"], 30)
        self.assertEqual(manifest["clips"][1]["sample_count"], 20)

    def test_export_bank_includes_existing_manifest_clips_before_writing_timeline(self):
        manifest = {}
        idle = build_clip_spec("Idle", 0, 0, 9, 1, source_fps=30.0, target_game_fps=120.0)
        dance = build_clip_spec("Dance", 1, 0, 19, 1, source_fps=30.0, target_game_fps=120.0)
        merge_clip_into_manifest(manifest, idle)

        bank = build_animation_bank_for_export(manifest, dance)

        self.assertEqual([clip.name for clip in bank.clips], ["idle", "dance"])
        self.assertEqual([clip.clip_index for clip in bank.clips], [0, 1])
        self.assertEqual(build_timeline_static_rows(bank), [(2, 0, 0, 0), (10, 4, 0, 9), (20, 4, 0, 19)])


if __name__ == "__main__":
    unittest.main()
