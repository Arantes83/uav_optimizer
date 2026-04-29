import io
import json
import os
import queue
import struct
import subprocess
import threading

from mathutils import Matrix, Vector

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


UVPM_ENGINE_VERSION = "3.4.4"
UVPM_ENGINE_MARKER = f"release-{UVPM_ENGINE_VERSION}.uvpmi"
UVPM_DEFAULT_INSTALL_ROOT = r"C:\Program Files\UVPackmaster"


class UVPackmasterError(RuntimeError):
    pass


class UvpmOpcode:
    EXECUTE_SCENARIO = 1


class UvpmMessageCode:
    PHASE = 0
    ISLANDS = 3
    OUT_ISLANDS = 4
    LOG = 5


class UvpmPhaseCode:
    DONE = 2


class UvpmRetCode:
    SUCCESS = 0
    NO_SPACE = 2
    WARNING = 8


class UvpmLogType:
    WARNING = 2
    ERROR = 3


class UvpmMapSerializationFlags:
    CONTAINS_FLAGS = 1


class UvpmFaceInputFlags:
    SELECTED = 1


class UvpmOutIslandsSerializationFlags:
    CONTAINS_TRANSFORM = 1
    CONTAINS_IPARAMS = 2
    CONTAINS_FLAGS = 4
    CONTAINS_VERTICES = 8


class UvpmIslandIntParams:
    MAX_COUNT = 16


class UvpmRunResult:
    def __init__(self):
        self.retcode = None
        self.island_faces = None
        self.out_islands = None
        self.logs = []
        self.warning_messages = []
        self.error_messages = []

    @property
    def has_solution(self):
        return self.retcode in {
            UvpmRetCode.SUCCESS,
            UvpmRetCode.NO_SPACE,
            UvpmRetCode.WARNING,
        } and self.island_faces and self.out_islands


def _addon_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _vendor_root():
    return os.path.join(_addon_dir(), "uvpm3_vendor", "scripted_pipeline")


def _packages_dir():
    return os.path.join(_vendor_root(), "engine_packages")


def _scenario_dir():
    return os.path.join(_vendor_root(), "engine_scenarios", "pack-general")


def validate_vendor_files():
    required_paths = (
        os.path.join(_packages_dir(), "__init__.py"),
        os.path.join(_packages_dir(), "pack_utils", "__init__.py"),
        os.path.join(_packages_dir(), "pack_utils", "pack_manager.py"),
        os.path.join(_packages_dir(), "scripted_pipeline.py"),
        os.path.join(_packages_dir(), "utils.py"),
        os.path.join(_packages_dir(), "geom_utils.py"),
        os.path.join(_packages_dir(), "similarity_utils.py"),
        os.path.join(_scenario_dir(), "scenario.py"),
        os.path.join(_scenario_dir(), "scenario.json"),
    )
    missing = [path for path in required_paths if not os.path.exists(path)]
    if missing:
        preview = ", ".join(os.path.relpath(path, _addon_dir()) for path in missing[:6])
        suffix = "..." if len(missing) > 6 else ""
        raise UVPackmasterError(
            "UVPackmaster scripted pipeline is incomplete inside the addon. "
            f"Missing: {preview}{suffix}"
        )


def _normalize_engine_root(path):
    if not path:
        return None
    path = os.path.normpath(os.path.expanduser(path.strip().strip('"')))
    if not path:
        return None
    basename = os.path.basename(path).lower()
    if basename == "engine3":
        return path
    candidate = os.path.join(path, "engine3")
    if os.path.isdir(candidate):
        return candidate
    return path


