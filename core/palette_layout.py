"""Helpers for VS-T0 palette row layout and matrix packing."""

from mathutils import Matrix

from ..addon_constants import RESERVED_PALETTE_ROWS


def calculate_slot_capacity_for_part_size(part_row_count):
    """Return how many 3-row bones fit inside a part window after reserved rows."""
    part_row_count = max(int(part_row_count), RESERVED_PALETTE_ROWS)
    return max(0, (part_row_count - RESERVED_PALETTE_ROWS) // 3)


def build_identity_rows(row_count):
    """Build a list of identity-style float4 rows long enough to fill a buffer segment."""
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
    """Create a fresh palette segment initialized to identity rows."""
    return build_identity_rows(part_row_count)


def build_identity_buffer_rows(buffer_row_count):
    """Create a full float4 buffer initialized with identity rows."""
    return build_identity_rows(buffer_row_count)


def flatten_matrix_to_list(matrix):
    """Flatten a 4x4 matrix into a 16-value row-major list for Blender properties."""
    return [matrix[row][column] for row in range(4) for column in range(4)]


def build_matrix_from_flat_values(values):
    """Build a 4x4 Matrix from a flat 16-value row-major list."""
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
    """Rebuild a 4x4 matrix from the three VS-T0 float4 rows stored for one bone."""
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
    """Convert a 4x4 matrix into the three float4 rows expected by VS-T0."""
    return [
        (float(matrix[0][0]), float(matrix[0][1]), float(matrix[0][2]), float(matrix[0][3])),
        (float(matrix[1][0]), float(matrix[1][1]), float(matrix[1][2]), float(matrix[1][3])),
        (float(matrix[2][0]), float(matrix[2][1]), float(matrix[2][2]), float(matrix[2][3])),
    ]
