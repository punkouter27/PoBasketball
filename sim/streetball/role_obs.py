"""The role-ordered interface for this app: 131 observations in, 28 role actions out.

RULES.md R6-R8/R13/R14 in ``PoPunkouterSoftware/docs/unite/RULES.md``. This is the basketball half of the same
contract PoRobotTrain implements: the layout, the mask, the defaults, the gains and the action
scales all come from ``PoPunkouterSoftware/docs/unite/creatures/streetball_humanoid/contract.json``, so a brain
trained anywhere against that interface can be driven here without re-deriving what float 87 means.

It deliberately does **not** replace ``obs.py``. That 119-float layout is this game's task
observation (ball position, palm distance, contact flags, level task block) and the trainer, the
UE plugin and the web twin all speak it. This module is the *portable* view of the same body:

    RoleInterface.build(state, prev_action, command, t)  ->  131 floats, role ordered
    RoleInterface.targets(action)                        ->  29 joint targets, gaps PD-held

The two are different questions. "Can this body be driven by a shared brain?" is answered here;
"what does the ball look like right now?" stays in ``obs.py``.

Every implementation must reproduce the creature's ``golden_role_obs.npz`` to 1e-5 — the reference
builder in ``PoPunkouterSoftware/docs/unite/tools/role_obs.py`` is the authority, this file is one implementation of
it, and ``sim/tests/test_role_obs.py`` is the proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from streetball.obs import quat_to_mat

ROLE_SLOTS = (
    "joint_pos_rel",
    "joint_vel",
    "prev_action",
    "base_ang_vel",
    "projected_gravity",
    "velocity_commands",
    "gait_phase",
    "role_mask",
    "morphology_onehot",
)
CREATURE = "streetball_humanoid"
DEFAULT_GAIT_PERIOD_S = 0.8
MOVING_COMMAND_THRESHOLD = 0.1

UNITE = pathlib.Path(__file__).resolve().parents[3] / "PoPunkouterSoftware" / "docs" / "unite"
CONTRACT_PATH = UNITE / "creatures" / CREATURE / "contract.json"
GOLDEN_PATH = UNITE / "creatures" / CREATURE / "golden_role_obs.npz"


class ContractMismatch(RuntimeError):
    """The policy does not match the contract it would drive (R14): refuse, never degrade."""


@dataclass
class RoleState:
    """The five inputs the universal observation needs, in this app's joint order."""

    q: np.ndarray  # joint positions, len(joint_names)
    dq: np.ndarray  # joint velocities, len(joint_names)
    imu_quat: np.ndarray  # (w, x, y, z), root body in world
    gyro: np.ndarray  # body-frame angular velocity, (3,)

    @classmethod
    def from_mjdata(cls, d, qadr: np.ndarray, vadr: np.ndarray, root_q: int, root_v: int) -> RoleState:
        return cls(
            q=np.asarray(d.qpos[qadr], dtype=np.float64).copy(),
            dq=np.asarray(d.qvel[vadr], dtype=np.float64).copy(),
            imu_quat=np.asarray(d.qpos[root_q + 3 : root_q + 7], dtype=np.float64).copy(),
            gyro=np.asarray(d.qvel[root_v + 3 : root_v + 6], dtype=np.float64).copy(),
        )


def available() -> bool:
    """False on a checkout without ``PoPunkouterSoftware/docs/unite`` (CI, a fresh clone)."""
    return CONTRACT_PATH.is_file()


def load_contract() -> dict:
    if not available():
        raise ContractMismatch(f"no contract at {CONTRACT_PATH}; the role interface needs PoPunkouterSoftware/docs/unite")
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def projected_gravity(quat: Sequence[float]) -> np.ndarray:
    """World gravity (0, 0, -1) in the body frame: ``R^T g``."""
    return quat_to_mat(np.asarray(quat, dtype=np.float64)).T @ np.array([0.0, 0.0, -1.0])


