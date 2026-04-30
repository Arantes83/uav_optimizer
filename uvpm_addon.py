"""UVPackmaster addon integration modeled after ZenUV's UVPM manager."""

import addon_utils
import os
import sys
import time

import bpy


class UVPmAddonData:
    """Discover and cache UVPackmaster when it is installed as a Blender addon."""

    _ADDON_NAMES = {
        "UVPackmaster3",
        "UVPackmaster 3",
        "UVPackmaster 2",
        "UVPackmaster2",
    }

    _CACHE_VERSION = None
    _CACHE_PATH = None
    _CACHE_PACKAGE = None
    _CACHE_PANELS = None

    @classmethod
    def _invalidate(cls):
        cls._CACHE_VERSION = None
        cls._CACHE_PATH = None
        cls._CACHE_PACKAGE = None
        cls._CACHE_PANELS = None

    @classmethod
    def update(cls):
        active_addons = bpy.context.preferences.addons

        if cls._CACHE_PACKAGE is not None and cls._CACHE_PACKAGE in active_addons:
            return

        cls._invalidate()
        for addon in addon_utils.modules():
            try:
                info = addon_utils.module_bl_info(addon)
            except Exception:
                continue

            if not info or info.get("name") not in cls._ADDON_NAMES:
                continue

            package = addon.__name__
            if package not in active_addons:
                continue

            version = info.get("version", (0, 0, 0))
            cls._CACHE_VERSION = tuple(int(part) for part in version[:3])
            cls._CACHE_PACKAGE = package
            cls._CACHE_PATH = os.path.dirname(os.path.abspath(addon.__file__))
            return

    @classmethod
    def version(cls):
        cls.update()
        return cls._CACHE_VERSION

    @classmethod
    def path(cls):
        cls.update()
        return cls._CACHE_PATH

    @classmethod
    def package(cls):
        cls.update()
        return cls._CACHE_PACKAGE

    @classmethod
    def prefs(cls):
        cls.update()
        if cls._CACHE_PACKAGE is None:
            return None
        addon_entry = bpy.context.preferences.addons.get(cls._CACHE_PACKAGE)
        return addon_entry.preferences if addon_entry else None

    @classmethod
    def pack_panels_module(cls):
        if cls._CACHE_PANELS is not None:
            return cls._CACHE_PANELS

        for module_name, module in sys.modules.items():
            if module_name.endswith("scripted_pipeline.panels.pack_panels"):
                cls._CACHE_PANELS = module
                break
        return cls._CACHE_PANELS

    @classmethod
    def is_installed_as_addon(cls):
        return cls.version() is not None


class UVPmAddonPoll:
    """Version gates for UVPackmaster addon API changes."""

    @classmethod
    def _version(cls):
        return UVPmAddonData.version()

    @classmethod
    def since_3_4_0(cls):
        version = cls._version()
        return version is not None and version >= (3, 4, 0)

    @classmethod
    def since_3_3_3(cls):
        version = cls._version()
        return version is not None and version >= (3, 3, 3)

    @classmethod
    def since_3_3_2(cls):
        version = cls._version()
        return version is not None and version >= (3, 3, 2)

    @classmethod
    def since_3(cls):
        version = cls._version()
        return version is not None and version >= (3, 0, 0)

    @classmethod
    def is_v2(cls):
        version = cls._version()
        return version is not None and version < (3, 0, 0)


def _find_uvpm_get_main_props():
    package = UVPmAddonData.package()
    for module_name, module in sys.modules.items():
        if package and not module_name.startswith(package):
            continue
        getter = getattr(module, "get_main_props", None)
        if callable(getter):
            return getter
    return None


def get_uvpm_scene_props(context):
    """Return the UVPM packing property pointer, including UVPM 3.4 option sets."""
    if not hasattr(context.scene, "uvpm3_props"):
        return None

    scene_props = context.scene.uvpm3_props
    if UVPmAddonPoll.since_3_4_0():
        getter = _find_uvpm_get_main_props()
        if getter is not None:
            try:
                return getter(context)
            except Exception:
                pass
        return getattr(scene_props, "default_main_props", scene_props)

    return scene_props


