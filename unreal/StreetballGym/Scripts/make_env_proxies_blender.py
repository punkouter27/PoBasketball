"""Headless Blender: procedurally build low/mid-poly STAND-IN environment meshes for the streetball neighbourhood.

These are placeholders that a PCG graph scatters outside the court fence until Megascans/Fab assets replace them.
Every mesh is built in metres (Blender, Z-up, +X = front), one object per mesh, flat-shaded, box-mapped UVs and
named material slots (Unreal assigns procedural materials by slot name). Each mesh is exported as its own FBX with
1 unit = 1 cm, Z-up, +X forward for Unreal; then every FBX is re-imported into a clean scene to measure the real
bounds / triangle count / slot names, which go into env_manifest.json. A contact-sheet render (Workbench, backface
culling on so flipped normals show up as holes, red cone = pivot) is written to env_preview.png.

UV modes: "world_1m" = box-mapped world-scale UVs, 1 UV unit = 1 m (large/tiling surfaces);
          "box_0_1"  = box-mapped and normalised by the largest dimension into 0..1 (small props).

    blender -b --factory-startup --python make_env_proxies_blender.py -- [<out_dir>] [<raw_blend_dir>]

Defaults: out_dir = Content/Art/Exports/Env, raw_blend_dir = Content/Art/Raw/Env (source .blend is saved there).
"""
import json
import math
import os
import random
import re
import struct
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
_args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT_DIR = os.path.abspath(_args[0]) if len(_args) > 0 else os.path.join(HERE, "..", "Content", "Art", "Exports", "Env")
RAW_DIR = os.path.abspath(_args[1]) if len(_args) > 1 else os.path.join(HERE, "..", "Content", "Art", "Raw", "Env")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(RAW_DIR, exist_ok=True)

MAX_TRIS = 20000

# viewport colours (preview only; Unreal assigns its own materials by slot name)
MAT_COLOURS = {
    "M_Brick": (0.50, 0.22, 0.15), "M_Concrete": (0.58, 0.56, 0.52), "M_Paint": (0.88, 0.86, 0.80),
    "M_Window": (0.92, 0.92, 0.90), "M_Glass": (0.25, 0.40, 0.55), "M_Metal": (0.22, 0.24, 0.27),
    "M_Wood": (0.48, 0.30, 0.15), "M_Leaf": (0.25, 0.50, 0.18), "M_Bark": (0.30, 0.22, 0.15),
    "M_Rubber": (0.04, 0.04, 0.04), "M_Emissive": (1.00, 0.92, 0.55), "M_Net": (0.95, 0.95, 0.95),
    "M_Paper": (0.90, 0.88, 0.80), "M_Plastic": (0.80, 0.15, 0.12), "M_Feather": (0.48, 0.50, 0.56),
    "M_Beak": (0.80, 0.45, 0.40), "M_CarPaint": (0.15, 0.30, 0.55), "M_TailLight": (0.75, 0.05, 0.05),
    "M_HydrantPaint": (0.80, 0.12, 0.08), "M_Label": (0.85, 0.10, 0.10), "M_Water": (0.35, 0.60, 0.80),
}


def get_mat(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    c = MAT_COLOURS.get(name, (0.7, 0.7, 0.7))
    m.diffuse_color = (*c, 1.0)
    return m


# ---------------------------------------------------------------- mesh builder
class MB:
    """Accumulates primitives into one bmesh; each primitive gets a named material slot."""

    def __init__(self, name, seed=0):
        self.name = name
        self.bm = bmesh.new()
        self.slots = []
        self.rng = random.Random(seed)

    def mi(self, mat):
        if mat not in self.slots:
            self.slots.append(mat)
        return self.slots.index(mat)

    @staticmethod
    def _faces(verts):
        return list({f for v in verts for f in v.link_faces})

    def _finish(self, faces, mat, recalc=False):
        idx = self.mi(mat)
        for f in faces:
            f.material_index = idx
            f.smooth = False
        if recalc:
            bmesh.ops.recalc_face_normals(self.bm, faces=faces)
        return faces

    def box(self, x0, x1, y0, y1, z0, z1, mat):
        c = Vector(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
        s = (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))
        m = Matrix.Translation(c) @ Matrix.Diagonal((*s, 1.0))
        return self._finish(self._faces(bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)["verts"]), mat)

    def obox(self, center, size, rot, mat):
        """Oriented box: rot is a 3x3/4x4 rotation Matrix."""
        m = Matrix.Translation(Vector(center)) @ rot.to_4x4() @ Matrix.Diagonal((*size, 1.0))
        return self._finish(self._faces(bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)["verts"]), mat)

    def cyl(self, p0, p1, r0, r1=None, segs=8, mat="M_Metal", caps=True, smooth=False, spin=0.0):
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        L = d.length
        r1 = r0 if r1 is None else r1
        rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
        m = Matrix.Translation((p0 + p1) / 2) @ rot @ Matrix.Rotation(spin, 4, "Z")
        verts = bmesh.ops.create_cone(self.bm, cap_ends=caps, cap_tris=False, segments=segs, radius1=r0,
                                      radius2=r1, depth=L, matrix=m)["verts"]
        faces = self._finish(self._faces(verts), mat)
        if smooth:
            axis = d.normalized()
            for f in faces:
                if abs(f.normal.dot(axis)) < 0.7:
                    f.smooth = True
        return faces

    def blob(self, center, radii, subdiv=1, jitter=0.15, mat="M_Leaf"):
        m = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*radii, 1.0))
        verts = bmesh.ops.create_icosphere(self.bm, subdivisions=subdiv, radius=1.0, matrix=m)["verts"]
        c = Vector(center)
        for v in verts:
            v.co = c + (v.co - c) * (1.0 + self.rng.uniform(-jitter, jitter))
        return self._finish(self._faces(verts), mat)

    def prism(self, pts2d, depth, mat, matrix=Matrix.Identity(4)):
        """Extrude a 2D polygon (local XY) along local Z from -depth/2..depth/2, then transform."""
        bot = [self.bm.verts.new(matrix @ Vector((x, y, -depth / 2))) for x, y in pts2d]
        top = [self.bm.verts.new(matrix @ Vector((x, y, depth / 2))) for x, y in pts2d]
        n = len(pts2d)
        faces = [self.bm.faces.new(bot[::-1]), self.bm.faces.new(top)]
        for i in range(n):
            j = (i + 1) % n
            faces.append(self.bm.faces.new((bot[i], bot[j], top[j], top[i])))
        return self._finish(faces, mat, recalc=True)

    def torus(self, center, R, r, segu, segv, mat):
        c = Vector(center)
        rows = []
        for i in range(segu):
            a = 2 * math.pi * i / segu
            ring = []
            for j in range(segv):
                b = 2 * math.pi * j / segv
                rr = R + r * math.cos(b)
                ring.append(self.bm.verts.new(c + Vector((rr * math.cos(a), rr * math.sin(a), r * math.sin(b)))))
            rows.append(ring)
        faces = []
        for i in range(segu):
            for j in range(segv):
                i2, j2 = (i + 1) % segu, (j + 1) % segv
                faces.append(self.bm.faces.new((rows[i][j], rows[i2][j], rows[i2][j2], rows[i][j2])))
        return self._finish(faces, mat, recalc=True)

    def poly(self, pts, mat):
        vs = [self.bm.verts.new(Vector(p)) for p in pts]
        return self._finish([self.bm.faces.new(vs)], mat)

    # ---------------------------------------------------------- finalise
    def build(self, uv_mode="world_1m", vcol_fn=None):
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        uv = bm.loops.layers.uv.new("UVMap")
        xs = [v.co for v in bm.verts]
        lo = Vector((min(p.x for p in xs), min(p.y for p in xs), min(p.z for p in xs)))
        hi = Vector((max(p.x for p in xs), max(p.y for p in xs), max(p.z for p in xs)))
        span = max(hi - lo) or 1.0
        for f in bm.faces:
            n = f.normal
            ax = max(range(3), key=lambda k: abs(n[k]))
            for l in f.loops:
                p = l.vert.co if uv_mode == "world_1m" else (l.vert.co - lo) / span
                if ax == 0:
                    u, v = (p.y if n.x > 0 else -p.y), p.z
                elif ax == 1:
                    u, v = (-p.x if n.y > 0 else p.x), p.z
                else:
                    u, v = p.x, (p.y if n.z > 0 else -p.y)
                if uv_mode != "world_1m":  # keep 0..1 after mirroring
                    u, v = u % 1.0000001, v % 1.0000001
                l[uv].uv = (u, v)
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        for s in self.slots:
            me.materials.append(get_mat(s))
        if vcol_fn is not None:
            attr = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
            for i, v in enumerate(me.vertices):
                attr.data[i].color = vcol_fn(v.co)
            me.color_attributes.active_color = attr
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        return ob


