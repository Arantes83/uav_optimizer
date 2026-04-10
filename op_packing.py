"""
op_packing.py — Island Packing Engine for UV Atlas Optimization
================================================================
UAV Topology Optimizer — Standalone packing module.

Operators:
  UAV_OT_uv_pack       — Island packing engine (Skyline / MaxRects)
  UAV_OT_uv_pack_reset — Reset stored best occupancy

This module implements optimized 2D bin packing algorithms for UV islands:
  - Skyline: Linear-time greedy placement
  - MaxRects: Rectangle packing with multiple heuristics
  - Optimizers: Iterative search, Simulated Annealing
"""

import bpy
import bmesh
import math
import random
import time
from collections import defaultdict
from mathutils import Vector
from bpy.types import Operator
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty,
    StringProperty, FloatVectorProperty,
)


# ═══════════════════════════════════════════════════════════════════════════
#  UV ISLAND & GEOMETRY UTILITIES (SHARED)
# ═══════════════════════════════════════════════════════════════════════════

def _get_uv_islands(bm, uv_layer):
    """Partition UV faces into connected island groups."""
    EPSILON = 1e-5
    face_visited = set()
    islands = []
    edge_face_map = defaultdict(list)
    for face in bm.faces:
        for loop in face.loops:
            uv0 = loop[uv_layer].uv.copy().freeze()
            uv1 = loop.link_loop_next[uv_layer].uv.copy().freeze()
            edge_face_map[loop.edge.index].append((face.index, uv0, uv1))

    face_neighbors = defaultdict(set)
    for entries in edge_face_map.values():
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                fi, uv0i, uv1i = entries[i]
                fj, uv0j, uv1j = entries[j]
                match = (
                    ((uv0i - uv0j).length < EPSILON and
                     (uv1i - uv1j).length < EPSILON) or
                    ((uv0i - uv1j).length < EPSILON and
                     (uv1i - uv0j).length < EPSILON)
                )
                if match:
                    face_neighbors[fi].add(fj)
                    face_neighbors[fj].add(fi)

    face_map  = {f.index: f for f in bm.faces}
    all_faces = set(face_map)
    while all_faces - face_visited:
        seed  = next(iter(all_faces - face_visited))
        stack = [seed]
        group = set()
        while stack:
            fi = stack.pop()
            if fi in face_visited:
                continue
            face_visited.add(fi)
            group.add(fi)
            stack.extend(face_neighbors[fi] - face_visited)
        islands.append([face_map[i] for i in group])
    return islands


def _bounds(faces, ul):
    """Get AABB of UV island."""
    mn_u = mn_v = float('inf')
    mx_u = mx_v = float('-inf')
    for f in faces:
        for l in f.loops:
            u, v = l[ul].uv
            if u < mn_u: mn_u = u
            if v < mn_v: mn_v = v
            if u > mx_u: mx_u = u
            if v > mx_v: mx_v = v
    return mn_u, mn_v, mx_u, mx_v


def _area(faces, ul):
    """Compute 2D area of UV faces (shoelace formula)."""
    a = 0.0
    for f in faces:
        uvs = [l[ul].uv for l in f.loops]
        for i in range(1, len(uvs) - 1):
            a += abs((uvs[i].x - uvs[0].x) * (uvs[i + 1].y - uvs[0].y) -
                     (uvs[i + 1].x - uvs[0].x) * (uvs[i].y - uvs[0].y)) * 0.5
    return a


def _normalize(faces, ul):
    """Move UV island to origin (0,0)."""
    mn_u, mn_v, mx_u, mx_v = _bounds(faces, ul)
    for f in faces:
        for l in f.loops:
            l[ul].uv.x -= mn_u
            l[ul].uv.y -= mn_v
    return mx_u - mn_u, mx_v - mn_v


