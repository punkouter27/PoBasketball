"""C5: evaluation harness. 200 randomised episodes with a deterministic policy, reports
pass/fail against the level's PRD milestone (blueprint C.2).

    uv run python -m streetball.evaluate --level l0_stand --ckpt runs/<run>/model.pt [--episodes 200]

Writes docs/phase_reports/eval_<level>.md and .json. Exit code 0 on pass.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

import torch

from streetball.env_base import EnvConfig, RandomizationConfig, StreetballEnv
from streetball.levels import make
from streetball.ppo import Actor

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORTS = ROOT.parent / "docs" / "phase_reports"


def evaluate(level_name: str, ckpt: pathlib.Path, episodes: int = 200, seed: int = 123,
             push_scale: float = 1.0, push_max: float | None = None) -> dict:
    level = make(level_name)
    sd = torch.load(ckpt, map_location="cpu")
    # evaluate under the same push magnitude the checkpoint was trained with unless overridden
    if push_max is None:
        push_max = float(sd.get("push_max", 150.0))
    env = StreetballEnv(level, EnvConfig(num_envs=episodes, seed=seed,
                                         randomization=RandomizationConfig(enabled=True, push_force=(0.0, push_max))))
    env.push_scale = push_scale
    sd = torch.load(ckpt, map_location=env.device)
    actor = Actor(env.N_OBS, env.N_ACT).to(env.device)
    actor.load_state_dict({k[len("actor."):]: v for k, v in sd["ac"].items() if k.startswith("actor.")})
    actor.eval()

    N = env.N
    finished = torch.zeros(N, dtype=torch.bool, device=env.device)
    success = torch.zeros(N, dtype=torch.bool, device=env.device)
    ep_len = torch.zeros(N, device=env.device)
    fell = torch.zeros(N, dtype=torch.bool, device=env.device)
    metrics_sum: dict[str, torch.Tensor] = {}
    obs = env.obs
    t0 = time.perf_counter()
    step_i = 0
    with torch.no_grad():
        while not finished.all():
            a = actor(obs)
            obs, rew, done, info = env.step(a)
            step_i += 1
            just = done & ~finished
            success |= just & info["success"]          # computed by the env before its auto-reset
            fell |= just & info["fallen"]
            ep_len = torch.where(just, torch.full_like(ep_len, float(step_i)), ep_len)
            for k, v in info.items():
                if k.startswith("m/"):
                    metrics_sum[k] = metrics_sum.get(k, torch.zeros(N, device=env.device)) + torch.where(finished, 0.0, v.float())
            finished |= just
    dt = time.perf_counter() - t0
    rate = success.float().mean().item()
    # UU_AGENT graduation gate: the target score must hold for 100 straight episodes. Episodes run in
    # parallel, so 'straight' is evaluated in finishing order: every window of 100 consecutive finishes
    # must meet the level's pass fraction.
    import numpy as np
    order = torch.argsort(ep_len)
    succ_sorted = success[order].float().cpu().numpy()
    window = 100
    if len(succ_sorted) >= window:
        rolling = np.convolve(succ_sorted, np.ones(window) / window, mode="valid")
        holds_100 = bool(rolling.min() >= level.pass_fraction - 1e-9)
    else:
        holds_100 = False
    ckpt_sd = torch.load(ckpt, map_location="cpu")
    nan_grads = int(ckpt_sd.get("nan_grads", 0))
    passed = rate >= level.pass_fraction and holds_100 and nan_grads == 0
    steps_run = ep_len.clamp_min(1)
    res = {
        "level": level_name, "checkpoint": str(ckpt), "episodes": episodes, "push_scale": push_scale, "push_max_N": push_max,
        "success_rate": rate, "pass_fraction": level.pass_fraction, "passed": passed,
        "holds_100_straight": holds_100, "nan_grads": nan_grads,
        "interface_sha": ckpt_sd.get("interface_sha"), "physics_sha": ckpt_sd.get("physics_sha"),
        "fall_rate": fell.float().mean().item(),
        "mean_episode_s": (ep_len * env.control_dt).mean().item(),
        "metrics": {k: (v / steps_run).mean().item() for k, v in metrics_sum.items()},
        "wall_s": dt,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"eval_{level_name}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    lines = [f"# Evaluation — {level_name}: {'PASS' if passed else 'FAIL'}", "",
             f"Checkpoint `{ckpt}`, {episodes} randomised episodes, deterministic policy, pushes up to {push_max:.0f} N x scale {push_scale}.", "",
             "| Metric | Value |", "|---|---|",
             f"| Success rate | {rate*100:.1f} % (need >= {level.pass_fraction*100:.0f} %) |",
             f"| Holds for 100 straight episodes | {'yes' if holds_100 else 'no'} |",
             f"| NaN-gradient batches in training | {nan_grads} (must be 0) |",
             f"| Fall rate | {res['fall_rate']*100:.1f} % |",
             f"| Mean episode length | {res['mean_episode_s']:.1f} s of {level.episode_s:.0f} s |"]
    for k, v in res["metrics"].items():
        lines.append(f"| {k[2:]} | {v:.3f} |")
    (REPORTS / f"eval_{level_name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--push-scale", type=float, default=1.0)
    ap.add_argument("--push-max", type=float, default=None, help="override the push force cap (N); default: from checkpoint")
    args = ap.parse_args()
    res = evaluate(args.level, pathlib.Path(args.ckpt), args.episodes, push_scale=args.push_scale, push_max=args.push_max)
    print(json.dumps(res, indent=2))
    raise SystemExit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
