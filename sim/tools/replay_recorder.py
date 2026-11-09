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
    ap.add_argument("--level", default="l0_stand", choices=["l0_stand", "l1_traverse", "l2a_dribble_r"],
                    help="policy mode: start state and task block of this level (zeros for l0_stand)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    mujoco.mj_resetDataKeyframe(m, d, key)
    root = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    ball = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "ball")]
    ball_v = m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "ball")]
    rng = np.random.default_rng(args.seed)
    in_control0 = 0.0
    if args.mode == "policy":
        if args.level in ("l0_stand", "l1_traverse"):
            # Tier 1/2 start as in training and the Unreal director: ball parked away from the feet,
            # not at its keyframe spot beside the right foot (the athlete trips over it).
            d.qpos[ball:ball + 3] = ([d.qpos[root] + 3.0, d.qpos[root + 1], 0.1205] if args.level == "l0_stand"
                                     else [0.0, 8.0, 0.1205])
        else:
            # l2a_dribble_r start (l2_dribble.on_reset, mirrored by UStreetballDirector::PrepareReset): right hand,
            # ball at the dribble spot (0.25 m ahead, 0.35 m right of the root), h ~ U(0.40, 0.95), vz = -/+ sqrt(2g(1-h))
            q = d.qpos[root + 3:root + 7]
            fwd = obs_spec.heading_mat(q)[:2, 0]; left = obs_spec.heading_mat(q)[:2, 1]
            spot = d.qpos[root:root + 2] + 0.25 * fwd - 0.35 * left
            h = rng.uniform(0.40, 0.95)
            vz = -np.sqrt(2 * 9.81 * (1.0 - h)) * (1.0 if rng.uniform() < 0.5 else -1.0)
            d.qpos[ball:ball + 7] = [spot[0], spot[1], h, 1, 0, 0, 0]
            d.qvel[ball_v:ball_v + 6] = [0, 0, vz, 0, 0, 0]
            in_control0 = 1.0
    mujoco.mj_forward(m, d)
    T = int(round(args.seconds / (m.opt.timestep * SUBSTEPS)))
    rec = {"mode": args.mode, "level": args.level, "xml": "scene.xml", "dt": float(m.opt.timestep), "substeps": SUBSTEPS,
           "steps": T, "nq": int(m.nq), "nv": int(m.nv), "nu": int(m.nu), "n_obs": obs_spec.N_OBS, "key": "stand",
           "qpos0": d.qpos.tolist(), "qvel0": d.qvel.tolist(), "ctrl": [], "qpos": [], "qvel": [], "angmom": []}
    pelvis = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "pelvis")

    def kinematics():
        # whole-body angular momentum about the humanoid's CoM (subtree of the pelvis), for the 5 s rollout gate
        rec["qvel"].append(d.qvel.tolist())
        mujoco.mj_subtreeVel(m, d)
        rec["angmom"].append(d.subtree_angmom[pelvis].tolist())

    if args.mode == "random":
        seq = smooth_random_ctrl(m, T, args.seed)
        for t in range(T):
            d.ctrl[:] = seq[t]
            for _ in range(SUBSTEPS):
                mujoco.mj_step(m, d)
            rec["ctrl"].append(d.ctrl.tolist()); rec["qpos"].append(d.qpos.tolist()); kinematics()
    else:
        import onnxruntime as ort
        sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
        ix = obs_spec.ObsIndex(m)
        prev = np.zeros(obs_spec.N_JOINTS); task = np.zeros(obs_spec.N_TASK)
        rec["obs"] = []; rec["action"] = []; rec["task"] = []; rec["in_control"] = []; rec["countdown"] = []
        ball_g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "ball")
        palm_g = {mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"palm_{s}") for s in "lr"}
        # l1_traverse command: a waypoint 10 m ahead and 2 m left of the start, 1.5 m/s (never reached in 5 s)
        q0 = d.qpos[root + 3:root + 7]
        wp = d.qpos[root:root + 2] + 10.0 * obs_spec.heading_mat(q0)[:2, 0] + 2.0 * obs_spec.heading_mat(q0)[:2, 1]
        in_ctrl, countdown, loose_t, last_palm = in_control0, 1.0, -1.0, (0.0 if in_control0 else -10.0)
        for t in range(T):
            if args.level == "l1_traverse":
                rel = wp - d.qpos[root:root + 2]
                dist = float(np.linalg.norm(rel))
                Hm = obs_spec.heading_mat(d.qpos[root + 3:root + 7])
                dw = rel / max(dist, 1e-6)
                task[:4] = [dw @ Hm[:2, 0], dw @ Hm[:2, 1], min(dist, 10.0), 1.5]
            elif args.level == "l2a_dribble_r":
                task[:3] = [1.0, 1.0, 0.0]             # right hand, apex 1.0 m, no commanded switches
            o = obs_spec.compute_obs(m, d, ix, prev, task, in_ctrl, countdown)
            rec["task"].append(task.tolist()); rec["in_control"].append(in_ctrl); rec["countdown"].append(countdown)
            a = sess.run(["action"], {"obs": o[None].astype(np.float32)})[0][0].astype(np.float64)
            a = np.clip(a, -1, 1)
            d.ctrl[:] = ix.action_to_ctrl(a)
            for _ in range(SUBSTEPS):
                mujoco.mj_step(m, d)
            prev = a
            # ball control after the step (env_base._update_ball_state / UStreetballTracker::Update)
            now = d.time
            if any((c.geom1 == ball_g and c.geom2 in palm_g) or (c.geom2 == ball_g and c.geom1 in palm_g) for c in d.contact[:d.ncon]):
                last_palm = now
            horiz = float(np.linalg.norm(d.qpos[ball:ball + 2] - d.qpos[root:root + 2]))
            ctrl_ok = horiz < 0.75 and d.qpos[ball + 2] < 1.3 and (now - last_palm) < 0.6
            if not ctrl_ok and in_ctrl > 0.5:
                loose_t = now
            if ctrl_ok:
                loose_t = -1.0
            in_ctrl = 1.0 if ctrl_ok else 0.0
            countdown = float(np.clip(1.0 - (now - loose_t) / 3.0, 0, 1)) if loose_t >= 0 else 1.0
            rec["obs"].append(o.tolist()); rec["action"].append(a.tolist())
            rec["ctrl"].append(d.ctrl.tolist()); rec["qpos"].append(d.qpos.tolist()); kinematics()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec), encoding="utf-8")
    root = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    print(f"wrote {out}: {T} control steps, final pelvis z {rec['qpos'][-1][root + 2]:.3f} m")
    min_z = min(q[root + 2] for q in rec["qpos"])
    if args.mode == "policy" and min_z < 0.7:
        # a golden where the athlete falls makes the Unreal gate meaningless (it passed that way on 2026-11-06)
        raise SystemExit(f"FAIL: pelvis dropped to {min_z:.3f} m (< 0.70 m); the policy does not stay upright from the keyframe")


if __name__ == "__main__":
    main()
