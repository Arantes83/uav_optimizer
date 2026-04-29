import bpy
import bmesh
import mathutils
from dataclasses import dataclass, field
from collections import deque


STATUS_READY = "READY"
STATUS_WARNING = "WARNING"
STATUS_RISKY = "RISKY"
STATUS_FAILED = "FAILED"
STATUS_UNKNOWN = "UNKNOWN"

DEFAULT_AREA_EPSILON = 1.0e-12
DEFAULT_LENGTH_EPSILON = 1.0e-9
DEFAULT_SMALL_COMPONENT_FACES = 32


@dataclass
class MeshHealthReport:
    object_name: str
    vertex_count: int = 0
    edge_count: int = 0
    face_count: int = 0

    loose_vertices: int = 0
    loose_edges: int = 0
    boundary_edges: int = 0
    manifold_edges: int = 0
    non_manifold_edges: int = 0

    degenerate_faces: int = 0
    zero_area_faces: int = 0

    component_count: int = 0
    small_components: int = 0
    largest_component_faces: int = 0

    is_watertight: bool = False
    is_two_manifold: bool = False
    has_loose_geometry: bool = False
    has_degenerate_geometry: bool = False

    status: str = STATUS_UNKNOWN
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class MeshRepairResult:
    removed_loose_vertices: int = 0
    removed_loose_edges: int = 0
    removed_degenerate_faces: int = 0
    removed_small_components: int = 0
    filled_holes: int = 0
    recalculated_normals: bool = False


def _failed_report(object_name, message):
    report = MeshHealthReport(object_name=object_name, status=STATUS_FAILED)
    report.errors.append(message)
    return report


def _compute_face_component_sizes(bm):
    visited = set()
    sizes = []

    for face in bm.faces:
        if face in visited:
            continue

        queue = deque([face])
        visited.add(face)
        count = 0

        while queue:
            current = queue.popleft()
            count += 1

            for edge in current.edges:
                for linked_face in edge.link_faces:
                    if linked_face not in visited:
                        visited.add(linked_face)
                        queue.append(linked_face)

        sizes.append(count)

    return sizes


def _compute_face_components(bm):
    visited = set()
    components = []

    for face in bm.faces:
        if face in visited:
            continue

        queue = deque([face])
        visited.add(face)
        faces = []

        while queue:
            current = queue.popleft()
            faces.append(current)

            for edge in current.edges:
                for linked_face in edge.link_faces:
                    if linked_face not in visited:
                        visited.add(linked_face)
                        queue.append(linked_face)

        components.append(faces)

    return components


def analyze_mesh_health(obj, area_epsilon=DEFAULT_AREA_EPSILON, length_epsilon=DEFAULT_LENGTH_EPSILON):
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return _failed_report(getattr(obj, "name", "<invalid>"), "Object is not a mesh.")

    report = MeshHealthReport(object_name=obj.name)
    bm = bmesh.new()

    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        report.vertex_count = len(bm.verts)
        report.edge_count = len(bm.edges)
        report.face_count = len(bm.faces)

        for vert in bm.verts:
            if len(vert.link_edges) == 0 and len(vert.link_faces) == 0:
                report.loose_vertices += 1

        for edge in bm.edges:
            face_valence = len(edge.link_faces)
            if face_valence == 0:
                report.loose_edges += 1
            elif face_valence == 1:
                report.boundary_edges += 1
            elif face_valence == 2:
                report.manifold_edges += 1
            else:
                report.non_manifold_edges += 1

        for face in bm.faces:
            if face.calc_area() < area_epsilon:
                report.degenerate_faces += 1
                report.zero_area_faces += 1

        component_sizes = _compute_face_component_sizes(bm)
        report.component_count = len(component_sizes)
        report.small_components = sum(1 for size in component_sizes if size < DEFAULT_SMALL_COMPONENT_FACES)
        report.largest_component_faces = max(component_sizes) if component_sizes else 0

        report.is_watertight = (
            report.edge_count > 0
            and report.boundary_edges == 0
            and report.loose_edges == 0
            and report.non_manifold_edges == 0
        )
        report.is_two_manifold = (
            report.non_manifold_edges == 0
            and report.loose_edges == 0
        )
        report.has_loose_geometry = report.loose_vertices > 0 or report.loose_edges > 0
        report.has_degenerate_geometry = report.degenerate_faces > 0

        classify_retopo_readiness(report)
        return report
    finally:
        bm.free()


