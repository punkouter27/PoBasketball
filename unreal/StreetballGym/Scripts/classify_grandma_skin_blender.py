import bpy, sys, json, math, colorsys, mathutils
import numpy as np
src, out = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
o = [x for x in bpy.data.objects if x.type == "MESH"][0]
arm = [x for x in bpy.data.objects if x.type == "ARMATURE"][0]
nt0 = o.active_material.node_tree
bsdf0 = next(n for n in nt0.nodes if n.type == "BSDF_PRINCIPLED")
def upstream_image(sock, depth=0):
    for l in sock.links:
        n = l.from_node
        if n.type == "TEX_IMAGE" and n.image: return n.image
        if depth < 4:
            for i in n.inputs:
                r = upstream_image(i, depth + 1)
                if r: return r
    return None
img = upstream_image(bsdf0.inputs["Base Color"])
print("CLASSIFY images", [(n.image.name, n.image.colorspace_settings.name, [l.to_socket.name for l in n.outputs[0].links]) for n in nt0.nodes if n.type == "TEX_IMAGE" and n.image])
print("CLASSIFY base image", img.name if img else None)
W, H = img.size
px = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, img.channels)[:, :, :3]
me = o.data
uv = me.uv_layers.active.data
nv = len(me.vertices)
acc = np.zeros((nv, 3)); cnt = np.zeros(nv)
for loop in me.loops:
    u, v = uv[loop.index].uv
    x = min(W - 1, max(0, int((u % 1.0) * W))); y = min(H - 1, max(0, int((v % 1.0) * H)))
    acc[loop.vertex_index] += px[y, x]; cnt[loop.vertex_index] += 1
col = acc / np.maximum(cnt, 1)[:, None]
hsv = np.array([colorsys.rgb_to_hsv(*c) for c in col])
mw = o.matrix_world
co = np.array([tuple(mw @ v.co) for v in me.vertices])
bones = {b.name: arm.matrix_world @ b.head_local for b in arm.data.bones}
z_neck = bones["neck_01"].z
zmin, zmax = co[:, 2].min(), co[:, 2].max()
region = co[:, 2] > z_neck - 0.02 * (zmax - zmin)
h, s, v = hsv[:, 0] * 360, hsv[:, 1], hsv[:, 2]
# stats in the region to pick thresholds
for name, m in (("region", region),):
    hh = h[m]; ss = s[m]; vv = v[m]
    print("CLASSIFY hue pct", np.percentile(hh, [5, 25, 50, 75, 95]).round(1), "sat", np.percentile(ss, [5, 25, 50, 75, 95]).round(2), "val", np.percentile(vv, [5, 50, 95]).round(2))
skin = region & (s > 0.18) & (s < 0.75) & ((h < float(__import__("os").environ.get("SKIN_HUE_MAX", "21"))) | (h > 340)) & (v > 0.15)
print("CLASSIFY region", int(region.sum()), "skin", int(skin.sum()), "z_neck", round(z_neck, 3), "height", round(zmax - zmin, 3))
json.dump({"skin_world": co[skin].round(5).tolist(), "all_bbox": [co.min(0).tolist(), co.max(0).tolist()],
           "head_bone": list(bones["head"]), "neck_01": list(bones["neck_01"])}, open(out + "/skin.json", "w"))
# debug render: skin red, rest grey (vertex colours)
ca = me.color_attributes.new("dbg", "FLOAT_COLOR", "POINT")
for i in range(nv):
    ca.data[i].color = (0.9, 0.1, 0.1, 1) if skin[i] else (0.6, 0.6, 0.6, 1)
mat = bpy.data.materials.new("dbg"); mat.use_nodes = True
nt = mat.node_tree; bsdf = nt.nodes["Principled BSDF"]; attr = nt.nodes.new("ShaderNodeAttribute"); attr.attribute_name = "dbg"
nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
o.data.materials.clear(); o.data.materials.append(mat)
scn = bpy.context.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scn.collection.objects.link(cam); cam.data.lens = 70
l = bpy.data.objects.new("l", bpy.data.lights.new("l", "SUN")); scn.collection.objects.link(l); l.rotation_euler = (math.radians(40), 0, 0); l.data.energy = 3
scn.render.resolution_x = scn.render.resolution_y = 512; scn.camera = cam
hc = mathutils.Vector(bones["head"]) + mathutils.Vector((0, 0, 0.06 * (zmax - zmin) / 1.8))
for nm, d in (("front", (0, -1, 0)), ("side", (1, 0, 0)), ("back", (0, 1, 0))):
    cam.location = hc + mathutils.Vector(d) * 0.9 * (zmax - zmin) / 1.8
    cam.rotation_euler = (hc - cam.location).to_track_quat("-Z", "Y").to_euler()
    scn.render.filepath = f"{out}/skin_{nm}.png"; bpy.ops.render.render(write_still=True)
