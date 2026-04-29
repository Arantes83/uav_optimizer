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
from bpy.types import Operator
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty,
    StringProperty, FloatVectorProperty,
)
from .uv_utils import (
    _angles,
    _area,
    _bounds,
    _eff_margin,
    _get_uv_islands,
    _normalize,
    _restore,
    _rotate,
    _rotdims,
    _save,
    _scale,
    _scale_island_from_center,
    _translate,
)
from .uvpm_bridge import (
    UVPackmasterError,
    apply_uvpackmaster_result,
    auto_detect_engine_path,
    get_engine_status,
    run_uvpackmaster,
)


_MASK_META = {}

def _layout_is_out_of_bounds(islands, uv_layer, epsilon=1e-6):
    """Return True if any island extends outside the 0-1 UV tile."""
    for faces in islands:
        min_u, min_v, max_u, max_v = _bounds(faces, uv_layer)
        if (
            min_u < -epsilon or min_v < -epsilon or
            max_u > 1.0 + epsilon or max_v > 1.0 + epsilon
        ):
            return True
    return False



def _equalize_island_scales(islands, bm, uv_layer, weight):
    """Pre-scale islands toward a common texel density target."""
    del bm
    weight = max(0.0, min(1.0, float(weight)))
    if weight <= 0.0 or not islands:
        return

    densities = []
    for faces in islands:
        area_3d = sum(face.calc_area() for face in faces)
        area_uv = _area(faces, uv_layer)
        if area_3d <= 1e-12 or area_uv <= 1e-12:
            densities.append(None)
            continue
        densities.append(math.sqrt(area_uv / area_3d))

    valid = [density for density in densities if density and density > 1e-12]
    if not valid:
        return

    target_density = sum(valid) / len(valid)
    for faces, current_density in zip(islands, densities):
        if current_density is None or current_density <= 1e-12:
            continue
        desired_scale = target_density / current_density
        factor = desired_scale * weight + 1.0 * (1.0 - weight)
        if abs(factor - 1.0) > 1e-6:
            _scale_island_from_center(faces, uv_layer, factor)


def _mask_size_px(length, res):
    return max(1, min(res, int(math.ceil(max(0.0, float(length)) * res))))


def _mask_meta(mask):
    return _MASK_META.get(id(mask), {'w_px': 0, 'h_px': 0, 'pixels': ()})


def _register_mask(mask, w_px, h_px, pixels):
    _MASK_META[id(mask)] = {
        'w_px': int(w_px),
        'h_px': int(h_px),
        'pixels': tuple(pixels),
    }
    return mask


def _extract_island_polygons(faces, uv_layer):
    return [[(loop[uv_layer].uv.x, loop[uv_layer].uv.y) for loop in face.loops] for face in faces]


def _rotate_polygons_to_origin(polygons, angle_deg):
    if abs(angle_deg) < 0.01:
        copied = [[(u, v) for u, v in poly] for poly in polygons]
    else:
        points = [point for poly in polygons for point in poly]
        min_u = min(u for u, _ in points)
        min_v = min(v for _, v in points)
        max_u = max(u for u, _ in points)
        max_v = max(v for _, v in points)
        center_u = (min_u + max_u) * 0.5
        center_v = (min_v + max_v) * 0.5
        radians = math.radians(angle_deg)
        cos_a = math.cos(radians)
        sin_a = math.sin(radians)
        copied = []
        for poly in polygons:
            rotated = []
            for u, v in poly:
                du = u - center_u
                dv = v - center_v
                rotated.append((
                    center_u + du * cos_a - dv * sin_a,
                    center_v + du * sin_a + dv * cos_a,
                ))
            copied.append(rotated)

    all_points = [point for poly in copied for point in poly]
    min_u = min(u for u, _ in all_points)
    min_v = min(v for _, v in all_points)
    max_u = max(u for u, _ in all_points)
    max_v = max(v for _, v in all_points)
    shifted = [[(u - min_u, v - min_v) for u, v in poly] for poly in copied]
    return shifted, max_u - min_u, max_v - min_v


def _point_in_triangle(px, py, a, b, c):
    denom = ((b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]))
    if abs(denom) <= 1e-12:
        return False
    wa = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / denom
    wb = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / denom
    wc = 1.0 - wa - wb
    return wa >= -1e-6 and wb >= -1e-6 and wc >= -1e-6


