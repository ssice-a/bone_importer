"""Shared UV coordinate transforms between game buffers and Blender."""

from __future__ import annotations


DEFAULT_UV_FLIP_V = True
DEFAULT_UV_MIRROR_U = False


def flip_uv_v(uv: tuple[float, float]) -> tuple[float, float]:
    return (float(uv[0]), 1.0 - float(uv[1]))


def mirror_uv_u(uv: tuple[float, float]) -> tuple[float, float]:
    return (1.0 - float(uv[0]), float(uv[1]))


def transform_uv(
    uv: tuple[float, float],
    *,
    mirror_u: bool = DEFAULT_UV_MIRROR_U,
    flip_v: bool = DEFAULT_UV_FLIP_V,
) -> tuple[float, float]:
    transformed = (float(uv[0]), float(uv[1]))
    if mirror_u:
        transformed = mirror_uv_u(transformed)
    if flip_v:
        transformed = flip_uv_v(transformed)
    return transformed


def game_uv_to_blender(
    uv: tuple[float, float],
    *,
    mirror_u: bool = DEFAULT_UV_MIRROR_U,
    flip_v: bool = DEFAULT_UV_FLIP_V,
) -> tuple[float, float]:
    return transform_uv(uv, mirror_u=mirror_u, flip_v=flip_v)


def blender_uv_to_game(
    uv: tuple[float, float],
    *,
    mirror_u: bool = DEFAULT_UV_MIRROR_U,
    flip_v: bool = DEFAULT_UV_FLIP_V,
) -> tuple[float, float]:
    return transform_uv(uv, mirror_u=mirror_u, flip_v=flip_v)
