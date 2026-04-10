"""
op_quadwild.py — QuadWild Retopology Operator
==============================================
Integrates the QuadWild algorithm (lib_quadwild.dll + lib_quadpatches.dll)
into the UAV Optimizer pipeline.

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
            self.report({'INFO'}, "QuadWild: quadrangulating (ILP)… this may take a while.")
            qw.quadrangulate(
                enableSmoothing                  = qw_props.enable_smoothing,
                scaleFact                        = qw_props.scale_fact,
                fixedChartClusters               = qw_props.fixed_chart_clusters,
                alpha                            = qw_props.alpha,
                ilpMethod                        = qw_props.ilp_method,
                timeLimit                        = qw_props.time_limit,
                gapLimit                         = qw_props.gap_limit,
                minimumGap                       = qw_props.minimum_gap,
                isometry                         = qw_props.isometry,
                regularityQuadrilaterals         = qw_props.regularity_quads,
                regularityNonQuadrilaterals      = qw_props.regularity_non_quads,
                regularityNonQuadrilateralsWeight= qw_props.regularity_non_quads_weight,
                alignSingularities               = qw_props.align_singularities,
                alignSingularitiesWeight         = qw_props.align_singularities_weight,
                repeatLosingConstraintsIterations= qw_props.repeat_losing_iters,
                repeatLosingConstraintsQuads     = qw_props.repeat_losing_quads,
                repeatLosingConstraintsNonQuads  = qw_props.repeat_losing_non_quads,
                repeatLosingConstraintsAlign     = qw_props.repeat_losing_align,
                hardParityConstraint             = qw_props.hard_parity,
                flowConfig                       = qw_props.flow_config,
                satsumaConfig                    = qw_props.satsuma_config,
                callbackTimeLimit                = list(qw_props.callback_time_limit),
                callbackGapLimit                 = list(qw_props.callback_gap_limit),
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