class RoleObs:
    """131 floats, role ordered, zero where this body has no joint for a role (R6)."""

    def __init__(self, contract: dict, joint_names: Sequence[str]):
        roles = contract["roles"]["canonical_order"]
        self.roles: list[str] = list(roles)
        self.n_roles = len(self.roles)
        self.mask = np.asarray(contract["roles"]["mask"], dtype=np.float32)
        self.slots = {
            s["name"]: (int(s["start"]), int(s["size"]), float(s["scale"])) for s in contract["observation"]["slots"]
        }
        self.n_obs = int(contract["observation"]["n_obs"])
        self.onehot_size = int(contract["roles"].get("morphology_onehot_size", 8))
        self.morphology_id = int(contract["roles"].get("morphology_id", 0))
        self.joint_index: dict[str, int] = {n: i for i, n in enumerate(joint_names)}

        self.joint_of_role: dict[str, int] = {}
        self.default_of_role = np.zeros(self.n_roles, dtype=np.float64)
        for j in contract["morphology"]["joints"]:
            role = j.get("role")
            i = self.joint_index.get(j["name"])
            if role in self.roles and i is not None:
                self.joint_of_role[role] = i
                self.default_of_role[self.roles.index(role)] = float(j.get("default") or 0.0)

        missing = [n for n in ROLE_SLOTS if n not in self.slots]
        if missing:
            raise ValueError(f"contract is missing observation slots {missing}")
        self.obs = np.zeros(self.n_obs, dtype=np.float32)

    def slice_of(self, obs: np.ndarray, name: str) -> np.ndarray:
        start, size, _ = self.slots[name]
        return obs[start : start + size]

    def build(
        self,
        state: RoleState,
        prev_action: np.ndarray,
        command: Sequence[float] | None = None,
        t: float = 0.0,
        gait_period_s: float = DEFAULT_GAIT_PERIOD_S,
    ) -> np.ndarray:
        obs = self.obs
        pos = np.zeros(self.n_roles, dtype=np.float64)
        vel = np.zeros(self.n_roles, dtype=np.float64)
        act = np.zeros(self.n_roles, dtype=np.float64)
        prev = np.asarray(prev_action, dtype=np.float64).reshape(-1)

        for i, role in enumerate(self.roles):
            if self.mask[i] == 0:
                continue
            j = self.joint_of_role.get(role)
            if j is None:
                continue
            pos[i] = float(state.q[j]) - self.default_of_role[i]
            vel[i] = float(state.dq[j])
            if i < prev.shape[0]:
                act[i] = prev[i]

        cmd = np.zeros(3, dtype=np.float64)
        if command is not None:
            c = np.asarray(command, dtype=np.float64).reshape(-1)
            cmd[: min(3, c.shape[0])] = c[:3]
        if float(np.linalg.norm(cmd)) >= MOVING_COMMAND_THRESHOLD:
            phase = (t / float(gait_period_s)) % 1.0
            gait = np.array([math.sin(2.0 * math.pi * phase), math.cos(2.0 * math.pi * phase)])
        else:
            gait = np.zeros(2)

        onehot = np.zeros(self.onehot_size, dtype=np.float64)
        if 0 <= self.morphology_id < self.onehot_size:
            onehot[self.morphology_id] = 1.0

        blocks = {
            "joint_pos_rel": pos,
            "joint_vel": vel,
            "prev_action": act,
            "base_ang_vel": np.asarray(state.gyro, dtype=np.float64).reshape(3),
            "projected_gravity": projected_gravity(state.imu_quat),
            "velocity_commands": cmd,
            "gait_phase": gait,
            "role_mask": self.mask,
            "morphology_onehot": onehot,
        }
        for name, values in blocks.items():
            start, size, scale = self.slots[name]
            if len(values) != size:
                raise ValueError(f"slot {name}: built {len(values)} values, contract says {size}")
            obs[start : start + size] = np.asarray(values, dtype=np.float64) * scale
        return obs


class RoleActionMap:
    """28 role actions -> joint targets, with the contract's gains (R7, layer 6).

    Joints this body has but no role drives (``lumbar_flex`` here) are held at their contract
    default; masked roles are held the same way and are never driven by the policy.
    """

    def __init__(self, contract: dict, joint_names: Sequence[str]):
        self.roles: list[str] = list(contract["roles"]["canonical_order"])
        self.mask = np.asarray(contract["roles"]["mask"], dtype=np.float64)
        self.n_roles = len(self.roles)
        self.joint_names = list(joint_names)
        self.index: dict[str, int] = {n: i for i, n in enumerate(self.joint_names)}
        self.n_joints = len(self.joint_names)

        factor = float(contract["action"].get("soft_limit_factor", 0.9))
        self.q_default = np.zeros(self.n_joints, dtype=np.float64)
        self.kp = np.zeros(self.n_joints, dtype=np.float64)
        self.kd = np.zeros(self.n_joints, dtype=np.float64)
        self.scale = np.zeros(self.n_joints, dtype=np.float64)
        self.lo = np.zeros(self.n_joints, dtype=np.float64)
        self.hi = np.zeros(self.n_joints, dtype=np.float64)

        self.joint_of_role: dict[str, int] = {}
        for j in contract["morphology"]["joints"]:
            i = self.index.get(j["name"])
            if i is None:
                continue
            self.q_default[i] = float(j.get("default") or 0.0)
            self.kp[i] = float(j.get("kp") or 0.0)
            self.kd[i] = float(j.get("kd") or 0.0)
            self.scale[i] = float(j.get("action_scale") or 0.0)
            lo, hi = (float(x) for x in j["range"])
            pad = (1.0 - factor) * 0.5 * (hi - lo)
            self.lo[i] = lo + pad
            self.hi[i] = hi - pad
            role = j.get("role")
            if role in self.roles:
                self.joint_of_role[role] = i

    @property
    def unmapped_joints(self) -> list[str]:
        driven = set(self.joint_of_role.values())
        return [n for i, n in enumerate(self.joint_names) if i not in driven]

    def targets(self, action: np.ndarray) -> np.ndarray:
        a = np.asarray(action, dtype=np.float64).reshape(-1)
        if a.shape[0] != self.n_roles:
            raise ValueError(f"action has {a.shape[0]} values, the role interface wants {self.n_roles}")
        q = self.q_default.copy()
        for i, role in enumerate(self.roles):
            j = self.joint_of_role.get(role)
            if j is None or self.mask[i] == 0:
                continue
            q[j] = min(max(self.q_default[j] + a[i] * self.scale[j], self.lo[j]), self.hi[j])
        return q


