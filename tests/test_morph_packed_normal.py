import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_morph_export_module():
    root = Path(__file__).resolve().parents[1]
    core_pkg = sys.modules.get("core")
    if core_pkg is None:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["core"] = core_pkg

    sys.modules.setdefault(
        "bpy",
        types.SimpleNamespace(path=types.SimpleNamespace(abspath=lambda value: str(value)), context=None),
    )

    animation_stub = types.ModuleType("core.animation_export")
    animation_stub.build_runtime_export_name_prefix = lambda _proxy: "rxanimin"
    animation_stub.normalize_animation_frame_range = lambda start, end, step: tuple(range(int(start), int(end) + 1, int(step)))
    animation_stub.normalize_clip_name = lambda value: str(value or "rxanimin")
    animation_stub.sanitize_export_name = lambda value, fallback: str(value or fallback)
    animation_stub.write_json_file = lambda _path, _payload: None
    animation_stub.write_uint4_buffer_rows = lambda _path, _rows: None
    sys.modules["core.animation_export"] = animation_stub

    coordinate_name = "core.coordinate_contract"
    coordinate_module = sys.modules.get(coordinate_name)
    if coordinate_module is None or not hasattr(coordinate_module, "hlsl_coordinate_contract"):
        coordinate_spec = importlib.util.spec_from_file_location(coordinate_name, root / "core" / "coordinate_contract.py")
        coordinate_module = importlib.util.module_from_spec(coordinate_spec)
        sys.modules[coordinate_name] = coordinate_module
        coordinate_spec.loader.exec_module(coordinate_module)

    fq_name = "core.morph_export"
    sys.modules.pop(fq_name, None)
    source_path = root / "core" / "morph_export.py"
    spec = importlib.util.spec_from_file_location(fq_name, source_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[fq_name] = module
    spec.loader.exec_module(module)
    return module


morph_export = _load_morph_export_module()


class MorphPackedNormalTests(unittest.TestCase):
    def test_morph_packed_tangent_roll_matches_geometry_export_semantics(self):
        packed = morph_export.encode_normal_to_efmi_packed_uint(
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            1.0,
            flip_texcoord_v=False,
            flip_bitangent_sign=False,
        )

        self.assertAlmostEqual(
            morph_export.decode_efmi_packed_tangent_scalar(packed),
            -256.0 / 511.0,
            places=6,
        )

    def test_morph_packed_tangent_roll_reaches_positive_basis_endpoint(self):
        packed = morph_export.encode_normal_to_efmi_packed_uint(
            (0.0, 0.0, 1.0),
            (-1.0, -1.0, 0.0),
            1.0,
            flip_texcoord_v=False,
            flip_bitangent_sign=False,
        )

        self.assertAlmostEqual(morph_export.decode_efmi_packed_tangent_scalar(packed), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
