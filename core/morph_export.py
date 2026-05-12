"""RX morph export helpers and file writers."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import math
import os
import re
import struct

import bpy

from .animation_export import (
    build_runtime_export_name_prefix,
    normalize_animation_frame_range,
    normalize_clip_name,
    sanitize_export_name,
    write_json_file,
    write_uint4_buffer_rows,
)


MORPH_FLAG_HAS_POSITION_DELTAS = 1 << 0
MORPH_FLAG_HAS_NORMAL_TARGETS = 1 << 1
MORPH_FLAG_HAS_TANGENT_TARGETS = 1 << 2

MORPH_NORMAL_MODE_NONE = 0
MORPH_NORMAL_MODE_EFMI_VB0_OCT_R32_UINT = 1

MORPH_CHANNEL_MODE_ANIMATED = "ANIMATED"
MORPH_CHANNEL_MODE_ALL = "ALL"

MORPH_WEIGHT_EPSILON = 1e-4
MORPH_POSITION_EPSILON = 1e-6
MORPH_TANGENT_EPSILON = 1e-4

_RESOURCE_SECTION_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")


@dataclass(frozen=True)
class MorphMeshExportResult:
    """Summary for one exported morph mesh payload."""

    mesh_key: str
    morph_static_path: str
    morph_anim_path: str
    metadata_path: str
    channel_names: tuple[str, ...]
    sample_count: int
    vertex_count: int
    influence_count: int
    static_stride: int
    base_position_path: str
    base_position_stride: int
    base_position_resource_name: str
    base_position_layout: str
    include_normals: bool
    include_tangents: bool


def resolve_morph_export_paths(output_directory: str, clip_name: str, mesh_key: str):
    """Build shared morph-manifest and per-mesh morph paths."""
    directory_path = bpy.path.abspath(output_directory or "//")
    os.makedirs(directory_path, exist_ok=True)
    safe_clip_name = sanitize_export_name(normalize_clip_name(clip_name), "rxanimin")
    safe_mesh_key = sanitize_export_name(mesh_key, "morph_mesh")
    morph_manifest_path = os.path.join(directory_path, f"{safe_clip_name}_morph_manifest.json")
    morph_static_path = os.path.join(directory_path, f"{safe_mesh_key}_morph_static.buf")
    morph_anim_path = os.path.join(directory_path, f"{safe_mesh_key}_morph_anim.buf")
    morph_metadata_path = os.path.join(directory_path, f"{safe_mesh_key}_morph.json")
    return directory_path, morph_manifest_path, morph_static_path, morph_anim_path, morph_metadata_path


def build_morph_static_header_uint4_rows(
    channel_count: int,
    vertex_count: int,
    span_count: int,
    influence_count: int,
    span_row_count: int = 0,
    influence_row_count: int = 0,
    max_influences_per_vertex: int = 0,
    include_normals: bool = True,
    include_tangents: bool = False,
    influence_row_stride: int = 1,
):
    """Build the fixed uint4 header rows for one morph-static buffer."""
    flags = MORPH_FLAG_HAS_POSITION_DELTAS
    normal_mode = MORPH_NORMAL_MODE_NONE
    if include_normals:
        flags |= MORPH_FLAG_HAS_NORMAL_TARGETS
        normal_mode = MORPH_NORMAL_MODE_EFMI_VB0_OCT_R32_UINT
    if include_tangents:
        flags |= MORPH_FLAG_HAS_TANGENT_TARGETS
    return [
        (
            max(int(channel_count), 0),
            max(int(vertex_count), 0),
            max(int(span_count), 0),
            max(int(influence_count), 0),
        ),
        (
            int(flags),
            int(normal_mode),
            max(int(span_row_count), 0),
            max(int(influence_row_count), 0),
        ),
        (
            max(int(max_influences_per_vertex), 0),
            max(int(influence_row_stride), 1),
            0,
            0,
        ),
    ]


def build_morph_anim_header_uint4_rows(
    channel_count: int,
    sample_count: int,
    clip_id: int,
    source_frame_start: int,
    source_frame_step: int,
    baked_weight_row_count: int,
    weights_per_row: int = 8,
):
    """Build the fixed uint4 header rows for one morph-animation buffer."""
    safe_sample_count = max(int(sample_count), 1)
    return [
        (
            max(int(channel_count), 0),
            safe_sample_count,
            max(int(baked_weight_row_count), 0),
            max(int(weights_per_row), 1),
        ),
        (
            int(clip_id),
            int(source_frame_start),
            max(int(source_frame_step), 1),
            0,
        ),
    ]


def build_morph_manifest(clip_name: str, clip_id: int, mesh_results: tuple[MorphMeshExportResult, ...]):
    """Build the shared morph manifest for one logical clip."""
    return {
        "format": "rx_morph_manifest_v1",
        "clip_name": str(normalize_clip_name(clip_name)),
        "clip_id": int(clip_id),
        "shared_timeline_semantics": "uses_rx_anim_master_playback_v2",
        "per_mesh_playback_state": "none",
        "sample_window_source": "shared_master_playback.tick_to_sample_window",
        "weight_sampling_mode": "evaluated_per_sample",
        "normal_encoding_mode": "efmi_vb0_tbn_r10g10b10a2_uint",
        "tangent_strategy": "optional_key_1_targets_for_explicit_tangent_layouts",
        "vertex_order_requirement": "match_theherta_unique_vertex_order",
        "meshes": [
            {
                "mesh_key": result.mesh_key,
                "morph_static_path": result.morph_static_path,
                "morph_anim_path": result.morph_anim_path,
                "metadata_path": result.metadata_path,
                "channel_names": list(result.channel_names),
                "sample_count": int(result.sample_count),
                "vertex_count": int(result.vertex_count),
                "influence_count": int(result.influence_count),
                "static_stride": int(result.static_stride),
                "base_position_path": result.base_position_path,
                "base_position_stride": int(result.base_position_stride),
                "base_position_resource_name": result.base_position_resource_name,
                "base_position_layout": result.base_position_layout,
                "include_normals": bool(result.include_normals),
                "include_tangents": bool(result.include_tangents),
            }
            for result in mesh_results
        ],
    }


def write_morph_manifest(output_directory: str, clip_name: str, clip_id: int, mesh_results: tuple[MorphMeshExportResult, ...]):
    """Write the shared morph manifest if any morph mesh was exported."""
    if not mesh_results:
        return ""
    _, morph_manifest_path, _morph_static_path, _morph_anim_path, _morph_metadata_path = resolve_morph_export_paths(
        output_directory,
        clip_name,
        mesh_results[0].mesh_key,
    )
    write_json_file(morph_manifest_path, build_morph_manifest(clip_name, clip_id, mesh_results))
    return morph_manifest_path


def _sign_not_zero(value: float) -> float:
    return 1.0 if value >= 0.0 else -1.0


def _normalize_vector3(vector, fallback=(0.0, 0.0, 1.0)):
    vector_x = float(vector[0])
    vector_y = float(vector[1])
    vector_z = float(vector[2])
    vector_length = math.sqrt(vector_x * vector_x + vector_y * vector_y + vector_z * vector_z)
    if vector_length <= 1e-8:
        return (float(fallback[0]), float(fallback[1]), float(fallback[2]))
    return (vector_x / vector_length, vector_y / vector_length, vector_z / vector_length)


def _dot3(vector_a, vector_b) -> float:
    return (
        float(vector_a[0]) * float(vector_b[0])
        + float(vector_a[1]) * float(vector_b[1])
        + float(vector_a[2]) * float(vector_b[2])
    )


def _cross3(vector_a, vector_b):
    return (
        float(vector_a[1]) * float(vector_b[2]) - float(vector_a[2]) * float(vector_b[1]),
        float(vector_a[2]) * float(vector_b[0]) - float(vector_a[0]) * float(vector_b[2]),
        float(vector_a[0]) * float(vector_b[1]) - float(vector_a[1]) * float(vector_b[0]),
    )


def _encode_tangent_to_efmi_scalar(tangent_vector, normal_vector) -> float:
    normalized_normal = _normalize_vector3(normal_vector)
    normalized_tangent = _normalize_vector3(tangent_vector, fallback=(1.0, 0.0, 0.0))

    reference_vector = (
        normalized_normal[1] - normalized_normal[2],
        normalized_normal[2] - normalized_normal[0],
        normalized_normal[0] - normalized_normal[1],
    )
    reference_length = math.sqrt(_dot3(reference_vector, reference_vector))
    if reference_length < 1e-6 or not math.isfinite(reference_length):
        helper_axis = (1.0, 0.0, 0.0) if abs(normalized_normal[0]) < 0.9 else (0.0, 1.0, 0.0)
        reference_vector = _normalize_vector3(_cross3(normalized_normal, helper_axis), fallback=(1.0, 0.0, 0.0))
    else:
        reference_vector = (
            reference_vector[0] / reference_length,
            reference_vector[1] / reference_length,
            reference_vector[2] / reference_length,
        )

    bitangent_vector = _normalize_vector3(
        _cross3(reference_vector, normalized_normal),
        fallback=(0.0, 1.0, 0.0),
    )

    cos_theta = max(-1.0, min(1.0, _dot3(normalized_tangent, reference_vector)))
    sin_theta = max(-1.0, min(1.0, _dot3(normalized_tangent, bitangent_vector)))

    denominator = abs(cos_theta) + abs(sin_theta)
    unit_tangent = (cos_theta / denominator) if denominator > 1e-8 else 0.0
    encoded_tangent = 0.5 * (1.0 + unit_tangent)

    sine_sign = 1.0 if sin_theta == 0.0 else _sign_not_zero(sin_theta)
    return math.copysign(encoded_tangent, sine_sign)


def encode_normal_to_efmi_packed_uint(
    normal_vector,
    tangent_vector=None,
    bitangent_sign=1.0,
    *,
    flip_texcoord_v: bool = True,
    flip_bitangent_sign: bool = True,
) -> int:
    """Encode one EFMI packed TBN uint from normal+tangent state."""
    normal_x = float(normal_vector[0])
    normal_y = float(normal_vector[1])
    normal_z = float(normal_vector[2])
    normal_length = math.sqrt(normal_x * normal_x + normal_y * normal_y + normal_z * normal_z)
    if normal_length <= 1e-8:
        normal_x = 0.0
        normal_y = 0.0
        normal_z = 1.0
    else:
        normal_x /= normal_length
        normal_y /= normal_length
        normal_z /= normal_length

    l1_norm = abs(normal_x) + abs(normal_y) + abs(normal_z)
    if l1_norm <= 1e-8:
        encoded_x = 0.0
        encoded_y = 0.0
    else:
        encoded_x = normal_x / l1_norm
        encoded_y = normal_y / l1_norm
        encoded_z = normal_z / l1_norm
        if encoded_z < 0.0:
            folded_x = (1.0 - abs(encoded_y)) * _sign_not_zero(encoded_x)
            folded_y = (1.0 - abs(encoded_x)) * _sign_not_zero(encoded_y)
            encoded_x = folded_x
            encoded_y = folded_y

    packed_x = int(max(-511, min(511, round(encoded_x * 511.0)))) & 0x3FF
    packed_y = int(max(-511, min(511, round(encoded_y * 511.0)))) & 0x3FF

    tangent_x = 1.0
    tangent_y = 0.0
    tangent_z = 0.0
    if tangent_vector is not None:
        tangent_x = float(tangent_vector[0])
        tangent_y = float(tangent_vector[1])
        tangent_z = float(tangent_vector[2])

    if flip_texcoord_v:
        tangent_x = -tangent_x
        tangent_y = -tangent_y
        tangent_z = -tangent_z

    encoded_tangent = _encode_tangent_to_efmi_scalar(
        (tangent_x, tangent_y, tangent_z),
        (normal_x, normal_y, normal_z),
    )
    packed_z = int(max(-511, min(511, round(encoded_tangent * 511.0)))) & 0x3FF

    tangent_sign = float(bitangent_sign)
    if flip_bitangent_sign:
        tangent_sign *= -1.0

    packed_flag = 1 << 30
    sign_flag = (1 << 31) if tangent_sign >= 0.0 else 0
    return packed_x | (packed_y << 10) | (packed_z << 20) | packed_flag | sign_flag


def _pack_half2_uint(value_a: float, value_b: float) -> int:
    return struct.unpack("<I", struct.pack("<ee", float(value_a), float(value_b)))[0]


def _normal_mismatch(base_packed_normal: int, target_packed_normal: int) -> bool:
    return int(base_packed_normal) != int(target_packed_normal)


def _position_delta_is_zero(delta_position) -> bool:
    return (
        abs(float(delta_position[0])) <= MORPH_POSITION_EPSILON
        and abs(float(delta_position[1])) <= MORPH_POSITION_EPSILON
        and abs(float(delta_position[2])) <= MORPH_POSITION_EPSILON
    )


def _tangent_mismatch(base_tangent, target_tangent) -> bool:
    return any(
        abs(float(base_component) - float(target_component)) > MORPH_TANGENT_EPSILON
        for base_component, target_component in zip(base_tangent, target_tangent)
    )


@contextmanager
def _preserve_shape_key_values(source_mesh):
    """Save and restore all non-basis shape-key values."""
    shape_keys = getattr(getattr(source_mesh.data, "shape_keys", None), "key_blocks", None)
    if not shape_keys:
        yield {}
        return
    original_values = {key_block.name: float(key_block.value) for key_block in shape_keys}
    try:
        yield original_values
    finally:
        for key_block in shape_keys:
            key_block.value = original_values.get(key_block.name, float(key_block.value))


def _set_shape_key_values(source_mesh, values_by_name: dict[str, float]):
    """Assign shape-key values by name, defaulting unspecified keys back to zero."""
    shape_keys = getattr(getattr(source_mesh.data, "shape_keys", None), "key_blocks", None)
    if not shape_keys:
        return
    for key_block in shape_keys:
        if getattr(key_block, "relative_key", None) is key_block:
            continue
        key_block.value = float(values_by_name.get(key_block.name, 0.0))


@contextmanager
def _temporary_disabled_armature_modifiers(source_mesh):
    """Temporarily hide armature modifiers so morph export stays in pre-skin local space."""
    saved_states = []
    for modifier in source_mesh.modifiers:
        if modifier.type == "ARMATURE":
            saved_states.append((modifier, bool(modifier.show_viewport)))
            modifier.show_viewport = False
    if saved_states:
        bpy.context.view_layer.update()
    try:
        yield
    finally:
        for modifier, saved_state in saved_states:
            modifier.show_viewport = saved_state
        if saved_states:
            bpy.context.view_layer.update()


@contextmanager
def _evaluated_mesh_without_armature(source_mesh):
    """Yield an evaluated mesh with armature deformation disabled."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    with _temporary_disabled_armature_modifiers(source_mesh):
        evaluated_object = source_mesh.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_object.to_mesh()
        try:
            yield evaluated_mesh
        finally:
            evaluated_object.to_mesh_clear()


