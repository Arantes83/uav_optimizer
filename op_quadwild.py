"""
op_quadwild.py — QuadWild Retopology Operator
==============================================
Integrates the QuadWild algorithm (lib_quadwild.dll + lib_quadpatches.dll)
into the MeshForge UAV pipeline.

Pipeline identical to QRemeshify:
  BMesh → OBJ (disk) → remeshAndField → trace → quadrangulate → OBJ → Blender mesh

All DLL calls go through quadwild_lib.Quadwild, which is the same wrapper
extracted from QRemeshify. No Python re-implementation of the algorithm.
"""

import os
import math

import bpy
import bmesh
import mathutils
from bpy.types import Operator

from .quadwild_lib import Quadwild, QWException
from .quadwild_util import bisect, exporter, importer


QUADWILD_DEFAULT_CALLBACK_TIMES = [3.0, 5.0, 10.0, 20.0, 30.0, 60.0, 90.0, 120.0]
QUADWILD_DEFAULT_CALLBACK_GAPS = [0.005, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.3]
QUADWILD_TARGET_WARNING_DEVIATION = 0.25
QUADWILD_NATURAL_OUTPUT_RATIO = 0.3518
QUADWILD_SCALE_TARGET_EXPONENT = 1.2915


def _triangle_equivalent_count(mesh):
    return sum(max(1, len(poly.vertices) - 2) for poly in mesh.polygons)


def _mesh_face_breakdown(mesh):
    faces = len(mesh.polygons)
    quads = sum(1 for poly in mesh.polygons if len(poly.vertices) == 4)
    triangles = sum(1 for poly in mesh.polygons if len(poly.vertices) == 3)
    ngons = faces - quads - triangles
    return faces, quads, triangles, ngons