def _rasterize_polygons(polygons, width, height, res):
    mask = bytearray(res * res)
    w_px = _mask_size_px(width, res)
    h_px = _mask_size_px(height, res)
    pixels = []

    scale_u = 0.0 if width <= 1e-12 or w_px <= 1 else (w_px - 1) / width
    scale_v = 0.0 if height <= 1e-12 or h_px <= 1 else (h_px - 1) / height

    for poly in polygons:
        if len(poly) < 3:
            continue
        for tri_index in range(1, len(poly) - 1):
            tri = (poly[0], poly[tri_index], poly[tri_index + 1])
            tri_px = []
            for u, v in tri:
                x_px = 0.0 if w_px <= 1 else u * scale_u
                y_px = 0.0 if h_px <= 1 else v * scale_v
                tri_px.append((x_px, y_px))

            min_col = max(0, int(math.floor(min(x for x, _ in tri_px))))
            max_col = min(w_px - 1, int(math.ceil(max(x for x, _ in tri_px))))
            min_row = max(0, int(math.floor(min(y for _, y in tri_px))))
            max_row = min(h_px - 1, int(math.ceil(max(y for _, y in tri_px))))

            for row in range(min_row, max_row + 1):
                py = 0.0 if h_px <= 1 else row + 0.5
                for col in range(min_col, max_col + 1):
                    px = 0.0 if w_px <= 1 else col + 0.5
                    if not _point_in_triangle(px, py, tri_px[0], tri_px[1], tri_px[2]):
                        continue
                    idx = row * res + col
                    if not mask[idx]:
                        mask[idx] = 1
                        pixels.append((col, row))

    return _register_mask(mask, w_px, h_px, pixels)


def _rasterize_island(faces, uv_layer, res):
    polygons = _extract_island_polygons(faces, uv_layer)
    width, height = _bounds(faces, uv_layer)[2:]
    min_u, min_v, _, _ = _bounds(faces, uv_layer)
    width -= min_u
    height -= min_v
    normalized = [[(u - min_u, v - min_v) for u, v in poly] for poly in polygons]
    return _rasterize_polygons(normalized, width, height, res)


def _pad_mask(island_mask, res, margin_px):
    if margin_px <= 0:
        return island_mask
    meta = _mask_meta(island_mask)
    padded = bytearray(res * res)
    pixels = []
    for col, row in meta['pixels']:
        new_col = col + margin_px
        new_row = row + margin_px
        if new_col < 0 or new_col >= res or new_row < 0 or new_row >= res:
            continue
        idx = new_row * res + new_col
        if not padded[idx]:
            padded[idx] = 1
            pixels.append((new_col, new_row))
    return _register_mask(padded, meta['w_px'] + margin_px * 2, meta['h_px'] + margin_px * 2, pixels)


def _mask_fits(atlas_mask, island_mask, res, px, py):
    meta = _mask_meta(island_mask)
    for col, row in meta['pixels']:
        atlas_idx = (py + row) * res + (px + col)
        if atlas_mask[atlas_idx] and island_mask[row * res + col]:
            return False
    return True


def _mask_place(atlas_mask, island_mask, res, px, py):
    meta = _mask_meta(island_mask)
    for col, row in meta['pixels']:
        atlas_mask[(py + row) * res + (px + col)] = 1


def _mask_find_position(atlas_mask, island_mask, res, island_w_px, island_h_px):
    if island_w_px > res or island_h_px > res:
        return None
    for py in range(0, res - island_h_px + 1):
        for px in range(0, res - island_w_px + 1):
            if _mask_fits(atlas_mask, island_mask, res, px, py):
                return px, py
    return None


def _attempt_pixel(data, order, rots, margin, res):
    atlas_mask = bytearray(res * res)
    placements = [None] * len(data)
    total_area = sum(d['area'] for d in data)
    margin_px = max(0, int(math.ceil(margin * res)))
    used_height_px = 0

    for idx in order:
        rot_entry = data[idx]['rot_masks'][float(rots[idx])]
        mask = rot_entry['mask']
        if margin_px > 0:
            padded_key = f'padded::{margin_px}'
            if padded_key not in rot_entry:
                rot_entry[padded_key] = _pad_mask(mask, res, margin_px)
            use_mask = rot_entry[padded_key]
        else:
            use_mask = mask

        meta = _mask_meta(use_mask)
        pos = _mask_find_position(atlas_mask, use_mask, res, meta['w_px'], meta['h_px'])
        if pos is None:
            return None, -1.0

        _mask_place(atlas_mask, use_mask, res, pos[0], pos[1])
        placements[idx] = {
            'x': (pos[0] + margin_px) / float(res),
            'y': (pos[1] + margin_px) / float(res),
            'angle': float(rots[idx]),
        }
        used_height_px = max(used_height_px, pos[1] + meta['h_px'])

    if used_height_px <= 0:
        return placements, 0.0
    used_height = used_height_px / float(res)
    occ = total_area / used_height if used_height > 1e-12 else 0.0
    return placements, occ


