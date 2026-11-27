"""The role interface must reproduce the creature's golden observations and refuse a foreign brain.

The golden is written by ``global/UNITE/tools/role_obs.py`` — the reference implementation this module
must agree with to 1e-5. A checkout without ``global/`` skips instead of inventing a layout.
"""

import json
import pathlib
import types

import numpy as np
import pytest

from streetball import role_obs

CONTRACT = role_obs.CONTRACT_PATH
GOLDEN = role_obs.GOLDEN_PATH
TOLERANCE = 1e-5

pytestmark = pytest.mark.skipif(not role_obs.available(), reason="global/UNITE is not present in this checkout")


@pytest.fixture(scope="module")
def contract():
    return role_obs.load_contract()


@pytest.fixture(scope="module")
def joint_names(contract):
    return [j["name"] for j in contract["morphology"]["joints"]]


@pytest.fixture(scope="module")
def iface(contract, joint_names):
    return role_obs.RoleInterface(contract, joint_names)


def test_layout_is_the_contract(contract, iface):
    assert iface.n_obs == 131 and iface.n_action == 28
    assert tuple(s["name"] for s in contract["observation"]["slots"]) == role_obs.ROLE_SLOTS
    at = 0
    for slot in contract["observation"]["slots"]:
        assert slot["start"] == at
        at += slot["size"]
    assert at == iface.n_obs


@pytest.mark.skipif(not GOLDEN.is_file(), reason="no golden_role_obs.npz for streetball_humanoid")
def test_reproduces_the_golden(contract, joint_names, iface):
    z = np.load(GOLDEN)
    assert str(z["interface_sha256_16"][0]) == contract["hashes"]["interface_sha256_16"]
    index = {n: i for i, n in enumerate(joint_names)}
    worst = 0.0
    for i in range(z["obs"].shape[0]):
        state = role_obs.RoleState(
            q=np.zeros(len(joint_names)),
            dq=np.zeros(len(joint_names)),
            imu_quat=np.asarray(z["pelvis_quat"][i], dtype=np.float64),
            gyro=np.asarray(z["pelvis_angvel"][i], dtype=np.float64),
        )
        for name, value in json.loads(z["joint_pos_json"][i]).items():
            state.q[index[name]] = value
        for name, value in json.loads(z["joint_vel_json"][i]).items():
            state.dq[index[name]] = value
        got = iface.build(
            state,
            np.asarray(z["prev_action"][i], dtype=np.float64),
            np.asarray(z["command"][i], dtype=np.float64),
            t=float(z["gait_phase"][i]) * role_obs.DEFAULT_GAIT_PERIOD_S,
        )
        worst = max(worst, float(np.max(np.abs(got - z["obs"][i]))))
    assert worst <= TOLERANCE, f"max deviation {worst:.3g}"


def test_masked_roles_are_zero(iface):
    state = role_obs.RoleState(
        q=np.full(29, 0.4), dq=np.full(29, 1.0), imu_quat=np.array([1.0, 0, 0, 0]), gyro=np.zeros(3)
    )
    obs = iface.build(state, np.ones(28))
    mask = iface.obs.slice_of(obs, "role_mask")
    assert int(mask.sum()) == 26
    for role in ("head_pitch", "head_yaw"):
        i = iface.roles.index(role)
        for slot in ("joint_pos_rel", "joint_vel", "prev_action"):
            assert iface.obs.slice_of(obs, slot)[i] == 0.0
    assert abs(float(iface.obs.slice_of(obs, "morphology_onehot").sum()) - 1.0) < 1e-6


def test_upright_gravity(iface):
    state = role_obs.RoleState(q=np.zeros(29), dq=np.zeros(29), imu_quat=np.array([1.0, 0, 0, 0]), gyro=np.zeros(3))
    obs = iface.build(state, np.zeros(28))
    assert np.allclose(iface.obs.slice_of(obs, "projected_gravity"), [0, 0, -1], atol=1e-6)


