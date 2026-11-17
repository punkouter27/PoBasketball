"""Headless Blender: give the grandma's loose cardigan hem its own material section + a cloth mask, for Chaos Cloth.

The scanned grandma is ONE closed surface: the cardigan hem is fused to the trousers (no separate shell). This
script never moves a vertex and never touches bones or skin weights. It only
  1. picks the faces of the cardigan's lower panel (belly fold -> hem lip),
  2. assigns them to a second material slot "Cardigan_Hem" (a copy of the original material, so it looks the same;
     the original slot stays first = section 0),
  3. writes the per-vertex cloth mask into the mesh's (only) colour attribute, renamed "cloth_weight": R = weight,
     G = B = A = 1 (the scan's existing layer was R=0, G=B=A=1). 0 = pinned (top edge of the hem band and every
     vertex shared with a non-hem face, so the section never tears off the trousers), ramping to 1 at the hem lip.
     In Unreal: Cloth Paint -> Max Distance -> import from vertex colour R (or "Weight map from vertex colour"),
     scaled by the max distance you want (e.g. 6-10 cm).
  4. exports with the SAME FBX settings as retarget_grandma_blender.py (shape keys included),
  5. re-imports and verifies skeleton / vertices / shape keys / slots, and renders debug previews (hem tinted).

Face selection = colour + body region + skinning:
  - diffuse texture sampled at each face's UV corners + centroid (median): cardigan = bright, unsaturated
    (V > 0.55, S < 0.20); trousers are maroon, skin/hair are saturated warm tones.
  - height band: hem lip (found from data) .. pelvis + TOP_ABOVE_PELVIS (the belly fold).
  - dominant skin weight on torso/leg bones (pelvis, spine_01/02, thighs, cc pelvis/thigh twists), not arm/hand.
  - cleanup: keep connected components (edge-adjacent faces) >= MIN_COMPONENT faces, then fill small enclosed
    holes (< MAX_HOLE faces, e.g. dark texture seams) inside the band.

    blender -b --factory-startup --python split_grandma_cloth_blender.py -- <SK_Grandma.fbx> <SK_Grandma_Cloth.fbx> [preview_dir]
"""
import colorsys
import heapq
import os
import sys
from collections import defaultdict

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
src_fbx, out_fbx = (os.path.abspath(a) for a in args[:2])
preview_dir = os.path.abspath(args[2]) if len(args) > 2 else os.path.dirname(out_fbx)

TOP_ABOVE_PELVIS = 0.045   # m: top edge of the hem band relative to the pelvis joint (belly fold)
V_MIN, S_MAX = 0.55, 0.20  # cardigan colour gate (sRGB HSV)
MAX_ABS_X = 0.33           # m: lateral limit (hands hang at |x| ~ 0.45-0.5)
MIN_COMPONENT = 200        # faces
MAX_HOLE = 400             # faces
GROW_RINGS = 2             # rings grown into non-maroon shadow faces at the hem lip
SEAM_FALLOFF = 0.03        # m: weight fades to 0 within this geodesic distance of the trouser seam
HEM_SLOT = "Cardigan_Hem"
TORSO = ("pelvis", "spine_01", "spine_02", "thigh_l", "thigh_r", "cc_base_pelvis",
         "cc_base_l_thightwist01", "cc_base_l_thightwist02", "cc_base_r_thightwist01", "cc_base_r_thightwist02")


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    return arm, mesh


def world_co(mesh):
    co = np.zeros(len(mesh.data.vertices) * 3)
    mesh.data.vertices.foreach_get("co", co)
    M = np.array(mesh.matrix_world)
    return co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]


# ---------------------------------------------------------------- load + per-face features
arm, mesh = load(src_fbx)
me = mesh.data
V = world_co(mesh)
pelvis_z = (arm.matrix_world @ arm.data.bones["pelvis"].head_local).z
nF = len(me.polygons)
loop_start = np.zeros(nF, int); me.polygons.foreach_get("loop_start", loop_start)
loop_total = np.zeros(nF, int); me.polygons.foreach_get("loop_total", loop_total)
loop_v = np.zeros(len(me.loops), int); me.loops.foreach_get("vertex_index", loop_v)
uv = np.zeros(len(me.loops) * 2); me.uv_layers[0].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)