class UAV_OT_quadwild(Operator):
    bl_idname  = "uav.quadwild_retopo"
    bl_label   = "Run QuadWild"
    bl_description = (
        "Feature-preserving quad retopology using the QuadWild algorithm "
        "(ILP + cross-field tracing). Best for architecture and sharp terrain features"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.selected_objects and
            any(obj.type == 'MESH' for obj in context.selected_objects)
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def execute(self, context):
        props    = context.scene.uav_props
        qw_props = context.scene.uav_quadwild_props   # QuadWild-specific props

        objects = [o for o in context.selected_objects if o.type == 'MESH']
        if not objects:
            self.report({'WARNING'}, "No valid meshes selected.")
            return {'CANCELLED'}

        # QuadWild processes one object at a time; warn if many are selected
        if len(objects) > 1:
            self.report(
                {'INFO'},
                f"Multiple objects selected — processing only '{objects[0].name}'. "
                "Run again for each additional object."
            )

        obj = objects[0]

        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if len(obj.data.polygons) == 0:
            self.report({'ERROR'}, "Mesh has 0 faces.")
            return {'CANCELLED'}

        # ------------------------------------------------------------------
        # 1. Collection setup
        # ------------------------------------------------------------------
        base_name  = obj.name.replace("_QEM", "").replace("_Voxel", "")
        col_name   = f"{base_name}_QuadWild"
        if col_name not in bpy.data.collections:
            qw_col = bpy.data.collections.new(col_name)
            context.scene.collection.children.link(qw_col)
        else:
            qw_col = bpy.data.collections[col_name]

        # ------------------------------------------------------------------
        # 2. Temporary OBJ path (bpy.app.tempdir survives the session)
        # ------------------------------------------------------------------
        safe_name    = "".join(c if c not in r'\/:*?<>|' else "_" for c in obj.name).strip()
        mesh_filepath = os.path.join(bpy.app.tempdir, f"{safe_name}_qw.obj")

        original_location = obj.location.copy()
        qw = Quadwild(mesh_filepath)

        bm = None
        evaluated_obj = None
        target_info = None

        try:
            # ----------------------------------------------------------
            # 3. Build BMesh (evaluated - modifiers + shape keys applied)
            # ----------------------------------------------------------
            if not qw_props.use_cache:
                depsgraph    = context.evaluated_depsgraph_get()
                evaluated_obj = obj.evaluated_get(depsgraph)
                mesh          = evaluated_obj.to_mesh()

                bm = bmesh.new()
                bm.from_mesh(mesh)

                # Apply rotation + scale (NOT location - restored at the end)
                if evaluated_obj.rotation_mode == 'QUATERNION':
                    matrix = mathutils.Matrix.LocRotScale(
                        None, evaluated_obj.rotation_quaternion, evaluated_obj.scale)
                else:
                    matrix = mathutils.Matrix.LocRotScale(
                        None, evaluated_obj.rotation_euler, evaluated_obj.scale)
                bmesh.ops.transform(bm, matrix=matrix, verts=bm.verts)

                # -- Symmetry bisect ----------------------------------
                if qw_props.symmetry_x or qw_props.symmetry_y or qw_props.symmetry_z:
                    bisect.bisect_on_axes(
                        bm,
                        qw_props.symmetry_x,
                        qw_props.symmetry_y,
                        qw_props.symmetry_z,
                    )

                # -- Sharp edge detection -----------------------------
                if qw_props.enable_sharp:
                    face_set_layer = bm.faces.layers.int.get('.sculpt_face_set')
                    bm.edges.ensure_lookup_table()
                    for edge in bm.edges:
                        angle_deg = math.degrees(edge.calc_face_angle(0))
                        is_sharp = angle_deg > qw_props.sharp_angle

                        is_material_boundary = (
                            len(edge.link_faces) > 1 and
                            edge.link_faces[0].material_index !=
                            edge.link_faces[1].material_index
                        )
                        is_face_set_boundary = (
                            face_set_layer is not None and
                            len(edge.link_faces) > 1 and
                            edge.link_faces[0][face_set_layer] !=
                            edge.link_faces[1][face_set_layer]
                        )

                        if (is_sharp or edge.is_boundary or edge.seam or
                                is_material_boundary or is_face_set_boundary):
                            edge.smooth = False

                # -- Triangulate --------------------------------------
                bmesh.ops.triangulate(
                    bm, faces=bm.faces,
                    quad_method='SHORT_EDGE', ngon_method='BEAUTY'
                )

                target_info = self._resolve_target_info(bm, qw_props)

                # -- Export OBJ ---------------------------------------
                exporter.export_mesh(bm, mesh_filepath)

                if qw_props.enable_sharp:
                    n_sharp = exporter.export_sharp_features(
                        bm, qw.sharp_path, qw_props.sharp_angle
                    )
                    self.report({'INFO'}, f"QuadWild: {n_sharp} sharp edges detected.")

                # -- remeshAndField -----------------------------------
                self.report({'INFO'}, "QuadWild: running remesh + cross-field…")
                qw.remeshAndField(
                    remesh      = qw_props.enable_preprocess,
                    enableSharp = qw_props.enable_sharp,
                    sharpAngle  = qw_props.sharp_angle,
                )

                if qw_props.debug:
                    self._import_debug(context, obj.name, qw.remeshed_path, "remeshAndField")

                # -- Trace --------------------------------------------
                self.report({'INFO'}, "QuadWild: tracing patch layout…")
                qw.trace()

                if qw_props.debug:
                    self._import_debug(context, obj.name, qw.traced_path, "trace")

            # ----------------------------------------------------------
            # 4. Quadrangulate (always runs - also when use_cache=True)
            # ----------------------------------------------------------
            if target_info is None:
                target_info = self._resolve_cached_target_info(obj, qw_props)

            scale_fact = target_info["scale_fact"] if target_info else qw_props.scale_fact
            self.report({'INFO'}, "QuadWild: quadrangulating (ILP)… this may take a while.")
            qw.quadrangulate(
                enableSmoothing                  = qw_props.enable_smoothing,
                scaleFact                        = scale_fact,
                fixedChartClusters               = qw_props.fixed_chart_clusters,
                alpha                            = qw_props.alpha,
                ilpMethod                        = qw_props.ilp_method,
                timeLimit                        = qw_props.time_limit,
                gapLimit                         = qw_props.gap_limit,
                minimumGap                       = qw_props.minimum_gap,
                isometry                         = True,
                regularityQuadrilaterals         = True,
                regularityNonQuadrilaterals      = True,
                regularityNonQuadrilateralsWeight= 0.9,
                alignSingularities               = True,
                alignSingularitiesWeight         = 0.1,
                repeatLosingConstraintsIterations= True,
                repeatLosingConstraintsQuads     = False,
                repeatLosingConstraintsNonQuads  = False,
                repeatLosingConstraintsAlign     = True,
                hardParityConstraint             = True,
                flowConfig                       = qw_props.flow_config,
                satsumaConfig                    = qw_props.satsuma_config,
                callbackTimeLimit                = QUADWILD_DEFAULT_CALLBACK_TIMES,
                callbackGapLimit                 = QUADWILD_DEFAULT_CALLBACK_GAPS,
            )

            if qw_props.debug and qw_props.enable_smoothing:
                self._import_debug(context, obj.name, qw.output_path, "quadrangulate")

            # ----------------------------------------------------------
            # 5. Import final result
            # ----------------------------------------------------------
            final_path = (
                qw.output_smoothed_path if qw_props.enable_smoothing
                else qw.output_path
            )
            final_mesh = importer.import_mesh(final_path)
            final_obj  = bpy.data.objects.new(f"{base_name}_QuadWild", final_mesh)
            context.collection.objects.link(final_obj)
            self._report_target_result(final_obj, target_info)

            # Move to dedicated collection
            context.collection.objects.unlink(final_obj)
            qw_col.objects.link(final_obj)

            context.view_layer.objects.active = final_obj
            final_obj.select_set(True)
            final_obj.location = original_location

            # -- Mirror modifier for symmetry -------------------------
            if qw_props.symmetry_x or qw_props.symmetry_y or qw_props.symmetry_z:
                mirror = final_obj.modifiers.new("Mirror", "MIRROR")
                mirror.use_axis[0]       = qw_props.symmetry_x
                mirror.use_axis[1]       = qw_props.symmetry_y
                mirror.use_axis[2]       = qw_props.symmetry_z
                mirror.use_clip          = True
                mirror.merge_threshold   = 0.001

            # Hide source
            obj.hide_set(True)
            obj.select_set(False)

            self.report(
                {'INFO'},
                f"QuadWild complete! Result in collection '{col_name}'."
            )

        except QWException as e:
            self.report({'ERROR'}, f"QuadWild failed: {e}")
            return {'CANCELLED'}

        finally:
            # Safe cleanup - variables may not exist if error was early
            del qw
            if bm is not None:
                bm.free()
            if evaluated_obj is not None:
                evaluated_obj.to_mesh_clear()

        return {'FINISHED'}

    def _resolve_target_info(self, bm, qw_props):
        bm.verts.ensure_lookup_table()
        current_vertices = len(bm.verts)
        current_tris = sum(max(1, len(face.verts) - 2) for face in bm.faces)
        total_area_m2 = sum(face.calc_area() for face in bm.faces)
        return self._build_target_info(
            qw_props,
            current_vertices=current_vertices,
            current_tris=current_tris,
            total_area_m2=total_area_m2,
            cache_warning=False,
        )

    def _resolve_cached_target_info(self, obj, qw_props):
        mesh = obj.data
        current_vertices = len(mesh.vertices)
        current_tris = _triangle_equivalent_count(mesh)
        total_area_m2 = sum(poly.area for poly in mesh.polygons)
        info = self._build_target_info(
            qw_props,
            current_vertices=current_vertices,
            current_tris=current_tris,
            total_area_m2=total_area_m2,
            cache_warning=True,
        )
        self.report(
            {'WARNING'},
            "QuadWild Use Cache is enabled; target scale was estimated from the active mesh, "
            "but cached trace data may come from older geometry."
        )
        return info

    def _build_target_info(self, qw_props, current_vertices, current_tris, total_area_m2, cache_warning):
        current_vertices = max(1, int(current_vertices))
        current_tris = max(1, int(current_tris))
        mode = qw_props.target_mode

        if mode == 'VERTEX_COUNT':
            requested_value = int(max(4, qw_props.target_vertex_count))
            target_tris = requested_value * 2
            metric_name = "vertices"
            target_metric = requested_value
        elif mode == 'TRIANGLE_COUNT':
            requested_value = int(max(4, qw_props.target_triangle_count))
            target_tris = requested_value
            metric_name = "tri-equivalent"
            target_metric = requested_value
        elif mode == 'DENSITY':
            area_for_calc = total_area_m2 * 10000.0 if qw_props.density_unit == 'CM2' else total_area_m2
            requested_value = max(0.0001, float(qw_props.target_density))
            target_tris = int(max(4, round(area_for_calc * requested_value))) if area_for_calc > 0 else current_tris
            metric_name = "tri-equivalent"
            target_metric = target_tris
        else:
            requested_value = min(max(float(qw_props.target_ratio), 0.001), 1.0)
            target_tris = int(max(4, round(current_tris * requested_value)))
            metric_name = "tri-equivalent"
            target_metric = target_tris

        target_tris = max(4, min(int(target_tris), current_tris * 100))
        # QuadWild does not preserve input density at scaleFact=1.0. Statue
        # calibration points:
        # 103k input, scaleFact=1.1665 -> 29.7k tri-equiv
        # 103k input, scaleFact=1.0905 -> 32.4k tri-equiv
        # These imply a natural scale=1 output near 35.18% of input and a
        # local scale exponent near 1.2915.
        natural_target_tris = max(1, current_tris * QUADWILD_NATURAL_OUTPUT_RATIO)
        scale_fact = (natural_target_tris / max(1, target_tris)) ** (1.0 / QUADWILD_SCALE_TARGET_EXPONENT)
        scale_fact = min(max(scale_fact, 0.01), 10.0)

        return {
            "mode": mode,
            "current_vertices": current_vertices,
            "current_tris": current_tris,
            "target_tris": target_tris,
            "target_metric": target_metric,
            "metric_name": metric_name,
            "scale_fact": scale_fact,
            "scale_exponent": QUADWILD_SCALE_TARGET_EXPONENT,
            "natural_output_ratio": QUADWILD_NATURAL_OUTPUT_RATIO,
            "cache_warning": cache_warning,
        }

    def _report_target_result(self, final_obj, target_info):
        if not target_info:
            return

        final_vertices = len(final_obj.data.vertices)
        final_tris = _triangle_equivalent_count(final_obj.data)
        final_faces, final_quads, final_triangles, final_ngons = _mesh_face_breakdown(final_obj.data)
        if target_info["metric_name"] == "vertices":
            final_metric = final_vertices
        else:
            final_metric = final_tris

        target_metric = max(1, int(target_info["target_metric"]))
        deviation = abs(final_metric - target_metric) / target_metric
        message = (
            f"QuadWild target {target_info['mode']}: requested {target_metric} "
            f"{target_info['metric_name']}, result {final_metric} "
            f"{target_info['metric_name']} ({final_vertices} verts / {final_faces} faces, "
            f"{final_quads} quads / {final_triangles} tris / {final_ngons} ngons, "
            f"{final_tris} tri-equiv), scaleFact {target_info['scale_fact']:.4f}, "
            f"natural {target_info['natural_output_ratio'] * 100:.1f}%, "
            f"exponent {target_info['scale_exponent']:.4f}, deviation {deviation * 100:.1f}%."
        )
        if deviation > QUADWILD_TARGET_WARNING_DEVIATION:
            self.report({'WARNING'}, message)
        else:
            self.report({'INFO'}, message)

    # ------------------------------------------------------------------
    # Helper: import an intermediate OBJ as a hidden debug object
    # ------------------------------------------------------------------
    def _import_debug(self, context, src_name: str, path: str, stage: str):
        try:
            mesh = importer.import_mesh(path)
            dbg  = bpy.data.objects.new(f"{src_name}_{stage}_debug", mesh)
            context.collection.objects.link(dbg)
            dbg.hide_set(True)
        except Exception as e:
            self.report({'WARNING'}, f"Debug import failed ({stage}): {e}")
