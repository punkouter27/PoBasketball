"""C3: PPO for the vectorised Warp env (rsl_rl-style: on-policy rollouts, GAE,
clipped surrogate, adaptive LR on a KL target, running observation normalisation
that is folded into the exported actor).

Actor: obs -> normalise -> MLP(512, 256, 128, ELU) -> tanh -> mean in [-1, 1];
Gaussian exploration with a state-independent log_std, samples clipped by the env.
Critic: same trunk shape, separate weights.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn


class RunningMeanStd(nn.Module):
    def __init__(self, shape: int, eps: float = 1e-4):
        super().__init__()
        self.register_buffer("mean", torch.zeros(shape))
        self.register_buffer("var", torch.ones(shape))
        self.register_buffer("count", torch.tensor(eps))

    @torch.no_grad()
    def update(self, x: torch.Tensor):
        bm, bv, bc = x.mean(0), x.var(0, unbiased=False), x.shape[0]
        delta = bm - self.mean
        tot = self.count + bc
        self.mean += delta * bc / tot
        m_a = self.var * self.count
        m_b = bv * bc
        self.var = (m_a + m_b + delta ** 2 * self.count * bc / tot) / tot
        self.count = tot

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return ((x - self.mean) / torch.sqrt(self.var + 1e-8)).clamp(-10.0, 10.0)


def mlp(inp: int, hidden: list[int], out: int) -> nn.Sequential:
    layers: list[nn.Module] = []
    d = inp
    for h in hidden:
        layers += [nn.Linear(d, h), nn.ELU()]
        d = h
    layers.append(nn.Linear(d, out))
    return nn.Sequential(*layers)


class Actor(nn.Module):
    """Deterministic policy head; this is exactly what gets exported to ONNX."""

    def __init__(self, n_obs: int, n_act: int, hidden=(512, 256, 128)):
        super().__init__()
        self.norm = RunningMeanStd(n_obs)
        self.net = mlp(n_obs, list(hidden), n_act)

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        return torch.tanh(self.net(self.norm(obs)))


class ActorCritic(nn.Module):
    def __init__(self, n_obs: int, n_act: int, hidden=(512, 256, 128), init_std: float = 0.5):
        super().__init__()
        self.actor = Actor(n_obs, n_act, hidden)
        self.critic = mlp(n_obs, list(hidden), 1)
        self.log_std = nn.Parameter(torch.full((n_act,), math.log(init_std)))

    def dist(self, obs: torch.Tensor) -> torch.distributions.Normal:
        mean = self.actor(obs)
        return torch.distributions.Normal(mean, self.log_std.exp().expand_as(mean))

    def value(self, obs: torch.Tensor) -> torch.Tensor:
        return self.critic(self.actor.norm(obs)).squeeze(-1)


@dataclass
class PPOConfig:
    steps_per_env: int = 24
    epochs: int = 5
    minibatches: int = 4
    gamma: float = 0.99
    lam: float = 0.95
    clip: float = 0.2
    entropy_coef: float = 0.0
    value_coef: float = 1.0
    max_grad_norm: float = 1.0
    lr: float = 3e-4
    kl_target: float = 0.01
    adaptive_lr: bool = True
    hidden: tuple[int, ...] = (512, 256, 128)
    init_std: float = 0.5


class PPO:
    def __init__(self, n_obs: int, n_act: int, num_envs: int, cfg: PPOConfig, device: torch.device):
        self.cfg = cfg
        self.device = device
        self.N = num_envs
        self.ac = ActorCritic(n_obs, n_act, cfg.hidden, cfg.init_std).to(device)
        self.opt = torch.optim.Adam(self.ac.parameters(), lr=cfg.lr)
        self.lr = cfg.lr
        T = cfg.steps_per_env
        z = lambda *s: torch.zeros(*s, device=device)
        self.obs_buf = z(T, num_envs, n_obs)
        self.act_buf = z(T, num_envs, n_act)
        self.logp_buf = z(T, num_envs)
        self.rew_buf = z(T, num_envs)
        self.done_buf = z(T, num_envs)
        self.timeout_buf = z(T, num_envs)
        self.val_buf = z(T, num_envs)
        self.mean_buf = z(T, num_envs, n_act)
        self.std_buf = z(T, num_envs, n_act)
        self.t = 0

    # ---- rollout --------------------------------------------------------------
    @torch.no_grad()
    def act(self, obs: torch.Tensor) -> torch.Tensor:
        self.ac.actor.norm.update(obs)
        d = self.ac.dist(obs)
        a = d.sample()
        t = self.t
        self.obs_buf[t] = obs
        self.act_buf[t] = a
        self.logp_buf[t] = d.log_prob(a).sum(-1)
        self.val_buf[t] = self.ac.value(obs)
        self.mean_buf[t] = d.mean
        self.std_buf[t] = d.stddev
        return a

    @torch.no_grad()
    def record(self, reward: torch.Tensor, done: torch.Tensor, time_out: torch.Tensor):
        t = self.t
        # Bootstrap truncated episodes with the value of the (pre-reset) state: rsl_rl's trick
        self.rew_buf[t] = reward + self.cfg.gamma * self.val_buf[t] * time_out.float()
        self.done_buf[t] = done.float()
        self.t += 1

    @torch.no_grad()
    def compute_returns(self, last_obs: torch.Tensor):
        last_val = self.ac.value(last_obs)
        T = self.cfg.steps_per_env
        adv = torch.zeros_like(self.rew_buf)
        gae = torch.zeros(self.N, device=self.device)
        for t in reversed(range(T)):
            next_val = last_val if t == T - 1 else self.val_buf[t + 1]
            nonterm = 1.0 - self.done_buf[t]
            delta = self.rew_buf[t] + self.cfg.gamma * next_val * nonterm - self.val_buf[t]
            gae = delta + self.cfg.gamma * self.cfg.lam * nonterm * gae
            adv[t] = gae
        self.ret_buf = adv + self.val_buf
        self.adv_buf = (adv - adv.mean()) / (adv.std() + 1e-8)

    # ---- update ---------------------------------------------------------------
    def update(self) -> dict[str, float]:
        cfg = self.cfg
        T, N = cfg.steps_per_env, self.N
        B = T * N
        mb = B // cfg.minibatches
        obs = self.obs_buf.reshape(B, -1)
        act = self.act_buf.reshape(B, -1)
        logp_old = self.logp_buf.reshape(B)
        ret = self.ret_buf.reshape(B)
        adv = self.adv_buf.reshape(B)
        val_old = self.val_buf.reshape(B)
        mean_old = self.mean_buf.reshape(B, -1)
        std_old = self.std_buf.reshape(B, -1)
        stats = {"loss/surrogate": 0.0, "loss/value": 0.0, "loss/entropy": 0.0, "ppo/kl": 0.0, "ppo/clip_frac": 0.0}
        n_upd = 0
        for _ in range(cfg.epochs):
            perm = torch.randperm(B, device=self.device)
            for i in range(cfg.minibatches):
                idx = perm[i * mb:(i + 1) * mb]
                d = self.ac.dist(obs[idx])
                logp = d.log_prob(act[idx]).sum(-1)
                ratio = torch.exp(logp - logp_old[idx])
                a = adv[idx]
                surr = -torch.min(ratio * a, ratio.clamp(1 - cfg.clip, 1 + cfg.clip) * a).mean()
                v = self.ac.value(obs[idx])
                v_clipped = val_old[idx] + (v - val_old[idx]).clamp(-cfg.clip, cfg.clip)
                vloss = torch.max((v - ret[idx]) ** 2, (v_clipped - ret[idx]) ** 2).mean()
                ent = d.entropy().sum(-1).mean()
                loss = surr + cfg.value_coef * vloss - cfg.entropy_coef * ent

                with torch.no_grad():
                    # KL(old || new) for diagonal Gaussians
                    std_new = d.stddev
                    kl = (torch.log(std_new / std_old[idx]) + (std_old[idx] ** 2 + (mean_old[idx] - d.mean) ** 2) / (2 * std_new ** 2) - 0.5).sum(-1).mean()
                    if cfg.adaptive_lr:
                        if kl > 2.0 * cfg.kl_target:
                            self.lr = max(1e-5, self.lr / 1.5)
                        elif kl < 0.5 * cfg.kl_target and kl > 0.0:
                            self.lr = min(1e-3, self.lr * 1.5)
                        for g in self.opt.param_groups:
                            g["lr"] = self.lr
                    clip_frac = ((ratio - 1.0).abs() > cfg.clip).float().mean()

                self.opt.zero_grad(set_to_none=True)
                loss.backward()
                nn.utils.clip_grad_norm_(self.ac.parameters(), cfg.max_grad_norm)
                self.opt.step()
                stats["loss/surrogate"] += surr.item(); stats["loss/value"] += vloss.item()
                stats["loss/entropy"] += ent.item(); stats["ppo/kl"] += kl.item(); stats["ppo/clip_frac"] += clip_frac.item()
                n_upd += 1
        for k in stats:
            stats[k] /= n_upd
        stats["ppo/lr"] = self.lr
        stats["ppo/std"] = self.ac.log_std.exp().mean().item()
        self.t = 0
        return stats

    # ---- persistence ----------------------------------------------------------
    def state_dict(self) -> dict:
        return {"ac": self.ac.state_dict(), "opt": self.opt.state_dict(), "lr": self.lr}

    def load_state_dict(self, sd: dict, actor_only: bool = False):
        if actor_only:
            self.ac.actor.load_state_dict({k[len("actor."):]: v for k, v in sd["ac"].items() if k.startswith("actor.")})
            return
        self.ac.load_state_dict(sd["ac"])
        self.opt.load_state_dict(sd["opt"])
        self.lr = sd.get("lr", self.lr)
