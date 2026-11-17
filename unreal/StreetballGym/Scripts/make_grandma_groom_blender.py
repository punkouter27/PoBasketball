"""Headless Blender: strand-hair groom (flyaways over the modelled hair + eyebrows) for the grandma, for UE Groom.

Everything is built in the bind-pose space of SK_Grandma.fbx (Blender world, metres, Z-up, character faces -Y),
read-only: the FBX is imported only to find surfaces and the head bone; nothing is written back to it.

  group 0  flyaways  ~6000 thin strands rooted on the OUTER surface of the modelled (mesh) hair. Hair faces =
                     diffuse texture blond (hue 0.055-0.16, sat > 0.12) above the neck, not the face. Strands grow
                     along the hair surface (down/back + away from the crown, projected on the tangent plane),
                     re-snapped to the surface every step at a 2-5 mm offset (growing a little towards the tip) with
                     frizz; 4-15 cm, 6-10 points; they stop ~1.5 cm after leaving the hair.
  group 1  eyebrows  ~150 strands per brow on the brow ridge (arc above the cc_base_l/r_eye joints, roots ray-cast
                     onto the skin from the front), 6-12 mm, 5 points, lying along the skin (0.3-0.8 mm off it),
                     medial hairs pointing up/out, the rest out and slightly down.

Output (one Alembic, both groups):  <out_dir>/Groom_Grandma.abc
  Curves carry the UE groom attributes  groom_group_id (int, per curve)  and  groom_width (float, per point, cm --
  arbitrary geom params are NOT scaled by the import Scale, only Alembic .widths are, and Blender writes none).
  UE import (Groom import options -> Conversion Settings):  Rotation = (90, 0, 0),  Scale = (100, -100, 100).
  Blender's exporter writes Y-up metres (an xform per object = Z-up -> Y-up swap); UE applies xform, then
  Scale, then Rotation: (x, y, z)_blender -> (100x, -100y, 100z) cm, which is exactly where the UE FBX importer put
  SK_Grandma (UE component space = Blender world * (100, -100, 100), see retarget_grandma_blender.py).
  <out_dir>/groom_info.json  head-bone rest transform in UE component space + the groom's transform relative to it.
  <out_dir>/groom_preview.png (+ groom_preview_side.png)  Cycles close-ups of the head with the strands.

    blender -b --factory-startup --python make_grandma_groom_blender.py -- <SK_Grandma.fbx> <out_dir> [grandma_bones_ue.json]
"""
import colorsys
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

args = sys.argv[sys.argv.index("--") + 1:]
src_fbx = os.path.abspath(args[0])
out_dir = os.path.abspath(args[1])
ue_bones_json = os.path.abspath(args[2]) if len(args) > 2 else None
os.makedirs(out_dir, exist_ok=True)
rng = np.random.default_rng(7)

N_FLY = 6000
N_BROW = 150
FLY_WIDTH_CM = 0.006      # 60 um
BROW_WIDTH_CM = 0.010     # 100 um
UE_SCALE = np.array([100.0, -100.0, 100.0])   # Blender world (m) -> UE component space (cm)