mat0 = mesh.material_slots[0].material
img = next(n.image for n in mat0.node_tree.nodes if n.type == "TEX_IMAGE" and "Diffuse" in n.image.name)
W, H = img.size
px = np.empty(W * H * 4, np.float32); img.pixels.foreach_get(px); px = px.reshape(H, W, 4)


def sample(u):
    x = np.clip((u[:, 0] % 1.0) * W, 0, W - 1).astype(int)
    y = np.clip((u[:, 1] % 1.0) * H, 0, H - 1).astype(int)
    return px[y, x, :3]


# corners pulled 25 % toward the centroid so we stay inside the UV island (atlas has dark dilation at seams)
face_rgb = np.zeros((nF, 3))
face_z = np.zeros(nF); face_x = np.zeros(nF)
for f in range(nF):
    ls = slice(loop_start[f], loop_start[f] + loop_total[f])
    u = uv[ls]; c = u.mean(0)
    pts = np.vstack([c[None], c + 0.75 * (u - c)])
    face_rgb[f] = np.median(sample(pts), axis=0)
    p = V[loop_v[ls]]
    face_z[f] = p[:, 2].mean(); face_x[f] = p[:, 0].mean()
hsv = np.array([colorsys.rgb_to_hsv(*c) for c in face_rgb])
is_white = (hsv[:, 2] > V_MIN) & (hsv[:, 1] < S_MAX)

# torso/leg skin weight per vertex -> per face
gi = {g.index: g.name for g in mesh.vertex_groups}
torso_w = np.zeros(len(me.vertices)); tot_w = np.zeros(len(me.vertices))
for v in me.vertices:
    for g in v.groups:
        tot_w[v.index] += g.weight
        if gi[g.group] in TORSO:
            torso_w[v.index] += g.weight
torso_frac = torso_w / np.maximum(tot_w, 1e-9)
face_torso = np.array([torso_frac[loop_v[loop_start[f]:loop_start[f] + loop_total[f]]].mean() for f in range(nF)])

# face adjacency through edges
edge_faces = defaultdict(list)
for f, poly in enumerate(me.polygons):
    for ek in poly.edge_keys:
        edge_faces[ek].append(f)
nbr = [[] for _ in range(nF)]
for fs in edge_faces.values():
    for a in fs:
        for b in fs:
            if a != b:
                nbr[a].append(b)


def components(mask):
    lab = -np.ones(nF, int); comps = []
    for s in np.flatnonzero(mask):
        if lab[s] >= 0:
            continue
        lab[s] = len(comps); st = [s]; cur = [s]
        while st:
            u = st.pop()
            for w in nbr[u]:
                if mask[w] and lab[w] < 0:
                    lab[w] = len(comps); st.append(w); cur.append(w)
        comps.append(cur)
    return comps


# hem lip: lowest cardigan-coloured torso face that is still part of the big cardigan body (not a stray fleck)
z_top = pelvis_z + TOP_ABOVE_PELVIS
cand = is_white & (face_torso > 0.5) & (np.abs(face_x) < MAX_ABS_X) & (face_z < z_top) & (face_z > pelvis_z - 0.35)
comps = sorted(components(cand), key=len, reverse=True)
sel = np.zeros(nF, bool)
for c in comps:
    if len(c) >= MIN_COMPONENT:
        sel[c] = True
print(f"CLOTH candidates {cand.sum()} faces in {len(comps)} components; kept "
      f"{[len(c) for c in comps if len(c) >= MIN_COMPONENT]}")
# fill enclosed holes: unselected components inside the band that touch only selected faces / band limits
band = (face_z < z_top) & (face_z > face_z[sel].min() - 0.005) & (np.abs(face_x) < MAX_ABS_X) & (face_torso > 0.3)
for c in components(band & ~sel):
    if len(c) > MAX_HOLE:
        continue
    cs = set(c)
    border = {w for u in c for w in nbr[u] if w not in cs}
    if border and all(sel[w] for w in border):
        sel[c] = True
