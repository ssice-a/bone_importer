import importlib.util
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rx_export_plan = _load_module("rx_export_plan", REPO_ROOT / "core" / "rx_export_plan.py")
rx_mesh_analysis = _load_module("rx_mesh_analysis", REPO_ROOT / "core" / "rx_mesh_analysis.py")


@dataclass
class FakeVertexGroup:
    name: str
    index: int


@dataclass
class FakeGroupElement:
    group: int
    weight: float


@dataclass
class FakeVertex:
    groups: list[FakeGroupElement] = field(default_factory=list)


@dataclass
class FakeMeshData:
    vertices: list[FakeVertex] = field(default_factory=list)
    shape_keys: object | None = None


@dataclass
class FakeObject:
    name: str
    vertex_groups: list[FakeVertexGroup]
    data: FakeMeshData
    bi_final_skin: str = "AUTO"
    bi_morph_enabled: bool = False
    bi_preskin_bone_enabled: bool = False
    bi_preskin_action: str = ""


class RXMeshRouteAnalysisTests(unittest.TestCase):
    def test_ignores_empty_groups_and_classifies_weighted_numeric_groups_as_source_slots(self):
        mesh = FakeObject(
            name="source_mesh",
            vertex_groups=[
                FakeVertexGroup("0", 0),
                FakeVertexGroup("12__body", 1),
                FakeVertexGroup("99", 2),
            ],
            data=FakeMeshData(vertices=[FakeVertex(groups=[FakeGroupElement(0, 1.0), FakeGroupElement(1, 0.5)])]),
        )

        analysis = rx_mesh_analysis.analyze_mesh_route(mesh)

        self.assertEqual((0, 12), analysis.source_slots)
        self.assertEqual((), analysis.own_bones)

    def test_classifies_weighted_non_numeric_groups_as_own_bones(self):
        mesh = FakeObject(
            name="own_mesh",
            vertex_groups=[
                FakeVertexGroup("Root", 0),
                FakeVertexGroup("Head", 1),
                FakeVertexGroup("Empty", 2),
            ],
            data=FakeMeshData(vertices=[FakeVertex(groups=[FakeGroupElement(1, 1.0), FakeGroupElement(0, 0.25)])]),
        )

        analysis = rx_mesh_analysis.analyze_mesh_route(mesh)

        self.assertEqual((), analysis.source_slots)
        self.assertEqual(("Head", "Root"), analysis.own_bones)

    def test_reads_explicit_route_flags_from_object_properties(self):
        mesh = FakeObject(
            name="morph_preskin_mesh",
            vertex_groups=[FakeVertexGroup("0", 0)],
            data=FakeMeshData(vertices=[FakeVertex(groups=[FakeGroupElement(0, 1.0)])]),
            bi_final_skin="SOURCE_GAME",
            bi_morph_enabled=True,
            bi_preskin_bone_enabled=True,
            bi_preskin_action="Loop",
        )
        preskin_armature = object()
        mesh.bi_preskin_armature = preskin_armature

        analysis = rx_mesh_analysis.analyze_mesh_route(mesh)

        self.assertEqual("SOURCE_GAME", analysis.final_skin_override)
        self.assertTrue(analysis.morph_payload_enabled)
        self.assertTrue(analysis.preskin_bone_enabled)
        self.assertIs(preskin_armature, analysis.preskin_armature_ref)
        self.assertEqual("Loop", analysis.preskin_action)


if __name__ == "__main__":
    unittest.main()