SPECS = {}  # name -> dict(meta)


def register(ob, swap_slot, front_axis, pivot, uv_mode, notes=""):
    SPECS[ob.name] = dict(obj=ob, swap_slot=swap_slot, front_axis=front_axis, pivot=pivot, uv_mode=uv_mode,
                          notes=notes)


# ---------------------------------------------------------------- brownstones
def brownstone(name, W, D, storeys, ncols, door_col, floor_h=3.3, fire_escape=False, cornice=0.55, seed=0,
               chimney=False, bulkhead=False):
    b = MB(name, seed)
    base_h = 1.5
    xf, t = D / 2, 0.3                      # facade plane, front wall thickness
    R = base_h + storeys * floor_h          # roof level
    H = R + 0.9                             # parapet top
    colw = W / ncols
    yc = [-W / 2 + (c + 0.5) * colw for c in range(ncols)]
    floors = [base_h + k * floor_h for k in range(storeys)]

    # body + roof + parapets
    b.box(-D / 2, xf - t, -W / 2, W / 2, 0, R, "M_Brick")
    b.box(-D / 2 + 0.25, xf - t, -W / 2 + 0.25, W / 2 - 0.25, R, R + 0.05, "M_Concrete")
    b.box(-D / 2, -D / 2 + 0.25, -W / 2, W / 2, R, R + 0.7, "M_Brick")
    for s in (-1, 1):
        y0, y1 = sorted((s * W / 2, s * (W / 2 - 0.25)))
        b.box(-D / 2 + 0.25, xf - t, y0, y1, R, R + 0.7, "M_Brick")

    # openings on the front wall: (kind, y0, y1, z0, z1)
    ops = []
    for c in range(ncols):
        if c == door_col:
            ops.append(("door", yc[c] - 0.6, yc[c] + 0.6, floors[0], floors[0] + 2.9))
        else:
            ops.append(("base", yc[c] - 0.45, yc[c] + 0.45, 0.45, 1.15))
            ops.append(("win", yc[c] - 0.55, yc[c] + 0.55, floors[0] + 0.5, floors[0] + 2.8))
        for k in range(1, storeys):
            top = 1.7 if k == storeys - 1 else 1.9
            ops.append(("win", yc[c] - 0.55, yc[c] + 0.55, floors[k] + 0.85, floors[k] + 0.85 + top))

    # front wall slab = rectangles around the openings
    zs = sorted({0.0, base_h, H} | {o[3] for o in ops} | {o[4] for o in ops})
    for za, zb in zip(zs, zs[1:]):
        cut = sorted((o[1], o[2]) for o in ops if o[3] <= za + 1e-6 and o[4] >= zb - 1e-6)
        y = -W / 2
        mat = "M_Concrete" if zb <= base_h + 1e-6 else "M_Brick"
        for ya, yb in cut + [(W / 2, W / 2)]:
            if ya - y > 1e-4:
                b.box(xf - t, xf, y, ya, za, zb, mat)
            y = max(y, yb)

    gx = xf - t + 0.10   # glass plane (0.2 m inset)
    for kind, ya, yb, za, zb in ops:
        fw = 0.06
        if kind == "door":
            b.box(gx - 0.04, gx + 0.04, ya, yb, za, za + 2.4, "M_Wood")
            b.box(gx - 0.02, gx, ya, yb, za + 2.4, zb, "M_Glass")
            b.box(gx, gx + 0.08, ya, yb, za + 2.4, za + 2.48, "M_Window")
            b.box(xf, xf + 0.12, ya - 0.28, ya - 0.06, za, zb, "M_Paint")
            b.box(xf, xf + 0.12, yb + 0.06, yb + 0.28, za, zb, "M_Paint")
            b.box(xf, xf + 0.25, ya - 0.38, yb + 0.38, zb, zb + 0.35, "M_Paint")
            continue
        b.box(gx - 0.02, gx, ya, yb, za, zb, "M_Glass")
        for (y0, y1, z0, z1) in ((ya, ya + fw, za, zb), (yb - fw, yb, za, zb), (ya, yb, za, za + fw),
                                 (ya, yb, zb - fw, zb), ((ya + yb) / 2 - 0.025, (ya + yb) / 2 + 0.025, za, zb),
                                 (ya, yb, (za + zb) / 2 - 0.03, (za + zb) / 2 + 0.03)):
            b.box(gx, gx + 0.08, y0, y1, z0, z1, "M_Window")
        b.box(gx, xf + 0.07, ya - 0.06, yb + 0.06, za - 0.07, za, "M_Concrete")       # sill
        if kind == "base":
            for yy in (ya + 0.2, (ya + yb) / 2, yb - 0.2):
                b.cyl((xf + 0.04, yy, za), (xf + 0.04, yy, zb), 0.012, segs=6, mat="M_Metal")
        else:
            b.box(xf, xf + 0.05, ya - 0.12, yb + 0.12, zb, zb + 0.3, "M_Concrete")    # lintel

    # string courses + cornice
    for k in range(1, storeys):
        b.box(xf, xf + 0.05, -W / 2, W / 2, floors[k] - 0.12, floors[k] + 0.03, "M_Concrete")
    b.box(xf, xf + 0.06, -W / 2, W / 2, base_h - 0.12, base_h, "M_Concrete")
    b.box(xf, xf + 0.10, -W / 2, W / 2, H - 0.9, H - 0.35, "M_Paint")
    b.box(xf, xf + cornice, -W / 2, W / 2, H - 0.35, H - 0.05, "M_Paint")
    b.box(xf, xf + cornice + 0.05, -W / 2, W / 2, H - 0.05, H, "M_Paint")
    nbr = max(2, int(W / 1.2))
    for i in range(nbr + 1):
        y = -W / 2 + 0.15 + i * (W - 0.3) / nbr
        b.box(xf + 0.10, xf + cornice - 0.08, y - 0.07, y + 0.07, H - 0.75, H - 0.35, "M_Paint")

    # back windows (flush glass panels + sills)
    for k in range(storeys):
        for c in range(ncols):
            za = floors[k] + 0.85
            b.box(-D / 2 - 0.03, -D / 2, yc[c] - 0.5, yc[c] + 0.5, za, za + 1.7, "M_Glass")
            b.box(-D / 2 - 0.08, -D / 2, yc[c] - 0.56, yc[c] + 0.56, za - 0.07, za, "M_Concrete")

    # stoop: landing + 7 steps down toward +X, railings both sides
    y0 = yc[door_col]
    sw = 0.95
    land, run, nst = 1.2, 0.28, 8
    b.box(xf, xf + land, y0 - sw, y0 + sw, 0, base_h, "M_Concrete")
    for k in range(1, nst):
        x0 = xf + land + (k - 1) * run
        b.box(x0, x0 + run, y0 - sw, y0 + sw, 0, base_h * (nst - k) / nst, "M_Concrete")
    xe = xf + land + (nst - 1) * run
    for s in (-1, 1):
        yy = y0 + s * (sw - 0.06)
        b.cyl((xf, yy, base_h + 0.9), (xf + land, yy, base_h + 0.9), 0.025, segs=6, mat="M_Metal")
        b.cyl((xf + land, yy, base_h + 0.9), (xe, yy, base_h / nst + 0.9), 0.025, segs=6, mat="M_Metal")
        b.cyl((xe - 0.1, yy, 0), (xe - 0.1, yy, base_h / nst + 1.0), 0.05, segs=8, mat="M_Metal")  # newel
        for i in range(1, 9):
            x = xf + i * (xe - 0.1 - xf) / 9
            zb = base_h if x <= xf + land else base_h * (nst - 1 - int((x - xf - land) / run)) / nst
            zt = base_h + 0.9 if x <= xf + land else base_h + 0.9 - (x - xf - land) * (base_h - base_h / nst) / (xe - xf - land)
            b.cyl((x, yy, zb), (x, yy, zt), 0.012, segs=6, mat="M_Metal", caps=False)

    if chimney:
        b.box(-D / 2 + 1.0, -D / 2 + 1.8, -W / 2 + 0.3, -W / 2 + 1.1, R, R + 2.0, "M_Brick")
    if bulkhead:
        b.box(-1.5, 1.0, W / 2 - 2.5, W / 2 - 0.3, R, R + 2.4, "M_Brick")
        b.box(-1.6, 1.1, W / 2 - 2.6, W / 2 - 0.2, R + 2.4, R + 2.55, "M_Concrete")

    if fire_escape:
        cols = [c for c in range(ncols) if c != door_col][:2]
        ya, yb = yc[min(cols)] - colw / 2 + 0.25, yc[max(cols)] + colw / 2 - 0.25
        dep = 1.1
        for k in range(1, storeys):
            z0 = floors[k]
            b.box(xf, xf + dep, ya, yb, z0 - 0.06, z0, "M_Metal")
            for (p, q) in (((xf + dep, ya), (xf + dep, yb)), ((xf, ya), (xf + dep, ya)), ((xf, yb), (xf + dep, yb))):
                for zz in (z0 + 1.0, z0 + 0.5):
                    b.cyl((p[0], p[1], zz), (q[0], q[1], zz), 0.018, segs=6, mat="M_Metal")
            for (px, py) in ((xf + dep, ya), (xf + dep, yb), (xf, ya), (xf, yb)):
                b.cyl((px, py, z0), (px, py, z0 + 1.0), 0.02, segs=6, mat="M_Metal")
            nb = int((yb - ya) / 0.18)
            for i in range(1, nb):
                y = ya + i * (yb - ya) / nb
                b.cyl((xf + dep, y, z0), (xf + dep, y, z0 + 1.0), 0.007, segs=4, mat="M_Metal", caps=False)
            for side_y in (ya, yb):
                for i in range(1, 6):
                    x = xf + i * dep / 6
                    b.cyl((x, side_y, z0), (x, side_y, z0 + 1.0), 0.007, segs=4, mat="M_Metal", caps=False)
            # stair up to the next platform (zig-zag), outer half of the platform
            if k < storeys - 1:
                z1 = floors[k + 1]
                rl = 2.8
                if k % 2:
                    sy0, sy1 = ya + 0.3, ya + 0.3 + rl
                else:
                    sy0, sy1 = yb - 0.3, yb - 0.3 - rl
                for sx in (xf + 0.55, xf + 1.0):
                    b.cyl((sx, sy0, z0), (sx, sy1, z1), 0.03, segs=4, mat="M_Metal")
                    b.cyl((sx, sy0, z0 + 0.9), (sx, sy1, z1 + 0.9), 0.015, segs=6, mat="M_Metal")
                nt = 14
                for i in range(1, nt):
                    f = i / nt
                    yy = sy0 + (sy1 - sy0) * f
                    zz = z0 + (z1 - z0) * f
                    b.box(xf + 0.55, xf + 1.0, yy - 0.08, yy + 0.08, zz - 0.02, zz, "M_Metal")
        # drop ladder below the lowest platform
        z0 = floors[1]
        ly = yb - 0.5
        for dy in (-0.22, 0.22):
            b.cyl((xf + 0.8, ly + dy, z0), (xf + 0.8, ly + dy, z0 - 2.4), 0.02, segs=6, mat="M_Metal")
        for i in range(1, 8):
            zz = z0 - i * 0.3
            b.cyl((xf + 0.8, ly - 0.22, zz), (xf + 0.8, ly + 0.22, zz), 0.012, segs=4, mat="M_Metal")

    ob = b.build("world_1m")
    register(ob, "building", "+X", "bottom centre of the main block footprint (z=0 ground); facade plane at "
             f"x=+{xf:.2f} m, stoop/cornice/fire escape protrude beyond it toward +X", "world_1m",
             notes=f"{storeys} storeys, {ncols} bays, front wall plane x=+{xf:.2f} m; sides are party walls")
    return ob