def _registry_engine_root():
    if winreg is None:
        return None

    keys_to_try = (
        (winreg.HKEY_LOCAL_MACHINE, r"Software\UVPackmaster"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\UVPackmaster"),
    )
    for hive, subkey in keys_to_try:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Engine3InstallPath")
        except OSError:
            continue
        root = _normalize_engine_root(value)
        if root:
            return root
    return None


def _validate_engine_root(root):
    if not root:
        return None
    marker_path = os.path.join(root, UVPM_ENGINE_MARKER)
    exec_path = os.path.join(root, "win", "uvpm.exe")
    if not os.path.isdir(root):
        return None
    if not os.path.isfile(marker_path):
        return None
    if not os.path.isfile(exec_path):
        return None
    return {
        "engine_root": root,
        "exec_path": exec_path,
        "marker_path": marker_path,
    }


def auto_detect_engine_path():
    for source, candidate in (
        ("registry", _registry_engine_root()),
        ("default", _normalize_engine_root(UVPM_DEFAULT_INSTALL_ROOT)),
    ):
        validated = _validate_engine_root(candidate)
        if validated:
            validated["source"] = source
            return validated
    return None


def get_engine_status(configured_path=""):
    configured_root = _normalize_engine_root(configured_path)
    if configured_root:
        validated = _validate_engine_root(configured_root)
        if validated:
            validated["available"] = True
            validated["source"] = "configured"
            validated["display_path"] = configured_root
            return validated
        return {
            "available": False,
            "source": "configured",
            "display_path": configured_root,
            "error": (
                "Configured UVPackmaster path is invalid. "
                "Point to the UVPackmaster install root or directly to 'engine3'."
            ),
        }

    detected = auto_detect_engine_path()
    if detected:
        detected["available"] = True
        detected["display_path"] = detected["engine_root"]
        return detected

    fallback = _normalize_engine_root(UVPM_DEFAULT_INSTALL_ROOT)
    return {
        "available": False,
        "source": "missing",
        "display_path": fallback,
        "error": (
            "UVPackmaster was not found on this machine. "
            "Install it or set the engine path manually."
        ),
    }


def is_uvpackmaster_available(configured_path=""):
    return bool(get_engine_status(configured_path).get("available"))


def _force_read_bytes(stream, byte_count):
    output = bytearray()
    while len(output) < byte_count:
        chunk = stream.read(byte_count - len(output))
        if not chunk:
            raise UVPackmasterError("Not enough output from the UVPackmaster engine.")
        output.extend(chunk)
    return bytes(output)


def _force_read_int(stream):
    return struct.unpack("i", _force_read_bytes(stream, 4))[0]


def _force_read_ints(stream, count):
    return struct.unpack("i" * count, _force_read_bytes(stream, count * 4))


def _force_read_floats(stream, count):
    return struct.unpack("f" * count, _force_read_bytes(stream, count * 4))


def _force_read_elems(stream, elem_mark, count):
    return struct.unpack(elem_mark * count, _force_read_bytes(stream, struct.calcsize(elem_mark * count)))


def _read_int_array(stream):
    count = _force_read_int(stream)
    if count <= 0:
        return ()
    return _force_read_ints(stream, count)


def _encode_string(value, encoding="utf-8"):
    encoded = value.encode(encoding)
    return struct.pack("i", len(encoded)) + encoded


def _decode_string(stream, encoding="utf-8"):
    length = _force_read_int(stream)
    return _force_read_bytes(stream, length).decode(encoding)


def _recv_message(stream):
    msg_size = _force_read_int(stream)
    return io.BytesIO(_force_read_bytes(stream, msg_size))


def _connection_thread(stream, out_queue):
    try:
        while True:
            out_queue.put(_recv_message(stream))
    except Exception as exc:
        out_queue.put(exc)


def _send_finish_confirmation(engine_proc):
    engine_proc.stdin.write(b"fin")
    engine_proc.stdin.flush()


def _blender_threads():
    try:
        import bpy

        return max(1, int(getattr(bpy.context.preferences.system, "threads", 0) or 0))
    except Exception:
        return max(1, os.cpu_count() or 1)


def _map_scale_mode(scale_mode):
    if scale_mode == "MAX_SCALE":
        return 0
    if scale_mode in {"LOCKED", "CUSTOM"}:
        return 1
    return 0


def build_script_params(props):
    params = {
        "pack_op_type": 0,
        "pinned_as_others": False,
        "precision": int(props.precision),
        "margin": float(props.margin),
        "scale_mode": _map_scale_mode(props.scale_mode),
        "arrange_non_packed": False,
        "pack_strategy": 0,
        "rotation_enable": bool(props.rotation_enable),
        "pre_rotation_disable": False,
        "rotation_step": int(props.rotation_step),
        "flipping_enable": False,
        "lock_overlapping_mode": 0,
        "normalize_scale": False,
        "target_boxes": [[0.0, 0.0, 1.0, 1.0]],
        "__skip_topology_parsing": False,
        "__disable_immediate_uv_update": True,
        "__disable_tips": True,
        "__pack_ratio": 1.0,
        "__sys_path": [
            _packages_dir(),
            _scenario_dir(),
        ],
    }

    if getattr(props, "pixel_margin_enable", False):
        params["pixel_margin"] = int(props.pixel_margin)
        params["pixel_margin_tex_size"] = int(props.texture_size)
        params["pixel_perfect_align"] = False

    if getattr(props, "search_time", 0.0) > 0.01:
        params["heuristic_search_time"] = float(props.search_time)
        params["heuristic_max_wait_time"] = max(1.0, float(props.search_time))
        if getattr(props, "advanced_heuristic", False):
            params["advanced_heuristic"] = True

    if getattr(props, "scale_mode", "MAX_SCALE") == "CUSTOM":
        params["__uav_custom_scale"] = float(getattr(props, "custom_scale", 1.0))

    return params


def serialize_uv_maps(bm, uv_layer):
    face_id_len_array = []
    uv_coord_array = []
    vert_idx_array = []
    face_flags_array = []
    face_indices = []
    next_vert_idx = 0

    for face in bm.faces:
        face_indices.append(face.index)
        face_id_len_array.extend((face.index, len(face.verts)))
        face_flags_array.append(UvpmFaceInputFlags.SELECTED)
        for loop in face.loops:
            uv = loop[uv_layer].uv
            uv_coord_array.extend((float(uv.x), float(uv.y)))
            vert_idx_array.append(next_vert_idx)
            next_vert_idx += 1

    if not face_indices:
        return b"", 0

    payload = bytearray()
    payload += struct.pack("i", UvpmMapSerializationFlags.CONTAINS_FLAGS)
    payload += struct.pack("i", len(face_indices))
    payload += struct.pack("i" * len(face_id_len_array), *face_id_len_array)
    payload += struct.pack("i", len(vert_idx_array))
    payload += struct.pack("f" * len(uv_coord_array), *uv_coord_array)
    payload += struct.pack("i" * len(vert_idx_array), *vert_idx_array)
    payload += struct.pack("i" * len(face_flags_array), *face_flags_array)

    uv_sets = ("selected_islands", "unselected_islands", "pinned_islands")
    payload += struct.pack("i", len(uv_sets))
    for uv_set in uv_sets:
        payload += _encode_string(uv_set)

    payload += struct.pack("i", 0)
    return bytes(payload), len(face_indices)


def _parse_islands_message(msg):
    set_sizes = _read_int_array(msg)
    _flags = _read_int_array(msg)
    island_count = len(_flags)
    islands = []
    for _ in range(island_count):
        islands.append(tuple(_read_int_array(msg)))
    return islands


def _parse_out_islands_message(msg):
    island_count = _force_read_int(msg)
    serialization_flags = _force_read_int(msg)

    contains_transform = bool(serialization_flags & UvpmOutIslandsSerializationFlags.CONTAINS_TRANSFORM)
    contains_iparams = bool(serialization_flags & UvpmOutIslandsSerializationFlags.CONTAINS_IPARAMS)
    contains_flags = bool(serialization_flags & UvpmOutIslandsSerializationFlags.CONTAINS_FLAGS)
    contains_vertices = bool(serialization_flags & UvpmOutIslandsSerializationFlags.CONTAINS_VERTICES)

    if contains_iparams:
        _ = _read_int_array(msg)

    island_indices = _force_read_ints(msg, island_count)

    if contains_transform:
        transform_raw = _force_read_floats(msg, island_count * 9)
    else:
        transform_raw = None

    if contains_iparams:
        _ = _force_read_elems(msg, "i", UvpmIslandIntParams.MAX_COUNT * island_count)

    if contains_flags:
        flags_array = _force_read_ints(msg, island_count)
    else:
        flags_array = (None,) * island_count

    face_orders = []
    vertices_array = []
    if contains_vertices:
        for _ in range(island_count):
            face_orders.append(tuple(_read_int_array(msg)))
            vert_count = _force_read_int(msg)
            verts_raw = _force_read_floats(msg, vert_count * 2)
            vertices_array.append(
                [(verts_raw[i], verts_raw[i + 1]) for i in range(0, len(verts_raw), 2)]
            )
    else:
        face_orders = [None] * island_count
        vertices_array = [None] * island_count

    out_islands = []
    for idx in range(island_count):
        matrix = None
        if transform_raw is not None:
            base = idx * 9
            matrix = Matrix((
                transform_raw[base:base + 3],
                transform_raw[base + 3:base + 6],
                transform_raw[base + 6:base + 9],
            ))
        out_islands.append({
            "index": island_indices[idx],
            "transform": matrix,
            "flags": flags_array[idx],
            "face_order": face_orders[idx],
            "vertices": vertices_array[idx],
        })
    return out_islands


def _collect_engine_result(proc):
    result = UvpmRunResult()
    progress_queue = queue.Queue()
    worker = threading.Thread(target=_connection_thread, args=(proc.stdout, progress_queue), daemon=True)
    worker.start()

    while True:
        item = progress_queue.get()
        if isinstance(item, Exception):
            if proc.poll() is None:
                proc.terminate()
            raise UVPackmasterError(f"UVPackmaster communication failed: {item}")

        msg = item
        msg_code = _force_read_int(msg)

        if msg_code == UvpmMessageCode.PHASE:
            phase = _force_read_int(msg)
            if phase == UvpmPhaseCode.DONE:
                _send_finish_confirmation(proc)
                proc.wait(timeout=300)
                worker.join(timeout=5)
                result.retcode = proc.returncode
                return result
        elif msg_code == UvpmMessageCode.ISLANDS:
            result.island_faces = _parse_islands_message(msg)
        elif msg_code == UvpmMessageCode.OUT_ISLANDS:
            result.out_islands = _parse_out_islands_message(msg)
        elif msg_code == UvpmMessageCode.LOG:
            log_type = _force_read_int(msg)
            log_string = _decode_string(msg)
            _ = _force_read_int(msg)
            result.logs.append((log_type, log_string))
            if log_type == UvpmLogType.WARNING:
                result.warning_messages.append(log_string)
            elif log_type == UvpmLogType.ERROR:
                result.error_messages.append(log_string)


def run_uvpackmaster(bm, uv_layer, props):
    status = get_engine_status(getattr(props, "uvpm_engine_path", ""))
    if not status.get("available"):
        raise UVPackmasterError(status.get("error", "UVPackmaster engine not available."))

    validate_vendor_files()
    serialized_maps, selected_count = serialize_uv_maps(bm, uv_layer)
    if selected_count <= 0:
        raise UVPackmasterError("No UV faces available for UVPackmaster packing.")

    script_params = build_script_params(props)
    payload = _encode_string(json.dumps(script_params)) + serialized_maps

    engine_exec = status["exec_path"]
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    args = [
        engine_exec,
        "-E",
        "-o", str(UvpmOpcode.EXECUTE_SCENARIO),
        "-t", str(_blender_threads()),
        "-b", str(os.getpid()),
        "-p",
    ]

    env = os.environ.copy()
    engine_win_dir = os.path.dirname(engine_exec)
    env["PATH"] = engine_win_dir + os.pathsep + env.get("PATH", "")

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        env=env,
    )
    proc.stdin.write(payload)
    proc.stdin.flush()
    return _collect_engine_result(proc)