def _rotate(faces, ul, angle_deg):
    """Rotate UV island around its center by angle_deg degrees."""
    if abs(angle_deg) < 0.01:
        return
    mn_u, mn_v, mx_u, mx_v = _bounds(faces, ul)
    cx, cy = (mn_u + mx_u) * 0.5, (mn_v + mx_v) * 0.5
    rad = math.radians(angle_deg)
    ca, sa = math.cos(rad), math.sin(rad)
    for f in faces:
        for l in f.loops:
            uv = l[ul].uv
            dx, dy = uv.x - cx, uv.y - cy
            uv.x = cx + dx * ca - dy * sa
            uv.y = cy + dx * sa + dy * ca
    mn2, mv2, _, _ = _bounds(faces, ul)
    for f in faces:
        for l in f.loops:
            l[ul].uv.x -= mn2
            l[ul].uv.y -= mv2


def _translate(faces, ul, du, dv):
    """Translate UV island by (du, dv)."""
    for f in faces:
        for l in f.loops:
            l[ul].uv.x += du
            l[ul].uv.y += dv


def _scale(faces, ul, sx, sy):
    """Scale UV island by (sx, sy)."""
    for f in faces:
        for l in f.loops:
            l[ul].uv.x *= sx
            l[ul].uv.y *= sy


def _save(bm, ul):
    """Save all UV coordinates for later restore."""
    return {l.index: l[ul].uv.copy() for f in bm.faces for l in f.loops}


def _restore(bm, ul, saved):
    """Restore UV coordinates from saved state."""
    for f in bm.faces:
        for l in f.loops:
            l[ul].uv = saved[l.index].copy()


def _rotdims(w, h, a):
    """Get rotated dimensions of rectangle at angle a (degrees)."""
    if abs(a) < 0.01:
        return w, h
    if abs(a - 90) < 0.01 or abs(a - 270) < 0.01:
        return h, w
    rad = math.radians(a)
    ca, sa = abs(math.cos(rad)), abs(math.sin(rad))
    return w * ca + h * sa, w * sa + h * ca


def _eff_margin(p):
    """Convert pixel margin to UV units."""
    return (p.pixel_margin / p.texture_size
            if p.pixel_margin_enable and p.texture_size > 0
            else p.margin)


def _angles(p):
    """Build list of rotation angles from property."""
    if not p.rotation_enable:
        return [0.0]
    step = int(p.rotation_step)
    return [float(a) for a in range(0, 360, step)]


def _scale_island_from_center(faces, uv_layer, factor):
    """Scale UV island from its center."""
    mn_u, mn_v, mx_u, mx_v = _bounds(faces, uv_layer)
    cx = (mn_u + mx_u) * 0.5
    cy = (mn_v + mx_v) * 0.5
    for face in faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            uv.x = cx + (uv.x - cx) * factor
            uv.y = cy + (uv.y - cy) * factor


# ═══════════════════════════════════════════════════════════════════════════
#  PACKING ENGINE (STANDALONE)
# ═══════════════════════════════════════════════════════════════════════════

class _Sky:
    """Skyline bin packing algorithm."""
    def __init__(self): self.sky = [(0.,0.,1.)]
    def insert(self, rw, rh):
        bY=bW=float('inf'); bX=float('inf'); bI=-1
        for i,(sx,_,_) in enumerate(self.sky):
            if sx+rw>1+1e-9: continue
            mY=waste=0.; rem=rw; j=i
            while rem>1e-9 and j<len(self.sky):
                nx,ny,nw=self.sky[j]; mY=max(mY,ny)
                cov=min(nw if j>i else min(nw,rw),rem); rem-=cov; j+=1
            if rem>1e-9: continue
            rem2=rw; k=i
            while rem2>1e-9 and k<len(self.sky):
                nx,ny,nw=self.sky[k]; c=min(nw if k>i else min(nw,rw),rem2)
                waste+=c*(mY-ny); rem2-=c; k+=1
            if (mY<bY-1e-9 or (abs(mY-bY)<1e-9 and waste<bW-1e-9) or
                    (abs(mY-bY)<1e-9 and abs(waste-bW)<1e-9 and sx<bX)):
                bY,bX,bW,bI=mY,sx,waste,i
        if bI==-1: bY=max(y for _,y,_ in self.sky); bX=0.
        px,py=bX,bY; top=py+rh; ns=[]; ins=False
        for sx,sy,sw in self.sky:
            se=sx+sw
            if se<=px+1e-9: ns.append((sx,sy,sw))
            elif sx>=px+rw-1e-9:
                if not ins: ns.append((px,top,rw)); ins=True
                ns.append((sx,sy,sw))
            else:
                if sx<px-1e-9: ns.append((sx,sy,px-sx))
                if not ins: ns.append((px,top,rw)); ins=True
                if se>px+rw+1e-9: ns.append((px+rw,sy,se-px-rw))
        if not ins: ns.append((px,top,rw))
        m=[ns[0]]
        for seg in ns[1:]:
            a=m[-1]
            if abs(a[1]-seg[1])<1e-9 and abs(a[0]+a[2]-seg[0])<1e-9: m[-1]=(a[0],a[1],a[2]+seg[2])
            else: m.append(seg)
        self.sky=m; return px,py
    def height(self): return max(y for _,y,_ in self.sky)


