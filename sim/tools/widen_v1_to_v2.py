"""Widen a graduated humanoid_v1 (27-DoF, 119 obs) policy into the humanoid_v2 interface (29-DoF, 125 obs).

v2 only inserts the toe hinges (`toe_l` after `ankle_roll_l`, `toe_r` after `ankle_roll_r`); every other input and
output keeps its meaning. Following UU_AGENT section 3 ("new features with zero-initialised weights"):
  - first-layer columns for the new toe inputs are zero, every old column is copied to its new slot;
  - last-layer rows for the toe actions are zero (action 0 = nominal toe angle, i.e. flat foot);
  - normaliser stats are moved with their inputs; toe stats are borrowed from the same side's ankle_pitch.
The widened actor is checked to give the v1 ONNX's exact actions on random v1 observations (toe inputs zero).
Result supports `train.py --init <out> --init-actor-only` only.

    uv run python tools/widen_v1_to_v2.py ../shared/policies_v1_27dof/balance.onnx --out runs/production/balance_v1w.pt
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import numpy as np
import onnxruntime as ort
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from onnx_to_ckpt import rebuild  # noqa: E402

from streetball import obs as obs_spec  # noqa: E402
from streetball.ppo import Actor  # noqa: E402


def v1_spec() -> dict:
    """The v1 obs contract from git (the commit before humanoid_v2)."""
    txt = subprocess.run(
        ["git", "show", "7db8307~1:shared/obs_spec.json"], cwd=ROOT.parent, capture_output=True, text=True, check=True
    ).stdout
    return json.loads(txt)


def index_maps(v1: dict, v2: dict) -> tuple[list[int | None], list[int | None]]:
    """For each v2 obs / action index, the v1 index carrying the same quantity (None = new input)."""
    j1 = {n: i for i, n in enumerate(v1["joint_order"])}
    jmap = [j1.get(n) for n in v2["joint_order"]]
    s1 = {s["name"]: s for s in v1["slots"]}
    obs_map: list[int | None] = []
    for s in v2["slots"]:
        o = s1[s["name"]]
        if s["size"] == len(v2["joint_order"]):  # per-joint block
            assert o["size"] == len(v1["joint_order"]), s["name"]
            obs_map += [None if j is None else o["start"] + j for j in jmap]
        else:
            assert o["size"] == s["size"], s["name"]
            obs_map += list(range(o["start"], o["start"] + s["size"]))
    assert len(obs_map) == v2["n_obs"]
    return obs_map, jmap


def widen(v1_actor: Actor, obs_map, jmap, v2: dict, hidden) -> Actor:
    n_obs, n_act = v2["n_obs"], v2["n_action"]
    a2 = Actor(n_obs, n_act, hidden)
    names = v2["joint_order"]
    # toe normaliser stats: same side's ankle_pitch, per joint block
    borrow = {i: names.index("ankle_pitch_" + n[-1]) for i, n in enumerate(names) if n.startswith("toe_")}
    with torch.no_grad():
        l1 = [m for m in v1_actor.net if isinstance(m, torch.nn.Linear)]
        l2 = [m for m in a2.net if isinstance(m, torch.nn.Linear)]
        for k, (a, b) in enumerate(zip(l1, l2)):
            if k == 0:
                b.weight.zero_()
                for i2, i1 in enumerate(obs_map):
                    if i1 is not None:
                        b.weight[:, i2] = a.weight[:, i1]
                b.bias.copy_(a.bias)
            elif k == len(l1) - 1:
                b.weight.zero_()
                b.bias.zero_()
                for j2, j1 in enumerate(jmap):
                    if j1 is not None:
                        b.weight[j2] = a.weight[j1]
                        b.bias[j2] = a.bias[j1]
            else:
                b.weight.copy_(a.weight)
                b.bias.copy_(a.bias)
        for i2, i1 in enumerate(obs_map):
            if i1 is None:
                # i2 sits in a per-joint block; find the same block's ankle_pitch slot
                blk = next(s for s in v2["slots"] if s["start"] <= i2 < s["start"] + s["size"])
                src = obs_map[blk["start"] + borrow[i2 - blk["start"]]]
                a2.norm.mean[i2] = 0.0
                a2.norm.var[i2] = v1_actor.norm.var[src]
            else:
                a2.norm.mean[i2] = v1_actor.norm.mean[i1]
                a2.norm.var[i2] = v1_actor.norm.var[i1]
        a2.norm.count.fill_(1e6)
    return a2.eval()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("onnx", help="v1 27-DoF production ONNX")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    hidden = (512, 256, 128)
    v1 = v1_spec()
    v2 = json.loads((ROOT.parent / "shared" / "obs_spec.json").read_text(encoding="utf-8"))
    assert v2["n_obs"] == obs_spec.N_OBS and v2["n_action"] == obs_spec.N_JOINTS
    src = pathlib.Path(args.onnx)
    a1, diff = rebuild(src, hidden, n_obs=v1["n_obs"], n_act=v1["n_action"])
    print(f"v1 rebuild vs onnxruntime max abs diff {diff:.2e}")
    if diff >= 1e-5:
        raise SystemExit("FAIL: v1 rebuild parity above 1e-5")
    obs_map, jmap = index_maps(v1, v2)
    a2 = widen(a1, obs_map, jmap, v2, hidden)

    # parity: v2 actor on v1 observations placed in v2 slots (toe inputs = normaliser mean -> zero contribution)
    sess = ort.InferenceSession(str(src), providers=["CPUExecutionProvider"])
    x1 = np.random.default_rng(1).normal(0, 2, (1000, v1["n_obs"])).astype(np.float32)
    x2 = np.zeros((1000, v2["n_obs"]), np.float32)
    for i2, i1 in enumerate(obs_map):
        x2[:, i2] = 0.0 if i1 is None else x1[:, i1]
    ref = np.concatenate([sess.run(["action"], {"obs": x1[i : i + 1]})[0] for i in range(len(x1))], 0)
    with torch.no_grad():
        got = a2(torch.from_numpy(x2)).numpy()
    toe = [j for j, k in enumerate(jmap) if k is None]
    keep = [j for j, k in enumerate(jmap) if k is not None]
    d = float(np.abs(got[:, keep] - ref[:, [jmap[j] for j in keep]]).max())
    t = float(np.abs(got[:, toe]).max())
    print(f"widened v2 vs v1 onnx max abs diff {d:.2e}; toe actions max |a| {t:.2e}")
    if d >= 1e-5 or t >= 1e-6:
        raise SystemExit("FAIL: widened parity, checkpoint not written")

    side = src.with_suffix(".json")
    meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    sd = {
        "ac": {f"actor.{k}": v for k, v in a2.state_dict().items()},
        "actor_only": True,
        "widened_from_v1_onnx": str(src),
        "level": meta.get("level"),
        "interface_sha": None,
        "physics_sha": None,
        "steps": meta.get("train_steps"),
        "nan_grads": meta.get("nan_grads", 0),
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(sd, out)
    print(f"wrote {out} (actor only, 27->29 DoF, parity PASS)")


if __name__ == "__main__":
    main()
