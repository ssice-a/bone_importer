"""Runtime coordinate contract shared by RX export and generated HLSL.

This module is the single Python-side truth source for Blender-to-game
coordinate rules used by the manifest-driven RX route. Legacy palette import
and export can still use ``core.transform`` for old proxy workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RuntimeCoordinateContract:
    """The coordinate rules a DrawPart's geometry and Bone Payload must share."""

    name: str
    mirror_x_default: bool = True
    uv_flip_v_default: bool = True


RX_RUNTIME_COORDINATE_CONTRACT = RuntimeCoordinateContract(
    name="RX_RUNTIME_YV_AXIS",
    mirror_x_default=True,
    uv_flip_v_default=True,
)


def mirror_x_vector(value: Sequence[float]) -> tuple[float, float, float]:
    """Mirror a Blender-space vector/point into RX game-space X."""

    return (-float(value[0]), float(value[1]), float(value[2]))


def mirror_x_array(values):
    """Return a copy of a NumPy-like ``Nx3`` array mirrored on X."""

    mirrored = values.copy()
    mirrored[:, 0] *= -1.0
    return mirrored


def bitangent_sign_needs_flip(*, mirror_x: bool, uv_flip_v: bool) -> bool:
    """Handedness flips when exactly one orientation-changing rule is active."""

    return bool(mirror_x) ^ bool(uv_flip_v)


def resolve_object_mirror_x(obj, default: bool | None = None) -> bool:
    """Resolve the mirror-X rule from common importer metadata."""

    fallback = RX_RUNTIME_COORDINATE_CONTRACT.mirror_x_default if default is None else bool(default)
    value = _object_get(obj, "bmc_mirror_flip", None)
    if value is None:
        value = _object_get(obj, "modimp_mirror_flip", None)
    if value is None:
        return fallback
    return bool(value)


def resolve_object_uv_flip_v(obj, default: bool | None = None) -> bool:
    """Resolve the UV V-flip rule from common importer metadata."""

    fallback = RX_RUNTIME_COORDINATE_CONTRACT.uv_flip_v_default if default is None else bool(default)
    value = _object_get(obj, "bmc_uv_flip_v", None)
    if value is None:
        value = _object_get(obj, "modimp_flip_v", None)
    if value is None:
        return fallback
    return bool(value)


def yv_axis_skin_rows(
    row0: Sequence[float],
    row1: Sequence[float],
    row2: Sequence[float],
) -> tuple[tuple[float, float, float, float], ...]:
    """Convert Blender-space skin rows to the RX runtime palette basis.

    YV/EFMI axis conversion itself is not a mirror. Mirrored importer slot
    layout is handled by slot binding remap in ``core.slot_contract``; the
    palette shader only performs the YV row mapping:

    ``game_row_0 =  blender_row_0``
    ``game_row_1 =  blender_row_2``
    ``game_row_2 = -blender_row_1``
    """

    return (
        (float(row0[0]), float(row0[1]), float(row0[2]), float(row0[3])),
        (float(row2[0]), float(row2[1]), float(row2[2]), float(row2[3])),
        (-float(row1[0]), -float(row1[1]), -float(row1[2]), -float(row1[3])),
    )


def hlsl_coordinate_contract() -> str:
    """Generated HLSL include for the RX runtime coordinate contract."""

    return RX_RUNTIME_COORDINATE_CONTRACT_HLSLI


def _object_get(obj, key: str, default=None):
    if obj is None:
        return default
    get = getattr(obj, "get", None)
    if callable(get):
        try:
            return get(key, default)
        except TypeError:
            pass
    return getattr(obj, key, default)


RX_RUNTIME_COORDINATE_CONTRACT_HLSLI = r"""#ifndef RX_ANIM_COORDINATE_CONTRACT_HLSLI
#define RX_ANIM_COORDINATE_CONTRACT_HLSLI

// Runtime Coordinate Contract: RX_RUNTIME_YV_AXIS.
// YV/EFMI axis conversion itself is not a mirror. Mirrored imported slot
// layouts are handled by slot binding remap in the exporter; the game VS
// consumes palette rows like the YV reference shader:
//     game_row_0 =  blender_row_0
//     game_row_1 =  blender_row_2
//     game_row_2 = -blender_row_1
void RxConvertSkinRowsFromBlenderToGame(
    float4 blender0,
    float4 blender1,
    float4 blender2,
    out float4 game0,
    out float4 game1,
    out float4 game2
)
{
    game0 = blender0;
    game1 = blender2;
    game2 = -blender1;
}

#endif
"""
