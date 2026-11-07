"""Retarget LocoMuJoCo SkeletonTorque mocap onto the Streetball humanoid and build AMP demo transitions.

    uv run python tools/retarget_loco_mujoco.py --src ../../ext/mocap_raw --skeleton ../../ext/loco-mujoco-models/loco_mujoco_models/skeleton/skeleton_torque.xml

Data licence: robfiras/loco-mujoco-datasets is CC BY-NC-ND 4.0 (non-commercial, no redistribution of
derivatives). The retargeted output (sim/data/mocap/) is git-ignored and must not be shipped.

Method (joint-space retargeting; enough for a style prior, not for tracking):
  1. Joint map by anatomical name (SkeletonTorque -> ours). Pronation/supination is dropped (we have none).
  2. Sign per joint by *function*: +0.3 rad on the joint in each model from its anatomical-zero pose and compare
     the world displacement of the distal body's centre of mass (hand / foot / head). |cos| < 0.5 -> joint zeroed.
  3. q_ours_model = clip(sign * q_src, anatomical range) - anatomical_offset.
  4. Root: orientation re-expressed through the constant pelvis-frame offset between the models at qpos0;
     position scaled by the pelvis-height ratio; per clip the floor is re-levelled from the feet.
  5. Resample to the 50 Hz control rate; velocities by finite differences (mj_differentiatePos).
  6. Features via streetball.amp.amp_features on (s_t, s_t+1) pairs -> sim/data/mocap/amp_demo.npz
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import mujoco
import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streetball.amp import KEY_BODIES, amp_features  # noqa: E402

SHARED = ROOT.parent / "shared"
OUT = ROOT / "data" / "mocap"
CONTROL_HZ = 50.0

MAP = {  # ours <- SkeletonTorque
    "shoulder_pitch_l": "arm_flex_l", "shoulder_abd_l": "arm_add_l", "shoulder_rot_l": "arm_rot_l", "elbow_l": "elbow_flex_l",
    "wrist_flex_l": "wrist_flex_l", "wrist_dev_l": "wrist_dev_l",
    "shoulder_pitch_r": "arm_flex_r", "shoulder_abd_r": "arm_add_r", "shoulder_rot_r": "arm_rot_r", "elbow_r": "elbow_flex_r",
    "wrist_flex_r": "wrist_flex_r", "wrist_dev_r": "wrist_dev_r",
    "hip_flex_l": "hip_flexion_l", "hip_abd_l": "hip_adduction_l", "hip_rot_l": "hip_rotation_l", "knee_l": "knee_angle_l",
    "ankle_pitch_l": "ankle_angle_l", "ankle_roll_l": "subtalar_angle_l",
    "hip_flex_r": "hip_flexion_r", "hip_abd_r": "hip_adduction_r", "hip_rot_r": "hip_rotation_r", "knee_r": "knee_angle_r",
    "ankle_pitch_r": "ankle_angle_r", "ankle_roll_r": "subtalar_angle_r",
    "lumbar_flex": "lumbar_extension", "lumbar_lat": "lumbar_bending", "lumbar_twist": "lumbar_rotation",
}
# Joints where the functional test is ambiguous at the anatomical-zero pose (forearm supination differs between the
# models). Elbow: both models define + as flexion (ranges 0..145 / -17..150), so the sign is set by convention.
# Wrists contribute little to locomotion style and are held at zero.
SIGN_OVERRIDE = {"elbow_l": 1.0, "elbow_r": 1.0, "wrist_flex_l": 0.0, "wrist_flex_r": 0.0, "wrist_dev_l": 0.0, "wrist_dev_r": 0.0}
# distal body whose COM displacement defines the joint's function (ours, skeleton)
EFFECTOR = {"shoulder": ("hand", "hand"), "elbow": ("hand", "hand"), "wrist": ("hand", "hand"),
            "hip": ("foot", "calcn"), "knee": ("foot", "calcn"), "ankle": ("foot", "toes"), "lumbar": ("head", "torso")}


def jid(m, n):
    return mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, n)


def bid(m, n):
    return mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)


def effector(ours: str) -> tuple[str, str]:
    group = ours.split("_")[0]
    o, s = EFFECTOR[group]
    side = ours[-1] if ours[-2] == "_" else ""
    return (f"{o}_{side}" if side else o), (f"{s}_{side}" if side else s)


def calibrate(ms, md, off, jnames):
    ds, dd = mujoco.MjData(ms), mujoco.MjData(md)
    base_d = md.qpos0.copy()
    for n in MAP:
        base_d[md.jnt_qposadr[jid(md, n)]] = -off[n]           # anatomical zero
    root = md.jnt_qposadr[jid(md, "root")]
    base_d[root:root + 7] = [0, 0, 1.2, 1, 0, 0, 0]
    signs, quality = {}, {}
    for ours, src in MAP.items():
        eo, es = effector(ours)
        disp = []
        for m, d, q0, jn, bn in ((ms, ds, ms.qpos0.copy(), src, es), (md, dd, base_d.copy(), ours, eo)):
            b = bid(m, bn)
            d.qpos[:] = q0; mujoco.mj_kinematics(m, d); mujoco.mj_comPos(m, d); p0 = d.xipos[b].copy()
            d.qpos[:] = q0; d.qpos[m.jnt_qposadr[jid(m, jn)]] += 0.3; mujoco.mj_kinematics(m, d); p1 = d.xipos[b].copy()
            disp.append(p1 - p0)
        a, b_ = disp
        c = float(a @ b_ / (np.linalg.norm(a) * np.linalg.norm(b_) + 1e-9))
        signs[ours] = SIGN_OVERRIDE.get(ours, 0.0 if abs(c) < 0.5 else float(np.sign(c)))
        quality[ours] = round(c, 2)
    return signs, quality


def slerp(q0, q1, t):
    d = np.sum(q0 * q1, -1, keepdims=True)
    q1 = np.where(d < 0, -q1, q1); d = np.abs(d)
    th = np.arccos(np.clip(d, -1, 1)); s = np.sin(th)
    w0 = np.where(s > 1e-6, np.sin((1 - t) * th) / np.maximum(s, 1e-6), 1 - t)
    w1 = np.where(s > 1e-6, np.sin(t * th) / np.maximum(s, 1e-6), t)
    q = w0 * q0 + w1 * q1
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def quat_mul(a, b):
    w1, x1, y1, z1 = np.moveaxis(a, -1, 0); w2, x2, y2, z2 = np.moveaxis(b, -1, 0)
    return np.stack([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2], -1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="folder with SkeletonTorque .npz clips")
    ap.add_argument("--skeleton", required=True, help="skeleton_torque.xml")
    ap.add_argument("--clips", default="", help="comma list of file stems (default: all)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    ms = mujoco.MjModel.from_xml_path(args.skeleton)
    md = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    spec = json.loads((SHARED / "humanoid_spec.json").read_text(encoding="utf-8"))
    order = [j["name"] for j in spec["joints"]]
    off = {j["name"]: np.radians(j.get("anatomical_offset_deg", 0.0)) for j in spec["joints"]}
    rng_anat = {n: (md.jnt_range[jid(md, n)] + off[n]) for n in order}
    signs, quality = calibrate(ms, md, off, order)
    print("sign calibration (cos of effector displacement):")
    for n in order:
        print(f"  {n:17s} <- {MAP[n]:17s} cos {quality[n]:+.2f} -> sign {signs[n]:+.0f}")

    # constant pelvis-frame offset: R_dst = R_src @ C, C = R_src0^T R_dst0 (R_dst0 = I)
    ds = mujoco.MjData(ms); mujoco.mj_kinematics(ms, ds)
    C = ds.xmat[bid(ms, "pelvis")].reshape(3, 3).T
    qC = np.zeros(4); mujoco.mju_mat2Quat(qC, C.flatten())
    h_src = float(ds.xpos[bid(ms, "pelvis")][2])
    dd = mujoco.MjData(md)
    key = mujoco.mj_name2id(md, mujoco.mjtObj.mjOBJ_KEY, "stand")
    mujoco.mj_resetDataKeyframe(md, dd, key); mujoco.mj_kinematics(md, dd)
    rootq = md.jnt_qposadr[jid(md, "root")]
    h_dst = float(dd.qpos[rootq + 2])
    scale = h_dst / h_src
    print(f"pelvis height src {h_src:.3f} m, ours {h_dst:.3f} m -> scale {scale:.3f}")

    jadr = np.array([md.jnt_qposadr[jid(md, n)] for n in order])
    vadr = np.array([md.jnt_dofadr[jid(md, n)] for n in order])
    rootv = md.jnt_dofadr[jid(md, "root")]
    keyb = [bid(md, b) for b in KEY_BODIES]
    foot_geoms = [mujoco.mj_name2id(md, mujoco.mjtObj.mjOBJ_GEOM, g) for g in ("foot_l", "foot_r")]

    stems = [s for s in args.clips.split(",") if s] or sorted(p.stem for p in pathlib.Path(args.src).glob("*.npz"))
    all_pairs, report = [], []
    for stem in stems:
        z = np.load(pathlib.Path(args.src) / f"{stem}.npz", allow_pickle=True)
        names = list(z["joint_names"]); qpos_s = z["qpos"].astype(np.float64); hz = float(z["frequency"])
        sp = list(z["split_points"]) if z["split_points"].size else [0, len(qpos_s)]
        # column index inside this clip's qpos (clips may omit joints, e.g. LAFAN1 drops mtp / pro_sup)
        qadr_s, col = {}, 0
        for nm in names:
            qadr_s[nm] = col
            col += 7 if nm == "root" else 1
        assert col == qpos_s.shape[1], (stem, col, qpos_s.shape)
        for seg in range(len(sp) - 1):
            Q = qpos_s[sp[seg]:sp[seg + 1]]
            if len(Q) < hz:                                    # under one second
                continue
            T = (len(Q) - 1) / hz
            t_new = np.arange(0.0, T, 1.0 / CONTROL_HZ)
            u = t_new * hz; i0 = np.floor(u).astype(int); i1 = np.minimum(i0 + 1, len(Q) - 1); w = (u - i0)[:, None]
            n = len(t_new)
            q = np.tile(md.qpos0, (n, 1))
            # root
            ps = Q[:, 0:3]; qs = Q[:, 3:7]
            p = (1 - w) * ps[i0] + w * ps[i1]
            r = slerp(qs[i0], qs[i1], w)
            q[:, rootq:rootq + 3] = (p - p[0] * np.array([1, 1, 0])) * scale
            q[:, rootq + 3:rootq + 7] = quat_mul(r, np.tile(qC, (n, 1)))
            # joints
            for k, ours in enumerate(order):
                src = MAP[ours]
                if signs[ours] == 0.0 or src not in qadr_s:
                    a = np.zeros(n)
                else:
                    js = (1 - w[:, 0]) * Q[i0, qadr_s[src]] + w[:, 0] * Q[i1, qadr_s[src]]
                    a = signs[ours] * js
                lo, hi = rng_anat[ours]
                q[:, jadr[k]] = np.clip(a, lo, hi) - off[ours]
            # floor: lowest foot-geom point per frame, re-levelled so its 3rd percentile sits on z = 0
            low = np.zeros(n)
            for f in range(n):
                dd.qpos[:] = q[f]; mujoco.mj_kinematics(md, dd)
                zs = []
                for g in foot_geoms:
                    Rg = dd.geom_xmat[g].reshape(3, 3); half = md.geom_size[g]
                    zs.append(dd.geom_xpos[g][2] - np.abs(Rg[2, :3]) @ half[:3])
                low[f] = min(zs)
            q[:, rootq + 2] -= np.percentile(low, 3)
            # velocities + FK features
            qv = np.zeros((n, md.nv)); keyp = np.zeros((n, len(keyb), 3))
            for f in range(n):
                if f + 1 < n:
                    mujoco.mj_differentiatePos(md, qv[f], 1.0 / CONTROL_HZ, q[f], q[f + 1])
                else:
                    qv[f] = qv[f - 1]
                dd.qpos[:] = q[f]; mujoco.mj_kinematics(md, dd); keyp[f] = dd.xpos[keyb]
            tt = lambda x: torch.as_tensor(x, dtype=torch.float32)
            feats = amp_features(tt(q[:, rootq:rootq + 3]), tt(q[:, rootq + 3:rootq + 7]), tt(qv[:, rootv:rootv + 3]),
                                 tt(qv[:, rootv + 3:rootv + 6]), tt(q[:, jadr]), tt(qv[:, vadr]), tt(keyp))
            pairs = torch.cat([feats[:-1], feats[1:]], -1)
            all_pairs.append(pairs)
            speed = np.linalg.norm(qv[:, rootv:rootv + 2], axis=1)
            np.savez_compressed(OUT / f"{stem}_seg{seg}_qpos.npz", qpos=q.astype(np.float32), hz=CONTROL_HZ)
            report.append({"clip": stem, "seg": seg, "seconds": round(n / CONTROL_HZ, 1), "mean_speed": round(float(speed.mean()), 2),
                           "pelvis_z": round(float(q[:, rootq + 2].mean()), 3), "clipped_frac": round(float(np.mean(
                               [(np.abs(q[:, jadr[k]] + off[o] - np.clip(q[:, jadr[k]] + off[o], *rng_anat[o])) > 1e-6).mean() for k, o in enumerate(order)])), 3)})
            print(f"  {stem} seg {seg}: {n / CONTROL_HZ:6.1f} s, mean speed {speed.mean():.2f} m/s, pelvis z {q[:, rootq + 2].mean():.3f}")
    demo = torch.cat(all_pairs, 0)
    np.savez_compressed(OUT / "amp_demo.npz", pairs=demo.numpy(), feat_dim=demo.shape[1] // 2,
                        clips=np.array([r["clip"] for r in report]))
    (OUT / "retarget_report.json").write_text(json.dumps({"signs": signs, "calibration_cos": quality, "scale": scale,
                                                           "clips": report, "n_pairs": int(demo.shape[0])}, indent=2), encoding="utf-8")
    print(f"wrote {OUT / 'amp_demo.npz'}: {demo.shape[0]} transitions x {demo.shape[1]} features")


if __name__ == "__main__":
    main()
