import unittest
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path


RX_EXPORT_PLAN_SOURCE = Path(__file__).resolve().parents[1] / "core" / "rx_export_plan.py"


def _load_rx_export_plan_module():
    spec = importlib.util.spec_from_file_location("rx_export_plan_under_test", RX_EXPORT_PLAN_SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rx_export_plan = _load_rx_export_plan_module()
FINAL_SKIN_OWN = rx_export_plan.FINAL_SKIN_OWN
FINAL_SKIN_SOURCE_GAME = rx_export_plan.FINAL_SKIN_SOURCE_GAME
DEFORM_PRESKIN_BONE = rx_export_plan.DEFORM_PRESKIN_BONE
DEFORM_MORPH_THEN_PRESKIN_BONE = rx_export_plan.DEFORM_MORPH_THEN_PRESKIN_BONE
MeshRouteAnalysis = rx_export_plan.MeshRouteAnalysis
RXExportPlanError = rx_export_plan.RXExportPlanError
build_rx_export_plan = rx_export_plan.build_rx_export_plan


@dataclass
class FakeObject:
    name: str
    type: str = "MESH"


@dataclass
class FakeCollection:
    name: str
    objects: list[FakeObject] = field(default_factory=list)
    children: list["FakeCollection"] = field(default_factory=list)


class RXExportV3PlanTests(unittest.TestCase):
    def test_direct_meshes_become_draw_segments_in_implicit_part00(self):
        source_mesh = FakeObject("source_like_face")
        own_mesh = FakeObject("own_skeleton_lashes")
        root = FakeCollection(
            "RX Export Collection",
            children=[
                FakeCollection(
                    "e78c7068-10590-0",
                    objects=[source_mesh, own_mesh],
                )
            ],
        )

        analyses = {
            "source_like_face": MeshRouteAnalysis(source_slots=(0, 1, 2)),
            "own_skeleton_lashes": MeshRouteAnalysis(own_bones=("Head", "Eye.L")),
        }

        plan = build_rx_export_plan(root, lambda obj: analyses[obj.name])

        self.assertEqual(1, len(plan.draw_parts))
        draw_part = plan.draw_parts[0]
        self.assertEqual("e78c7068", draw_part.identity.ib_hash)
        self.assertEqual(10590, draw_part.identity.match_index_count)
        self.assertTrue(draw_part.skip_original)
        self.assertEqual(1, len(draw_part.parts))
        part = draw_part.parts[0]
        self.assertEqual("part00", part.part_name)
        self.assertEqual(2, len(part.segments))
        self.assertEqual("source_like_face", part.segments[0].object_name)
        self.assertEqual(FINAL_SKIN_SOURCE_GAME, part.segments[0].final_skin_palette)
        self.assertFalse(part.segments[0].geometry_required)
        self.assertEqual("own_skeleton_lashes", part.segments[1].object_name)
        self.assertEqual(FINAL_SKIN_OWN, part.segments[1].final_skin_palette)
        self.assertTrue(part.segments[1].geometry_required)

    def test_source_game_only_segments_keep_original_draw(self):
        source_mesh = FakeObject("source_body")
        root = FakeCollection(
            "RX Export Collection",
            children=[
                FakeCollection(
                    "640d1c0e-46845-0",
                    objects=[source_mesh],
                )
            ],
        )

        plan = build_rx_export_plan(root, lambda _obj: MeshRouteAnalysis(source_slots=(0, 1, 2, 3)))

        draw_part = plan.draw_parts[0]
        self.assertFalse(draw_part.skip_original)
        self.assertFalse(draw_part.parts[0].segments[0].geometry_required)
        self.assertEqual(FINAL_SKIN_SOURCE_GAME, draw_part.parts[0].segments[0].final_skin_palette)

    def test_direct_meshes_are_invalid_when_part_collections_exist(self):
        root = FakeCollection(
            "RX Export Collection",
            children=[
                FakeCollection(
                    "640d1c0e-46845-0",
                    objects=[FakeObject("direct_mesh")],
                    children=[FakeCollection("part00", objects=[FakeObject("part_mesh")])],
                )
            ],
        )

        with self.assertRaisesRegex(RXExportPlanError, "direct mesh object"):
            build_rx_export_plan(root, lambda _obj: MeshRouteAnalysis(source_slots=(0,)))

    def test_explicit_part_collections_create_separate_parts_with_recursive_segments(self):
        root = FakeCollection(
            "RX Export Collection",
            children=[
                FakeCollection(
                    "2e5d9294-23220-0",
                    children=[
                        FakeCollection(
                            "part00 face",
                            children=[
                                FakeCollection(
                                    "nested segment group",
                                    objects=[FakeObject("face_segment")],
                                )
                            ],
                        ),
                        FakeCollection("part01 skirt", objects=[FakeObject("skirt_segment")]),
                    ],
                )
            ],
        )

        plan = build_rx_export_plan(root, lambda _obj: MeshRouteAnalysis(source_slots=(0, 1)))

        draw_part = plan.draw_parts[0]
        self.assertFalse(draw_part.skip_original)
        self.assertEqual(["part00", "part01"], [part.part_name for part in draw_part.parts])
        self.assertEqual("face_segment", draw_part.parts[0].segments[0].object_name)
        self.assertEqual("skirt_segment", draw_part.parts[1].segments[0].object_name)

    def test_preskin_bone_requires_source_game_final_skin_and_exports_geometry(self):
        mesh = FakeObject("mounted_prop")
        root = FakeCollection(
            "RX Export Collection",
            children=[FakeCollection("1377f2c3-59679-0", objects=[mesh])],
        )

        plan = build_rx_export_plan(
            root,
            lambda _obj: MeshRouteAnalysis(
                source_slots=(0,),
                preskin_bone_enabled=True,
                preskin_armature="PropRig",
                preskin_action="Loop",
            ),
        )

        segment = plan.draw_parts[0].parts[0].segments[0]
        self.assertTrue(plan.draw_parts[0].skip_original)
        self.assertTrue(segment.geometry_required)
        self.assertEqual(FINAL_SKIN_SOURCE_GAME, segment.final_skin_palette)
        self.assertEqual(DEFORM_PRESKIN_BONE, segment.deform_chain)
        self.assertEqual("PropRig", segment.preskin_armature)
        self.assertEqual("Loop", segment.preskin_action)

    def test_preskin_bone_rejects_own_final_skin(self):
        mesh = FakeObject("own_only_prop")
        root = FakeCollection(
            "RX Export Collection",
            children=[FakeCollection("1377f2c3-59679-0", objects=[mesh])],
        )

        with self.assertRaisesRegex(RXExportPlanError, "PreSkinBone requires SOURCE_GAME"):
            build_rx_export_plan(
                root,
                lambda _obj: MeshRouteAnalysis(
                    own_bones=("Root",),
                    preskin_bone_enabled=True,
                ),
            )

    def test_morph_then_preskin_uses_fixed_deform_order(self):
        mesh = FakeObject("face_with_morph_and_preskin")
        root = FakeCollection(
            "RX Export Collection",
            children=[FakeCollection("e78c7068-10590-0", objects=[mesh])],
        )

        plan = build_rx_export_plan(
            root,
            lambda _obj: MeshRouteAnalysis(
                source_slots=(0, 1),
                morph_payload_enabled=True,
                preskin_bone_enabled=True,
            ),
        )

        segment = plan.draw_parts[0].parts[0].segments[0]
        self.assertTrue(segment.geometry_required)
        self.assertEqual(DEFORM_MORPH_THEN_PRESKIN_BONE, segment.deform_chain)

    def test_source_and_own_final_skin_is_ambiguous_without_override(self):
        mesh = FakeObject("mixed_groups")
        root = FakeCollection(
            "RX Export Collection",
            children=[FakeCollection("e78c7068-10590-0", objects=[mesh])],
        )

        with self.assertRaisesRegex(RXExportPlanError, "choose Final Skin explicitly"):
            build_rx_export_plan(
                root,
                lambda _obj: MeshRouteAnalysis(source_slots=(0, 1), own_bones=("Root",)),
            )

    def test_final_skin_override_resolves_source_and_own_ambiguity(self):
        mesh = FakeObject("mixed_groups")
        root = FakeCollection(
            "RX Export Collection",
            children=[FakeCollection("e78c7068-10590-0", objects=[mesh])],
        )

        plan = build_rx_export_plan(
            root,
            lambda _obj: MeshRouteAnalysis(
                source_slots=(0, 1),
                own_bones=("Root",),
                final_skin_override=FINAL_SKIN_OWN,
            ),
        )

        segment = plan.draw_parts[0].parts[0].segments[0]
        self.assertEqual(FINAL_SKIN_OWN, segment.final_skin_palette)
        self.assertTrue(segment.geometry_required)


if __name__ == "__main__":
    unittest.main()
