import importlib
import pathlib
import sys
import types

import bpy


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_PARENT = ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def reset_scene():
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object else None
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


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
    return obj


def main():
    reset_scene()

    addon = importlib.import_module("uav_optimizer")
    try:
        addon.unregister()
    except Exception:
        pass
    addon.register()

    op_lod = importlib.import_module("uav_optimizer.op_lod")
    context = bpy.context
    base_obj = make_mesh_object("SmokePartial")
    lod_col = bpy.data.collections.new("SmokePartial_LOD")
    context.scene.collection.children.link(lod_col)
    lod0 = op_lod._duplicate_mesh_object(base_obj, "SmokePartial_LOD0", lod_col)

    operator = types.SimpleNamespace(
        _base_name="SmokePartial",
        _prev_obj=lod0,
        _lod_col=lod_col,
        _created=[lod0],
    )

    original_decimate = op_lod._decimate_obj

    def fail_decimate(_context, _obj, _ratio):
        raise RuntimeError("forced smoke decimate failure")

    op_lod._decimate_obj = fail_decimate
    try:
        try:
            op_lod.UAV_OT_generate_lods._process_step(
                operator,
                context,
                {"level": 1, "step_ratio": 0.5},
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("LOD step did not raise the forced decimate failure")
    finally:
        op_lod._decimate_obj = original_decimate

    assert_true("SmokePartial_LOD1" not in bpy.data.objects, "Partial LOD object remained in bpy.data.objects.")
    assert_true(
        "SmokePartial_LOD1" not in {obj.name for obj in lod_col.objects},
        "Partial LOD object remained linked in the LOD collection.",
    )
    assert_true(operator._created == [lod0], "Failed partial LOD was added to _created.")
    assert_true(operator._prev_obj == lod0, "Failed partial LOD replaced _prev_obj.")

    print("SMOKE_LOD_FAILURE_CLEANUP_PASS")
    addon.unregister()


if __name__ == "__main__":
    main()
