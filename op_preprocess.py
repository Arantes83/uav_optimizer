import time

import bpy
import bmesh
import mathutils
from bpy.types import Operator


PREPROCESS_SUFFIX = "_PREP"


def _duplicate_mesh_object(source_obj, target_name, scene_collection):
    """Create a single-user object+mesh copy that preserves the original."""
    new_obj = source_obj.copy()
    if source_obj.data is not None:
        new_obj.data = source_obj.data.copy()
        new_obj.data.name = target_name
    new_obj.name = target_name

    target_collections = list(source_obj.users_collection) or [scene_collection]
    for collection in target_collections:
        collection.objects.link(new_obj)
    return new_obj


class UAV_OT_preprocess(Operator):
    bl_idname = "uav.preprocess"
    bl_label = "Run Pre-Processing"
    bl_description = (
        "Create processed mesh copies from the selected sources. "
        "The original meshes are preserved and hidden after the cleanup finishes"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props = context.scene.uav_props
        scene_collection = context.scene.collection
        sources = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not sources:
            self.report({'WARNING'}, "No valid meshes selected.")
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        created_objects = []
        start_time = time.perf_counter()
        self.report({'INFO'}, "Starting pre-processing on mesh copies...")

        for source_obj in sources:
            target_name = f"{source_obj.name}{PREPROCESS_SUFFIX}"
            new_obj = _duplicate_mesh_object(source_obj, target_name, scene_collection)
            try:
                bpy.ops.object.select_all(action='DESELECT')
                new_obj.select_set(True)
                context.view_layer.objects.active = new_obj

                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')

                bpy.ops.mesh.remove_doubles(threshold=props.pre_merge_distance)
                bpy.ops.mesh.dissolve_degenerate(threshold=props.pre_degenerate_threshold)
                bpy.ops.mesh.customdata_custom_splitnormals_clear()

                if props.pre_smooth_iterations > 0:
                    bpy.ops.mesh.vertices_smooth(
                        repeat=props.pre_smooth_iterations,
                        factor=props.pre_smooth_factor,
                        wait_for_input=False,
                    )

                if props.pre_despike_threshold > 0.0:
                    bm = bmesh.from_edit_mesh(new_obj.data)
                    for _ in range(props.pre_despike_passes):
                        for vert in bm.verts:
                            if vert.is_boundary or not vert.link_edges:
                                continue
                            neighbors = [edge.other_vert(vert) for edge in vert.link_edges]
                            avg_loc = sum((neighbor.co for neighbor in neighbors), mathutils.Vector()) / len(neighbors)
                            if (vert.co - avg_loc).length > props.pre_despike_threshold:
                                vert.co = vert.co.lerp(avg_loc, props.pre_despike_lerp)
                    bmesh.update_edit_mesh(new_obj.data)

                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.shade_smooth()
            except Exception:
                if context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                bpy.data.objects.remove(new_obj, do_unlink=True)
                raise

            source_obj.hide_set(True)
            source_obj.select_set(False)
            new_obj.select_set(False)
            created_objects.append(new_obj)

        bpy.ops.object.select_all(action='DESELECT')
        for obj in created_objects:
            obj.select_set(True)
        if created_objects:
            context.view_layer.objects.active = created_objects[0]

        elapsed = time.perf_counter() - start_time
        self.report(
            {'INFO'},
            f"Pre-processing complete: {len(created_objects)} mesh copy/copies generated in {elapsed:.2f}s.",
        )
        return {'FINISHED'}