import unittest
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_rx_geometry_module(module_name):
    root = Path(__file__).resolve().parents[1]
    core_pkg = sys.modules.get("core")
    if core_pkg is None:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["core"] = core_pkg
    rx_pkg = sys.modules.get("core.rx_geometry_export")
    if rx_pkg is None:
        rx_pkg = types.ModuleType("core.rx_geometry_export")
        rx_pkg.__path__ = [str(root / "core" / "rx_geometry_export")]
        sys.modules["core.rx_geometry_export"] = rx_pkg

    fq_name = f"core.rx_geometry_export.{module_name}"
    if fq_name in sys.modules:
        return sys.modules[fq_name]
    source_path = root / "core" / "rx_geometry_export" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(fq_name, source_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[fq_name] = module
    spec.loader.exec_module(module)
    return module


export_buffers = _load_rx_geometry_module("export_buffers")
uv_transform = _load_rx_geometry_module("uv_transform")


def _mesh_cache(
    *,
    mirror_flip=False,
    uv_mirror_u=False,
    uv_flip_v=True,
    positions=None,
    normals=None,
    tangents=None,
    bitangent_signs=None,
    uv_values=None,
):
    return export_buffers._MeshExportCache(
        mesh_obj=SimpleNamespace(name="Mesh"),
        mesh=SimpleNamespace(),
        group_index_to_global={},
        mirror_flip=mirror_flip,
        uv_mirror_u=uv_mirror_u,
        uv_flip_v=uv_flip_v,
        matrix_world_applied=True,
        vertex_position_values=list(positions or []),
        loop_normal_values=list(normals or []),
        loop_tangent_values=list(tangents or []),
        loop_bitangent_sign_values=list(bitangent_signs or []),
        game_position_values=None,
        game_normal_values=None,
        game_tangent_values=None,
        game_bitangent_sign_values=None,
        game_packed_tangent_frame_values=None,
        game_position_by_vertex={},
        game_normal_by_loop={},
        top4_by_vertex={},
        top4_packed_by_vertex={},
        blend_weights_by_vertex=None,
        blend_indices_by_vertex=None,
        uv_layers={"UV0": object()},
        uv_values_by_layer={"UV0": list(uv_values or [])},
        game_uv_values_by_layer={},
        uv_by_layer_loop={},
        attribute_refs={},
        color_attribute_refs={},
        texcoord_snorm4_sources={},
    )


class RxGeometryTransformRulesTests(unittest.TestCase):
    def assertRowsAlmostEqual(self, actual, expected, places=6):
        self.assertEqual(len(actual), len(expected))
        for actual_row, expected_row in zip(actual, expected):
            self.assertEqual(len(actual_row), len(expected_row))
            for actual_value, expected_value in zip(actual_row, expected_row):
                self.assertAlmostEqual(float(actual_value), float(expected_value), places=places)

    def test_uv_v_transform_is_symmetric_between_import_and_export(self):
        game_uv = (0.125, 0.75)
        blender_uv = uv_transform.game_uv_to_blender(game_uv)

        self.assertEqual(blender_uv, (0.125, 0.25))
        self.assertEqual(uv_transform.blender_uv_to_game(blender_uv), game_uv)

    def test_export_uv_v_is_flipped_by_default(self):
        cache = _mesh_cache(uv_values=[(0.25, 0.75), (0.5, 0.5), (0.75, 0.25)])

        values = export_buffers._game_uv_values(cache.mesh, "UV0", cache)

        self.assertEqual(
            values.tolist(),
            [[0.25, 0.25], [0.5, 0.5], [0.75, 0.75]],
        )

    def test_export_uv_u_mirror_is_explicit(self):
        cache = _mesh_cache(
            uv_mirror_u=True,
            uv_values=[(0.25, 0.75), (0.5, 0.5), (0.75, 0.25)],
        )

        values = export_buffers._game_uv_values(cache.mesh, "UV0", cache)

        self.assertEqual(
            values.tolist(),
            [[0.75, 0.25], [0.5, 0.5], [0.25, 0.75]],
        )

    def test_export_uv_v_flip_can_be_disabled(self):
        cache = _mesh_cache(
            uv_flip_v=False,
            uv_values=[(0.25, 0.75), (0.5, 0.5), (0.75, 0.25)],
        )

        values = export_buffers._game_uv_values(cache.mesh, "UV0", cache)

        self.assertEqual(
            values.tolist(),
            [[0.25, 0.75], [0.5, 0.5], [0.75, 0.25]],
        )

    def test_export_mirror_flips_position_normal_and_tangent_x(self):
        cache = _mesh_cache(
            mirror_flip=True,
            positions=[(1.0, 2.0, 3.0)],
            normals=[(0.25, -0.5, 0.75)],
            tangents=[(0.8, 0.1, 0.2)],
        )

        self.assertEqual(export_buffers._game_position_values(cache.mesh, cache).tolist(), [[-1.0, 2.0, 3.0]])
        self.assertRowsAlmostEqual(
            export_buffers._game_normal_values(cache.mesh, cache).tolist(),
            [[-0.267261, -0.534522, 0.801784]],
        )
        self.assertRowsAlmostEqual(
            export_buffers._game_tangent_values(cache.mesh, cache).tolist(),
            [[-0.963087, 0.120386, 0.240772]],
        )

    def test_bitangent_sign_flips_when_exactly_one_of_mirror_or_uv_flip_is_enabled(self):
        cases = [
            (False, False, [1.0, -1.0]),
            (True, True, [1.0, -1.0]),
            (True, False, [-1.0, 1.0]),
            (False, True, [-1.0, 1.0]),
        ]
        for mirror_flip, uv_flip_v, expected in cases:
            with self.subTest(mirror_flip=mirror_flip, uv_flip_v=uv_flip_v):
                cache = _mesh_cache(
                    mirror_flip=mirror_flip,
                    uv_flip_v=uv_flip_v,
                    bitangent_signs=[1.0, -1.0],
                )

                values = export_buffers._game_bitangent_sign_values(cache.mesh, cache)

                self.assertEqual(values.tolist(), expected)

    def test_object_uv_flip_prefers_import_metadata_over_global_default(self):
        imported_with_no_vflip = {"bmc_uv_flip_v": False}
        imported_with_vflip = {"modimp_flip_v": True}

        self.assertFalse(export_buffers._object_uv_flip(imported_with_no_vflip, True))
        self.assertTrue(export_buffers._object_uv_flip(imported_with_vflip, False))
        self.assertTrue(export_buffers._object_uv_flip({}, True))

    def test_object_uv_mirror_u_is_explicit_metadata(self):
        self.assertFalse(export_buffers._object_uv_mirror_u({}, False))
        self.assertTrue(export_buffers._object_uv_mirror_u({"bmc_uv_mirror_u": True}, False))
        self.assertFalse(export_buffers._object_uv_mirror_u({"modimp_mirror_uv_u": False}, True))

    def test_vb3_same_backing_as_vb0_is_redundant_alias(self):
        layout = export_buffers._normalize_vertex_layout(
            {
                "buffers": {
                    "vb0": {
                        "slot": "vb0",
                        "stride": 40,
                        "backing_hash": "1d6a6186",
                        "elements": [
                            {"semantic": "POSITION0", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 0},
                            {"semantic": "NORMAL0", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 12},
                        ],
                    },
                    "vb3": {
                        "slot": "vb3",
                        "stride": 40,
                        "backing_hash": "1d6a6186",
                        "elements": [
                            {"semantic": "TEXCOORD4", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 0},
                        ],
                    },
                }
            }
        )

        self.assertTrue(export_buffers._is_redundant_vb3_alias(layout["vb3"], layout))

    def test_vb3_different_backing_stays_independent(self):
        layout = export_buffers._normalize_vertex_layout(
            {
                "buffers": {
                    "vb0": {
                        "slot": "vb0",
                        "stride": 40,
                        "backing_hash": "position-buffer",
                        "elements": [
                            {"semantic": "POSITION0", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 0},
                        ],
                    },
                    "vb3": {
                        "slot": "vb3",
                        "stride": 40,
                        "backing_hash": "independent-extra-buffer",
                        "elements": [
                            {"semantic": "TEXCOORD4", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 0},
                        ],
                    },
                }
            }
        )

        self.assertFalse(export_buffers._is_redundant_vb3_alias(layout["vb3"], layout))

    def test_pnta40_vb0_gets_implicit_tangent_field(self):
        layout = export_buffers._normalize_vertex_layout(
            {
                "buffers": {
                    "vb0": {
                        "slot": "vb0",
                        "stride": 40,
                        "elements": [
                            {"semantic": "POSITION0", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 0},
                            {"semantic": "NORMAL0", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 12},
                        ],
                    }
                }
            }
        )

        self.assertEqual(
            [(field["semantic"], field["format"], field["aligned_byte_offset"]) for field in layout["vb0"]["fields"]],
            [
                ("POSITION0", "R32G32B32_FLOAT", 0),
                ("NORMAL0", "R32G32B32_FLOAT", 12),
                ("TANGENT0", "R32G32B32A32_FLOAT", 24),
            ],
        )

    def test_pnta40_position_writer_accepts_tangent_field(self):
        slot = export_buffers._prepare_vertex_slot(
            "vb0",
            {
                "stride": 40,
                "fields": [
                    {"semantic_name": "POSITION", "semantic_index": 0, "semantic": "POSITION0", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 0},
                    {"semantic_name": "NORMAL", "semantic_index": 0, "semantic": "NORMAL0", "format": "R32G32B32_FLOAT", "aligned_byte_offset": 12},
                    {"semantic_name": "TANGENT", "semantic_index": 0, "semantic": "TANGENT0", "format": "R32G32B32A32_FLOAT", "aligned_byte_offset": 24},
                ],
            },
            "Position",
            "Position.buf",
            "Position.buf",
            1,
        )

        self.assertEqual(
            export_buffers._fast_field_plans(slot),
            [("position3", 0), ("normal3", 12), ("tangent4", 24)],
        )


if __name__ == "__main__":
    unittest.main()
