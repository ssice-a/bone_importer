import math

from mathutils import Matrix

from ..constants import GAME_TO_BLENDER_X_DEGREES


def blender_from_game_matrix():
    return Matrix.Rotation(math.radians(GAME_TO_BLENDER_X_DEGREES), 4, "X")


def game_from_blender_matrix():
    return blender_from_game_matrix().inverted()


def convert_game_matrix_to_blender(matrix):
    correction = blender_from_game_matrix()
    correction_inv = correction.inverted()
    return correction @ matrix @ correction_inv


def convert_blender_matrix_to_game(matrix):
    correction = game_from_blender_matrix()
    correction_inv = correction.inverted()
    return correction @ matrix @ correction_inv


def coordinate_conversion_label():
    return f"Game -> Blender: rotate X by +{GAME_TO_BLENDER_X_DEGREES:.0f} deg"