class _MR:
    """MaxRects rectangle packing algorithm."""
    def __init__(self): self.fr=[(0.,0.,1.,100.)]; self.ur=[]
    def insert(self, rw, rh, method='BSSF'):
        bs=None; bp=None
        for (fx,fy,fw,fh) in self.fr:
            if rw<=fw+1e-9 and rh<=fh+1e-9:
                sc=self._sc(fw,fh,rw,rh,fx,fy,method)
                if bs is None or sc<bs: bs=sc; bp=(fx,fy)
        if bp is None: return None
        px,py=bp; pl=(px,py,rw,rh); self.ur.append(pl); self._sp(pl); self._pr(); return px,py
    def _sc(self,fw,fh,rw,rh,fx,fy,m):
        lw,lh=fw-rw,fh-rh
        if m=='BSSF': return (min(lw,lh),max(lw,lh))
        if m=='BLSF': return (max(lw,lh),min(lw,lh))
        if m=='BAF':  return (lw*lh,min(lw,lh))
        if m=='BL':   return (fy,fx)
        if m=='CP':
            cp=0.
            if abs(fx)<1e-9: cp+=rh
            if abs(fy)<1e-9: cp+=rw
            if abs(fx+rw-1)<1e-9: cp+=rh
            for ux,uy,uw,uh in self.ur:
                if abs(fx-(ux+uw))<1e-9 or abs(fx+rw-ux)<1e-9:
                    ov=min(fy+rh,uy+uh)-max(fy,uy)
                    if ov>0: cp+=ov
                if abs(fy-(uy+uh))<1e-9 or abs(fy+rh-uy)<1e-9:
                    ov=min(fx+rw,ux+uw)-max(fx,ux)
                    if ov>0: cp+=ov
            return (-cp,min(lw,lh))
        return (min(lw,lh),max(lw,lh))
    def _sp(self, pl):
        px,py,pw,ph=pl; nf=[]
        for fx,fy,fw,fh in self.fr:
            if px>=fx+fw-1e-9 or px+pw<=fx+1e-9 or py>=fy+fh-1e-9 or py+ph<=fy+1e-9:
                nf.append((fx,fy,fw,fh)); continue
            if px>fx+1e-9: nf.append((fx,fy,px-fx,fh))
            if px+pw<fx+fw-1e-9: nf.append((px+pw,fy,fx+fw-px-pw,fh))
            if py>fy+1e-9: nf.append((fx,fy,fw,py-fy))
            if py+ph<fy+fh-1e-9: nf.append((fx,py+ph,fw,fy+fh-py-ph))
        self.fr=nf
    def _pr(self):
        r=self.fr; n=len(r); sk=set()
        for i in range(n):
            if i in sk: continue
            ai=r[i]
            for j in range(n):
                if i==j or j in sk: continue
                aj=r[j]
                if ai[0]>=aj[0]-1e-9 and ai[1]>=aj[1]-1e-9 and ai[0]+ai[2]<=aj[0]+aj[2]+1e-9 and ai[1]+ai[3]<=aj[1]+aj[3]+1e-9:
                    sk.add(i); break
        self.fr=[r[i] for i in range(n) if i not in sk]
    def height(self): return max((y+h for _,y,_,h in self.ur),default=0.)


