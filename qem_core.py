import copy
import heapq
import numpy as np

OPTIM_VALENCE = 6
VALENCE_WEIGHT = 1


class MeshQEM:
    """Lightweight NumPy-only port of the mesh_simplification core.

    Adapted for Blender add-on use: no scipy / sklearn / tqdm, and built from
    in-memory vertex/face arrays instead of file IO.
    """

    def __init__(self, vertices, faces):
        self.vs = np.asarray(vertices, dtype=np.float64).copy()
        self.faces = np.asarray(faces, dtype=np.int32).copy()
        if self.faces.ndim != 2 or self.faces.shape[1] != 3:
            raise ValueError("MeshQEM requires triangulated faces (N x 3).")
        self.compute_face_normals()
        self.compute_face_center()
        self.build_topology()
        self.simp = False
        self.pool_hash = []
        self.unpool_hash = {}

    def compute_face_normals(self):
        if len(self.faces) == 0:
            self.fn = np.zeros((0, 3), dtype=np.float64)
            self.fa = np.zeros((0,), dtype=np.float64)
            return
        face_normals = np.cross(
            self.vs[self.faces[:, 1]] - self.vs[self.faces[:, 0]],
            self.vs[self.faces[:, 2]] - self.vs[self.faces[:, 0]],
        )
        norm = np.linalg.norm(face_normals, axis=1, keepdims=True) + 1e-24
        face_areas = 0.5 * np.sqrt((face_normals ** 2).sum(axis=1))
        face_normals = face_normals / norm
        self.fn = face_normals
        self.fa = face_areas

    def compute_face_center(self):
        if len(self.faces) == 0:
            self.fc = np.zeros((0, 3), dtype=np.float64)
            return
        self.fc = np.sum(self.vs[self.faces], axis=1) / 3.0

    def build_topology(self):
        self.vf = [set() for _ in range(len(self.vs))]
        self.v2v = [set() for _ in range(len(self.vs))]
        edge_map = {}
        edge_faces = {}
        for fi, f in enumerate(self.faces):
            a, b, c = int(f[0]), int(f[1]), int(f[2])
            self.vf[a].add(fi)
            self.vf[b].add(fi)
            self.vf[c].add(fi)
            pairs = ((a, b), (b, c), (c, a))
            for u, v in pairs:
                self.v2v[u].add(v)
                self.v2v[v].add(u)
                e = tuple(sorted((u, v)))
                if e not in edge_map:
                    edge_map[e] = len(edge_map)
                edge_faces.setdefault(e, []).append(fi)
        self.edges = np.asarray(list(edge_map.keys()), dtype=np.int32)
        self.edge_faces = edge_faces
        self.v2v = [sorted(list(s)) for s in self.v2v]

    def has_boundary(self):
        return any(len(fs) != 2 for fs in self.edge_faces.values())

    def simplification(self, target_v, valence_aware=True, midpoint=False, preserve_boundary=True):
        vs, vf, fn, fc, edges = self.vs, self.vf, self.fn, self.fc, self.edges

        Q_s = [None for _ in range(len(vs))]
        for i, v in enumerate(vs):
            f_s = np.array(sorted(list(vf[i])), dtype=np.int32)
            if len(f_s) == 0:
                Q_s[i] = np.zeros((4, 4), dtype=np.float64)
                continue
            fc_s = fc[f_s]
            fn_s = fn[f_s]
            d_s = -1.0 * np.sum(fn_s * fc_s, axis=1, keepdims=True)
            abcd_s = np.concatenate([fn_s, d_s], axis=1)
            Q_s[i] = np.matmul(abcd_s.T, abcd_s)

        E_heap = []
        for e in edges:
            v0, v1 = int(e[0]), int(e[1])
            if preserve_boundary and len(vf[v0].intersection(vf[v1])) != 2:
                continue
            E_new = self._compute_qem_cost(v0, v1, Q_s, vf, valence_aware, midpoint)
            heapq.heappush(E_heap, (float(E_new), (v0, v1)))

        simp_mesh = copy.deepcopy(self)
        vi_mask = np.ones((len(simp_mesh.vs),), dtype=np.bool_)
        fi_mask = np.ones((len(simp_mesh.faces),), dtype=np.bool_)
        vert_map = [{i} for i in range(len(simp_mesh.vs))]

        while int(np.sum(vi_mask)) > int(target_v):
            if not E_heap:
                break
            _err, (vi_0, vi_1) = heapq.heappop(E_heap)
            if not vi_mask[vi_0] or not vi_mask[vi_1]:
                continue
            shared_vv = list(set(simp_mesh.v2v[vi_0]).intersection(set(simp_mesh.v2v[vi_1])))
            merged_faces = simp_mesh.vf[vi_0].intersection(simp_mesh.vf[vi_1])

            if len(shared_vv) != 2:
                continue
            if preserve_boundary and len(merged_faces) != 2:
                continue
            if len(merged_faces) < 1:
                continue

            self.edge_collapse(
                simp_mesh, vi_0, vi_1, merged_faces, vi_mask, fi_mask,
                vert_map, Q_s, E_heap, valence_aware, midpoint, preserve_boundary,
            )

        self.rebuild_mesh(simp_mesh, vi_mask, fi_mask, vert_map)
        simp_mesh.simp = True
        self.build_hash(simp_mesh, vi_mask, vert_map)
        return simp_mesh

    def edge_based_simplification(self, target_v, valence_aware=True, preserve_boundary=True):
        vs, vf, edges = self.vs, self.vf, self.edges
        edge_len = np.linalg.norm(vs[edges][:, 0, :] - vs[edges][:, 1, :], axis=1)
        E_heap = []
        for i, e in enumerate(edges):
            v0, v1 = int(e[0]), int(e[1])
            if preserve_boundary and len(vf[v0].intersection(vf[v1])) != 2:
                continue
            heapq.heappush(E_heap, (float(edge_len[i]), (v0, v1)))

        simp_mesh = copy.deepcopy(self)
        vi_mask = np.ones((len(simp_mesh.vs),), dtype=np.bool_)
        fi_mask = np.ones((len(simp_mesh.faces),), dtype=np.bool_)
        vert_map = [{i} for i in range(len(simp_mesh.vs))]

        while int(np.sum(vi_mask)) > int(target_v):
            if not E_heap:
                break
            _err, (vi_0, vi_1) = heapq.heappop(E_heap)
            if not vi_mask[vi_0] or not vi_mask[vi_1]:
                continue
            shared_vv = list(set(simp_mesh.v2v[vi_0]).intersection(set(simp_mesh.v2v[vi_1])))
            merged_faces = simp_mesh.vf[vi_0].intersection(simp_mesh.vf[vi_1])
            if len(shared_vv) != 2:
                continue
            if preserve_boundary and len(merged_faces) != 2:
                continue
            if len(merged_faces) < 1:
                continue
            self.edge_based_collapse(
                simp_mesh, vi_0, vi_1, merged_faces, vi_mask, fi_mask,
                vert_map, E_heap, valence_aware, preserve_boundary,
            )

        self.rebuild_mesh(simp_mesh, vi_mask, fi_mask, vert_map)
        simp_mesh.simp = True
        self.build_hash(simp_mesh, vi_mask, vert_map)
        return simp_mesh

    def _compute_qem_cost(self, v0, v1, Q_s, vf, valence_aware, midpoint):
        Q_new = Q_s[v0] + Q_s[v1]
        v_new = self._optimal_vertex_position(self.vs, v0, v1, Q_new, midpoint)
        v4_new = np.concatenate([v_new, np.array([1.0])])
        valence_penalty = 1.0
        if valence_aware:
            merged_faces = vf[v0].intersection(vf[v1])
            valence_new = len(vf[v0].union(vf[v1]).difference(merged_faces))
            valence_penalty = self.valence_weight(valence_new)
        return float(np.matmul(v4_new, np.matmul(Q_new, v4_new.T)) * valence_penalty)

    @staticmethod
    def _optimal_vertex_position(vertices, v0, v1, q_new, midpoint):
        p0 = vertices[v0]
        p1 = vertices[v1]
        if midpoint:
            return 0.5 * (p0 + p1)

        q_lp = np.eye(4, dtype=np.float64)
        q_lp[:3] = q_new[:3]
        try:
            q_lp_inv = np.linalg.inv(q_lp)
            return np.matmul(
                q_lp_inv,
                np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float64).reshape(-1, 1),
            ).reshape(-1)[:3]
        except np.linalg.LinAlgError:
            return 0.5 * (p0 + p1)

    def edge_collapse(self, simp_mesh, vi_0, vi_1, merged_faces, vi_mask, fi_mask,
                      vert_map, Q_s, E_heap, valence_aware, midpoint, preserve_boundary):
        shared_vv = list(set(simp_mesh.v2v[vi_0]).intersection(set(simp_mesh.v2v[vi_1])))
        new_vi_0 = set(simp_mesh.v2v[vi_0]).union(set(simp_mesh.v2v[vi_1])).difference({vi_0, vi_1})
        simp_mesh.vf[vi_0] = simp_mesh.vf[vi_0].union(simp_mesh.vf[vi_1]).difference(merged_faces)
        simp_mesh.vf[vi_1] = set()
        for sv in shared_vv[:2]:
            simp_mesh.vf[sv] = simp_mesh.vf[sv].difference(merged_faces)

        simp_mesh.v2v[vi_0] = sorted(list(new_vi_0))
        for v in simp_mesh.v2v[vi_1]:
            if v != vi_0:
                simp_mesh.v2v[v] = sorted(list(set(simp_mesh.v2v[v]).difference({vi_1}).union({vi_0})))
        simp_mesh.v2v[vi_1] = []
        vi_mask[vi_1] = False

        vert_map[vi_0] = vert_map[vi_0].union(vert_map[vi_1]).union({vi_1})
        vert_map[vi_1] = set()
        if len(merged_faces):
            fi_mask[np.array(list(merged_faces), dtype=np.int32)] = False

        Q_s[vi_0] = Q_s[vi_0] + Q_s[vi_1]
        Q_s[vi_1] = np.zeros((4, 4), dtype=np.float64)
        simp_mesh.vs[vi_0] = self._optimal_vertex_position(
            simp_mesh.vs, vi_0, vi_1, Q_s[vi_0], midpoint
        )

        for vv_i in simp_mesh.v2v[vi_0]:
            merged_local = simp_mesh.vf[vi_0].intersection(simp_mesh.vf[vv_i])
            if preserve_boundary and len(merged_local) != 2:
                continue
            E_new = self._compute_qem_cost(vi_0, vv_i, Q_s, simp_mesh.vf, valence_aware, midpoint)
            heapq.heappush(E_heap, (float(E_new), (vi_0, vv_i)))

    def edge_based_collapse(self, simp_mesh, vi_0, vi_1, merged_faces, vi_mask, fi_mask,
                            vert_map, E_heap, valence_aware, preserve_boundary):
        shared_vv = list(set(simp_mesh.v2v[vi_0]).intersection(set(simp_mesh.v2v[vi_1])))
        new_vi_0 = set(simp_mesh.v2v[vi_0]).union(set(simp_mesh.v2v[vi_1])).difference({vi_0, vi_1})
        simp_mesh.vf[vi_0] = simp_mesh.vf[vi_0].union(simp_mesh.vf[vi_1]).difference(merged_faces)
        simp_mesh.vf[vi_1] = set()
        for sv in shared_vv[:2]:
            simp_mesh.vf[sv] = simp_mesh.vf[sv].difference(merged_faces)

        simp_mesh.v2v[vi_0] = sorted(list(new_vi_0))
        for v in simp_mesh.v2v[vi_1]:
            if v != vi_0:
                simp_mesh.v2v[v] = sorted(list(set(simp_mesh.v2v[v]).difference({vi_1}).union({vi_0})))
        simp_mesh.v2v[vi_1] = []
        vi_mask[vi_1] = False

        vert_map[vi_0] = vert_map[vi_0].union(vert_map[vi_1]).union({vi_1})
        vert_map[vi_1] = set()
        if len(merged_faces):
            fi_mask[np.array(list(merged_faces), dtype=np.int32)] = False

        simp_mesh.vs[vi_0] = 0.5 * (simp_mesh.vs[vi_0] + simp_mesh.vs[vi_1])

        for vv_i in simp_mesh.v2v[vi_0]:
            merged_local = simp_mesh.vf[vi_0].intersection(simp_mesh.vf[vv_i])
            if preserve_boundary and len(merged_local) != 2:
                continue
            edge_len = np.linalg.norm(simp_mesh.vs[vi_0] - simp_mesh.vs[vv_i])
            if valence_aware:
                valence_new = len(simp_mesh.vf[vi_0].union(simp_mesh.vf[vv_i]).difference(merged_local))
                edge_len *= self.valence_weight(valence_new)
            heapq.heappush(E_heap, (float(edge_len), (vi_0, vv_i)))

    @staticmethod
    def valence_weight(valence_new):
        valence_penalty = abs(int(valence_new) - OPTIM_VALENCE) * VALENCE_WEIGHT + 1
        if int(valence_new) == 3:
            valence_penalty *= 100000
        return float(valence_penalty)

    @staticmethod
    def rebuild_mesh(simp_mesh, vi_mask, fi_mask, vert_map):
        face_map = dict(zip(np.arange(len(vi_mask)), np.cumsum(vi_mask) - 1))
        simp_mesh.vs = simp_mesh.vs[vi_mask]

        vert_dict = {}
        for i, vm in enumerate(vert_map):
            for j in vm:
                vert_dict[j] = i

        for i, f in enumerate(simp_mesh.faces):
            simp_mesh.faces[i] = [vert_dict.get(int(f[0]), int(f[0])), vert_dict.get(int(f[1]), int(f[1])), vert_dict.get(int(f[2]), int(f[2]))]

        simp_mesh.faces = simp_mesh.faces[fi_mask]
        for i, f in enumerate(simp_mesh.faces):
            simp_mesh.faces[i] = [face_map[int(f[0])], face_map[int(f[1])], face_map[int(f[2])]]

        simp_mesh.compute_face_normals()
        simp_mesh.compute_face_center()
        simp_mesh.build_topology()

    @staticmethod
    def build_hash(simp_mesh, vi_mask, vert_map):
        pool_hash = {}
        unpool_hash = {}
        for simp_i, idx in enumerate(np.where(vi_mask)[0]):
            if len(vert_map[idx]) == 0:
                continue
            for org_i in vert_map[idx]:
                pool_hash[org_i] = simp_i
            unpool_hash[simp_i] = list(vert_map[idx])
        simp_mesh.pool_hash = sorted(pool_hash.items(), key=lambda x: x[0])
        simp_mesh.unpool_hash = unpool_hash
