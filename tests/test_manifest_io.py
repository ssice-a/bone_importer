import ast
import json
import tempfile
import unittest
from pathlib import Path


def _load_manifest_helpers():
    source_path = Path(__file__).resolve().parents[1] / "core" / "manifest.py"
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {"resolve_export_manifest_path", "load_export_manifest"}
    selected = [node for node in module_ast.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {
        "json": json,
        "os": __import__("os"),
        "MANIFEST_FILE_NAME": "rx_export_manifest.json",
    }
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec")
    exec(compiled, namespace)
    return namespace["load_export_manifest"]


class ManifestIOTests(unittest.TestCase):
    def test_load_export_manifest_accepts_utf8_bom(self):
        load_export_manifest = _load_manifest_helpers()

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "rx_export_manifest.json"
            manifest_path.write_text('{"format":"rx_runtime_manifest_v2"}', encoding="utf-8-sig")

            manifest = load_export_manifest(temp_dir)

        self.assertEqual(manifest["format"], "rx_runtime_manifest_v2")
        self.assertEqual(manifest["clips"], {})
        self.assertEqual(manifest["payloads"], {})


if __name__ == "__main__":
    unittest.main()
