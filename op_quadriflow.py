import bpy
from bpy.types import Operator

try:
    from . import mesh_health
except ImportError:
    import mesh_health


def _triangle_equivalent_count(mesh):
    return sum(max(1, len(poly.vertices) - 2) for poly in mesh.polygons)


def _mesh_surface_area(mesh):
    return sum(float(poly.area) for poly in mesh.polygons)


def _resolve_target_faces(props, current_vertices, current_tris, total_area_m2):
    current_vertices = max(1, int(current_vertices))
    current_tris = max(1, int(current_tris))
    mode = getattr(props, "quadriflow_target_mode", "QUAD_COUNT")

    if mode == "RATIO":
        ratio = min(max(float(props.quadriflow_target_ratio), 0.001), 1.0)
        target_tris = max(4, int(round(current_tris * ratio)))
        return max(4, int(round(target_tris / 2.0)))

    if mode == "DENSITY":
        area_for_calc = total_area_m2 * 10000.0 if props.quadriflow_density_unit == "CM2" else total_area_m2
        density = max(0.0001, float(props.quadriflow_target_density))
        target_tris = max(4, int(round(area_for_calc * density))) if area_for_calc > 0.0 else current_tris
        return max(4, int(round(target_tris / 2.0)))

    return max(4, int(props.target_quad_count))


def _quadriflow_result_looks_unchanged(before_vertices, before_faces, after_vertices, after_faces):
    return (
        int(before_vertices) == int(after_vertices) and
        int(before_faces) == int(after_faces)
    )


def _target_delta_requires_change(before_faces, target_faces):
    before_faces = max(1, int(before_faces))
    target_faces = max(1, int(target_faces))
    return abs(target_faces - before_faces) > max(8, int(round(before_faces * 0.02)))


def _quadriflow_diagnostic_summary(report):
    diagnostics = []
    if int(getattr(report, "face_count", 0)) <= 0:
        diagnostics.append("mesh has no valid faces")
    if int(getattr(report, "degenerate_faces", 0)) > 0:
        diagnostics.append("degenerate faces detected")
    if int(getattr(report, "loose_edges", 0)) > 0:
        diagnostics.append("loose edges detected")
    if int(getattr(report, "loose_vertices", 0)) > 0:
        diagnostics.append("loose vertices detected")
    if int(getattr(report, "non_manifold_edges", 0)) > 0:
        diagnostics.append("non-manifold edges detected")
    if int(getattr(report, "boundary_edges", 0)) > 0:
        diagnostics.append("open boundary edges detected")
    return ", ".join(diagnostics)


def _quadriflow_failure_message(base_error, report):
    base_error = str(base_error).strip()
    diagnostics = _quadriflow_diagnostic_summary(report)
    if diagnostics:
        if base_error:
            return f"{base_error} Likely mesh issues: {diagnostics}."
        return f"Likely mesh issues: {diagnostics}."
    return base_error


def _capture_source_state(context, obj):
    return {
        "hidden": obj.hide_get(),
        "selected": obj.select_get(),
        "active": context.view_layer.objects.active is obj,
    }


def _restore_source_state(context, obj, state):
    obj.hide_set(state["hidden"])
    obj.select_set(state["selected"])
    if state["active"] or state["selected"]:
        context.view_layer.objects.active = obj