# ---------------------------------------------------------------- street furniture
def bench():
    b = MB("SM_Bench")
    L = 1.8
    for i in range(4):  # seat slats
        x0 = -0.22 + i * 0.12
        b.box(x0, x0 + 0.09, -L / 2, L / 2, 0.43, 0.46, "M_Wood")
    rot = Matrix.Rotation(math.radians(-15), 3, "Y")  # backrest leans toward -X
    for i in range(3):
        zc = 0.58 + i * 0.13
        xc = -0.27 - (zc - 0.5) * math.tan(math.radians(15))
        b.obox((xc, 0, zc), (0.025, L, 0.09), rot, "M_Wood")
    for y in (-L / 2 + 0.15, L / 2 - 0.15):
        b.box(0.14, 0.18, y - 0.03, y + 0.03, 0, 0.43, "M_Metal")         # front leg
        b.box(-0.26, -0.22, y - 0.03, y + 0.03, 0, 0.43, "M_Metal")       # back leg
        b.box(-0.26, 0.20, y - 0.03, y + 0.03, 0.40, 0.43, "M_Metal")     # seat bearer
        b.obox((-0.30, y, 0.68), (0.04, 0.06, 0.52), rot, "M_Metal")      # back upright
        b.box(-0.24, 0.22, y - 0.035, y + 0.035, 0.64, 0.67, "M_Metal")   # armrest
        b.box(0.17, 0.21, y - 0.03, y + 0.03, 0.43, 0.67, "M_Metal")      # arm post
        b.box(-0.30, 0.22, y - 0.04, y + 0.04, 0, 0.02, "M_Metal")        # foot
    ob = b.build("world_1m")
    register(ob, "bench", "+X", "bottom centre of footprint (z=0)", "world_1m", "seat faces +X, length along Y")