def _build_theherta_like_unique_loop_indices(evaluated_mesh):
    """Rebuild TheHerta-style unique-vertex order from loops."""
    if len(evaluated_mesh.uv_layers) > 0:
        try:
            evaluated_mesh.calc_tangents()
        except RuntimeError:
            pass

    unique_vertex_map = OrderedDict()
    representative_loop_indices = []
    has_tangent_data = bool(len(evaluated_mesh.uv_layers) > 0)

    for polygon in evaluated_mesh.polygons:
        for loop_index in range(polygon.loop_start, polygon.loop_start + polygon.loop_total):
            loop = evaluated_mesh.loops[loop_index]
            vertex = evaluated_mesh.vertices[loop.vertex_index]
            tangent = loop.tangent if has_tangent_data else (0.0, 0.0, 0.0)
            bitangent_sign = float(loop.bitangent_sign) if has_tangent_data else 1.0
            key_bytes = b"".join(
                (
                    struct.pack("<I", int(loop.vertex_index)),
                    struct.pack("<3f", float(vertex.co.x), float(vertex.co.y), float(vertex.co.z)),
                    struct.pack("<3f", float(loop.normal.x), float(loop.normal.y), float(loop.normal.z)),
                    struct.pack("<3f", float(tangent[0]), float(tangent[1]), float(tangent[2])),
                    struct.pack("<f", bitangent_sign),
                )
            )
            if key_bytes not in unique_vertex_map:
                unique_vertex_map[key_bytes] = len(unique_vertex_map)
                representative_loop_indices.append(loop_index)

    return tuple(representative_loop_indices)


