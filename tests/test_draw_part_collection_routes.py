import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeObject:
    name: str
    type: str = "MESH"
    bi_proxy_armature_name: str = "ProxyArm"
    bi_match_priority: int = -1000
    bi_bone_enabled: bool = True
    bi_bone_slot_map_json: str = ""
    bi_skin_contract: str = "TARGET_NUMERIC_GROUPS"
    bi_morph_enabled: bool = False
    bi_morph_source_object: object | None = None
    bi_cb1_profile: str = "NONE"
    bi_vb_layout_profile: str = "AUTO"
    bi_buffer_correction_mode: str = ""
    bi_base_position_path: str = ""
    bi_base_position_stride: int = 0
    bi_bone_source_armature: object | None = None


@dataclass
class FakeCollection:
    name: str
    objects: list[FakeObject] = field(default_factory=list)
    children: list["FakeCollection"] = field(default_factory=list)
    bi_cb1_override: str = "NONE"


def _load_draw_part_module(objects_by_name):
    package = types.ModuleType("bone_importer")
    package.__path__ = [str(REPO_ROOT)]
    core_package = types.ModuleType("bone_importer.core")
    core_package.__path__ = [str(REPO_ROOT / "core")]
    sys.modules.setdefault("bone_importer", package)
    sys.modules.setdefault("bone_importer.core", core_package)

    fake_bpy = types.ModuleType("bpy")
    fake_bpy.types = types.SimpleNamespace(Object=object)
    fake_bpy.data = types.SimpleNamespace(objects=objects_by_name)
    sys.modules["bpy"] = fake_bpy
    fake_mathutils = types.ModuleType("mathutils")
    fake_mathutils.Vector = lambda values: tuple(values)
    sys.modules["mathutils"] = fake_mathutils

    for module_name in (
        "bone_importer.core.context",
        "bone_importer.core.collection_plan",
        "bone_importer.core.draw_part",
    ):
        sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(
        "bone_importer.core.draw_part",
        REPO_ROOT / "core" / "draw_part.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DrawPartCollectionRouteTests(unittest.TestCase):
    def test_ib_collection_with_visible_meshes_becomes_runtime_draw_part(self):
        proxy = FakeObject("ProxyArm", type="ARMATURE", bi_proxy_armature_name="")
        face = FakeObject("000_face")
        lashes = FakeObject("005_lashes")
        root = FakeCollection(
            "RX Export Collection",
            children=[
                FakeCollection(
                    "e78c7068-10590-0",
                    objects=[face, lashes],
                )
            ],
        )
        draw_part = _load_draw_part_module({"ProxyArm": proxy})

        draw_parts = draw_part.draw_parts_from_export_collection(root)

        self.assertEqual(1, len(draw_parts))
        self.assertEqual("e78c7068_10590_0", draw_parts[0].draw_key)
        self.assertEqual("000_face", draw_parts[0].source_object.name)
        self.assertEqual(["000_face", "005_lashes"], [obj.name for obj in draw_parts[0].source_objects])
        self.assertIs(proxy, draw_parts[0].proxy_armature)

    def test_legacy_draw_part_named_objects_still_work(self):
        proxy = FakeObject("ProxyArm", type="ARMATURE", bi_proxy_armature_name="")
        legacy = FakeObject("e78c7068-10590-0")
        root = FakeCollection("RX Runtime DrawParts", objects=[legacy])
        draw_part = _load_draw_part_module({"ProxyArm": proxy})

        draw_parts = draw_part.draw_parts_from_export_collection(root)

        self.assertEqual(1, len(draw_parts))
        self.assertEqual("e78c7068_10590_0", draw_parts[0].draw_key)
        self.assertEqual(["e78c7068-10590-0"], [obj.name for obj in draw_parts[0].source_objects])


if __name__ == "__main__":
    unittest.main()
