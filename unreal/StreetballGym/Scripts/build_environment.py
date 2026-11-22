"""Items 5-6: the PCG neighbourhood around the court (outside the fence; nothing here is in the MuJoCo scene).

    run_headless.ps1 -EditorArgs @("-run=pythonscript", "-script=<this file>")     (after import_env_assets.py)

Builds /Game/Project/Environments/PCG/PCG_Neighbourhood and puts a PCG Volume ("StreetballNeighbourhood") into /Game/Project/Environments/Maps/Court. The graph:
  layout anchors (Create Points, from the ring geometry below)
    -> Attribute Noise on density -> Density Filter (random thinning per seed)
    -> Transform Points (position / yaw / scale jitter)
    -> Static Mesh Spawner (weighted pick from Content/Art/env_slots.json)
Branches: brownstone rows facing the court, sidewalk + street ground strips, street trees and lights, benches /
trash cans / hydrants / a fountain on the sidewalk, parked cars along the curb, weeds along the fence base and litter.
Court wear (item 6) lives in M_CourtAsphalt (scuffs under the hoops, faded paint, cracks, puddles).

The component generates on load with seed PCG_SEED; change the seed (or env_slots.json, to swap in Megascans/Fab
meshes) and re-run for a different neighbourhood. All spawned meshes have collision off (MuJoCo owns physics).
"""
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unreal  # noqa: E402

L = unreal.StreetballEditorLibrary
EAL = unreal.EditorAssetLibrary
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLOTS_JSON = os.path.join(PROJECT, "Content", "Art", "env_slots.json")
GRAPH = "/Game/Project/Environments/PCG/PCG_Neighbourhood"
MAP = "/Game/Project/Environments/Maps/Court"
PCG_SEED = 1959

# ring geometry (metres, court centre at the origin; fence half extents from court.xml)
FX, FY = 16.0, 9.5
SIDEWALK = 4.0       # inner sidewalk outside the fence
STREET = 8.0
FAR_WALK = 3.0
CUBE = "/Engine/BasicShapes/Cube.Cube"


def pt(x, y, z=0.0, yaw=0.0, sx=1.0, sy=1.0, sz=1.0, seed=0):
    q = unreal.Rotator(0.0, 0.0, yaw).quaternion() if hasattr(unreal.Rotator(0.0, 0.0, yaw), "quaternion") else None
    qx, qy, qz, qw = (q.x, q.y, q.z, q.w) if q else (0.0, 0.0, math.sin(math.radians(yaw) / 2), math.cos(math.radians(yaw) / 2))
    return (f"(Transform=(Rotation=(X={qx:.6f},Y={qy:.6f},Z={qz:.6f},W={qw:.6f}),Translation=(X={x * 100:.1f},Y={y * 100:.1f},Z={z * 100:.1f}),"
            f"Scale3D=(X={sx:.4f},Y={sy:.4f},Z={sz:.4f})),Density=1.000000,BoundsMin=(X=-50,Y=-50,Z=-50),BoundsMax=(X=50,Y=50,Z=50),"
            f"Color=(X=1,Y=1,Z=1,W=1),Steepness=1.000000,Seed={seed})")


