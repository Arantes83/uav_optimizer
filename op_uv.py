"""
Native Blender UV tools used by the addon.

This module intentionally keeps only:
- Smart UV Project
- Conformal unwrap
- Angle Based unwrap
- Minimum Stretch
- Texel density equalization
- UV packing statistics
"""

import math
import time

import bmesh
import bpy
from bpy.types import Operator
from .uv_utils import (
    _area as _area_uv,
    _bounds as _bounds_uv,
    _get_uv_islands,
    _scale_island_from_center,
)

EPSILON = 1e-12


def _ensure_uv_layer(bm):
    """Return the active UV layer, creating one if needed."""
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.new("UVMap")
    return uv_layer


def _area_3d(faces):
    """Compute 3D surface area for a list of faces."""
    return sum(face.calc_area() for face in faces)


def _island_density(faces, uv_layer):
    """Return (area_3d, area_uv, density) for one island."""
    area_3d = _area_3d(faces)
    area_uv = _area_uv(faces, uv_layer)
    density = math.sqrt(area_uv / area_3d) if area_3d > EPSILON else 0.0
    return area_3d, area_uv, density


def _face_area_ratio(face, uv_layer):
    """Return UV area / 3D area for one face, or None if degenerate."""
    area_3d = face.calc_area()
    if area_3d <= EPSILON:
        return None

    uvs = [loop[uv_layer].uv for loop in face.loops]
    area_uv = 0.0
    for index in range(1, len(uvs) - 1):
        area_uv += abs(
            (uvs[index].x - uvs[0].x) * (uvs[index + 1].y - uvs[0].y) -
            (uvs[index + 1].x - uvs[0].x) * (uvs[index].y - uvs[0].y)
        ) * 0.5

    if area_uv <= EPSILON:
        return None
    return area_uv / area_3d


def _compute_face_stretch_map(bm, uv_layer):
    """Compute a scale-invariant stretch score per face."""
    ratios = {}
    for face in bm.faces:
        ratio = _face_area_ratio(face, uv_layer)
        if ratio is not None:
            ratios[face.index] = ratio

    if not ratios:
        return {}

    log_mean = sum(math.log(ratio) for ratio in ratios.values()) / len(ratios)
    reference_ratio = math.exp(log_mean)
    return {
        face_index: abs(math.log(ratio / reference_ratio))
        for face_index, ratio in ratios.items()
    }


def _compute_face_stretch(bm, uv_layer):
    """Return average and max stretch."""
    stretches = list(_compute_face_stretch_map(bm, uv_layer).values())
    if not stretches:
        return 0.0, 0.0
    return sum(stretches) / len(stretches), max(stretches)


def _validate_uvs(bm, uv_layer):
    """Return (flipped_faces, out_of_bounds_faces)."""
    flipped = 0
    out_of_bounds = 0

    for face in bm.faces:
        uvs = [loop[uv_layer].uv for loop in face.loops]
        signed_area = 0.0
        for index in range(1, len(uvs) - 1):
            signed_area += (
                (uvs[index].x - uvs[0].x) * (uvs[index + 1].y - uvs[0].y) -
                (uvs[index + 1].x - uvs[0].x) * (uvs[index].y - uvs[0].y)
            ) * 0.5

        if signed_area < 0.0:
            flipped += 1

        if any(
            uv.x < 0.0 or uv.x > 1.0 or uv.y < 0.0 or uv.y > 1.0
            for uv in uvs
        ):
            out_of_bounds += 1

    return flipped, out_of_bounds


def equalize_texel_density(bm, uv_layer, mode="UNIFORM"):
    """Equalize texel density across UV islands."""
    islands = _get_uv_islands(bm, uv_layer)
    if not islands:
        return

    total_3d = sum(_area_3d(faces) for faces in islands)
    total_uv = sum(_area_uv(faces, uv_layer) for faces in islands)
    if total_3d <= EPSILON:
        return

    base_density = math.sqrt(total_uv / total_3d)

    for faces in islands:
        area_3d, _, current_density = _island_density(faces, uv_layer)
        if current_density <= EPSILON:
            continue

        if mode == "ADAPTIVE":
            complexity_factor = 1.0 + 0.5 * (area_3d / total_3d)
            target_density = base_density * complexity_factor
        else:
            target_density = base_density

        scale = target_density / current_density
        if abs(scale - 1.0) > 1e-4:
            _scale_island_from_center(faces, uv_layer, scale)


