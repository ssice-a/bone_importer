"""读写插件使用的调色板二进制和元数据文件。"""

import json
import os
from array import array

import bpy

from .models import LoadedPaletteFile


def resolve_palette_export_paths(raw_output_path, armature_name):
    """解析导出二进制文件和同名元数据文件的路径。"""
    output_path = bpy.path.abspath(raw_output_path or "//")
    root_path, extension = os.path.splitext(output_path)
    if not extension:
        if output_path.endswith(os.sep) or output_path.endswith("/") or os.path.isdir(output_path):
            output_path = os.path.join(output_path, f"{armature_name}_vst0_palette.bin")
        else:
            output_path = f"{output_path}.bin"
        root_path, _ = os.path.splitext(output_path)
    return output_path, f"{root_path}.json"


def write_palette_package_to_disk(package, output_path, armature_name, write_metadata=True):
    """把调色板 float4 行写入磁盘，并可选写出 JSON 元数据。"""
    binary_path, metadata_path = resolve_palette_export_paths(output_path, armature_name)

    output_directory = os.path.dirname(binary_path)
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)

    flat_float_values = array("f")
    for row in package["buffer_rows"]:
        flat_float_values.extend(row)
    with open(binary_path, "wb") as binary_file:
        flat_float_values.tofile(binary_file)

    if write_metadata:
        with open(metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(package["metadata"], metadata_file, indent=2, ensure_ascii=False)

    return binary_path, metadata_path


def convert_flat_float_values_to_rows(flat_float_values):
    """把拍平的 float 序列还原成 float4 行列表。"""
    if len(flat_float_values) % 4 != 0:
        raise ValueError("Palette binary does not contain a whole number of float4 rows")
    return [
        tuple(float(flat_float_values[index + offset]) for offset in range(4))
        for index in range(0, len(flat_float_values), 4)
    ]


def read_palette_rows_from_file(binary_path):
    """把二进制调色板文件完整读取成 float4 行列表。"""
    return read_palette_rows_in_range(binary_path)


def read_palette_rows_in_range(binary_path, row_start=0, row_count=None):
    """只读取指定范围内的 float4 行，避免导入时把整块大缓冲都读进来。"""
    flat_float_values = array("f")
    item_byte_size = flat_float_values.itemsize
    file_size = os.path.getsize(binary_path)
    if file_size % (item_byte_size * 4) != 0:
        raise ValueError("Palette binary does not contain a whole number of float4 rows")

    total_row_count = file_size // (item_byte_size * 4)
    normalized_row_start = max(0, int(row_start))
    if normalized_row_start >= total_row_count:
        return []

    if row_count is None:
        normalized_row_count = total_row_count - normalized_row_start
    else:
        normalized_row_count = max(0, min(int(row_count), total_row_count - normalized_row_start))

    if normalized_row_count == 0:
        return []

    with open(binary_path, "rb") as binary_file:
        binary_file.seek(normalized_row_start * 4 * item_byte_size)
        flat_float_values.fromfile(binary_file, normalized_row_count * 4)
    return convert_flat_float_values_to_rows(flat_float_values)


def read_palette_metadata_from_file(metadata_path):
    """从磁盘读取可选的调色板元数据 JSON。"""
    if not metadata_path or not os.path.exists(metadata_path):
        return None
    with open(metadata_path, "r", encoding="utf-8") as metadata_file:
        return json.load(metadata_file)


def build_metadata_path_from_binary_path(binary_path):
    """根据二进制路径生成默认的元数据路径。"""
    root_path, _ = os.path.splitext(binary_path)
    return f"{root_path}.json"


def load_palette_file(binary_path, metadata_path=None, row_start=0, row_count=None):
    """读取调色板行和可选元数据，并封装成统一对象。"""
    metadata_path = metadata_path or build_metadata_path_from_binary_path(binary_path)
    return LoadedPaletteFile(
        binary_path=binary_path,
        rows=read_palette_rows_in_range(binary_path, row_start=row_start, row_count=row_count),
        metadata=read_palette_metadata_from_file(metadata_path),
        row_start=max(0, int(row_start)),
    )
