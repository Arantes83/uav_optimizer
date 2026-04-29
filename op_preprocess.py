import time

import bpy
import bmesh
import mathutils
from bpy.types import Operator

from .mesh_health import (
    analyze_mesh_health,
    repair_mesh_safely,
    classify_retopo_readiness,
    write_report_to_object,
    format_report_summary,
    format_report_details,
)


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


def _build_status_summary(status_counts):
    return (
        f"READY={status_counts.get('READY', 0)}, "
        f"WARNING={status_counts.get('WARNING', 0)}, "
        f"RISKY={status_counts.get('RISKY', 0)}, "
        f"FAILED={status_counts.get('FAILED', 0)}, "
        f"UNKNOWN={status_counts.get('UNKNOWN', 0)}"
    )


def _store_preprocess_ui_report(props, title, status, lines):
    props.pre_last_report_title = title
    props.pre_last_report_status = status
    props.pre_last_report_body = "\n".join(lines)


class UAV_OT_preprocess(Operator):
    bl_idname = "uav.preprocess"
    bl_label = "Run Pre-Processing"
    bl_description = (
        "Diagnose mesh topology in place or create processed mesh copies from the selected sources. "
        "Original meshes are preserved when cleanup finishes"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props = context.scene.uav_props
        scene_collection = context.scene.collection
        sources = [obj for obj in context.selected_objects if obj.type == 'MESH']
        diagnose_only = props.pre_topology_enable and props.pre_repair_mode == "DIAGNOSE"

        if not sources:
            self.report({'WARNING'}, "No valid meshes selected.")
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        created_objects = []
        status_counts = {
            "READY": 0,
            "WARNING": 0,
            "RISKY": 0,
            "FAILED": 0,
            "UNKNOWN": 0,
        }
        report_summaries = []
        report_lines = []
        start_time = time.perf_counter()
        _store_preprocess_ui_report(props, "", "", [])
        if diagnose_only:
            self.report({'INFO'}, "Starting topology diagnosis on selected source meshes...")
        else:
            self.report({'INFO'}, "Starting pre-processing on mesh copies...")

        for source_obj in sources:
            if diagnose_only:
                source_obj["uav_role"] = "HIGH_SOURCE"
                source_obj["uav_stage"] = "SOURCE"
                source_obj["uav_can_be_bake_source"] = True

                final_report = analyze_mesh_health(source_obj)
                classify_retopo_readiness(final_report, props)

                if props.pre_store_health_report:
                    write_report_to_object(source_obj, final_report)

                status_counts[final_report.status] = status_counts.get(final_report.status, 0) + 1
                report_summaries.append((source_obj.name, final_report.status, format_report_summary(final_report)))
                report_lines.extend(format_report_details(final_report))
                report_lines.append("")
                continue

            target_name = f"{source_obj.name}{PREPROCESS_SUFFIX}"
            source_obj["uav_role"] = "HIGH_SOURCE"
            source_obj["uav_stage"] = "SOURCE"
            source_obj["uav_can_be_bake_source"] = True
            source_obj["uav_last_preprocess_target"] = target_name

            new_obj = _duplicate_mesh_object(source_obj, target_name, scene_collection)
            source_obj["uav_last_preprocess_target"] = new_obj.name
            new_obj["uav_role"] = "PREPROCESS"
            new_obj["uav_stage"] = "PREP"
            new_obj["uav_source_object"] = source_obj.name
            new_obj["uav_can_continue_pipeline"] = True
            new_obj["uav_can_be_bake_source"] = False

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

                if props.pre_topology_enable:
                    initial_report = analyze_mesh_health(new_obj)
                    repair_result = repair_mesh_safely(new_obj, props, initial_report)
                    final_report = analyze_mesh_health(new_obj)
                    classify_retopo_readiness(final_report, props)

                    if props.pre_store_health_report:
                        write_report_to_object(new_obj, final_report)

                    new_obj["uav_repair_removed_loose_vertices"] = repair_result.removed_loose_vertices
                    new_obj["uav_repair_removed_loose_edges"] = repair_result.removed_loose_edges
                    new_obj["uav_repair_removed_degenerate_faces"] = repair_result.removed_degenerate_faces
                    new_obj["uav_repair_removed_small_components"] = repair_result.removed_small_components
                    new_obj["uav_repair_filled_holes"] = repair_result.filled_holes
                    new_obj["uav_repair_recalculated_normals"] = repair_result.recalculated_normals

                    status_counts[final_report.status] = status_counts.get(final_report.status, 0) + 1
                    report_summaries.append((new_obj.name, final_report.status, format_report_summary(final_report)))
                    report_lines.extend(format_report_details(final_report, repair_result))
                    report_lines.append("")
                else:
                    status_counts["UNKNOWN"] += 1
                    report_summaries.append((new_obj.name, "UNKNOWN", "Topology check disabled."))
                    report_lines.extend((
                        f"Object: {new_obj.name}",
                        "Status: UNKNOWN",
                        "Summary: Topology check disabled.",
                        "",
                    ))

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

        if created_objects:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in created_objects:
                obj.select_set(True)
            context.view_layer.objects.active = created_objects[0]

        elapsed = time.perf_counter() - start_time
        if report_lines and report_lines[-1] == "":
            report_lines.pop()
        if len(report_summaries) == 1:
            _obj_name, status, summary = report_summaries[0]
            status_summary = f" Status: {status}. {summary}"
            report_status = status
        else:
            status_summary = f" {_build_status_summary(status_counts)}."
            if status_counts.get("FAILED", 0) > 0:
                report_status = "FAILED"
            elif status_counts.get("RISKY", 0) > 0:
                report_status = "RISKY"
            elif status_counts.get("WARNING", 0) > 0:
                report_status = "WARNING"
            elif status_counts.get("READY", 0) > 0:
                report_status = "READY"
            else:
                report_status = "UNKNOWN"

        title = (
            f"Topology Diagnosis: {_build_status_summary(status_counts)}"
            if diagnose_only else
            f"Pre-Processing Result: {_build_status_summary(status_counts)}"
        )
        _store_preprocess_ui_report(props, title, report_status, report_lines)

        self.report(
            {'INFO'},
            (
                f"Topology diagnosis complete: {len(report_summaries)} source mesh(es) analyzed in {elapsed:.2f}s.{status_summary}"
                if diagnose_only else
                f"Pre-processing complete: {len(created_objects)} mesh copy/copies generated in {elapsed:.2f}s.{status_summary}"
            ),
        )
        return {'FINISHED'}