def trash_can():
    b = MB("SM_TrashCan")
    n = 18
    for i in range(n):
        a = 2 * math.pi * i / n
        p0 = (0.26 * math.cos(a), 0.26 * math.sin(a), 0.03)
        p1 = (0.30 * math.cos(a), 0.30 * math.sin(a), 0.88)
        b.cyl(p0, p1, 0.008, segs=4, mat="M_Metal", caps=False)
    for z, r in ((0.04, 0.26), (0.35, 0.274), (0.62, 0.287), (0.88, 0.30)):
        b.torus((0, 0, z), r, 0.012 if z > 0.8 else 0.008, 24, 4, "M_Metal")
    b.cyl((0, 0, 0), (0, 0, 0.04), 0.26, segs=24, mat="M_Metal")
    b.cyl((0, 0, 0.04), (0, 0, 0.80), 0.24, 0.27, segs=16, mat="M_Plastic", caps=False, smooth=True)  # liner
    ob = b.build("box_0_1")
    register(ob, "trash_can", "+X", "bottom centre of footprint (z=0)", "box_0_1", "wire basket + liner bag")


def water_fountain():
    b = MB("SM_WaterFountain")
    b.cyl((0, 0, 0), (0, 0, 0.06), 0.30, segs=8, mat="M_Concrete")
    b.cyl((0, 0, 0.06), (0, 0, 0.80), 0.16, 0.13, segs=8, mat="M_Concrete")
    b.cyl((0, 0, 0.80), (0, 0, 0.86), 0.18, segs=8, mat="M_Concrete")
    b.cyl((0, 0, 0.86), (0, 0, 0.98), 0.20, 0.27, segs=16, mat="M_Metal", smooth=True)   # bowl
    b.cyl((0, 0, 0.955), (0, 0, 0.965), 0.21, segs=16, mat="M_Water")
    b.cyl((0.0, 0, 0.94), (0.0, 0, 1.02), 0.02, segs=8, mat="M_Metal")                 # spout
    b.cyl((0.0, 0, 1.02), (0.05, 0, 1.03), 0.012, segs=6, mat="M_Metal")
    b.box(0.25, 0.30, -0.04, 0.04, 0.88, 0.94, "M_Metal")                              # push button
    ob = b.build("box_0_1")
    register(ob, "fountain", "+X", "bottom centre of footprint (z=0)", "box_0_1", "push button on +X")


