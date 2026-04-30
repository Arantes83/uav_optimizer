import os

import bpy
import bpy.utils.previews


_PREVIEW_COLLECTIONS = {}
_BANNER_KEY = "meshforge_uav_banner"
_BANNER_RELATIVE_PATHS = (
    os.path.join("Documentation", "Images", "MeshForgeUAV.png"),
    os.path.join("documentation", "Images", "MeshForgeUAV.png"),
)


def _addon_root():
    return os.path.dirname(os.path.abspath(__file__))


def _banner_path():
    base_dir = _addon_root()
    for rel_path in _BANNER_RELATIVE_PATHS:
        candidate = os.path.join(base_dir, rel_path)
        if os.path.isfile(candidate):
            return candidate
    return None


def register():
    if _PREVIEW_COLLECTIONS:
        return

    pcoll = bpy.utils.previews.new()
    banner_path = _banner_path()
    if banner_path:
        pcoll.load(_BANNER_KEY, banner_path, 'IMAGE')
    _PREVIEW_COLLECTIONS["main"] = pcoll


def unregister():
    for pcoll in _PREVIEW_COLLECTIONS.values():
        try:
            bpy.utils.previews.remove(pcoll)
        except Exception:
            pass
    _PREVIEW_COLLECTIONS.clear()


def get_banner_icon_id():
    pcoll = _PREVIEW_COLLECTIONS.get("main")
    if not pcoll:
        return 0
    preview = pcoll.get(_BANNER_KEY)
    return preview.icon_id if preview else 0
