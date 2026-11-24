"""Headless Blender: re-proportion a mannequin-named character so it can skin the existing physics body.

The physics humanoid (sim/assets/humanoid.xml) was built from UE5 Manny's joints, and UMuJoCoBoneMapper drives
bone ROTATIONS only (plus the pelvis position). A character whose joints are not where Manny's are would float
(short legs) or miss the ball (short arms). This script moves every main joint of the source rig onto Manny's
bind-pose joint (shared/mannequin_bones.json) and deforms the mesh with it, so qpos = 0 in MuJoCo matches the
new bind pose exactly as it does for Manny.

Per chain bone b with chain child c, a linear map T_b sends the source segment head->child onto Manny's
(two-vector frame alignment, stretch along the segment by |target| / |source|, cross-section scaled by the
global scale g). End bones (head, hands, toes) are rigid (rotation + g). Every other bone (twists, fingers, face)
follows its nearest chain ancestor. Vertices (and every shape key) get the weight-blended T, i.e. linear blend
skinning with these maps; edit bones get head/tail/roll mapped the same way.

    blender -b --factory-startup --python retarget_grandma_blender.py -- <in.fbx> <mannequin_bones.json> <out.fbx> <preview_dir> [global_scale]
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

src_fbx, manny_json, out_fbx, preview_dir = sys.argv[sys.argv.index("--") + 1:][:4]

# chain bone -> (child joint used for the segment, secondary-axis pair or None, mode)
CHAIN = {
    "pelvis": (None, None, "rigid_upright"),
    "spine_01": ("spine_02", None, "stretch"),
    "spine_02": ("spine_03", None, "stretch"),
    "spine_03": ("spine_04", None, "stretch"),
    "spine_04": ("spine_05", None, "stretch"),
    "spine_05": ("neck_01", None, "stretch"),
    "neck_01": ("neck_02", None, "stretch"),
    "neck_02": ("head", None, "stretch"),
    "head": (None, None, "rigid_upright"),
}
for s in ("l", "r"):
    CHAIN.update({
        f"clavicle_{s}": (f"upperarm_{s}", None, "stretch"),
        f"upperarm_{s}": (f"lowerarm_{s}", None, "stretch"),
        f"lowerarm_{s}": (f"hand_{s}", None, "stretch"),
        f"hand_{s}": (f"middle_01_{s}", (f"index_01_{s}", f"pinky_01_{s}"), "rigid"),
        f"thigh_{s}": (f"calf_{s}", None, "stretch"),
        f"calf_{s}": (f"foot_{s}", None, "stretch"),
        f"foot_{s}": (f"ball_{s}", None, "stretch"),
        f"ball_{s}": (None, None, "rigid_parent"),
    })
IK_FOLLOW = {"ik_foot_l": "foot_l", "ik_foot_r": "foot_r", "ik_hand_gun": "hand_r", "ik_hand_r": "hand_r", "ik_hand_l": "hand_l"}

# ---------------------------------------------------------------- load
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src_fbx)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = next(o for o in bpy.data.objects if o.type == "MESH")
bones = arm.data.bones
Aw = arm.matrix_world.copy()
Hg = {b.name: Aw @ b.head_local for b in bones}

manny = json.load(open(manny_json, encoding="utf-8"))
# UE component space (cm, left-handed, +Y forward) -> Blender world (m, right-handed, -Y forward)
Ht = {b["name"]: Vector((b["component_space"]["pos_cm"][0], -b["component_space"]["pos_cm"][1],
                         b["component_space"]["pos_cm"][2])) / 100.0 for b in manny["bones"]}
missing = [n for n in CHAIN if n not in Hg or n not in Ht]
if missing:
    raise SystemExit(f"bones missing from source or Manny: {missing}")

g = (Ht["head"] - Ht["pelvis"]).length / (Hg["head"] - Hg["pelvis"]).length
# Optional 5th argument: fixed global scale. A MetaHuman body is already sized to Manny's height by its own body
# constraints (Scripts/build_grandma_metahuman.py), so its widths are right as they are: pass 1.0 so cross-sections,
# hands and feet are not widened by the torso ratio (the separate face mesh is never scaled).
_extra = sys.argv[sys.argv.index("--") + 1:][4:]
if _extra:
    print(f"RETARGET torso ratio {g:.4f}, global scale fixed to {float(_extra[0]):.4f}")
    g = float(_extra[0])
print(f"RETARGET global scale g = {g:.4f}")


def frame(p: Vector, s: Vector | None) -> Matrix:
    p = p.normalized()
    if s is None or abs(p.dot(s.normalized())) > 0.95:
        s = Vector((1, 0, 0)) if abs(p.x) < 0.9 else Vector((0, 1, 0))
    s = (s - p * p.dot(s)).normalized()
    return Matrix((p, s, p.cross(s))).transposed()   # columns = axes


def align(b: str):
    child, sec, _ = CHAIN[b]
    u, v = Hg[child] - Hg[b], Ht[child] - Ht[b]
    su = sv = None
    if sec:
        su, sv = Hg[sec[1]] - Hg[sec[0]], Ht[sec[1]] - Ht[sec[0]]
    else:   # keep the sideways axis: limbs and spine keep their lateral direction
        su = sv = Vector((1, 0, 0))
    Fu, Fv = frame(u, su), frame(v, sv)
    return Fv @ Fu.transposed(), u, v


L = {}   # bone -> (3x3 linear map, source pivot, target pivot)
for b, (child, sec, mode) in CHAIN.items():
    if mode == "rigid_upright":
        L[b] = (Matrix.Identity(3) * g, Hg[b], Ht[b])
    elif mode == "rigid_parent":
        R, _, _ = align(bones[b].parent.name)
        L[b] = (R * g, Hg[b], Ht[b])
    elif mode == "rigid":
        R, _, _ = align(b)
        L[b] = (R * g, Hg[b], Ht[b])
    else:
        R, u, v = align(b)
        k = v.length / u.length
        un = u.normalized()
        S = Matrix.Identity(3) * g + (k - g) * Matrix([[un[i] * un[j] for j in range(3)] for i in range(3)])
        L[b] = (R @ S, Hg[b], Ht[b])
        print(f"RETARGET {b:12s} stretch {k / g:5.2f}x (segment {u.length * g:.3f} m -> {v.length:.3f} m)")


def owner(name: str) -> str | None:
    if name in IK_FOLLOW:
        return IK_FOLLOW[name]
    bn = bones.get(name)
    while bn is not None and bn.name not in CHAIN:
        bn = bn.parent
    return bn.name if bn else None


def apply_map(b: str | None, x: Vector) -> Vector:
    if b is None:
        return x.copy()
    M, ps, pt = L[b]
    return pt + M @ (x - ps)


# ---------------------------------------------------------------- deform the mesh (base + every shape key)
Mw, Mw_inv = mesh.matrix_world.copy(), mesh.matrix_world.inverted()
nv = len(mesh.data.vertices)
gi_owner = {vg.index: owner(vg.name) for vg in mesh.vertex_groups}
weights = []
for v in mesh.data.vertices:
    acc = {}
    for ge in v.groups:
        o = gi_owner.get(ge.group)
        if o is not None and ge.weight > 0:
            acc[o] = acc.get(o, 0.0) + ge.weight
    tot = sum(acc.values())
    weights.append({k: w / tot for k, w in acc.items()} if tot > 0 else {"pelvis": 1.0})

owners = sorted(L)
oi = {b: i for i, b in enumerate(owners)}
W = np.zeros((nv, len(owners)))
for i, d in enumerate(weights):
    for b, w in d.items():
        W[i, oi[b]] = w
Ms = np.array([np.array(L[b][0]) for b in owners])          # (B,3,3)
Ps = np.array([np.array(L[b][1]) for b in owners])          # (B,3)
Pt = np.array([np.array(L[b][2]) for b in owners])
Mw_np, Mwi_np = np.array(Mw), np.array(Mw_inv)


def deform(local_co: np.ndarray) -> np.ndarray:
    world = local_co @ Mw_np[:3, :3].T + Mw_np[:3, 3]
    per = Pt[None] + np.einsum("bij,nbj->nbi", Ms, world[:, None, :] - Ps[None])   # (N,B,3)
    out = np.einsum("nb,nbi->ni", W, per)
    return out @ Mwi_np[:3, :3].T + Mwi_np[:3, 3]


def get_co(coll) -> np.ndarray:
    a = np.empty(len(coll) * 3)
    coll.foreach_get("co", a)
    return a.reshape(-1, 3)


def set_co(coll, a: np.ndarray):
    coll.foreach_set("co", a.ravel())


base_world = deform(get_co(mesh.data.vertices)) @ Mw_np[:3, :3].T + Mw_np[:3, 3]
# Feet: the source sole sits lower under the ankle than Manny's, so after the joint fit the soles would sink
# into the court. Remap z below each ankle linearly so the ankle stays put and the lowest foot vertex lands on
# z = 0, weighted by the vertex's foot+ball share (smooth into the calf).
FOOT = {}
for s in ("l", "r"):
    w = W[:, oi[f"foot_{s}"]] + W[:, oi[f"ball_{s}"]]
    sel = w > 0.5
    if not sel.any():  # a mesh without feet (e.g. a MetaHuman outfit): nothing to put on the floor
        print(f"RETARGET foot_{s}: no foot vertices, soles left as they are")
        continue
    FOOT[s] = (w, float(Ht[f"foot_{s}"].z), float(base_world[sel, 2].min()))
    print(f"RETARGET foot_{s}: sole z {FOOT[s][2] * 100:.1f} cm -> 0.0 cm (ankle {FOOT[s][1] * 100:.1f} cm)")


def fix_feet(local_co: np.ndarray) -> np.ndarray:
    world = local_co @ Mw_np[:3, :3].T + Mw_np[:3, 3]
    z = world[:, 2]
    for w, ha, zmin in FOOT.values():
        low = z < ha
        zr = ha - (ha - z) * ha / (ha - zmin)
        z = np.where(low, z + w * (zr - z), z)
    world[:, 2] = z
    return (world - Mw_np[:3, 3]) @ Mwi_np[:3, :3].T


set_co(mesh.data.vertices, fix_feet(deform(get_co(mesh.data.vertices))))
if mesh.data.shape_keys:
    for kb in mesh.data.shape_keys.key_blocks:
        set_co(kb.data, fix_feet(deform(get_co(kb.data))))
mesh.data.update()

# ---------------------------------------------------------------- move the rest skeleton
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
Aw_inv = Aw.inverted()
A3, A3_inv = Aw.to_3x3(), Aw.to_3x3().inverted()
new = {}
for eb in arm.data.edit_bones:
    o = owner(eb.name)
    head_w, tail_w = Aw @ eb.head, Aw @ eb.tail
    z_w = (A3 @ eb.z_axis).normalized()
    nh, nt = apply_map(o, head_w), apply_map(o, tail_w)
    nz = (L[o][0] @ z_w) if o else z_w
    new[eb.name] = (Aw_inv @ nh, Aw_inv @ nt, (A3_inv @ nz).normalized())
for eb in arm.data.edit_bones:
    h, t, z = new[eb.name]
    eb.head, eb.tail = h, t
    eb.align_roll(z)
bpy.ops.object.mode_set(mode="OBJECT")

err = max((Aw @ arm.data.bones[b].head_local - Ht[b]).length for b in CHAIN)
print(f"RETARGET max joint error vs Manny = {err * 1000:.2f} mm")
zmin = min((Mw @ v.co).z for v in mesh.data.vertices)
zmax = max((Mw @ v.co).z for v in mesh.data.vertices)
print(f"RETARGET new height {zmax - zmin:.3f} m, sole at z = {zmin * 100:.1f} cm")

# ---------------------------------------------------------------- export
os.makedirs(os.path.dirname(out_fbx), exist_ok=True)
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
mesh.select_set(True)
bpy.ops.export_scene.fbx(filepath=out_fbx, use_selection=True, object_types={"ARMATURE", "MESH"},
                         add_leaf_bones=False, bake_anim=False, path_mode="COPY", embed_textures=True,
                         use_armature_deform_only=False, mesh_smooth_type="FACE")
print(f"RETARGET wrote {out_fbx}")
