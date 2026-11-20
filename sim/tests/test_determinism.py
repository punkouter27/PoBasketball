"""A8: MuJoCo Warp (float32, GPU) vs libmujoco (float64, CPU) drift over a 5 s replay.

Same scene.xml, same keyframe, same 250-step (50 Hz) action sequence with 10 physics substeps each, same device and
fixed seeds. Contract section 6 gate: root position within 2 cm and every actuated joint within 1 degree at every
control step, for EVERY Warp world (not just world 0).

World-to-world: Warp is not bit-deterministic on the GPU (contact/constraint forces are accumulated with float32
atomics, so the summation order changes from launch to launch) and the contact-rich humanoid amplifies that round-off,
so identical worlds drift apart over 5 s (docs/phase_reports/A8_root_cause.md). The like-for-like checks are therefore:
  * the worlds start bit-identical and differ only by round-off after the first control step (< 1e-6): a real
    per-world difference (seed, randomisation, uninitialised buffer) shows up there at once;
  * over the whole replay any two worlds agree within the contract gate (root 2 cm, joints 1 degree).
The ball is a free, bouncing sphere: its position is reported (informational) and its orientation is ignored.

The test writes its report to pytest's tmp_path only. To refresh docs/phase_reports/A8_determinism.md run
    uv run python tools/a8_determinism_report.py
"""

import pathlib

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")
mjw = pytest.importorskip("mujoco_warp", reason="MuJoCo Warp not installed (GPU test; run in sim/.venv)")
wp = pytest.importorskip("warp", reason="NVIDIA Warp not installed (GPU test; run in sim/.venv)")

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

N_CTRL = 250
SUBSTEPS = 10
NWORLD = 8
ROOT_GATE_M = 0.02
JOINT_GATE_DEG = 1.0
FIRST_STEP_ROUNDOFF = 1e-6


def _cuda_available() -> bool:
    try:
        wp.init()
        return wp.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - any Warp/driver failure means "no usable GPU"
        return False


pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(not _cuda_available(), reason="no CUDA device: Warp determinism runs on the GPU only"),
]


def _action_sequence(m, rng: np.random.Generator) -> np.ndarray:
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


def _run_cpu(m, seq: np.ndarray) -> np.ndarray:
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand"))
    out = np.empty((N_CTRL, m.nq))
    for t in range(N_CTRL):
        d.ctrl[:] = seq[t]
        for _ in range(SUBSTEPS):
            mujoco.mj_step(m, d)
        out[t] = d.qpos
    return out


