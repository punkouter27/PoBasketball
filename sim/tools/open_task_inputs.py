"""Open dormant task-block inputs of a trained actor before a new curriculum stage uses them (UU_AGENT section 3:
new features enter with zero-initialised weights).

A stage that never set some task inputs (e.g. the stationary dribble: speed / waypoint direction / distance always 0)
leaves the observation normaliser with var ~ 0 on them and first-layer weights that never saw a gradient (still at their
random init). The next stage's first non-zero command is then scaled by ~1/sqrt(1e-8) and multiplied into random weights:
the 2026-11-21 l3a_walk probe fell in 2 s (239 / 256) with the same actor that dribbles 17 s standing still.

This tool, for the given task-block slots: zeroes the first-layer weight columns (the actor ignores those inputs, so it
acts exactly as before whatever the command), and sets normaliser mean 0 / the given std so the inputs arrive at unit
scale once training starts using them. Writes an actor-only checkpoint (`train.py --init <out> --init-actor-only`).

    uv run python tools/open_task_inputs.py runs/dribble_time10d/ckpt_600M.pt --out runs/production/dribble_walk_init.pt \
        --slot 3:1.0 --slot 4:1.0 --slot 5:1.0 --slot 6:3.0
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import torch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from streetball import obs as obs_spec  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--slot", action="append", required=True, help="task-block index:std, e.g. 3:1.0 (speed_cmd)")
    args = ap.parse_args()

    sd = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    ac = sd["ac"]
    n_obs = ac["actor.norm.mean"].numel()
    t0 = n_obs - obs_spec.N_TASK
    w = ac["actor.net.0.weight"]
    for s in args.slot:
        idx, std = s.split(":")
        i = t0 + int(idx)
        print(f"task[{idx}] (obs {i}): norm std {ac['actor.norm.var'][i].sqrt().item():.2e} -> {float(std)}, "
              f"|w col| {w[:, i].abs().max().item():.3f} -> 0")
        w[:, i] = 0.0
        ac["actor.norm.mean"][i] = 0.0
        ac["actor.norm.var"][i] = float(std) ** 2

    # parity: with the opened inputs at any value, actions equal the original actor's at those inputs = 0
    from streetball.ppo import Actor

    last_w = [v for k, v in ac.items() if k.startswith("actor.net.") and k.endswith(".weight")][-1]
    n_act = last_w.shape[0]
    actor = Actor(n_obs, n_act)
    actor.load_state_dict({k[6:]: v for k, v in ac.items() if k.startswith("actor.")})
    orig_ac = torch.load(args.ckpt, map_location="cpu", weights_only=False)["ac"]
    orig = Actor(n_obs, n_act)
    orig.load_state_dict({k[6:]: v for k, v in orig_ac.items() if k.startswith("actor.")})
    x = torch.randn(1000, n_obs)
    x0 = x.clone()
    for s in args.slot:
        x0[:, t0 + int(s.split(":")[0])] = 0.0
    with torch.no_grad():
        d = (actor(x) - orig(x0)).abs().max().item()
    print(f"parity (opened inputs random vs original with them at 0): max abs action diff {d:.2e}")
    if d > 1e-5:
        sys.exit("parity FAILED")
    out = {"ac": {k: v for k, v in ac.items() if k.startswith("actor.")}, "actor_only": True, "opened_task_slots": args.slot}
    for k in ("level", "interface_sha", "physics_sha", "steps", "push_max", "nan_grads"):
        if k in sd:
            out[k] = sd[k]
    torch.save(out, args.out)
    print(f"wrote {args.out} (actor only)")


if __name__ == "__main__":
    main()
