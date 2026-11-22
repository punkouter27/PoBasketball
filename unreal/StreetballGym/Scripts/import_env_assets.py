"""Items 1-2 (stand-ins): import the Blender proxy props (make_env_proxies_blender.py -> Content/Art/Exports/Env) and give
every material slot a Substrate instance by slot name. Writes Content/Art/env_slots.json, the swap table the PCG
neighbourhood (build_environment.py) reads.

    run_headless.ps1 -EditorArgs @("-run=pythonscript", "-script=<this file>")

Swapping in Megascans / Fab assets later: download them in the editor (Fab panel, needs the user's Epic sign-in),
then edit env_slots.json so a slot lists the new mesh paths (e.g. "bench": ["/Game/Fab/Bench_01/SM_Bench_01"]) and
re-run build_environment.py. Slots keep any paths that are not under /Game/Project/Environments/Env/Proxy when this script re-runs.
"""
import json
import os

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import unreal  # noqa: E402
import sbmat  # noqa: E402
from sbmat import Graph

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS = os.path.join(PROJECT, "Content", "Art", "Exports", "Env")
SLOTS_JSON = os.path.join(PROJECT, "Content", "Art", "env_slots.json")
DEST = "/Game/Project/Environments/Env/Proxy"
MATS = "/Game/Project/Environments/Env/Materials"

# slot material -> (base colour, roughness, metallic, emissive)
LOOK = {
    "M_Brick": ((0.30, 0.11, 0.07), 0.88, 0.0, 0.0), "M_Concrete": ((0.42, 0.41, 0.39), 0.9, 0.0, 0.0),
    "M_Wood": ((0.33, 0.20, 0.11), 0.72, 0.0, 0.0), "M_Glass": ((0.015, 0.02, 0.025), 0.06, 0.0, 0.0),
    "M_Window": ((0.80, 0.79, 0.75), 0.5, 0.0, 0.0), "M_Paint": ((0.70, 0.67, 0.60), 0.6, 0.0, 0.0),
    "M_Metal": ((0.32, 0.32, 0.34), 0.42, 1.0, 0.0), "M_Plastic": ((0.55, 0.09, 0.07), 0.5, 0.0, 0.0),
    "M_Water": ((0.08, 0.12, 0.16), 0.05, 0.0, 0.0), "M_CarPaint": ((0.10, 0.20, 0.42), 0.22, 0.0, 0.0),
    "M_Rubber": ((0.025, 0.025, 0.025), 0.9, 0.0, 0.0), "M_TailLight": ((0.55, 0.02, 0.02), 0.2, 0.0, 0.0),
    "M_Bark": ((0.19, 0.13, 0.08), 0.95, 0.0, 0.0), "M_Leaf": ((0.11, 0.26, 0.07), 0.7, 0.0, 0.0),
    "M_Emissive": ((1.0, 0.88, 0.66), 0.4, 0.0, 6.0), "M_HydrantPaint": ((0.58, 0.07, 0.04), 0.5, 0.0, 0.0),
    "M_Label": ((0.65, 0.09, 0.08), 0.4, 0.3, 0.0), "M_Paper": ((0.78, 0.76, 0.70), 0.92, 0.0, 0.0),
    "M_Net": ((0.92, 0.92, 0.90), 0.8, 0.0, 0.0), "M_Feather": ((0.33, 0.34, 0.38), 0.85, 0.0, 0.0),
    "M_Beak": ((0.55, 0.45, 0.28), 0.6, 0.0, 0.0),
}