def ring(offset, spacing, yaw_facing_court=True, jitter_start=0.0):
    """Points on the rectangle FX+offset, FY+offset; yaw makes local +X face the court."""
    out = []
    ax, ay = FX + offset, FY + offset
    for side in range(4):
        if side in (0, 1):            # north (+y) / south (-y): run along x
            y = ay if side == 0 else -ay
            n = int((2 * ax) // spacing)
            for i in range(n + 1):
                x = -ax + jitter_start + i * spacing
                if x > ax:
                    break
                out.append((x, y, -90.0 if side == 0 else 90.0))
        else:                         # east (+x) / west (-x): run along y
            x = ax if side == 2 else -ax
            n = int((2 * ay) // spacing)
            for i in range(1, n):
                yv = -ay + i * spacing
                out.append((x, yv, 180.0 if side == 2 else 0.0))
    return out


def layout():
    rnd = random.Random(PCG_SEED)
    L_ = {}
    # brownstones: facade line just past the far sidewalk; pivot is 5 m behind the facade
    face = SIDEWALK + STREET + FAR_WALK
    L_["building"] = [pt(x, y, 0, yaw, seed=i) for i, (x, y, yaw) in enumerate(ring(face + 5.0, 13.6, jitter_start=1.0))]
    # ground strips (scaled engine cubes): sidewalk 10 cm high, street asphalt flush-ish with the court
    g = []
    for off, width, z, h in ((SIDEWALK / 2, SIDEWALK, 0.05, 0.10), (SIDEWALK + STREET / 2, STREET, -0.01, 0.01),
                             (SIDEWALK + STREET + FAR_WALK / 2, FAR_WALK, 0.05, 0.10)):
        ax, ay = FX + off, FY + off
        lx, ly = 2 * (FX + off + width / 2), 2 * (FY + off + width / 2)
        g += [pt(0, ay, z, 0, lx, width, h), pt(0, -ay, z, 0, lx, width, h),
              pt(ax, 0, z, 0, width, ly - 2 * width, h), pt(-ax, 0, z, 0, width, ly - 2 * width, h)]
    L_["ground_sidewalk"] = [p for i, p in enumerate(g) if i // 4 in (0, 2)]
    L_["ground_street"] = [p for i, p in enumerate(g) if i // 4 == 1]
    L_["tree"] = [pt(x, y, 0.1, rnd.uniform(0, 360), seed=i) for i, (x, y, _) in enumerate(ring(SIDEWALK + STREET + 1.5, 9.0, jitter_start=3.0))]
    L_["streetlight"] = [pt(x, y, 0.1, yaw, seed=i) for i, (x, y, yaw) in enumerate(ring(SIDEWALK - 0.5, 17.0, jitter_start=7.0))]
    L_["sidewalk_prop"] = [pt(x, y, 0.1, yaw + 180.0, seed=i) for i, (x, y, yaw) in enumerate(ring(1.3, 5.5, jitter_start=1.5))]
    L_["car"] = [pt(x, y, -0.01, yaw + 90.0 + (180.0 if rnd.random() < 0.5 else 0.0), seed=i)
                 for i, (x, y, yaw) in enumerate(ring(SIDEWALK + 1.2, 6.0, jitter_start=2.0))]
    L_["weeds"] = [pt(x, y, 0.0, rnd.uniform(0, 360), seed=i) for i, (x, y, _) in enumerate(ring(0.15, 1.1, jitter_start=0.3))]
    L_["litter"] = [pt(x + rnd.uniform(-1, 1), y + rnd.uniform(-1, 1), 0.1, rnd.uniform(0, 360), seed=i)
                    for i, (x, y, _) in enumerate(ring(SIDEWALK * 0.5, 2.2))]
    return L_


# branch -> (slots with weights, keep fraction, jitter: (offset m, yaw deg, scale lo, scale hi))
BRANCHES = {
    "building": ({"building": 1}, 1.0, (0.0, 0.0, 1.0, 1.0)),
    "ground_sidewalk": ({"_cube_concrete": 1}, 1.0, None),
    "ground_street": ({"_cube_asphalt": 1}, 1.0, None),
    "tree": ({"tree": 1}, 0.8, (0.3, 0.0, 0.85, 1.15)),
    "streetlight": ({"streetlight": 1}, 1.0, (0.0, 0.0, 1.0, 1.0)),
    "sidewalk_prop": ({"bench": 3, "trash_can": 3, "hydrant": 2, "fountain": 1}, 0.45, (0.2, 8.0, 1.0, 1.0)),
    "car": ({"car": 1}, 0.55, (0.15, 3.0, 1.0, 1.0)),
    "weeds": ({"weeds": 1}, 0.5, (0.08, 180.0, 0.6, 1.5)),
    "litter": ({"litter": 1}, 0.3, (0.6, 180.0, 0.9, 1.2)),
}


def mesh_entries(slots, weights):
    entries = []
    for slot, w in weights.items():
        if slot == "_cube_concrete":
            paths = [(CUBE, "/Game/Project/Environments/Env/Materials/MI_Env_Concrete.MI_Env_Concrete")]
        elif slot == "_cube_asphalt":
            paths = [(CUBE, "/Game/Project/Environments/Materials/MI_CourtAsphalt.MI_CourtAsphalt")]
        else:
            paths = [(p if "." in p.rsplit("/", 1)[-1] else f"{p}.{p.rsplit('/', 1)[-1]}", None) for p in slots.get(slot, [])]
        for p, mat in paths:
            mats = f',OverrideMaterials=("{mat}")' if mat else ""
            entries.append(f'(Descriptor=(StaticMesh="{p}"{mats},BodyInstance=(CollisionProfileName="NoCollision",CollisionEnabled=NoCollision),'
                           f'bCastShadow=True),Weight={max(1, int(w))})')
    return "(" + ",".join(entries) + ")"


def build_graph(slots):
    if EAL.does_asset_exist(GRAPH):
        EAL.delete_asset(GRAPH)
    graph = unreal.AssetToolsHelpers.get_asset_tools().create_asset("PCG_Neighbourhood", "/Game/Project/Environments/PCG", unreal.PCGGraph, unreal.PCGGraphFactory())
    lay = layout()
    for name, (weights, keep, jit) in BRANCHES.items():
        entries = mesh_entries(slots, weights)
        if entries == "()":
            unreal.log_warning(f"PCG branch {name}: no meshes for {list(weights)}")
            continue
        n_create, s_create = graph.add_node_of_type(unreal.PCGCreatePointsSettings)
        if not L.set_property_text(s_create, "PointsToCreate", "(" + ",".join(lay[name]) + ")"):
            raise RuntimeError(f"PCG {name}: PointsToCreate")
        last = n_create
        if keep < 1.0:
            n_noise, s_noise = graph.add_node_of_type(unreal.PCGAttributeNoiseSettings)
            n_filter, s_filter = graph.add_node_of_type(unreal.PCGDensityFilterSettings)
            s_filter.set_editor_property("lower_bound", 1.0 - keep)
            s_filter.set_editor_property("upper_bound", 1.0)
            graph.add_edge(last, "Out", n_noise, "In")
            graph.add_edge(n_noise, "Out", n_filter, "In")
            last = n_filter
        if jit:
            off, yaw, slo, shi = jit
            n_tr, s_tr = graph.add_node_of_type(unreal.PCGTransformPointsSettings)
            s_tr.set_editor_property("offset_min", unreal.Vector(-off * 100, -off * 100, 0))
            s_tr.set_editor_property("offset_max", unreal.Vector(off * 100, off * 100, 0))
            s_tr.set_editor_property("rotation_min", unreal.Rotator(0, 0, -yaw))
            s_tr.set_editor_property("rotation_max", unreal.Rotator(0, 0, yaw))
            s_tr.set_editor_property("scale_min", unreal.Vector(slo, slo, slo))
            s_tr.set_editor_property("scale_max", unreal.Vector(shi, shi, shi))
            s_tr.set_editor_property("uniform_scale", True)
            graph.add_edge(last, "Out", n_tr, "In")
            last = n_tr
        n_sp, s_sp = graph.add_node_of_type(unreal.PCGStaticMeshSpawnerSettings)
        s_sp.set_editor_property("apply_mesh_bounds_to_points", False)
        if not L.set_property_text(s_sp, "MeshSelectorParameters.MeshEntries", entries):
            raise RuntimeError(f"PCG {name}: mesh entries {entries[:200]}")
        graph.add_edge(last, "Out", n_sp, "In")
        unreal.log(f"PCG branch {name}: {len(lay[name])} anchors, keep {keep:.2f}, {entries.count('Descriptor=')} meshes")
    EAL.save_loaded_asset(graph)
    return graph


def place_volume(graph):
    world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    if world is None:
        raise RuntimeError("cannot load Court map")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in actors.get_all_level_actors():
        if a.get_actor_label() == "StreetballNeighbourhood":
            actors.destroy_actor(a)
    vol = actors.spawn_actor_from_class(unreal.PCGVolume, unreal.Vector(0, 0, 500))
    vol.set_actor_label("StreetballNeighbourhood")
    vol.set_editor_property("tags", [unreal.Name("StreetballNeighbourhood")])   # -StreetballNoPresentation hides it
    vol.set_actor_scale3d(unreal.Vector(70.0, 55.0, 20.0))      # brush is 200 uu: 140 m x 110 m x 40 m
    comp = vol.get_component_by_class(unreal.PCGComponent)
    comp.set_graph(graph)
    comp.set_editor_property("seed", PCG_SEED)
    comp.set_editor_property("generation_trigger", unreal.PCGComponentGenerationTrigger.GENERATE_ON_LOAD)
    unreal.EditorLoadingAndSavingUtils.save_current_level()
    return vol


def main():
    with open(SLOTS_JSON, encoding="utf-8") as f:
        slots = json.load(f)
    graph = build_graph(slots)
    place_volume(graph)
    unreal.log(f"ENVIRONMENT OK graph {GRAPH}, volume in {MAP}, seed {PCG_SEED}")


main()
