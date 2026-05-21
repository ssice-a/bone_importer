import ast
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_rx_test.py"


def _replacement_geometry_literal():
    module_ast = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    for node in module_ast.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "REPLACEMENT_GEOMETRY" for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError("REPLACEMENT_GEOMETRY not found")


class RxExportScriptContractTests(unittest.TestCase):
    def test_replacement_geometry_writes_explicit_coordinate_contract(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("source.bi_export_mirror_x", source)
        self.assertIn("source.bi_export_uv_mirror_u", source)
        self.assertIn("source.bi_export_uv_flip_v", source)
        self.assertIn("target.bi_export_mirror_x", source)
        self.assertIn("target.bi_export_uv_mirror_u", source)
        self.assertIn("target.bi_export_uv_flip_v", source)

    def test_replacements_disable_v_flip_for_current_rx_scene(self):
        replacement_geometry = _replacement_geometry_literal()
        face = replacement_geometry["e78c7068-10590-0"]
        eyelash = replacement_geometry["2009f0d6-1356-0"]

        self.assertTrue(face["mirror_flip"])
        self.assertTrue(face["uv_mirror_u"])
        self.assertFalse(face["uv_flip_v"])
        self.assertTrue(eyelash["mirror_flip"])
        self.assertFalse(eyelash["uv_mirror_u"])
        self.assertFalse(eyelash["uv_flip_v"])

    def test_replacement_morph_sources_are_explicit(self):
        replacement_geometry = _replacement_geometry_literal()

        self.assertEqual(replacement_geometry["e78c7068-10590-0"]["morph_source_object"], "000_面")
        self.assertEqual(replacement_geometry["2009f0d6-1356-0"]["morph_source_object"], "005_睫眉")

    def test_geometry_draw_part_overwrites_stale_morph_source(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('morph_source_name = str(config.get("morph_source_object", "") or "").strip()', source)
        self.assertIn("target.bi_morph_source_object = morph_source_object", source)
        self.assertNotIn('if getattr(target, "bi_morph_source_object", None) is None:', source)


if __name__ == "__main__":
    unittest.main()