def parked_car():
    b = MB("SM_ParkedCar")
    toXZ = Matrix.Rotation(math.radians(90), 4, "X")      # local XY profile -> world XZ, extrude along Y
    body = [(-2.30, 0.28), (2.30, 0.28), (2.32, 0.62), (2.22, 0.80), (1.20, 0.90), (-1.55, 0.94),
            (-2.28, 0.88), (-2.32, 0.62)]
    b.prism(body, 1.78, "M_CarPaint", toXZ)
    cabin = [(1.18, 0.90), (0.35, 1.42), (-1.05, 1.44), (-1.55, 0.94)]
    b.prism(cabin, 1.52, "M_Glass", toXZ)
    roof = [(0.30, 1.40), (0.35, 1.45), (-1.05, 1.47), (-1.10, 1.42)]
    b.prism(roof, 1.50, "M_CarPaint", toXZ)
    for s in (-1, 1):
        b.box(-0.35, -0.29, s * 0.70, s * 0.78, 0.92, 1.42, "M_CarPaint")   # B-pillar (stand-in)
    for x in (-1.42, 1.42):
        for s in (-1, 1):
            b.cyl((x, s * 0.70, 0.33), (x, s * 0.92, 0.33), 0.33, segs=16, mat="M_Rubber", smooth=True)
            b.cyl((x, s * 0.92, 0.33), (x, s * 0.93, 0.33), 0.20, segs=12, mat="M_Metal")
    b.box(2.28, 2.33, -0.45, 0.45, 0.45, 0.62, "M_Metal")                    # grille
    for s in (-1, 1):
        b.box(2.20, 2.31, s * 0.55, s * 0.80, 0.64, 0.74, "M_Glass")        # headlights
        b.box(-2.33, -2.25, s * 0.55, s * 0.82, 0.66, 0.78, "M_TailLight")
        b.box(0.75, 0.95, s * 0.88, s * 0.98, 0.92, 1.02, "M_CarPaint")     # mirror
    b.box(2.28, 2.36, -0.85, 0.85, 0.30, 0.45, "M_Rubber")                  # bumpers
    b.box(-2.36, -2.28, -0.85, 0.85, 0.30, 0.45, "M_Rubber")
    ob = b.build("world_1m")
    register(ob, "car", "+X", "bottom centre of footprint (z=0, tyres touch ground)", "world_1m", "sedan, front +X")


def tree(name, height, seed, spread, nbranch, canopy):
    b = MB(name, seed)
    rng = b.rng
    trunk_top = height * 0.55
    b.cyl((0, 0, 0), (0, 0, 0.35), 0.32, 0.20, segs=8, mat="M_Bark", smooth=True)
    b.cyl((0, 0, 0.35), (0, 0, trunk_top), 0.20, 0.13, segs=8, mat="M_Bark", smooth=True)
    tips = []
    for i in range(nbranch):
        a = 2 * math.pi * i / nbranch + rng.uniform(-0.3, 0.3)
        z0 = trunk_top * rng.uniform(0.75, 1.0)
        r = spread * rng.uniform(0.6, 1.0)
        tip = Vector((r * math.cos(a), r * math.sin(a), z0 + height * rng.uniform(0.18, 0.3)))
        b.cyl((0, 0, z0), tip, 0.09, 0.04, segs=6, mat="M_Bark", smooth=True)
        tips.append(tip)
    top = Vector((0, 0, height * 0.78))
    b.cyl((0, 0, trunk_top), top, 0.13, 0.05, segs=6, mat="M_Bark", smooth=True)
    tips.append(top)
    for p in tips:
        rr = canopy * rng.uniform(0.8, 1.1)
        b.blob(p, (rr, rr, rr * 0.8), subdiv=3, jitter=0.08)
    for _ in range(4):
        a = rng.uniform(0, 2 * math.pi)
        p = Vector((spread * 0.4 * math.cos(a), spread * 0.4 * math.sin(a), height * rng.uniform(0.62, 0.8)))
        rr = canopy * rng.uniform(0.7, 0.95)
        b.blob(p, (rr, rr, rr * 0.75), subdiv=1, jitter=0.15)
    ob = b.build("world_1m")
    register(ob, "tree", "none (radially symmetric)", "base of trunk (z=0)", "world_1m")


def street_light():
    b = MB("SM_StreetLight")
    b.cyl((0, 0, 0), (0, 0, 0.5), 0.18, 0.14, segs=8, mat="M_Metal")
    b.cyl((0, 0, 0.5), (0, 0, 5.6), 0.085, 0.06, segs=8, mat="M_Metal", smooth=True)
    pts = []
    R = 0.8
    for i in range(7):  # quarter arc from vertical to horizontal toward +X
        a = math.pi / 2 * i / 6
        pts.append(Vector((R - R * math.cos(a), 0, 5.6 + R * math.sin(a))))
    pts.append(Vector((1.75, 0, 6.4)))
    for p, q in zip(pts, pts[1:]):
        b.cyl(p, q, 0.055, segs=8, mat="M_Metal", smooth=True)
    hx = 1.85
    b.cyl((hx, 0, 6.25), (hx, 0, 6.45), 0.32, 0.12, segs=12, mat="M_Metal")
    b.cyl((hx, 0, 6.23), (hx, 0, 6.25), 0.27, segs=12, mat="M_Emissive")
    ob = b.build("world_1m")
    register(ob, "streetlight", "+X (arm/lamp reach toward +X)", "base of pole (z=0)", "world_1m",
             "lamp lens slot M_Emissive at ~6.24 m, 1.85 m out along +X")


