"""C3: training driver.

    uv run python -m streetball.train --level l0_stand --steps 100e6 [--init runs/<prev>/model.pt]
                                      [--num-envs 4096] [--run-name l0] [--push-curriculum]

Writes runs/<run>/ : config.json, TensorBoard events, model.pt (latest), best.pt, log.csv.
Curriculum knobs: --push-curriculum ramps the push magnitude from 0 to 1 over the first
third of training (env.push_scale).
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import time
from dataclasses import asdict

import torch
from torch.utils.tensorboard import SummaryWriter

from streetball.env_base import EnvConfig, RandomizationConfig, StreetballEnv
from streetball.levels import make
from streetball.ppo import PPO, PPOConfig

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", required=True)
    ap.add_argument("--steps", type=float, default=100e6, help="total env steps")
    ap.add_argument("--num-envs", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--init", default=None, help="checkpoint to initialise from (actor+critic if same level, actor only otherwise)")
    ap.add_argument("--init-actor-only", action="store_true")
    ap.add_argument("--no-randomization", action="store_true")
    ap.add_argument("--push-curriculum", action="store_true")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--steps-per-env", type=int, default=24)
    ap.add_argument("--init-std", type=float, default=0.5)
    ap.add_argument("--push-max", type=float, default=150.0, help="max random push force in N")
    ap.add_argument("--save-every", type=int, default=50, help="iterations")
    return ap.parse_args()


def main():
    args = parse()
    torch.manual_seed(args.seed)
    run = args.run_name or f"{args.level}_{time.strftime('%m%d_%H%M%S')}"
    out = RUNS / run
    out.mkdir(parents=True, exist_ok=True)

    env_cfg = EnvConfig(num_envs=args.num_envs, seed=args.seed,
                        randomization=RandomizationConfig(enabled=not args.no_randomization,
                                                          push_force=(0.0, args.push_max)))
    ppo_cfg = PPOConfig(lr=args.lr, steps_per_env=args.steps_per_env, init_std=args.init_std)
    level = make(args.level)
    env = StreetballEnv(level, env_cfg)
    agent = PPO(env.N_OBS, env.N_ACT, env.N, ppo_cfg, env.device)
    if args.init:
        sd = torch.load(args.init, map_location=env.device)
        agent.load_state_dict(sd, actor_only=args.init_actor_only)
        print(f"initialised from {args.init} (actor_only={args.init_actor_only})")

    (out / "config.json").write_text(json.dumps({
        "args": vars(args), "env": asdict(env_cfg), "ppo": asdict(ppo_cfg), "level": level.name,
        "control_dt": env.control_dt, "max_steps": env.max_steps}, indent=2, default=str), encoding="utf-8")
    writer = SummaryWriter(str(out))
    csvf = open(out / "log.csv", "w", newline="", encoding="utf-8")
    csvw = None

    steps_per_iter = env.N * ppo_cfg.steps_per_env
    n_iters = int(args.steps // steps_per_iter)
    obs = env.obs.clone()
    best = -float("inf")
    ep_returns: list[float] = []
    ep_lens: list[float] = []
    t_start = time.time()
    print(f"run {run}: {n_iters} iterations x {steps_per_iter} steps; level {level.name}; episode {level.episode_s}s")

    for it in range(1, n_iters + 1):
        if args.push_curriculum:
            env.push_scale = min(1.0, it / max(1, n_iters // 3))
        t0 = time.time()
        metric_acc: dict[str, float] = {}
        succ_acc = 0.0
        for _ in range(ppo_cfg.steps_per_env):
            a = agent.act(obs)
            obs, rew, done, info = env.step(a)
            agent.record(rew, done, info["time_outs"])
            if "ep_return" in info:
                ep_returns += info["ep_return"].tolist()
                ep_lens += info["ep_len"].tolist()
            for k, v in info.items():
                if k.startswith("m/"):
                    metric_acc[k] = metric_acc.get(k, 0.0) + float(v.float().mean())
        agent.compute_returns(obs)
        t_roll = time.time() - t0
        stats = agent.update()
        t_upd = time.time() - t0 - t_roll

        total_steps = it * steps_per_iter
        fps = steps_per_iter / (t_roll + t_upd)
        rec = {"iter": it, "steps": total_steps, "fps": fps,
               "ep_return": sum(ep_returns[-1000:]) / max(1, len(ep_returns[-1000:])),
               "ep_len_s": env.control_dt * sum(ep_lens[-1000:]) / max(1, len(ep_lens[-1000:])),
               "push_scale": env.push_scale, **stats}
        for k, v in metric_acc.items():
            rec[k] = v / ppo_cfg.steps_per_env
        for k, v in rec.items():
            writer.add_scalar(k, v, total_steps)
        if csvw is None:
            csvw = csv.DictWriter(csvf, fieldnames=list(rec.keys()))
            csvw.writeheader()
        csvw.writerow(rec); csvf.flush()

        if it % 10 == 0 or it == 1:
            el = time.time() - t_start
            print(f"it {it:5d} | {total_steps/1e6:7.1f}M steps | {fps/1e3:5.1f}k fps | ret {rec['ep_return']:8.2f} | "
                  f"ep {rec['ep_len_s']:5.1f}s | kl {stats['ppo/kl']:.4f} lr {stats['ppo/lr']:.1e} std {stats['ppo/std']:.3f} | "
                  f"push {env.push_scale:.2f} | {el/60:.1f} min", flush=True)
        if it % args.save_every == 0 or it == n_iters:
            torch.save(agent.state_dict(), out / "model.pt")
            if rec["ep_return"] > best and len(ep_returns) > 100:
                best = rec["ep_return"]
                torch.save(agent.state_dict(), out / "best.pt")
    torch.save(agent.state_dict(), out / "model.pt")
    writer.close(); csvf.close()
    print(f"done: {out}")


if __name__ == "__main__":
    main()