def equalize_texel_density_manual(bm, uv_layer, target_density, reference_resolution):
    """Scale islands to a manual px/m target at a given bake resolution."""
    if target_density <= 0.0 or reference_resolution <= 0:
        return

    target_uv_density = target_density / float(reference_resolution)
    for faces in _get_uv_islands(bm, uv_layer):
        _, _, current_density = _island_density(faces, uv_layer)
        if current_density <= EPSILON:
            continue
        scale = target_uv_density / current_density
        if abs(scale - 1.0) > 1e-4:
            _scale_island_from_center(faces, uv_layer, scale)


def _collect_uv_stats(bm, uv_layer):
    """Gather the UV metrics shown by the addon UI."""
    islands = _get_uv_islands(bm, uv_layer)
    densities = []
    total_uv_area = 0.0

    for faces in islands:
        _, island_uv_area, density = _island_density(faces, uv_layer)
        total_uv_area += island_uv_area
        densities.append(density)

    avg_stretch, _ = _compute_face_stretch(bm, uv_layer)
    flipped, out_of_bounds = _validate_uvs(bm, uv_layer)

    return {
        "islands": len(islands),
        "coverage": min(total_uv_area * 100.0, 100.0),
        "avg_stretch": avg_stretch,
        "avg_density": sum(densities) / len(densities) if densities else 0.0,
        "min_density": min(densities) if densities else 0.0,
        "max_density": max(densities) if densities else 0.0,
        "flipped": flipped,
        "out_of_bounds": out_of_bounds,
    }


def _store_uv_results(props, stats, method_name=None, elapsed_time=None):
    """Persist metrics into the property group used by the panel."""
    props.last_islands = stats["islands"]
    props.last_stretch = stats["avg_stretch"]
    props.last_coverage = stats["coverage"]
    props.last_avg_density = stats["avg_density"]
    props.last_min_density = stats["min_density"]
    props.last_max_density = stats["max_density"]
    props.last_flipped = stats["flipped"]
    props.last_oob = stats["out_of_bounds"]
    if method_name is not None:
        props.last_method_used = method_name
    if elapsed_time is not None:
        props.last_time = elapsed_time


def _call_smart_project(props):
    """Run Smart UV Project while tolerating minor API naming differences."""
    kwargs = {
        "angle_limit": props.smart_uv_angle_limit,
        "island_margin": props.smart_uv_island_margin,
        "correct_aspect": props.unwrap_correct_aspect,
    }

    for area_key in ("area_weight", "user_area_weight"):
        try:
            bpy.ops.uv.smart_project(**kwargs, **{area_key: props.smart_uv_area_weight})
            return
        except TypeError:
            continue

    bpy.ops.uv.smart_project(**kwargs)


def _call_unwrap(props, method):
    bpy.ops.uv.unwrap(
        method=method,
        fill_holes=props.unwrap_fill_holes,
        correct_aspect=props.unwrap_correct_aspect,
        use_subsurf_data=props.unwrap_use_subsurf,
        margin=props.unwrap_margin,
    )


def _call_minimum_stretch(obj, props):
    """Run Minimum Stretch, seeding UVs when starting from scratch."""
    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = _ensure_uv_layer(bm)
    has_uv_area = _area_uv(bm.faces, uv_layer) > EPSILON
    bmesh.update_edit_mesh(obj.data)

    if not has_uv_area:
        _call_unwrap(props, "ANGLE_BASED")

    try:
        bpy.ops.uv.minimize_stretch(
            fill_holes=props.unwrap_fill_holes,
            blend=props.min_stretch_blend,
            iterations=props.min_stretch_iterations,
        )
    except TypeError:
        bpy.ops.uv.minimize_stretch(
            blend=props.min_stretch_blend,
            iterations=props.min_stretch_iterations,
        )


def _run_native_uv_method(obj, props):
    """Dispatch the selected native Blender UV method."""
    bpy.ops.mesh.select_all(action="SELECT")

    if props.unwrap_method == "SMART":
        _call_smart_project(props)
        return "Smart UV Project"

    if props.unwrap_method == "CONFORMAL":
        _call_unwrap(props, "CONFORMAL")
        return "Conformal"

    if props.unwrap_method == "ANGLE_BASED":
        _call_unwrap(props, "ANGLE_BASED")
        return "Angle Based"

    _call_minimum_stretch(obj, props)
    return "Minimum Stretch"


