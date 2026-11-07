"""Adversarial Motion Priors (AMP), ported from MimicKit (xbpeng/MimicKit, learning/amp_agent.py + amp_model.py).

AMP adds a *style* reward: a discriminator D learns to tell short state transitions of the policy from
transitions in a motion-capture dataset, and the policy is paid for transitions D believes are mocap:

    r_style = -log(max(1 - sigmoid(D(s, s')), 1e-4)) * disc_reward_scale        (MimicKit _calc_disc_rewards)
    L_D = 0.5 * (BCE(D(agent), 0) + BCE(D(demo), 1))
          + grad_penalty * 0.5 * (E|dD/dx_demo|^2 + E|dD/dx_agent|^2)          (MimicKit _compute_disc_loss)
          + logit_reg * |w_out|^2

Differences from MimicKit (documented, deliberate):
  * Our MuJoCo Warp env and the frozen 119-float policy interface stay unchanged (Unreal relies on them);
    AMP only changes training. MimicKit's engines (Isaac Gym/Lab, Newton) are not used.
  * Two-frame discriminator input (s_t, s_t+1) at the 50 Hz control rate (MimicKit humanoid default: 10 frames).
  * The style reward is computed online each control step instead of once per batch (same quantity).
  * Adam instead of MimicKit's SGD-based MPOptimizer.

The feature function `amp_features` is the single definition used for both the retargeted mocap
(tools/retarget_loco_mujoco.py) and live rollouts (train_amp.py), so the two distributions are comparable.
"""
from __future__ import annotations

import torch
from torch import nn

KEY_BODIES = ("hand_l", "hand_r", "foot_l", "foot_r", "head")
# Joints without a mocap counterpart are left out of the style features: the retargeted data holds them at
# exactly zero (wrists: zeroed in retargeting; ankle roll: SkeletonTorque subtalar joint is locked), so any real
# motion there would let the discriminator separate policy from mocap trivially (seen in the first smoke test).
EXCLUDED_JOINTS = (4, 5, 10, 11, 17, 23)   # wrist_flex/dev l+r, ankle_roll l+r (humanoid_spec order)
AMP_JOINTS = tuple(i for i in range(27) if i not in EXCLUDED_JOINTS)
N_JOINT = len(AMP_JOINTS)
FEAT_DIM = 1 + 6 + 3 + 3 + N_JOINT + N_JOINT + 3 * len(KEY_BODIES)   # 70 per frame


def quat_to_mat(q: torch.Tensor) -> torch.Tensor:
    """wxyz -> (..., 3, 3) world <- body (same formula as StreetballEnv.quat_to_mat)."""
    w, x, y, z = q.unbind(-1)
    return torch.stack([
        torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
        torch.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
        torch.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1),
    ], -2)


def heading_mat(R: torch.Tensor) -> torch.Tensor:
    """Yaw-only frame of R (same as StreetballEnv.heading_mat)."""
    fwd = R[..., :, 0].clone()
    fwd[..., 2] = 0.0
    n = fwd.norm(dim=-1, keepdim=True)
    fwd = torch.where(n > 1e-6, fwd / n.clamp_min(1e-6), torch.tensor([1.0, 0.0, 0.0], device=fwd.device, dtype=fwd.dtype))
    left = torch.stack([-fwd[..., 1], fwd[..., 0], torch.zeros_like(fwd[..., 0])], -1)
    up = torch.zeros_like(fwd)
    up[..., 2] = 1.0
    return torch.stack([fwd, left, up], -1)


def amp_features(root_pos, root_quat, v_world, w_local, jpos, jvel, key_world) -> torch.Tensor:
    """Per-frame style features, invariant to position on the court and to heading.

    root_pos (N,3), root_quat (N,4) wxyz, v_world (N,3) pelvis linear velocity in world, w_local (N,3) pelvis
    angular velocity in the pelvis frame (MuJoCo free-joint convention), jpos/jvel (N,27) all actuated joints (AMP_JOINTS are selected here) in
    humanoid_spec order, key_world (N,K,3) world positions of KEY_BODIES. Returns (N, FEAT_DIM).
    """
    R = quat_to_mat(root_quat)
    H = heading_mat(R)
    Ht = H.transpose(-1, -2)
    R_h = Ht @ R                                                  # pelvis orientation relative to its heading
    tan_norm = torch.cat([R_h[..., :, 0], R_h[..., :, 2]], -1)    # 6: forward and up axes
    v_h = torch.einsum("nij,nj->ni", Ht, v_world)
    key_rel = torch.einsum("nij,nkj->nki", Ht, key_world - root_pos[:, None, :]).reshape(root_pos.shape[0], -1)
    sel = list(AMP_JOINTS)
    return torch.cat([root_pos[:, 2:3], tan_norm, v_h, w_local, jpos[:, sel], jvel[:, sel], key_rel], -1)


