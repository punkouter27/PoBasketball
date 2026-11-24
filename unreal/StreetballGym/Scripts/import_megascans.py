"""Import the Fab Megascans listed in Content/Art/megascans.json (local only: the files are git-ignored, see .gitignore).

For each asset whose 2K texture-set zip is in the downloads folder, extract only the listed maps to
Content/Art/Raw/Megascans/<id>/ and import them to /Game/Project/Environments/Megascans/<id>/T_<id>_<Map>.
Map kinds: color (sRGB), normal_gl (OpenGL normal from the generic texture set: green flipped for Unreal), mask (linear
grayscale). Assets whose zip is missing are skipped and reported.

    pwsh Scripts/run_headless.ps1 -TimeoutSec 900 "-ExecutePythonScript=<abs path>/Scripts/import_megascans.py"
    (downloads folder: env STREETBALL_DOWNLOADS, default ~/Downloads)
"""

import json
import os
import pathlib
import re
import zipfile

import unreal

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "Content" / "Art" / "megascans.json"
RAW = ROOT / "Content" / "Art" / "Raw" / "Megascans"
PKG = "/Game/Project/Environments/Megascans"
DOWNLOADS = pathlib.Path(os.environ.get("STREETBALL_DOWNLOADS", pathlib.Path.home() / "Downloads"))


def extract(zip_path: pathlib.Path, asset_id: str, maps: dict) -> dict:
    """map name -> extracted file. Only plain file names matching *_<Map>.jpg|png are taken (no paths from the zip)."""
    out_dir = RAW / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    found = {}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if "/" in name or "\\" in name or name.startswith("."):
                continue  # only top-level files; never write outside out_dir
            for m in maps:
                if re.search(rf"_{m}\.(jpg|png)$", name, re.IGNORECASE):
                    dst = out_dir / name
                    dst.write_bytes(z.read(info))
                    found[m] = dst
    return found


def import_texture(src: pathlib.Path, dest_pkg: str, dest_name: str, kind: str):
    task = unreal.AssetImportTask()
    task.filename = str(src)
    task.destination_path = dest_pkg
    task.destination_name = dest_name
    task.automated = True
    task.replace_existing = True
    task.save = False
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex = unreal.EditorAssetLibrary.load_asset(f"{dest_pkg}/{dest_name}")
    if tex is None:
        raise RuntimeError(f"import failed: {src}")
    if kind == "normal_gl":
        tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
        tex.set_editor_property("srgb", False)
        tex.set_editor_property("flip_green_channel", True)
    elif kind == "mask":
        tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_GRAYSCALE)
        tex.set_editor_property("srgb", False)
    else:
        tex.set_editor_property("srgb", True)
    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    return tex


def main():
    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    done, missing = [], []
    for a in cfg["assets"]:
        zp = DOWNLOADS / a["zip"]
        if not zp.exists():
            missing.append(a["zip"])
            continue
        files = extract(zp, a["id"], a["maps"])
        pkg = f"{PKG}/{a['id']}"
        for m, kind in a["maps"].items():
            if m not in files:
                raise RuntimeError(f"{a['zip']}: no *_{m}.jpg/png inside")
            import_texture(files[m], pkg, f"T_{a['id']}_{m}", kind)
        done.append(a["name"])
    unreal.log(f"import_megascans: imported {done}; zip not found in {DOWNLOADS}: {missing}")


main()