class UAV_OT_uv_unwrap(Operator):
    """Run one of Blender's native UV operators."""
    bl_idname = "uav.uv_unwrap"
    bl_label = "Native UV Unwrap"
    bl_description = "Run Smart UV, Conformal, Angle Based, or Minimum Stretch"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        props = context.scene.uav_std_uv_props
        original_mode = obj.mode

        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        try:
            bm = bmesh.from_edit_mesh(obj.data)
            _ensure_uv_layer(bm)
            bmesh.update_edit_mesh(obj.data)

            start_time = time.perf_counter()
            method_name = _run_native_uv_method(obj, props)

            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = _ensure_uv_layer(bm)
            stats = _collect_uv_stats(bm, uv_layer)
            elapsed_time = time.perf_counter() - start_time
            _store_uv_results(props, stats, method_name=method_name, elapsed_time=elapsed_time)
            bmesh.update_edit_mesh(obj.data)

            self.report({'INFO'}, f"{method_name} completed in {elapsed_time:.2f}s.")
        except Exception as exc:
            self.report({'ERROR'}, f"UV unwrap failed: {exc}")
            if original_mode != 'EDIT':
                bpy.ops.object.mode_set(mode=original_mode)
            return {'CANCELLED'}

        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode=original_mode)

        return {'FINISHED'}


class UAV_OT_uv_equalize_texel(Operator):
    """Equalize texel density across UV islands."""
    bl_idname = "uav.uv_equalize_texel"
    bl_label = "Equalize Texel Density"
    bl_description = "Rescale UV islands to even out texel density"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            obj.data.uv_layers.active is not None
        )

    def execute(self, context):
        obj = context.active_object
        props = context.scene.uav_std_uv_props
        original_mode = obj.mode

        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        try:
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = _ensure_uv_layer(bm)
            start_time = time.perf_counter()

            if props.density_mode == "MANUAL":
                equalize_texel_density_manual(
                    bm,
                    uv_layer,
                    props.target_density,
                    props.density_bake_resolution,
                )
            else:
                equalize_texel_density(bm, uv_layer, mode=props.density_mode)

            stats = _collect_uv_stats(bm, uv_layer)
            elapsed_time = time.perf_counter() - start_time
            method_name = f"Texel Density ({props.density_mode.replace('_', ' ').title()})"
            _store_uv_results(props, stats, method_name=method_name, elapsed_time=elapsed_time)
            bmesh.update_edit_mesh(obj.data)

            self.report({'INFO'}, "Texel density equalized successfully.")
        except Exception as exc:
            self.report({'ERROR'}, f"Texel density failed: {exc}")
            if original_mode != 'EDIT':
                bpy.ops.object.mode_set(mode=original_mode)
            return {'CANCELLED'}

        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode=original_mode)

        return {'FINISHED'}


class UAV_OT_uv_island_stats(Operator):
    """Refresh UV density and coverage statistics."""
    bl_idname = "uav.uv_island_stats"
    bl_label = "UV Island Statistics"
    bl_description = "Analyze UV density, stretch, coverage, and bounds"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            obj.data.uv_layers.active is not None
        )

    def execute(self, context):
        obj = context.active_object
        props = context.scene.uav_std_uv_props
        original_mode = obj.mode

        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        try:
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = _ensure_uv_layer(bm)
            stats = _collect_uv_stats(bm, uv_layer)
            _store_uv_results(props, stats)
            bmesh.update_edit_mesh(obj.data)

            self.report(
                {'INFO'},
                (
                    f"Islands: {stats['islands']} | Coverage: {stats['coverage']:.1f}% | "
                    f"Avg density: {stats['avg_density']:.4f}"
                ),
            )
        except Exception as exc:
            self.report({'ERROR'}, f"UV stats failed: {exc}")
            if original_mode != 'EDIT':
                bpy.ops.object.mode_set(mode=original_mode)
            return {'CANCELLED'}

        if original_mode != 'EDIT':
            bpy.ops.object.mode_set(mode=original_mode)

        return {'FINISHED'}
