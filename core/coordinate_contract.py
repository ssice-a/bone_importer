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
    uv_mirror_u_default: bool = False
    uv_flip_v_default: bool = True


RX_RUNTIME_COORDINATE_CONTRACT = RuntimeCoordinateContract(
    name="RX_RUNTIME_YV_AXIS",
    mirror_x_default=True,
    uv_mirror_u_default=False,
    uv_flip_v_default=True,
)

RX_BONE_PAYLOAD_FLAG_MIRROR_X = 1


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


def mirror_uv_u(uv: Sequence[float]) -> tuple[float, float]:
    """Mirror a UV coordinate horizontally for explicitly mirrored UV layouts."""

    return (1.0 - float(uv[0]), float(uv[1]))


def resolve_object_mirror_x(obj, default: bool | None = None) -> bool:
    """Resolve the mirror-X export rule.

    Bone Importer owns this decision.  Importer metadata is only a compatibility
    fallback for older scenes that have not saved the explicit export checkbox.
    """

    fallback = RX_RUNTIME_COORDINATE_CONTRACT.mirror_x_default if default is None else bool(default)
    value = _object_get(obj, "bi_export_mirror_x", None)
    if value is None:
        value = _object_get(obj, "bmc_mirror_flip", None)
    if value is None:
        value = _object_get(obj, "modimp_mirror_flip", None)
    if value is None:
        return fallback
    return bool(value)


def resolve_object_uv_mirror_u(obj, default: bool | None = None) -> bool:
    """Resolve the explicit Blender-UV to game-UV U adapter."""

    fallback = RX_RUNTIME_COORDINATE_CONTRACT.uv_mirror_u_default if default is None else bool(default)
    value = _object_get(obj, "bi_export_uv_mirror_u", None)
    if value is None:
        value = _object_get(obj, "bmc_uv_mirror_u", None)
    if value is None:
        value = _object_get(obj, "bmc_mirror_uv_u", None)
    if value is None:
        value = _object_get(obj, "modimp_mirror_uv_u", None)
    if value is None:
        value = _object_get(obj, "modimp_uv_mirror_u", None)
    if value is None:
        return fallback
    return bool(value)


def resolve_object_uv_flip_v(obj, default: bool | None = None) -> bool:
    """Resolve the Blender-UV to game-UV V adapter."""

    fallback = RX_RUNTIME_COORDINATE_CONTRACT.uv_flip_v_default if default is None else bool(default)
    value = _object_get(obj, "bi_export_uv_flip_v", None)
    if value is None:
        value = _object_get(obj, "bmc_uv_flip_v", None)
    if value is None:
        value = _object_get(obj, "modimp_flip_v", None)
    if value is None:
        return fallback
    return bool(value)


def mirror_x_skin_rows(
    row0: Sequence[float],
    row1: Sequence[float],
    row2: Sequence[float],
) -> tuple[tuple[float, float, float, float], ...]:
    """Apply ``Mx * skin * Mx`` for meshes imported through mirror-X.

    3dmigoto-bone-merge mirrors imported vertex coordinates on Blender X but
    preserves BLENDINDICES/vertex-group ids. Runtime slot ids therefore remain
    unchanged; only the final affine skin matrix needs the mirror-space
    conjugation before it is handed back to the game.
    """

    return (
        (float(row0[0]), -float(row0[1]), -float(row0[2]), -float(row0[3])),
        (-float(row1[0]), float(row1[1]), float(row1[2]), float(row1[3])),
        (-float(row2[0]), float(row2[1]), float(row2[2]), float(row2[3])),
    )


def yv_axis_skin_rows(
    row0: Sequence[float],
    row1: Sequence[float],
    row2: Sequence[float],
    *,
    mirror_x: bool = False,
) -> tuple[tuple[float, float, float, float], ...]:
    """Convert Blender-space skin rows to the RX runtime palette basis.

    YV/EFMI axis conversion itself is not a mirror. Mirror metadata may affect
    exported geometry vector values and final skin rows, but it must not
    silently remap Bone Payload slot ids. Non-identity slot binding belongs to
    an explicit Bone Slot Map. For mirror-X imports, rows are first converted by
    ``Mx * skin * Mx`` and then passed through the YV row mapping:

    ``game_row_0 =  blender_row_0``
    ``game_row_1 =  blender_row_2``
    ``game_row_2 = -blender_row_1``
    """

    if mirror_x:
        row0, row1, row2 = mirror_x_skin_rows(row0, row1, row2)

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
// YV/EFMI axis conversion itself is not a mirror. Mirror metadata may affect
// exported geometry and UV values, but Bone Payload slot ids remain runtime
// namespace ids unless the user provides an explicit Bone Slot Map. The game VS
// consumes palette rows like the YV reference shader:
//     game_row_0 =  blender_row_0
//     game_row_1 =  blender_row_2
//     game_row_2 = -blender_row_1
static const uint RX_BONE_PAYLOAD_FLAG_MIRROR_X = 1u;

void RxMirrorSkinRowsOnX(
    float4 row0,
    float4 row1,
    float4 row2,
    out float4 mirrored0,
    out float4 mirrored1,
    out float4 mirrored2
)
{
    // Mx * skin * Mx. Mirror import changes vector space, not slot ids.
    mirrored0 = float4(row0.x, -row0.y, -row0.z, -row0.w);
    mirrored1 = float4(-row1.x, row1.y, row1.z, row1.w);
    mirrored2 = float4(-row2.x, row2.y, row2.z, row2.w);
}

void RxConvertSkinRowsFromBlenderToGame(
    float4 blender0,
    float4 blender1,
    float4 blender2,
    uint payload_flags,
    out float4 game0,
    out float4 game1,
    out float4 game2
)
{
    if ((payload_flags & RX_BONE_PAYLOAD_FLAG_MIRROR_X) != 0u)
    {
        float4 mirrored0, mirrored1, mirrored2;
        RxMirrorSkinRowsOnX(blender0, blender1, blender2, mirrored0, mirrored1, mirrored2);
        blender0 = mirrored0;
        blender1 = mirrored1;
        blender2 = mirrored2;
    }

    game0 = blender0;
    game1 = blender2;
    game2 = -blender1;
}

#endif
"""
