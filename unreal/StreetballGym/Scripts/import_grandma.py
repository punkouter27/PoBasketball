"""Import the retargeted grandma (Content/Art/Exports/Grandma/SK_Grandma.fbx, made by retarget_grandma_blender.py)
as the main character's skeletal mesh, with its own skeleton, materials, textures and morph targets.

    UnrealEditor-Cmd.exe <project> -run=pythonscript -script="<this file>"     (via Scripts/run_headless.ps1)

Output: /Game/Project/Agents/Grandma/SK_Grandma (+ _Skeleton, materials, textures). No physics asset: the body
is simulated by MuJoCo, Chaos stays off.
"""
import os

import unreal

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "Content", "Art", "Exports", "Grandma", "SK_Grandma.fbx")
DEST = "/Game/Project/Agents/Grandma"

ui = unreal.FbxImportUI()
ui.set_editor_property("import_as_skeletal", True)
ui.set_editor_property("import_mesh", True)
ui.set_editor_property("import_materials", True)
ui.set_editor_property("import_textures", True)
ui.set_editor_property("import_animations", False)
ui.set_editor_property("create_physics_asset", False)
ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
sk = ui.get_editor_property("skeletal_mesh_import_data")
sk.set_editor_property("import_morph_targets", True)
sk.set_editor_property("convert_scene", True)
sk.set_editor_property("import_uniform_scale", 1.0)
sk.set_editor_property("use_t0_as_ref_pose", False)

task = unreal.AssetImportTask()
task.set_editor_property("filename", SRC)
task.set_editor_property("destination_path", DEST)
task.set_editor_property("destination_name", "SK_Grandma")
task.set_editor_property("automated", True)
task.set_editor_property("replace_existing", True)
task.set_editor_property("save", True)
task.set_editor_property("options", ui)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

paths = list(task.get_editor_property("imported_object_paths"))
unreal.log(f"GRANDMA_IMPORT imported {len(paths)} objects: {paths}")
mesh = unreal.load_asset(f"{DEST}/SK_Grandma")
if mesh is None:
    raise SystemExit("GRANDMA_IMPORT FAILED: SK_Grandma not created")
unreal.EditorAssetLibrary.save_directory(DEST)
unreal.log("GRANDMA_IMPORT OK")
