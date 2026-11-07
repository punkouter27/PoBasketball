"""A8: MuJoCo Warp (float32, GPU) vs libmujoco (float64, CPU) drift over a 5 s replay.

Same scene.xml, same keyframe, same 250-step (50 Hz) action sequence with 10 physics
substeps each. Contract section 6 gate: root position within 2 cm and every joint
within 1 degree at every control step. Also checks Warp world-to-world determinism.

Run: uv run python -m pytest tests/test_determinism.py -q -s
"""
import json
import pathlib

import mujoco
import mujoco_warp as mjw
import numpy as np
import warp as wp

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
REPORT = ROOT.parent / "docs" / "phase_reports" / "A8_determinism.md"

N_CTRL = 250
SUBSTEPS = 10
NWORLD = 8


def _action_sequence(m: mujoco.MjModel, rng: np.random.Generator) -> np.ndarray:
    """Smooth random targets around the stand keyframe, inside ctrlrange."""
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    nominal = m.key_ctrl[key].copy()
    lo, hi = m.actuator_ctrlrange[:, 0], m.actuator_ctrlrange[:, 1]
    half = 0.5 * (hi - lo)
    seq = np.empty((N_CTRL, m.nu))
    a = np.zeros(m.nu)
    for t in range(N_CTRL):
        a = 0.9 * a + 0.1 * rng.uniform(-1, 1, m.nu)
        seq[t] = np.clip(nominal + 0.3 * half * a, lo, hi)
    return seq


def _run_cpu(m: mujoco.MjModel, seq: np.ndarray):
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand"))
    out = np.empty((N_CTRL, m.nq))
    for t in range(N_CTRL):
        d.ctrl[:] = seq[t]
        for _ in range(SUBSTEPS):
            mujoco.mj_step(m, d)
        out[t] = d.qpos
    return out


def _run_warp(m: mujoco.MjModel, seq: np.ndarray):
    d0 = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d0, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand"))
    mujoco.mj_forward(m, d0)
    wm = mjw.put_model(m)
    wd = mjw.put_data(m, d0, nworld=NWORLD)
    out = np.empty((N_CTRL, NWORLD, m.nq))
    ctrl_host = np.zeros((NWORLD, m.nu), dtype=np.float32)
    for t in range(N_CTRL):
        ctrl_host[:] = seq[t]
        wd.ctrl.assign(ctrl_host)
        for _ in range(SUBSTEPS):
            mjw.step(wm, wd)
        out[t] = wd.qpos.numpy()
    wp.synchronize()
    return out


def test_warp_vs_cpu_drift():
    m = mujoco.MjModel.from_xml_path(str(ASSETS / "scene.xml"))
    rng = np.random.default_rng(0)
    seq = _action_sequence(m, rng)

    cpu = _run_cpu(m, seq)
    gpu = _run_warp(m, seq)

    # Warp world-to-world determinism
    w2w = np.abs(gpu - gpu[:, :1]).max()

    root = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    jadr = np.array([m.jnt_qposadr[m.actuator_trnid[i, 0]] for i in range(m.nu)])

    g = gpu[:, 0]
    root_err = np.linalg.norm(g[:, root:root + 3] - cpu[:, root:root + 3], axis=1)        # m
    joint_err = np.degrees(np.abs(g[:, jadr] - cpu[:, jadr]))                             # deg
    ball = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "ball")]
    ball_err = np.linalg.norm(g[:, ball:ball + 3] - cpu[:, ball:ball + 3], axis=1)

    t = np.arange(1, N_CTRL + 1) * SUBSTEPS * m.opt.timestep
    rows = [(1.0, 2.0, 3.0, 4.0, 5.0)]
    lines = []
    for sec in rows[0]:
        i = int(sec / (SUBSTEPS * m.opt.timestep)) - 1
        lines.append(f"| {sec:.0f} s | {root_err[i]*100:.3f} cm | {joint_err[i].max():.3f}° | {ball_err[i]*100:.2f} cm |")

    passed = root_err.max() < 0.02 and joint_err.max() < 1.0
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        f"# A8 — Warp vs libmujoco determinism: {'PASS' if passed else 'FAIL'}\n\n"
        f"Scene `scene.xml`, keyframe `stand`, {N_CTRL} control steps × {SUBSTEPS} substeps "
        f"(dt {m.opt.timestep}), smooth random PD targets. Warp float32 on GPU vs libmujoco float64 on CPU.\n\n"
        f"| Time | Root pos error | Max joint error | Ball pos error |\n|---|---|---|---|\n"
        + "\n".join(lines)
        + f"\n\nMax over the run: root {root_err.max()*100:.3f} cm (gate 2 cm), joints {joint_err.max():.3f}° (gate 1°), "
          f"ball {ball_err.max()*100:.2f} cm (informational).\n\n"
          f"Warp world-to-world max |Δqpos| over {NWORLD} identical worlds: {w2w:.2e} (gate 1e-3; Warp sums contact forces with atomics, so it is not bit-exact).\n",
        encoding="utf-8",
    )
    print(REPORT.read_text(encoding="utf-8").encode("ascii", "replace").decode())
    # Warp is not bit-deterministic across worlds (atomic accumulation order); it must stay tiny.
    assert w2w < 1e-3, f"Warp worlds with identical inputs diverged by {w2w:.2e}"
    assert passed, f"drift gate failed: root {root_err.max()*100:.2f} cm, joints {joint_err.max():.2f} deg"