def _apply_transform_to_faces(face_group, uv_layer, matrix):
    for face in face_group:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            transformed = matrix @ Vector((uv.x, uv.y, 1.0))
            if abs(transformed.z) <= 1e-12:
                raise UVPackmasterError("UVPackmaster returned a singular transform.")
            loop[uv_layer].uv = (transformed.x / transformed.z, transformed.y / transformed.z)


def _apply_vertices_to_faces(face_group, ordered_face_indices, vertices, uv_layer):
    face_map = {face.index: face for face in face_group}
    cursor = 0
    for face_index in ordered_face_indices:
        face = face_map.get(face_index)
        if face is None:
            raise UVPackmasterError("UVPackmaster returned face indices that do not match the current mesh.")
        for loop in face.loops:
            if cursor >= len(vertices):
                raise UVPackmasterError("UVPackmaster returned an incomplete vertex payload.")
            uv = vertices[cursor]
            loop[uv_layer].uv = (uv[0], uv[1])
            cursor += 1
    if cursor != len(vertices):
        raise UVPackmasterError("UVPackmaster returned extra vertex data.")


def apply_uvpackmaster_result(bm, uv_layer, run_result, custom_scale=1.0):
    if not run_result.island_faces or not run_result.out_islands:
        raise UVPackmasterError("UVPackmaster did not return island placement data.")

    face_lookup = {face.index: face for face in bm.faces}
    island_lookup = []
    for face_indices in run_result.island_faces:
        island_lookup.append([face_lookup[index] for index in face_indices if index in face_lookup])

    for out_island in run_result.out_islands:
        island_index = out_island["index"]
        if island_index < 0 or island_index >= len(island_lookup):
            raise UVPackmasterError("UVPackmaster returned an invalid island index.")
        face_group = island_lookup[island_index]
        if not face_group:
            continue
        if out_island["vertices"] is not None and out_island["face_order"] is not None:
            _apply_vertices_to_faces(face_group, out_island["face_order"], out_island["vertices"], uv_layer)
        elif out_island["transform"] is not None:
            _apply_transform_to_faces(face_group, uv_layer, out_island["transform"])

    custom_scale = float(custom_scale)
    if abs(custom_scale - 1.0) > 1e-6:
        center = Vector((0.5, 0.5))
        for face in bm.faces:
            for loop in face.loops:
                uv = loop[uv_layer].uv
                loop[uv_layer].uv = center + (uv - center) * custom_scale
