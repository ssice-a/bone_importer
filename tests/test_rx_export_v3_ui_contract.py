import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROPERTIES_SOURCE = (REPO_ROOT / "properties.py").read_text(encoding="utf-8")
PANEL_SOURCE = (REPO_ROOT / "panel.py").read_text(encoding="utf-8")
OPERATORS_SOURCE = (REPO_ROOT / "operators.py").read_text(encoding="utf-8")
INIT_SOURCE = (REPO_ROOT / "__init__.py").read_text(encoding="utf-8")


class RXExportV3UIContractTests(unittest.TestCase):
    def test_scene_level_v3_export_controls_are_registered(self):
        for property_name in (
            "bi_ui_language",
            "bi_rx_export_type",
            "bi_rx_export_geometry",
            "bi_rx_source_fps",
            "bi_rx_target_game_fps",
            "bi_rx_playback_speed",
            "bi_rx_preview_expanded",
            "bi_rx_object_advanced_expanded",
        ):
            self.assertIn(property_name, PROPERTIES_SOURCE)

    def test_main_panel_uses_single_v3_export_flow(self):
        for property_name in (
            "bi_ui_language",
            "bi_rx_export_type",
            "bi_rx_export_geometry",
            "bi_rx_source_fps",
            "bi_rx_target_game_fps",
            "bi_rx_playback_speed",
        ):
            self.assertIn(property_name, PANEL_SOURCE)

        self.assertIn('operator("object.bi_create_rx_export_collection"', PANEL_SOURCE)
        self.assertIn('operator("object.bi_export_rx_package"', PANEL_SOURCE)
        self.assertNotIn('operator("object.bi_export_animation"', PANEL_SOURCE)
        self.assertNotIn('operator("object.bi_export_morph"', PANEL_SOURCE)
        self.assertNotIn('"bi_animation_presents_per_step"', PANEL_SOURCE)
        self.assertNotIn("Export Bone Payload", PANEL_SOURCE)
        self.assertNotIn("Export Morph Payload", PANEL_SOURCE)

    def test_single_v3_export_operator_is_registered(self):
        self.assertIn("class BI_OT_create_rx_export_collection", OPERATORS_SOURCE)
        self.assertIn("bl_idname = \"object.bi_create_rx_export_collection\"", OPERATORS_SOURCE)
        self.assertIn("operators.BI_OT_create_rx_export_collection", INIT_SOURCE)
        self.assertIn("class BI_OT_export_rx_package", OPERATORS_SOURCE)
        self.assertIn("bl_idname = \"object.bi_export_rx_package\"", OPERATORS_SOURCE)
        self.assertIn("operators.BI_OT_export_rx_package", INIT_SOURCE)

    def test_panel_uses_dedicated_translation_module(self):
        self.assertIn("from .core.i18n import tr", PANEL_SOURCE)

    def test_object_route_properties_are_registered(self):
        for property_name in (
            "bi_final_skin",
            "bi_final_armature",
            "bi_force_replace_geometry",
            "bi_preskin_bone_enabled",
            "bi_preskin_armature",
            "bi_preskin_action",
        ):
            self.assertIn(property_name, PROPERTIES_SOURCE)

    def test_panel_exposes_final_skin_and_preskin_controls(self):
        for property_name in (
            "bi_final_skin",
            "bi_final_armature",
            "bi_force_replace_geometry",
            "bi_preskin_bone_enabled",
            "bi_preskin_armature",
            "bi_preskin_action",
        ):
            self.assertIn(property_name, PANEL_SOURCE)


if __name__ == "__main__":
    unittest.main()