def _pack_best_occ_key(obj, uv_layer):
    uv_name = getattr(uv_layer, "name", "") or "UVMap"
    return f"_uav_best_uv_occupancy::{uv_name}"


def _get_pack_best_occupancy(obj, uv_layer):
    if obj is None or uv_layer is None:
        return 0.0
    try:
        return max(0.0, min(1.0, float(obj.get(_pack_best_occ_key(obj, uv_layer), 0.0))))
    except (TypeError, ValueError):
        return 0.0


def _set_pack_best_occupancy(obj, uv_layer, value):
    if obj is None or uv_layer is None:
        return 0.0
    clamped = max(0.0, min(1.0, float(value)))
    obj[_pack_best_occ_key(obj, uv_layer)] = clamped
    return clamped


def _clear_pack_best_occupancy(obj, uv_layer):
    if obj is None or uv_layer is None:
        return
    key = _pack_best_occ_key(obj, uv_layer)
    if key in obj:
        del obj[key]


def _sync_pack_best_occupancy(props, obj, uv_layer):
    props.best_ever_occupancy = _get_pack_best_occupancy(obj, uv_layer)
    return props.best_ever_occupancy


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
    def __init__(self): self.fr=[(0.,0.,1.,1e9)]; self.ur=[]
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
    if method in {'PIXEL', 'HORIZON'}:
        res = data[0].get('pixel_res', 64) if data else 64
        return _attempt_pixel(data, order, rots, margin, res)

    pk = _Sky() if method == 'SKYLINE' else _MR()
    ins = pk.insert if method == 'SKYLINE' else lambda rw, rh: pk.insert(rw, rh, method=sub)
    placements = [None]*len(data)
    for idx in order:
        d = data[idx]; rw,rh = _rotdims(d['w'],d['h'],rots[idx])
        pw,ph = rw+margin*2, rh+margin*2
        res = ins(pw, ph)
        if res is None:
            return None, -1.0
        placements[idx] = {'x':res[0]+margin, 'y':res[1]+margin, 'angle':rots[idx]}
    th = pk.height()
    if th < 1e-9:
        return placements, 0.
    occ = sum(d['area'] for d in data) / (1.*th) if th>1e-12 else 0.
    return placements, occ


def _iter_opt(data, margin, method, sub, angles, max_iter, tlim, min_occ):
    """Iterative optimization with multiple sort keys."""
    n=len(data); best_occ=min_occ; best=None; it=0; t0=time.time()
    stop_on_target = min_occ >= 0.0
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
        p,occ=_attempt(data,o,r,margin,method,sub)
        if p is not None and occ>best_occ+1e-6:
            best_occ=occ
            best=(p,r[:])
    def done():
        return it>=max_iter or (time.time()-t0)>tlim or (stop_on_target and best_occ>=0.98)
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
    stop_on_target = min_occ >= 0.0
    order=sorted(range(n),key=lambda i:-data[i]['area']); rots=[0.]*n
    p,cur=_attempt(data,order,rots,margin,method,sub)
    best_occ=min_occ; best=None
    if p is not None and cur>best_occ+1e-6:
        best_occ=cur
        best=(p,rots[:])
    else:
        cur=min_occ
    temp=temp0; it=0
    while it<max_iter and (time.time()-t0)<tlim and (not stop_on_target or best_occ<0.98):
        no=order[:]; nr=rots[:]
        if n<2: nr[0]=random.choice(angles)
        else:
            act=random.random()
            if act<0.35: i,j=random.sample(range(n),2); no[i],no[j]=no[j],no[i]
            elif act<0.6: nr[random.randint(0,n-1)]=random.choice(angles)
            elif act<0.8: i,j=random.randint(0,n-1),random.randint(0,n-1); item=no.pop(i); no.insert(j,item)
            else:
                i,j=sorted(random.sample(range(n),2)); no[i:j+1]=reversed(no[i:j+1])
        p,new=_attempt(data,no,nr,margin,method,sub)
        if p is None:
            temp*=cool; it+=1
            continue
        delta=new-cur
        acc=delta>0
        if not acc and temp>1e-12:
            try: acc=random.random()<math.exp(delta/temp)
            except OverflowError: pass
        if acc:
            order,rots,cur=no,nr,new
            if cur>best_occ+1e-6:
                best_occ=cur
                best=(p,rots[:])
        temp*=cool; it+=1
    return best, best_occ, it


