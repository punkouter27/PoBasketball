"""AMP training driver (MimicKit-style Adversarial Motion Priors on the Streetball env).

    uv run python -m streetball.train_amp --level l1_traverse_amp --init runs/l1_v2_armstop/model.pt \
        --demo data/mocap/amp_demo.npz --run-name l1_amp_v1 --time-budget-min 90 --push-curriculum --init-std 0.3

The baseline driver (streetball/train.py) is untouched so the two approaches can be compared. Same env,
same PPO, same policy interface and checkpoint format (evaluate.py / export_onnx.py / Unreal work unchanged);
the reward per step becomes

    r = task_w * r_task + style_w * r_style(s_t, s_t+1)

with r_style from the discriminator in streetball/amp.py, which is trained every iteration on the rollout's
transitions vs. the retargeted LocoMuJoCo motion capture.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict

import mujoco
import numpy as np
import torch
from torch.utils.tensorboard import SummaryWriter

import streetball.train as base
from streetball.amp import AMP, KEY_BODIES, amp_features
from streetball.env_base import EnvConfig, RandomizationConfig, StreetballEnv
from streetball.levels import make
from streetball.ppo import PPO, PPOConfig


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="l1_traverse_amp")
    ap.add_argument("--demo", default=str(base.ROOT / "data" / "mocap" / "amp_demo.npz"))
    ap.add_argument("--steps", type=float, default=1e9)
    ap.add_argument("--num-envs", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--init", default=None)
    ap.add_argument("--init-actor-only", action="store_true")
    ap.add_argument("--push-curriculum", action="store_true")
    ap.add_argument("--push-max", type=float, default=150.0)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--init-std", type=float, default=0.5)
    ap.add_argument("--task-w", type=float, default=1.0)
    ap.add_argument("--style-w", type=float, default=1.0)
    ap.add_argument("--time-budget-min", type=float, default=0.0)
    ap.add_argument("--save-every", type=int, default=50)
    return ap.parse_args()


def main():
    args = parse()
    torch.manual_seed(args.seed)
    out = base.RUNS / args.run_name
    out.mkdir(parents=True, exist_ok=True)
    env_cfg = EnvConfig(num_envs=args.num_envs, seed=args.seed,
                        randomization=RandomizationConfig(enabled=True, push_force=(0.0, args.push_max)))
    ppo_cfg = PPOConfig(lr=args.lr, init_std=args.init_std)
    level = make(args.level)
    env = StreetballEnv(level, env_cfg)
    agent = PPO(env.N_OBS, env.N_ACT, env.N, ppo_cfg, env.device)
    if args.init:
        sd = torch.load(args.init, map_location=env.device)
        agent.load_state_dict(sd, actor_only=args.init_actor_only)
        print(f"initialised from {args.init}", flush=True)
    demo = torch.as_tensor(np.load(args.demo)["pairs"], dtype=torch.float32)
    amp = AMP(demo, env.device)
    print(f"AMP demo: {demo.shape[0]} transitions x {demo.shape[1]} features from {args.demo}", flush=True)

    keyb = torch.as_tensor([mujoco.mj_name2id(env.mjm, mujoco.mjtObj.mjOBJ_BODY, b) for b in KEY_BODIES], device=env.device)
    rq, rv = env.root_q, env.root_v

    def feats():
        return amp_features(env.qpos[:, rq:rq + 3], env.qpos[:, rq + 3:rq + 7], env.qvel[:, rv:rv + 3],
                            env.qvel[:, rv + 3:rv + 6], env.joint_pos(), env.joint_vel(), env.xpos[:, keyb])

    (out / "config.json").write_text(json.dumps({"args": vars(args), "env": asdict(env_cfg), "ppo": asdict(ppo_cfg),
        "level": level.name, "method": "AMP (MimicKit port, streetball/amp.py)"}, indent=2, default=str), encoding="utf-8")
    writer = SummaryWriter(str(out))
    csvf = open(out / "log.csv", "w", newline="", encoding="utf-8")
    csvw = None
    base.PUSH_MAX = float(args.push_max)
    tags = base.version_tags("l1_traverse" if level.name.startswith("l1_traverse") else level.name)
    tags["method"] = "amp"
    steps_per_iter = env.N * ppo_cfg.steps_per_env
    n_iters = int(args.steps // steps_per_iter)
    obs = env.obs.clone()
    f_prev = feats().clone()
    ep_returns, ep_lens = [], []
    t_start = time.time()
    nan_grads, best, rec, it = 0, -float("inf"), {}, 0
    stop_reason = "budget of steps reached"
    print(f"run {args.run_name}: AMP on {level.name}, task_w {args.task_w}, style_w {args.style_w}", flush=True)
    for it in range(1, n_iters + 1):
        if args.push_curriculum:
            env.push_scale = min(1.0, it / max(1, n_iters // 3))
        t0 = time.time()
        metric_acc: dict[str, float] = {}
        pair_list = []
        r_task_sum = r_style_sum = 0.0
        for _ in range(ppo_cfg.steps_per_env):
            a = agent.act(obs)
            obs, rew, done, info = env.step(a)
            f_cur = feats()
            pairs = torch.cat([f_prev, f_cur], -1)
            valid = ~done                                  # a done step's f_cur is already the reset state
            r_style = amp.reward(pairs) * valid.float()
            agent.record(args.task_w * rew + args.style_w * r_style, done, info["time_outs"])
            pair_list.append(pairs[valid])
            f_prev = f_cur.clone()
            r_task_sum += float(rew.mean()); r_style_sum += float(r_style.mean())
            if "ep_return" in info:
                ep_returns += info["ep_return"].tolist(); ep_lens += info["ep_len"].tolist()
            for k, v in info.items():
                if k.startswith("m/"):
                    metric_acc[k] = metric_acc.get(k, 0.0) + float(v.float().mean())
        agent.compute_returns(obs)
        t_roll = time.time() - t0
        stats = agent.update()
        stats.update(amp.update(torch.cat(pair_list, 0)))
        nan_grads += int(stats.pop("ppo/nan_grad_batches", 0))
        stats["ppo/nan_grads_total"] = nan_grads
        T = ppo_cfg.steps_per_env
        stats["amp/r_task"] = r_task_sum / T
        stats["amp/r_style"] = r_style_sum / T
        total_steps = it * steps_per_iter
        fps = steps_per_iter / (time.time() - t0)
        rec = {"iter": it, "steps": total_steps, "fps": fps,
               "ep_return": sum(ep_returns[-1000:]) / max(1, len(ep_returns[-1000:])),
               "ep_len_s": env.control_dt * sum(ep_lens[-1000:]) / max(1, len(ep_lens[-1000:])),
               "push_scale": env.push_scale, **stats}
        for k, v in metric_acc.items():
            rec[k] = v / T
        for k, v in rec.items():
            writer.add_scalar(k, v, total_steps)
        if csvw is None:
            csvw = csv.DictWriter(csvf, fieldnames=list(rec.keys()))
            csvw.writeheader()
        csvw.writerow(rec); csvf.flush()
        if it % 10 == 0 or it == 1:
            print(f"it {it:5d} | {total_steps/1e6:7.1f}M | {fps/1e3:5.1f}k fps | ret {rec['ep_return']:8.1f} | ep {rec['ep_len_s']:5.1f}s | "
                  f"r_task {stats['amp/r_task']:.2f} r_style {stats['amp/r_style']:.2f} | D acc agent {stats['amp/agent_acc']:.2f} "
                  f"demo {stats['amp/demo_acc']:.2f} | {(time.time()-t_start)/60:.1f} min", flush=True)
        extra = {"steps": total_steps, "nan_grads": nan_grads, "amp": amp.state_dict()}
        if args.time_budget_min > 0 and (time.time() - t_start) / 60 >= args.time_budget_min:
            stop_reason = f"time budget {args.time_budget_min:.0f} min reached at {total_steps/1e6:.1f}M steps"
            base.save_ckpt(agent, out / "model.pt", tags, extra)
            break
        if it % args.save_every == 0:
            base.save_ckpt(agent, out / "model.pt", tags, extra)
            if rec["ep_return"] > best and len(ep_returns) > 100:
                best = rec["ep_return"]
                base.save_ckpt(agent, out / "best.pt", tags, extra)
    base.save_ckpt(agent, out / "model.pt", tags, {"steps": it * steps_per_iter, "nan_grads": nan_grads, "amp": amp.state_dict()})
    writer.close(); csvf.close()
    (out / "done.json").write_text(json.dumps({"stop_reason": stop_reason, "steps": int(it * steps_per_iter), "iters": it,
        "wall_min": (time.time() - t_start) / 60, "nan_grads": nan_grads, "final_ep_return": rec.get("ep_return"),
        "final_ep_len_s": rec.get("ep_len_s")}), encoding="utf-8")
    print(f"done: {out} ({stop_reason})", flush=True)


if __name__ == "__main__":
    main()