def hydrant():
    b = MB("SM_Hydrant")
    b.cyl((0, 0, 0), (0, 0, 0.05), 0.16, segs=12, mat="M_HydrantPaint")
    b.cyl((0, 0, 0.05), (0, 0, 0.55), 0.115, segs=12, mat="M_HydrantPaint", smooth=True)
    b.cyl((0, 0, 0.55), (0, 0, 0.60), 0.14, segs=12, mat="M_HydrantPaint")
    b.cyl((0, 0, 0.60), (0, 0, 0.74), 0.13, 0.06, segs=12, mat="M_HydrantPaint", smooth=True)
    b.cyl((0, 0, 0.74), (0, 0, 0.80), 0.03, segs=5, mat="M_Metal")
    for s in (-1, 1):
        b.cyl((0, s * 0.10, 0.42), (0, s * 0.19, 0.42), 0.045, segs=10, mat="M_HydrantPaint")
        b.cyl((0, s * 0.19, 0.42), (0, s * 0.22, 0.42), 0.05, segs=6, mat="M_Metal")
    b.cyl((0.10, 0, 0.40), (0.20, 0, 0.40), 0.065, segs=10, mat="M_HydrantPaint")
    b.cyl((0.20, 0, 0.40), (0.24, 0, 0.40), 0.07, segs=6, mat="M_Metal")
    ob = b.build("box_0_1")
    register(ob, "hydrant", "+X (pumper nozzle)", "bottom centre of footprint (z=0)", "box_0_1")


# ---------------------------------------------------------------- litter / small
def litter_can():
    b = MB("SM_Litter_Can")
    b.cyl((0, 0, 0), (0, 0, 0.01), 0.026, 0.033, segs=12, mat="M_Metal")
    b.cyl((0, 0, 0.01), (0, 0, 0.11), 0.033, segs=12, mat="M_Label", smooth=True, caps=False)
    b.cyl((0, 0, 0.11), (0, 0, 0.122), 0.033, 0.027, segs=12, mat="M_Metal")
    ob = b.build("box_0_1")
    register(ob, "litter", "none", "bottom centre (z=0), upright; rotate 90 deg to lie it down", "box_0_1")


def litter_paper():
    b = MB("SM_Litter_Paper", seed=7)
    b.blob((0, 0, 0.055), (0.075, 0.065, 0.055), subdiv=2, jitter=0.25, mat="M_Paper")
    bm = b.bm
    zmin = min(v.co.z for v in bm.verts)
    for v in bm.verts:
        v.co.z -= zmin
    ob = b.build("box_0_1")
    register(ob, "litter", "none", "bottom centre (z=0)", "box_0_1", "crumpled ball")


def litter_cup():
    b = MB("SM_Litter_Cup")
    b.cyl((0, 0, 0), (0, 0, 0.11), 0.032, 0.045, segs=12, mat="M_Paper", smooth=True)
    b.cyl((0, 0, 0.11), (0, 0, 0.122), 0.048, 0.044, segs=12, mat="M_Plastic")
    b.cyl((0.01, 0, 0.10), (0.025, 0.005, 0.20), 0.004, segs=5, mat="M_Plastic")
    ob = b.build("box_0_1")
    register(ob, "litter", "none", "bottom centre (z=0), upright", "box_0_1", "takeaway cup with lid + straw")


def weeds():
    b = MB("SM_Weeds", seed=11)
    rng = b.rng
    for i in range(22):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0, 0.08)
        base = Vector((r * math.cos(a), r * math.sin(a), 0))
        h = rng.uniform(0.15, 0.32)
        lean = Vector((math.cos(a), math.sin(a), 0)) * rng.uniform(0.04, 0.12)
        mid = base + Vector((0, 0, h * 0.55)) + lean * 0.4
        tip = base + Vector((0, 0, h)) + lean
        fa = a + math.pi / 2
        side = Vector((math.cos(fa), math.sin(fa), 0))
        nrm = Vector((math.cos(a), math.sin(a), 0))
        w = rng.uniform(0.006, 0.010)
        tri = lambda c, s: [c + side * s, c - side * s, c + nrm * 0.003]
        vb = [bm_v(b, p) for p in tri(base, w)]
        vm = [bm_v(b, p) for p in tri(mid, w * 0.7)]
        vt = bm_v(b, tip)
        faces = [b.bm.faces.new(vb[::-1])]
        for k in range(3):
            k2 = (k + 1) % 3
            faces.append(b.bm.faces.new((vb[k], vb[k2], vm[k2], vm[k])))
            faces.append(b.bm.faces.new((vm[k], vm[k2], vt)))
        b._finish(faces, "M_Leaf", recalc=True)
    ob = b.build("box_0_1")
    register(ob, "weeds", "none", "bottom centre (z=0)", "box_0_1", "22 closed thin wedge blades (no two-sided needed)")


def bm_v(b, p):
    return b.bm.verts.new(Vector(p))


NET_R_TOP, NET_R_BOT, NET_LEN, NET_STRANDS, NET_ROWS = 0.2286, 0.15, 0.42, 12, 6


def basketball_net():
    b = MB("SM_BasketballNet")

    def node(i, j):
        t = j / NET_ROWS
        r = NET_R_TOP + (NET_R_BOT - NET_R_TOP) * t + 0.012 * math.sin(math.pi * t)  # slight belly
        a = (i + 0.5 * (j % 2)) * 2 * math.pi / NET_STRANDS
        return Vector((r * math.cos(a), r * math.sin(a), -NET_LEN * t))

    rs = 0.003  # 6 mm string
    for j in range(NET_ROWS):
        for i in range(NET_STRANDS):
            for k in (i + (j % 2) - 1, i + (j % 2)):
                b.cyl(node(i, j), node(k % NET_STRANDS, j + 1), rs, segs=4, mat="M_Net", caps=False)
    for i in range(NET_STRANDS):  # top loop ring (sits on the rim centre circle) + bottom hem
        b.cyl(node(i, 0), node(i + 1, 0), rs, segs=4, mat="M_Net", caps=False)
        b.cyl(node(i, NET_ROWS), node(i + 1, NET_ROWS), rs, segs=4, mat="M_Net", caps=False)
    ob = b.build("box_0_1", vcol_fn=lambda co: (min(1.0, max(0.0, -co.z / NET_LEN)), 0.0, 0.0, 1.0))
    register(ob, "net", "none", "top ring centre (z=0 = rim plane, net hangs to -Z)", "box_0_1",
             f"rim NOT included (MuJoCo rim drives it); top ring radius {NET_R_TOP} m at rim centre circle, "
             f"bottom radius {NET_R_BOT} m, length {NET_LEN} m, {NET_STRANDS} strands x {NET_ROWS} diamond rows, "
             "6 mm open tubes. Vertex colour R = normalised distance down the net (0 top, 1 bottom); "
             "import with Vertex Color Import Option = Replace")