def _capture_unique_vertex_targets(evaluated_mesh, representative_loop_indices):
    """Capture one position + packed normal + tangent target for each exported unique vertex."""
    has_tangent_data = False
    if len(evaluated_mesh.uv_layers) > 0:
        try:
            evaluated_mesh.calc_tangents()
            has_tangent_data = True
        except RuntimeError:
            has_tangent_data = False

    unique_positions = []
    unique_normals = []
    unique_tangents = []
    for loop_index in representative_loop_indices:
        loop = evaluated_mesh.loops[loop_index]
        vertex = evaluated_mesh.vertices[loop.vertex_index]
        unique_positions.append((float(vertex.co.x), float(vertex.co.y), float(vertex.co.z)))
        tangent = loop.tangent if has_tangent_data else (0.0, 0.0, 0.0)
        bitangent_sign = float(loop.bitangent_sign) if has_tangent_data else 1.0
        unique_normals.append(
            encode_normal_to_efmi_packed_uint(
                loop.normal,
                tangent,
                bitangent_sign,
            )
        )
        unique_tangents.append(
            (
                float(tangent[0]),
                float(tangent[1]),
                float(tangent[2]),
                float(bitangent_sign),
            )
        )
    return tuple(unique_positions), tuple(unique_normals), tuple(unique_tangents)


