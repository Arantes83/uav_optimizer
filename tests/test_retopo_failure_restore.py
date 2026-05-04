import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


sys.modules["bpy"] = types.SimpleNamespace()
sys.modules["bpy.types"] = types.SimpleNamespace(Operator=object)

op_voxel = importlib.import_module("op_voxel")
op_quadriflow = importlib.import_module("op_quadriflow")


class FakeModifierList:
    def new(self, name, type):
        return types.SimpleNamespace(name=name, type=type, thickness=0.0, offset=0.0)


class FakeObject:
    def __init__(self, name, collection=None):
        self.name = name
        self.type = "MESH"
        self.mode = "OBJECT"
        self.hidden = False
        self.selected = False
        self.users_collection = []
        self.modifiers = FakeModifierList()
        self.data = types.SimpleNamespace(remesh_voxel_size=0.0)
        if collection is not None:
            collection.objects.link(self)

    def hide_set(self, value):
        self.hidden = bool(value)

    def hide_get(self):
        return self.hidden

    def select_set(self, value):
        self.selected = bool(value)

    def select_get(self):
        return self.selected


class FakeCollectionObjects:
    def __init__(self, collection):
        self.collection = collection
        self.items = []

    def link(self, obj):
        if obj not in self.items:
            self.items.append(obj)
        if self.collection not in obj.users_collection:
            obj.users_collection.append(self.collection)

    def unlink(self, obj):
        if obj in self.items:
            self.items.remove(obj)
        if self.collection in obj.users_collection:
            obj.users_collection.remove(self.collection)


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.objects = FakeCollectionObjects(self)
        self.children = FakeCollectionChildren()


class FakeCollectionChildren:
    def __init__(self):
        self.items = []

    def link(self, collection):
        if collection not in self.items:
            self.items.append(collection)


class FakeCollections(dict):
    def new(self, name):
        collection = FakeCollection(name)
        self[name] = collection
        return collection


class FakeObjects:
    def __init__(self, context):
        self.context = context
        self.removed = []

    def remove(self, obj, do_unlink=False):
        self.removed.append((obj, do_unlink))
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        if self.context.view_layer.objects.active is obj:
            self.context.view_layer.objects.active = None


class FakeObjectOps:
    def __init__(self, context, fail_method):
        self.context = context
        self.fail_method = fail_method

    def select_all(self, action):
        if action == "DESELECT":
            for obj in self.context.all_objects:
                obj.select_set(False)

    def duplicate(self):
        source = self.context.view_layer.objects.active
        duplicate = FakeObject(source.name + ".001")
        for collection in list(source.users_collection):
            collection.objects.link(duplicate)
        self.context.all_objects.append(duplicate)
        self.context.view_layer.objects.active = duplicate
        duplicate.select_set(True)

    def modifier_apply(self, modifier):
        return {"FINISHED"}

    def voxel_remesh(self):
        if self.fail_method == "voxel":
            raise RuntimeError("forced voxel failure")
        return {"FINISHED"}

    def quadriflow_remesh(self, **_kwargs):
        if self.fail_method == "quadriflow":
            raise RuntimeError("forced quadriflow failure")
        return {"FINISHED"}


class FakeContext:
    def __init__(self, fail_method):
        self.scene = types.SimpleNamespace(
            uav_props=types.SimpleNamespace(
                voxel_size=0.25,
                voxel_solidify_thickness=2.0,
                target_quad_count=512,
            ),
            collection=FakeCollection("Scene"),
        )
        self.view_layer = types.SimpleNamespace(objects=types.SimpleNamespace(active=None))
        self.all_objects = []
        self.initial_collection = FakeCollection("Source")
        self.source = FakeObject("Terrain_QEM", self.initial_collection)
        self.source.select_set(True)
        self.view_layer.objects.active = self.source
        self.all_objects.append(self.source)
        self.bpy = types.SimpleNamespace(
            data=types.SimpleNamespace(
                collections=FakeCollections(),
                objects=FakeObjects(self),
            ),
            ops=types.SimpleNamespace(object=FakeObjectOps(self, fail_method)),
        )

    @property
    def active_object(self):
        return self.view_layer.objects.active

    @property
    def selected_objects(self):
        return [obj for obj in self.all_objects if obj.select_get()]


class RetopoFailureRestoreTests(unittest.TestCase):
    def _run_operator(self, module, operator_cls, fail_method):
        context = FakeContext(fail_method)
        original_bpy = module.bpy
        module.bpy = context.bpy
        operator = operator_cls()
        operator.report = lambda _levels, _message: None
        try:
            result = operator.execute(context)
        finally:
            module.bpy = original_bpy
        return result, context

    def test_voxel_failure_restores_original_visibility_selection_and_active(self):
        result, context = self._run_operator(op_voxel, op_voxel.UAV_OT_voxel_retopo, "voxel")

        self.assertEqual(result, {"CANCELLED"})
        self.assertFalse(context.source.hide_get())
        self.assertTrue(context.source.select_get())
        self.assertIs(context.view_layer.objects.active, context.source)
        self.assertEqual(
            [obj.name for obj, do_unlink in context.bpy.data.objects.removed],
            ["Terrain_Voxel"],
        )
        self.assertTrue(all(do_unlink for _obj, do_unlink in context.bpy.data.objects.removed))

    def test_quadriflow_failure_restores_original_visibility_selection_and_active(self):
        result, context = self._run_operator(op_quadriflow, op_quadriflow.UAV_OT_quadriflow, "quadriflow")

        self.assertEqual(result, {"CANCELLED"})
        self.assertFalse(context.source.hide_get())
        self.assertTrue(context.source.select_get())
        self.assertIs(context.view_layer.objects.active, context.source)
        self.assertEqual(
            [obj.name for obj, do_unlink in context.bpy.data.objects.removed],
            ["Terrain_QuadriFlow"],
        )
        self.assertTrue(all(do_unlink for _obj, do_unlink in context.bpy.data.objects.removed))


if __name__ == "__main__":
    unittest.main()
