import importlib
import pathlib
import sys

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


def make_grid_mesh(name, size=8):
    vertices = []
    faces = []
    for y in range(size + 1):
        for x in range(size + 1):
            vertices.append((x / size, y / size, 0.0))

    def vertex_index(x, y):
        return y * (size + 1) + x

    for y in range(size):
        for x in range(size):
            faces.append((
                vertex_index(x, y),
                vertex_index(x + 1, y),
                vertex_index(x + 1, y + 1),
                vertex_index(x, y + 1),
            ))

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
            uv_layer.data[loop_index].uv = (vertex.co.x, vertex.co.y)
    mesh.uv_layers.active = uv_layer

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def run_lod_generation(op_lod, base_obj):
    context = bpy.context
    props = context.scene.uav_lod_props

    base_name = op_lod._resolve_base_name(base_obj)
    base_tris = op_lod._tri_count(base_obj)
    table = op_lod._calc_lod_table(
        base_tris,
        props.lod_min_polycount,
        props.lod_ratio,
        props.lod_max_levels,
    )
    assert_true(table, "LOD table is empty; smoke mesh did not exercise generation.")

    col_name = props.lod_collection_name.strip() or f"{base_name}_LOD"
    if col_name not in bpy.data.collections:
        lod_col = bpy.data.collections.new(col_name)
        context.scene.collection.children.link(lod_col)
    else:
        lod_col = bpy.data.collections[col_name]

    removed = op_lod._remove_existing_lod_objects(lod_col, base_name)
    created = [
        op_lod._duplicate_mesh_object(base_obj, f"{base_name}_LOD0", lod_col)
    ]
    prev_obj = created[0]
    for entry in table:
        new_obj = op_lod._duplicate_mesh_object(prev_obj, f"{base_name}_LOD{entry['level']}", lod_col)
        op_lod._decimate_obj(context, new_obj, entry["step_ratio"])
        created.append(new_obj)
        prev_obj = new_obj

    op_lod._sync_export_lod_collection(context, lod_col)
    return lod_col, created, removed


def main():
    reset_scene()

    addon = importlib.import_module("uav_optimizer")
    try:
        addon.unregister()
    except Exception:
        pass
    addon.register()

    op_lod = importlib.import_module("uav_optimizer.op_lod")
    op_export = importlib.import_module("uav_optimizer.op_export")

    base_obj = make_grid_mesh("SmokeAsset", size=8)
    lod_props = bpy.context.scene.uav_lod_props
    lod_props.lod_ratio = 0.5
    lod_props.lod_min_polycount = 8
    lod_props.lod_max_levels = 3
    lod_props.lod_collection_name = "SmokeAsset_LOD"

    export_props = bpy.context.scene.uav_export_props
    export_props.scope = "LOD_COLLECTION"
    export_props.collection_ref = None

    first_col, first_created, first_removed = run_lod_generation(op_lod, base_obj)
    first_names = [obj.name for obj in op_export._collect_export_objects(bpy.context, export_props)]
    assert_true(first_removed == 0, f"First run removed unexpected objects: {first_removed}")
    assert_true(len(first_names) == len(first_created), f"First export list mismatch: {first_names}")

    second_col, second_created, second_removed = run_lod_generation(op_lod, base_obj)
    export_names = [obj.name for obj in op_export._collect_export_objects(bpy.context, export_props)]

    assert_true(second_col == first_col, "LOD generation switched collection unexpectedly.")
    assert_true(export_props.collection_ref == second_col, "Export collection_ref was not synced.")
    assert_true(
        second_removed == len(first_created),
        f"Second run removed {second_removed}, expected {len(first_created)} stale LOD objects.",
    )
    assert_true(
        len(export_names) == len(second_created),
        f"Export collection contains stale/extra objects: {export_names}",
    )
    assert_true(
        not any(".00" in name for name in export_names),
        f"Export collection contains Blender duplicate names: {export_names}",
    )
    assert_true(
        export_names == [obj.name for obj in second_created],
        f"Export order/list mismatch: {export_names}",
    )

    print("SMOKE_LOD_CLEANUP_PASS")
    print("EXPORT_OBJECTS=" + ",".join(export_names))
    print(f"STALE_REMOVED={second_removed}")

    addon.unregister()


if __name__ == "__main__":
    main()
