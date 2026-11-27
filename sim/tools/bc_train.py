"""DAgger-style behavior cloning from the composite locomotion + dribble teacher.

    uv run python tools/bc_train.py --time-budget-min 480 --rounds 0

The output is an actor-only checkpoint for `train.py --init ... --init-actor-only`.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streetball import teacher as teacher_lib  # noqa: E402
from streetball.env_base import EnvConfig, RandomizationConfig, StreetballEnv  # noqa: E402
from streetball.levels import make  # noqa: E402
from streetball.train import version_tags  # noqa: E402


def parse_args() -> argparse.Namespace:
    policies = ROOT.parent / "shared" / "policies"
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", default="l3a_walk")
    ap.add_argument("--locomotion", default=str(policies / "locomotion.onnx"))
    ap.add_argument("--dribble", default=str(policies / "dribble.onnx"))
    ap.add_argument("--out", default=str(ROOT / "runs" / "bc_l3a_walk.pt"))
    ap.add_argument("--num-envs", type=int, default=256)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--push-max", type=float, default=0.0)
    ap.add_argument("--rollout-seconds", type=float, default=30.0)
    ap.add_argument("--rounds", type=int, default=None, help="DAgger rounds (default: 10 without a time budget)")
    ap.add_argument("--time-budget-min", type=float, default=0.0)
    ap.add_argument("--capacity", type=int, default=500_000, help="maximum stored observation/action pairs")
    ap.add_argument("--updates-per-round", type=int, default=200)
    ap.add_argument("--batch-size", type=int, default=2048)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--no-lumbar", action="store_true")
    args = ap.parse_args()
    if args.num_envs < 1 or args.rollout_seconds <= 0 or args.capacity < 1:
        ap.error("num-envs, rollout-seconds, and capacity must be positive")
    if (args.rounds is not None and args.rounds < 0) or args.time_budget_min < 0:
        ap.error("rounds and time-budget-min cannot be negative")
    if args.rounds is None and args.time_budget_min == 0:
        args.rounds = 10
    if args.rounds == 0:
        if args.time_budget_min == 0:
            ap.error("--rounds 0 requires a positive --time-budget-min")
        args.rounds = None
    if args.updates_per_round < 1 or args.batch_size < 1 or args.lr <= 0:
        ap.error("updates-per-round, batch-size, and lr must be positive")
    return args


def save_actor(actor, out: pathlib.Path, level: str, steps: int, push_max: float) -> None:
    tags = version_tags(level)
    tags["push_max"] = push_max
    payload = {
        "ac": {f"actor.{key}": value.detach().cpu() for key, value in actor.state_dict().items()},
        "actor_only": True,
        "level": level,
        "steps": steps,
        "nan_grads": 0,
        "bc": True,
        **tags,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    torch.save(payload, tmp)
    tmp.replace(out)


def train_round(actor, buffer, optimizer, args) -> float:
    losses = 0.0
    for _ in range(args.updates_per_round):
        obs, target = buffer.sample(args.batch_size)
        loss = torch.nn.functional.mse_loss(actor(obs), target)
        if not torch.isfinite(loss):
            raise RuntimeError("non-finite BC loss; refusing to save this round")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(actor.parameters(), 1.0)
        if not torch.isfinite(grad_norm):
            raise RuntimeError("non-finite BC gradient; refusing to save this round")
        optimizer.step()
        losses += loss.detach().item()
    return losses / args.updates_per_round


def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    env = StreetballEnv(
        make(args.level),
        EnvConfig(
            num_envs=args.num_envs,
            seed=args.seed,
            randomization=RandomizationConfig(push_force=(0.0, args.push_max)),
        ),
    )
    device = env.device
    cfg = teacher_lib.TeacherConfig(include_lumbar=not args.no_lumbar)
    teacher = teacher_lib.CompositeTeacher(
        teacher_lib.load_actor(args.locomotion, device),
        teacher_lib.load_actor(args.dribble, device),
        cfg,
    )
    probe_steps = int(round(max(args.rollout_seconds, 30.0) / env.control_dt))
    probe = teacher_lib.rollout(env, teacher.act, probe_steps)
    if not teacher_lib.teacher_is_cloneable(probe):
        raise SystemExit(
            "composite teacher failed the preflight gate "
            f"(control={probe.metrics.get('m/control_frac', 0.0):.3f}, "
            f"distance={probe.metrics.get('m/dist_m', 0.0):.2f} m, "
            f"falls={probe.falls:.1%}); BC training was not started"
        )
    env.reset(torch.arange(env.N, device=device))
    student = teacher_lib.open_walk_inputs(teacher_lib.load_actor(args.dribble, device))
    buffer = teacher_lib.BCEntryBuffer(args.capacity, env.N_OBS, env.N_ACT, device)
    optimizer = torch.optim.Adam(student.parameters(), lr=args.lr)
    steps = int(round(args.rollout_seconds / env.control_dt))
    out = pathlib.Path(args.out)
    deadline = time.monotonic() + args.time_budget_min * 60 if args.time_budget_min else None
    rounds = 0
    seen = 0

    print(
        f"BC {args.level}: {args.num_envs} envs, {steps} steps/round, teacher joints={cfg.joints}, output={out}",
        flush=True,
    )
    while (args.rounds is None or rounds < args.rounds) and (deadline is None or time.monotonic() < deadline):
        stats = teacher_lib.rollout(env, student, steps, buffer=buffer, teacher=teacher)
        if buffer.size == 0:
            raise RuntimeError("DAgger rollout collected no samples; refusing to train an empty dataset")
        loss = train_round(student, buffer, optimizer, args)
        seen = buffer.total_added
        rounds += 1
        save_actor(student, out, args.level, seen, args.push_max)
        print(
            f"round={rounds} samples={buffer.size} loss={loss:.6f} "
            f"episodes={stats.episodes} success={stats.success:.3f} falls={stats.falls:.3f} "
            f"control={stats.metrics.get('m/control_frac', 0.0):.3f} "
            f"waypoints={stats.metrics.get('m/waypoints', 0.0):.3f}",
            flush=True,
        )
    print(f"saved actor-only BC initialization: {out}", flush=True)


if __name__ == "__main__":
    main()