# ---------------------------------------------------------------- load
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src_fbx)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = next(o for o in bpy.data.objects if o.type == "MESH")
me = mesh.data
J = {b.name: np.array(arm.matrix_world @ b.head_local) for b in arm.data.bones}
M = np.array(mesh.matrix_world)
co = np.zeros(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
V = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
tris = [tuple(p.vertices) for p in me.polygons]
bvh = BVHTree.FromPolygons([Vector(v) for v in V], tris)   # world space, bind pose
nF = len(me.polygons)
fc = np.array([V[list(t)].mean(0) for t in tris])
fn = np.zeros((nF, 3))
for i, t in enumerate(tris):
    a, b, c = V[t[0]], V[t[1]], V[t[2]]
    n = np.cross(b - a, c - a); fn[i] = n / (np.linalg.norm(n) + 1e-12)
fa = np.array([0.5 * np.linalg.norm(np.cross(V[t[1]] - V[t[0]], V[t[2]] - V[t[0]])) for t in tris])

img = next(i for i in bpy.data.images if "Diffuse" in i.name)
W, H = img.size
px = np.empty(W * H * 4, np.float32); img.pixels.foreach_get(px); px = px.reshape(H, W, 4)
uv = np.zeros(len(me.loops) * 2); me.uv_layers[0].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
hsv = np.zeros((nF, 3))
for i, p in enumerate(me.polygons):
    u = uv[list(p.loop_indices)]; c = u.mean(0)
    pts = np.vstack([c[None], c + 0.7 * (u - c)])
    x = np.clip((pts[:, 0] % 1) * W, 0, W - 1).astype(int); y = np.clip((pts[:, 1] % 1) * H, 0, H - 1).astype(int)
    hsv[i] = colorsys.rgb_to_hsv(*np.median(px[y, x, :3], axis=0))

# ---------------------------------------------------------------- hair faces
head, eyeL, eyeR = J["head"], J["cc_base_l_eye"], J["cc_base_r_eye"]
eye_z, face_y = 0.5 * (eyeL[2] + eyeR[2]), eyeL[1]
blond = (hsv[:, 0] > 0.055) & (hsv[:, 0] < 0.16) & (hsv[:, 1] > 0.12) & (hsv[:, 2] > 0.22)
above_neck = fc[:, 2] > J["neck_01"][2] - 0.10        # shoulder-length hair hangs below the neck joint
face_zone = (fc[:, 1] < face_y + 0.035) & (np.abs(fc[:, 0]) < 0.055) & (fc[:, 2] < eye_z + 0.045)
cy = head[1] + 0.01
ctr = np.stack([np.zeros(nF), np.full(nF, cy), np.minimum(fc[:, 2], eye_z)], 1)
outward = fc - ctr; outward /= np.linalg.norm(outward, axis=1, keepdims=True)
facing_out = (fn * outward).sum(1) > 0.15
hair = blond & above_neck & ~face_zone
root_ok = hair & facing_out & (fn[:, 2] > -0.5)
print(f"GROOM hair faces {hair.sum()}, root faces {root_ok.sum()}, hair z {fc[hair, 2].min():.3f}..{fc[hair, 2].max():.3f}")


def hair_at(face_index):
    return face_index is not None and hair[face_index]


def tangent(d, n):
    t = d - n * np.dot(d, n)
    L = np.linalg.norm(t)
    return t / L if L > 1e-6 else None


def snap(p, off):
    loc, nrm, fi, _ = bvh.find_nearest(Vector(p))
    if loc is None:
        return p, None, None
    q, n = np.array(loc), fn[fi]
    if np.dot(p - q, n) < off:      # inside or too close -> lift onto the offset shell
        p = q + n * off
    return p, n, fi


# ---------------------------------------------------------------- flyaways
idx = np.flatnonzero(root_ok)
pick = rng.choice(idx, size=N_FLY, p=fa[idx] / fa[idx].sum())
fly = []
down_back = np.array([0.0, 0.35, -1.0]); down_back /= np.linalg.norm(down_back)
for f in pick:
    t = tris[f]
    w = rng.dirichlet((1, 1, 1))
    root = (V[list(t[:3])] * w[:, None]).sum(0)
    n = fn[f]
    off0 = rng.uniform(0.002, 0.004)
    p = root + n * off0 * 0.5
    radial = outward[f] * np.array([1, 1, 0]); radial /= max(np.linalg.norm(radial), 1e-6)
    d = tangent(down_back + 0.45 * radial + rng.normal(0, 0.15, 3), n)
    if d is None:
        continue
    npts = int(rng.integers(6, 11))
    length = float(np.clip(rng.gamma(2.2, 0.03), 0.04, 0.15))
    step = length / (npts - 1)
    pts = [p.copy()]
    off_hair = 0.0
    for k in range(1, npts):
        off = off0 + (0.003 * k / (npts - 1))                       # 2-4 mm at the root -> up to 7 mm at the tip
        cand = pts[-1] + d * step + rng.normal(0, 0.10 * step, 3)   # frizz
        cand, nn, fi = snap(cand, off)
        if fi is not None and hair_at(fi):
            # pull back onto the shell so it hugs the hair instead of drifting off
            loc = np.array(bvh.find_nearest(Vector(cand))[0])
            cand = loc + nn * off
            off_hair = 0.0
        else:
            off_hair += step
            if off_hair > 0.015:
                break
        pts.append(cand)
        nd = cand - pts[-2]; nd /= np.linalg.norm(nd)
        nd = 0.75 * nd + 0.25 * down_back
        d = (tangent(nd, nn) if nn is not None else None)
        d = d if d is not None else nd / np.linalg.norm(nd)
    if len(pts) >= 4:
        fly.append(np.array(pts))
# trim any strand at its first point that ended up inside the body (e.g. a tip crossing the cardigan collar)
def trim_inside(s):
    for i, p in enumerate(s):
        loc, _, fi, _ = bvh.find_nearest(Vector(p))
        if np.dot(p - np.array(loc), fn[fi]) < -1e-4:
            return s[:i]
    return s


n_before = len(fly)
fly = [t for t in (trim_inside(s) for s in fly) if len(t) >= 4]
print(f"GROOM trimmed strands entering the body; dropped {n_before - len(fly)}")
print(f"GROOM flyaways {len(fly)} strands, {sum(len(s) for s in fly)} points, "
      f"length {np.mean([np.linalg.norm(np.diff(s, axis=0), axis=1).sum() for s in fly]) * 100:.1f} cm mean")

# ---------------------------------------------------------------- eyebrows
# The CC eye joints sit ~5 cm above the scanned eyes, so the brow is found on the mesh itself: profile rays from the
# front give the nose tip (most forward point near the head joint), then per side the eye socket (most recessed point
# 1-4.5 cm above the nose tip) and the brow ridge (most forward point 0-3.5 cm above the socket).
def front_y(x, z):
    h = bvh.ray_cast(Vector((x, -0.5, z)), Vector((0, 1, 0)), 1.0)
    return h[0].y if h[0] is not None else np.nan


zs = np.arange(head[2] - 0.06, head[2] + 0.06, 0.0025)
nose_z = zs[np.nanargmin([front_y(0.0, z) for z in zs])]
ridge = {}
for side in (1, -1):
    zr, xr = [], []
    for xm in (0.025, 0.03, 0.035):
        zw = np.arange(nose_z + 0.01, nose_z + 0.045, 0.0015)
        z_sock = zw[np.nanargmax([front_y(side * xm, z) for z in zw])]
        zw2 = np.arange(z_sock, z_sock + 0.035, 0.0015)
        zr.append(zw2[np.nanargmin([front_y(side * xm, z) for z in zw2])])
    ridge[side] = float(np.median(zr))
    print(f"GROOM brow ridge side {side:+d}: z {ridge[side]:.4f} m (nose tip z {nose_z:.4f}, eye joint z {eyeL[2]:.4f})")

BROW_X0, BROW_X1 = 0.010, 0.056   # medial / lateral |x| of the brow (m)
brows = []
for side in (1, -1):
    made = tries = 0
    while made < N_BROW and tries < N_BROW * 20:
        tries += 1
        t = rng.random() ** 0.8                       # 0 medial (head of brow, denser) .. 1 lateral tail
        x = side * (BROW_X0 + t * (BROW_X1 - BROW_X0))
        z = ridge[side] + 0.002 + 0.003 * math.sin(math.pi * t) - 0.008 * max(t - 0.6, 0) / 0.4
        thick = 0.008 * (1.0 - 0.55 * t)
        z += rng.uniform(-0.5, 0.5) * thick
        hit = bvh.ray_cast(Vector((x, -0.5, z)), Vector((0, 1, 0)), 1.0)
        if hit[0] is None:
            continue
        q, fi = np.array(hit[0]), hit[2]
        n = fn[fi]
        if n[1] > -0.2:      # must face forward (the brow ridge), not a hair fold
            continue
        lat = np.array([side, 0.0, 0.0])
        up = np.array([0.0, 0.0, 1.0])
        ang = math.radians(65 * (1 - t / 0.25)) if t < 0.25 else math.radians(-15 * (t - 0.25) / 0.75)
        d = tangent(math.cos(ang) * lat + math.sin(ang) * up + rng.normal(0, 0.12, 3), n)
        if d is None:
            continue
        L = rng.uniform(0.006, 0.012)
        npts = 5
        pts = []
        for k in range(npts):
            s = k / (npts - 1)
            p = q + d * L * s
            loc, nn, fj, _ = bvh.find_nearest(Vector(p))
            off = 0.0003 + 0.0005 * s
            p = np.array(loc) + fn[fj] * off
            pts.append(p)
        brows.append(np.array(pts))
        made += 1
print(f"GROOM brows {len(brows)} strands")

# ---------------------------------------------------------------- curves objects + export
bpy.ops.object.select_all(action="DESELECT")


def make_curves(name, strands, gid, width_cm, root_r, tip_r):
    cd = bpy.data.hair_curves.new(name)
    cd.add_curves([len(s) for s in strands])
    cd.position_data.foreach_set("vector", np.concatenate(strands).astype(np.float32).ravel())
    # poly curves: the default Catmull-Rom type exports spline knots that UE's Alembic hair translator rejects
    ct = cd.attributes.get("curve_type") or cd.attributes.new("curve_type", "INT8", "CURVE")
    ct.data.foreach_set("value", [1] * len(strands))
    g = cd.attributes.new("groom_group_id", "INT", "CURVE")
    g.data.foreach_set("value", [gid] * len(strands))
    wv = np.concatenate([np.linspace(1.0, 0.4, len(s)) for s in strands]) * width_cm
    a = cd.attributes.new("groom_width", "FLOAT", "POINT")
    a.data.foreach_set("value", wv.astype(np.float32))
    r = cd.attributes.get("radius") or cd.attributes.new("radius", "FLOAT", "POINT")
    r.data.foreach_set("value", np.concatenate([np.linspace(root_r, tip_r, len(s)) for s in strands]).astype(np.float32))
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    return ob


# radius here is only for the Blender preview render (Blender's Alembic writer does not export it)
fly_ob = make_curves("Grandma_Flyaways", fly, 0, FLY_WIDTH_CM, 0.00012, 0.00005)
brow_ob = make_curves("Grandma_Brows", brows, 1, BROW_WIDTH_CM, 0.00018, 0.00008)
abc = os.path.join(out_dir, "Groom_Grandma.abc")
for o in bpy.data.objects:
    o.select_set(o in (fly_ob, brow_ob))
bpy.ops.wm.alembic_export(filepath=abc, selected=True, start=1, end=1, global_scale=1.0, export_hair=False,
                          export_particles=False, evaluation_mode="RENDER")
raw = open(abc, "rb").read()
print(f"GROOM wrote {abc} ({len(raw) / 1e6:.2f} MB), attributes in file: "
      f"{[s.decode() for s in (b'groom_group_id', b'groom_width') if s in raw]}")

# ---------------------------------------------------------------- groom_info.json
def quat_rotate(q, v):          # q = (x, y, z, w), Hamilton, same maths as FQuat::RotateVector
    x, y, z, w = q
    u = np.array([x, y, z])
    return v + 2 * np.cross(u, np.cross(u, v) + w * v)


def quat_to_rotator(q):         # FQuat::Rotator()
    X, Y, Z, W = q
    st = Z * X - W * Y
    yaw = math.degrees(math.atan2(2 * (W * Z + X * Y), 1 - 2 * (Y * Y + Z * Z)))
    if st < -0.4999995:
        pitch, roll = -90.0, (-yaw - 2 * math.degrees(math.atan2(X, W)))
    elif st > 0.4999995:
        pitch, roll = 90.0, (yaw - 2 * math.degrees(math.atan2(X, W)))
    else:
        pitch = math.degrees(math.asin(2 * st))
        roll = math.degrees(math.atan2(-2 * (W * X + Y * Z), 1 - 2 * (X * X + Y * Y)))
    return {"pitch": pitch, "yaw": yaw, "roll": roll}


head_ue = (head * UE_SCALE).tolist()
info = {
    "groom_file": "Groom_Grandma.abc",
    "groups": {"0": {"name": "flyaways", "strands": len(fly), "width_cm": FLY_WIDTH_CM},
               "1": {"name": "eyebrows", "strands": len(brows), "width_cm": BROW_WIDTH_CM}},
    "space": "SK_Grandma bind pose, UE component space (cm); identical to the skeletal mesh's component space",
    "ue_import_conversion_settings": {"rotation": [90.0, 0.0, 0.0], "scale": [100.0, -100.0, 100.0]},
    "head_bone_rest_component_space": {"location_cm": head_ue, "source": "Blender bind pose * (100,-100,100)"},
    "attach_bound_to_mesh": {
        "parent": "SkeletalMeshComponent (SK_Grandma)", "socket": None,
        "relative_location_cm": [0, 0, 0], "relative_rotation": {"pitch": 0, "yaw": 0, "roll": 0},
        "binding": "GroomBindingAsset: target SK_Grandma, no source mesh (groom authored on this bind pose)"},
}
if ue_bones_json and os.path.exists(ue_bones_json):
    ue = {b["name"]: b for b in json.load(open(ue_bones_json, encoding="utf-8"))["bones"]}["head"]["component_space"]
    q = np.array(ue["quat_xyzw"]); t = np.array(ue["pos_cm"])
    qi = np.array([-q[0], -q[1], -q[2], q[3]])
    rel_loc = quat_rotate(qi, -t)
    info["head_bone_rest_component_space"].update({
        "location_cm_ue_dump": t.tolist(), "rotation_quat_xyzw": q.tolist(), "rotation": quat_to_rotator(q),
        "location_mismatch_cm": float(np.linalg.norm(t - np.array(head_ue))), "dump": os.path.basename(ue_bones_json)})
    info["attach_rigid_to_head_socket"] = {
        "parent": "SkeletalMeshComponent (SK_Grandma)", "socket": "head",
        "relative_location_cm": rel_loc.tolist(), "relative_rotation_quat_xyzw": qi.tolist(),
        "relative_rotation": quat_to_rotator(qi),
        "note": "= inverse(head bind transform): puts the groom's origin back on the component origin in bind pose"}
json.dump(info, open(os.path.join(out_dir, "groom_info.json"), "w"), indent=2)
print("GROOM info", json.dumps(info.get("attach_rigid_to_head_socket", {}), indent=None))

# ---------------------------------------------------------------- verify by re-import
for o in (fly_ob, brow_ob):
    o.hide_render = False
before = {o.name: np.concatenate(fly if o is fly_ob else brows) for o in (fly_ob, brow_ob)}
coll = bpy.data.collections.new("abc_check"); bpy.context.scene.collection.children.link(coll)
n0 = set(bpy.data.objects)
bpy.ops.wm.alembic_import(filepath=abc)
for o in set(bpy.data.objects) - n0:
    pos = np.array([tuple(o.matrix_world @ Vector(p.vector)) for p in o.data.position_data]) if o.type == "CURVES" else None
    attrs = {a.name: a.domain for a in o.data.attributes if not a.name.startswith(".")} if o.type == "CURVES" else {}
    ref = next((v for k, v in before.items() if k in o.name), None)
    err = float(np.abs(pos - ref).max()) if pos is not None and ref is not None and len(pos) == len(ref) else float("nan")
    print(f"VERIFY re-import {o.name} {o.type} curves {len(o.data.curves) if o.type == 'CURVES' else '-'} "
          f"points {len(pos) if pos is not None else '-'} max pos delta {err * 1000:.4f} mm attrs {attrs}")
    bpy.data.objects.remove(o)

# root distance to surface + inside check
def surf_stats(strands):
    d_root, inside = [], 0
    for s in strands:
        for i, p in enumerate(s):
            loc, nrm, fi, dist = bvh.find_nearest(Vector(p))
            sd = float(np.dot(p - np.array(loc), fn[fi]))
            if i == 0:
                d_root.append(sd)
            inside += sd < -1e-4
    return np.array(d_root), inside


for name, s in (("flyaways", fly), ("brows", brows)):
    dr, ins = surf_stats(s)
    print(f"VERIFY {name}: root offset {dr.min() * 1000:.2f}..{dr.max() * 1000:.2f} mm, points inside the mesh {ins}")

# ---------------------------------------------------------------- preview render (Cycles)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 24
scene.render.resolution_x, scene.render.resolution_y = 1100, 1100
scene.render.film_transparent = False
world = bpy.data.worlds.new("w"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.35, 0.37, 0.42, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.4


def flat_mat(name, rgb):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = 0.5
    return m


fly_mat = flat_mat("fly", (0.1, 0.9, 1.0)); fly_ob.data.materials.append(fly_mat)
brow_mat = flat_mat("brow", (1.0, 0.1, 0.6)); brow_ob.data.materials.append(brow_mat)
NATURAL = {fly_mat: (0.80, 0.62, 0.36), brow_mat: (0.16, 0.11, 0.08)}
DEBUG = {fly_mat: (0.1, 0.9, 1.0), brow_mat: (1.0, 0.1, 0.6)}
for e in (("key", (0.6, -1.2, 2.2), 160), ("fill", (-1.2, -0.8, 1.7), 60), ("rim", (0.3, 1.2, 2.0), 120)):
    ld = bpy.data.lights.new(e[0], "AREA"); ld.energy = e[2]; ld.size = 1.0
    lo = bpy.data.objects.new(e[0], ld); lo.location = e[1]; scene.collection.objects.link(lo)
    lo.rotation_euler = (Vector((0, 0, 1.6)) - Vector(e[1])).to_track_quat("-Z", "Y").to_euler()
cam_d = bpy.data.cameras.new("cam"); cam_d.lens = 85
cam = bpy.data.objects.new("cam", cam_d); scene.collection.objects.link(cam); scene.camera = cam
target = Vector((0, -0.01, 1.63))
VIEWS = (("", (0.35, -1.05, 1.70), NATURAL), ("_debug", (0.35, -1.05, 1.70), DEBUG),
         ("_side", (1.1, 0.25, 1.68), DEBUG), ("_back", (-0.3, 1.05, 1.70), DEBUG))
for tag, loc, cols in VIEWS:
    for m, c in cols.items():
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*c, 1)
    cam.location = loc
    cam.rotation_euler = (target - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(out_dir, f"groom_preview{tag}.png")
    bpy.ops.render.render(write_still=True)
    print("PREVIEW wrote", scene.render.filepath)
