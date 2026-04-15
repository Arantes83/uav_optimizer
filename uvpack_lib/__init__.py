"""
uvpack_lib/__init__.py
ctypes wrapper for lib_uvpack, following the same external-DLL pattern as quadwild_lib.
"""
import platform
from glob import glob
from ctypes import *
from os import path

MIN_DLL_VERSION = (1, 2, 1)


class UVIsland(Structure):
    _fields_ = [
        ('id', c_int),
        ('w', c_float),
        ('h', c_float),
        ('area', c_float),
        ('mask_data', POINTER(c_uint8)),
        ('mask_stride', c_int),
    ]


class UVPlacement(Structure):
    _fields_ = [('id', c_int), ('x', c_float), ('y', c_float), ('angle', c_float)]


class UVPackConfig(Structure):
    _fields_ = [
        ('method', c_int),
        ('heuristic', c_int),
        ('optimizer', c_int),
        ('margin', c_float),
        ('max_iter', c_int),
        ('time_limit', c_float),
        ('rotation_step', c_int),
        ('resolution', c_int),
        ('sa_initial_temp', c_float),
        ('sa_cooling_rate', c_float),
        ('min_occupancy', c_float),
    ]


METHODS = {'MAXRECTS': 0, 'SKYLINE': 1, 'PIXEL': 2, 'HORIZON': 3}
HEURISTICS = {'BSSF': 0, 'BLSF': 1, 'BAF': 2, 'BL': 3, 'CP': 4}
OPTIMIZERS = {'NONE': 0, 'ITERATIVE': 1, 'SA': 2}


class UVPackException(Exception):
    pass


def _parse_version_tuple(version_text: str):
    numbers = []
    for token in version_text.replace('-', ' ').split():
        if token and all(part.isdigit() for part in token.split('.')):
            numbers = [int(part) for part in token.split('.')]
            break
    return tuple(numbers) if numbers else (0, 0, 0)


class UVPackLib:
    def __init__(self):
        system = platform.system()
        base_dir = path.dirname(path.abspath(__file__))
        if system == 'Windows':
            pattern = 'lib_uvpack_*.dll'
            fallback = 'lib_uvpack.dll'
        elif system == 'Darwin':
            pattern = 'lib_uvpack_*.dylib'
            fallback = 'liblib_uvpack.dylib'
        else:
            pattern = 'lib_uvpack_*.so'
            fallback = 'liblib_uvpack.so'

        candidates = sorted(glob(path.join(base_dir, pattern)), reverse=True)
        fallback_path = path.join(base_dir, fallback)
        if fallback_path not in candidates and path.exists(fallback_path):
            candidates.append(fallback_path)
        if not candidates:
            candidates = [fallback_path]

        load_errors = []
        loaded = None
        loaded_path = None
        for candidate in candidates:
            try:
                lib = cdll.LoadLibrary(candidate)
                lib.uvpack_run.argtypes = [
                    POINTER(UVIsland), c_int, POINTER(UVPackConfig), POINTER(UVPlacement)
                ]
                lib.uvpack_run.restype = c_float
                lib.uvpack_version.argtypes = []
                lib.uvpack_version.restype = c_char_p
                version_text = lib.uvpack_version().decode(errors='replace')
                version_tuple = _parse_version_tuple(version_text)
                if version_tuple < MIN_DLL_VERSION:
                    load_errors.append(
                        f"{candidate}: incompatible version {version_text} (minimum required: {'.'.join(map(str, MIN_DLL_VERSION))})"
                    )
                    continue
                loaded = lib
                loaded_path = candidate
                self._version_text = version_text
                break
            except OSError as exc:
                load_errors.append(f"{candidate}: {exc}")

        if loaded is None:
            details = '\n'.join(load_errors) if load_errors else 'No candidate DLL was found.'
            raise UVPackException(
                'Failed to load a compatible lib_uvpack build.\n'
                'Compile the native library before using CPP_NATIVE.\n'
                f'{details}'
            )

        self._lib = loaded
        self._lib_path = loaded_path

    def version(self):
        return self._version_text

    def pack(self, islands_data: list, props, min_occupancy: float = 0.0):
        n = len(islands_data)
        if n == 0:
            return [], 0.0

        c_islands = (UVIsland * n)()
        resolution = int(getattr(props, 'pixel_resolution', 64))
        mask_buffer = None
        cursor = 0

        if getattr(props, 'packing_method', '') in {'PIXEL', 'HORIZON'}:
            total_mask_bytes = sum(len(d.get('mask', b'')) for d in islands_data)
            mask_buffer = create_string_buffer(total_mask_bytes if total_mask_bytes > 0 else 1)

        for i, d in enumerate(islands_data):
            mask_ptr = POINTER(c_uint8)()
            mask_stride = 0
            if mask_buffer is not None:
                mask = bytes(d.get('mask', b''))
                mask_len = len(mask)
                if mask_len:
                    memmove(addressof(mask_buffer) + cursor, mask, mask_len)
                    mask_ptr = cast(addressof(mask_buffer) + cursor, POINTER(c_uint8))
                    mask_stride = resolution
                    cursor += mask_len

            c_islands[i] = UVIsland(
                d['id'],
                d['w'],
                d['h'],
                d['area'],
                mask_ptr,
                mask_stride,
            )

        rot_step = int(props.rotation_step) if props.rotation_enable else 0
        margin = (
            props.pixel_margin / props.texture_size
            if props.pixel_margin_enable and props.texture_size > 0
            else props.margin
        )

        cfg = UVPackConfig(
            method=METHODS.get(props.packing_method, 0),
            heuristic=HEURISTICS.get(props.maxrects_heuristic, 0),
            optimizer=OPTIMIZERS.get(props.optimizer, 1),
            margin=margin,
            max_iter=props.precision,
            time_limit=props.search_time,
            rotation_step=rot_step,
            resolution=resolution,
            sa_initial_temp=props.sa_initial_temp,
            sa_cooling_rate=props.sa_cooling_rate,
            min_occupancy=min_occupancy,
        )
        c_out = (UVPlacement * n)()

        try:
            occ = self._lib.uvpack_run(c_islands, n, byref(cfg), c_out)
        except Exception as exc:
            raise UVPackException(f'uvpack_run failed: {exc}') from exc

        placements = [
            {'id': c_out[i].id, 'x': c_out[i].x, 'y': c_out[i].y, 'angle': c_out[i].angle}
            for i in range(n)
        ]
        return placements, float(occ)


_instance: UVPackLib | None = None


def get_lib() -> UVPackLib:
    global _instance
    if _instance is None:
        _instance = UVPackLib()
    return _instance
