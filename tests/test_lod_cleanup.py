import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeBpyObjects:
    def __init__(self):
        self.removed = []

    def remove(self, obj, do_unlink=False):
        self.removed.append((obj, do_unlink))


fake_bpy = types.SimpleNamespace(
    data=types.SimpleNamespace(objects=FakeBpyObjects()),
)
sys.modules["bpy"] = fake_bpy
sys.modules["bpy.types"] = types.SimpleNamespace(Operator=object)
sys.modules["bmesh"] = types.SimpleNamespace()

op_lod = importlib.import_module("op_lod")


class FakeObject:
    def __init__(self, name):
        self.name = name


class FakeMeshData:
    def __init__(self, name="Mesh"):
        self.name = name

    def copy(self):
        return FakeMeshData(self.name + ".copy")


class FakeMeshObject:
    def __init__(self, name):
        self.name = name
        self.data = FakeMeshData(name + "_Mesh")

    def copy(self):
        return FakeMeshObject(self.name + ".copy")

    def select_set(self, _value):
        pass


class FakeCollectionObjects:
    def __init__(self):
        self.linked = []

    def link(self, obj):
        self.linked.append(obj)


class FakeCollection:
    def __init__(self, objects):
        self.objects = list(objects)


class FakeLinkCollection:
    def __init__(self):
        self.objects = FakeCollectionObjects()


class FakeExportProps:
    def __init__(self, collection_ref=None):
        self.collection_ref = collection_ref


class FakeContext:
    def __init__(self, export_props):
        self.scene = types.SimpleNamespace(uav_export_props=export_props)


class LODCleanupTests(unittest.TestCase):
    def setUp(self):
        fake_bpy.data.objects.removed.clear()

    def test_removes_existing_generated_lods_for_same_base_only(self):
        target_collection = FakeCollection([
            FakeObject("Tree_LOD0"),
            FakeObject("Tree_LOD1"),
            FakeObject("Tree_LOD1.001"),
            FakeObject("Rock_LOD0"),
            FakeObject("Tree_custom_helper"),
        ])

        removed = op_lod._remove_existing_lod_objects(target_collection, "Tree")

        self.assertEqual(removed, 3)
        self.assertEqual(
            [obj.name for obj, do_unlink in fake_bpy.data.objects.removed],
            ["Tree_LOD0", "Tree_LOD1", "Tree_LOD1.001"],
        )
        self.assertTrue(all(do_unlink for _obj, do_unlink in fake_bpy.data.objects.removed))

    def test_export_collection_selector_is_replaced_with_latest_lod_collection(self):
        old_collection = object()
        new_collection = object()
        export_props = FakeExportProps(collection_ref=old_collection)
        context = FakeContext(export_props)

        op_lod._sync_export_lod_collection(context, new_collection)

        self.assertIs(export_props.collection_ref, new_collection)

    def test_failed_lod_step_removes_partial_duplicate_before_reraising(self):
        operator = object.__new__(op_lod.UAV_OT_generate_lods)
        operator._base_name = "Tree"
        operator._prev_obj = FakeMeshObject("Tree_LOD0")
        operator._lod_col = FakeLinkCollection()
        operator._created = [operator._prev_obj]
        context = object()
        original_decimate = op_lod._decimate_obj

        def fail_decimate(_context, _obj, _ratio):
            raise RuntimeError("forced decimate failure")

        op_lod._decimate_obj = fail_decimate
        try:
            with self.assertRaisesRegex(RuntimeError, "forced decimate failure"):
                operator._process_step(context, {"level": 1, "step_ratio": 0.5})
        finally:
            op_lod._decimate_obj = original_decimate

        self.assertEqual([obj.name for obj in operator._lod_col.objects.linked], ["Tree_LOD1"])
        self.assertEqual(
            [obj.name for obj, do_unlink in fake_bpy.data.objects.removed],
            ["Tree_LOD1"],
        )
        self.assertTrue(all(do_unlink for _obj, do_unlink in fake_bpy.data.objects.removed))
        self.assertEqual([obj.name for obj in operator._created], ["Tree_LOD0"])
        self.assertIs(operator._prev_obj, operator._created[0])


if __name__ == "__main__":
    unittest.main()
