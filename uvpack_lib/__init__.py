"""
uvpack_lib/__init__.py
Wrapper ctypes para lib_uvpack — padrão idêntico ao quadwild_lib.
"""
import platform
from ctypes import *
from os import path


class UVIsland(Structure):
    _fields_ = [('id', c_int), ('w', c_float), ('h', c_float), ('area', c_float)]

class UVPlacement(Structure):
    _fields_ = [('id', c_int), ('x', c_float), ('y', c_float), ('angle', c_float)]

class UVPackConfig(Structure):
    _fields_ = [
        ('method',          c_int),
        ('heuristic',       c_int),
        ('optimizer',       c_int),
        ('margin',          c_float),
        ('max_iter',        c_int),
        ('time_limit',      c_float),
        ('rotation_step',   c_int),
        ('sa_initial_temp', c_float),
        ('sa_cooling_rate', c_float),
        ('min_occupancy',   c_float),
    ]

METHODS    = {'MAXRECTS': 0, 'SKYLINE': 1}
HEURISTICS = {'BSSF': 0, 'BLSF': 1, 'BAF': 2, 'BL': 3, 'CP': 4}
OPTIMIZERS = {'NONE': 0, 'ITERATIVE': 1, 'SA': 2}


class UVPackException(Exception):
    pass


class UVPackLib:
    def __init__(self):
        system = platform.system()
        name = {'Windows': 'lib_uvpack.dll',
                'Darwin':  'liblib_uvpack.dylib'}.get(system, 'liblib_uvpack.so')
        lib_path = path.join(path.dirname(path.abspath(__file__)), name)
        try:
            self._lib = cdll.LoadLibrary(lib_path)
        except OSError as e:
            raise UVPackException(
                f"Não foi possível carregar {lib_path}\n"
                f"Compile com CMake antes de usar.\nErro: {e}"
            ) from e

        self._lib.uvpack_run.argtypes = [
            POINTER(UVIsland), c_int, POINTER(UVPackConfig), POINTER(UVPlacement)]
        self._lib.uvpack_run.restype  = c_float
        self._lib.uvpack_version.argtypes = []
        self._lib.uvpack_version.restype  = c_char_p

    def version(self):
        return self._lib.uvpack_version().decode()

    def pack(self, islands_data: list, props, min_occupancy: float = 0.0):
        """
        islands_data: list de dict {'id', 'w', 'h', 'area'}
        props: UAVUVPackProperties
        Retorna: (placements: list de dict {'id','x','y','angle'}, occupancy: float)
        """
        n = len(islands_data)
        if n == 0:
            return [], 0.0

        c_islands = (UVIsland * n)()
        for i, d in enumerate(islands_data):
            c_islands[i] = UVIsland(d['id'], d['w'], d['h'], d['area'])

        rot_step = int(props.rotation_step) if props.rotation_enable else 0
        margin   = (props.pixel_margin / props.texture_size
                    if props.pixel_margin_enable and props.texture_size > 0
                    else props.margin)

        cfg = UVPackConfig(
            method          = METHODS.get(props.packing_method, 0),
            heuristic       = HEURISTICS.get(props.maxrects_heuristic, 0),
            optimizer       = OPTIMIZERS.get(props.optimizer, 1),
            margin          = margin,
            max_iter        = props.precision,
            time_limit      = props.search_time,
            rotation_step   = rot_step,
            sa_initial_temp = props.sa_initial_temp,
            sa_cooling_rate = props.sa_cooling_rate,
            min_occupancy   = min_occupancy,
        )
        c_out = (UVPlacement * n)()

        try:
            occ = self._lib.uvpack_run(c_islands, n, byref(cfg), c_out)
        except Exception as e:
            raise UVPackException(f"uvpack_run falhou: {e}") from e

        placements = [{'id': c_out[i].id, 'x': c_out[i].x,
                       'y': c_out[i].y, 'angle': c_out[i].angle}
                      for i in range(n)]
        return placements, float(occ)


_instance: UVPackLib | None = None

def get_lib() -> UVPackLib:
    global _instance
    if _instance is None:
        _instance = UVPackLib()
    return _instance
