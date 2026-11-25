"""The original (CC) grandma as a MetaHuman (2026-11-24, local only: /Game/Project/Agents/GrandmaCCMH is git-ignored).

Mesh to MetaHuman, headless, after Epic's examples/example_conform_from_custom_mesh.py. The target is the original
grandma's face skin only (her hair and clothes are part of the same mesh and would read as skull / neck):
Scripts/classify_grandma_skin_blender.py samples her diffuse texture and writes the skin vertices to
Content/Art/Raw/GrandmaCCMH/skin.json (Blender world, metres); this script finds the same vertices on SK_Grandma.

Stages (env GRANDMA_CCMH_STAGE), each run through run_headless.ps1 "-ExecutePythonScript=<abs path>":
    target    map the skin points onto SK_Grandma (face patch -> head_target.json) and choose the portrait camera
              (camera.json); then Scripts/render_grandma_portrait_blender.py renders portrait.png with that camera
    track     face landmarks on portrait.png (Epic's tracker) -> head_target.json curves, landmarks.png
    conform   new MetaHuman Character MHC_GrandmaCC conformed HEAD_ONLY to the face skin + landmarks
    preview   conformed head -> preview_head.fbx (likeness check)
    look      skin tone / age, blonde hair groom
    rig       cloud auto-rig (joints + blend shapes) and texture sources (needs the owner's MetaHuman sign-in).
              Run it AFTER look: commit_skin_settings discards downloaded textures, and the build refuses without them.
    build     assemble (Optimized, medium) into /Game/Project/Agents/GrandmaCCMH/Build
    import    her headless clothed body (make_grandma_headless_blender.py) + Content/Art/Exports/GrandmaCCMH/parts.json
"""

import json
import os

import unreal

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(PROJECT, "Content", "Art", "Raw", "GrandmaCCMH")
PKG = "/Game/Project/Agents/GrandmaCCMH"
CHAR_NAME = "MHC_GrandmaCC"
CHAR = f"{PKG}/{CHAR_NAME}"
TARGET = "/Game/Project/Agents/Grandma/SK_Grandma"
IMG = 1024
FOV = 30.0
CAM_DIST = 70.0   # cm from the face centre

eal = unreal.EditorAssetLibrary
mhs = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)


def log(*a):
    msg = "GRANDMA_CCMH " + " ".join(str(x) for x in a)
    unreal.log(msg)
    with open(os.path.join(WORK, "log.txt"), "a", encoding="utf-8") as f:
        f.write(msg + "\n")


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


def target_mesh_data():
    mesh = unreal.load_asset(TARGET)
    verts, tris, *_ = mhs.get_mesh_data_for_conforming(mesh)
    return mesh, verts, tris


