"""处理 VS-T0 调色板布局和矩阵打包格式的辅助函数。"""

from mathutils import Matrix

from ..constants import RESERVED_PALETTE_ROWS


def calculate_slot_capacity_for_part_size(part_row_count):
    """计算一个部位窗口在扣除保留行后还能容纳多少根骨骼。"""
    part_row_count = max(int(part_row_count), RESERVED_PALETTE_ROWS)
    return max(0, (part_row_count - RESERVED_PALETTE_ROWS) // 3)


def build_identity_rows(row_count):
    """生成足够长的单位矩阵行列表，用来初始化缓冲区片段。"""
    rows = []
    while len(rows) < row_count:
        rows.extend(
            [
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
            ]
        )
    return rows[:row_count]


def build_empty_palette_segment(part_row_count):
    """创建一个新的片段，并用单位矩阵行初始化。"""
    return build_identity_rows(part_row_count)


def build_identity_buffer_rows(buffer_row_count):
    """创建完整缓冲区，并用单位矩阵行初始化。"""
    return build_identity_rows(buffer_row_count)


def flatten_matrix_to_list(matrix):
    """把 4x4 矩阵拍平成 16 个值，便于写入 Blender 属性。"""
    return [matrix[row][column] for row in range(4) for column in range(4)]


def build_matrix_from_flat_values(values):
    """把 16 个拍平的值还原成 4x4 矩阵。"""
    if not values or len(values) != 16:
        return Matrix.Identity(4)
    return Matrix(
        (
            (values[0], values[1], values[2], values[3]),
            (values[4], values[5], values[6], values[7]),
            (values[8], values[9], values[10], values[11]),
            (values[12], values[13], values[14], values[15]),
        )
    )


def build_matrix_from_palette_rows(rows):
    """把 VS-T0 中一根骨骼的 3 行 float4 还原成 4x4 矩阵。"""
    if not rows or len(rows) != 3:
        return Matrix.Identity(4)
    first_row, second_row, third_row = rows
    return Matrix(
        (
            (first_row[0], first_row[1], first_row[2], first_row[3]),
            (second_row[0], second_row[1], second_row[2], second_row[3]),
            (third_row[0], third_row[1], third_row[2], third_row[3]),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def convert_matrix_to_palette_rows(matrix):
    """把 4x4 矩阵转换成 VS-T0 需要的 3 行 float4。"""
    return [
        (float(matrix[0][0]), float(matrix[0][1]), float(matrix[0][2]), float(matrix[0][3])),
        (float(matrix[1][0]), float(matrix[1][1]), float(matrix[1][2]), float(matrix[1][3])),
        (float(matrix[2][0]), float(matrix[2][1]), float(matrix[2][2]), float(matrix[2][3])),
    ]