# grow a couple of rings into the dark shadow flecks along the hem lip (texture seams / occlusion), never into maroon
maroon = (hsv[:, 1] > 0.35) & ((hsv[:, 0] > 0.85) | (hsv[:, 0] < 0.06)) & (hsv[:, 2] > 0.22)
zmin_sel = face_z[sel].min()
for _ in range(GROW_RINGS):
    ring = {w for u in np.flatnonzero(sel) for w in nbr[u] if not sel[w]}
    add = [w for w in ring if not maroon[w] and zmin_sel - 0.01 < face_z[w] < z_top and abs(face_x[w]) < MAX_ABS_X]
    sel[add] = True
print(f"CLOTH hem faces {sel.sum()}, face z range {face_z[sel].min():.3f}..{face_z[sel].max():.3f} m "
      f"(pelvis z {pelvis_z:.3f})")

# ---------------------------------------------------------------- material slot
hem_mat = mat0.copy(); hem_mat.name = HEM_SLOT
mesh.data.materials.append(hem_mat)
mi = np.zeros(nF, int); mi[sel] = 1
me.polygons.foreach_set("material_index", mi)

# ---------------------------------------------------------------- cloth weight
sel_f = np.flatnonzero(sel)
hem_v = np.unique(np.concatenate([loop_v[loop_start[f]:loop_start[f] + loop_total[f]] for f in sel_f]))
non_v = np.unique(np.concatenate([loop_v[loop_start[f]:loop_start[f] + loop_total[f]] for f in np.flatnonzero(~sel)]))
seam = np.intersect1d(hem_v, non_v)
zv = V[hem_v, 2]
z_lo, z_hi = zv.min(), zv.max()
ramp = np.clip((z_hi - V[:, 2]) / (z_hi - z_lo), 0, 1)
ramp = ramp * ramp * (3 - 2 * ramp)  # smoothstep: soft near the pinned top
# geodesic distance (edge Dijkstra inside the hem) from the LOWER seam (hem <-> trousers); the top seam is already 0
in_hem = np.zeros(len(V), bool); in_hem[hem_v] = True
vadj = defaultdict(list)
for e in me.edges:
    a, b = e.vertices
    if in_hem[a] and in_hem[b]:
        d = float(np.linalg.norm(V[a] - V[b])); vadj[a].append((b, d)); vadj[b].append((a, d))
z_mid = 0.5 * (z_lo + z_hi)
dist = np.full(len(V), np.inf)
pq = [(0.0, int(v)) for v in seam if V[v, 2] < z_mid]
for _, v in pq:
    dist[v] = 0.0
heapq.heapify(pq)
while pq:
    d, u = heapq.heappop(pq)
    if d > dist[u] or d > SEAM_FALLOFF:
        continue
    for w, l in vadj[u]:
        if d + l < dist[w]:
            dist[w] = d + l; heapq.heappush(pq, (d + l, w))
fade = np.clip(dist / SEAM_FALLOFF, 0, 1)
weight = np.zeros(len(V))
weight[hem_v] = ramp[hem_v] * fade[hem_v]
weight[seam] = 0.0
print(f"CLOTH vertices {len(hem_v)}, seam (pinned) {len(seam)}, weight>0.5: {(weight > 0.5).sum()}, max {weight.max():.2f}")

ca = me.color_attributes[0] if len(me.color_attributes) else me.color_attributes.new("cloth_weight", "BYTE_COLOR", "CORNER")
ca.name = "cloth_weight"
if ca.domain == "CORNER":
    col = np.ones((len(me.loops), 4), np.float32); col[:, 0] = weight[loop_v]
else:
    col = np.ones((len(V), 4), np.float32); col[:, 0] = weight
ca.data.foreach_set("color", col.ravel())
me.update()

# ---------------------------------------------------------------- export (identical settings to retarget_grandma_blender.py)
ref_bones = {b.name: (np.array(arm.matrix_world @ b.matrix_local), b.parent.name if b.parent else None) for b in arm.data.bones}
ref_nv, ref_nsk = len(me.vertices), len(me.shape_keys.key_blocks) if me.shape_keys else 0
ref_V = V.copy()
os.makedirs(os.path.dirname(out_fbx), exist_ok=True)
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
mesh.select_set(True)
bpy.ops.export_scene.fbx(filepath=out_fbx, use_selection=True, object_types={"ARMATURE", "MESH"},
                         add_leaf_bones=False, bake_anim=False, path_mode="COPY", embed_textures=True,
                         use_armature_deform_only=False, mesh_smooth_type="FACE")
print(f"CLOTH wrote {out_fbx}")

