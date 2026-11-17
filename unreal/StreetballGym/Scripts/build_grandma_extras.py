"""Items 4, 13-15: grandma cosmetic upgrades, headlessly. Visual only: the MuJoCo body, bone mapping and policies are
untouched (the cloth mesh keeps SK_Grandma's skeleton, bind pose and vertices; split_grandma_cloth_blender.py checks it).

    run_headless.ps1 -EditorArgs @("-run=pythonscript", "-script=<this file>")

  1. M_GrandmaSubstrate: one Substrate slab driven by the CC diffuse/normal maps; skin-coloured texels get subsurface
     (SSS MFP), the white knit gets fuzz (cloth sheen). Assigned to SK_Grandma and SK_Grandma_Cloth.
  2. SK_Grandma_Cloth (Content/Art/Exports/Grandma/SK_Grandma_Cloth.fbx): same skin with the cardigan hem as its own
     section, imported on SK_Grandma_Skeleton, then turned into Chaos Cloth (Max Distance painted from vertex colour R,
     gravity override because the project's world gravity is 0).
  3. GR_Grandma_Flyaways (Groom/Groom_Grandma.abc: flyaway group 0 + eyebrow group 1) with hair physics on group 0.
     AStreetballCharacter::AttachExtras rides it on the head bone (no binding asset needed).

MetaHuman (item 13): there is no headless way to author one. Make it in MetaHuman Creator, then start the game with
-StreetballCharacterMesh=/Game/MetaHumans/<Name>/Body/<BodyMesh>.<BodyMesh>. A MetaHuman body is on the UE5 mannequin
skeleton, so UMuJoCoBoneMapper drives it by bone name; run Scripts/compare_bones.py against it first (joint offsets).
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import unreal  # noqa: E402
import sbmat  # noqa: E402
from sbmat import Graph  # noqa: E402

PROJECT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
EXPORTS = _os.path.join(PROJECT, "Content", "Art", "Exports", "Grandma")
DEST = "/Game/Art/Characters/Grandma"
EAL = unreal.EditorAssetLibrary
L = unreal.StreetballEditorLibrary

SKIN_HLSL = r"""
float mx = max(C.r, max(C.g, C.b)), mn = min(C.r, min(C.g, C.b));
float sat = (mx - mn) / max(mx, 1e-3);
float skin = step(C.b, C.g) * step(C.g, C.r) * smoothstep(0.12, 0.22, sat) * (1.0 - smoothstep(0.55, 0.7, sat)) * step(0.22, mx);
float knit = (1.0 - smoothstep(0.08, 0.16, sat)) * smoothstep(0.45, 0.6, mx);
return float4(skin, knit, 0, 0);
"""


def grandma_material():
    diff = unreal.load_asset(f"{DEST}/Material_Diffuse")
    norm = unreal.load_asset(f"{DEST}/Material_Normal")
    m = sbmat.new_material(f"{DEST}/M_GrandmaSubstrate")
    m.set_editor_property("used_with_skeletal_mesh", True)
    m.set_editor_property("used_with_morph_targets", True)
    m.set_editor_property("used_with_clothing", True)
    g = Graph(m)
    if diff is None or norm is None:
        raise RuntimeError("grandma textures missing (run import_grandma.py)")
    td = g.e(unreal.MaterialExpressionTextureSampleParameter2D, parameter_name="Diffuse")
    td.set_editor_property("texture", diff)
    tn = g.e(unreal.MaterialExpressionTextureSampleParameter2D, parameter_name="Normal")
    tn.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    tn.set_editor_property("texture", norm)
    if td.get_editor_property("texture") is None or tn.get_editor_property("texture") is None:
        raise RuntimeError("texture assignment did not stick")
    masks = g.custom(SKIN_HLSL, [("C", (td, "RGB"))], unreal.CustomMaterialOutputType.CMOT_FLOAT4, "SkinKnitMasks")
    # ComponentMask defaults to R+G on: set all four channels explicitly
    skin = g.e(unreal.MaterialExpressionComponentMask, r=True, g=False, b=False, a=False)
    g.link(masks, "", skin, "")
    knit = g.e(unreal.MaterialExpressionComponentMask, r=False, g=True, b=False, a=False)
    g.link(masks, "", knit, "")
    mfp = g.e(unreal.MaterialExpressionMultiply)
    g.link(g.const3(1.0, 0.37, 0.20), "", mfp, "A")
    g.link(skin, "", mfp, "B")
    fuzz = g.e(unreal.MaterialExpressionMultiply)
    g.link(knit, "", fuzz, "A")
    g.link(g.scalar("KnitFuzz", 0.45), "", fuzz, "B")
    rough = g.e(unreal.MaterialExpressionLinearInterpolate)
    g.link(g.const(0.62), "", rough, "A")
    g.link(g.const(0.48), "", rough, "B")
    g.link(skin, "", rough, "Alpha")
    s = g.slab(albedo=(td, "RGB"), normal=(tn, "RGB"), roughness=(rough, ""), sss_mfp=(mfp, ""), sss_mfp_scale=(g.scalar("SkinMFPScale", 0.12), ""),
               fuzz_amount=(fuzz, ""), fuzz_color=(td, "RGB"), fuzz_roughness=(g.const(0.5), ""))
    g.front(s)
    return g.finish()


def import_cloth_mesh():
    src = _os.path.join(EXPORTS, "SK_Grandma_Cloth.fbx")
    if not _os.path.exists(src):
        unreal.log_warning("GRANDMA cloth fbx missing; run split_grandma_cloth_blender.py")
        return None
    skel = unreal.load_asset(f"{DEST}/SK_Grandma_Skeleton")
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_as_skeletal", True)
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", False)
    ui.set_editor_property("create_physics_asset", False)
    ui.set_editor_property("skeleton", skel)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    sk = ui.get_editor_property("skeletal_mesh_import_data")
    sk.set_editor_property("import_morph_targets", True)
    sk.set_editor_property("convert_scene", True)
    sk.set_editor_property("import_uniform_scale", 1.0)
    sk.set_editor_property("use_t0_as_ref_pose", False)
    sk.set_editor_property("vertex_color_import_option", unreal.VertexColorImportOption.REPLACE)
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", src)
    t.set_editor_property("destination_path", DEST)
    t.set_editor_property("destination_name", "SK_Grandma_Cloth")
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", True)
    t.set_editor_property("options", ui)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    return unreal.load_asset(f"{DEST}/SK_Grandma_Cloth")


def assign_material(mesh, mat):
    """Set every slot and read it back (a mesh rebuild, e.g. adding cloth, can reset slots to WorldGridMaterial)."""
    # set_editor_property("materials") is silently ignored on skeletal meshes in 5.8: go through reflection text
    import re
    txt = L.get_property_text(mesh, "Materials")
    txt = re.sub(r"MaterialInterface=[^,)]*", f"MaterialInterface=\"{mat.get_path_name()}\"", txt)
    if not L.set_property_text(mesh, "Materials", txt):
        raise RuntimeError(f"{mesh.get_name()}: Materials text rejected: {txt[:300]}")
    mats = mesh.get_editor_property("materials")
    EAL.save_loaded_asset(mesh)
    back = [s.get_editor_property("material_interface") for s in mesh.get_editor_property("materials")]
    if any(b is None or b.get_name() != mat.get_name() for b in back):
        raise RuntimeError(f"{mesh.get_name()}: material did not stick: {[b.get_name() if b else None for b in back]}")
    return len(mats)


def hair_material():
    m = sbmat.new_material(f"{DEST}/Groom/M_GrandmaHair", shading=unreal.MaterialShadingModel.MSM_HAIR)
    m.set_editor_property("used_with_hair_strands", True)
    g = Graph(m)
    g.to(g.vector("HairColor", 0.62, 0.52, 0.36), "", unreal.MaterialProperty.MP_BASE_COLOR)
    g.to(g.const(0.35), "", unreal.MaterialProperty.MP_ROUGHNESS)
    g.to(g.const(0.5), "", unreal.MaterialProperty.MP_SPECULAR)
    return g.finish()


def import_groom():
    src = _os.path.join(EXPORTS, "Groom", "Groom_Grandma.abc")
    if not _os.path.exists(src):
        unreal.log_warning("GRANDMA groom abc missing; run make_grandma_groom_blender.py")
        return None
    opts = unreal.GroomImportOptions()
    conv = opts.get_editor_property("conversion_settings")
    conv.set_editor_property("rotation", unreal.Vector(90.0, 0.0, 0.0))
    conv.set_editor_property("scale", unreal.Vector(100.0, -100.0, 100.0))
    opts.set_editor_property("conversion_settings", conv)
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", src)
    t.set_editor_property("destination_path", f"{DEST}/Groom")
    t.set_editor_property("destination_name", "GR_Grandma_Flyaways")
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", True)
    t.set_editor_property("options", opts)
    # needs the AlembicHairImporter plugin (the groom translator); without it .abc falls through to the geometry importer
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    groom = unreal.load_asset(f"{DEST}/Groom/GR_Grandma_Flyaways")
    if groom is None:
        return None
    hm = hair_material()
    try:
        slot = unreal.HairGroupsMaterial()
        slot.set_editor_property("material", hm)
        slot.set_editor_property("slot_name", "GrandmaHair")
        mats = [slot]
        groom.set_editor_property("hair_groups_materials", mats)
    except Exception as e:
        unreal.log_warning(f"GRANDMA groom material: {e}")
    try:
        # MaterialSlotName is a plain UPROPERTY() (not editable from Python): set it through reflection
        import re
        txt = L.get_property_text(groom, "HairGroupsRendering")
        txt = re.sub(r"MaterialSlotName=[^,)]*", 'MaterialSlotName="GrandmaHair"', txt)
        if "MaterialSlotName" not in txt:
            txt = txt.replace("((", '((MaterialSlotName="GrandmaHair",').replace("),(", '),(MaterialSlotName="GrandmaHair",')
        unreal.log(f"GRANDMA groom slot names set: {L.set_property_text(groom, 'HairGroupsRendering', txt)}")
    except Exception as e:
        unreal.log_warning(f"GRANDMA groom slot: {e}")
    try:
        phys = groom.get_editor_property("hair_groups_physics")
        if len(phys) > 0:
            solver = phys[0].get_editor_property("solver_settings")
            solver.set_editor_property("enable_simulation", True)
            phys[0].set_editor_property("solver_settings", solver)
            groom.set_editor_property("hair_groups_physics", phys)
        unreal.log(f"GRANDMA groom groups: {len(phys)}, materials {len(mats)}")
    except Exception as e:
        unreal.log_warning(f"GRANDMA groom settings: {e}")
    EAL.save_loaded_asset(groom)
    return groom


def main():
    if "assign" in _sys.argv[1:]:
        mat = unreal.load_asset(f"{DEST}/M_GrandmaSubstrate")
        for name in ("SK_Grandma", "SK_Grandma_Cloth"):
            mesh = unreal.load_asset(f"{DEST}/{name}")
            if mesh:
                unreal.log(f"GRANDMA {name} material slots set: {assign_material(mesh, mat)}")
        unreal.log("GRANDMA_EXTRAS OK assign-only")
        return
    if "groom" in _sys.argv[1:]:
        groom = import_groom()
        unreal.log(f"GRANDMA_EXTRAS OK groom-only groom={'yes' if groom else 'no'}")
        return
    mat = None
    try:
        mat = grandma_material()
    except Exception as e:
        unreal.log_error(f"GRANDMA material FAILED: {e}")
    base = unreal.load_asset(f"{DEST}/SK_Grandma")
    if mat and base:
        unreal.log(f"GRANDMA SK_Grandma material slots set: {assign_material(base, mat)}")
    cloth_mesh = import_cloth_mesh()
    cloth = None
    if cloth_mesh:
        mats = cloth_mesh.get_editor_property("materials")
        section = next((i for i, sm in enumerate(mats) if str(sm.get_editor_property("material_slot_name")).startswith("Cardigan_Hem")), 1)
        cloth = L.create_cloth_from_section(cloth_mesh, 0, section, 6.0, 0.0, "Cardigan_Hem_Cloth")
        EAL.save_loaded_asset(cloth_mesh)
        unreal.log(f"GRANDMA cloth on section {section}: {'ok' if cloth else 'FAILED'}")
        if mat:   # after the cloth step: binding cloth rebuilds the mesh
            unreal.log(f"GRANDMA SK_Grandma_Cloth material slots set: {assign_material(cloth_mesh, mat)}")
    groom = None
    try:
        groom = import_groom()
    except Exception as e:
        unreal.log_error(f"GRANDMA groom FAILED: {e}")
    unreal.log(f"GRANDMA_EXTRAS OK material={'yes' if mat else 'no'} cloth={'yes' if cloth else 'no'} groom={'yes' if groom else 'no'}")


main()