def _apply(bm, ul, islands, data, placements, props, margin):
    """Apply packing result to UV islands."""
    for i,faces in enumerate(islands):
        p=placements[i]
        if abs(p['angle'])>0.01: _rotate(faces,ul,p['angle'])
        _normalize(faces,ul)
        _translate(faces,ul,p['x'],p['y'])
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
    elif props.scale_mode=='LOCKED':
        pass
    elif props.scale_mode=='CUSTOM':
        cf=props.custom_scale
        for faces in islands:
            for f in faces:
                for l in f.loops:
                    uv=l[ul].uv; uv.x=0.5+(uv.x-0.5)*cf; uv.y=0.5+(uv.y-0.5)*cf


def run_packing_engine(obj, bm, uv_layer, props, report_fn=None):
    """Pack UV islands. props = UAVUVPackProperties."""
    t0 = time.time()
    islands = _get_uv_islands(bm, uv_layer)
    if not islands:
        if report_fn:
            report_fn({'WARNING'}, "No UV islands found.")
        return

    n = len(islands)
    cur_uvs = _save(bm, uv_layer)
    cur_occ = min(sum(_area(f, uv_layer) for f in islands), 1.)
    cur_oob = _layout_is_out_of_bounds(islands, uv_layer)
    prev_best = _sync_pack_best_occupancy(props, obj, uv_layer)
    min_occ = -1.0 if cur_oob else cur_occ
    margin = _eff_margin(props)
    angs = _angles(props)
    max_iter = props.precision
    tlim = props.search_time if props.search_time > 0.01 else 999999.
    method = props.packing_method
    sub = props.maxrects_heuristic if method == 'MAXRECTS' else ''

    if report_fn:
        status_msg = (
            "Current layout is outside the 0-1 UV tile. Any valid pack result will be applied."
            if cur_oob else
            f"Best: {prev_best*100:.1f}%."
        )
        report_fn(
            {'INFO'},
            f"Found {n} island(s). Current: {cur_occ*100:.1f}%. {status_msg} Running {method} + {props.optimizer}?"
        )

    data = []
    for faces in islands:
        _normalize(faces, uv_layer)
    _equalize_island_scales(islands, bm, uv_layer, getattr(props, "density_weight", 0.0))
    for faces in islands:
        w, h = _normalize(faces, uv_layer)
        entry = {'w': w, 'h': h, 'area': _area(faces, uv_layer)}
        if method in {'PIXEL', 'HORIZON'}:
            pixel_res = max(1, int(getattr(props, "pixel_resolution", 64)))
            polygons = _extract_island_polygons(faces, uv_layer)
            rot_masks = {}
            for angle in angs:
                rotated_polygons, rw, rh = _rotate_polygons_to_origin(polygons, angle)
                if abs(angle) < 0.01:
                    mask = _rasterize_island(faces, uv_layer, pixel_res)
                else:
                    mask = _rasterize_polygons(rotated_polygons, rw, rh, pixel_res)
                rot_masks[float(angle)] = {
                    'mask': mask,
                    'w': rw,
                    'h': rh,
                }
            entry.update({
                'mask': rot_masks.get(0.0, {'mask': _rasterize_island(faces, uv_layer, pixel_res)})['mask'],
                'rot_masks': rot_masks,
                'pixel_res': pixel_res,
            })
        data.append(entry)
    norm_uvs = _save(bm, uv_layer)

    props.run_counter += 1
    random.seed(props.run_counter * 7919 + int(time.time() * 1000) % 100000)

    if props.optimizer == 'NONE':
        order = sorted(range(n), key=lambda i: -data[i]['area'])
        rots = [0.] * n
        p, occ = _attempt(data, order, rots, margin, method, sub)
        best_result = (
            (p, rots)
            if p is not None and (cur_oob or occ > min_occ + 1e-6)
            else None
        )
        best_occ, iters = (occ if best_result else min_occ), 1
    elif props.optimizer == 'ITERATIVE':
        best_result, best_occ, iters = _iter_opt(data, margin, method, sub, angs, max_iter, tlim, min_occ)
    else:
        best_result, best_occ, iters = _sa_opt(
            data, margin, method, sub, angs, max_iter, tlim,
            props.sa_initial_temp, props.sa_cooling_rate, min_occ
        )

    if props.advanced_heuristic and best_result and len(angs) > 1:
        pl, rts = best_result
        improved = True
        rc = 0
        mr = n * len(angs) * 2
        while improved and rc < mr:
            improved = False
            for idx in range(n):
                if (time.time() - t0) > tlim:
                    break
                for a in angs:
                    if abs(a - rts[idx]) < 0.01:
                        continue
                    tr = rts[:]
                    tr[idx] = a
                    order = sorted(range(n), key=lambda i: -data[i]['area'])
                    p, o = _attempt(data, order, tr, margin, method, sub)
                    iters += 1
                    rc += 1
                    if p is not None and o > best_occ + 1e-6:
                        best_occ = o
                        best_result = (p, tr[:])
                        rts = tr[:]
                        improved = True
                        break

    elapsed = time.time() - t0

    if best_result:
        pl, rts = best_result
        _restore(bm, uv_layer, norm_uvs)
        _apply(bm, uv_layer, islands, data, pl, props, margin)
        final_occ = min(sum(_area(f, uv_layer) for f in islands), 1.)
        final_oob = _layout_is_out_of_bounds(islands, uv_layer)
        props.best_ever_occupancy = _set_pack_best_occupancy(
            obj, uv_layer, max(prev_best, final_occ))
        props.last_occupancy = final_occ * 100
        props.last_iterations = iters
        props.last_time = elapsed
        props.last_method = f"{method} + {props.optimizer}"
        if report_fn:
            if cur_oob:
                suffix = (
                    " Result still extends outside 0-1."
                    if final_oob else
                    " Layout is back inside the 0-1 UV tile."
                )
                report_fn(
                    {'INFO'},
                    f"Packed from out-of-bounds layout: {final_occ*100:.1f}% | {iters} iters | {elapsed:.2f}s.{suffix}"
                )
            else:
                report_fn(
                    {'INFO'},
                    f"Improved! {final_occ*100:.1f}% (was {cur_occ*100:.1f}%) | {iters} iters | {elapsed:.2f}s"
                )
    else:
        _restore(bm, uv_layer, cur_uvs)
        props.best_ever_occupancy = prev_best
        props.last_iterations = iters
        props.last_time = elapsed
        props.last_method = f"{method} + {props.optimizer} (no improvement)"
        if report_fn:
            if cur_oob:
                report_fn(
                    {'WARNING'},
                    f"No valid pack result found for the out-of-bounds layout. ({iters} iters, {elapsed:.2f}s)"
                )
            else:
                report_fn(
                    {'WARNING'},
                    f"No improvement (current: {cur_occ*100:.1f}%). Try more precision or a different method. ({iters} iters, {elapsed:.2f}s)"
                )