class Discriminator(nn.Module):
    """MimicKit 'fc_2layers_1024units' disc net + linear logit head (uniform init +-1 on the head)."""

    def __init__(self, n_in: int, hidden=(1024, 512)):
        super().__init__()
        layers, d = [], n_in
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU()]
            d = h
        self.body = nn.Sequential(*layers)
        self.logit = nn.Linear(d, 1)
        nn.init.uniform_(self.logit.weight, -1.0, 1.0)
        nn.init.zeros_(self.logit.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.logit(self.body(x)).squeeze(-1)


class FixedNormalizer(nn.Module):
    """Mean/std fitted once on the demo transitions (agent data is normalised with the same statistics)."""

    def __init__(self, data: torch.Tensor, clip: float = 10.0):
        super().__init__()
        self.register_buffer("mean", data.mean(0))
        self.register_buffer("std", data.std(0).clamp_min(1e-2))
        self.clip = clip

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return ((x - self.mean) / self.std).clamp(-self.clip, self.clip)


class AMP:
    """Discriminator, demo data, replay buffer and losses (hyper-parameters from MimicKit amp agent yaml)."""

    def __init__(self, demo_pairs: torch.Tensor, device: torch.device, lr: float = 1e-4, weight_decay: float = 1e-4,
                 grad_penalty: float = 5.0, logit_reg: float = 0.01, reward_scale: float = 2.0,
                 replay_size: int = 200_000, replay_samples: int = 1000, epochs: int = 2, batch: int = 8192):
        self.device = device
        self.demo = demo_pairs.to(device)                         # (M, 2*FEAT_DIM)
        self.norm = FixedNormalizer(self.demo).to(device)
        self.disc = Discriminator(self.demo.shape[1]).to(device)
        self.opt = torch.optim.Adam(self.disc.parameters(), lr=lr, weight_decay=weight_decay)
        self.grad_penalty, self.logit_reg, self.reward_scale = grad_penalty, logit_reg, reward_scale
        self.replay = torch.zeros(replay_size, self.demo.shape[1], device=device)
        self.replay_n, self.replay_i = 0, 0
        self.replay_samples, self.epochs, self.batch = replay_samples, epochs, batch

    @torch.no_grad()
    def reward(self, pairs: torch.Tensor) -> torch.Tensor:
        logits = self.disc(self.norm(pairs))
        prob = torch.sigmoid(logits)
        return -torch.log(torch.clamp(1.0 - prob, min=1e-4)) * self.reward_scale

    def _push_replay(self, x: torch.Tensor):
        n = x.shape[0] if self.replay_n < self.replay.shape[0] else min(x.shape[0], self.replay_samples)
        x = x[torch.randperm(x.shape[0], device=self.device)[:n]]
        idx = (self.replay_i + torch.arange(n, device=self.device)) % self.replay.shape[0]
        self.replay[idx] = x
        self.replay_i = int((self.replay_i + n) % self.replay.shape[0])
        self.replay_n = min(self.replay.shape[0], self.replay_n + n)

    def update(self, agent_pairs: torch.Tensor) -> dict[str, float]:
        """agent_pairs: (B, 2*FEAT_DIM) policy transitions from the last rollout."""
        agent_pairs = agent_pairs.detach()
        stats = {"amp/disc_loss": 0.0, "amp/grad_penalty": 0.0, "amp/agent_acc": 0.0, "amp/demo_acc": 0.0,
                 "amp/agent_logit": 0.0, "amp/demo_logit": 0.0}
        B = agent_pairs.shape[0]
        n_batches = max(1, B // self.batch)
        steps = 0
        for _ in range(self.epochs):
            perm = torch.randperm(B, device=self.device)
            for b in range(n_batches):
                a = agent_pairs[perm[b * self.batch:(b + 1) * self.batch]]
                if self.replay_n > 0:
                    r = self.replay[torch.randint(0, self.replay_n, (a.shape[0],), device=self.device)]
                    a = torch.cat([a, r], 0)
                d = self.demo[torch.randint(0, self.demo.shape[0], (self.batch,), device=self.device)]
                xa = self.norm(a).requires_grad_(True)
                xd = self.norm(d).requires_grad_(True)
                la, ld = self.disc(xa), self.disc(xd)
                bce = nn.functional.binary_cross_entropy_with_logits
                loss = 0.5 * (bce(la, torch.zeros_like(la)) + bce(ld, torch.ones_like(ld)))
                ga = torch.autograd.grad(la.sum(), xa, create_graph=True)[0].pow(2).sum(-1).mean()
                gd = torch.autograd.grad(ld.sum(), xd, create_graph=True)[0].pow(2).sum(-1).mean()
                gp = 0.5 * (ga + gd)
                loss = loss + self.grad_penalty * gp + self.logit_reg * self.disc.logit.weight.pow(2).sum()
                self.opt.zero_grad(set_to_none=True)
                loss.backward()
                self.opt.step()
                steps += 1
                stats["amp/disc_loss"] += float(loss.detach()); stats["amp/grad_penalty"] += float(gp.detach())
                stats["amp/agent_acc"] += float((la < 0).float().mean()); stats["amp/demo_acc"] += float((ld > 0).float().mean())
                stats["amp/agent_logit"] += float(la.mean()); stats["amp/demo_logit"] += float(ld.mean())
        self._push_replay(agent_pairs)
        return {k: v / max(1, steps) for k, v in stats.items()}

    def state_dict(self) -> dict:
        return {"disc": self.disc.state_dict(), "norm": self.norm.state_dict(), "opt": self.opt.state_dict()}
