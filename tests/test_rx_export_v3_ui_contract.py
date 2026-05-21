import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROPERTIES_SOURCE = (REPO_ROOT / "properties.py").read_text(encoding="utf-8")
PANEL_SOURCE = (REPO_ROOT / "panel.py").read_text(encoding="utf-8")


class RXExportV3UIContractTests(unittest.TestCase):
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