class UVPmAddonManager:
    """Delegate packing to the installed UVPackmaster addon."""

    _NON_INTERACTIVE_HEURISTIC_SECONDS = 10
    _EXTRA_STORED_PROPS = (
        "advanced_heuristic",
        "heuristic_search_time",
        "heuristic_max_wait_time",
    )

    _PROPS_3_3_3 = {
        "margin": "margin",
        "rotation_enable": "rotation_enable",
        "lock_overlapping_enable": "lock_overlapping_enable",
        "lock_overlapping_mode": "lock_overlapping_mode",
        "scale_mode": None,
        "heuristic_enable": "advanced_heuristic",
        "normalize_scale": False,
        "use_blender_tile_grid": False,
        "tex_ratio": False,
    }

    _PROPS_3_2 = {
        "margin": "margin",
        "rotation_enable": "rotation_enable",
        "lock_overlapping_enable": "lock_overlapping_enable",
        "lock_overlapping_mode": "lock_overlapping_mode",
        "fixed_scale": False,
        "heuristic_enable": "advanced_heuristic",
        "normalize_scale": False,
        "use_blender_tile_grid": False,
        "tex_ratio": False,
    }

    _PROPS_3_0 = {
        "margin": "margin",
        "rotation_enable": "rotation_enable",
        "lock_overlapping_enable": "lock_overlapping_enable",
        "lock_overlapping_mode": "lock_overlapping_mode",
        "fixed_scale": False,
        "heuristic_enable": "advanced_heuristic",
        "normalize_islands": False,
        "use_blender_tile_grid": False,
        "tex_ratio": False,
    }

    _PROPS_2 = {
        "margin": "margin",
        "rot_enable": "rotation_enable",
        "lock_overlapping_mode": "lock_overlapping_mode",
        "fixed_scale": False,
        "heuristic_enable": "advanced_heuristic",
        "normalize_islands": False,
        "pack_to_others": False,
        "use_blender_tile_grid": False,
        "tex_ratio": False,
    }

    def __init__(self):
        self.uvpm_version = None
        self.props_pointer = None
        self.parsed_props = None
        self.stored_state = {}
        self.last_error = ""
        self.last_elapsed = 0.0

    def get_engine_version(self, context):
        version = UVPmAddonData.version()
        self.uvpm_version = version

        if UVPmAddonPoll.since_3_4_0():
            self.props_pointer = get_uvpm_scene_props(context)
            self.parsed_props = self._PROPS_3_3_3
        elif UVPmAddonPoll.since_3_3_3():
            self.props_pointer = getattr(context.scene, "uvpm3_props", None)
            self.parsed_props = self._PROPS_3_3_3
        elif UVPmAddonPoll.since_3_3_2():
            self.props_pointer = getattr(context.scene, "uvpm3_props", None)
            self.parsed_props = self._PROPS_3_2
        elif UVPmAddonPoll.since_3():
            self.props_pointer = getattr(context.scene, "uvpm3_props", None)
            if self.props_pointer and hasattr(self.props_pointer, "normalize_scale"):
                self.parsed_props = self._PROPS_3_2
            else:
                self.parsed_props = self._PROPS_3_0
        elif UVPmAddonPoll.is_v2():
            self.props_pointer = getattr(context.scene, "uvp2_props", None)
            self.parsed_props = self._PROPS_2
        else:
            return None

        return version if self.props_pointer is not None else None

    def _store_props(self):
        self.stored_state = {}
        if self.props_pointer is None or self.parsed_props is None:
            return
        prop_names = set(self.parsed_props)
        prop_names.update(self._EXTRA_STORED_PROPS)
        for attr in prop_names:
            if hasattr(self.props_pointer, attr):
                self.stored_state[attr] = getattr(self.props_pointer, attr)

    def _restore_props(self):
        for attr, value in self.stored_state.items():
            try:
                setattr(self.props_pointer, attr, value)
            except Exception:
                pass

    def _transfer_uav_to_uvpm(self, uav_props):
        for uvpm_attr, source in self.parsed_props.items():
            if not hasattr(self.props_pointer, uvpm_attr):
                continue
            try:
                if source is None:
                    if uvpm_attr != "scale_mode":
                        continue
                    value = "1" if getattr(uav_props, "scale_mode", "MAX_SCALE") in {"LOCKED", "CUSTOM"} else "0"
                elif isinstance(source, str):
                    if not hasattr(uav_props, source):
                        continue
                    value = getattr(uav_props, source)
                else:
                    value = source
                setattr(self.props_pointer, uvpm_attr, value)
            except Exception as exc:
                print(f"MeshForge UAV UVPM transfer warning: {uvpm_attr}: {exc}")
        self._transfer_uvpm_heuristic_options(uav_props)

    def _transfer_uvpm_heuristic_options(self, uav_props):
        """UVPM non-interactive pack requires a finite heuristic timeout."""
        heuristic_enabled = bool(getattr(uav_props, "advanced_heuristic", False))

        for attr in ("heuristic_enable", "advanced_heuristic"):
            if hasattr(self.props_pointer, attr):
                try:
                    setattr(self.props_pointer, attr, heuristic_enabled)
                except Exception as exc:
                    print(f"MeshForge UAV UVPM transfer warning: {attr}: {exc}")

        if not heuristic_enabled:
            return

        search_time = float(getattr(uav_props, "search_time", 0.0) or 0.0)
        if search_time <= 0.01:
            search_time = self._NON_INTERACTIVE_HEURISTIC_SECONDS

        search_time = max(1, min(3600, int(round(search_time))))
        max_wait_time = max(1, min(300, search_time))

        for attr, value in (
            ("heuristic_search_time", search_time),
            ("heuristic_max_wait_time", max_wait_time),
        ):
            if hasattr(self.props_pointer, attr):
                try:
                    setattr(self.props_pointer, attr, value)
                except Exception as exc:
                    print(f"MeshForge UAV UVPM transfer warning: {attr}: {exc}")

    def _active_uvpm_mode_id(self, context):
        if UVPmAddonPoll.since_3_4_0():
            prefs = UVPmAddonData.prefs()
            if prefs is None:
                raise RuntimeError("UVPackmaster preferences were not found.")
            active_mode = prefs.get_active_main_mode(context)
            return active_mode.MODE_ID
        return getattr(context.scene.uav_uvpack_props, "uvp3_packing_method", "pack.single_tile")

    def _invoke(self, context):
        try:
            if UVPmAddonPoll.since_3_4_0():
                if not bpy.ops.uvpackmaster3.pack.poll():
                    self.last_error = "uvpackmaster3.pack poll() failed."
                    return False
                bpy.ops.uvpackmaster3.pack(
                    mode_id=self._active_uvpm_mode_id(context),
                    pack_op_type="0",
                )
            elif UVPmAddonPoll.since_3_3_2():
                if not bpy.ops.uvpackmaster3.pack.poll():
                    self.last_error = "uvpackmaster3.pack poll() failed."
                    return False
                bpy.ops.uvpackmaster3.pack(
                    mode_id=self._active_uvpm_mode_id(context),
                    pack_op_type="0",
                )
            elif UVPmAddonPoll.since_3():
                if not bpy.ops.uvpackmaster3.pack.poll():
                    self.last_error = "uvpackmaster3.pack poll() failed."
                    return False
                bpy.ops.uvpackmaster3.pack(
                    mode_id=self._active_uvpm_mode_id(context),
                    pack_to_others=False,
                )
            elif UVPmAddonPoll.is_v2():
                if not bpy.ops.uvpackmaster2.uv_pack.poll():
                    self.last_error = "uvpackmaster2.uv_pack poll() failed."
                    return False
                bpy.ops.uvpackmaster2.uv_pack()
            else:
                self.last_error = "Unsupported UVPackmaster addon version."
                return False
        except Exception as exc:
            self.last_error = str(exc)
            return False
        return True

    def pack(self, context, uav_props):
        start_time = time.perf_counter()
        if not self.get_engine_version(context):
            return False, "UVPackmaster addon was not detected or is not enabled."
        if self.props_pointer is None:
            return False, "UVPackmaster properties were not found."

        self._store_props()
        try:
            self._transfer_uav_to_uvpm(uav_props)
            success = self._invoke(context)
        finally:
            self._restore_props()

        self.last_elapsed = time.perf_counter() - start_time
        if not success:
            return False, f"UVPackmaster addon invocation failed: {self.last_error}"
        return True, f"UVPackmaster addon {self.uvpm_version} invoked."

    def sync_only(self, context, uav_props):
        if not self.get_engine_version(context):
            return False, "UVPackmaster addon was not detected or is not enabled."
        if self.props_pointer is None:
            return False, "UVPackmaster properties were not found."
        self._transfer_uav_to_uvpm(uav_props)
        return True, "UAV packing properties synced to UVPackmaster."