def _attempt(data, order, rots, margin, method, sub):
    """Try one packing configuration."""
    pk = _Sky() if method == 'SKYLINE' else _MR()
    ins = pk.insert if method == 'SKYLINE' else lambda rw, rh: pk.insert(rw, rh, method=sub)
    placements = [None]*len(data)
    for idx in order:
        d = data[idx]; rw,rh = _rotdims(d['w'],d['h'],rots[idx])
        pw,ph = rw+margin*2, rh+margin*2
        res = ins(pw, ph)
        placements[idx] = {'x':(res[0]+margin if res else 0.), 'y':(res[1]+margin if res else 0.), 'angle':rots[idx]}
    th = pk.height()
    if th < 1e-9: return placements, 0., 1.
    occ = sum(d['area'] for d in data) / (1.*th) if th>1e-12 else 0.
    return placements, occ, 1./max(1.,th)


def _iter_opt(data, margin, method, sub, angles, max_iter, tlim, min_occ):
    """Iterative optimization with multiple sort keys."""
    n=len(data); best_occ=min_occ; best=None; it=0; t0=time.time()
    keys=[
        lambda d,i:-d[i]['area'],
        lambda d,i:-max(d[i]['w'],d[i]['h']),
        lambda d,i:-d[i]['h'],
        lambda d,i:-d[i]['w'],
        lambda d,i:-(d[i]['w']+d[i]['h']),
        lambda d,i:-(d[i]['w']*d[i]['h']),
        lambda d,i:-(max(d[i]['w'],d[i]['h'])/(min(d[i]['w'],d[i]['h'])+1e-9)),
    ]
    def try_it(o,r):
        nonlocal best_occ,best,it; it+=1
        p,occ,s=_attempt(data,o,r,margin,method,sub)
        if occ>best_occ+1e-6: best_occ=occ; best=(p,r[:],s)
    def done(): return it>=max_iter or (time.time()-t0)>tlim or best_occ>=0.98
    for kf in keys:
        if done(): break
        order=sorted(range(n),key=lambda i,k=kf:k(data,i))
        try_it(order,[0.]*n)
        if done(): break
        if len(angles)>1:
            for a in angles:
                if done(): break
                if a!=0.: try_it(order,[a]*n)
            smart=[]
            for d in data:
                ba,bm=0.,max(d['w'],d['h'])
                for a in angles:
                    rw,rh=_rotdims(d['w'],d['h'],a); md=max(rw,rh)
                    if md<bm-1e-9: bm,ba=md,a
                smart.append(ba)
            try_it(order,smart)
            if done(): break
            try_it(order,[90. if d['h']>d['w'] else 0. for d in data])
    while not done():
        if random.random()<0.7:
            order=sorted(range(n),key=lambda i:-(data[i]['area']*random.uniform(0.8,1.2)))
        else:
            order=list(range(n)); random.shuffle(order)
        try_it(order,[random.choice(angles) for _ in range(n)])
    return best, best_occ, it


def _sa_opt(data, margin, method, sub, angles, max_iter, tlim, temp0, cool, min_occ):
    """Simulated Annealing optimization."""
    n=len(data); t0=time.time()
    order=sorted(range(n),key=lambda i:-data[i]['area']); rots=[0.]*n
    p,cur,s=_attempt(data,order,rots,margin,method,sub)
    best_occ=min_occ; best=None
    if cur>best_occ+1e-6: best_occ=cur; best=(p,rots[:],s)
    temp=temp0; it=0
    while it<max_iter and (time.time()-t0)<tlim and best_occ<0.98:
        no=order[:]; nr=rots[:]
        if n<2: nr[0]=random.choice(angles)
        else:
            act=random.random()
            if act<0.35: i,j=random.sample(range(n),2); no[i],no[j]=no[j],no[i]
            elif act<0.6: nr[random.randint(0,n-1)]=random.choice(angles)
            elif act<0.8: i,j=random.randint(0,n-1),random.randint(0,n-1); item=no.pop(i); no.insert(j,item)
            else:
                i,j=sorted(random.sample(range(n),2)); no[i:j+1]=reversed(no[i:j+1])
        p,new,s=_attempt(data,no,nr,margin,method,sub); delta=new-cur
        acc=delta>0
        if not acc and temp>1e-12:
            try: acc=random.random()<math.exp(delta/temp)
            except OverflowError: pass
        if acc:
            order,rots,cur=no,nr,new
            if cur>best_occ+1e-6: best_occ=cur; best=(p,rots[:],s)
        temp*=cool; it+=1
    return best, best_occ, it


