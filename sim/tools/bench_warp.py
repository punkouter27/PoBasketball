"""A1 smoke benchmark: step N copies of a model on MuJoCo Warp with CUDA graph capture.

Usage: uv run python tools/bench_warp.py [path/to/model.xml] [--n 4096] [--steps 500]
Default model is the mujoco_warp test humanoid.
"""
import argparse
import pathlib
import time

import mujoco
import mujoco_warp as mjw
import warp as wp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xml", nargs="?", default=None)
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--steps", type=int, default=500)
    args = ap.parse_args()

    xml = args.xml or str(
        pathlib.Path(mjw.__file__).parent / "test_data" / "humanoid" / "humanoid.xml"
    )
    mjm = mujoco.MjModel.from_xml_path(xml)
    mjd = mujoco.MjData(mjm)
    mujoco.mj_forward(mjm, mjd)

    m = mjw.put_model(mjm)
    d = mjw.put_data(mjm, mjd, nworld=args.n)
    for _ in range(10):
        mjw.step(m, d)
    wp.synchronize()

    with wp.ScopedCapture() as cap:
        mjw.step(m, d)
    t = time.perf_counter()
    for _ in range(args.steps):
        wp.capture_launch(cap.graph)
    wp.synchronize()
    dt = time.perf_counter() - t
    rate = args.n * args.steps / dt
    print(
        f"{xml}\n{args.n} envs x {args.steps} steps in {dt:.2f}s -> "
        f"{rate/1e6:.2f} M physics steps/s  (nq={mjm.nq}, nv={mjm.nv}, "
        f"mean active contacts/world={d.nacon.numpy().sum()/args.n:.1f})"
    )


if __name__ == "__main__":
    main()
