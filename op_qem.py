import time

import bpy
import bmesh
import numpy as np
from bpy.types import Operator

from .qem_core import MeshQEM


ENGINE_SUFFIXES = {
    'FAST_DECIMATE': 'FASTDECIMATE',
    'TRUE_QEM': 'TRUEQEM',
    'EDGE_LENGTH': 'EDGELENGTH',
}

ENGINE_LABELS = {
    'FAST_DECIMATE': 'Fast Decimate',
    'TRUE_QEM': 'True QEM',
    'EDGE_LENGTH': 'Edge Length',
}


def _collect_mesh_seam_edges(mesh):
    seam_edges = set()
    for edge in mesh.edges:
        if edge.use_seam:
            seam_edges.add(tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))))
    return seam_edges


def _capture_mesh_face_data(mesh):
    uv_layers = {}
    for uv_layer in mesh.uv_layers:
        uv_layers[uv_layer.name] = [
            [tuple(uv_layer.data[loop_index].uv) for loop_index in poly.loop_indices]
            for poly in mesh.polygons
        ]

    active_uv_name = None
    if mesh.uv_layers.active is not None:
        active_uv_name = mesh.uv_layers.active.name

    render_uv_name = None
    for uv_layer in mesh.uv_layers:
        if getattr(uv_layer, "active_render", False):
            render_uv_name = uv_layer.name
            break

    return {
        "uv_layers": uv_layers,
        "active_uv_name": active_uv_name,
        "render_uv_name": render_uv_name,
        "material_indices": [poly.material_index for poly in mesh.polygons],
        "smooth_flags": [poly.use_smooth for poly in mesh.polygons],
    }


def _restore_mesh_face_data(mesh, face_sources, mesh_face_data):
    if not mesh_face_data or face_sources is None:
        return

    uv_layers_data = mesh_face_data.get("uv_layers", {})
    uv_layers = {}
    for layer_name in uv_layers_data:
        uv_layer = mesh.uv_layers.get(layer_name)
        if uv_layer is None:
            uv_layer = mesh.uv_layers.new(name=layer_name)
        uv_layers[layer_name] = uv_layer

    material_indices = mesh_face_data.get("material_indices", [])
    smooth_flags = mesh_face_data.get("smooth_flags", [])

    for poly_index, poly in enumerate(mesh.polygons):
        if poly_index >= len(face_sources):
            break
        source_face_index = int(face_sources[poly_index])
        if 0 <= source_face_index < len(material_indices):
            poly.material_index = material_indices[source_face_index]
        if 0 <= source_face_index < len(smooth_flags):
            poly.use_smooth = smooth_flags[source_face_index]

        for layer_name, uv_source_faces in uv_layers_data.items():
            if not (0 <= source_face_index < len(uv_source_faces)):
                continue
            src_uvs = uv_source_faces[source_face_index]
            uv_layer = uv_layers[layer_name]
            for loop_offset, loop_index in enumerate(poly.loop_indices):
                if loop_offset >= len(src_uvs):
                    break
                uv_layer.data[loop_index].uv = src_uvs[loop_offset]

    active_uv_name = mesh_face_data.get("active_uv_name")
    if active_uv_name:
        active_layer = mesh.uv_layers.get(active_uv_name)
        if active_layer is not None:
            try:
                mesh.uv_layers.active = active_layer
            except Exception:
                pass

    render_uv_name = mesh_face_data.get("render_uv_name")
    if render_uv_name:
        render_layer = mesh.uv_layers.get(render_uv_name)
        if render_layer is not None:
            try:
                render_layer.active_render = True
            except Exception:
                pass


