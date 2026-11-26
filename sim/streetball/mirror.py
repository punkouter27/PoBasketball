"""Left/right mirror of observations and actions, for the symmetry loss (ppo.PPOConfig.sym_coef).

Mirror plane: the body's sagittal plane, world/pelvis/heading y -> -y (x forward, y left, z up). A polar vector
(position, velocity, gravity) maps to (x, -y, z); an axial vector (angular velocity) maps to (-x, y, -z).

Joints: each joint maps to its partner (`_l` <-> `_r`, centre-line joints to themselves) times a sign. The sign is read
from the model, not written by hand: the partner's world axis at the `stand` keyframe must equal the mirrored axis
(+1) or its negative (-1). `build()` checks that the pair is symmetric (axes, nominal pose, range), so that the
normalised action and the obs joint slots mirror with that same sign:
    ctrl = nominal + a * half  ->  mirrored a_partner = sign * a.

The task block (12 slots) means something different on every level, so each level declares its own mirror via
`Level.task_mirror()` (None = the level is not left/right symmetric, e.g. right-hand dribbling; the loss is then off).
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

from streetball import obs as obs_spec

AXIS_TOL = 0.98  # |cos| between partner axis and mirrored axis
ANGLE_TOL = 1e-3  # rad, nominal / range symmetry


def partner_name(name: str) -> str:
    if name.endswith("_l"):
        return name[:-2] + "_r"
    if name.endswith("_r"):
        return name[:-2] + "_l"
    return name


def mirror_axial(v: np.ndarray) -> np.ndarray:
    return np.array([-v[0], v[1], -v[2]])


@dataclass
class Mirror:
    """obs' = obs[obs_perm] * obs_sign ; act' = act[act_perm] * act_sign (both involutions)."""

    obs_perm: np.ndarray
    obs_sign: np.ndarray
    act_perm: np.ndarray
    act_sign: np.ndarray

    def obs(self, o: np.ndarray) -> np.ndarray:
        return o[..., self.obs_perm] * self.obs_sign

    def act(self, a: np.ndarray) -> np.ndarray:
        return a[..., self.act_perm] * self.act_sign


def joint_mirror(m: mujoco.MjModel, ix: obs_spec.ObsIndex) -> tuple[np.ndarray, np.ndarray]:
    """(perm, sign) over the obs joint order, checked against the model."""
    d = mujoco.MjData(m)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    mujoco.mj_resetDataKeyframe(m, d, key)
    mujoco.mj_forward(m, d)
    names = ix.joint_names
    perm = np.zeros(len(names), dtype=np.int64)
    sign = np.zeros(len(names))
    for i, n in enumerate(names):
        p = names.index(partner_name(n))
        a_i = d.xaxis[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, n)]
        a_p = d.xaxis[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, names[p])]
        c = float(np.dot(mirror_axial(a_i), a_p))
        if abs(c) < AXIS_TOL:
            raise ValueError(f"{n} -> {names[p]}: axes are not mirror images (cos {c:.3f})")
        s = 1.0 if c > 0 else -1.0
        if abs(s * ix.nominal[i] - ix.nominal[p]) > ANGLE_TOL:
            raise ValueError(f"{n} -> {names[p]}: nominal pose not symmetric")
        lo, hi = (ix.lo[i], ix.hi[i]) if s > 0 else (-ix.hi[i], -ix.lo[i])
        if abs(lo - ix.lo[p]) > ANGLE_TOL or abs(hi - ix.hi[p]) > ANGLE_TOL:
            raise ValueError(f"{n} -> {names[p]}: joint range not symmetric")
        perm[i], sign[i] = p, s
    return perm, sign


def build(m: mujoco.MjModel, ix: obs_spec.ObsIndex, task_perm=None, task_sign=None) -> Mirror:
    """Full obs/action mirror. task_perm/task_sign: the level's 12-slot task mirror (identity when None)."""
    n = obs_spec.N_OBS
    perm = np.arange(n)
    sign = np.ones(n)
    polar = np.array([1.0, -1.0, 1.0])
    axial = np.array([-1.0, 1.0, -1.0])
    sign[0:3] = polar  # gravity, pelvis frame
    sign[3:6] = polar  # pelvis linear velocity
    sign[6:9] = axial  # pelvis angular velocity
    jp, js = joint_mirror(m, ix)
    for start in (obs_spec._S_JPOS, obs_spec._S_JVEL, obs_spec._S_ACT):
        perm[start : start + obs_spec.N_JOINTS] = start + jp
        sign[start : start + obs_spec.N_JOINTS] = js
    b = obs_spec._S_BALL
    sign[b : b + 3] = polar  # ball position, heading frame
    sign[b + 3 : b + 6] = polar  # ball velocity
    perm[b + 7], perm[b + 8] = b + 8, b + 7  # palm_l/palm_r distance
    perm[b + 9], perm[b + 10] = b + 10, b + 9  # foot_l/foot_r contact
    sign[b + 12 : b + 15] = axial  # ball angular velocity
    if task_perm is not None:
        perm[obs_spec.N_BASE :] = obs_spec.N_BASE + np.asarray(task_perm)
    if task_sign is not None:
        sign[obs_spec.N_BASE :] = np.asarray(task_sign, dtype=float)
    return Mirror(perm, sign, jp, js)


def mirror_state(m: mujoco.MjModel, ix: obs_spec.ObsIndex, d: mujoco.MjData, out: mujoco.MjData) -> None:
    """Write the mirror image of d's humanoid + ball state into out (for tests). mj_forward is left to the caller."""
    jp, js = joint_mirror(m, ix)
    out.qpos[:] = d.qpos
    out.qvel[:] = d.qvel
    for fq, fv in ((ix.root_q, ix.root_v), (ix.ball_q, ix.ball_v)):
        out.qpos[fq + 1] = -d.qpos[fq + 1]
        w, x, y, z = d.qpos[fq + 3 : fq + 7]
        out.qpos[fq + 3 : fq + 7] = (w, -x, y, -z)  # reflection y -> -y conjugates the rotation
        out.qvel[fv + 1] = -d.qvel[fv + 1]  # world linear velocity: polar
        out.qvel[fv + 3 : fv + 6] = mirror_axial(d.qvel[fv + 3 : fv + 6])  # body-frame angular velocity
    out.qpos[ix.qadr[jp]] = js * d.qpos[ix.qadr]
    out.qvel[ix.vadr[jp]] = js * d.qvel[ix.vadr]
