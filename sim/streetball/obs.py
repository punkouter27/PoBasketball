"""Observation specification: the single source of truth shared by training (Python)
and runtime (C++ in the UE plugin).

Layout (119 floats, blueprint C.1). Every slot has a name, index range and scale so
`shared/obs_spec.json` can be generated and the C++ builder can be diff-tested
against `shared/golden/obs_golden.npz`.

Frames
  pelvis frame   : full orientation of the pelvis body (sim world -> pelvis).
  heading frame  : yaw-only rotation of the pelvis about world Z. Ball quantities
                   are expressed here so they stay meaningful when the torso leans.

    [  0:  3] gravity direction in pelvis frame            (unit vector)
    [  3:  6] pelvis linear velocity, pelvis frame         (m/s)        x 1.0
    [  6:  9] pelvis angular velocity, pelvis frame        (rad/s)      x 0.25
    [  9: 36] joint positions minus nominal                (rad)        x 1.0
    [ 36: 63] joint velocities                             (rad/s)      x 0.1
    [ 63: 90] previous action                              ([-1,1])
    [ 90: 93] ball position - pelvis position, heading frame (m)        x 1.0
    [ 93: 96] ball velocity - pelvis velocity, heading frame (m/s)      x 0.5
    [ 96    ] ball-in-control flag                         (0/1)
    [ 97: 99] palm_l, palm_r distance to ball centre       (m)          x 1.0
    [ 99:101] foot_l, foot_r floor-contact flags           (0/1)
    [101    ] pelvis height                                (m)
    [102:105] ball angular velocity, heading frame         (rad/s)      x 0.05
    [105    ] scramble countdown remaining fraction        (0..1, 1 when not loose)
    [106    ] reserved (0)
    [107:119] level task block (12), zero-padded; meaning per level in levels/*.py

Actions: 27 floats in [-1, 1]; target_i = clip(nominal_i + a_i * 0.5*(hi_i - lo_i), lo_i, hi_i).
"""
from __future__ import annotations

import json
import pathlib

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"

N_JOINTS = 27
N_TASK = 12
N_BASE = 107
N_OBS = N_BASE + N_TASK

SLOTS = [
    # name, start, size, scale
    ("gravity_pelvis", 0, 3, 1.0),
    ("pelvis_linvel", 3, 3, 1.0),
    ("pelvis_angvel", 6, 3, 0.25),
    ("joint_pos_rel", 9, N_JOINTS, 1.0),
    ("joint_vel", 36, N_JOINTS, 0.1),
    ("prev_action", 63, N_JOINTS, 1.0),
    ("ball_pos_rel", 90, 3, 1.0),
    ("ball_vel_rel", 93, 3, 0.5),
    ("ball_in_control", 96, 1, 1.0),
    ("palm_ball_dist", 97, 2, 1.0),
    ("foot_contact", 99, 2, 1.0),
    ("pelvis_height", 101, 1, 1.0),
    ("ball_angvel", 102, 3, 0.05),
    ("countdown_frac", 105, 1, 1.0),
    ("reserved", 106, 1, 1.0),
    ("task", 107, N_TASK, 1.0),
]
assert SLOTS[-1][1] + SLOTS[-1][2] == N_OBS