# ---------------------------------------------------------------- verify
arm, mesh = load(out_fbx)
me = mesh.data
names = {b.name for b in arm.data.bones}
assert names == set(ref_bones), f"bone set differs: {names ^ set(ref_bones)}"
dpos = max(np.linalg.norm(np.array(arm.matrix_world @ b.matrix_local)[:3, 3] - ref_bones[b.name][0][:3, 3]) for b in arm.data.bones)
drot = max(np.abs(np.array(arm.matrix_world @ b.matrix_local)[:3, :3] / np.linalg.norm(np.array(arm.matrix_world @ b.matrix_local)[:3, :3], axis=0)
                  - ref_bones[b.name][0][:3, :3] / np.linalg.norm(ref_bones[b.name][0][:3, :3], axis=0)).max() for b in arm.data.bones)
par_ok = all((b.parent.name if b.parent else None) == ref_bones[b.name][1] for b in arm.data.bones)
V2 = world_co(mesh)
nsk = len(me.shape_keys.key_blocks) if me.shape_keys else 0
mi = np.zeros(len(me.polygons), int); me.polygons.foreach_get("material_index", mi)
print(f"VERIFY bones {len(names)} (same names, parents {'same' if par_ok else 'DIFFER'}), "
      f"max joint delta {dpos * 100:.4f} cm, max rot-matrix delta {drot:.2e}")
print(f"VERIFY vertices {len(me.vertices)} (ref {ref_nv}), max vertex delta "
      f"{np.abs(V2 - ref_V).max() * 100 if len(V2) == len(ref_V) else float('nan'):.4f} cm, shape keys {nsk} (ref {ref_nsk})")
print(f"VERIFY material slots {[s.material.name for s in mesh.material_slots]}, hem faces {(mi == 1).sum()}")
hv = np.unique([me.loops[li].vertex_index for p in me.polygons if p.material_index == 1 for li in p.loop_indices])
print(f"VERIFY hem vertex z range {V2[hv, 2].min():.3f}..{V2[hv, 2].max():.3f} m, x range "
      f"{V2[hv, 0].min():.3f}..{V2[hv, 0].max():.3f} m, components {len(components(mi == 1)) if len(mi) == nF else '?'}")
ca = me.color_attributes
print(f"VERIFY colour attributes {[c.name for c in ca]}")
if len(ca):
    c = np.zeros(len(ca[0].data) * 4, np.float32); ca[0].data.foreach_get("color", c); c = c.reshape(-1, 4)
    print(f"VERIFY cloth_weight R range {c[:, 0].min():.2f}..{c[:, 0].max():.2f}, loops with R>0: {(c[:, 0] > 0).sum()}")

# ---------------------------------------------------------------- debug previews (hem tinted magenta)
dbg = mesh.material_slots[1].material
for n in list(dbg.node_tree.nodes):
    if n.type == "TEX_IMAGE":
        dbg.node_tree.nodes.remove(n)
dbg.diffuse_color = (1.0, 0.1, 0.8, 1.0)
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.render.resolution_x, scene.render.resolution_y = 1000, 1100
scene.world = bpy.data.worlds.new("w"); scene.world.color = (0.18, 0.18, 0.2)
cam_data = bpy.data.cameras.new("cam"); cam_data.type = "ORTHO"; cam_data.ortho_scale = 1.3
cam = bpy.data.objects.new("cam", cam_data); scene.collection.objects.link(cam); scene.camera = cam
VIEWS = {"front": ((0, -5, 0.95), (1.5708, 0, 0)), "side": ((5, 0, 0.95), (1.5708, 0, 1.5708)),
         "back": ((0, 5, 0.95), (1.5708, 0, 3.1416))}
for prefix, ctype, views in (("cloth_hem", "TEXTURE", ("front", "side", "back")), ("cloth_weight", "VERTEX", ("front", "side"))):
    scene.display.shading.color_type = ctype   # VERTEX = the cloth_weight colour (R ramp; G=B=1 shows cyan->white)
    for tag in views:
        cam.location, cam.rotation_euler = VIEWS[tag]
        scene.render.filepath = os.path.join(preview_dir, f"{prefix}_{tag}.png")
        bpy.ops.render.render(write_still=True)
        print("PREVIEW wrote", scene.render.filepath)