def select_face(verts, tris):
    """Indices of SK_Grandma vertices that are face skin, largest connected patch only."""
    import numpy as np
    V = np.array([(v.x, v.y, v.z) for v in verts], dtype=np.float64)
    T = np.array(list(tris), dtype=np.int64).reshape(-1, 3)
    S = np.array(json.load(open(os.path.join(WORK, "skin.json")))["skin_world"], dtype=np.float64) * 100.0
    # Blender world -> UE mesh space: an axis permutation / flip (FBX import), found by nearest-neighbour error
    best = None
    for perm in ((0, 1), (1, 0)):
        for sx in (1, -1):
            for sy in (1, -1):
                P = np.stack([sx * S[:, perm[0]], sy * S[:, perm[1]], S[:, 2]], 1)
                sub = P[:: max(1, len(P) // 150)]
                d = np.sqrt(((sub[:, None, :] - V[None, :, :]) ** 2).sum(-1)).min(1)
                err = float(np.median(d))
                if best is None or err < best[0]:
                    best = (err, P, (perm, sx, sy))
    err, P, how = best
    log("portrait: blender->ue mapping", how, "median nn error cm", round(err, 3))
    if err > 0.5:
        raise RuntimeError(f"skin points do not land on SK_Grandma (median {err:.2f} cm)")
    near = np.zeros(len(V), bool)
    for i in range(0, len(V), 4000):
        d = np.sqrt(((V[i:i + 4000, None, :] - P[None, :, :]) ** 2).sum(-1)).min(1)
        near[i:i + 4000] = d < 0.6
    keep_t = near[T].all(1)
    Tk = T[keep_t]
    # largest connected component over shared vertices
    parent = np.arange(len(V))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b, c in Tk:
        for x, y in ((a, b), (b, c)):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry
    roots = np.array([find(t[0]) for t in Tk])
    vals, counts = np.unique(roots, return_counts=True)
    main = vals[counts.argmax()]
    Tf = Tk[roots == main]
    used = np.unique(Tf)
    log("portrait: face patch", len(used), "verts,", len(Tf), "tris (of", int(near.sum()), "skin-near verts,", len(vals), "patches)")
    return V, used, Tf


def portrait():
    os.makedirs(WORK, exist_ok=True)
    mesh, verts, tris = target_mesh_data()
    V, used, Tf = select_face(verts, tris)
    import numpy as np
    face = V[used]
    centre = face.mean(0)
    # outward direction: from the head's vertical axis through the face centre (horizontal)
    allc = V[V[:, 2] > face[:, 2].min()].mean(0)
    out = centre - allc
    out[2] = 0.0
    out /= np.linalg.norm(out)
    cam = centre + out * CAM_DIST
    log("target: face centre", centre.round(1).tolist(), "outward", out.round(3).tolist(), "camera", cam.round(1).tolist())
    cam_rot = unreal.MathLibrary.find_look_at_rotation(unreal.Vector(*cam.tolist()), unreal.Vector(*centre.tolist()))
    # the portrait itself is rendered by render_grandma_portrait_blender.py with this camera (the headless scene
    # capture renders her material black)
    json.dump({"location": cam.tolist(), "target": centre.tolist(), "rotation": [cam_rot.pitch, cam_rot.yaw, cam_rot.roll],
               "fov": FOV, "size": [IMG, IMG]}, open(os.path.join(WORK, "camera.json"), "w"))
    json.dump({"vertices": V[used].tolist(), "triangles": np.searchsorted(used, Tf).tolist()},
              open(os.path.join(WORK, "head_target.json"), "w"))


def track():
    png = os.path.join(WORK, "portrait.png")
    size, pixels = unreal.PromotedFrameUtils.get_promoted_frame_as_pixel_array_from_disk(png)
    res = mhs.track_face_landmarks_from_image(pixels, size.x, size.y)
    if isinstance(res, tuple) and len(res) == 1:
        res = res[0]
    items = list(res.items()) if res else []
    if items:
        log("track: TrackingPoints fields", {k: type(x).__name__ for k, x in items[0][1].to_dict().items()})
    curves = {}
    for k, v in items:
        pts = next(x for x in v.to_dict().values() if isinstance(x, (list, tuple, unreal.Array)))
        curves[k] = [(float(p.x), float(p.y)) for p in pts]
    log("track: landmark curves", len(curves), {k: len(v) for k, v in sorted(curves.items())})
    if not curves:
        raise RuntimeError("no face landmarks found on the portrait")
    d = json.load(open(os.path.join(WORK, "head_target.json")))
    d["curves"] = curves
    json.dump(d, open(os.path.join(WORK, "head_target.json"), "w"))
    try:
        from PIL import Image, ImageDraw
        im = Image.open(png).convert("RGB")
        dr = ImageDraw.Draw(im)
        for pts in curves.values():
            dr.line(pts, fill=(0, 255, 0), width=2)
        im.save(os.path.join(WORK, "landmarks.png"))
    except Exception as e:  # debug image only
        log("portrait: landmark image skipped", e)


def conform():
    d = json.load(open(os.path.join(WORK, "head_target.json")))
    c = json.load(open(os.path.join(WORK, "camera.json")))
    mesh = unreal.load_asset(TARGET)
    if eal.does_asset_exist(CHAR):
        eal.delete_asset(CHAR)
    ch = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name=CHAR_NAME, package_path=PKG, asset_class=unreal.MetaHumanCharacter,
        factory=unreal.new_object(type=unreal.MetaHumanCharacterFactoryNew))
    with Editing(ch):
        p = unreal.ConformTargetParams()
        p.conform_target_mesh.target_parts_type = unreal.TargetPartsType.HEAD_ONLY
        p.conform_target_mesh.head_vertices = [unreal.Vector3f(*v) for v in d["vertices"]]
        p.conform_target_mesh.head_vertex_indices = [i for t in d["triangles"] for i in t]
        p.auto_solve = True
        p.body_conform_solve_settings.pipeline_name = "head_only"   # what the editor's Mesh Import tool sets for HeadOnly
        tracking = {}
        field = next(k for k, x in unreal.TrackingPoints().to_dict().items() if isinstance(x, (list, tuple, unreal.Array)))
        for k, pts in d["curves"].items():
            tp = unreal.TrackingPoints()
            tp.set_editor_property(field, [unreal.Vector2D(x, y) for x, y in pts])
            tracking[k] = tp
        p.curve_tracking_points = tracking
        v = unreal.MinimalViewInfo()
        v.location = unreal.Vector(*c["location"])
        v.rotation = unreal.Rotator(pitch=c["rotation"][0], yaw=c["rotation"][1], roll=c["rotation"][2])
        v.fov = c["fov"]
        v.aspect_ratio = c["size"][0] / c["size"][1]
        v.projection_mode = unreal.CameraProjectionMode.PERSPECTIVE
        p.camera_view_info = v
        p.image_size = unreal.IntPoint(*c["size"])
        key = unreal.MetaHumanCharacterTargetMeshKey()
        key.head_mesh = mesh
        ok = mhs.conform_to_target_meshes(ch, key, p)
        log("conform: solve", ok, "verts", len(d["vertices"]), "curves", len(d["curves"]))
        if not ok:
            raise RuntimeError("conform_to_target_meshes failed")
        try:
            mhs.commit_posed_state_as_a_pose(ch, key)
        except Exception as e:
            log("conform: commit A pose skipped:", str(e).splitlines()[0][:160])
        log("conform: can build", mhs.can_build_meta_human(ch, True))
    eal.save_loaded_asset(ch)


def preview():
    """Conformed head -> skeletal mesh asset -> Content/Art/Raw/GrandmaCCMH/preview_head.fbx (likeness check in Blender)."""
    ch = unreal.load_asset(CHAR)
    with Editing(ch):
        g = unreal.MetaHumanGeometryExportParams()
        g.head_skeletal_mesh = True
        g.overwrite_existing_assets = True
        g.project_path = f"{PKG}/Preview"
        unreal.MetaHumanCharacterExportBlueprintLibrary.export_geometry(ch, g)
    assets = [a for a in eal.list_assets(f"{PKG}/Preview", recursive=True, include_folder=False)
              if isinstance(unreal.load_asset(a), unreal.SkeletalMesh)]
    log("preview: exported", assets)
    head = unreal.load_asset(next(a for a in assets if a.split(".")[0].endswith("_Head")))
    t = unreal.AssetExportTask()
    t.object = head
    t.filename = os.path.join(WORK, "preview_head.fbx")
    t.automated, t.prompt, t.replace_identical = True, False, True
    t.exporter = unreal.SkeletalMeshExporterFBX()
    ok = unreal.Exporter.run_asset_export_task(t)
    log("preview: fbx", ok, t.filename)


def rig():
    ch = unreal.load_asset(CHAR)
    with Editing(ch):
        r = unreal.MetaHumanCharacterAutoRiggingRequestParams()
        r.blocking, r.report_progress = True, False
        r.rig_type = unreal.MetaHumanRigType.JOINTS_AND_BLEND_SHAPES
        mhs.request_auto_rigging(ch, r)
        t = unreal.MetaHumanCharacterTextureRequestParams()
        t.blocking, t.report_progress = True, False
        mhs.request_texture_sources(ch, t)
        log("rig: can build", mhs.can_build_meta_human(ch, True))
    eal.save_loaded_asset(ch)


def look():
    ch = unreal.load_asset(CHAR)
    # her hair: shoulder length, straight, swept back, no fringe; blonde colour set after assembly below
    hair = os.environ.get("GRANDMA_CCMH_HAIR", "/MetaHumanCharacter/Optional/Grooms/Bindings/Hair/WI_Hair_L_Straight.WI_Hair_L_Straight")
    wi = unreal.load_asset(hair)
    if wi is None:
        raise RuntimeError(f"hair wardrobe item missing: {hair}")
    col = ch.internal_collection
    key = col.try_add_item_from_wardrobe_item("Hair", wi)
    col.default_instance.try_add_slot_selection(unreal.MetaHumanPipelineSlotSelection(slot_name="Hair", selected_item=key))
    with Editing(ch):
        s = unreal.MetaHumanCharacterSkinProperties()
        s.u, s.v = float(os.environ.get("GRANDMA_CCMH_SKIN_U", "0.30")), float(os.environ.get("GRANDMA_CCMH_SKIN_V", "0.55"))
        s.face_texture_index = int(os.environ.get("GRANDMA_CCMH_FACE_TEX", "-1")) if os.environ.get("GRANDMA_CCMH_FACE_TEX") else s.face_texture_index
        settings = unreal.MetaHumanCharacterSkinSettings()
        settings.skin = s
        mhs.commit_skin_settings(ch, settings)
        mhs.assemble_for_preview(character=ch)
        params = col.default_instance.get_instance_parameters(item_path=unreal.MetaHumanPaletteItemPath(item_key=key))
        for prm in params:
            if prm.name == "Melanin":
                prm.set_float(value=0.25)   # blonde
            elif prm.name == "Redness":
                prm.set_float(value=0.25)
        log("look: hair", hair, "params", [str(p.name) for p in params])
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
            log("build: engine errors during copy:", str(e).splitlines()[0][:160])
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    built = eal.list_assets(f"{PKG}/Build", recursive=True, include_folder=False)
    log("build:", len(built), "assets;", [a for a in built if "/SKM_" in a or "/BP_" in a or "Groom" in a or "/GR_" in a][:20])


def import_body():
    """Her own clothed body without head/hair (make_grandma_headless_blender.py) + parts.json for the game
    (AStreetballCharacter MetaHuman slot 0): face mesh + anim class and grooms read from the built Blueprint."""
    exports = os.path.join(PROJECT, "Content", "Art", "Exports", "GrandmaCCMH")
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_as_skeletal", True)
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", False)
    ui.set_editor_property("create_physics_asset", False)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    sk = ui.get_editor_property("skeletal_mesh_import_data")
    sk.set_editor_property("import_morph_targets", True)
    sk.set_editor_property("convert_scene", True)
    sk.set_editor_property("import_uniform_scale", 1.0)
    sk.set_editor_property("use_t0_as_ref_pose", False)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", os.path.join(exports, "SK_GrandmaCC_Body.fbx"))
    task.set_editor_property("destination_path", PKG)
    task.set_editor_property("destination_name", "SK_GrandmaCC_Body")
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    task.set_editor_property("options", ui)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    body = unreal.load_asset(f"{PKG}/SK_GrandmaCC_Body")
    if body is None:
        raise RuntimeError("SK_GrandmaCC_Body not imported")
    src = list(unreal.load_asset(TARGET).get_editor_property("materials"))
    dst = list(body.get_editor_property("materials"))
    for i, m in enumerate(dst):
        m.material_interface = src[min(i, len(src) - 1)].material_interface
        dst[i] = m
    body.set_editor_property("materials", dst)
    eal.save_loaded_asset(body)
    log("import: body", body.get_path_name(), "materials", [m.material_interface.get_name() if m.material_interface else None for m in dst])

    bp = unreal.load_asset(f"{PKG}/Build/{CHAR_NAME}/BP_{CHAR_NAME}")
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    parts = {"body": body.get_path_name(), "face": None, "face_anim_class": None, "grooms": {}}
    for h in sub.k2_gather_subobject_data_for_blueprint(context=bp):
        o = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(h))
        if o is None:
            continue
        name = o.get_name().replace("_GEN_VARIABLE", "")
        if isinstance(o, unreal.GroomComponent) and o.get_editor_property("groom_asset") and o.get_editor_property("binding_asset"):
            mats = [m.get_path_name() if m else "" for m in o.get_editor_property("override_materials")]
            parts["grooms"][name] = {"groom": o.get_editor_property("groom_asset").get_path_name(),
                                     "binding": o.get_editor_property("binding_asset").get_path_name(), "materials": mats}
        elif isinstance(o, unreal.SkeletalMeshComponent) and name == "Face":
            parts["face"] = o.get_editor_property("skeletal_mesh_asset").get_path_name()
            cls = o.get_editor_property("anim_class")
            parts["face_anim_class"] = cls.get_path_name() if cls else None
    with open(os.path.join(exports, "parts.json"), "w", encoding="utf-8") as f:
        json.dump(parts, f, indent=2)
    log("import: parts", parts)


