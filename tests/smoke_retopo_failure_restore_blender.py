import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import op_quadriflow
import op_voxel


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def assert_false(value, message):
    if value:
        raise AssertionError(message)


def make_mesh_object(name):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(
        [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def validate_restore(module, name):
    obj = make_mesh_object(name)
    state = module._capture_source_state(bpy.context, obj)

    obj.hide_set(True)
    obj.select_set(False)
    bpy.context.view_layer.objects.active = None

    module._restore_source_state(bpy.context, obj, state)

    assert_false(obj.hide_get(), name + " source should be visible after restore")
    assert_true(obj.select_get(), name + " source should be selected after restore")
    assert_true(
        bpy.context.view_layer.objects.active is obj,
        name + " source should be active after restore",
    )


def run():
    validate_restore(op_voxel, "SmokeVoxelSource")
    validate_restore(op_quadriflow, "SmokeQuadriFlowSource")
    print("SMOKE_RETOPO_RESTORE_PASS")


if __name__ == "__main__":
    run()
