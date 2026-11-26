"""The original grandma's body and clothes without her head and hair (2026-11-24), for the MetaHuman face made from her
own head (build_grandma_cc_metahuman.py). Same texture colour classes as classify_grandma_skin_blender.py:
    hair (blonde, hue 21-55, saturated)  -> removed everywhere (it hangs over the shoulders and back)
    skin (hue < 21)                      -> removed above the cut (just under neck_01): the MetaHuman neck covers it
    everything else (cardigan, trousers, shoes) -> kept
Exported with the same settings as retarget_grandma_blender.py, so it imports onto the same joints.

    blender -b --factory-startup --python make_grandma_headless_blender.py -- <SK_Grandma.fbx> <out.fbx> <preview dir>
"""
import colorsys
import math
import sys

import bmesh
import bpy
import mathutils
import numpy as np

src, out_fbx, preview = sys.argv[sys.argv.index("--") + 1:][:3]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
o = [x for x in bpy.data.objects if x.type == "MESH"][0]
arm = [x for x in bpy.data.objects if x.type == "ARMATURE"][0]

nt = o.active_material.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")


def upstream_image(sock, depth=0):
    for link in sock.links:
        n = link.from_node
        if n.type == "TEX_IMAGE" and n.image:
            return n.image
        if depth < 4:
            for i in n.inputs:
                r = upstream_image(i, depth + 1)
                if r:
                    return r
    return None


img = upstream_image(bsdf.inputs["Base Color"])
W, H = img.size
px = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, img.channels)[:, :, :3]
me = o.data
uv = me.uv_layers.active.data
acc = np.zeros((len(me.vertices), 3))
cnt = np.zeros(len(me.vertices))
for loop in me.loops:
    u, v = uv[loop.index].uv
    x = min(W - 1, max(0, int((u % 1.0) * W)))
    y = min(H - 1, max(0, int((v % 1.0) * H)))
    acc[loop.vertex_index] += px[y, x]
    cnt[loop.vertex_index] += 1
col = acc / np.maximum(cnt, 1)[:, None]
hsv = np.array([colorsys.rgb_to_hsv(*c) for c in col])
h, s, v = hsv[:, 0] * 360, hsv[:, 1], hsv[:, 2]
mw = o.matrix_world
z = np.array([(mw @ vt.co).z for vt in me.vertices])
height = z.max() - z.min()
neck = (arm.matrix_world @ arm.data.bones["neck_01"].head_local).z
cut = neck - 0.035 * height / 1.8
hair = (h >= 21) & (h <= 55) & (s > 0.25) & (v > 0.2) & (z > z.min() + 0.55 * height)
skin = (s > 0.18) & (s < 0.75) & ((h < 21) | (h > 340)) & (v > 0.15)
# everything above the top of the collar is head: hair, skin, earrings, the scalp's dark parts
head = z > neck + 0.02 * height / 1.8
drop = hair | (skin & (z > cut)) | head
print(f"HEADLESS verts {len(z)}, drop {int(drop.sum())} (hair {int(hair.sum())}, skin above cut {int((skin & (z > cut)).sum())}, "
      f"above collar {int(head.sum())}), neck_01 z {neck:.3f}, cut {cut:.3f}")
bm = bmesh.new()
bm.from_mesh(me)
bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.verts[i] for i in np.nonzero(drop)[0]], context="VERTS")
# loose fragments left by the colour test (stray hair/skin specks on the cardigan)
bm.verts.ensure_lookup_table()
islands, seen = [], set()
for vstart in bm.verts:
    if vstart.index in seen:
        continue
    stack, comp = [vstart], []
    seen.add(vstart.index)
    while stack:
        a = stack.pop()
        comp.append(a)
        for e in a.link_edges:
            b = e.other_vert(a)
            if b.index not in seen:
                seen.add(b.index)
                stack.append(b)
    islands.append(comp)
small = [vv for comp in islands if len(comp) < 30 for vv in comp]
bmesh.ops.delete(bm, geom=small, context="VERTS")
bm.to_mesh(me)
bm.free()
print(f"HEADLESS kept {len(me.vertices)} verts in {len(islands) - sum(1 for c in islands if len(c) < 30)} pieces")
o.name = "SK_GrandmaCC_Body"

# previews
scn = bpy.context.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam)
cam.data.lens = 50
for rot, e in (((55, 0, -25), 3.0), ((70, 0, 60), 1.0)):
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    scn.collection.objects.link(sun)
    sun.rotation_euler = tuple(math.radians(a) for a in rot)
    sun.data.energy = e
scn.world = bpy.data.worlds.new("w")
scn.world.color = (0.3, 0.3, 0.32)
scn.camera = cam
scn.render.resolution_x = scn.render.resolution_y = 512
c = mathutils.Vector((0, 0, neck - 0.15))
for name, d in (("front", (0, -1, 0.15)), ("back", (0, 1, 0.15))):
    cam.location = c + mathutils.Vector(d).normalized() * 1.6
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    scn.render.filepath = f"{preview}/headless_{name}.png"
    bpy.ops.render.render(write_still=True)

bpy.ops.object.select_all(action="DESELECT")
o.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.fbx(filepath=out_fbx, use_selection=True, object_types={"ARMATURE", "MESH"},
                         add_leaf_bones=False, bake_anim=False, path_mode="COPY", embed_textures=True,
                         use_armature_deform_only=False, mesh_smooth_type="FACE")
print("HEADLESS wrote", out_fbx)
