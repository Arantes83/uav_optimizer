import bpy
import bmesh
import mathutils
from bpy.types import Operator

class UAV_OT_preprocess(Operator):
    bl_idname = "uav.preprocess"
    bl_label = "Run Pre-Processing"
    bl_description = "Cleans the raw photogrammetry mesh. Removes spikes, welds overlapping vertices, and smooths noise to ensure a clean bake"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props = context.scene.uav_props

        objects_to_process = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not objects_to_process:
            self.report({'WARNING'}, "No valid meshes selected.")
            return {'CANCELLED'}

        self.report({'INFO'}, "Starting Pre-Processing on high-poly mesh...")

        for obj in objects_to_process:
            context.view_layer.objects.active = obj

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')

            # ------------------------------------------------------------------
            # 1. Basic mandatory cleanup - thresholds now come from properties
            # ------------------------------------------------------------------
            bpy.ops.mesh.remove_doubles(threshold=props.pre_merge_distance)
            bpy.ops.mesh.dissolve_degenerate(threshold=props.pre_degenerate_threshold)
            bpy.ops.mesh.customdata_custom_splitnormals_clear()

            # ------------------------------------------------------------------
            # 2. Vertex smoothing (sunken vertices / surface noise)
            # ------------------------------------------------------------------
            if props.pre_smooth_iterations > 0:
                bpy.ops.mesh.vertices_smooth(
                    repeat=props.pre_smooth_iterations,
                    factor=props.pre_smooth_factor,
                    wait_for_input=False
                )

            # ------------------------------------------------------------------
            # 3. Despiker - passes, lerp strength and threshold all exposed
            # ------------------------------------------------------------------
            if props.pre_despike_threshold > 0.0:
                bm = bmesh.from_edit_mesh(obj.data)

                for _ in range(props.pre_despike_passes):
                    for v in bm.verts:
                        # Skip boundary verts (correct) and isolated verts (fix)
                        if v.is_boundary or not v.link_edges:
                            continue

                        neighbors = [e.other_vert(v) for e in v.link_edges]
                        avg_loc = sum(
                            (nv.co for nv in neighbors), mathutils.Vector()
                        ) / len(neighbors)

                        if (v.co - avg_loc).length > props.pre_despike_threshold:
                            v.co = v.co.lerp(avg_loc, props.pre_despike_lerp)

                bmesh.update_edit_mesh(obj.data)

            bpy.ops.object.mode_set(mode='OBJECT')

            # Recalculate normals for correct shading
            bpy.ops.object.shade_smooth()

        self.report({'INFO'}, "Pre-Processing Complete! Mesh is clean.")
        return {'FINISHED'}