def _apply(bm, ul, islands, data, placements, scale, props, margin):
    """Apply packing result to UV islands."""
    for i,faces in enumerate(islands):
        p=placements[i]
        if abs(p['angle'])>0.01: _rotate(faces,ul,p['angle'])
        _normalize(faces,ul); _scale(faces,ul,scale,scale)
        _translate(faces,ul,p['x']*scale,p['y']*scale)
    if props.scale_mode=='MAX_SCALE':
        g0=g1=float('inf'); g2=g3=float('-inf')
        for faces in islands:
            a,b,c,d=_bounds(faces,ul)
            g0=min(g0,a); g1=min(g1,b); g2=max(g2,c); g3=max(g3,d)
        cw,ch=g2-g0,g3-g1
        if cw>1e-9 and ch>1e-9:
            tgt=max(0.1,1.-margin*2); sf=min(tgt/cw,tgt/ch)
            for faces in islands: _translate(faces,ul,-g0,-g1); _scale(faces,ul,sf,sf)
            g0=g1=float('inf'); g2=g3=float('-inf')
            for faces in islands:
                a,b,c,d=_bounds(faces,ul)
                g0=min(g0,a); g1=min(g1,b); g2=max(g2,c); g3=max(g3,d)
            ou=(1.-(g2-g0))*0.5-g0; ov=(1.-(g3-g1))*0.5-g1
            for faces in islands: _translate(faces,ul,ou,ov)
    elif props.scale_mode=='CUSTOM':
        cf=props.custom_scale
        for faces in islands:
            for f in faces:
                for l in f.loops:
                    uv=l[ul].uv; uv.x=0.5+(uv.x-0.5)*cf; uv.y=0.5+(uv.y-0.5)*cf
    return min(sum(_area(f,ul) for f in islands),1.)


