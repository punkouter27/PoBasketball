"""Bundle the web replay viewer for static hosting:  python web/build.py  ->  web/dist/

The viewer plays the golden replays (shared/golden/replay_*.json, written by sim/tools/replay_recorder.py) in a
browser. No physics runs in the page: this script loads sim/assets/scene.xml in CPU MuJoCo, runs forward
kinematics on every recorded qpos, and writes
  dist/data/model.json      every visible geom (body, type, size, local pose, colour)
  dist/data/replays.json    the list of replays (name, level, mode, frame count, frame time)
  dist/data/<name>.json     per frame: position + quaternion of every body that carries a geom
Needs only `mujoco` and `numpy` (CI installs mujoco==4.0.0, the version in sim/uv.lock).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import mujoco
import numpy as np

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
DIST = WEB / "dist"
ASSETS = ROOT / "sim" / "assets"
GOLDEN = ROOT / "shared" / "golden"

TYPES = {
    mujoco.mjtGeom.mjGEOM_PLANE: "plane",
    mujoco.mjtGeom.mjGEOM_SPHERE: "sphere",
    mujoco.mjtGeom.mjGEOM_CAPSULE: "capsule",
    mujoco.mjtGeom.mjGEOM_ELLIPSOID: "ellipsoid",
    mujoco.mjtGeom.mjGEOM_CYLINDER: "cylinder",
    mujoco.mjtGeom.mjGEOM_BOX: "box",
}


def r(a, n=4):
    return [round(float(x), n) for x in np.ravel(a)]


def build_version() -> str:
    """The one version stamp: UTC yyMMdd of the commit being built (same rule as the Unreal build).

    Injected into index.html and diag.html (meta po-version + the footer). Falls back to today (UTC) outside git."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=format-local:%y%m%d"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "TZ": "UTC"},
        ).stdout.strip()
        if len(out) == 6 and out.isdigit():
            return out
    except (OSError, subprocess.CalledProcessError):
        pass
    return time.strftime("%y%m%d", time.gmtime())


def check_diag_config() -> None:
    """Every local /diag check must point at a file in dist; every CDN check must match the page's import map."""
    cfg = json.loads((WEB / "diag_checks.json").read_text(encoding="utf-8"))
    page = (WEB / "index.html").read_text(encoding="utf-8")
    kinds = {"json", "text", "replays", "webgl2"}
    for c in cfg["checks"]:
        if c["kind"] not in kinds or c["group"] not in {"api", "data", "service"}:
            raise SystemExit(f"diag_checks.json: bad kind/group in {c}")
        url = c.get("url")
        if not url:
            continue
        if url.startswith("https://"):
            base = url.split("/build/")[0].split("/examples/")[0]
            if base not in page:
                raise SystemExit(f"diag_checks.json: {url} is not what index.html imports")
        elif not (DIST / url).is_file():
            raise SystemExit(f"diag_checks.json: {url} is not in {DIST}")


def main() -> None:
    models: dict[str, mujoco.MjModel] = {}

    def model(xml: str) -> mujoco.MjModel:
        if xml not in models:
            models[xml] = mujoco.MjModel.from_xml_path(str(ASSETS / xml))
        return models[xml]

    shutil.rmtree(DIST, ignore_errors=True)
    (DIST / "data").mkdir(parents=True)

    replays = []
    for path in sorted(GOLDEN.glob("replay_*.json")):
        rep = json.loads(path.read_text(encoding="utf-8"))
        xml = rep.get("xml", "scene.xml")
        m = model(xml)
        qpos = np.asarray(rep["qpos"], dtype=np.float64)
        if qpos.ndim != 2 or qpos.shape[1] != m.nq:
            # recorded against an older body: skip it (re-record with sim/tools/replay_recorder.py)
            print(f"::warning::{path.name} skipped: qpos is {qpos.shape}, current {xml} has nq={m.nq}")
            continue
        d = mujoco.MjData(m)
        bodies = sorted({int(b) for b in m.geom_bodyid})
        frames = []
        for q in qpos:
            d.qpos[:] = q
            mujoco.mj_kinematics(m, d)
            if not np.isfinite(d.xpos).all():
                raise SystemExit(f"{path.name}: non-finite body positions")
            frames.append(r(np.hstack([d.xpos[bodies], d.xquat[bodies]])))
        name = path.stem.removeprefix("replay_")
        (DIST / "data" / f"{name}.json").write_text(
            json.dumps({"bodies": bodies, "frames": frames}, separators=(",", ":")), encoding="utf-8"
        )
        replays.append(
            {
                "name": name,
                "xml": xml,
                "level": rep.get("level", ""),
                "mode": rep.get("mode", ""),
                "frames": len(frames),
                "frameTime": float(rep["dt"]) * int(rep.get("substeps", 1)),
            }
        )
        print(f"{name}: {len(frames)} frames, {len(bodies)} bodies")

    if not replays:
        raise SystemExit(f"no replay_*.json in {GOLDEN}")

    scenes = {}
    for xml, m in models.items():
        geoms = []
        for g in range(m.ngeom):
            kind = TYPES.get(int(m.geom_type[g]))
            if kind is None or m.geom_group[g] >= 3 or m.geom_rgba[g][3] == 0:
                continue  # meshes/hfields (none in the scene) and hidden geoms
            geoms.append(
                {
                    "name": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "",
                    "body": int(m.geom_bodyid[g]),
                    "type": kind,
                    "size": r(m.geom_size[g]),
                    "pos": r(m.geom_pos[g]),
                    "quat": r(m.geom_quat[g]),
                    "rgba": r(m.geom_rgba[g], 3),
                }
            )
        scenes[xml] = {"geoms": geoms}
    (DIST / "data" / "model.json").write_text(json.dumps(scenes, separators=(",", ":")), encoding="utf-8")
    (DIST / "data" / "replays.json").write_text(json.dumps(replays, indent=1), encoding="utf-8")

    for f in ("index.html", "diag.html", "app.js", "diag_checks.json", "staticwebapp.config.json"):
        shutil.copy2(WEB / f, DIST / f)
    ver = build_version()
    for html_name in ("index.html", "diag.html"):
        page = DIST / html_name
        text = page.read_text(encoding="utf-8")
        if "{{VERSION}}" not in text:
            raise SystemExit(f"{html_name}: no {{{{VERSION}}}} placeholder")
        page.write_text(text.replace("{{VERSION}}", ver), encoding="utf-8")
    check_diag_config()
    print(f"version v{ver}")
    print(f"built {DIST}")


if __name__ == "__main__":
    main()