def pigeon():
    b = MB("SM_Pigeon", seed=3)
    b.blob((0, 0, 0), (0.11, 0.055, 0.06), subdiv=2, jitter=0.03, mat="M_Feather")
    b.blob((0.10, 0, 0.05), (0.035, 0.03, 0.035), subdiv=1, jitter=0.03, mat="M_Feather")
    b.cyl((0.13, 0, 0.045), (0.16, 0, 0.038), 0.008, 0.002, segs=5, mat="M_Beak")
    b.prism([(-0.07, 0.025), (-0.17, 0.045), (-0.17, -0.045), (-0.07, -0.025)], 0.01, "M_Feather",
            Matrix.Translation((0, 0, 0.005)))
    for s in (-1, 1):
        wing = [(0.04, 0.04 * s), (0.02, 0.30 * s), (-0.06, 0.26 * s), (-0.07, 0.04 * s)]
        if s < 0:
            wing = wing[::-1]
        m = Matrix.Translation((0, 0, 0.02)) @ Matrix.Rotation(math.radians(10 * s), 4, "X")
        b.prism(wing, 0.008, "M_Feather", m)
        b.cyl((-0.01, 0.02 * s, -0.04), (-0.02, 0.02 * s, -0.075), 0.005, segs=4, mat="M_Beak")
    bm = b.bm
    lo = Vector([min(v.co[k] for v in bm.verts) for k in range(3)])
    hi = Vector([max(v.co[k] for v in bm.verts) for k in range(3)])
    c = (lo + hi) / 2
    for v in bm.verts:
        v.co -= c
    ob = b.build("box_0_1")
    register(ob, "pigeon", "+X (head)", "bounds centre", "box_0_1", "wings spread (flight pose), span ~0.6 m")


def leaf():
    b = MB("SM_Leaf")
    fz = 0.004
    b.poly([(-0.04, 0, 0), (0.04, 0, 0), (0.018, 0.013, fz), (-0.015, 0.017, fz)], "M_Leaf")
    b.poly([(-0.04, 0, 0), (-0.015, -0.017, fz), (0.018, -0.013, fz), (0.04, 0, 0)], "M_Leaf")
    b.poly([(-0.04, 0, 0), (-0.052, -0.002, 0), (-0.052, 0.002, 0)], "M_Leaf")  # stem
    for v in b.bm.verts:
        v.co.z -= fz / 2
    ob = b.build("box_0_1")
    register(ob, "leaf", "+X (tip)", "centre", "box_0_1", "single-sided card, normal +Z: use a two-sided material")


# ---------------------------------------------------------------- build all
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.unit_settings.system = "METRIC"
bpy.context.scene.unit_settings.scale_length = 1.0

brownstone("SM_Brownstone_A", W=8.0, D=10.0, storeys=3, ncols=3, door_col=0, chimney=True, seed=1)
brownstone("SM_Brownstone_B", W=9.0, D=10.0, storeys=4, ncols=3, door_col=2, fire_escape=True, seed=2)
brownstone("SM_Brownstone_C", W=10.0, D=10.0, storeys=3, ncols=4, door_col=1, floor_h=3.6, cornice=0.75,
           bulkhead=True, seed=3)
bench()
trash_can()
water_fountain()
parked_car()
tree("SM_Tree_A", height=8.5, seed=21, spread=1.6, nbranch=4, canopy=1.5)
tree("SM_Tree_B", height=6.5, seed=42, spread=2.4, nbranch=5, canopy=1.4)
street_light()
hydrant()
litter_can()
litter_paper()
litter_cup()
weeds()
basketball_net()
pigeon()
leaf()

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(RAW_DIR, "env_proxies.blend"))

# ---------------------------------------------------------------- export
for name, spec in SPECS.items():
    ob = spec["obj"]
    for o in bpy.context.scene.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    path = os.path.join(OUT_DIR, f"{name}.fbx")
    # apply_unit_scale + FBX_SCALE_NONE: metres are baked to centimetres, FBX UnitScaleFactor = 1 (cm).
    # Default axes (-Z forward / Y up in FBX space) round-trip to Unreal as Z-up with Blender +X = Unreal +X.
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH"}, global_scale=1.0,
                             apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
                             mesh_smooth_type="FACE", use_mesh_modifiers=True, add_leaf_bones=False,
                             bake_anim=False, colors_type="LINEAR", path_mode="AUTO")
    spec["slots"] = [s.material.name for s in ob.material_slots]
    spec["src_tris"] = sum(len(p.vertices) - 2 for p in ob.data.polygons)


def fbx_unit_scale(path):
    data = open(path, "rb").read()
    i = data.find(b"UnitScaleFactor")
    j = data.find(b"D", i + 15, i + 80)
    return struct.unpack("<d", data[j + 1:j + 9])[0] if i >= 0 and j >= 0 else None


