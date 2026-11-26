"""The left/right mirror (streetball/mirror.py) matches the physics: obs(mirrored state) == mirror(obs(state))."""

import pathlib

import mujoco
import numpy as np

from streetball import mirror as mr
from streetball import obs as obs_spec

SCENE = pathlib.Path(__file__).resolve().parents[1] / "assets" / "scene.xml"


def _model():
    m = mujoco.MjModel.from_xml_path(str(SCENE))
    return m, obs_spec.ObsIndex(m)


def test_mirror_is_an_involution():
    m, ix = _model()
    M = mr.build(m, ix)
    x = np.random.default_rng(1).normal(size=obs_spec.N_OBS)
    a = np.random.default_rng(2).normal(size=obs_spec.N_JOINTS)
    np.testing.assert_allclose(M.obs(M.obs(x)), x)
    np.testing.assert_allclose(M.act(M.act(a)), a)


def test_lateral_joints_flip_sign():
    m, ix = _model()
    _, sign = mr.joint_mirror(m, ix)
    flipped = {n for n, s in zip(ix.joint_names, sign) if s < 0}
    assert flipped == {"wrist_dev_l", "wrist_dev_r", "ankle_roll_l", "ankle_roll_r", "lumbar_lat", "lumbar_twist"}


def test_obs_of_mirrored_state_is_mirrored_obs():
    m, ix = _model()
    M = mr.build(m, ix)
    rng = np.random.default_rng(0)
    d, d2 = mujoco.MjData(m), mujoco.MjData(m)
    for _ in range(20):
        mujoco.mj_resetDataKeyframe(m, d, 0)
        d.qpos[ix.qadr] = np.clip(ix.nominal + rng.normal(0, 0.3, obs_spec.N_JOINTS), ix.lo, ix.hi)
        d.qvel[:] = rng.normal(0, 1, m.nv)
        q = rng.normal(size=4)
        d.qpos[ix.root_q + 3 : ix.root_q + 7] = q / np.linalg.norm(q)
        d.qpos[ix.root_q : ix.root_q + 2] = rng.normal(size=2)
        d.qpos[ix.ball_q : ix.ball_q + 3] += rng.normal(0, 0.3, 3)
        mujoco.mj_forward(m, d)
        mr.mirror_state(m, ix, d, d2)
        mujoco.mj_forward(m, d2)
        a = rng.uniform(-1, 1, obs_spec.N_JOINTS)
        task = np.zeros(obs_spec.N_TASK)
        o1 = obs_spec.compute_obs(m, d, ix, a, task, 1.0, 1.0)
        o2 = obs_spec.compute_obs(m, d2, ix, M.act(a), task, 1.0, 1.0)
        err = np.abs(M.obs(o1) - o2)
        b = obs_spec._S_BALL
        err[b + 9 : b + 11] = 0.0  # foot contacts: a random pose may graze the floor on one side only
        assert err.max() < 1e-4, (int(err.argmax()), float(err.max()))
