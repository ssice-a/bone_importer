"""Animation Bank and Clip table helpers for RX runtime exports.

This module is intentionally Blender-free. It owns the small but important
contract shared by manifest merging, timeline buffers, HLSL sampling, and the
runtime UI action selector.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os


ANIM_FLAG_PLAYING = 1
ANIM_FLAG_LOOPING = 2

DEFAULT_BANK_NAME = "rxanimin"
RUNTIME_MANIFEST_FORMAT = "rx_runtime_manifest_v3"
TIMELINE_BUFFER_DIR = os.path.join("Buffer", "Timeline")
MANIFEST_DIR = os.path.join("Meta", "Manifest")


def normalize_clip_name(name: str | None) -> str:
    """Return a stable non-empty logical Clip key."""

    candidate = str(name or "").strip()
    return candidate.lower() if candidate else DEFAULT_BANK_NAME


def sanitize_export_name(name: str | None, fallback: str = DEFAULT_BANK_NAME) -> str:
    """Build a filesystem-safe stem without depending on Blender modules."""

    candidate = str(name or "").strip() or str(fallback or "").strip() or DEFAULT_BANK_NAME
    candidate = candidate.replace(os.sep, "_").replace("/", "_")
    safe = "".join(character if character.isalnum() or character in ("_", "-", ".") else "_" for character in candidate)
    return safe.strip("_") or DEFAULT_BANK_NAME


def normalize_frame_range(frame_start: int, frame_end: int, frame_step: int) -> tuple[int, ...]:
    start = int(frame_start)
    end = int(frame_end)
    step = int(frame_step)
    if step <= 0:
        raise ValueError("Frame Step must be greater than zero")
    if end < start:
        raise ValueError("Frame End must be greater than or equal to Frame Start")
    return tuple(range(start, end + 1, step))


def derive_ticks_per_sample(
    *,
    source_fps: float,
    target_game_fps: float = 120.0,
    playback_speed: float = 1.0,
    frame_step: int = 1,
) -> int:
    """Convert intuitive playback speed into the current integer tick backend."""

    safe_source_fps = max(float(source_fps), 1e-6)
    safe_target_fps = max(float(target_game_fps), 1.0)
    safe_speed = max(float(playback_speed), 0.01)
    safe_step = max(int(frame_step), 1)
    sample_fps = safe_source_fps / float(safe_step)
    return max(int(round(safe_target_fps / max(sample_fps * safe_speed, 1e-6))), 1)


@dataclass(frozen=True)
class ClipSpec:
    name: str
    clip_id: int
    clip_index: int
    frame_start: int
    frame_end: int
    frame_step: int
    sample_count: int
    source_fps: float
    target_game_fps: float
    playback_speed: float
    default_ticks_per_sample: int
    default_loop_start_sample: int
    default_loop_end_sample: int

    def with_index(self, clip_index: int) -> "ClipSpec":
        return replace(self, clip_index=int(clip_index))

    def to_manifest_payload(self) -> dict:
        return {
            "name": self.name,
            "clip_name": self.name,
            "clip_id": int(self.clip_id),
            "clip_index": int(self.clip_index),
            "frame_start": int(self.frame_start),
            "frame_end": int(self.frame_end),
            "frame_step": int(self.frame_step),
            "sample_count": int(self.sample_count),
            "fps": float(self.source_fps),
            "source_fps": float(self.source_fps),
            "target_game_fps": float(self.target_game_fps),
            "playback_speed": float(self.playback_speed),
            "default_ticks_per_sample": int(self.default_ticks_per_sample),
            "default_loop_start_sample": int(self.default_loop_start_sample),
            "default_loop_end_sample": int(self.default_loop_end_sample),
        }


@dataclass(frozen=True)
class AnimationBank:
    name: str = DEFAULT_BANK_NAME
    clips: tuple[ClipSpec, ...] = ()
    default_clip_index: int = 0
    flags: int = 0
    timeline_static_path: str = ""
    master_playback_path: str = ""

    @property
    def safe_name(self) -> str:
        return sanitize_export_name(self.name, DEFAULT_BANK_NAME)

    @property
    def default_clip(self) -> ClipSpec:
        if not self.clips:
            return build_clip_spec(self.name, 0, 0, 0, 1, source_fps=30.0, target_game_fps=120.0)
        for clip in self.clips:
            if clip.clip_index == self.default_clip_index:
                return clip
        return self.clips[0]


def build_clip_spec(
    name: str,
    clip_id: int,
    frame_start: int,
    frame_end: int,
    frame_step: int,
    *,
    source_fps: float,
    target_game_fps: float = 120.0,
    playback_speed: float = 1.0,
    clip_index: int = 0,
    loop_start_sample: int | None = None,
    loop_end_sample: int | None = None,
) -> ClipSpec:
    frames = normalize_frame_range(frame_start, frame_end, frame_step)
    sample_count = max(len(frames), 1)
    loop_start = 0 if loop_start_sample is None else int(loop_start_sample)
    loop_end = sample_count - 1 if loop_end_sample is None else int(loop_end_sample)
    loop_start, loop_end = clamp_loop_sample_range(sample_count, loop_start, loop_end)
    ticks_per_sample = derive_ticks_per_sample(
        source_fps=source_fps,
        target_game_fps=target_game_fps,
        playback_speed=playback_speed,
        frame_step=frame_step,
    )
    return ClipSpec(
        name=normalize_clip_name(name),
        clip_id=int(clip_id),
        clip_index=int(clip_index),
        frame_start=int(frames[0]),
        frame_end=int(frames[-1]),
        frame_step=int(frame_step),
        sample_count=sample_count,
        source_fps=float(source_fps),
        target_game_fps=float(target_game_fps),
        playback_speed=float(playback_speed),
        default_ticks_per_sample=ticks_per_sample,
        default_loop_start_sample=loop_start,
        default_loop_end_sample=loop_end,
    )


def clamp_loop_sample_range(sample_count: int, loop_start: int, loop_end: int) -> tuple[int, int]:
    safe_count = max(int(sample_count), 1)
    start = min(max(int(loop_start), 0), safe_count - 1)
    end = min(max(int(loop_end), 0), safe_count - 1)
    if end < start:
        return 0, safe_count - 1
    return start, end


def clip_spec_from_manifest_payload(payload: dict) -> ClipSpec:
    sample_count = max(int(payload.get("sample_count", payload.get("frame_count", 1)) or 1), 1)
    frame_step = max(int(payload.get("frame_step", 1) or 1), 1)
    frame_start = int(payload.get("frame_start", 0) or 0)
    frame_end = int(payload.get("frame_end", frame_start + (sample_count - 1) * frame_step) or frame_start)
    source_fps = float(payload.get("source_fps", payload.get("fps", 30.0)) or 30.0)
    target_game_fps = float(payload.get("target_game_fps", 120.0) or 120.0)
    playback_speed = float(payload.get("playback_speed", 1.0) or 1.0)
    return ClipSpec(
        name=normalize_clip_name(payload.get("name", payload.get("clip_name", DEFAULT_BANK_NAME))),
        clip_id=int(payload.get("clip_id", 0) or 0),
        clip_index=int(payload.get("clip_index", 0) or 0),
        frame_start=frame_start,
        frame_end=frame_end,
        frame_step=frame_step,
        sample_count=sample_count,
        source_fps=source_fps,
        target_game_fps=target_game_fps,
        playback_speed=playback_speed,
        default_ticks_per_sample=max(int(payload.get("default_ticks_per_sample", 1) or 1), 1),
        default_loop_start_sample=int(payload.get("default_loop_start_sample", 0) or 0),
        default_loop_end_sample=int(payload.get("default_loop_end_sample", sample_count - 1) or 0),
    )


def clip_specs_from_manifest(manifest: dict) -> tuple[ClipSpec, ...]:
    raw_clips = manifest.get("clips", [])
    if isinstance(raw_clips, dict):
        payloads = []
        for index, (name, payload) in enumerate(raw_clips.items()):
            clip_payload = dict(payload or {})
            clip_payload.setdefault("name", name)
            clip_payload.setdefault("clip_index", index)
            payloads.append(clip_payload)
    else:
        payloads = [dict(payload or {}) for payload in list(raw_clips or [])]
    clips = [clip_spec_from_manifest_payload(payload) for payload in payloads]
    clips.sort(key=lambda clip: int(clip.clip_index))
    return tuple(clips)


def build_animation_bank_from_manifest(manifest: dict, bank_name: str = DEFAULT_BANK_NAME) -> AnimationBank:
    bank_payload = dict(manifest.get("animation_bank", {}) or {})
    clips = clip_specs_from_manifest(manifest)
    default_clip_index = int(bank_payload.get("default_clip_index", 0) or 0)
    return AnimationBank(
        name=str(bank_payload.get("name", bank_name) or bank_name),
        clips=clips,
        default_clip_index=default_clip_index,
        flags=int(bank_payload.get("flags", 0) or 0),
        timeline_static_path=str(bank_payload.get("timeline_static", "") or ""),
        master_playback_path=str(bank_payload.get("master_playback", "") or ""),
    )


def build_timeline_static_rows(bank: AnimationBank) -> list[tuple[int, int, int, int]]:
    rows = [
        (
            max(len(bank.clips), 1),
            0,
            int(bank.default_clip_index),
            int(bank.flags),
        )
    ]
    for clip in sorted(bank.clips, key=lambda item: item.clip_index):
        rows.append(
            (
                int(clip.sample_count),
                int(clip.default_ticks_per_sample),
                int(clip.default_loop_start_sample),
                int(clip.default_loop_end_sample),
            )
        )
    if len(rows) == 1:
        default_clip = bank.default_clip
        rows.append(
            (
                int(default_clip.sample_count),
                int(default_clip.default_ticks_per_sample),
                int(default_clip.default_loop_start_sample),
                int(default_clip.default_loop_end_sample),
            )
        )
    return rows


def build_master_playback_rows(bank: AnimationBank) -> list[tuple[int, int, int, int]]:
    clip = bank.default_clip
    return [
        (int(ANIM_FLAG_PLAYING | ANIM_FLAG_LOOPING), 0, 0, 0),
        (
            int(clip.default_ticks_per_sample),
            int(clip.default_loop_start_sample),
            int(clip.default_loop_end_sample),
            0,
        ),
        (0, 0, int(clip.clip_index), int(clip.clip_index)),
    ]


def animation_bank_paths(output_directory: str, bank_name: str = DEFAULT_BANK_NAME) -> tuple[str, str, str]:
    root = os.path.abspath(output_directory or ".")
    safe_name = sanitize_export_name(bank_name, DEFAULT_BANK_NAME)
    timeline_path = os.path.join(root, TIMELINE_BUFFER_DIR, f"{safe_name}_timeline_static.buf")
    master_path = os.path.join(root, TIMELINE_BUFFER_DIR, f"{safe_name}_master_playback.buf")
    metadata_path = os.path.join(root, MANIFEST_DIR, f"{safe_name}_clip.json")
    return timeline_path, master_path, metadata_path


def _ensure_manifest_shape(manifest: dict, bank_name: str = DEFAULT_BANK_NAME) -> dict:
    manifest["format"] = RUNTIME_MANIFEST_FORMAT
    manifest.setdefault("animation_bank", {})
    manifest["animation_bank"].setdefault("name", bank_name)
    manifest["animation_bank"].setdefault("default_clip_index", 0)
    manifest["animation_bank"].setdefault("flags", 0)
    if not isinstance(manifest.get("clips"), list):
        manifest["clips"] = [clip.to_manifest_payload() for clip in clip_specs_from_manifest(manifest)]
    manifest.setdefault("draw_parts", {})
    manifest.setdefault("bone_exports", {})
    manifest.setdefault("morph_exports", {})
    manifest.setdefault("geometry_exports", {})
    manifest.setdefault("payloads", {})
    return manifest


def merge_clip_into_manifest(manifest: dict, clip: ClipSpec, bank_name: str = DEFAULT_BANK_NAME) -> dict:
    """Append or replace a Clip while preserving stable clip_index values."""

    _ensure_manifest_shape(manifest, bank_name)
    existing_clips = clip_specs_from_manifest(manifest)
    by_name = {existing.name: existing for existing in existing_clips}
    if clip.name in by_name:
        stable_index = by_name[clip.name].clip_index
    else:
        stable_index = (max((existing.clip_index for existing in existing_clips), default=-1) + 1)
    replacement = clip.with_index(stable_index)
    merged = [replacement if existing.name == replacement.name else existing for existing in existing_clips]
    if replacement.name not in by_name:
        merged.append(replacement)
    merged.sort(key=lambda existing: existing.clip_index)
    manifest["clips"] = [existing.to_manifest_payload() for existing in merged]
    return manifest
