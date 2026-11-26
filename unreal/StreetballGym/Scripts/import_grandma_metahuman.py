"""Import the re-proportioned MetaHuman body (local only, git-ignored) as the main character's skeletal mesh.

    Content/Art/Exports/GrandmaMH/SK_GrandmaMH_{Body,Outfit}.fbx  (retarget_grandma_blender.py ... 1.0, from the
    MetaHuman build's body and baked outfit exported to Content/Art/Raw/GrandmaMH/)
    -> /Game/Project/Agents/GrandmaMH/SK_GrandmaMH_Body (+ _Skeleton) and SK_GrandmaMH_Outfit (same skeleton)

Materials are copied slot by slot from the build's meshes (the FBX round trip does not carry them). No physics asset: MuJoCo simulates the body.

    pwsh Scripts/run_headless.ps1 -TimeoutSec 900 "-ExecutePythonScript=<abs path>/Scripts/import_grandma_metahuman.py"
"""

import os

import unreal

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS = os.path.join(PROJECT, "Content", "Art", "Exports", "GrandmaMH")
DEST = "/Game/Project/Agents/GrandmaMH"


def import_one(fbx_name: str, dest_name: str, built: str, skeleton=None):
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_as_skeletal", True)
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", False)
    ui.set_editor_property("create_physics_asset", False)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    if skeleton is not None:
        ui.set_editor_property("skeleton", skeleton)  # the outfit shares the body's skeleton asset (leader pose)
    sk = ui.get_editor_property("skeletal_mesh_import_data")
    sk.set_editor_property("import_morph_targets", True)
    sk.set_editor_property("convert_scene", True)
    sk.set_editor_property("import_uniform_scale", 1.0)
    sk.set_editor_property("use_t0_as_ref_pose", False)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", os.path.join(EXPORTS, fbx_name))
    task.set_editor_property("destination_path", DEST)
    task.set_editor_property("destination_name", dest_name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    task.set_editor_property("options", ui)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    mesh = unreal.load_asset(f"{DEST}/{dest_name}")
    if mesh is None:
        raise SystemExit(f"GRANDMA_MH_IMPORT FAILED: {dest_name} not created")
    src_mats = list(unreal.load_asset(built).get_editor_property("materials"))
    dst_mats = list(mesh.get_editor_property("materials"))
    by_name = {str(m.material_slot_name): m.material_interface for m in src_mats}
    for i, m in enumerate(dst_mats):
        m.material_interface = by_name.get(str(m.material_slot_name)) or (src_mats[i].material_interface if i < len(src_mats) else None)
        dst_mats[i] = m
    mesh.set_editor_property("materials", dst_mats)
    unreal.EditorAssetLibrary.save_loaded_asset(mesh)
    unreal.log(f"GRANDMA_MH_IMPORT OK {dest_name}: "
               f"{[(str(m.material_slot_name), m.material_interface.get_name() if m.material_interface else None) for m in dst_mats]}")
    return mesh


body = import_one("SK_GrandmaMH_Body.fbx", "SK_GrandmaMH_Body", f"{DEST}/Build/MHC_Grandma/Body/SKM_MHC_Grandma_BodyMesh")
import_one("SK_GrandmaMH_Outfit.fbx", "SK_GrandmaMH_Outfit", f"{DEST}/Build/MHC_Grandma/Clothing/MHC_Grandma_Outfits",
           skeleton=body.get_editor_property("skeleton"))


def write_parts():
    """Parts list for AStreetballCharacter::AttachMetaHuman, read from the built Blueprint (the paths change with the
    hair/outfit choice): face mesh + its anim class (ABP_Face copies the pose from its attach parent = our body), and
    every groom with a binding. Written next to the FBX exports (git-ignored, local only)."""
    import json

    bp = unreal.load_asset(f"{DEST}/Build/MHC_Grandma/BP_MHC_Grandma")
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    parts = {"body": f"{DEST}/SK_GrandmaMH_Body.SK_GrandmaMH_Body", "outfit": f"{DEST}/SK_GrandmaMH_Outfit.SK_GrandmaMH_Outfit",
             "face": None, "face_anim_class": None, "grooms": {}}
    for h in sub.k2_gather_subobject_data_for_blueprint(context=bp):
        o = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(h))
        if o is None:
            continue
        name = o.get_name().replace("_GEN_VARIABLE", "")
        if isinstance(o, unreal.GroomComponent) and o.get_editor_property("groom_asset") and o.get_editor_property("binding_asset"):
            # the hair colour / cards / helmet materials live on the component, not on the groom asset
            mats = [m.get_path_name() if m else "" for m in o.get_editor_property("override_materials")]
            parts["grooms"][name] = {"groom": o.get_editor_property("groom_asset").get_path_name(),
                                     "binding": o.get_editor_property("binding_asset").get_path_name(), "materials": mats}
        elif isinstance(o, unreal.SkeletalMeshComponent) and name == "Face":
            parts["face"] = o.get_editor_property("skeletal_mesh_asset").get_path_name()
            cls = o.get_editor_property("anim_class")
            parts["face_anim_class"] = cls.get_path_name() if cls else None
    out = os.path.join(EXPORTS, "parts.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(parts, f, indent=2)
    unreal.log(f"GRANDMA_MH_IMPORT parts -> {out}: {parts}")


write_parts()