def _parse_position_resource_from_ini(ini_path: str, mesh_key: str):
    """Try to locate one TheHerta-exported position resource and stride from an ini file."""
    current_section = ""
    matched_section = ""
    matched_stride = 0
    matched_filename = ""
    with open(ini_path, "r", encoding="utf-8", errors="ignore") as ini_file:
        for raw_line in ini_file:
            stripped_line = raw_line.strip()
            if not stripped_line or stripped_line.startswith(";"):
                continue
            section_match = _RESOURCE_SECTION_RE.match(stripped_line)
            if section_match:
                current_section = section_match.group("name")
                lower_section = current_section.lower()
                mesh_key_lower = mesh_key.lower()
                if (
                    "position" in lower_section
                    and mesh_key_lower in lower_section
                    and "uav" not in lower_section
                ):
                    matched_section = current_section
                    matched_stride = 0
                    matched_filename = ""
                else:
                    matched_section = ""
                continue
            if not matched_section or "=" not in stripped_line:
                continue
            key, value = (part.strip() for part in stripped_line.split("=", 1))
            if key.lower() == "stride":
                try:
                    matched_stride = int(value)
                except ValueError:
                    matched_stride = 0
            elif key.lower() == "filename":
                matched_filename = value.replace("/", os.sep).replace("\\", os.sep)
            if matched_section and matched_stride > 0 and matched_filename:
                resolved_path = os.path.abspath(os.path.join(os.path.dirname(ini_path), matched_filename))
                return matched_section, resolved_path, matched_stride
    return "", "", 0


