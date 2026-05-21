import importlib.util
import sys
import unittest
from pathlib import Path


SOURCE_PATH = Path(__file__).resolve().parents[1] / "core" / "rx_collection_setup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("rx_collection_setup_under_test", SOURCE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rx_collection_setup = _load_module()


class RXCollectionSetupTests(unittest.TestCase):
    def test_manifest_draw_parts_create_sorted_ib_part00_plan(self):
        manifest = {
            "draw_parts": {
                "small_96_0": {
                    "object_name": "58870754-96-0",
                    "hash": "58870754",
                    "match_index_count": 96,
                    "first_index": 0,
                    "match_priority": -1000,
                },
                "large_59679_0": {
                    "object_name": "1377f2c3-59679-0",
                    "hash": "1377f2c3",
                    "match_index_count": 59679,
                    "first_index": 0,
                    "match_priority": -1000,
                },
            },
            "payloads": {
                "large_59679_0": {"bone": {"static": "large_bone_static.buf"}},
                "small_96_0": {"bone": {"static": "small_bone_static.buf"}},
            },
        }

        plan = rx_collection_setup.build_collection_setup_plan(manifest)

        self.assertEqual("RX Export Collection", plan.root_collection_name)
        self.assertEqual(["1377f2c3-59679-0", "58870754-96-0"], [part.collection_name for part in plan.draw_parts])
        self.assertTrue(all(part.part_collection_name == "part00" for part in plan.draw_parts))
        self.assertEqual("1377f2c3-59679-0", plan.draw_parts[0].objects[0].object_name)
        self.assertTrue(plan.draw_parts[0].has_bone)

    def test_geometry_object_names_override_draw_part_object_for_replacement(self):
        manifest = {
            "draw_parts": {
                "e78c7068_10590_0": {
                    "object_name": "e78c7068-10590-0",
                    "hash": "e78c7068",
                    "match_index_count": 10590,
                    "first_index": 0,
                    "cb1_profile": "NONE",
                    "vb_layout_profile": "AUTO",
                    "export_mirror_x": True,
                    "export_uv_flip_v": True,
                }
            },
            "payloads": {
                "e78c7068_10590_0": {
                    "geometry": [
                        {
                            "object_names": ["RXEXP_e78c7068-10590-0_000_face.001"],
                            "vertex_buffers": {"vb0": {"stride": 16}},
                        }
                    ],
                    "morph": {
                        "base_position_path": "Buffer/e78c7068-10590-0_part00-Position.buf",
                        "base_position_stride": 16,
                    },
                }
            },
        }

        plan = rx_collection_setup.build_collection_setup_plan(manifest)
        obj = plan.draw_parts[0].objects[0]

        self.assertEqual("RXEXP_e78c7068-10590-0_000_face.001", obj.object_name)
        self.assertTrue(obj.force_replace_geometry)
        self.assertTrue(obj.morph_enabled)
        self.assertEqual("Buffer/e78c7068-10590-0_part00-Position.buf", obj.base_position_path)
        self.assertEqual(16, obj.base_position_stride)


if __name__ == "__main__":
    unittest.main()
