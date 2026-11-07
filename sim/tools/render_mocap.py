"""Render a strip of frames of a retargeted clip on the Streetball humanoid (visual check of the retargeting).

    uv run python tools/render_mocap.py data/mocap/default_walk_seg0_qpos.npz --start 10 --frames 8 --step 6 --out walk.png
"""
from __future__ import annotations

import argparse
import pathlib

import mujoco
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--start", type=float, default=5.0, help="seconds")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--step", type=int, default=6, help="control steps between frames (50 Hz)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    q = np.load(args.clip)["qpos"]
    root = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    r = mujoco.Renderer(m, 360, 300)
    cam = mujoco.MjvCamera()
    tiles = []
    for i in range(args.frames):
        f = min(len(q) - 1, int(args.start * 50) + i * args.step)
        d.qpos[:] = q[f]
        mujoco.mj_forward(m, d)
        cam.lookat[:] = [d.qpos[root], d.qpos[root + 1], 0.9]
        cam.distance, cam.elevation = 3.0, -8.0
        # side view relative to the athlete's heading
        w, x, y, z = d.qpos[root + 3:root + 7]
        yaw = np.degrees(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
        cam.azimuth = yaw + 90.0
        r.update_scene(d, cam)
        tiles.append(r.render())
    Image.fromarray(np.concatenate(tiles, 1)).save(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
