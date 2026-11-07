"""UU_AGENT section 2: primitive colliders, non-adjacent parts collide, zero penetration at rest,
at joint limits and through motion.

"Zero penetration" for a soft-contact simulator means no geometric overlap in static poses
(rest pose, every joint at either limit) between any pair that is allowed to collide, and
bounded contact depth (<= 1 cm) while moving under random actions at 500 Hz.
"""
import pathlib

import mujoco
import numpy as np
import pytest

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
MOTION_DEPTH_LIMIT = 0.010   # m, dynamic (soft contact) tolerance
STATIC_DEPTH_LIMIT = 0.002   # m, geometric overlap tolerance in static poses


def _model():
    m = mujoco.MjModel.from_xml_path(str(ASSETS / "scene.xml"))
    return m, mujoco.MjData(m)


def _hum_geoms(m):
    pelvis = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    hum_bodies = set()
    for b in range(m.nbody):
        r = b
        while r not in (0, pelvis):
            r = m.body_parentid[r]
        if r == pelvis:
            hum_bodies.add(b)
    return {g for g in range(m.ngeom) if m.geom_bodyid[g] in hum_bodies}


def _self_contacts(m, d, hum):
    out = []
    for c in range(d.ncon):
        con = d.contact[c]
        if con.geom1 in hum and con.geom2 in hum:
            out.append((mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, con.geom1),
                        mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, con.geom2), float(con.dist)))
    return out


def test_primitive_colliders_only():
    m, _ = _model()
    allowed = {mujoco.mjtGeom.mjGEOM_CAPSULE, mujoco.mjtGeom.mjGEOM_SPHERE, mujoco.mjtGeom.mjGEOM_BOX, mujoco.mjtGeom.mjGEOM_PLANE}
    bad = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) for g in range(m.ngeom) if m.geom_type[g] not in allowed]
    assert not bad, f"non-primitive geoms: {bad}"


def test_non_adjacent_parts_collide():
    """Siblings must be allowed to collide: force the two calves together and expect a contact."""
    m, d = _model()
    hum = _hum_geoms(m)
    mujoco.mj_resetDataKeyframe(m, d, 0)
    for s in "lr":
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"hip_abd_{s}")
        d.qpos[m.jnt_qposadr[j]] = np.radians(-30.0)       # adduct both legs toward each other
    mujoco.mj_forward(m, d)
    pairs = {tuple(sorted(p[:2])) for p in _self_contacts(m, d, hum)}
    assert ("calf_l", "calf_r") in pairs or ("thigh_l", "thigh_r") in pairs, f"legs crossed without a contact: {pairs}"


def test_no_overlap_at_rest():
    m, d = _model()
    hum = _hum_geoms(m)
    mujoco.mj_resetDataKeyframe(m, d, 0)
    mujoco.mj_forward(m, d)
    worst = min([p[2] for p in _self_contacts(m, d, hum)] + [0.0])
    assert worst > -STATIC_DEPTH_LIMIT, f"self overlap at rest: {_self_contacts(m, d, hum)}"
    for _ in range(500):
        mujoco.mj_step(m, d)
    depth = min([float(d.contact[c].dist) for c in range(d.ncon)] + [0.0])
    assert depth > -MOTION_DEPTH_LIMIT, f"contact depth after settling {depth*1000:.1f} mm"


def test_no_overlap_at_joint_limits():
    m, d = _model()
    hum = _hum_geoms(m)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    offenders = []
    for i in range(m.nu):
        j = m.actuator_trnid[i, 0]
        for k, lim in enumerate(m.jnt_range[j]):
            mujoco.mj_resetDataKeyframe(m, d, key)
            d.qpos[m.jnt_qposadr[j]] = lim
            mujoco.mj_forward(m, d)
            for g1, g2, dist in _self_contacts(m, d, hum):
                if dist < -STATIC_DEPTH_LIMIT:
                    offenders.append((mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j), "lo" if k == 0 else "hi", g1, g2, round(dist * 1000, 1)))
    assert not offenders, "overlap at joint limits (joint, end, geom1, geom2, mm): " + str(offenders)


@pytest.mark.parametrize("seed", [0, 1])
def test_bounded_depth_through_motion(seed):
    """Random smooth PD targets for 4 s: every active contact stays shallower than 1 cm."""
    m, d = _model()
    rng = np.random.default_rng(seed)
    mujoco.mj_resetDataKeyframe(m, d, 0)
    lo, hi = m.actuator_ctrlrange[:, 0], m.actuator_ctrlrange[:, 1]
    nominal = m.key_ctrl[0].copy()
    a = np.zeros(m.nu)
    worst = 0.0
    worst_pair = None
    for t in range(200):
        a = 0.9 * a + 0.1 * rng.uniform(-1, 1, m.nu)
        d.ctrl[:] = np.clip(nominal + 0.6 * 0.5 * (hi - lo) * a, lo, hi)
        for _ in range(10):
            mujoco.mj_step(m, d)
            for c in range(d.ncon):
                if d.contact[c].dist < worst:
                    worst = float(d.contact[c].dist)
                    worst_pair = (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, d.contact[c].geom1),
                                  mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, d.contact[c].geom2))
    assert worst > -MOTION_DEPTH_LIMIT, f"deepest contact {worst*1000:.1f} mm between {worst_pair}"
