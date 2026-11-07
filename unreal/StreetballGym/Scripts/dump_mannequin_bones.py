"""Task A2: dump the UE5 Mannequin skeleton to JSON.

Run inside the Unreal editor (headless is fine):

    UnrealEditor-Cmd.exe <project>.uproject -run=pythonscript
        -script="<this file> <output.json>" -unattended -nop4 -nosplash

Output: for every bone, its name, parent, bind-pose (reference pose) world
transform in UE units (cm, left-handed, Z-up), its local transform, and the
distance to its parent (bone length in metres, for the MJCF author).
"""
import json
import sys

import unreal

MESH_PATH = "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple"
OUT = sys.argv[1] if len(sys.argv) > 1 else "mannequin_bones.json"


def _xf_to_dict(xf: unreal.Transform) -> dict:
    t = xf.translation
    r = xf.rotation  # FQuat
    s = xf.scale3d
    return {
        "pos_cm": [t.x, t.y, t.z],
        "quat_xyzw": [r.x, r.y, r.z, r.w],
        "scale": [s.x, s.y, s.z],
    }


def main() -> None:
    mesh = unreal.load_asset(MESH_PATH)
    if mesh is None:
        raise SystemExit(f"could not load {MESH_PATH}")
    skel = mesh.skeleton
    # Spawn a temporary component so we can query the reference pose in component space.
    world = unreal.EditorLevelLibrary.get_editor_world()
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0)
    )
    comp = actor.skeletal_mesh_component
    comp.set_skeletal_mesh_asset(mesh)
    # With no AnimInstance the component-space transforms are the reference pose.
    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_CUSTOM_MODE)

    bones = []
    for idx in range(comp.get_num_bones()):
        name = str(comp.get_bone_name(idx))
        parent_name = str(comp.get_parent_bone(name))
        world_xf = comp.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_WORLD)
        comp_xf = comp.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT)
        bones.append(
            {
                "name": name,
                "index": idx,
                "parent": parent_name if parent_name != "None" else None,
                "component_space": _xf_to_dict(comp_xf),
                "world_space": _xf_to_dict(world_xf),
            }
        )
    bones.sort(key=lambda b: b["index"])

    by_name = {b["name"]: b for b in bones}
    for b in bones:
        p = b["parent"]
        if p and p in by_name:
            a = b["component_space"]["pos_cm"]
            c = by_name[p]["component_space"]["pos_cm"]
            b["length_from_parent_m"] = (
                sum((a[i] - c[i]) ** 2 for i in range(3)) ** 0.5 / 100.0
            )
        else:
            b["length_from_parent_m"] = 0.0

    try:
        bmin, bmax = comp.get_local_bounds()
        bounds = {"min": [bmin.x, bmin.y, bmin.z], "max": [bmax.x, bmax.y, bmax.z]}
    except Exception as e:  # noqa: BLE001
        bounds = {"error": str(e)}
    out = {
        "mesh": MESH_PATH,
        "skeleton": skel.get_path_name(),
        "units": "cm, UE left-handed Z-up; quat as (x,y,z,w)",
        "mesh_bounds_cm": bounds,
        "bones": bones,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    actor.destroy_actor()
    unreal.log(f"wrote {len(bones)} bones to {OUT}")


main()