class ObsIndex:
    """Cached model indices so compute_obs is allocation-light."""

    def __init__(self, m: mujoco.MjModel):
        spec = json.load(open(SHARED / "humanoid_spec.json", encoding="utf-8"))
        self.joint_names = [j["name"] for j in spec["joints"]]
        assert len(self.joint_names) == N_JOINTS
        jids = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, n) for n in self.joint_names]
        self.qadr = np.array([m.jnt_qposadr[j] for j in jids])
        self.vadr = np.array([m.jnt_dofadr[j] for j in jids])
        self.nominal = np.radians([j["nominal_deg"] for j in spec["joints"]])
        self.lo = np.array([np.radians(j["range_deg"][0]) for j in spec["joints"]])
        self.hi = np.array([np.radians(j["range_deg"][1]) for j in spec["joints"]])
        self.half = 0.5 * (self.hi - self.lo)
        # Actuators are created in joint order; assert so ctrl can be written by joint index.
        for i, n in enumerate(self.joint_names):
            assert mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) == n
        self.pelvis = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
        self.ball = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "ball")
        self.root_q = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
        self.root_v = m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
        self.ball_q = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "ball")]
        self.ball_v = m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "ball")]
        self.palm_l = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "palm_l")
        self.palm_r = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "palm_r")
        self.foot_geom = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "foot_l"),
                          mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "foot_r")]
        self.floor_geom = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "floor")

    def action_to_ctrl(self, action: np.ndarray) -> np.ndarray:
        return np.clip(self.nominal + action * self.half, self.lo, self.hi)


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    """MuJoCo (w,x,y,z) -> 3x3 rotation matrix (world <- body)."""
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def heading_mat(q: np.ndarray) -> np.ndarray:
    """Yaw-only rotation matrix (world <- heading) from a pelvis quaternion."""
    R = quat_to_mat(q)
    fwd = R[:, 0].copy()
    fwd[2] = 0.0
    n = np.linalg.norm(fwd)
    if n < 1e-6:                      # pelvis pointing straight up/down: fall back to +X
        fwd = np.array([1.0, 0.0, 0.0])
    else:
        fwd /= n
    left = np.array([-fwd[1], fwd[0], 0.0])
    return np.column_stack([fwd, left, [0.0, 0.0, 1.0]])


def compute_obs(m: mujoco.MjModel, d: mujoco.MjData, ix: ObsIndex, prev_action: np.ndarray,
                task: np.ndarray, in_control: float, countdown_frac: float,
                out: np.ndarray | None = None) -> np.ndarray:
    """Reference (single-env, numpy) observation. mj_forward must have been called."""
    if out is None:
        out = np.zeros(N_OBS)
    q = d.qpos[ix.root_q + 3:ix.root_q + 7]
    R = quat_to_mat(q)                       # world <- pelvis
    H = heading_mat(q)                       # world <- heading
    p_pelvis = d.qpos[ix.root_q:ix.root_q + 3]
    v_pelvis = d.qvel[ix.root_v:ix.root_v + 3]          # world linear velocity (free joint dofs are world-frame)
    w_pelvis = d.qvel[ix.root_v + 3:ix.root_v + 6]      # free joint angular velocity is in the *body* frame

    out[0:3] = R.T @ np.array([0.0, 0.0, -1.0])
    out[3:6] = R.T @ v_pelvis
    out[6:9] = 0.25 * w_pelvis
    out[9:36] = d.qpos[ix.qadr] - ix.nominal
    out[36:63] = 0.1 * d.qvel[ix.vadr]
    out[63:90] = prev_action

    p_ball = d.qpos[ix.ball_q:ix.ball_q + 3]
    v_ball = d.qvel[ix.ball_v:ix.ball_v + 3]
    w_ball = d.qvel[ix.ball_v + 3:ix.ball_v + 6]        # body frame; for a sphere this is fine as-is
    out[90:93] = H.T @ (p_ball - p_pelvis)
    out[93:96] = 0.5 * (H.T @ (v_ball - v_pelvis))
    out[96] = in_control
    out[97] = np.linalg.norm(d.site_xpos[ix.palm_l] - p_ball)
    out[98] = np.linalg.norm(d.site_xpos[ix.palm_r] - p_ball)
    fl = fr = 0.0
    for c in range(d.ncon):
        g1, g2 = d.contact[c].geom1, d.contact[c].geom2
        if ix.floor_geom in (g1, g2):
            other = g2 if g1 == ix.floor_geom else g1
            if other == ix.foot_geom[0]:
                fl = 1.0
            elif other == ix.foot_geom[1]:
                fr = 1.0
    out[99], out[100] = fl, fr
    out[101] = p_pelvis[2]
    out[102:105] = 0.05 * (H.T @ w_ball)
    out[105] = countdown_frac
    out[106] = 0.0
    out[107:119] = task
    return out


