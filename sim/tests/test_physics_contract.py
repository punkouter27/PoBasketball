"""Po Game Standard (articulated agents): Earth gravity, joint limits, PD actuators, no collision between connected
bones, ground friction. Checked on the compiled scene the trainer and Unreal both load (sim/assets/scene.xml).

Gaze tracking is not here: the body has no neck/head joint (owner decision pending, AGENTS.md)."""

import pathlib

import mujoco
import numpy as np

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"


def _model():
    return mujoco.MjModel.from_xml_path(str(ASSETS / "scene.xml"))


def test_earth_gravity():
    m = _model()
    assert np.allclose(m.opt.gravity, [0.0, 0.0, -9.81])


def test_every_hinge_has_joint_limits():
    m = _model()
    hinges = [j for j in range(m.njnt) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE]
    assert len(hinges) >= 29
    for j in hinges:
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j)
        lo, hi = m.jnt_range[j]
        assert m.jnt_limited[j], f"{name} has no limits"
        assert lo < hi and hi - lo < 2 * np.pi, f"{name} range {lo:.2f}..{hi:.2f}"


def test_actuators_are_pd_with_torque_limits():
    m = _model()
    assert m.nu == 29
    for a in range(m.nu):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, a)
        kp = m.actuator_gainprm[a, 0]
        # position actuator: force = kp * ctrl - kp * q - kv * qdot  (biasprm = [0, -kp, -kv])
        assert m.actuator_gaintype[a] == mujoco.mjtGain.mjGAIN_FIXED and kp > 0, name
        assert m.actuator_biastype[a] == mujoco.mjtBias.mjBIAS_AFFINE, name
        assert np.isclose(m.actuator_biasprm[a, 1], -kp) and m.actuator_biasprm[a, 2] < 0, f"{name}: no D term"
        assert m.actuator_forcelimited[a] and m.actuator_forcerange[a, 1] > 0, f"{name}: no torque limit"


def test_connected_bones_do_not_collide():
    m = _model()
    # MuJoCo filters parent-child contacts unless the filterparent flag is disabled
    assert not (m.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_FILTERPARENT)


def test_ground_has_friction():
    m = _model()
    floor = [g for g in range(m.ngeom) if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE]
    assert floor, "no ground plane"
    for g in floor:
        assert m.geom_friction[g, 0] >= 0.5 and m.geom_contype[g] and m.geom_conaffinity[g]