# ═══════════════════════════════════════════════════════════════════════════
#  OPERATORS
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
#  ENGINE — BLENDER NATIVE
# ═══════════════════════════════════════════════════════════════════════════

def _call_blender_native_pack(props, margin):
    """Chama bpy.ops.uv.pack_islands com fallback para versões antigas do Blender."""
    attempts = [
        dict(rotate=props.rotation_enable, scale=True,
             merge_overlap=props.native_merge_overlap,
             margin_method='SCALED', shape_method=props.native_shape_method,
             margin=margin),
        dict(rotate=props.rotation_enable, scale=True,
             margin_method='SCALED', shape_method=props.native_shape_method,
             margin=margin),
        dict(rotate=props.rotation_enable, scale=True,
             margin_method='SCALED', margin=margin),
        dict(rotate=props.rotation_enable, margin=margin),
        dict(margin=margin),
    ]
    last_err = None
    for kwargs in attempts:
        try:
            bpy.ops.uv.pack_islands(**kwargs)
            return
        except TypeError as e:
            last_err = e
    if last_err:
        raise last_err


def run_blender_native_pack(obj, bm, uv_layer, props, report_fn=None):
    """Pack UV usando o operador nativo do Blender."""
    import time
    t0     = time.time()
    margin = _eff_margin(props)
    prev_best = _sync_pack_best_occupancy(props, obj, uv_layer)

    bpy.ops.mesh.select_all(action='SELECT')
    _call_blender_native_pack(props, margin)

    islands   = _get_uv_islands(bm, uv_layer)
    occupancy = min(sum(_area(f, uv_layer) for f in islands), 1.0)
    elapsed   = time.time() - t0

    props.best_ever_occupancy = _set_pack_best_occupancy(
        obj, uv_layer, max(prev_best, occupancy))
    props.last_occupancy  = occupancy * 100.0
    props.last_iterations = 1
    props.last_time       = elapsed
    props.last_method     = f"Blender Native ({props.native_shape_method.title()})"

    if report_fn:
        report_fn({'INFO'}, f"Blender native pack: {occupancy*100:.1f}% | {elapsed:.2f}s")