# ---------------------------------------------------------------- verify by re-import
bpy.ops.wm.read_factory_settings(use_empty=True)
manifest = []
problems = []
imported = {}
for name, spec in SPECS.items():
    path = os.path.join(OUT_DIR, f"{name}.fbx")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path)
    obs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    assert len(obs) == 1, (name, obs)
    ob = obs[0]
    bpy.context.view_layer.update()
    M = ob.matrix_world
    ws = [M @ v.co for v in ob.data.vertices]
    lo = [min(p[k] for p in ws) for k in range(3)]
    hi = [max(p[k] for p in ws) for k in range(3)]
    ob.data.calc_loop_triangles()
    tris = len(ob.data.loop_triangles)
    slots = [re.sub(r"\.\d{3}$", "", s.material.name) for s in ob.material_slots]
    if slots != spec["slots"]:
        problems.append(f"{name}: slot mismatch {slots} vs {spec['slots']}")
    if tris > MAX_TRIS:
        problems.append(f"{name}: {tris} tris > {MAX_TRIS}")
    usf = fbx_unit_scale(path)
    entry = {
        "name": name,
        "fbx": f"{name}.fbx",
        "bounds_m": [round(hi[k] - lo[k], 4) for k in range(3)],
        "bbox_min_m": [round(x, 4) for x in lo],
        "bbox_max_m": [round(x, 4) for x in hi],
        "tris": tris,
        "material_slots": slots,
        "front_axis": spec["front_axis"],
        "pivot": spec["pivot"],
        "swap_slot": spec["swap_slot"],
        "uv_mode": spec["uv_mode"],
        "fbx_unit_scale_factor_cm": usf,
    }
    if spec["notes"]:
        entry["notes"] = spec["notes"]
    if ob.data.color_attributes:
        ca = ob.data.color_attributes[0]
        rv = [d.color[0] for d in ca.data]
        entry["vertex_color"] = {"channel": "R", "meaning": "normalised distance down the net (0 top, 1 bottom)",
                                 "min": round(min(rv), 4), "max": round(max(rv), 4)}
    manifest.append(entry)
    imported[name] = (ob, lo, hi, tris)
    print(f"ENV {name:20s} bounds_m=({entry['bounds_m'][0]:.3f}, {entry['bounds_m'][1]:.3f}, "
          f"{entry['bounds_m'][2]:.3f}) min=({lo[0]:.3f},{lo[1]:.3f},{lo[2]:.3f}) tris={tris} "
          f"usf={usf} slots={slots}")

with open(os.path.join(OUT_DIR, "env_manifest.json"), "w") as f:
    json.dump({"generator": "Scripts/make_env_proxies_blender.py",
               "units": "FBX 1 unit = 1 cm, Z-up, +X forward (Unreal axes); bounds below in metres",
               "uv_modes": {"world_1m": "box-mapped, 1 UV unit = 1 m", "box_0_1": "box-mapped, normalised to 0..1"},
               "meshes": manifest}, f, indent=2)
for p in problems:
    print("ENV PROBLEM", p)

# ---------------------------------------------------------------- contact sheet
for m in bpy.data.materials:
    base = re.sub(r"\.\d{3}$", "", m.name)
    c = MAT_COLOURS.get(base, (0.7, 0.7, 0.7))
    m.diffuse_color = (*c, 1.0)
scene = bpy.context.scene
NCOL, CELL_X, CELL_Z, SIZE = 6, 3.4, 4.2, 2.2
names = list(imported)
red = bpy.data.materials.new("PivotMarker")
red.diffuse_color = (1, 0, 0, 1)
txtm = bpy.data.materials.new("Label")
txtm.diffuse_color = (0.05, 0.05, 0.05, 1)
for idx, name in enumerate(names):
    ob, lo, hi, tris = imported[name]
    dims = [hi[k] - lo[k] for k in range(3)]
    s = SIZE / max(dims)
    col, row = idx % NCOL, idx // NCOL
    cx, cz = col * CELL_X, -row * CELL_Z
    lift = -lo[2] * s if lo[2] < -1e-3 else 0.0   # hanging meshes (net): show below a raised pivot
    ob.matrix_world = (Matrix.Translation((cx, 0, cz + lift)) @ Matrix.Rotation(math.radians(-50), 4, "Z")
                       @ Matrix.Diagonal((s, s, s, 1)) @ ob.matrix_world)
    me = bpy.data.meshes.new("pv")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.07, radius2=0.0, depth=0.18,
                          matrix=Matrix.Translation((0, 0, -0.09)))
    bm.to_mesh(me)
    bm.free()
    me.materials.append(red)
    pv = bpy.data.objects.new(f"pivot_{name}", me)
    pv.location = (cx, 0, cz + lift)
    scene.collection.objects.link(pv)
    cu = bpy.data.curves.new(f"lbl_{name}", "FONT")
    cu.body = f"{name}\n{dims[0]:.2f} x {dims[1]:.2f} x {dims[2]:.2f} m\n{tris} tris"
    cu.size = 0.22
    cu.align_x = "CENTER"
    cu.materials.append(txtm)
    lb = bpy.data.objects.new(f"lbl_{name}", cu)
    lb.location = (cx, -1.6, cz - 0.55)
    lb.rotation_euler = (math.radians(70), 0, 0)
    scene.collection.objects.link(lb)

nrows = (len(names) + NCOL - 1) // NCOL
cam_d = bpy.data.cameras.new("cam")
cam_d.type = "ORTHO"
cam_d.ortho_scale = NCOL * CELL_X + 0.6
cam = bpy.data.objects.new("cam", cam_d)
centre = Vector(((NCOL - 1) * CELL_X / 2, 0, -(nrows - 1) * CELL_Z / 2 + 0.2))
vd = Vector((0, math.cos(math.radians(20)), -math.sin(math.radians(20))))
cam.location = centre - vd * 60
cam.rotation_euler = (math.radians(70), 0, 0)
cam_d.clip_end = 200
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_backface_culling = True
scene.display.shading.show_cavity = True
scene.display.shading.show_object_outline = True
world = bpy.data.worlds.new("w")
world.color = (0.75, 0.78, 0.82)
scene.world = world
scene.render.resolution_x = 2400
scene.render.resolution_y = int(2400 * (nrows * CELL_Z * math.cos(math.radians(20)) + 0.6) / (NCOL * CELL_X + 0.6))
scene.render.resolution_percentage = 100
scene.render.filepath = os.path.join(OUT_DIR, "env_preview.png")
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
print(f"ENV wrote {len(manifest)} meshes, manifest + preview in {OUT_DIR}; problems={len(problems)}")