def test_gait_phase_only_when_commanded(iface):
    state = role_obs.RoleState(q=np.zeros(29), dq=np.zeros(29), imu_quat=np.array([1.0, 0, 0, 0]), gyro=np.zeros(3))
    still = iface.build(state, np.zeros(28), (0, 0, 0), t=0.3)
    assert np.array_equal(iface.obs.slice_of(still, "gait_phase"), np.zeros(2))
    moving = iface.build(state, np.zeros(28), (0.5, 0, 0), t=0.0)
    assert np.allclose(iface.obs.slice_of(moving, "gait_phase"), [0.0, 1.0], atol=1e-6)


def test_zero_action_holds_the_nominal_pose(iface):
    q = iface.targets(np.zeros(28))
    assert np.allclose(q, iface.action.q_default)
    assert "lumbar_flex" in iface.action.unmapped_joints


def test_action_is_clipped_to_soft_limits(iface):
    q = iface.targets(np.full(28, 5.0))
    amap = iface.action
    assert np.all(q >= amap.lo - 1e-12) and np.all(q <= amap.hi + 1e-12)
    knee = amap.index["left_knee_joint"] if "left_knee_joint" in amap.index else None
    if knee is not None:
        assert q[knee] != amap.q_default[knee]


def test_gains_come_from_the_contract(contract, iface):
    by_name = {j["name"]: j for j in contract["morphology"]["joints"]}
    for name, joint in by_name.items():
        i = iface.action.index[name]
        assert iface.action.kp[i] == pytest.approx(joint["kp"])
        assert iface.action.kd[i] == pytest.approx(joint["kd"])
        assert iface.action.scale[i] == pytest.approx(joint["action_scale"])


def _fake_policy(tmp_path, contract, *, corrupt=False, name="policy"):
    onnx = tmp_path / f"{name}.onnx"
    onnx.write_bytes(b"stub weights; only the hash is checked at load")
    import hashlib

    sc = {
        "policy_name": name,
        "creature": contract["creature"],
        "n_obs": 131,
        "n_action": 28,
        "interface_sha256": contract["hashes"]["interface_sha256"],
        "morphology_sha256": contract["hashes"]["morphology_sha256"],
        "physics_sha256": contract["hashes"]["physics_sha256"],
        "policy_sha256": hashlib.sha256(onnx.read_bytes()).hexdigest(),
    }
    if corrupt:
        sc["interface_sha256"] = "0" * 64
    onnx.with_suffix(".json").write_text(json.dumps(sc), encoding="utf-8")
    return types.SimpleNamespace(path=onnx, num_obs=131, num_actions=28)


def test_conforming_policy_is_accepted(tmp_path, contract, joint_names):
    nn = _fake_policy(tmp_path, contract)
    assert role_obs.for_policy(nn, joint_names, contract).n_obs == 131


def test_foreign_brain_is_loadable_but_flagged(tmp_path, contract, joint_names):
    """R13: another creature's brain is accepted through a matching interface and marked foreign."""
    nn = _fake_policy(tmp_path, contract, name="foreign")
    sc = json.loads(nn.path.with_suffix(".json").read_text(encoding="utf-8"))
    sc["creature"] = "unitree_r1_a5"
    sc["morphology_sha256"] = "a" * 64
    nn.path.with_suffix(".json").write_text(json.dumps(sc), encoding="utf-8")
    iface = role_obs.for_policy(nn, joint_names, contract)
    assert iface.foreign and iface.trained_for == "unitree_r1_a5"


def test_stale_sidecar_is_refused(tmp_path, contract, joint_names):
    nn = _fake_policy(tmp_path, contract, corrupt=True)
    with pytest.raises(role_obs.ContractMismatch):
        role_obs.for_policy(nn, joint_names, contract)


def test_wrong_shape_is_refused(joint_names, contract):
    nn = types.SimpleNamespace(path=pathlib.Path("nope.onnx"), num_obs=119, num_actions=27)
    with pytest.raises(role_obs.ContractMismatch):
        role_obs.for_policy(nn, joint_names, contract)