def write_spec_and_golden(n_samples: int = 1000, seed: int = 0) -> None:
    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    ix = ObsIndex(m)
    spec = {
        "n_obs": N_OBS, "n_action": N_JOINTS, "n_task": N_TASK,
        "slots": [{"name": n, "start": s, "size": k, "scale": sc} for n, s, k, sc in SLOTS],
        "joint_order": ix.joint_names,
        "nominal_rad": ix.nominal.tolist(), "lo_rad": ix.lo.tolist(), "hi_rad": ix.hi.tolist(),
        "action_rule": "ctrl = clip(nominal + a * 0.5*(hi-lo), lo, hi)",
        "frames": {
            "pelvis": "full pelvis orientation; gravity/linvel expressed as R^T v",
            "heading": "yaw-only pelvis frame: fwd = R[:,0] with z zeroed and normalised, left = z x fwd",
            "angvel_note": "MuJoCo free-joint qvel[3:6] is already in the body frame; used directly",
        },
        "ball_in_control_rule": "ball within 0.75 m horizontally of pelvis AND ball z < 1.3 m AND last palm contact < 0.6 s ago",
        "foot_contact_rule": "any active contact between geom foot_l/foot_r and geom floor",
    }
    SHARED.mkdir(parents=True, exist_ok=True)
    (SHARED / "obs_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")

    rng = np.random.default_rng(seed)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    qpos = np.empty((n_samples, m.nq)); qvel = np.empty((n_samples, m.nv))
    prev = np.empty((n_samples, N_JOINTS)); task = np.empty((n_samples, N_TASK))
    flags = np.empty((n_samples, 2)); obs = np.empty((n_samples, N_OBS))
    for i in range(n_samples):
        mujoco.mj_resetDataKeyframe(m, d, key)
        d.qpos[ix.root_q:ix.root_q + 3] += rng.normal(0, [1.0, 1.0, 0.1])
        qr = rng.normal(size=4); d.qpos[ix.root_q + 3:ix.root_q + 7] = qr / np.linalg.norm(qr)
        d.qpos[ix.qadr] = rng.uniform(ix.lo, ix.hi)
        d.qpos[ix.ball_q:ix.ball_q + 3] = d.qpos[ix.root_q:ix.root_q + 3] + rng.normal(0, [0.6, 0.6, 0.5])
        d.qpos[ix.ball_q + 2] = max(0.1205, d.qpos[ix.ball_q + 2])
        d.qvel[:] = rng.normal(0, 1.0, m.nv)
        # some samples with feet on the floor so contact flags are exercised
        if i % 3 == 0:
            d.qpos[ix.root_q + 3:ix.root_q + 7] = [1, 0, 0, 0]
            d.qpos[ix.qadr] = ix.nominal
            d.qpos[ix.root_q:ix.root_q + 3] = [rng.uniform(-10, 10), rng.uniform(-5, 5), m.key_qpos[key][ix.root_q + 2] - 0.002]
        mujoco.mj_forward(m, d)
        prev[i] = rng.uniform(-1, 1, N_JOINTS); task[i] = rng.normal(size=N_TASK)
        flags[i] = [float(rng.integers(0, 2)), rng.uniform(0, 1)]
        qpos[i], qvel[i] = d.qpos, d.qvel
        compute_obs(m, d, ix, prev[i], task[i], flags[i, 0], flags[i, 1], obs[i])
    (SHARED / "golden").mkdir(exist_ok=True)
    np.savez(SHARED / "golden" / "obs_golden.npz", qpos=qpos, qvel=qvel, prev_action=prev, task=task,
             in_control=flags[:, 0], countdown_frac=flags[:, 1], obs=obs)
    nz = (obs[:, 99:101] > 0).mean(axis=0)
    print(f"wrote obs_spec.json and golden/obs_golden.npz ({n_samples} samples; foot contact rate l/r = {nz[0]:.2f}/{nz[1]:.2f})")


if __name__ == "__main__":
    write_spec_and_golden()
