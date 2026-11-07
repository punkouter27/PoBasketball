"""A3 acceptance tests for the generated humanoid model.

A joint-level PD alone cannot balance an 80 kg, 1 m-high centre of mass:
gravity's destabilising stiffness m*g*h is about 800 N*m/rad versus the
200 N*m/rad ankle gain, so free standing is the job of the L0 policy. These
tests check what PD *can* guarantee: the model is well-formed, joints track
their targets, and the feet carry the body weight without any solver blow-up.
"""
import pathlib

import mujoco
import numpy as np

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
D2R = np.pi / 180.0


def _load():
    m = mujoco.MjModel.from_xml_path(str(ASSETS / "scene.xml"))
    d = mujoco.MjData(m)
    return m, d


def _root_adr(m):
    return m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]


def _actuated_joint_qpos(m, d):
    out = np.empty(m.nu)
    for i in range(m.nu):
        out[i] = d.qpos[m.jnt_qposadr[m.actuator_trnid[i, 0]]]
    return out


def test_model_shape_and_mass():
    m, d = _load()
    assert m.nu == 27
    assert m.nq == 7 + 7 + 27 and m.nv == 6 + 6 + 27
    hum = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    mujoco.mj_forward(m, d)
    assert abs(m.body_subtreemass[hum] - 80.0) < 0.5


def test_feet_on_floor_at_keyframe():
    m, d = _load()
    mujoco.mj_resetDataKeyframe(m, d, 0)
    mujoco.mj_forward(m, d)
    zs = [d.site_xpos[i][2] for i in range(m.nsite)
          if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SITE, i) or "").startswith("foot_")]
    assert len(zs) == 8
    assert abs(min(zs)) < 2e-3


def test_pd_tracks_targets_without_gravity():
    m, d = _load()
    m.opt.gravity[:] = 0.0
    mujoco.mj_resetData(m, d)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    d.ctrl[:] = m.key_ctrl[key]
    for _ in range(int(1.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    err = np.abs(_actuated_joint_qpos(m, d) - d.ctrl) / D2R
    assert np.all(np.isfinite(d.qpos))
    assert err.max() < 2.0, f"max tracking error {err.max():.2f} deg"


def test_feet_carry_weight():
    m, d = _load()
    mujoco.mj_resetDataKeyframe(m, d, 0)
    pelvis = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    weight = m.body_subtreemass[pelvis] * 9.81
    f = np.zeros(6)
    fz = []
    for i in range(int(0.5 / m.opt.timestep)):
        mujoco.mj_step(m, d)
        if i > 50:                       # after the initial settling transient
            total = 0.0
            for c in range(d.ncon):
                con = d.contact[c]
                g1 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, con.geom1)
                g2 = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, con.geom2)
                if "foot" in (g1 or "") or "foot" in (g2 or ""):
                    mujoco.mj_contactForce(m, d, c, f)
                    total += f[0]        # normal force in contact frame
            fz.append(total)
    fz = np.array(fz)
    assert np.all(np.isfinite(d.qpos))
    up = d.xmat[pelvis].reshape(3, 3)[2, 2]
    assert up > 0.95, "fell within 0.5 s"
    assert abs(fz.mean() - weight) / weight < 0.15, f"mean foot normal force {fz.mean():.0f} N vs weight {weight:.0f} N"
