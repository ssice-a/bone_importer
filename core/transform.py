"""处理游戏空间与 Blender 空间之间的最终蒙皮矩阵转换。"""

import math

from mathutils import Matrix

from ..constants import COORDINATE_X_ROTATION_DEGREES


def _build_game_to_blender_correction_matrix():
    """构建把游戏躺地姿态转到 Blender 站立姿态的统一修正矩阵。"""
    return Matrix.Rotation(math.radians(COORDINATE_X_ROTATION_DEGREES), 4, "X")


def convert_matrix_from_game_to_blender(matrix):
    """把游戏最终蒙皮矩阵整体左乘到 Blender 站立空间。"""
    correction_matrix = _build_game_to_blender_correction_matrix()
    return correction_matrix @ matrix


def convert_matrix_from_blender_to_game(matrix):
    """把 Blender 最终蒙皮矩阵整体左乘逆变换回游戏空间。"""
    correction_matrix = _build_game_to_blender_correction_matrix()
    correction_inverse = correction_matrix.inverted()
    return correction_inverse @ matrix