# ═══════════════════════════════════════════════════════════════════════════
#  ENGINE — C++ NATIVE (via DLL)
# ═══════════════════════════════════════════════════════════════════════════

def run_cpp_pack(obj, bm, uv_layer, props, report_fn=None):
    """
    Pack UV islands via DLL C++ (lib_uvpack).
    The optimisation loop runs in compiled C++; final UV application remains in Python.
    """
    import time
    try:
        from .uvpack_lib import get_lib, UVPackException
    except ImportError as e:
        if report_fn:
            report_fn({'ERROR'}, f"uvpack_lib not found: {e}")
        return

    t0 = time.time()

    islands = _get_uv_islands(bm, uv_layer)
    if not islands:
        if report_fn:
            report_fn({'WARNING'}, "No UV islands found.")
        return

    n = len(islands)
    cur_uvs = _save(bm, uv_layer)
    cur_occ = min(sum(_area(f, uv_layer) for f in islands), 1.)
    cur_oob = _layout_is_out_of_bounds(islands, uv_layer)
    prev_best = _sync_pack_best_occupancy(props, obj, uv_layer)
    min_occ = -1.0 if cur_oob else cur_occ
    margin = _eff_margin(props)
    angs = _angles(props)

    if report_fn:
        status_msg = (
            "Current layout is outside the 0-1 UV tile. Any valid result will be applied."
            if cur_oob else
            f"Best: {prev_best*100:.1f}%."
        )
        report_fn(
            {'INFO'},
            f"C++ pack: {n} island(s). Current: {cur_occ*100:.1f}%. {status_msg} {props.packing_method}+{props.optimizer}?"
        )

    islands_data = []
    for faces in islands:
        _normalize(faces, uv_layer)
    _equalize_island_scales(islands, bm, uv_layer, getattr(props, "density_weight", 0.0))
    for i, faces in enumerate(islands):
        w, h = _normalize(faces, uv_layer)
        entry = {'id': i, 'w': w, 'h': h, 'area': _area(faces, uv_layer)}
        if props.packing_method in {'PIXEL', 'HORIZON'}:
            pixel_res = max(1, int(getattr(props, "pixel_resolution", 64)))
            polygons = _extract_island_polygons(faces, uv_layer)
            rot_masks = {}
            for angle in angs:
                rotated_polygons, rw, rh = _rotate_polygons_to_origin(polygons, angle)
                if abs(angle) < 0.01:
                    mask = _rasterize_island(faces, uv_layer, pixel_res)
                else:
                    mask = _rasterize_polygons(rotated_polygons, rw, rh, pixel_res)
                rot_masks[float(angle)] = {
                    'mask': mask,
                    'w': rw,
                    'h': rh,
                }
            entry.update({
                'mask': rot_masks.get(0.0, {'mask': _rasterize_island(faces, uv_layer, pixel_res)})['mask'],
                'rot_masks': rot_masks,
                'pixel_res': pixel_res,
            })
        islands_data.append(entry)
    norm_uvs = _save(bm, uv_layer)

    try:
        lib = get_lib()
        placements, best_occ = lib.pack(islands_data, props, min_occupancy=min_occ)
    except UVPackException as e:
        if report_fn:
            report_fn({'ERROR'}, str(e))
        _restore(bm, uv_layer, cur_uvs)
        return

    elapsed = time.time() - t0

    if (cur_oob and best_occ < 0.0) or ((not cur_oob) and best_occ <= min_occ + 1e-6):
        _restore(bm, uv_layer, cur_uvs)
        props.best_ever_occupancy = prev_best
        props.last_iterations = props.precision
        props.last_time = elapsed
        props.last_method = f"C++ {props.packing_method}+{props.optimizer} (no improvement)"
        if report_fn:
            if cur_oob:
                report_fn(
                    {'WARNING'},
                    f"No valid C++ pack result was found for the out-of-bounds layout. ({elapsed:.2f}s)"
                )
            else:
                report_fn(
                    {'WARNING'},
                    f"No improvement (current: {cur_occ*100:.1f}%). ({elapsed:.2f}s)"
                )
        return

    _restore(bm, uv_layer, norm_uvs)
    placement_map = {p['id']: p for p in placements}
    missing_ids = [i for i in range(n) if i not in placement_map]
    if missing_ids:
        _restore(bm, uv_layer, cur_uvs)
        props.best_ever_occupancy = prev_best
        props.last_iterations = props.precision
        props.last_time = elapsed
        props.last_method = f"C++ {props.packing_method}+{props.optimizer} (invalid placements)"
        if report_fn:
            preview = ", ".join(str(i) for i in missing_ids[:8])
            suffix = "..." if len(missing_ids) > 8 else ""
            report_fn(
                {'ERROR'},
                "C++ pack returned invalid placement ids. "
                f"Missing islands: {preview}{suffix}. "
                "This usually means lib_uvpack.dll is out of sync with the addon files."
            )
        return

    ordered_placements = [placement_map[i] for i in range(n)]
    _apply(bm, uv_layer, islands, islands_data, ordered_placements, props, margin)
    final_occ = min(sum(_area(f, uv_layer) for f in islands), 1.)
    final_oob = _layout_is_out_of_bounds(islands, uv_layer)
    props.best_ever_occupancy = _set_pack_best_occupancy(
        obj, uv_layer, max(prev_best, final_occ))
    props.last_occupancy = final_occ * 100.
    props.last_iterations = props.precision
    props.last_time = elapsed
    props.last_method = f"C++ {props.packing_method}+{props.optimizer}"

    if report_fn:
        if cur_oob:
            suffix = (
                " Result still extends outside 0-1."
                if final_oob else
                " Layout is back inside the 0-1 UV tile."
            )
            report_fn(
                {'INFO'},
                f"C++ pack applied from out-of-bounds layout: {final_occ*100:.1f}% | {elapsed:.2f}s.{suffix}"
            )
        else:
            report_fn(
                {'INFO'},
                f"C++ pack OK! {final_occ*100:.1f}% (was {cur_occ*100:.1f}%) | {elapsed:.2f}s"
            )