def run_packing_engine(bm, uv_layer, props, report_fn=None):
    """Pack UV islands. props = UAVUVPackProperties."""
    t0 = time.time()
    islands = _get_uv_islands(bm, uv_layer)
    if not islands:
        if report_fn: report_fn({'WARNING'}, "No UV islands found.")
        return

    n            = len(islands)
    cur_uvs      = _save(bm, uv_layer)
    cur_occ      = min(sum(_area(f, uv_layer) for f in islands), 1.)
    min_occ      = max(cur_occ, props.best_ever_occupancy)
    margin       = _eff_margin(props)
    angs         = _angles(props)
    max_iter     = props.precision
    tlim         = props.search_time if props.search_time > 0.01 else 999999.
    method       = props.packing_method
    sub          = props.maxrects_heuristic if method == 'MAXRECTS' else ''

    if report_fn:
        report_fn({'INFO'},
            f"Found {n} island(s). Current: {cur_occ*100:.1f}%. "
            f"Running {method} + {props.optimizer}…")

    data = []
    for faces in islands:
        w, h = _normalize(faces, uv_layer)
        data.append({'w': w, 'h': h, 'area': _area(faces, uv_layer)})
    norm_uvs = _save(bm, uv_layer)

    props.run_counter += 1
    random.seed(props.run_counter * 7919 + int(time.time() * 1000) % 100000)

    if props.optimizer == 'NONE':
        order = sorted(range(n), key=lambda i: -data[i]['area'])
        rots  = [0.]*n
        p,occ,s = _attempt(data,order,rots,margin,method,sub)
        best_result = (p,rots,s) if occ>min_occ+1e-6 else None
        best_occ,iters = (occ if best_result else min_occ), 1
    elif props.optimizer == 'ITERATIVE':
        best_result,best_occ,iters = _iter_opt(data,margin,method,sub,angs,max_iter,tlim,min_occ)
    else:
        best_result,best_occ,iters = _sa_opt(data,margin,method,sub,angs,max_iter,tlim,
                                              props.sa_initial_temp,props.sa_cooling_rate,min_occ)

    if props.advanced_heuristic and best_result and len(angs)>1:
        pl,rts,sc=best_result; improved=True; rc=0; mr=n*len(angs)*2
        while improved and rc<mr:
            improved=False
            for idx in range(n):
                if (time.time()-t0)>tlim: break
                for a in angs:
                    if abs(a-rts[idx])<0.01: continue
                    tr=rts[:]; tr[idx]=a
                    order=sorted(range(n),key=lambda i:-data[i]['area'])
                    p,o,s=_attempt(data,order,tr,margin,method,sub); iters+=1; rc+=1
                    if o>best_occ+1e-6: best_occ=o; best_result=(p,tr[:],s); rts=tr[:]; improved=True; break

    elapsed = time.time()-t0

    if best_result:
        pl,rts,sc = best_result
        _restore(bm, uv_layer, norm_uvs)
        final_occ = _apply(bm,uv_layer,islands,data,pl,sc,props,margin)
        props.best_ever_occupancy = max(props.best_ever_occupancy, final_occ)
        props.last_occupancy  = final_occ*100
        props.last_iterations = iters
        props.last_time       = elapsed
        props.last_method     = f"{method} + {props.optimizer}"
        if report_fn:
            report_fn({'INFO'},
                f"Improved! {final_occ*100:.1f}% "
                f"(was {min_occ*100:.1f}%) | {iters} iters | {elapsed:.2f}s")
    else:
        _restore(bm, uv_layer, cur_uvs)
        props.last_iterations = iters
        props.last_time       = elapsed
        props.last_method     = f"{method} + {props.optimizer} (no improvement)"
        if report_fn:
            report_fn({'WARNING'},
                f"No improvement (current: {min_occ*100:.1f}%). "
                f"Try more precision or a different method. ({iters} iters, {elapsed:.2f}s)")


# ═══════════════════════════════════════════════════════════════════════════
#  OPERATORS
# ═══════════════════════════════════════════════════════════════════════════

class UAV_OT_uv_pack(Operator):
    """Pack UV islands using the embedded Skyline/MaxRects engine"""
    bl_idname  = "uav.uv_pack"
    bl_label   = "Pack Islands"
    bl_description = (
        "Pack UV islands using Skyline or MaxRects packer with "
        "Iterative or Simulated Annealing optimizer. "
        "Only applies result when it improves on the previous best."
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'MESH' and
                obj.data.uv_layers.active is not None)

    def execute(self, context):
        uvp = context.scene.uav_uvpack_props
        obj = context.active_object

        was_edit = (obj.mode == 'EDIT')
        if not was_edit:
            bpy.ops.object.mode_set(mode='EDIT')

        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            self.report({'ERROR'}, "No active UV map found.")
            if not was_edit:
                bpy.ops.object.mode_set(mode='OBJECT')
            return {'CANCELLED'}

        run_packing_engine(bm, uv_layer, uvp, self.report)
        bmesh.update_edit_mesh(obj.data)

        if not was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


class UAV_OT_uv_pack_reset(Operator):
    """Reset the stored best occupancy so the next pack starts fresh"""
    bl_idname  = "uav.uv_pack_reset"
    bl_label   = "Reset Best Occupancy"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        uvp = context.scene.uav_uvpack_props
        uvp.best_ever_occupancy = 0.0
        uvp.run_counter         = 0
        uvp.last_occupancy      = 0.0
        uvp.last_iterations     = 0
        uvp.last_time           = 0.0
        uvp.last_method         = ""
        self.report({'INFO'}, "Best occupancy reset — next pack starts fresh.")
        return {'FINISHED'}
