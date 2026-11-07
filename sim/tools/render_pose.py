"""Render the scene to PNG for a visual sanity check.

Usage: uv run python tools/render_pose.py [--key stand] [--out ../docs/phase_reports/A3_pose.png]
"""
import argparse
import pathlib

import mujoco
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="stand")
    ap.add_argument("--out", default=str(ROOT.parent / "docs" / "phase_reports" / "A3_pose.png"))
    args = ap.parse_args()

    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    if args.key == "zero":
        mujoco.mj_resetData(m, d)
    else:
        mujoco.mj_resetDataKeyframe(m, d, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, args.key))
    mujoco.mj_forward(m, d)

    r = mujoco.Renderer(m, height=720, width=1280)
    tiles = []
    for az, el, dist, look in [(135, -15, 3.2, (0, 0, 0.95)), (90, -10, 3.2, (0, 0, 0.95)),
                               (180, -10, 3.2, (0, 0, 0.95)), (150, -25, 12.0, (6, 0, 1.5))]:
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.azimuth, cam.elevation, cam.distance = az, el, dist
        cam.lookat[:] = look
        r.update_scene(d, camera=cam)
        tiles.append(r.render().copy())
    top = np.concatenate(tiles[:2], axis=1)
    bottom = np.concatenate(tiles[2:], axis=1)
    img = np.concatenate([top, bottom], axis=0)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