class RoleInterface:
    """Both halves plus gains, for a runner that speaks the universal interface."""

    def __init__(self, contract: dict, joint_names: Sequence[str]):
        self.contract = contract
        self.obs = RoleObs(contract, joint_names)
        self.action = RoleActionMap(contract, joint_names)
        self.n_obs = self.obs.n_obs
        self.n_action = self.obs.n_roles
        self.roles = self.obs.roles
        self.mask = self.obs.mask
        self.kp = self.action.kp.copy()
        self.kd = self.action.kd.copy()
        self.foreign = False
        self.trained_for: str | None = None
        if self.n_action != int(contract["action"]["n_action"]):
            raise ValueError(
                f"contract roles ({self.n_action}) disagree with action.n_action ({contract['action']['n_action']})"
            )

    def build(self, state: RoleState, prev_action, command=None, t: float = 0.0) -> np.ndarray:
        return self.obs.build(state, prev_action, command, t)

    def targets(self, action: np.ndarray) -> np.ndarray:
        return self.action.targets(action)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar_problems(policy_path: str | pathlib.Path, contract: dict, *, foreign: bool = False) -> list[str]:
    """What a runtime checks before trusting a brain (R10/R14). Empty list = loadable.

    ``foreign=True`` is R13: a brain trained for another body may be driven here when the *interface*
    hash matches (all six creatures publish one layout). Its morphology and physics hashes describing
    a different body is not a defect — it is a loadable-but-not-correct brain, and the caller labels it.
    """
    path = pathlib.Path(policy_path)
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        return [f"{path.name} has no sidecar ({sidecar.name}); R10 requires one beside every onnx"]
    sc = json.loads(sidecar.read_text(encoding="utf-8"))
    problems: list[str] = []
    for key in ("interface_sha256", "morphology_sha256", "physics_sha256", "policy_sha256"):
        if not sc.get(key):
            problems.append(f"sidecar is missing {key}")
    keys = ("interface_sha256",) if foreign else ("interface_sha256", "morphology_sha256", "physics_sha256")
    for key in keys:
        want = contract["hashes"][key]
        got = sc.get(key)
        if got and got != want:
            problems.append(f"sidecar {key} = {str(got)[:16]}... but this creature's contract has {want[:16]}...")
    if sc.get("policy_sha256") and sc["policy_sha256"] != _sha256(path):
        problems.append("policy_sha256 does not match the onnx; the file changed after the sidecar was written")
    if int(sc.get("n_obs", -1)) != int(contract["observation"]["n_obs"]):
        problems.append(f"sidecar n_obs {sc.get('n_obs')} != contract {contract['observation']['n_obs']}")
    if int(sc.get("n_action", -1)) != int(contract["action"]["n_action"]):
        problems.append(f"sidecar n_action {sc.get('n_action')} != contract {contract['action']['n_action']}")
    return problems


def for_policy(nn, joint_names: Sequence[str], contract: dict | None = None) -> RoleInterface:
    """Build the interface for a conforming ONNX, or raise: this path does not degrade (R14).

    A brain trained for a different creature is accepted when the interface hash matches (R13) and is
    marked ``foreign``: loadable here, correct only on the body it was trained for.
    """
    c = contract if contract is not None else load_contract()
    want = (int(c["observation"]["n_obs"]), int(c["action"]["n_action"]))
    if (int(nn.num_obs), int(nn.num_actions)) != want:
        raise ContractMismatch(
            f"policy io {nn.num_obs}->{nn.num_actions} is not the role interface {want[0]}->{want[1]}"
        )
    sc_path = pathlib.Path(nn.path).with_suffix(".json")
    sc = json.loads(sc_path.read_text(encoding="utf-8")) if sc_path.is_file() else {}
    foreign = bool(sc.get("creature")) and sc.get("creature") != c["creature"]
    problems = sidecar_problems(nn.path, c, foreign=foreign)
    if problems:
        raise ContractMismatch(f"role policy refused: {problems[0]}")
    iface = RoleInterface(c, joint_names)
    iface.foreign = foreign
    iface.trained_for = sc.get("creature")
    return iface
