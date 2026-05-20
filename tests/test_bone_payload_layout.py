import ast
import unittest
from pathlib import Path


def _load_static_row_builder():
    source_path = Path(__file__).resolve().parents[1] / "core" / "bone_payload_export.py"
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {"_pack_slot_ids_uint4", "build_bone_static_uint4_rows"}
    selected = [node for node in module_ast.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {"RESERVED_PALETTE_ROWS": 3, "BONE_PAYLOAD_FLAGS_NONE": 0}
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec")
    exec(compiled, namespace)
    return namespace["build_bone_static_uint4_rows"]


class BonePayloadLayoutTests(unittest.TestCase):
    def test_bone_static_reserves_three_rows_before_slot_zero(self):
        build_bone_static_uint4_rows = _load_static_row_builder()

        rows = build_bone_static_uint4_rows((0, 2), sample_count=5)

        self.assertEqual(rows[0], (2, 5, 3, 1))
        self.assertEqual(rows[1], (12, 12, 0, 0))
        self.assertEqual(rows[2], (0, 2, 0xFFFFFFFF, 0xFFFFFFFF))


if __name__ == "__main__":
    unittest.main()