class UAV_OT_quadriflow(Operator):
    bl_idname = "uav.quadriflow_retopo"
    bl_label = "Run QuadriFlow"
    
    # --- O TOOLTIP DO BOT-O FICA AQUI ---
    bl_description = "Executes native QuadriFlow to generate an all-quad mesh inside a new collection. Ideal for organic terrain"
    
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        # S- permite clicar no bot-o se houver pelo menos uma malha selecionada
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props = context.scene.uav_props
        
        objects_to_process = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not objects_to_process:
            self.report({'WARNING'}, "No valid meshes selected.")
            return {'CANCELLED'}
            
        # ==================================================================
        # 1. CRIAR A NOVA COLE--O PARA O QUADRIFLOW
        # ==================================================================
        base_name = objects_to_process[0].name.replace("_QEM", "")
        qflow_col_name = f"{base_name}_QuadriFlow"
        
        if qflow_col_name not in bpy.data.collections:
            qflow_col = bpy.data.collections.new(qflow_col_name)
            context.scene.collection.children.link(qflow_col)
        else:
            qflow_col = bpy.data.collections[qflow_col_name]
            
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        created_objects = []
        restored_sources = []

        self.report({'INFO'}, "Starting QuadriFlow. Blender may freeze for a moment...")

        # ==================================================================
        # 2. PROCESSAR CADA CHUNK SELECIONADO
        # ==================================================================
        for obj in objects_to_process:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            source_state = _capture_source_state(context, obj)
            precheck_report = mesh_health.analyze_mesh_health(obj)
            
            bpy.ops.object.duplicate()
            new_obj = context.active_object
            
            clean_name = obj.name.replace("_QEM", "")
            new_obj.name = f"{clean_name}_QuadriFlow"

            before_faces = len(new_obj.data.polygons)
            before_vertices = len(new_obj.data.vertices)
            target_quads = _resolve_target_faces(
                props,
                current_vertices=before_vertices,
                current_tris=_triangle_equivalent_count(new_obj.data),
                total_area_m2=_mesh_surface_area(new_obj.data),
            )
            
            obj.hide_set(True)
            obj.select_set(False)
            
            for coll in new_obj.users_collection:
                coll.objects.unlink(new_obj)
            qflow_col.objects.link(new_obj)
            
            # ==================================================================
            # 3. EXECU--O DO QUADRIFLOW (Corrigido para o Blender 4.4)
            # ==================================================================
            try:
                self.report(
                    {'INFO'},
                    f"QuadriFlow target for '{obj.name}': {target_quads} quads "
                    f"(mode: {props.quadriflow_target_mode}).",
                )
                bpy.ops.object.quadriflow_remesh(
                    mode='FACES',
                    target_faces=target_quads,
                    use_mesh_symmetry=False,
                    use_preserve_sharp=True,
                    use_preserve_boundary=True,
                    smooth_normals=True
                )

                after_faces = len(new_obj.data.polygons)
                after_vertices = len(new_obj.data.vertices)
                if (
                    _quadriflow_result_looks_unchanged(
                        before_vertices=before_vertices,
                        before_faces=before_faces,
                        after_vertices=after_vertices,
                        after_faces=after_faces,
                    )
                    and _target_delta_requires_change(before_faces, target_quads)
                ):
                    raise RuntimeError(
                        f"QuadriFlow finished on '{new_obj.name}' without changing topology "
                        f"({before_faces} -> {after_faces} faces, target {target_quads})."
                    )

                created_objects.append(context.active_object)
                
            except RuntimeError as e:
                detailed_error = _quadriflow_failure_message(e, precheck_report)
                self.report({'ERROR'}, f"QuadriFlow failed on {new_obj.name}: {detailed_error}")
                print(f"QuadriFlow Error: {detailed_error}")
                bpy.data.objects.remove(new_obj, do_unlink=True)
                _restore_source_state(context, obj, source_state)
                restored_sources.append(obj)

        # ==================================================================
        # 4. LIMPEZA FINAL E SELE--O
        # ==================================================================
        bpy.ops.object.select_all(action='DESELECT')
        for created_obj in created_objects:
            if created_obj:
                created_obj.select_set(True)
        for source_obj in restored_sources:
            if source_obj:
                source_obj.select_set(True)
                
        if created_objects:
            context.view_layer.objects.active = created_objects[0]
            self.report({'INFO'}, f"QuadriFlow Completed Successfully! Generated {len(created_objects)} quad meshes in '{qflow_col_name}'.")
            return {'FINISHED'}
        elif restored_sources:
            context.view_layer.objects.active = restored_sources[0]
            self.report({'WARNING'}, "QuadriFlow failed to generate any meshes.")
            return {'CANCELLED'}
        else:
            self.report({'WARNING'}, "QuadriFlow failed to generate any meshes.")
            return {'CANCELLED'}