def _run_warp(m, seq: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Returns (initial qpos per world, qpos per control step per world)."""
    d0 = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d0, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand"))
    mujoco.mj_forward(m, d0)
    wm = mjw.put_model(m)
    wd = mjw.put_data(m, d0, nworld=NWORLD, naconmax=NWORLD * 48, njmax=160)
    q0 = wd.qpos.numpy().copy()
    out = np.empty((N_CTRL, NWORLD, m.nq))
    ctrl_host = np.zeros((NWORLD, m.nu), dtype=np.float32)
    for t in range(N_CTRL):
        ctrl_host[:] = seq[t]
        wd.ctrl.assign(ctrl_host)
        for _ in range(SUBSTEPS):
            mjw.step(wm, wd)
        out[t] = wd.qpos.numpy()
    wp.synchronize()
    return q0, out


def measure() -> dict:
    """Run the A8 replay once on CPU and once on Warp; return every number the gates and the report use."""
    m = mujoco.MjModel.from_xml_path(str(ASSETS / "scene.xml"))
    seq = _action_sequence(m, np.random.default_rng(0))
    cpu = _run_cpu(m, seq)
    q0, gpu = _run_warp(m, seq)

    root = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    ball = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "ball")]
    jadr = np.array([m.jnt_qposadr[m.actuator_trnid[i, 0]] for i in range(m.nu)])

    root_err = np.linalg.norm(gpu[:, :, root : root + 3] - cpu[:, None, root : root + 3], axis=-1)  # (T, W) m
    joint_err = np.degrees(np.abs(gpu[:, :, jadr] - cpu[:, None, jadr])).max(axis=-1)  # (T, W) deg
    ball_err = np.linalg.norm(gpu[:, :, ball : ball + 3] - cpu[:, None, ball : ball + 3], axis=-1)

    hum = np.r_[root : root + 3, jadr]  # humanoid root position + actuated joints
    first_step_spread = float(np.abs(gpu[0][:, hum] - gpu[0][:1, hum]).max())
    root_spread = float(np.linalg.norm(gpu[:, :, root : root + 3] - gpu[:, :1, root : root + 3], axis=-1).max())
    joint_spread = float(np.degrees(np.abs(gpu[:, :, jadr] - gpu[:, :1, jadr])).max())
    ball_spread = float(np.linalg.norm(gpu[:, :, ball : ball + 3] - gpu[:, :1, ball : ball + 3], axis=-1).max())

    per_sec = []
    for sec in (1.0, 2.0, 3.0, 4.0, 5.0):
        i = int(sec / (SUBSTEPS * m.opt.timestep)) - 1
        per_sec.append((sec, root_err[i].max(), joint_err[i].max(), ball_err[i].max()))
    return {
        "timestep": float(m.opt.timestep),
        "init_spread": float(np.abs(q0 - q0[:1]).max()),
        "first_step_spread": first_step_spread,
        "root_err_max": float(root_err.max()),
        "joint_err_max": float(joint_err.max()),
        "ball_err_max": float(ball_err.max()),
        "root_spread": root_spread,
        "joint_spread": joint_spread,
        "ball_spread": ball_spread,
        "per_sec": per_sec,
    }


def report_markdown(r: dict) -> str:
    drift_ok = r["root_err_max"] < ROOT_GATE_M and r["joint_err_max"] < JOINT_GATE_DEG
    spread_ok = (
        r["init_spread"] == 0.0
        and r["first_step_spread"] < FIRST_STEP_ROUNDOFF
        and r["root_spread"] < ROOT_GATE_M
        and r["joint_spread"] < JOINT_GATE_DEG
    )
    rows = "\n".join(
        f"| {s:.0f} s | {re * 100:.3f} cm | {je:.3f}° | {be * 100:.2f} cm |" for s, re, je, be in r["per_sec"]
    )
    return (
        f"# A8 — Warp vs libmujoco determinism: {'PASS' if drift_ok and spread_ok else 'FAIL'}\n\n"
        f"Scene `scene.xml`, keyframe `stand`, {N_CTRL} control steps × {SUBSTEPS} substeps (dt {r['timestep']}), "
        f"smooth random PD targets (seed 0). Warp float32 on GPU ({NWORLD} worlds) vs libmujoco float64 on CPU. "
        "Errors are the worst world at each time.\n\n"
        "| Time | Root pos error | Max joint error | Ball pos error |\n|---|---|---|---|\n"
        f"{rows}\n\n"
        f"Max over the run (worst world): root {r['root_err_max'] * 100:.3f} cm (gate 2 cm), joints "
        f"{r['joint_err_max']:.3f}° (gate 1°), ball {r['ball_err_max'] * 100:.2f} cm (informational).\n\n"
        f"World-to-world (identical inputs, same device): start {r['init_spread']:.1e}, after the first control step "
        f"{r['first_step_spread']:.1e} (gate {FIRST_STEP_ROUNDOFF:.0e}: round-off only), over the run root "
        f"{r['root_spread'] * 100:.3f} cm and joints {r['joint_spread']:.3f}° (gates 2 cm / 1°), ball "
        f"{r['ball_spread'] * 100:.2f} cm (informational). Why the worlds are not bit-identical: "
        "docs/phase_reports/A8_root_cause.md.\n"
    )


@pytest.fixture(scope="module")
def a8() -> dict:
    return measure()


def test_warp_vs_cpu_drift(a8, tmp_path):
    (tmp_path / "A8_determinism.md").write_text(report_markdown(a8), encoding="utf-8")
    assert a8["root_err_max"] < ROOT_GATE_M, f"root drift {a8['root_err_max'] * 100:.2f} cm >= 2 cm in some world"
    assert a8["joint_err_max"] < JOINT_GATE_DEG, f"joint drift {a8['joint_err_max']:.2f} deg >= 1 deg in some world"


def test_warp_worlds_like_for_like(a8):
    assert a8["init_spread"] == 0.0, "Warp worlds do not start from the same state"
    assert a8["first_step_spread"] < FIRST_STEP_ROUNDOFF, (
        f"worlds differ by {a8['first_step_spread']:.1e} after one control step: more than float32 round-off, "
        "so some per-world input (seed, randomisation, buffer) is not identical"
    )
    assert a8["root_spread"] < ROOT_GATE_M, f"identical worlds diverged {a8['root_spread'] * 100:.2f} cm at the root"
    assert a8["joint_spread"] < JOINT_GATE_DEG, f"identical worlds diverged {a8['joint_spread']:.2f} deg at a joint"
