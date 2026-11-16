"""Headless Blender: front + side orthographic preview of a character FBX, with Manny's bind joints as red dots.

    blender -b --factory-startup --python render_character_preview.py -- <in.fbx> <mannequin_bones.json> <out.png> [fit_height_m]

fit_height_m (optional) uniformly rescales the import to that height so an unretargeted source can be compared
against the same joints.
"""
import json
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
src, manny_json, out_png = args[:3]
fit = float(args[3]) if len(args) > 3 else 0.0

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
mesh = next(o for o in bpy.data.objects if o.type == "MESH")
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
dg = bpy.context.evaluated_depsgraph_get()
zs = [(mesh.matrix_world @ v.co).z for v in mesh.data.vertices]
if fit > 0:
    k = fit / (max(zs) - min(zs))
    arm.animation_data_clear()
    arm.scale = arm.scale * k
    arm.location.z -= min(zs) * k

manny = json.load(open(manny_json, encoding="utf-8"))
mat = bpy.data.materials.new("joint")
mat.diffuse_color = (1, 0.05, 0.05, 1)
for b in manny["bones"]:
    if b["name"].startswith(("ik_", "interaction", "center", "root")) or any(f in b["name"] for f in ("index", "middle", "ring", "pinky", "thumb", "twist")):
        continue
    p = b["component_space"]["pos_cm"]
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.018, location=(p[0] / 100, -p[1] / 100, p[2] / 100))
    bpy.context.object.data.materials.append(mat)
    bpy.context.object.show_in_front = True

bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 0, 0))
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.display.shading.show_xray = False
scene.render.resolution_x, scene.render.resolution_y = 1400, 1100
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.18, 0.18, 0.2)

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = 2.6
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

import os  # noqa: E402
base, ext = os.path.splitext(out_png)
for tag, loc, rot in (("front", (0, -5, 0.95), (1.5708, 0, 0)), ("side", (5, 0, 0.95), (1.5708, 0, 1.5708))):
    cam.location, cam.rotation_euler = Vector(loc), rot
    scene.render.filepath = f"{base}_{tag}{ext}"
    bpy.ops.render.render(write_still=True)
    print("PREVIEW wrote", scene.render.filepath)
