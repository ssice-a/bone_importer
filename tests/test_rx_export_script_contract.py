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

        self.assertIn('source["bmc_mirror_flip"]', source)
        self.assertIn('source["bmc_uv_mirror_u"]', source)
        self.assertIn('source["bmc_uv_flip_v"]', source)

    def test_face_replacement_disables_v_flip_for_current_rx_scene(self):
        replacement_geometry = _replacement_geometry_literal()
        face = replacement_geometry["e78c7068-10590-0"]
        eyelash = replacement_geometry["2009f0d6-1356-0"]

        self.assertTrue(face["mirror_flip"])
        self.assertTrue(face["uv_mirror_u"])
        self.assertFalse(face["uv_flip_v"])
        self.assertTrue(eyelash["mirror_flip"])
        self.assertFalse(eyelash["uv_mirror_u"])
        self.assertTrue(eyelash["uv_flip_v"])


if __name__ == "__main__":
    unittest.main()
