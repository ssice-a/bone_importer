import importlib.util
import sys
import types
import unittest
from pathlib import Path


class Vector:
    def __init__(self, values):
        self.x = float(values[0])
        self.y = float(values[1])
        self.z = float(values[2])

    def __add__(self, other):
        return Vector((self.x + other.x, self.y + other.y, self.z + other.z))

    def __mul__(self, scalar):
        return Vector((self.x * scalar, self.y * scalar, self.z * scalar))

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return Vector((self.x / scalar, self.y / scalar, self.z / scalar))


class VertexGroup:
    def __init__(self, name, index):
        self.name = name
        self.index = index


class VertexGroupWeight:
    def __init__(self, group, weight):
        self.group = group
        self.weight = weight


class Vertex:
    def __init__(self, co, group, weight=1.0):
        self.co = Vector(co)
        self.groups = [VertexGroupWeight(group, weight)]


class MeshData:
    def __init__(self, vertices):
        self.vertices = vertices


class MeshObject(dict):
    type = "MESH"

    def __init__(self, name, mirror_x=True, group_names=None):
        super().__init__()
        self.name = name
        self["bmc_mirror_flip"] = mirror_x
        group_names = group_names or ("0", "1", "2")
        self.vertex_groups = [
            VertexGroup(group_name, index)
            for index, group_name in enumerate(group_names)
        ]
        self.data = MeshData(
            [
                Vertex((-1.0, 0.0, 0.0), 0),
                Vertex((1.0, 0.0, 0.0), min(1, len(group_names) - 1)),
                Vertex((0.0, 0.0, 0.0), min(2, len(group_names) - 1)),
            ]
        )


class PoseBone:
    def __init__(self, name):
        self.name = name
        self.bi_slot_id = -1
        self.bi_mesh_key = ""


class PoseBones(list):
    def __contains__(self, item):
        if isinstance(item, str):
            return any(pose_bone.name == item for pose_bone in self)
        return super().__contains__(item)

    def get(self, name, default=None):
        for pose_bone in self:
            if pose_bone.name == name:
                return pose_bone
        return default


class Armature:
    type = "ARMATURE"

    def __init__(self, name, mesh_name, head_positions=None):
        head_positions = head_positions or {
            0: (-1.0, 0.0, 0.0),
            1: (1.0, 0.0, 0.0),
            2: (0.0, 0.0, 0.0),
        }
        self.name = name
        self.matrix_world = None
        self.pose = types.SimpleNamespace(
            bones=PoseBones(
                [
                    self._pose_bone(0, mesh_name, head_positions),
                    self._pose_bone(1, mesh_name, head_positions),
                    self._pose_bone(2, mesh_name, head_positions),
                ]
            )
        )

    def _pose_bone(self, slot_id, mesh_name, head_positions):
        pose_bone = PoseBone(f"{slot_id}__{mesh_name}")
        pose_bone.bone = types.SimpleNamespace(head_local=Vector(head_positions[slot_id]))
        return pose_bone


class DrawPart:
    draw_key = "test_3_0"
    bone_enabled = True
    bone_slot_map_json = ""
    skin_contract = "TARGET_NUMERIC_GROUPS"

    def __init__(self, mesh, armature):
        self.source_object = mesh
        self.proxy_armature = armature
        self.bone_source_armature = armature


def _load_slot_contract_module():
    repo_root = Path(__file__).resolve().parents[1]
    package = types.ModuleType("bone_importer")
    package.__path__ = [str(repo_root)]
    core_package = types.ModuleType("bone_importer.core")
    core_package.__path__ = [str(repo_root / "core")]
    sys.modules.setdefault("bone_importer", package)
    sys.modules.setdefault("bone_importer.core", core_package)

    fake_bpy = types.ModuleType("bpy")
    fake_bpy.types = types.SimpleNamespace(Object=object)
    fake_bpy.data = types.SimpleNamespace(objects={})
    sys.modules["bpy"] = fake_bpy

    fake_mathutils = types.ModuleType("mathutils")
    fake_mathutils.Vector = Vector
    sys.modules["mathutils"] = fake_mathutils

    for module_name, path in (
        ("bone_importer.core.coordinate_contract", repo_root / "core" / "coordinate_contract.py"),
        ("bone_importer.core.slot_contract", repo_root / "core" / "slot_contract.py"),
    ):
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return sys.modules["bone_importer.core.slot_contract"]


class SlotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slot_contract = _load_slot_contract_module()

    def test_mirrored_numeric_target_slots_keep_direct_slot_bindings(self):
        mesh = MeshObject("mesh", mirror_x=True)
        draw_part = DrawPart(mesh, Armature("arm", mesh.name))

        bindings = self.slot_contract.resolve_bone_slot_bindings(draw_part)

        self.assertEqual(
            [(binding.slot_id, binding.source_bone) for binding in bindings],
            [(0, "0__mesh"), (1, "1__mesh"), (2, "2__mesh")],
        )

    def test_non_mirrored_numeric_target_slots_keep_direct_bindings(self):
        mesh = MeshObject("mesh", mirror_x=False)
        draw_part = DrawPart(mesh, Armature("arm", mesh.name))

        bindings = self.slot_contract.resolve_bone_slot_bindings(draw_part)

        self.assertEqual(
            [(binding.slot_id, binding.source_bone) for binding in bindings],
            [(0, "0__mesh"), (1, "1__mesh"), (2, "2__mesh")],
        )

    def test_explicit_slot_map_is_not_mirrored(self):
        mesh = MeshObject("mesh", mirror_x=True)
        draw_part = DrawPart(mesh, Armature("arm", mesh.name))
        draw_part.bone_slot_map_json = '[{"slot_id": 0, "source_bone": "0__mesh"}]'

        bindings = self.slot_contract.resolve_bone_slot_bindings(draw_part)

        self.assertEqual(
            [(binding.slot_id, binding.source_bone) for binding in bindings],
            [(0, "0__mesh")],
        )

    def test_collection_draw_part_uses_union_of_all_source_mesh_slots(self):
        face = MeshObject("face", group_names=("0", "1"))
        lashes = MeshObject("lashes", group_names=("2",))
        armature = Armature("arm", face.name)
        armature.pose.bones.append(PoseBone("2__lashes"))
        draw_part = DrawPart(face, armature)
        draw_part.source_objects = (face, lashes)
        draw_part.bone_slot_map_json = (
            '[{"slot_id": 0, "source_bone": "0__face"},'
            '{"slot_id": 1, "source_bone": "1__face"},'
            '{"slot_id": 2, "source_bone": "2__lashes"}]'
        )

        bindings = self.slot_contract.resolve_bone_slot_bindings(draw_part)

        self.assertEqual(
            [(binding.slot_id, binding.source_bone) for binding in bindings],
            [(0, "0__face"), (1, "1__face"), (2, "2__lashes")],
        )


if __name__ == "__main__":
    unittest.main()