def _duplicate_mesh_object(source_obj, target_name, target_collection):
    """Create a single-user object+mesh copy inside the target collection."""
    new_obj = source_obj.copy()
    if source_obj.data is not None:
        new_obj.data = source_obj.data.copy()
        new_obj.data.name = target_name
    new_obj.name = target_name
    target_collection.objects.link(new_obj)
    return new_obj


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
        self.start_time = time.perf_counter()

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
                elapsed = time.perf_counter() - self.start_time
                self.report(
                    {'INFO'},
                    f"QEM complete: {self.current_task_idx} object(s) processed, "
                    f"{len(self.created_qem_chunks)} output mesh(es) in '{self.qem_col_name}' "
                    f"in {elapsed:.2f}s.",
                )
                return {'FINISHED'}

        elif event.type == 'ESC':
            self._finish_ui(context)
            self.report({'WARNING'}, "QEM cancelled.")
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

        temp_name = f"{original_obj.name}_QEM_TMP"
        new_obj = _duplicate_mesh_object(original_obj, temp_name, self.qem_col)
        object_start = time.perf_counter()
        try:
            self._pre_cleanup(new_obj)

            target_v, current_v, current_tris = self._resolve_target_counts(new_obj)
            if target_v >= current_v:
                bpy.data.objects.remove(new_obj, do_unlink=True)
                self.report({'INFO'}, f"QEM skipped '{original_obj.name}' because the target is already reached.")
                return

            if self.props.qem_engine == 'FAST_DECIMATE':
                used_engine = self._run_fast_decimate(new_obj, target_v, current_v, current_tris)
            else:
                used_engine = self._run_true_qem(context, new_obj, target_v)

            self._post_cleanup(new_obj)
            self._fix_normals_zup(new_obj)
        except Exception:
            if new_obj.name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[new_obj.name], do_unlink=True)
            context.view_layer.objects.active = original_obj
            original_obj.select_set(True)
            raise

        suffix = ENGINE_SUFFIXES.get(used_engine, used_engine)
        final_name = f"{original_obj.name}_{suffix}"
        new_obj.name = final_name
        if new_obj.data is not None:
            new_obj.data.name = final_name

        original_obj.hide_set(True)
        original_obj.select_set(False)
        self.created_qem_chunks.append(new_obj)

        elapsed = time.perf_counter() - object_start
        engine_label = ENGINE_LABELS.get(used_engine, used_engine)
        self.report({'INFO'}, f"{engine_label} finished on '{original_obj.name}' in {elapsed:.2f}s.")

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
            avg_z = sum(face.normal.z for face in bm_n.faces) / len(bm_n.faces)
            if avg_z < 0:
                bmesh.ops.reverse_faces(bm_n, faces=bm_n.faces)
        bm_n.to_mesh(obj.data)
        bm_n.free()
        obj.data.update()

    def _resolve_target_counts(self, obj):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        total_area_m2 = sum(face.calc_area() for face in bm.faces)
        current_tris = sum(max(1, len(face.verts) - 2) for face in bm.faces)
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
            if self.props.qem_preserve_seams:
                mod.delimit = {'SEAM'}
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
        return 'FAST_DECIMATE'

    def _run_true_qem(self, context, obj, target_v):
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')

        verts = np.array([vertex.co[:] for vertex in obj.data.vertices], dtype=np.float64)
        faces = np.array([polygon.vertices[:] for polygon in obj.data.polygons], dtype=np.int32)
        if len(faces) == 0:
            return self.props.qem_engine

        mesh_face_data = _capture_mesh_face_data(obj.data)
        seam_edges = _collect_mesh_seam_edges(obj.data) if self.props.qem_preserve_seams else set()
        mesh = MeshQEM(verts, faces, protected_edges=seam_edges)
        if mesh.has_boundary() and self.props.qem_boundary_action == 'CANCEL':
            raise RuntimeError("True QEM found open boundaries. Switch boundary handling to Fallback or use Fast Decimate.")
        if mesh.has_boundary() and self.props.qem_boundary_action == 'FALLBACK':
            current_v = len(verts)
            return self._run_fast_decimate(obj, target_v, current_v, len(faces))

        if self.props.qem_engine == 'EDGE_LENGTH':
            simp = mesh.edge_based_simplification(
                target_v=target_v,
                valence_aware=self.props.qem_valence_aware,
                preserve_boundary=True,
            )
            used_engine = 'EDGE_LENGTH'
        else:
            simp = mesh.simplification(
                target_v=target_v,
                valence_aware=self.props.qem_valence_aware,
                midpoint=self.props.qem_midpoint_fallback,
                preserve_boundary=True,
            )
            used_engine = 'TRUE_QEM'

        self._replace_mesh_geometry(
            context,
            obj,
            simp.vs,
            simp.faces,
            seam_edges=getattr(simp, 'protected_edges', set()),
            face_sources=getattr(simp, 'face_sources', None),
            mesh_face_data=mesh_face_data,
        )
        return used_engine

    def _replace_mesh_geometry(self, context, obj, vertices, faces, seam_edges=None, face_sources=None, mesh_face_data=None):
        mesh = obj.data
        seam_edges = seam_edges or set()
        mesh.clear_geometry()
        mesh.from_pydata([tuple(map(float, vert)) for vert in vertices], [], [tuple(map(int, face)) for face in faces])
        mesh.update()
        _restore_mesh_face_data(mesh, face_sources, mesh_face_data)
        for edge in mesh.edges:
            edge_key = tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1]))))
            edge.use_seam = edge_key in seam_edges
        mesh.update()
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')