def hair_color():
    """Blonde on the built hair material instances (the character's groom instance parameters came back empty
    headless). GRANDMA_CCMH_HAIR_SET='Melanin=0.15,Redness=0.3' sets scalars; without it the scalars are listed."""
    mel = unreal.MaterialEditingLibrary
    mis = [a for a in eal.list_assets(f"{PKG}/Build/{CHAR_NAME}/Grooms", recursive=True, include_folder=False) if "/MI_" in a]
    want = dict(kv.split("=") for kv in os.environ.get("GRANDMA_CCMH_HAIR_SET", "").split(",") if "=" in kv)
    for path in mis:
        mi = unreal.load_asset(path)
        names = [str(n) for n in mel.get_scalar_parameter_names(mi)]
        vals = {n: round(mel.get_material_instance_scalar_parameter_value(mi, n), 3) for n in names}
        log("hair:", path.split("/")[-1], vals)
        for k, v in want.items():
            if k in names:
                mel.set_material_instance_scalar_parameter_value(mi, k, float(v))
        if want:
            mel.update_material_instance(mi)
            eal.save_loaded_asset(mi)


STAGES = {"hair": hair_color, "import": import_body, "target": portrait, "track": track, "conform": conform, "preview": preview, "rig": rig, "look": look, "build": build}
stage = os.environ.get("GRANDMA_CCMH_STAGE", "portrait")
try:
    STAGES[stage]()
    log(stage, "DONE")
except Exception as e:
    log(stage, "FAILED", repr(e)[:400])
    raise
