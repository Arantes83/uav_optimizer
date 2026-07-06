bl_info = {
    "name": "MeshForge UAV",
    "author": "Rodrigo Arantes",
    "version": (1, 0, 0),
    "blender": (4, 5, 10),
    "location": "View3D > UI > MeshForge UAV",
    "description": (
        "MeshForge UAV photogrammetry / LiDAR post-processing pipeline. "
        "Pre-processing, QEM decimation, quad retopology (QuadriFlow, QuadWild, "
        "Voxel, Grid Projection), grid seam generation, native Blender UV unwrap, "
        "advanced UV island packing, Albedo / AO / Normal map baking, LOD generation, "
        "and engine-ready FBX export."
    ),
    "warning": "Release candidate build; APIs and generated outputs may change.",
    "category": "3D View",
}

import os
import sys
import bpy

# ---------------------------------------------------------------------------
# QuadWild DLL discovery — adds the lib folder to PATH / DLL search path
# ---------------------------------------------------------------------------
_addon_dir = os.path.dirname(os.path.abspath(__file__))
_dll_dir   = os.path.join(_addon_dir, "quadwild_lib")

_uvpack_dll_dir = os.path.join(_addon_dir, "uvpack_lib")

for _d in (_dll_dir, _uvpack_dll_dir):
    if os.path.isdir(_d):
        if _d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(_d)
            except OSError:
                pass

# ---------------------------------------------------------------------------
# Reload support (hot-reload without restarting Blender)
# ---------------------------------------------------------------------------
if "bpy" in locals():
    import importlib
    from . import (
        addon_images, properties, qem_core, uv_utils, mesh_health, uvpm_bridge, uvpm_addon, op_preprocess, op_qem, op_quadriflow, op_quadwild,
        op_shrinkwrap, op_voxel, op_seam, op_uv, op_packing, op_bake, op_lod, op_export, ui,
    )
    importlib.reload(addon_images)
    importlib.reload(properties)
    importlib.reload(qem_core)
    importlib.reload(uv_utils)
    importlib.reload(mesh_health)
    importlib.reload(uvpm_bridge)
    importlib.reload(uvpm_addon)
    importlib.reload(op_preprocess)
    importlib.reload(op_qem)
    importlib.reload(op_quadriflow)
    importlib.reload(op_quadwild)
    importlib.reload(op_shrinkwrap)
    importlib.reload(op_voxel)
    importlib.reload(op_seam)
    importlib.reload(op_uv)
    importlib.reload(op_packing)
    importlib.reload(op_bake)
    importlib.reload(op_lod)
    importlib.reload(op_export)
    importlib.reload(ui)

from . import uv_utils
from . import addon_images

from .properties import (
    UAVOptimizerProperties, UAVQuadWildProperties,
    UAVUVStandardMethodsProperties,
    UAVUVPackProperties, UAVBakeProperties, UAVLODProperties,
    UAVExportProperties,
)
from .op_uv  import (
    UAV_OT_uv_unwrap,
    UAV_OT_uv_equalize_texel, UAV_OT_uv_island_stats,
)
from .op_packing import UAV_OT_uv_pack, UAV_OT_uv_pack_reset, UAV_OT_uvpm_sync_props
from .op_bake import UAV_OT_detail_baking
from .op_lod  import UAV_OT_generate_lods, UAV_OT_lod_preview
from .op_export import UAV_OT_export_engine_asset
from .ui import UAV_PT_main_panel
from .op_preprocess import UAV_OT_preprocess
from .op_qem        import UAV_OT_qem_simplify
from .op_quadriflow import UAV_OT_quadriflow
from .op_quadwild   import UAV_OT_quadwild
from .op_shrinkwrap import UAV_OT_shrinkwrap_retopo
from .op_voxel      import UAV_OT_voxel_retopo
from .op_seam       import UAV_OT_trace_grid_seams

classes = (
    # PropertyGroups must come before any operator or panel that uses them
    UAVOptimizerProperties,
    UAVQuadWildProperties,
    UAVUVStandardMethodsProperties,
    UAVUVPackProperties,
    UAVBakeProperties,
    UAVLODProperties,
    UAVExportProperties,

    # UI
    UAV_PT_main_panel,

    # Pre-Processing
    UAV_OT_preprocess,

    # Retopology
    UAV_OT_qem_simplify,
    UAV_OT_quadriflow,
    UAV_OT_quadwild,
    UAV_OT_shrinkwrap_retopo,
    UAV_OT_voxel_retopo,

    # UV & Unwrapping
    UAV_OT_trace_grid_seams,
    UAV_OT_uv_unwrap,
    UAV_OT_uv_equalize_texel,
    UAV_OT_uv_island_stats,
    UAV_OT_uv_pack,
    UAV_OT_uv_pack_reset,
    UAV_OT_uvpm_sync_props,

    # Baking
    UAV_OT_detail_baking,
    UAV_OT_generate_lods,
    UAV_OT_lod_preview,
    UAV_OT_export_engine_asset,
)


SCENE_PROPS = (
    ("uav_props", UAVOptimizerProperties),
    ("uav_quadwild_props", UAVQuadWildProperties),
    ("uav_uvpack_props", UAVUVPackProperties),
    ("uav_bake_props", UAVBakeProperties),
    ("uav_lod_props", UAVLODProperties),
    ("uav_export_props", UAVExportProperties),
    ("uav_std_uv_props", UAVUVStandardMethodsProperties),
)

LEGACY_CLASS_NAMES = (
    "UAV_OT_split_chunks",
    "UAV_OT_uvpm_detect_engine",
)


def _safe_unregister_class(cls):
    registered_cls = getattr(bpy.types, cls.__name__, None)
    for candidate in (registered_cls, cls):
        if candidate is None:
            continue
        try:
            bpy.utils.unregister_class(candidate)
            return
        except (RuntimeError, ValueError):
            continue


def _safe_unregister_class_name(class_name):
    registered_cls = getattr(bpy.types, class_name, None)
    if registered_cls is None:
        return
    try:
        bpy.utils.unregister_class(registered_cls)
    except (RuntimeError, ValueError):
        pass


def _safe_register_class(cls):
    _safe_unregister_class(cls)
    try:
        bpy.utils.register_class(cls)
    except (RuntimeError, ValueError) as exc:
        if "already registered" not in str(exc):
            raise
        _safe_unregister_class(cls)
        bpy.utils.register_class(cls)


def _safe_unregister_scene_prop(name):
    if hasattr(bpy.types.Scene, name):
        try:
            delattr(bpy.types.Scene, name)
        except AttributeError:
            pass


def _safe_register_scene_prop(name, prop_type):
    _safe_unregister_scene_prop(name)
    setattr(bpy.types.Scene, name, bpy.props.PointerProperty(type=prop_type))


def register():
    unregister()

    addon_images.register()
    for cls in classes:
        _safe_register_class(cls)

    for name, prop_type in SCENE_PROPS:
        _safe_register_scene_prop(name, prop_type)


def unregister():
    for name, _prop_type in reversed(SCENE_PROPS):
        _safe_unregister_scene_prop(name)

    for class_name in LEGACY_CLASS_NAMES:
        _safe_unregister_class_name(class_name)

    for cls in reversed(classes):
        _safe_unregister_class(cls)

    addon_images.unregister()


if __name__ == "__main__":
    register()