def run_uvpackmaster_pack(obj, bm, uv_layer, props, report_fn=None):
    """Pack UV islands through the embedded UVPackmaster runtime."""
    t0 = time.time()
    islands = _get_uv_islands(bm, uv_layer)
    if not islands:
        if report_fn:
            report_fn({'WARNING'}, "No UV islands found.")
        return

    cur_uvs = _save(bm, uv_layer)
    cur_occ = min(sum(_area(f, uv_layer) for f in islands), 1.0)
    cur_oob = _layout_is_out_of_bounds(islands, uv_layer)
    prev_best = _sync_pack_best_occupancy(props, obj, uv_layer)
    custom_scale = float(getattr(props, "custom_scale", 1.0)) if props.scale_mode == 'CUSTOM' else 1.0

    if report_fn:
        status_msg = (
            "Current layout is outside the 0-1 UV tile. Any valid result will be applied."
            if cur_oob else
            f"Best: {prev_best*100:.1f}%."
        )
        report_fn(
            {'INFO'},
            f"UVPackmaster: {len(islands)} island(s). Current: {cur_occ*100:.1f}%. {status_msg}"
        )

    try:
        run_result = run_uvpackmaster(bm, uv_layer, props)
        if not run_result.has_solution:
            _restore(bm, uv_layer, cur_uvs)
            props.best_ever_occupancy = prev_best
            props.last_iterations = props.precision
            props.last_time = time.time() - t0
            props.last_method = "UVPackmaster 3.4.4 (no solution)"
            details = run_result.error_messages or run_result.warning_messages
            if report_fn:
                report_fn({'ERROR'}, details[0] if details else "UVPackmaster returned no valid placement.")
            return

        apply_uvpackmaster_result(bm, uv_layer, run_result, custom_scale=custom_scale)
    except UVPackmasterError as exc:
        _restore(bm, uv_layer, cur_uvs)
        props.best_ever_occupancy = prev_best
        props.last_iterations = props.precision
        props.last_time = time.time() - t0
        props.last_method = "UVPackmaster 3.4.4 (failed)"
        if report_fn:
            report_fn({'ERROR'}, str(exc))
        return

    final_occ = min(sum(_area(f, uv_layer) for f in islands), 1.0)
    final_oob = _layout_is_out_of_bounds(islands, uv_layer)
    elapsed = time.time() - t0

    if (not cur_oob) and final_occ <= cur_occ + 1e-6:
        _restore(bm, uv_layer, cur_uvs)
        props.best_ever_occupancy = prev_best
        props.last_occupancy = cur_occ * 100.0
        props.last_iterations = props.precision
        props.last_time = elapsed
        props.last_method = "UVPackmaster 3.4.4 (no improvement)"
        if report_fn:
            report_fn({'WARNING'}, f"No improvement (current: {cur_occ*100:.1f}%). ({elapsed:.2f}s)")
        return

    props.best_ever_occupancy = _set_pack_best_occupancy(
        obj, uv_layer, max(prev_best, final_occ)
    )
    props.last_occupancy = final_occ * 100.0
    props.last_iterations = props.precision
    props.last_time = elapsed
    props.last_method = "UVPackmaster 3.4.4"

    if report_fn:
        if cur_oob:
            suffix = (
                " Result still extends outside 0-1."
                if final_oob else
                " Layout is back inside the 0-1 UV tile."
            )
            report_fn(
                {'INFO'},
                f"UVPackmaster packed from out-of-bounds layout: {final_occ*100:.1f}% | {elapsed:.2f}s.{suffix}"
            )
        else:
            report_fn(
                {'INFO'},
                f"UVPackmaster: {final_occ*100:.1f}% (was {cur_occ*100:.1f}%) | {elapsed:.2f}s"
            )


