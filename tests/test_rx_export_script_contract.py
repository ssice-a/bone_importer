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

        self.assertIn("def _set_export_contract", source)
        self.assertIn('"bi_export_mirror_x"', source)
        self.assertIn('"bi_export_uv_mirror_u"', source)
        self.assertIn('"bi_export_uv_flip_v"', source)
        self.assertIn("_set_export_contract(geometry_source, config)", source)
        self.assertIn("target.bi_export_mirror_x", source)
        self.assertIn("target.bi_export_uv_mirror_u", source)
        self.assertIn("target.bi_export_uv_flip_v", source)

    def test_capture_manifest_path_is_ui_configurable(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("bi_capture_manifest_path", source)
        self.assertIn("RX_CAPTURE_MANIFEST", source)
        self.assertIn("ui_path", source)

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

    def test_replacement_geometry_uses_visible_source_meshes_with_slot_adapters(self):
        replacement_geometry = _replacement_geometry_literal()

        self.assertEqual(replacement_geometry["e78c7068-10590-0"]["geometry_object"], "000_面")
        self.assertEqual(replacement_geometry["2009f0d6-1356-0"]["geometry_object"], "005_睫眉")
        self.assertEqual(
            replacement_geometry["e78c7068-10590-0"]["slot_adapter_object"],
            "RXEXP_e78c7068-10590-0_000_面.001",
        )
        self.assertEqual(
            replacement_geometry["2009f0d6-1356-0"]["slot_adapter_object"],
            "RXEXP_2009f0d6-1356-0_005_睫眉.001",
        )

    def test_geometry_draw_part_defaults_morph_source_to_visible_source_mesh(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('morph_source_name = str(config.get("morph_source_object", "") or "").strip()', source)
        self.assertIn("else geometry_source", source)
        self.assertIn("target.bi_morph_source_object = morph_source_object", source)
        self.assertNotIn('if getattr(target, "bi_morph_source_object", None) is None:', source)

    def test_geometry_manifest_is_rewritten_to_visible_source_identity(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("def _rewrite_geometry_manifest_to_visible_sources", source)
        self.assertIn("_rewrite_geometry_manifest_to_visible_sources(bmc_manifest, exported_targets)", source)
        self.assertIn('bmc_manifest["export_source_collection"] = USER_EXPORT_COLLECTION_NAME', source)
        self.assertIn('bmc_manifest["export_collection"] = USER_EXPORT_COLLECTION_NAME', source)
        self.assertIn("record[\"object_names\"] = [exported[\"geometry_source\"].name]", source)

    def test_validation_scene_uses_ib_children_under_user_export_root(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('USER_EXPORT_COLLECTION_NAME = "RX Export Collection"', source)
        self.assertIn("def _sync_user_export_collection", source)
        self.assertIn("draw_collection = bpy.data.collections.new(target_name)", source)
        self.assertIn("_link_object_once(draw_collection, export_object)", source)

    def test_runtime_draw_part_collection_is_hidden_and_ib_structured(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("def _sync_runtime_drawpart_collection", source)
        self.assertIn("runtime_collection.hide_viewport = True", source)
        self.assertIn("draw_collection = bpy.data.collections.new(target_name)", source)
        self.assertIn("_link_object_once(draw_collection, target)", source)
        self.assertNotIn("_link_object_once(runtime_collection, target)", source)


if __name__ == "__main__":
    unittest.main()
