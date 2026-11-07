"""L0 Stand (PRD Tier 1): stay upright in an athletic stance for 60 s under random pushes.

Pass target (blueprint C.2): 95 % of evaluation episodes survive 60 s with pushes up to
150 N; mean pelvis sway < 3 cm.
"""
from __future__ import annotations

import torch

from streetball.levels.base import Level


class L0Stand(Level):
    name = "l0_stand"
    prd_tier = 1
    episode_s = 60.0
    pass_fraction = 0.95
    foot_move_limit = 0.35       # m; termination. Success still requires staying within 0.20 m (PRD stance rule)

    def setup(self) -> None:
        self._last_action = torch.zeros(self.N, self.env.N_ACT, device=self.dev)
        self.start_xy = torch.zeros(self.N, 2, device=self.dev)
        self.sway_acc = torch.zeros(self.N, device=self.dev)

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = ids.numel()
        # random spot on the court, random heading; ball parked out of the way
        xy = torch.stack([env.rand(k, lo=-10.0, hi=10.0), env.rand(k, lo=-5.0, hi=5.0)], -1)
        yaw = env.rand(k, lo=-3.1416, hi=3.1416)
        env.set_root_pose(ids, xy, yaw)
        # small joint perturbation so the policy sees varied starts
        env.qpos[ids[:, None], env.qadr[None, :]] += env.randn(k, env.N_ACT) * 0.03
        env.set_ball(ids, xy.new_tensor([[0.0, 0.0, 0.1205]]).repeat(k, 1) + torch.stack(
            [xy[:, 0] + 3.0, xy[:, 1], torch.zeros(k, device=self.dev)], -1))
        self.start_xy[ids] = xy
        self.sway_acc[ids] = 0.0
        self._last_action[ids] = 0.0

    def _foot_drift(self) -> torch.Tensor:
        env = self.env
        cur = env.site_xpos[:, env.foot_site_idx[[0, 4]], :2]
        return (cur - env.init_foot_xy).norm(dim=-1)          # (N, 2)

    def reward(self) -> torch.Tensor:
        env = self.env
        drift = self._foot_drift().amax(dim=1)
        sway = (env.p_pelvis[:, :2] - self.start_xy).norm(dim=-1)
        self.sway_acc += sway
        r = (
            1.0 * self.r_upright()
            + 0.5 * self.r_height()
            + 0.5 * torch.exp(-(sway / 0.05) ** 2)
            - 2.0 * drift
            - 0.05 * self.p_action_rate()
            - 0.002 * self.p_joint_vel()
            - 0.1 * self.p_pose()
            - 1e-5 * self.p_torque()
            + 0.2                                                    # alive bonus
        )
        self.track_action()
        return r

    def terminated(self) -> torch.Tensor:
        return (self._foot_drift() > self.foot_move_limit).any(dim=1)

    def metrics(self) -> dict[str, torch.Tensor]:
        env = self.env
        return {
            "m/sway_cm": (env.p_pelvis[:, :2] - self.start_xy).norm(dim=-1) * 100.0,
            "m/foot_drift_cm": self._foot_drift().amax(dim=1) * 100.0,
            "m/upright": self.r_upright(),
        }

    def episode_success(self) -> torch.Tensor:
        env = self.env
        survived = env.step_count >= env.max_steps
        mean_sway = self.sway_acc / env.step_count.clamp_min(1).float()
        in_stance = (self._foot_drift() < 0.20).all(dim=1)
        return survived & (mean_sway < 0.03) & in_stance