def resolve_base_position_resource(output_directory: str, mesh_key: str):
    """Resolve the existing TheHerta-exported base position buffer for one mesh key."""
    absolute_output_directory = bpy.path.abspath(output_directory or "//")
    preferred_ini_names = ("RXanimin.ini", "rxanimin.ini")
    ini_candidates = []
    for preferred_name in preferred_ini_names:
        preferred_path = os.path.join(absolute_output_directory, preferred_name)
        if os.path.exists(preferred_path):
            ini_candidates.append(preferred_path)
    for file_name in os.listdir(absolute_output_directory):
        if file_name.lower().endswith(".ini"):
            ini_path = os.path.join(absolute_output_directory, file_name)
            if ini_path not in ini_candidates:
                ini_candidates.append(ini_path)

    for ini_path in ini_candidates:
        section_name, buffer_path, stride = _parse_position_resource_from_ini(ini_path, mesh_key)
        if section_name and buffer_path and stride > 0 and os.path.exists(buffer_path):
            return {
                "resource_name": section_name,
                "buffer_path": buffer_path,
                "stride": stride,
            }

    buffer_directory = os.path.join(absolute_output_directory, "Buffer")
    if os.path.isdir(buffer_directory):
        mesh_key_lower = mesh_key.lower()
        for file_name in sorted(os.listdir(buffer_directory)):
            lower_name = file_name.lower()
            if lower_name.startswith(mesh_key_lower) and lower_name.endswith("-position.buf"):
                return {
                    "resource_name": "",
                    "buffer_path": os.path.join(buffer_directory, file_name),
                    "stride": 0,
                }
    raise ValueError(
        f"Could not resolve a TheHerta base Position buffer for mesh key {mesh_key} under {absolute_output_directory}"
    )


def _read_base_position_rows(buffer_path: str, stride: int):
    """Read one TheHerta-exported base position buffer."""
    with open(buffer_path, "rb") as buffer_file:
        raw_bytes = buffer_file.read()
    if stride <= 0 or (len(raw_bytes) % stride) != 0:
        raise ValueError(f"Base position buffer {buffer_path} has invalid length for stride {stride}")

    base_rows = []
    for byte_offset in range(0, len(raw_bytes), stride):
        if stride == 16:
            position_x, position_y, position_z, packed_normal = struct.unpack_from("<3fI", raw_bytes, byte_offset)
            base_rows.append(
                {
                    "position": (float(position_x), float(position_y), float(position_z)),
                    "packed_normal": int(packed_normal),
                    "normal": None,
                    "tangent": None,
                }
            )
            continue

        if stride >= 40:
            (
                position_x,
                position_y,
                position_z,
                normal_x,
                normal_y,
                normal_z,
                tangent_x,
                tangent_y,
                tangent_z,
                tangent_w,
            ) = struct.unpack_from("<10f", raw_bytes, byte_offset)
            base_normal = (float(normal_x), float(normal_y), float(normal_z))
            base_rows.append(
                {
                    "position": (float(position_x), float(position_y), float(position_z)),
                    "packed_normal": encode_normal_to_efmi_packed_uint(
                        base_normal,
                        (float(tangent_x), float(tangent_y), float(tangent_z)),
                        float(tangent_w),
                    ),
                    "normal": base_normal,
                    "tangent": (
                        float(tangent_x),
                        float(tangent_y),
                        float(tangent_z),
                        float(tangent_w),
                    ),
                }
            )
            continue

        raise ValueError(f"Unsupported base Position stride {stride} for {buffer_path}")
    return tuple(base_rows)


