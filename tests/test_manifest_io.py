import ast
import json
import os
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
        "os": os,
        "MANIFEST_FILE_NAME": "rx_export_manifest.json",
        "MANIFEST_DIR_NAME": os.path.join("Meta", "Manifest"),
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

    def test_load_export_manifest_prefers_meta_manifest_path(self):
        load_export_manifest = _load_manifest_helpers()

        with tempfile.TemporaryDirectory() as temp_dir:
            meta_manifest_dir = Path(temp_dir) / "Meta" / "Manifest"
            meta_manifest_dir.mkdir(parents=True)
            (Path(temp_dir) / "rx_export_manifest.json").write_text(
                '{"format":"legacy","clips":{"legacy":{}}}',
                encoding="utf-8",
            )
            (meta_manifest_dir / "rx_export_manifest.json").write_text(
                '{"format":"rx_runtime_manifest_v2","clips":{"meta":{}}}',
                encoding="utf-8",
            )

            manifest = load_export_manifest(temp_dir)

        self.assertIn("meta", manifest["clips"])
        self.assertNotIn("legacy", manifest["clips"])


if __name__ == "__main__":
    unittest.main()
