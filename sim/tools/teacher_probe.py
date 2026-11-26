"""Probe the composite locomotion + dribble teacher on l3a_walk (go / no-go before any cloning).

    uv run python tools/teacher_probe.py                      # teacher and the start brain, side by side
    uv run python tools/teacher_probe.py --stage 2 --lumbar   # a faster speed band, dribble arm + lean

The 2026-11-21 `walk_1h` run trained PPO on `l3a_walk` for 48 min and got 0 % success (0.01 waypoints per
episode, 66-95 % falls): the dribble brain has no gait. This probe answers the question the run left open -
does borrowing the shipped locomotion gait for the legs, and the gate-passing dribble brain for the arm,
walk the ball down the court? Only if it does is behaviour cloning worth doing (`tools/bc_train.py`).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streetball import teacher as teacher_lib  # noqa: E402
from streetball.env_base import EnvConfig, RandomizationConfig, StreetballEnv  # noqa: E402
from streetball.levels import make  # noqa: E402


def build_env(level_name: str, num_envs: int, seed: int, push_max: float) -> StreetballEnv:
    env = StreetballEnv(
        make(level_name),
        EnvConfig(num_envs=num_envs, seed=seed, randomization=RandomizationConfig(push_force=(0.0, push_max))),
    )
    return env


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="l3a_walk")
    ap.add_argument("--num-envs", type=int, default=256)
    ap.add_argument("--seconds", type=float, default=30.0, help="control seconds per episode to watch")
    ap.add_argument("--push-max", type=float, default=0.0, help="push force cap (N); the probe defaults to none")
    ap.add_argument("--stage", type=int, default=None, help="override the walk level's eval speed stage")
    ap.add_argument("--lumbar", action="store_true", help="the dribble brain also leans the lumbar joint")
    ap.add_argument("--baseline", default=str(teacher_lib.RUNS / "production" / "dribble_walk_init.pt"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", default=None, help="write the result here")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    env = build_env(args.level, args.num_envs, args.seed, args.push_max)
    if args.stage is not None:
        env.level.eval_stage = args.stage
    steps = int(round(args.seconds / env.control_dt))
    dev = env.device

    composite = teacher_lib.production_teacher(dev, teacher_lib.TeacherConfig(include_lumbar=args.lumbar))
    out = {"level": args.level, "stage": env.level._stage(), "num_envs": args.num_envs, "seconds": args.seconds}
    print(f"stage {out['stage']} speed band {env.level.speed_stages[out['stage']]} m/s, {args.num_envs} envs", flush=True)

    out["start_brain"] = teacher_lib.rollout(env, teacher_lib.load_actor(args.baseline, dev), steps).as_dict()
    print("start brain   ", json.dumps(out["start_brain"]), flush=True)
    env.reset(torch.arange(env.N, device=dev))
    out["teacher"] = teacher_lib.rollout(env, composite.act, steps).as_dict()
    print("composite     ", json.dumps(out["teacher"]), flush=True)

    if args.level.startswith("l3a"):
        t = out["teacher"]
        carries = t["metrics"].get("control_frac", 0.0) >= 0.9
        moves = t["metrics"].get("dist_m", 0.0) >= 3.0
        out["verdict"] = "clone" if (carries and moves and t["episodes"] > 0) else "do not clone"
        print(f"verdict: {out['verdict']} (control {t['metrics'].get('control_frac', 0):.3f}, "
              f"dist {t['metrics'].get('dist_m', 0):.2f} m, waypoints {t['metrics'].get('waypoints', 0):.2f}, "
              f"falls {t['falls']:.1%})", flush=True)
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print("wrote", args.json)


if __name__ == "__main__":
    main()