def _build_influence_rows(base_rows, channel_names, channel_targets_by_name, include_normals: bool, include_tangents: bool):
    """Build span rows and influence rows from captured per-channel targets."""
    vertex_influence_lists = [[] for _ in range(len(base_rows))]

    for channel_index, channel_name in enumerate(channel_names):
        target_payload = channel_targets_by_name[channel_name]
        target_positions = target_payload["positions"]
        target_normals = target_payload["packed_normals"]
        target_tangents = target_payload["tangents"]
        for vertex_index, base_row in enumerate(base_rows):
            target_position = target_positions[vertex_index]
            delta_position = (
                target_position[0] - base_row["position"][0],
                target_position[1] - base_row["position"][1],
                target_position[2] - base_row["position"][2],
            )
            target_packed_normal = target_normals[vertex_index]
            target_tangent = target_tangents[vertex_index]
            tangent_changed = bool(
                include_tangents
                and base_row["tangent"] is not None
                and _tangent_mismatch(base_row["tangent"], target_tangent)
            )
            if _position_delta_is_zero(delta_position) and (
                not include_normals or not _normal_mismatch(base_row["packed_normal"], target_packed_normal)
            ) and not tangent_changed:
                continue
            vertex_influence_lists[vertex_index].append(
                (
                    int(channel_index),
                    delta_position,
                    int(target_packed_normal),
                    target_tangent,
                )
            )

    span_rows = []
    influence_rows = []
    influence_row_stride = 2 if include_tangents else 1
    max_influences_per_vertex = 0
    running_first_influence = 0
    for influences in vertex_influence_lists:
        influence_count = len(influences)
        max_influences_per_vertex = max(max_influences_per_vertex, influence_count)
        span_rows.append((running_first_influence, influence_count, 0, 0))
        for channel_index, delta_position, target_packed_normal, target_tangent in influences:
            influence_rows.append(
                (
                    int(channel_index) & 0xFFFF,
                    _pack_half2_uint(delta_position[0], delta_position[1]),
                    _pack_half2_uint(delta_position[2], 0.0),
                    int(target_packed_normal) if include_normals else 0,
                )
            )
            if include_tangents:
                influence_rows.append(
                    (
                        _pack_half2_uint(target_tangent[0], target_tangent[1]),
                        _pack_half2_uint(target_tangent[2], target_tangent[3]),
                        0,
                        0,
                    )
                )
        running_first_influence += influence_count

    header_rows = build_morph_static_header_uint4_rows(
        channel_count=len(channel_names),
        vertex_count=len(base_rows),
        span_count=len(span_rows),
        influence_count=running_first_influence,
        span_row_count=len(span_rows),
        influence_row_count=len(influence_rows),
        max_influences_per_vertex=max_influences_per_vertex,
        include_normals=include_normals,
        include_tangents=include_tangents,
        influence_row_stride=influence_row_stride,
    )
    return header_rows + span_rows + influence_rows, running_first_influence, max_influences_per_vertex, influence_row_stride