def repair_mesh_safely(obj, props, report=None):
    result = MeshRepairResult()
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return result

    repair_mode = getattr(props, "pre_repair_mode", "SAFE")
    if repair_mode == "DIAGNOSE":
        return result

    area_epsilon = DEFAULT_AREA_EPSILON
    remove_loose = getattr(props, "pre_delete_loose_geometry", True)
    recalc_normals = getattr(props, "pre_recalculate_normals", True)
    remove_small_components = getattr(props, "pre_remove_small_components", False)
    min_component_faces = getattr(props, "pre_min_component_faces", DEFAULT_SMALL_COMPONENT_FACES)
    fill_small_holes = (
        getattr(props, "pre_fill_small_holes", False)
        and repair_mode in {"SURFACE_REPAIR", "VOXEL_PREP", "AGGRESSIVE"}
    )
    max_hole_edges = getattr(props, "pre_fill_hole_max_edges", 8)

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        if remove_loose:
            loose_edges = [edge for edge in bm.edges if len(edge.link_faces) == 0]
            result.removed_loose_edges = len(loose_edges)
            if loose_edges:
                bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

            loose_vertices = [
                vert for vert in bm.verts
                if len(vert.link_edges) == 0 and len(vert.link_faces) == 0
            ]
            result.removed_loose_vertices = len(loose_vertices)
            if loose_vertices:
                bmesh.ops.delete(bm, geom=loose_vertices, context='VERTS')
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

        degenerate_faces = [face for face in bm.faces if face.calc_area() < area_epsilon]
        result.removed_degenerate_faces = len(degenerate_faces)
        if degenerate_faces:
            bmesh.ops.delete(bm, geom=degenerate_faces, context='FACES')
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

        if remove_small_components and bm.faces:
            components = _compute_face_components(bm)
            faces_to_delete = []
            for component in components:
                if len(component) < min_component_faces:
                    faces_to_delete.extend(component)
                    result.removed_small_components += 1

            if faces_to_delete:
                bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

        if remove_loose:
            loose_edges = [edge for edge in bm.edges if len(edge.link_faces) == 0]
            result.removed_loose_edges += len(loose_edges)
            if loose_edges:
                bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

            loose_vertices = [
                vert for vert in bm.verts
                if len(vert.link_edges) == 0 and len(vert.link_faces) == 0
            ]
            result.removed_loose_vertices += len(loose_vertices)
            if loose_vertices:
                bmesh.ops.delete(bm, geom=loose_vertices, context='VERTS')
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

        if fill_small_holes and bm.edges:
            boundary_edges_before = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
            fill_sides = max(0, int(max_hole_edges))
            filled = bmesh.ops.holes_fill(
                bm,
                edges=[edge for edge in bm.edges if len(edge.link_faces) == 1],
                sides=fill_sides,
            )
            result.filled_holes = sum(1 for elem in filled.get("geom", []) if isinstance(elem, bmesh.types.BMFace))
            if result.filled_holes == 0 and boundary_edges_before > 0:
                result.filled_holes = max(0, boundary_edges_before - sum(1 for edge in bm.edges if len(edge.link_faces) == 1))
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

        if recalc_normals and bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            result.recalculated_normals = True

        bm.to_mesh(obj.data)
        obj.data.update()
        return result
    finally:
        bm.free()


