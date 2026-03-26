import json
import os
from array import array

import bpy

from .models import PaletteFileContents


def resolve_export_paths(raw_output_path, armature_name):
    path = bpy.path.abspath(raw_output_path or "//")
    root, ext = os.path.splitext(path)
    if not ext:
        if path.endswith(os.sep) or path.endswith("/") or os.path.isdir(path):
            path = os.path.join(path, f"{armature_name}_vst0_palette.bin")
        else:
            path = f"{path}.bin"
        root, _ = os.path.splitext(path)
    return path, f"{root}.json"


def write_palette_package(package, output_path, armature_name, write_metadata=True):
    binary_path, metadata_path = resolve_export_paths(output_path, armature_name)

    directory = os.path.dirname(binary_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    flat = array("f")
    for row in package["buffer_rows"]:
        flat.extend(row)
    with open(binary_path, "wb") as handle:
        flat.tofile(handle)

    if write_metadata:
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(package["metadata"], handle, indent=2, ensure_ascii=False)

    return binary_path, metadata_path


def read_palette_rows(binary_path):
    flat = array("f")
    with open(binary_path, "rb") as handle:
        flat.fromfile(handle, os.path.getsize(binary_path) // flat.itemsize)
    if len(flat) % 4 != 0:
        raise ValueError("Palette binary does not contain a whole number of float4 rows")
    return [tuple(float(flat[index + offset]) for offset in range(4)) for index in range(0, len(flat), 4)]


def read_metadata(metadata_path):
    if not metadata_path or not os.path.exists(metadata_path):
        return None
    with open(metadata_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def infer_metadata_path(binary_path):
    root, _ = os.path.splitext(binary_path)
    return f"{root}.json"


def read_palette_file(binary_path, metadata_path=None):
    metadata_path = metadata_path or infer_metadata_path(binary_path)
    return PaletteFileContents(
        binary_path=binary_path,
        rows=read_palette_rows(binary_path),
        metadata=read_metadata(metadata_path),
    )