def _build_morph_anim_rows(weight_rows_by_sample, channel_count, clip_id, source_frame_start, source_frame_step):
    """Pack sampled morph weights into uint4 rows."""
    weights_per_row = 8
    rows_per_sample = max((max(channel_count, 1) + weights_per_row - 1) // weights_per_row, 1)
    packed_payload_rows = []
    for sample_weights in weight_rows_by_sample:
        normalized_weights = list(sample_weights)
        if channel_count == 0:
            normalized_weights = []
        for channel_offset in range(0, max(channel_count, 1), weights_per_row):
            packed_weights = normalized_weights[channel_offset:channel_offset + weights_per_row]
            while len(packed_weights) < weights_per_row:
                packed_weights.append(0.0)
            packed_payload_rows.append(
                (
                    _pack_half2_uint(packed_weights[0], packed_weights[1]),
                    _pack_half2_uint(packed_weights[2], packed_weights[3]),
                    _pack_half2_uint(packed_weights[4], packed_weights[5]),
                    _pack_half2_uint(packed_weights[6], packed_weights[7]),
                )
            )
    header_rows = build_morph_anim_header_uint4_rows(
        channel_count=channel_count,
        sample_count=len(weight_rows_by_sample),
        clip_id=clip_id,
        source_frame_start=source_frame_start,
        source_frame_step=source_frame_step,
        baked_weight_row_count=len(packed_payload_rows),
        weights_per_row=weights_per_row,
    )
    return header_rows + packed_payload_rows, rows_per_sample


def _list_exportable_shape_keys(source_mesh):
    """List non-basis shape keys that are safe to export."""
    shape_keys = getattr(getattr(source_mesh.data, "shape_keys", None), "key_blocks", None)
    if not shape_keys:
        return ()
    exportable_names = []
    for key_block in shape_keys:
        if getattr(key_block, "relative_key", None) is key_block:
            continue
        exportable_names.append(key_block.name)
    return tuple(exportable_names)


def _sample_shape_key_weights(scene, source_mesh, channel_names, exported_frames):
    """Sample evaluated shape-key weights at the exported sample points."""
    if not channel_names:
        return tuple(() for _ in exported_frames)
    key_blocks = source_mesh.data.shape_keys.key_blocks
    sampled_weights = []
    for frame_number in exported_frames:
        scene.frame_set(frame_number)
        sampled_weights.append(tuple(float(key_blocks[channel_name].value) for channel_name in channel_names))
    return tuple(sampled_weights)


def _resolve_exported_channel_names(
    scene,
    source_mesh,
    exported_frames,
    channel_mode,
):
    """Resolve which shape-key channels should be exported."""
    exportable_names = _list_exportable_shape_keys(source_mesh)
    if not exportable_names:
        return (), tuple()

    sampled_weights = _sample_shape_key_weights(scene, source_mesh, exportable_names, exported_frames)
    if channel_mode == MORPH_CHANNEL_MODE_ALL:
        return exportable_names, sampled_weights

    exported_names = []
    exported_indices = []
    for channel_index, channel_name in enumerate(exportable_names):
        channel_min = min(sample_weights[channel_index] for sample_weights in sampled_weights)
        channel_max = max(sample_weights[channel_index] for sample_weights in sampled_weights)
        if (channel_max - channel_min) > MORPH_WEIGHT_EPSILON:
            exported_names.append(channel_name)
            exported_indices.append(channel_index)

    filtered_weights = []
    for sample_weights in sampled_weights:
        filtered_weights.append(tuple(sample_weights[channel_index] for channel_index in exported_indices))
    return tuple(exported_names), tuple(filtered_weights)


def export_morph_mesh_for_proxy_armature(
    context,
    proxy_armature,
    source_mesh,
    output_directory,
    clip_name,
    clip_id,
    frame_start,
    frame_end,
    frame_step,
    include_normals=True,
    include_tangents=False,
    channel_mode=MORPH_CHANNEL_MODE_ANIMATED,
    write_metadata=True,
):
    """Export one morph mesh payload for the proxy armature's source mesh."""
    if source_mesh is None or source_mesh.type != "MESH":
        return None

    exportable_shape_keys = _list_exportable_shape_keys(source_mesh)
    if not exportable_shape_keys:
        return None

    scene = context.scene
    exported_frames = normalize_animation_frame_range(frame_start, frame_end, frame_step)
    if not exported_frames:
        return None

    mesh_key = build_runtime_export_name_prefix(proxy_armature)
    original_frame = scene.frame_current

    with _preserve_shape_key_values(source_mesh):
        try:
            exported_channel_names, sampled_weights = _resolve_exported_channel_names(
                scene,
                source_mesh,
                exported_frames,
                channel_mode,
            )
            if not exported_channel_names:
                return None

            scene.frame_set(exported_frames[0])
            with _evaluated_mesh_without_armature(source_mesh) as reference_mesh:
                representative_loop_indices = _build_theherta_like_unique_loop_indices(reference_mesh)

            base_position_resource = resolve_base_position_resource(output_directory, mesh_key)
            resolved_base_stride = int(base_position_resource["stride"])
            if resolved_base_stride <= 0:
                base_buffer_size = os.path.getsize(base_position_resource["buffer_path"])
                unique_vertex_count = len(representative_loop_indices)
                if unique_vertex_count <= 0 or (base_buffer_size % unique_vertex_count) != 0:
                    raise ValueError(
                        f"Could not infer base Position stride for {mesh_key} from "
                        f"{base_position_resource['buffer_path']}"
                    )
                resolved_base_stride = base_buffer_size // unique_vertex_count
                if resolved_base_stride not in (16, 40):
                    raise ValueError(
                        f"Unsupported inferred base Position stride {resolved_base_stride} for {mesh_key}"
                    )
                base_position_resource["stride"] = resolved_base_stride
            base_rows = _read_base_position_rows(
                base_position_resource["buffer_path"],
                resolved_base_stride,
            )
            resolved_include_tangents = bool(
                include_normals
                and
                include_tangents
                and base_position_resource["stride"] >= 40
                and any(base_row["tangent"] is not None for base_row in base_rows)
            )
            if len(base_rows) != len(representative_loop_indices):
                raise ValueError(
                    "Morph vertex count does not match the TheHerta base Position buffer "
                    f"({len(representative_loop_indices)} != {len(base_rows)}) for {mesh_key}"
                )

            channel_targets_by_name = {}
            all_zero_values = {channel_name: 0.0 for channel_name in exportable_shape_keys}
            for channel_name in exported_channel_names:
                channel_values = dict(all_zero_values)
                channel_values[channel_name] = 1.0
                _set_shape_key_values(source_mesh, channel_values)
                bpy.context.view_layer.update()
                with _evaluated_mesh_without_armature(source_mesh) as target_mesh:
                    positions_at_one, packed_normals_at_one, tangents_at_one = _capture_unique_vertex_targets(
                        target_mesh,
                        representative_loop_indices,
                    )
                channel_targets_by_name[channel_name] = {
                    "positions": positions_at_one,
                    "packed_normals": packed_normals_at_one,
                    "tangents": tangents_at_one,
                }

            static_rows, influence_count, _max_influences, influence_row_stride = _build_influence_rows(
                base_rows=base_rows,
                channel_names=exported_channel_names,
                channel_targets_by_name=channel_targets_by_name,
                include_normals=include_normals,
                include_tangents=resolved_include_tangents,
            )
            anim_rows, rows_per_sample = _build_morph_anim_rows(
                sampled_weights,
                channel_count=len(exported_channel_names),
                clip_id=clip_id,
                source_frame_start=frame_start,
                source_frame_step=frame_step,
            )

            _directory_path, _manifest_path, morph_static_path, morph_anim_path, morph_metadata_path = resolve_morph_export_paths(
                output_directory,
                clip_name,
                mesh_key,
            )
            write_uint4_buffer_rows(morph_static_path, static_rows)
            write_uint4_buffer_rows(morph_anim_path, anim_rows)

            metadata_payload = {
                "format": "rx_morph_mesh_v1",
                "clip_name": normalize_clip_name(clip_name),
                "clip_id": int(clip_id),
                "mesh_key": mesh_key,
                "armature_name": proxy_armature.name,
                "source_mesh_name": source_mesh.name,
                "source_frame_start": int(frame_start),
                "source_frame_end": int(frame_end),
                "source_frame_step": int(frame_step),
                "sample_count": len(exported_frames),
                "channel_mode": str(channel_mode),
                "channel_names": list(exported_channel_names),
                "vertex_count": len(base_rows),
                "influence_count": int(influence_count),
                "rows_per_sample": int(rows_per_sample),
                "static_stride": 16,
                "morph_static_path": morph_static_path,
                "morph_anim_path": morph_anim_path,
                "base_position_path": base_position_resource["buffer_path"],
                "base_position_stride": int(resolved_base_stride),
                "base_position_layout": "EFMI_PNTA40" if int(resolved_base_stride) >= 40 else "EFMI_PACKED16",
                "include_normals": bool(include_normals),
                "include_tangents": bool(resolved_include_tangents),
                "normal_encoding_mode": "efmi_vb0_tbn_r10g10b10a2_uint" if include_normals else "none",
                "influence_row_stride": int(influence_row_stride),
                "sample_semantics": "shared_tick_to_sample_window",
                "vertex_order_requirement": "match_theherta_unique_vertex_order",
            }
            if write_metadata:
                write_json_file(morph_metadata_path, metadata_payload)
            else:
                morph_metadata_path = ""

            return MorphMeshExportResult(
                mesh_key=mesh_key,
                morph_static_path=morph_static_path,
                morph_anim_path=morph_anim_path,
                metadata_path=morph_metadata_path,
                channel_names=tuple(exported_channel_names),
                sample_count=len(exported_frames),
                vertex_count=len(base_rows),
                influence_count=int(influence_count),
                static_stride=16,
                base_position_path=base_position_resource["buffer_path"],
                base_position_stride=int(resolved_base_stride),
                base_position_resource_name=str(base_position_resource.get("resource_name", "")),
                base_position_layout="EFMI_PNTA40" if int(resolved_base_stride) >= 40 else "EFMI_PACKED16",
                include_normals=bool(include_normals),
                include_tangents=bool(resolved_include_tangents),
            )
        finally:
            scene.frame_set(original_frame)
