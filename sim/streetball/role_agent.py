"""Play a portable UNITE brain on this app's own court (131 observations -> 28 role actions).

    uv run python -m streetball.role_agent --policy ..\\global\\UNITE\\runs\\ppo-r1-edu-stand
    uv run python -m streetball.role_agent --policy <dir> --steps 500 --command 0.3,0,0 --json out.json

This is the consumer side of the role interface: it builds the 131 floats from the MuJoCo scene
``sim/assets/scene.xml`` (the same model the trainer and the Unreal twin load), refuses a policy whose
sidecar does not match ``creatures/streetball_humanoid/contract.json``, and maps the 28 actions onto
this body's 29 joints.

It is **not** the training environment. The trainer's 119-float task observation (ball, palm, contact,
level block) lives in ``obs.py`` and is unchanged; a brain driven here cannot see the ball. That is the
point of the universal interface — a shared locomotion or balance brain can be evaluated on this body
before anyone trains a basketball-specific one.

Requires numpy + mujoco + onnxruntime.
"""

from __future__ import annotations

import argparse
import json
import pathlib

import mujoco
import numpy as np

from streetball import role_obs
from streetball.obs import ObsIndex

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets" / "scene.xml"
FALL_FRACTION = 0.55


class Onnx:
    """onnxruntime wrapper with the three attributes ``role_obs.for_policy`` needs."""

    def __init__(self, path: pathlib.Path):
        import onnxruntime as ort

        self.path = path
        self.session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.num_obs = int(self.session.get_inputs()[0].shape[-1])
        self.num_actions = int(self.session.get_outputs()[0].shape[-1])

    def act(self, obs: np.ndarray) -> np.ndarray:
        out = self.session.run(None, {self.input_name: np.asarray(obs, dtype=np.float32).reshape(1, -1)})[0]
        return np.asarray(out, dtype=np.float32).reshape(-1)


def resolve_policy(p: str) -> pathlib.Path:
    path = pathlib.Path(p)
    if path.is_dir():
        path = path / "policy.onnx"
    if not path.is_file():
        raise SystemExit(f"no policy at {p}")
    return path


def run(policy_path: pathlib.Path, *, steps: int, command: tuple, seed: int = 0) -> dict:
    m = mujoco.MjModel.from_xml_path(str(SCENE))
    d = mujoco.MjData(m)
    ix = ObsIndex(m)
    c = role_obs.load_contract()
    nn = Onnx(policy_path)
    iface = role_obs.for_policy(nn, ix.joint_names, c)

    decimation = int(c["physics"]["decimation"])
    control_dt = float(c["physics"]["control_dt"])

    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand")
    if key >= 0:
        mujoco.mj_resetDataKeyframe(m, d, key)
    else:
        mujoco.mj_resetData(m, d)
        d.qpos[ix.qadr] = ix.nominal
    mujoco.mj_forward(m, d)

    z0 = float(d.qpos[ix.root_q + 2])
    x0 = np.array(d.qpos[ix.root_q : ix.root_q + 2], dtype=np.float64)
    prev_action = np.zeros(iface.n_action, dtype=np.float32)
    falls, finite, distances = 0, True, 0.0
    t = 0.0

    for _ in range(steps):
        state = role_obs.RoleState.from_mjdata(d, ix.qadr, ix.vadr, ix.root_q, ix.root_v)
        obs = iface.build(state, prev_action, command, t)
        action = nn.act(obs)
        if not np.isfinite(action).all():
            finite = False
            break
        d.ctrl[:] = iface.targets(action)
        for _ in range(decimation):
            mujoco.mj_step(m, d)
        t += control_dt
        prev_action[:] = action
        xy = np.array(d.qpos[ix.root_q : ix.root_q + 2], dtype=np.float64)
        distances = float(np.linalg.norm(xy - x0))
        if float(d.qpos[ix.root_q + 2]) < FALL_FRACTION * z0:
            falls += 1

    return {
        "policy": str(policy_path),
        "creature": c["creature"],
        "trained_for": iface.trained_for,
        "foreign": iface.foreign,
        "steps": steps,
        "control_dt": control_dt,
        "finite": finite,
        "height_start": round(z0, 4),
        "height_end": round(float(d.qpos[ix.root_q + 2]), 4),
        "steps_below_fall_height": falls,
        "distance_m": round(distances, 4),
        "command": list(map(float, command)),
        "roles_without_a_joint": iface.action.unmapped_joints,
        "masked_roles": [r for r, k in zip(iface.roles, iface.mask) if k == 0],
        "seed": seed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a portable role-interface policy on the basketball body.")
    ap.add_argument("--policy", required=True, help="a run directory or a policy.onnx")
    ap.add_argument("--steps", type=int, default=250, help="control steps at 50 Hz")
    ap.add_argument("--command", default="0,0,0", help="velocity command: vx,vy,wz")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", type=pathlib.Path)
    a = ap.parse_args()

    command = tuple(float(x) for x in a.command.split(","))
    if len(command) != 3:
        ap.error("--command wants three comma-separated numbers: vx,vy,wz")

    try:
        res = run(resolve_policy(a.policy), steps=a.steps, command=command, seed=a.seed)
    except role_obs.ContractMismatch as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(f"{res['policy']}: trained for {res['trained_for']}, {res['steps']} steps @ {1.0 / res['control_dt']:.0f} Hz")
    if res["foreign"]:
        print(f"  foreign brain: loadable on {res['creature']}, correct only on {res['trained_for']}")
    print(
        f"  height {res['height_start']:.3f} -> {res['height_end']:.3f} m, "
        f"falls {res['steps_below_fall_height']}/{res['steps']}, moved {res['distance_m']:.2f} m, "
        f"finite {res['finite']}"
    )
    print(f"  masked roles {res['masked_roles']}, joints with no role {res['roles_without_a_joint']}")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {a.json}")
    return 0 if res["finite"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
