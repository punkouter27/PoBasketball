"""Record a bank of real simulated falls for the get-up level (levels/l5_getup.py, UU_AGENT §3: "train recovery /
get-up skills starting from real simulated falls").

A shipped balance policy stands on CPU MuJoCo (the same scene.xml as training) and is knocked over by a large random
pelvis push. Once it has fallen (env_base's rule: pelvis below 0.55 m, or a body other than feet/palms on the floor),
the policy keeps acting for a random 0.3-1.5 s and the state is saved; so the bank holds bodies lying, sliding and
still settling, not only the instant of impact.

    uv run python tools/record_fall_states.py --onnx ../shared/policies/l0_stand.onnx --n 512
    -> data/fall_states.npz  (qpos [K, nq], qvel [K, nv], plus provenance)
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib

import mujoco
import numpy as np

from streetball import obs as obs_spec

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fall_states.npz"
SUBSTEPS = 10
PELVIS_FALL_Z = 0.55  # = env_base.StreetballEnv.step


def fallen(m, d, ix, pelvis_b, ok_geoms) -> bool:
    if d.qpos[ix.root_q + 2] < PELVIS_FALL_Z:
        return True
    for c in d.contact[: d.ncon]:
        if ix.floor_geom in (c.geom1, c.geom2):
            other = c.geom2 if c.geom1 == ix.floor_geom else c.geom1
            if other not in ok_geoms and other != ix.floor_geom and m.geom_bodyid[other] != ix.ball:
                return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=str(ROOT.parent / "shared" / "policies" / "l0_stand.onnx"))
    ap.add_argument("--n", type=int, default=512)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    import onnxruntime as ort

    rng = np.random.default_rng(args.seed)
    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    ix = obs_spec.ObsIndex(m)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    pelvis_b = ix.pelvis
    ok = set(ix.foot_geom) | set(ix.toe_geom)
    ok |= {mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"palm_{s}") for s in "lr"}
    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    task = np.zeros(obs_spec.N_TASK)
    control_dt = m.opt.timestep * SUBSTEPS

    qpos, qvel, push_n = [], [], []
    tries = 0
    while len(qpos) < args.n:
        tries += 1
        mujoco.mj_resetDataKeyframe(m, d, key)
        d.qpos[ix.ball_q : ix.ball_q + 3] = (2.0, 2.0, 0.12)  # ball out of the way
        mujoco.mj_forward(m, d)
        prev = np.zeros(obs_spec.N_JOINTS)
        t_push = rng.uniform(0.5, 1.5)
        ang = rng.uniform(0, 2 * np.pi)
        mag = rng.uniform(250.0, 600.0)
        dur = rng.uniform(0.15, 0.35)
        settle = rng.uniform(0.3, 1.5)
        t_fall = None
        for _ in range(int(6.0 / control_dt)):
            o = obs_spec.compute_obs(m, d, ix, prev, task, 0.0, 1.0)
            a = np.clip(sess.run(["action"], {"obs": o[None].astype(np.float32)})[0][0], -1, 1).astype(np.float64)
            d.ctrl[:] = ix.action_to_ctrl(a)
            d.xfrc_applied[pelvis_b, :] = 0.0
            if t_push <= d.time < t_push + dur:
                d.xfrc_applied[pelvis_b, :2] = mag * np.cos(ang), mag * np.sin(ang)
            for _ in range(SUBSTEPS):
                mujoco.mj_step(m, d)
            prev = a
            if not np.isfinite(d.qpos).all():
                break
            if t_fall is None and fallen(m, d, ix, pelvis_b, ok):
                t_fall = d.time
            if t_fall is not None and d.time >= t_fall + settle:
                qpos.append(d.qpos.copy())
                qvel.append(d.qvel.copy())
                push_n.append(mag)
                break
    sha = hashlib.sha256(pathlib.Path(args.onnx).read_bytes()).hexdigest()[:16]
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        qpos=np.array(qpos),
        qvel=np.array(qvel),
        push_n=np.array(push_n),
        source_onnx=pathlib.Path(args.onnx).name,
        source_sha256_16=sha,
        seed=args.seed,
    )
    z = np.array(qpos)[:, ix.root_q + 2]
    print(
        f"{len(qpos)} falls from {tries} pushes -> {out}; pelvis height min/median/max {z.min():.2f}/"
        f"{np.median(z):.2f}/{z.max():.2f} m"
    )


if __name__ == "__main__":
    main()
