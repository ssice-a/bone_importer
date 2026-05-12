"""Coordinate conversion helpers shared by static and runtime export paths."""

import math

from mathutils import Matrix

from ..constants import COORDINATE_X_ROTATION_DEGREES


BUFFER_CORRECTION_NONE = "NONE"
BUFFER_CORRECTION_Y_POS_90 = "Y_POS_90"
BUFFER_CORRECTION_Y_NEG_90 = "Y_NEG_90"

BUFFER_CORRECTION_ITEMS = (
    (BUFFER_CORRECTION_NONE, "Standard", "No extra rotation correction"),
    (BUFFER_CORRECTION_Y_POS_90, "Z +90", "Apply an extra world-space Z +90 correction"),
    (BUFFER_CORRECTION_Y_NEG_90, "Z -90", "Apply an extra world-space Z -90 correction"),
)

BUFFER_CORRECTION_CODE_MAP = {
    BUFFER_CORRECTION_NONE: 0,
    BUFFER_CORRECTION_Y_POS_90: 1,
    BUFFER_CORRECTION_Y_NEG_90: 2,
}


_GAME_TO_BLENDER_CORRECTION_MATRIX = Matrix.Rotation(math.radians(COORDINATE_X_ROTATION_DEGREES), 4, "X")
_BLENDER_TO_GAME_CORRECTION_MATRIX = _GAME_TO_BLENDER_CORRECTION_MATRIX.inverted()
_EXTRA_Y_POS_90_MATRIX = Matrix.Rotation(math.radians(90.0), 4, "Z")
_EXTRA_Y_NEG_90_MATRIX = Matrix.Rotation(math.radians(-90.0), 4, "Z")


def normalize_buffer_correction_mode(correction_mode):
    """Normalize unknown values back to the default correction mode."""
    normalized_mode = str(correction_mode or BUFFER_CORRECTION_NONE).upper()
    if normalized_mode in BUFFER_CORRECTION_CODE_MAP:
        return normalized_mode
    return BUFFER_CORRECTION_NONE


def get_proxy_buffer_correction_mode(proxy_armature):
    """Read the per-proxy special buffer correction mode."""
    return normalize_buffer_correction_mode(getattr(proxy_armature, "bi_buffer_correction_mode", BUFFER_CORRECTION_NONE))


def get_buffer_correction_code(correction_mode):
    """Expose a compact integer code for HLSL runtime buffers."""
    return int(BUFFER_CORRECTION_CODE_MAP[normalize_buffer_correction_mode(correction_mode)])


def _build_extra_blender_correction_matrix(correction_mode):
    """Build the optional extra Blender-space correction matrix for special buffers."""
    normalized_mode = normalize_buffer_correction_mode(correction_mode)
    if normalized_mode == BUFFER_CORRECTION_Y_POS_90:
        return _EXTRA_Y_POS_90_MATRIX.copy()
    if normalized_mode == BUFFER_CORRECTION_Y_NEG_90:
        return _EXTRA_Y_NEG_90_MATRIX.copy()
    return Matrix.Identity(4)


def build_extra_blender_correction_matrix(correction_mode):
    """Expose the optional extra Blender-space correction matrix."""
    return _build_extra_blender_correction_matrix(correction_mode)


def convert_matrix_from_game_to_blender(matrix, correction_mode=BUFFER_CORRECTION_NONE):
    """Convert a game-space skin matrix into Blender space with optional special-buffer correction."""
    extra_correction_inverse = _build_extra_blender_correction_matrix(correction_mode).inverted()
    return extra_correction_inverse @ _GAME_TO_BLENDER_CORRECTION_MATRIX @ matrix


def convert_matrix_from_blender_to_game(matrix, correction_mode=BUFFER_CORRECTION_NONE):
    """Convert a Blender-space skin matrix back into game space with optional special-buffer correction."""
    extra_correction = _build_extra_blender_correction_matrix(correction_mode)
    return _BLENDER_TO_GAME_CORRECTION_MATRIX @ extra_correction @ matrix
