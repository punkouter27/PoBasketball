"""MetaHuman Grandma (2026-11-24, local only: /Game/Project/Agents/GrandmaMH is git-ignored, public repo).

Stages, run headless through run_headless.ps1 "-ExecutePythonScript=<abs path>" with env GRANDMA_MH_STAGE:
    setup     duplicate the Grace preset (MetaHuman Creator optional content) to MHC_Grandma, request the cloud face
              auto-rig and texture sources (needs the owner's MetaHuman sign-in in the editor; ~6 min)
    customize body lengths x LENGTH_SCALE towards Manny (the physics humanoid was built from Manny's joints; the exact
              fit is done afterwards by Scripts/retarget_grandma_blender.py). Grace's own grey bob and the default
              garment are kept.
    build     assemble (Optimized, medium) into /Game/Project/Agents/GrandmaMH/Build
"""

import os

import unreal

PKG = "/Game/Project/Agents/GrandmaMH"
CHAR = f"{PKG}/MHC_Grandma"
PRESET = "/MetaHumanCharacter/Optional/Presets/Grace"
# Manny is ~180 cm, Grace 156.3 cm. Lengths scale; girths and the face do not.
LENGTH_SCALE = 180.0 / 156.3
LENGTHS = ("Height", "Inseam", "Rise", "Upper Arm Length", "Lower Arm Length", "Shoulder Height", "Neck to Waist")

eal = unreal.EditorAssetLibrary
mhs = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)


def log(*a):
    unreal.log("GRANDMA_MH " + " ".join(str(x) for x in a))


class Editing:
    def __init__(self, ch):
        self.ch = ch

    def __enter__(self):
        if not mhs.try_add_object_to_edit(self.ch):
            raise RuntimeError("cannot open the MetaHuman Character for edit")
        return self.ch

    def __exit__(self, *exc):
        if mhs.is_object_added_for_editing(self.ch):
            mhs.remove_object_to_edit(self.ch)


def setup():
    if eal.does_asset_exist(CHAR):
        eal.delete_asset(CHAR)
    ch = eal.duplicate_asset(PRESET, CHAR)
    eal.save_loaded_asset(ch)
    with Editing(ch):
        r = unreal.MetaHumanCharacterAutoRiggingRequestParams()
        r.blocking, r.report_progress = True, False
        r.rig_type = unreal.MetaHumanRigType.JOINTS_AND_BLEND_SHAPES
        mhs.request_auto_rigging(ch, r)
        t = unreal.MetaHumanCharacterTextureRequestParams()
        t.blocking, t.report_progress = True, False
        mhs.request_texture_sources(ch, t)
        log("setup: can build", mhs.can_build_meta_human(ch, True))
    eal.save_loaded_asset(ch)


def customize():
    ch = unreal.load_asset(CHAR)
    with Editing(ch):
        # Unreal Python hands out copies of struct elements: edit each copy and send a new list back
        cons = []
        before = {}
        for c in mhs.get_body_constraints(ch, False):
            name = str(c.name)
            before[name] = c.target_measurement
            if name in LENGTHS:
                c.is_active = True
                c.target_measurement = c.target_measurement * LENGTH_SCALE
                log("customize: range", name, round(c.min_measurement, 1), round(c.max_measurement, 1))
            cons.append(c)
        mhs.set_body_constraints(ch, cons)
        mhs.commit_body_state(ch)
        after = {str(c.name): round(c.target_measurement, 1) for c in mhs.get_body_constraints(ch)}
        log("customize: lengths", {k: (round(before[k], 1), after[k]) for k in LENGTHS})
        log("customize: can build", mhs.can_build_meta_human(ch, True))
    eal.save_loaded_asset(ch)


def build():
    ch = unreal.load_asset(CHAR)
    with Editing(ch):
        p = unreal.MetaHumanCharacterEditorBuildParameters()
        p.pipeline_type = unreal.MetaHumanDefaultPipelineType.OPTIMIZED
        p.pipeline_quality = unreal.MetaHumanQualityLevel.MEDIUM
        p.absolute_build_path = f"{PKG}/Build"
        p.common_folder_path = f"{PKG}/Build/Common"
        p.enable_wardrobe_item_validation = False
        try:
            mhs.build_meta_human(character=ch, params=p)
        except RuntimeError as e:
            # the build copies Epic's face control rigs into Common and logs "Cannot break link" errors that Python
            # raises as an exception; the assembly itself continues. Judge by what exists afterwards.
            log("build: engine errors during copy:", str(e).splitlines()[0][:160])
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    built = eal.list_assets(f"{PKG}/Build", recursive=True, include_folder=False)
    log("build:", len(built), "assets;", [a for a in built if "/SKM_" in a or "/BP_" in a or "/GR_" in a or "Groom" in a][:20])


{"setup": setup, "customize": customize, "build": build}[os.environ.get("GRANDMA_MH_STAGE", "build")]()
