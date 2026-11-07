"""C7: record a 5-second replay for the Step 4 verification gate (consumed by the UE
replay component, B6, and by the Python side of the comparison).

Two modes:
  random  : smooth random PD targets from the `stand` keyframe (same generator as A8)
  policy  : run an exported ONNX policy closed-loop on libmujoco (CPU, float64) with the
            reference obs builder (streetball/obs.py); records obs, action, ctrl and qpos

Output: JSON (easy to parse from C++):
{
  "mode", "xml": "scene.xml", "dt": 0.002, "substeps": 10, "steps": T, "nq", "nu", "n_obs",
  "key": "stand", "qpos0": [nq], "qvel0": [nv],
  "ctrl": [T][nu]       # applied for `substeps` physics steps each
  "qpos": [T][nq]       # state after each control step
  "obs":  [T][n_obs]    # policy mode only: observation fed to the policy at step t
  "action": [T][nu]     # policy mode only: policy output at step t
}

Usage:
  uv run python tools/replay_recorder.py random --out ../shared/golden/replay_random.json
  uv run python tools/replay_recorder.py policy --onnx ../shared/policies/l0_stand.onnx --out ../shared/golden/replay_l0.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streetball import obs as obs_spec  # noqa: E402

SUBSTEPS = 10


def smooth_random_ctrl(m: mujoco.MjModel, T: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    nominal = m.key_ctrl[key].copy()
    lo, hi = m.actuator_ctrlrange[:, 0], m.actuator_ctrlrange[:, 1]
    half = 0.5 * (hi - lo)
    seq = np.empty((T, m.nu)); a = np.zeros(m.nu)
    for t in range(T):
        a = 0.9 * a + 0.1 * rng.uniform(-1, 1, m.nu)
        seq[t] = np.clip(nominal + 0.3 * half * a, lo, hi)
    return seq


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["random", "policy"])
    ap.add_argument("--onnx", default=None)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    mujoco.mj_resetDataKeyframe(m, d, key)
    mujoco.mj_forward(m, d)
    T = int(round(args.seconds / (m.opt.timestep * SUBSTEPS)))
    rec = {"mode": args.mode, "xml": "scene.xml", "dt": float(m.opt.timestep), "substeps": SUBSTEPS, "steps": T,
           "nq": int(m.nq), "nu": int(m.nu), "n_obs": obs_spec.N_OBS, "key": "stand",
           "qpos0": d.qpos.tolist(), "qvel0": d.qvel.tolist(), "ctrl": [], "qpos": []}

    if args.mode == "random":
        seq = smooth_random_ctrl(m, T, args.seed)
        for t in range(T):
            d.ctrl[:] = seq[t]
            for _ in range(SUBSTEPS):
                mujoco.mj_step(m, d)
            rec["ctrl"].append(d.ctrl.tolist()); rec["qpos"].append(d.qpos.tolist())
    else:
        import onnxruntime as ort
        sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
        ix = obs_spec.ObsIndex(m)
        prev = np.zeros(obs_spec.N_JOINTS); task = np.zeros(obs_spec.N_TASK)
        rec["obs"] = []; rec["action"] = []
        last_palm = -10.0
        for t in range(T):
            o = obs_spec.compute_obs(m, d, ix, prev, task, 0.0, 1.0)
            a = sess.run(["action"], {"obs": o[None].astype(np.float32)})[0][0].astype(np.float64)
            a = np.clip(a, -1, 1)
            d.ctrl[:] = ix.action_to_ctrl(a)
            for _ in range(SUBSTEPS):
                mujoco.mj_step(m, d)
            prev = a
            rec["obs"].append(o.tolist()); rec["action"].append(a.tolist())
            rec["ctrl"].append(d.ctrl.tolist()); rec["qpos"].append(d.qpos.tolist())

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec), encoding="utf-8")
    root = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    print(f"wrote {out}: {T} control steps, final pelvis z {rec['qpos'][-1][root + 2]:.3f} m")


if __name__ == "__main__":
    main()
