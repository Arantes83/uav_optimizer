import bpy
import bmesh
import numpy as np
from bpy.types import Operator

from .qem_core import MeshQEM


class UAV_OT_qem_simplify(Operator):
    bl_idname = "uav.qem_simplify"
    bl_label = "Run QEM Simplification"
    bl_description = (
        "Simplify selected meshes using either Blender Decimate (fast fallback), "
        "a true Quadric Error Metrics solver, or an edge-length isotropic variant"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def invoke(self, context, event):
        self.props = context.scene.uav_props
        self.objects_to_process = [obj for obj in context.selected_objects if obj.type == 'MESH']
        self.total_tasks = len(self.objects_to_process)
        self.current_task_idx = 0
        self.created_qem_chunks = []
        self.wm = context.window_manager

        suffix = self.props.qem_collection_suffix.strip() or "QEM_Simplified"
        if self.total_tasks == 1:
            base_name = self.objects_to_process[0].name.split('_Chunk_')[0]
        else:
            base_name = self.objects_to_process[0].name.split('_Chunk_')[0].rstrip('.0123456789')
        self.qem_col_name = f"{base_name}_{suffix}"

        if self.qem_col_name not in bpy.data.collections:
            self.qem_col = bpy.data.collections.new(self.qem_col_name)
            context.scene.collection.children.link(self.qem_col)
        else:
            self.qem_col = bpy.data.collections[self.qem_col_name]

        self.wm.progress_begin(0, max(1, self.total_tasks))
        context.window.cursor_set('WAIT')

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self._timer = self.wm.event_timer_add(0.01, window=context.window)
        self.wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            if self.current_task_idx < self.total_tasks:
                original_obj = self.objects_to_process[self.current_task_idx]
                try:
                    self._process_one(context, original_obj)
                    self.current_task_idx += 1
                    self.wm.progress_update(self.current_task_idx)
                    return {'RUNNING_MODAL'}
                except Exception as exc:
                    self._finish_ui(context)
                    self.report({'ERROR'}, f"QEM failed on '{original_obj.name}': {exc}")
                    return {'CANCELLED'}
            else:
                self._finish_ui(context)
                bpy.ops.object.select_all(action='DESELECT')
                for chunk in self.created_qem_chunks:
                    chunk.select_set(True)
                if self.created_qem_chunks:
                    context.view_layer.objects.active = self.created_qem_chunks[0]
                self.report({'INFO'}, f"QEM complete — {self.current_task_idx} objects → '{self.qem_col_name}'")
                return {'FINISHED'}

        elif event.type == 'ESC':
            self._finish_ui(context)
            self.report({'WARNING'}, "QEM Cancelled.")
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def _finish_ui(self, context):
        self.wm.progress_end()
        context.window.cursor_set('DEFAULT')
        if hasattr(self, '_timer'):
            self.wm.event_timer_remove(self._timer)

    def _process_one(self, context, original_obj):
        bpy.ops.object.select_all(action='DESELECT')
        original_obj.select_set(True)
        context.view_layer.objects.active = original_obj
        bpy.ops.object.duplicate()
        new_obj = context.active_object
        new_obj.name = f"{original_obj.name}_QEM"
        new_obj_name = new_obj.name
        try:
            self._pre_cleanup(new_obj)

            target_v, current_v, current_tris = self._resolve_target_counts(new_obj)
            if target_v >= current_v:
                bpy.data.objects.remove(new_obj, do_unlink=True)
                self.report({'INFO'}, f"QEM skipped '{original_obj.name}' (target already reached).")
                return

            engine = self.props.qem_engine
            if engine == 'FAST_DECIMATE':
                self._run_fast_decimate(new_obj, target_v, current_v, current_tris)
            else:
                self._run_true_qem(context, new_obj, target_v)

            self._post_cleanup(new_obj)
            self._fix_normals_zup(new_obj)
        except Exception:
            if new_obj_name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[new_obj_name], do_unlink=True)
            context.view_layer.objects.active = original_obj
            original_obj.select_set(True)
            raise

        original_obj.hide_set(True)
        original_obj.select_set(False)
        for coll in list(new_obj.users_collection):
            coll.objects.unlink(new_obj)
        self.qem_col.objects.link(new_obj)
        self.created_qem_chunks.append(new_obj)

    def _pre_cleanup(self, obj):
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=self.props.qem_merge_distance)
        bpy.ops.mesh.dissolve_degenerate(threshold=self.props.qem_degenerate_threshold)
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
        bpy.ops.object.mode_set(mode='OBJECT')

    def _post_cleanup(self, obj):
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=self.props.qem_post_merge_distance)
        bpy.ops.mesh.dissolve_degenerate(threshold=self.props.qem_sliver_filter)
        bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
        bpy.ops.object.mode_set(mode='OBJECT')

    def _fix_normals_zup(self, obj):
        bm_n = bmesh.new()
        bm_n.from_mesh(obj.data)
        bm_n.normal_update()
        if bm_n.faces:
            avg_z = sum(f.normal.z for f in bm_n.faces) / len(bm_n.faces)
            if avg_z < 0:
                bmesh.ops.reverse_faces(bm_n, faces=bm_n.faces)
        bm_n.to_mesh(obj.data)
        bm_n.free()
        obj.data.update()

    def _resolve_target_counts(self, obj):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        total_area_m2 = sum(f.calc_area() for f in bm.faces)
        current_tris = sum(max(1, len(f.verts) - 2) for f in bm.faces)
        current_v = len(bm.verts)
        bm.free()

        mode = self.props.qem_target_mode
        if mode == 'VERTEX_COUNT':
            target_v = int(max(4, self.props.qem_target_vertex_count))
        elif mode == 'RATIO':
            target_v = int(max(4, round(current_v * self.props.qem_target_ratio)))
        else:
            area_for_calc = total_area_m2 * 10000.0 if self.props.qem_density_unit == 'CM2' else total_area_m2
            if current_tris > 0 and area_for_calc > 0:
                target_tris = area_for_calc * self.props.qem_target_density
                ratio = min(max(target_tris / current_tris, 0.0), 1.0)
            else:
                ratio = 1.0
            target_v = int(max(4, round(current_v * ratio)))
        target_v = min(target_v, current_v)
        return target_v, current_v, current_tris

    def _run_fast_decimate(self, obj, target_v, current_v, _current_tris):
        ratio = min(max(target_v / max(1, current_v), 0.0), 1.0)
        if ratio < 0.99:
            mod = obj.modifiers.new(name="QEM_Decimate", type='DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = ratio
            mod.use_collapse_triangulate = True
            mod.delimit = {'SEAM'}
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

    def _run_true_qem(self, context, obj, target_v):
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')

        verts = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float64)
        faces = np.array([p.vertices[:] for p in obj.data.polygons], dtype=np.int32)
        if len(faces) == 0:
            return

        mesh = MeshQEM(verts, faces)
        if mesh.has_boundary() and self.props.qem_boundary_action == 'CANCEL':
            raise RuntimeError("True QEM found open boundaries. Switch boundary handling to Fallback or use Fast Decimate.")
        if mesh.has_boundary() and self.props.qem_boundary_action == 'FALLBACK':
            current_v = len(verts)
            self._run_fast_decimate(obj, target_v, current_v, len(faces))
            return

        if self.props.qem_engine == 'EDGE_LENGTH':
            simp = mesh.edge_based_simplification(
                target_v=target_v,
                valence_aware=self.props.qem_valence_aware,
                preserve_boundary=True,
            )
        else:
            simp = mesh.simplification(
                target_v=target_v,
                valence_aware=self.props.qem_valence_aware,
                midpoint=self.props.qem_midpoint_fallback,
                preserve_boundary=True,
            )

        self._replace_mesh_geometry(context, obj, simp.vs, simp.faces)

    def _replace_mesh_geometry(self, context, obj, vertices, faces):
        mesh = obj.data
        mesh.clear_geometry()
        mesh.from_pydata([tuple(map(float, v)) for v in vertices], [], [tuple(map(int, f)) for f in faces])
        mesh.update()
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')
