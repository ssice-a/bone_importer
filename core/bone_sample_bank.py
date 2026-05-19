"""Shared Bone Payload sampling plan utilities.

This module is intentionally Blender-free so grouping and payload slicing can be
tested without a live ``bpy`` runtime. Blender-specific sampling stays in the
adapter that builds the actual sample arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Iterable, Mapping

import numpy as np


TRUTHY_CACHE_VALUES = {"1", "true", "yes", "on"}
FALSEY_CACHE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class BoneSampleGroupPlan:
    """One deduplicated source-bone set that can be sampled in one pass."""

    group_key: str
    correction_matrix: Any
    sample_entries: tuple[tuple[Any, Any, str], ...]
    sample_keys: tuple[Any, ...]
    index_by_key: Mapping[Any, int]


@dataclass(frozen=True)
class BonePayloadSamplePlan:
    """How one DrawPart selects columns from a BoneSampleGroupPlan."""

    draw_key: str
    group_key: str
    sample_keys: tuple[Any, ...]
    sample_indices: tuple[int, ...]


@dataclass(frozen=True)
class BoneSamplePlan:
    """Deduplicated source-bone sampling groups plus per-DrawPart selections."""

    groups: Mapping[str, BoneSampleGroupPlan]
    payloads: Mapping[str, BonePayloadSamplePlan]


def build_bone_sample_plan(
    prepared_payloads: Iterable[dict],
    binding_sample_key: Callable[[Any], Any],
) -> BoneSamplePlan:
    """Build a shared sampling plan from prepared DrawPart payloads.

    ``prepared_payloads`` is deliberately duck-typed so the exporter can pass its
    current payload dictionaries while tests can pass lightweight fakes.
    """

    group_payloads: dict[str, dict[str, Any]] = {}
    payload_sample_keys: dict[str, tuple[str, tuple[Any, ...]]] = {}

    for payload in prepared_payloads:
        draw_part = payload.get("draw_part")
        draw_key = str(payload.get("draw_key") or getattr(draw_part, "draw_key", ""))
        if not draw_key:
            raise ValueError("prepared payload is missing draw_key")

        group_key = str(payload["correction_mode"])
        group = group_payloads.setdefault(
            group_key,
            {
                "correction_matrix": payload.get("correction_matrix"),
                "entries_by_key": {},
            },
        )

        sample_keys = []
        for binding in payload.get("bindings", ()) or ():
            sample_key = binding_sample_key(binding)
            group["entries_by_key"][sample_key] = (
                sample_key,
                binding.source_armature,
                str(binding.source_bone),
            )
            sample_keys.append(sample_key)
        payload_sample_keys[draw_key] = (group_key, tuple(sample_keys))

    groups: dict[str, BoneSampleGroupPlan] = {}
    for group_key, group in group_payloads.items():
        sample_entries = tuple(
            sorted(
                group["entries_by_key"].values(),
                key=_sample_entry_sort_key,
            )
        )
        sample_keys = tuple(entry[0] for entry in sample_entries)
        index_by_key = {sample_key: index for index, sample_key in enumerate(sample_keys)}
        groups[group_key] = BoneSampleGroupPlan(
            group_key=group_key,
            correction_matrix=group["correction_matrix"],
            sample_entries=sample_entries,
            sample_keys=sample_keys,
            index_by_key=index_by_key,
        )

    payloads: dict[str, BonePayloadSamplePlan] = {}
    for draw_key, (group_key, sample_keys) in payload_sample_keys.items():
        group = groups[group_key]
        payloads[draw_key] = BonePayloadSamplePlan(
            draw_key=draw_key,
            group_key=group_key,
            sample_keys=sample_keys,
            sample_indices=tuple(group.index_by_key[sample_key] for sample_key in sample_keys),
        )

    return BoneSamplePlan(groups=groups, payloads=payloads)


def select_payload_samples(sample_cache, sample_indices: Iterable[int]):
    """Return ``sample_cache`` columns ordered for one DrawPart payload."""

    indices = tuple(int(index) for index in sample_indices)
    return np.asarray(sample_cache[:, indices, :], dtype="<f4")


def resolve_sample_cache_directory(
    output_directory: str,
    explicit_cache_dir: str = "",
    use_cache_flag: str = "",
    path_resolver: Callable[[str], str] = os.path.abspath,
) -> str:
    """Resolve the opt-in NPY cache directory shared by every export entrypoint."""

    raw_cache_dir = str(explicit_cache_dir or "").strip()
    raw_cache_flag = str(use_cache_flag or "").strip().lower()
    output_root = str(output_directory or ".")

    if raw_cache_dir:
        normalized_cache_dir = raw_cache_dir.lower()
        if normalized_cache_dir in FALSEY_CACHE_VALUES:
            return ""
        if normalized_cache_dir in TRUTHY_CACHE_VALUES:
            return path_resolver(os.path.join(output_root, ".rx_bone_sample_cache"))
        return path_resolver(raw_cache_dir)

    if raw_cache_flag in TRUTHY_CACHE_VALUES:
        return path_resolver(os.path.join(output_root, ".rx_bone_sample_cache"))

    return ""


def _sample_entry_sort_key(entry: tuple[Any, Any, str]) -> tuple[str, str, str]:
    sample_key, source_armature, source_bone = entry
    return (
        str(getattr(source_armature, "name", "")),
        str(source_bone),
        repr(sample_key),
    )
