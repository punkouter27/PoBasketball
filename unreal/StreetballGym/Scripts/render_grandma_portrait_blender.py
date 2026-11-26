"""Front portrait of the original grandma for the MetaHuman landmark tracker (2026-11-24).

The headless editor's scene capture renders her material black, so the portrait is rendered here with the exact camera
build_grandma_cc_metahuman.py chose (camera.json, UE cm). SK_Grandma.fbx imports into UE as (x, -y, z) * 100, so the
Blender camera is (x, -y, z) / 100 looking at the same point, same horizontal FOV, square image: identical framing.

    blender -b --factory-startup --python render_grandma_portrait_blender.py -- <SK_Grandma.fbx> <work dir>
"""
import json
import math
import sys

import bpy
import mathutils

src, work = sys.argv[sys.argv.index("--") + 1:][:2]
cam_ue = json.load(open(f"{work}/camera.json"))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)


def ue_to_b(p):
    return mathutils.Vector((p[0] / 100.0, -p[1] / 100.0, p[2] / 100.0))


loc = ue_to_b(cam_ue["location"])
target = ue_to_b(cam_ue["target"])
scn = bpy.context.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam)
cam.data.sensor_fit = "HORIZONTAL"
cam.data.angle = math.radians(cam_ue["fov"])
cam.location = loc
cam.rotation_euler = (target - loc).to_track_quat("-Z", "Y").to_euler()
# soft, even portrait light: key from the front-left above, fill from the right, warm-grey world
for rot, energy in (((55, 0, -25), 3.0), ((70, 0, 60), 1.2), ((100, 0, 180), 0.6)):
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    scn.collection.objects.link(sun)
    sun.rotation_euler = tuple(math.radians(a) for a in rot)
    sun.data.energy = energy
scn.world = bpy.data.worlds.new("w")
scn.world.color = (0.45, 0.45, 0.47)
scn.render.resolution_x, scn.render.resolution_y = cam_ue["size"]
scn.render.film_transparent = False
scn.camera = cam
scn.render.filepath = f"{work}/portrait.png"
bpy.ops.render.render(write_still=True)
print("PORTRAIT wrote", scn.render.filepath)
