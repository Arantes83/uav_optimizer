"""Shared UV utilities used by packing and unwrap modules."""

from collections import defaultdict
import math


def _get_uv_islands(bm, uv_layer):
    """Partition UV faces into connected island groups."""
    epsilon = 1e-5

    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    if not bm.faces:
        return []

    max_face_index = max(face.index for face in bm.faces)
    parent = list(range(max_face_index + 1))
    rank = [0] * (max_face_index + 1)

    def find(parent, index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(parent, rank, a, b):
        root_a = find(parent, a)
        root_b = find(parent, b)
        if root_a == root_b:
            return
        if rank[root_a] < rank[root_b]:
            parent[root_a] = root_b
        elif rank[root_a] > rank[root_b]:
            parent[root_b] = root_a
        else:
            parent[root_b] = root_a
            rank[root_a] += 1

    def same_uv_edge(loop_a, loop_b):
        uv_a0 = loop_a[uv_layer].uv
        uv_a1 = loop_a.link_loop_next[uv_layer].uv
        uv_b0 = loop_b[uv_layer].uv
        uv_b1 = loop_b.link_loop_next[uv_layer].uv
        same_direction = (uv_a0 - uv_b0).length <= epsilon and (uv_a1 - uv_b1).length <= epsilon
        opposite_direction = (uv_a0 - uv_b1).length <= epsilon and (uv_a1 - uv_b0).length <= epsilon
        return same_direction or opposite_direction

    for edge in bm.edges:
        loops = list(edge.link_loops)
        for i in range(len(loops)):
            face_a = loops[i].face
            for j in range(i + 1, len(loops)):
                face_b = loops[j].face
                if face_a is face_b:
                    continue
                if same_uv_edge(loops[i], loops[j]):
                    union(parent, rank, face_a.index, face_b.index)

    islands = defaultdict(list)
    for face in bm.faces:
        islands[find(parent, face.index)].append(face)
    return list(islands.values())


def _bounds(faces, uv_layer):
    """Get AABB of a UV island."""
    min_u = min_v = float("inf")
    max_u = max_v = float("-inf")
    for face in faces:
        for loop in face.loops:
            u, v = loop[uv_layer].uv
            if u < min_u:
                min_u = u
            if v < min_v:
                min_v = v
            if u > max_u:
                max_u = u
            if v > max_v:
                max_v = v
    return min_u, min_v, max_u, max_v


def _area(faces, uv_layer):
    """Compute 2D UV area using fan triangulation."""
    area = 0.0
    for face in faces:
        uvs = [loop[uv_layer].uv for loop in face.loops]
        for index in range(1, len(uvs) - 1):
            area += abs(
                (uvs[index].x - uvs[0].x) * (uvs[index + 1].y - uvs[0].y)
                - (uvs[index + 1].x - uvs[0].x) * (uvs[index].y - uvs[0].y)
            ) * 0.5
    return area


def _normalize(faces, uv_layer):
    """Move a UV island to the origin and return (width, height)."""
    min_u, min_v, max_u, max_v = _bounds(faces, uv_layer)
    for face in faces:
        for loop in face.loops:
            loop[uv_layer].uv.x -= min_u
            loop[uv_layer].uv.y -= min_v
    return max_u - min_u, max_v - min_v


def _rotate(faces, uv_layer, angle_deg):
    """Rotate a UV island around its center."""
    if abs(angle_deg) < 0.01:
        return
    min_u, min_v, max_u, max_v = _bounds(faces, uv_layer)
    center_u = (min_u + max_u) * 0.5
    center_v = (min_v + max_v) * 0.5
    radians = math.radians(angle_deg)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    for face in faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            dx = uv.x - center_u
            dy = uv.y - center_v
            uv.x = center_u + dx * cos_a - dy * sin_a
            uv.y = center_v + dx * sin_a + dy * cos_a
    new_min_u, new_min_v, _, _ = _bounds(faces, uv_layer)
    for face in faces:
        for loop in face.loops:
            loop[uv_layer].uv.x -= new_min_u
            loop[uv_layer].uv.y -= new_min_v


def _translate(faces, uv_layer, delta_u, delta_v):
    """Translate a UV island."""
    for face in faces:
        for loop in face.loops:
            loop[uv_layer].uv.x += delta_u
            loop[uv_layer].uv.y += delta_v


def _scale(faces, uv_layer, scale_u, scale_v):
    """Scale a UV island."""
    for face in faces:
        for loop in face.loops:
            loop[uv_layer].uv.x *= scale_u
            loop[uv_layer].uv.y *= scale_v


def _save(bm, uv_layer):
    """Save all UV coordinates for later restore."""
    return {loop.index: loop[uv_layer].uv.copy() for face in bm.faces for loop in face.loops}


def _restore(bm, uv_layer, saved):
    """Restore UV coordinates from a saved state."""
    for face in bm.faces:
        for loop in face.loops:
            loop[uv_layer].uv = saved[loop.index].copy()


def _rotdims(width, height, angle_deg):
    """Get the axis-aligned bounds of a rotated rectangle."""
    if abs(angle_deg) < 0.01:
        return width, height
    if abs(angle_deg - 90.0) < 0.01 or abs(angle_deg - 270.0) < 0.01:
        return height, width
    radians = math.radians(angle_deg)
    cos_a = abs(math.cos(radians))
    sin_a = abs(math.sin(radians))
    return width * cos_a + height * sin_a, width * sin_a + height * cos_a


def _eff_margin(props):
    """Convert pixel margin to UV units when enabled."""
    if props.pixel_margin_enable and props.texture_size > 0:
        return props.pixel_margin / props.texture_size
    return props.margin


def _angles(props):
    """Build the list of rotation angles from addon properties."""
    if not props.rotation_enable:
        return [0.0]
    step = int(props.rotation_step)
    return [float(angle) for angle in range(0, 360, step)]


def _scale_island_from_center(faces, uv_layer, factor):
    """Scale a UV island from its center."""
    min_u, min_v, max_u, max_v = _bounds(faces, uv_layer)
    center_u = (min_u + max_u) * 0.5
    center_v = (min_v + max_v) * 0.5
    for face in faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            uv.x = center_u + (uv.x - center_u) * factor
            uv.y = center_v + (uv.y - center_v) * factor