def master(path, two_sided):
    m = sbmat.new_material(path, two_sided=two_sided)
    g = Graph(m)
    wp = sbmat.world_pos(g)
    n = g.e(unreal.MaterialExpressionNoise, scale=0.02, levels=3, output_min=0.82, output_max=1.12, quality=1)
    g.link(wp, "", n, "World Position")
    base = g.vector("BaseColor", 0.5, 0.5, 0.5)
    albedo_c = g.e(unreal.MaterialExpressionMultiply)
    g.link(base, "", albedo_c, "A")
    g.link(n, "", albedo_c, "B")
    metal = g.scalar("Metallic", 0.0)
    albedo = g.e(unreal.MaterialExpressionLinearInterpolate)
    g.link(albedo_c, "", albedo, "A")
    g.link(g.const3(0, 0, 0), "", albedo, "B")
    g.link(metal, "", albedo, "Alpha")
    f0 = g.e(unreal.MaterialExpressionLinearInterpolate)
    g.link(g.const3(0.04, 0.04, 0.04), "", f0, "A")
    g.link(albedo_c, "", f0, "B")
    g.link(metal, "", f0, "Alpha")
    em = g.e(unreal.MaterialExpressionMultiply)
    g.link(base, "", em, "A")
    g.link(g.scalar("Emissive", 0.0), "", em, "B")
    g.front(g.slab(albedo=(albedo, ""), f0=(f0, ""), roughness=(g.scalar("Roughness", 0.7), ""), emissive=(em, "")))
    return g.finish()


def import_fbx(fbx, name):
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_as_skeletal", False)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
    sm = ui.get_editor_property("static_mesh_import_data")
    sm.set_editor_property("combine_meshes", True)
    sm.set_editor_property("auto_generate_collision", False)
    sm.set_editor_property("vertex_color_import_option", unreal.VertexColorImportOption.REPLACE)   # net wobble mask
    sm.set_editor_property("generate_lightmap_u_vs", False)
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", fbx)
    t.set_editor_property("destination_path", DEST)
    t.set_editor_property("destination_name", name)
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", True)
    t.set_editor_property("options", ui)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    return unreal.load_asset(f"{DEST}/{name}")


def main():
    with open(os.path.join(EXPORTS, "env_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    entries = manifest["meshes"] if isinstance(manifest, dict) and "meshes" in manifest else manifest
    unreal.EditorAssetLibrary.make_directory(DEST)
    unreal.EditorAssetLibrary.make_directory(MATS)
    opaque = master(f"{MATS}/M_EnvProxy", False)
    foliage = master(f"{MATS}/M_EnvProxyTwoSided", True)
    instances = {}
    for slot, (col, rough, metal, emis) in LOOK.items():
        parent = foliage if slot in ("M_Leaf", "M_Net", "M_Paper") else opaque
        instances[slot] = sbmat.instance(parent, f"{MATS}/MI_Env_{slot[2:]}",
                                         scalars={"Roughness": rough, "Metallic": metal, "Emissive": emis},
                                         vectors={"BaseColor": (col[0], col[1], col[2], 1.0)})
    slots = {}
    if os.path.exists(SLOTS_JSON):
        with open(SLOTS_JSON, encoding="utf-8") as f:
            slots = {k: [p for p in v if not p.startswith(DEST)] for k, v in json.load(f).items()}
    count = 0
    for e in entries:
        name = e["name"]
        mesh = import_fbx(os.path.join(EXPORTS, e["fbx"]), name)
        if mesh is None:
            unreal.log_error(f"ENV import failed: {name}")
            continue
        for i, sm in enumerate(mesh.get_editor_property("static_materials")):
            slot = str(sm.get_editor_property("material_slot_name"))
            mi = instances.get(slot)
            if mi:
                mesh.set_material(i, mi)
        unreal.EditorAssetLibrary.save_loaded_asset(mesh)
        slots.setdefault(e.get("swap_slot", name), [])
        path = f"{DEST}/{name}"
        if path not in slots[e.get("swap_slot", name)]:
            slots[e.get("swap_slot", name)].append(path)
        count += 1
        unreal.log(f"ENV imported {path} ({len(mesh.get_editor_property('static_materials'))} slots)")
    with open(SLOTS_JSON, "w", encoding="utf-8") as f:
        json.dump(slots, f, indent=2)
    unreal.log(f"ENV_IMPORT OK {count} meshes, slots: {sorted(slots)}")


main()