def classify_retopo_readiness(report, props=None):
    report.warnings.clear()
    report.errors.clear()

    if report.face_count == 0 or report.vertex_count == 0:
        report.status = STATUS_FAILED
        report.errors.append("Mesh has no valid surface faces.")
        return report.status

    if report.degenerate_faces > 0:
        report.status = STATUS_FAILED
        report.errors.append("Degenerate faces remain after pre-processing.")
        return report.status

    if report.loose_edges > 0:
        report.status = STATUS_FAILED
        report.errors.append("Loose edges remain after pre-processing.")
        return report.status

    if report.non_manifold_edges > 0:
        report.status = STATUS_RISKY
        report.warnings.append("Non-manifold edges remain; QuadriFlow and QuadWild may fail or produce unstable patches.")
        return report.status

    if report.loose_vertices > 0:
        report.status = STATUS_RISKY
        report.warnings.append("Loose vertices remain after pre-processing.")
        return report.status

    if report.component_count > 32 and report.small_components > 0:
        report.status = STATUS_RISKY
        report.warnings.append("Many disconnected small components detected.")
        return report.status

    warn_if_open = True if props is None else getattr(props, "pre_warn_if_not_watertight", True)
    if report.boundary_edges > 0 or (warn_if_open and not report.is_watertight):
        if report.is_two_manifold:
            report.status = STATUS_WARNING
            report.warnings.append("Open but two-manifold surface. OK for QEM/Grid Projection; caution for Voxel Remesh.")
        else:
            report.status = STATUS_RISKY
            report.warnings.append("Open surface is not two-manifold.")
        return report.status

    report.status = STATUS_READY
    return report.status


def write_report_to_object(obj, report):
    if obj is None:
        return

    obj["uav_health_status"] = report.status
    obj["uav_health_vertex_count"] = int(report.vertex_count)
    obj["uav_health_edge_count"] = int(report.edge_count)
    obj["uav_health_face_count"] = int(report.face_count)
    obj["uav_health_loose_vertices"] = int(report.loose_vertices)
    obj["uav_health_loose_edges"] = int(report.loose_edges)
    obj["uav_health_boundary_edges"] = int(report.boundary_edges)
    obj["uav_health_manifold_edges"] = int(report.manifold_edges)
    obj["uav_health_non_manifold_edges"] = int(report.non_manifold_edges)
    obj["uav_health_degenerate_faces"] = int(report.degenerate_faces)
    obj["uav_health_zero_area_faces"] = int(report.zero_area_faces)
    obj["uav_health_component_count"] = int(report.component_count)
    obj["uav_health_small_components"] = int(report.small_components)
    obj["uav_health_largest_component_faces"] = int(report.largest_component_faces)
    obj["uav_health_is_watertight"] = bool(report.is_watertight)
    obj["uav_health_is_two_manifold"] = bool(report.is_two_manifold)
    obj["uav_health_has_loose_geometry"] = bool(report.has_loose_geometry)
    obj["uav_health_has_degenerate_geometry"] = bool(report.has_degenerate_geometry)
    obj["uav_health_summary"] = format_report_summary(report)


def format_report_summary(report):
    if report.errors:
        return " ".join(report.errors)
    if report.warnings:
        return " ".join(report.warnings)
    if report.status == STATUS_READY:
        return "Closed two-manifold surface. Ready for QEM, Quad Retopology, UV and Bake target stages."
    if report.status == STATUS_UNKNOWN:
        return "Topology analysis did not produce a readiness classification."
    return f"Topology status: {report.status}."


def format_report_details(report, repair_result=None):
    lines = [
        f"Object: {report.object_name}",
        f"Status: {report.status}",
        f"Vertices={report.vertex_count} Edges={report.edge_count} Faces={report.face_count}",
        (
            "Loose Vertices={0} Loose Edges={1} Boundary Edges={2} "
            "Non-Manifold Edges={3}"
        ).format(
            report.loose_vertices,
            report.loose_edges,
            report.boundary_edges,
            report.non_manifold_edges,
        ),
        (
            "Degenerate Faces={0} Components={1} Small Components={2} "
            "Largest Component Faces={3}"
        ).format(
            report.degenerate_faces,
            report.component_count,
            report.small_components,
            report.largest_component_faces,
        ),
        f"Watertight={report.is_watertight} Two-Manifold={report.is_two_manifold}",
    ]

    if repair_result is not None:
        lines.append(
            (
                "Repair: Loose Verts Removed={0} Loose Edges Removed={1} "
                "Degenerate Faces Removed={2}"
            ).format(
                repair_result.removed_loose_vertices,
                repair_result.removed_loose_edges,
                repair_result.removed_degenerate_faces,
            )
        )
        lines.append(
            (
                "Repair: Small Components Removed={0} Holes Filled={1} "
                "Normals Recalculated={2}"
            ).format(
                repair_result.removed_small_components,
                repair_result.filled_holes,
                repair_result.recalculated_normals,
            )
        )

    summary = format_report_summary(report)
    if summary:
        lines.append(f"Summary: {summary}")

    return lines