class UAV_OT_uv_pack(Operator):
    """Pack UV islands using the embedded Skyline/MaxRects engine"""
    bl_idname  = "uav.uv_pack"
    bl_label   = "Pack Islands"
    bl_description = (
        "Pack UV islands using Skyline or MaxRects packer with "
        "Iterative or Simulated Annealing optimizer. "
        "Only applies result when it improves on the current layout."
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

        if uvp.pack_engine == 'BLENDER_NATIVE':
            run_blender_native_pack(obj, bm, uv_layer, uvp, self.report)
        elif uvp.pack_engine == 'CPP_NATIVE':
            run_cpp_pack(obj, bm, uv_layer, uvp, self.report)
        elif uvp.pack_engine == 'UVPACKMASTER':
            run_uvpackmaster_pack(obj, bm, uv_layer, uvp, self.report)
        else:
            run_packing_engine(obj, bm, uv_layer, uvp, self.report)
        bmesh.update_edit_mesh(obj.data)

        if not was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


class UAV_OT_uvpm_detect_engine(Operator):
    """Auto-detect UVPackmaster installation and store the engine path"""
    bl_idname = "uav.uvpm_detect_engine"
    bl_label = "Detect UVPackmaster"
    bl_description = "Search the machine for a UVPackmaster installation and store the detected engine path"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        uvp = context.scene.uav_uvpack_props
        detected = auto_detect_engine_path()
        if detected:
            uvp.uvpm_engine_path = detected["engine_root"]
            self.report({'INFO'}, f"UVPackmaster detected at {detected['engine_root']}")
            return {'FINISHED'}

        uvp.uvpm_engine_path = ""
        status = get_engine_status("")
        self.report({'WARNING'}, status.get("error", "UVPackmaster was not detected on this machine."))
        return {'CANCELLED'}


class UAV_OT_uv_pack_reset(Operator):
    """Reset the stored best occupancy so the next pack starts fresh"""
    bl_idname  = "uav.uv_pack_reset"
    bl_label   = "Reset Best Occupancy"
    bl_description = "Clear the stored best occupancy for the active object and UV map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        uvp = context.scene.uav_uvpack_props
        obj = context.active_object
        uv_layer = None
        if obj and obj.type == 'MESH':
            uv_layer = obj.data.uv_layers.active
        _clear_pack_best_occupancy(obj, uv_layer)
        uvp.best_ever_occupancy = 0.0
        uvp.run_counter         = 0
        uvp.last_occupancy      = 0.0
        uvp.last_iterations     = 0
        uvp.last_time           = 0.0
        uvp.last_method         = ""
        self.report({'INFO'}, "Best occupancy reset — next pack starts fresh.")
        return {'FINISHED'}
