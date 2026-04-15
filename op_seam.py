import bpy
import bmesh
import mathutils
from bpy.types import Operator


def _world_plane_to_local(obj, plane_co_world, plane_no_world):
    """Convert a world-space plane into the object's local space."""
    matrix_inv = obj.matrix_world.inverted()
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    plane_co_local = matrix_inv @ mathutils.Vector(plane_co_world)
    plane_no_local = (normal_matrix @ mathutils.Vector(plane_no_world)).normalized()
    return plane_co_local, plane_no_local

class UAV_OT_trace_grid_seams(Operator):
    bl_idname = "uav.trace_grid_seams"
    bl_label = "Trace Grid Seams"
    bl_description = "Slices the mesh mathematically along X/Y/Z to trace grid seams for UV islands without separating the object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def invoke(self, context, event):
        self.props = context.scene.uav_props
        self.rows  = self.props.chunk_rows
        self.cols  = self.props.chunk_cols
        self.levels = self.props.chunk_levels

        self.obj = context.active_object
        self.wm  = context.window_manager

        if context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Bounding box in world space
        bbox     = [self.obj.matrix_world @ mathutils.Vector(c) for c in self.obj.bound_box]
        x_coords = [v.x for v in bbox]
        y_coords = [v.y for v in bbox]
        z_coords = [v.z for v in bbox]

        self.x_min, self.x_max = min(x_coords), max(x_coords)
        self.y_min, self.y_max = min(y_coords), max(y_coords)
        self.z_min, self.z_max = min(z_coords), max(z_coords)

        self.x_step = (self.x_max - self.x_min) / self.cols
        self.y_step = (self.y_max - self.y_min) / self.rows
        self.z_step = (self.z_max - self.z_min) / self.levels

        # Internal grid lines only (cols=4 - 3 cuts on X)
        self.x_cuts = [self.x_min + i * self.x_step for i in range(1, self.cols)]
        self.y_cuts = [self.y_min + j * self.y_step for j in range(1, self.rows)]
        self.z_cuts = [self.z_min + k * self.z_step for k in range(1, self.levels)]

        self.cut_tasks = (
            [((cut_x, 0.0, 0.0), (1.0, 0.0, 0.0)) for cut_x in self.x_cuts]
            + [((0.0, cut_y, 0.0), (0.0, 1.0, 0.0)) for cut_y in self.y_cuts]
            + [((0.0, 0.0, cut_z), (0.0, 0.0, 1.0)) for cut_z in self.z_cuts]
        )

        self.total_tasks    = len(self.cut_tasks)
        self.current_task_idx = 0

        if self.total_tasks == 0:
            self.report({'WARNING'}, "Grid is set to 1x1x1. No seams to trace.")
            return {'CANCELLED'}

        self.wm.progress_begin(0, self.total_tasks)
        context.window.cursor_set('WAIT')

        # Load mesh into BMesh once - avoids repeated full-list reconstruction
        self.bm = bmesh.new()
        self.bm.from_mesh(self.obj.data)

        # Timer interval exposed via property (was hardcoded 0.01 s)
        interval   = self.props.chunk_timer_interval
        self._timer = self.wm.event_timer_add(interval, window=context.window)
        self.wm.modal_handler_add(self)

        self.report({'INFO'}, f"Tracing {self.total_tasks} grid seams in X/Y/Z (interval: {interval:.3f}s)...")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            if self.current_task_idx < self.total_tasks:

                # Rebuild geometry list each cut - necessary because bisect
                # creates new verts/edges/faces that must be included in the
                # next pass. This is unavoidable with bmesh.ops.bisect_plane.
                geom = self.bm.verts[:] + self.bm.edges[:] + self.bm.faces[:]
                plane_co_world, plane_no_world = self.cut_tasks[self.current_task_idx]
                plane_co, plane_no = _world_plane_to_local(
                    self.obj, plane_co_world, plane_no_world
                )
                res = bmesh.ops.bisect_plane(
                    self.bm, geom=geom,
                    plane_co=plane_co, plane_no=plane_no,
                    clear_inner=False, clear_outer=False
                )

                # Mark bisection edges as seams
                for item in res.get('geom_cut', []):
                    if isinstance(item, bmesh.types.BMEdge):
                        item.seam = True

                self.current_task_idx += 1
                self.wm.progress_update(self.current_task_idx)
                return {'RUNNING_MODAL'}

            else:
                return self._finish(context)

        elif event.type == 'ESC':
            # On cancel: still write partial result back so work is not lost
            self.report({'WARNING'}, "Seam Tracing Cancelled — partial seams written back.")
            return self._finish(context, cancelled=True)

        return {'PASS_THROUGH'}

    def _finish(self, context, cancelled=False):
        self.wm.progress_end()
        context.window.cursor_set('DEFAULT')
        self.wm.event_timer_remove(self._timer)

        self.bm.to_mesh(self.obj.data)
        self.bm.free()
        self.obj.data.update()

        if not cancelled:
            self.report({'INFO'}, "Grid Seams successfully traced on the mesh!")
            return {'FINISHED'}
        return {'CANCELLED'}
