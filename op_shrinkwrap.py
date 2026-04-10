import bpy
import bmesh
import mathutils
from bpy.types import Operator

class UAV_OT_shrinkwrap_retopo(Operator):
    bl_idname = "uav.shrinkwrap_retopo"
    bl_label = "Run Grid Projection"
    bl_description = "Projects a top-down Z-axis grid and automatically deletes excess geometry that misses the terrain"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props      = context.scene.uav_props
        resolution = props.grid_resolution

        # Formerly hardcoded values - now driven by properties
        spawn_offset   = props.grid_spawn_offset    # was 10.0
        miss_tolerance = props.grid_miss_tolerance  # was 1.0
        safety_margin  = props.grid_safety_margin   # was 1.02

        target_obj = context.active_object
        if target_obj.type != 'MESH':
            self.report({'WARNING'}, "Active object must be a mesh.")
            return {'CANCELLED'}

        # 1. Safe collection
        base_name  = target_obj.name.replace("_QEM", "")
        sw_col_name = f"{base_name}_GridProjected"

        if sw_col_name not in bpy.data.collections:
            sw_col = bpy.data.collections.new(sw_col_name)
            context.scene.collection.children.link(sw_col)
        else:
            sw_col = bpy.data.collections[sw_col_name]

        # 2. Bounding box
        bbox     = [target_obj.matrix_world @ mathutils.Vector(c) for c in target_obj.bound_box]
        x_coords = [v.x for v in bbox]
        y_coords = [v.y for v in bbox]
        z_coords = [v.z for v in bbox]

        size_x = max(x_coords) - min(x_coords)
        size_y = max(y_coords) - min(y_coords)
        max_z  = max(z_coords)

        # Spawn height: configurable offset above the highest peak
        spawn_height = max_z + spawn_offset

        max_size = max(size_x, size_y)
        subdiv_x = max(2, int((size_x / max_size) * resolution))
        subdiv_y = max(2, int((size_y / max_size) * resolution))

        loc_x = (max(x_coords) + min(x_coords)) / 2
        loc_y = (max(y_coords) + min(y_coords)) / 2

        # 3. Create projection grid
        bpy.ops.mesh.primitive_grid_add(
            x_subdivisions=subdiv_x,
            y_subdivisions=subdiv_y,
            size=1,
            location=(loc_x, loc_y, spawn_height)
        )
        grid_obj      = context.active_object
        grid_obj.name = f"{base_name}_GridProjected"

        # Safety margin is now configurable (default 1.02 = 2% larger than bbox)
        grid_obj.scale = (size_x * safety_margin, size_y * safety_margin, 1)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        for coll in grid_obj.users_collection:
            coll.objects.unlink(grid_obj)
        sw_col.objects.link(grid_obj)

        # 4. Shrinkwrap Z-Project
        sw_mod                    = grid_obj.modifiers.new(name="Z_Projection", type='SHRINKWRAP')
        sw_mod.wrap_method        = 'PROJECT'
        sw_mod.use_project_z      = True
        sw_mod.use_negative_direction = True
        sw_mod.use_positive_direction = False
        sw_mod.target             = target_obj
        bpy.ops.object.modifier_apply(modifier=sw_mod.name)

        # 5. Delete vertices that missed the terrain
        # Threshold is now configurable instead of hardcoded 1.0 m
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(grid_obj.data)

        verts_to_delete = [
            v for v in bm.verts
            if (grid_obj.matrix_world @ v.co).z > (spawn_height - miss_tolerance)
        ]
        bmesh.ops.delete(bm, geom=verts_to_delete, context='VERTS')

        bmesh.update_edit_mesh(grid_obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')

        # 6. Smooth shading
        bpy.ops.object.shade_smooth()

        target_obj.hide_set(True)
        target_obj.select_set(False)

        self.report(
            {'INFO'},
            f"Grid Projection complete! Removed {len(verts_to_delete)} missed vertices "
            f"(spawn +{spawn_offset}m, tolerance {miss_tolerance}m, margin ×{safety_margin})."
        )
        return {'FINISHED'}
