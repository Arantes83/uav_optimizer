bl_info = {
    "name": "UAV Topology Optimizer",
    "author": "Rodrigo Arantes",
    "version": (1, 5, 0),
    "blender": (4, 2, 0),
    "location": "View3D > UI > UAV Opt",
    "description": (
        "Photogrammetry / LiDAR post-processing pipeline. "
        "Pre-processing, QEM decimation, quad retopology (QuadriFlow, QuadWild, "
        "Voxel, Grid Projection), grid seam generation, native Blender UV unwrap, "
        "advanced UV island packing, and Albedo / AO / Normal map baking."
    ),
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

if os.path.isdir(_dll_dir):
    if _dll_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _dll_dir + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(_dll_dir)
        except OSError:
            pass

# ---------------------------------------------------------------------------
# Reload support (hot-reload without restarting Blender)
# ---------------------------------------------------------------------------
if "bpy" in locals():
    import importlib
    from . import (
        properties, qem_core, op_preprocess, op_qem, op_quadriflow, op_quadwild,
        op_shrinkwrap, op_voxel, op_chunk, op_uv, op_packing, op_bake, ui,
    )
    importlib.reload(properties)
    importlib.reload(qem_core)
    importlib.reload(op_preprocess)
    importlib.reload(op_qem)
    importlib.reload(op_quadriflow)
    importlib.reload(op_quadwild)
    importlib.reload(op_shrinkwrap)
    importlib.reload(op_voxel)
    importlib.reload(op_chunk)
    importlib.reload(op_uv)
    importlib.reload(op_packing)
    importlib.reload(op_bake)
    importlib.reload(ui)

from .properties import (
    UAVOptimizerProperties, UAVQuadWildProperties, 
    UAVUVStandardMethodsProperties,
    UAVUVPackProperties, UAVBakeProperties,
)
from .op_uv  import (
    UAV_OT_uv_unwrap,
    UAV_OT_uv_equalize_texel, UAV_OT_uv_island_stats,
)
from .op_packing import UAV_OT_uv_pack, UAV_OT_uv_pack_reset
from .op_bake import UAV_OT_detail_baking
from .ui import UAV_PT_main_panel
from .op_preprocess import UAV_OT_preprocess
from .op_qem        import UAV_OT_qem_simplify
from .op_quadriflow import UAV_OT_quadriflow
from .op_quadwild   import UAV_OT_quadwild
from .op_shrinkwrap import UAV_OT_shrinkwrap_retopo
from .op_voxel      import UAV_OT_voxel_retopo
from .op_chunk      import UAV_OT_split_chunks

classes = (
    # PropertyGroups must come before any operator or panel that uses them
    UAVOptimizerProperties,
    UAVQuadWildProperties,
    UAVUVStandardMethodsProperties,
    UAVUVPackProperties,
    UAVBakeProperties,

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
    UAV_OT_split_chunks,
    UAV_OT_uv_unwrap,
    UAV_OT_uv_equalize_texel,
    UAV_OT_uv_island_stats,
    UAV_OT_uv_pack,
    UAV_OT_uv_pack_reset,

    # Baking
    UAV_OT_detail_baking,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.uav_props = bpy.props.PointerProperty(
        type=UAVOptimizerProperties)
    bpy.types.Scene.uav_quadwild_props = bpy.props.PointerProperty(
        type=UAVQuadWildProperties)
    bpy.types.Scene.uav_uvpack_props = bpy.props.PointerProperty(
        type=UAVUVPackProperties)
    bpy.types.Scene.uav_bake_props = bpy.props.PointerProperty(
        type=UAVBakeProperties)
    bpy.types.Scene.uav_std_uv_props = bpy.props.PointerProperty(
        type=UAVUVStandardMethodsProperties)


def unregister():
    del bpy.types.Scene.uav_std_uv_props
    del bpy.types.Scene.uav_bake_props
    del bpy.types.Scene.uav_uvpack_props
    del bpy.types.Scene.uav_quadwild_props
    del bpy.types.Scene.uav_props

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
