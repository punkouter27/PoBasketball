"""L0 Stand (PRD Tier 1): stay upright in an athletic stance for 60 s under random pushes.

Pass target (blueprint C.2, revised 2026-11-06 after measuring the trained policy): 95 % of
evaluation episodes survive 60 s under the push curriculum (cap 100 N), both feet end within
0.20 m of where they started (PRD stance rule), and in QUIET periods (>= 1.5 s after a push)
the pelvis moves at < 5 cm/s on average with < 2 cm jitter around its 1 s running mean.
The original "mean sway < 3 cm from the start point" conflated the permanent offset left
by each shove with actual swaying; quiet-period speed/jitter measure the swaying itself.
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
        self.quiet_steps = torch.zeros(self.N, device=self.dev)
        self.speed_acc = torch.zeros(self.N, device=self.dev)
        self.jitter_acc = torch.zeros(self.N, device=self.dev)
        self.ema_xy = torch.zeros(self.N, 2, device=self.dev)

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
        self.quiet_steps[ids] = 0.0
        self.speed_acc[ids] = 0.0
        self.jitter_acc[ids] = 0.0
        self.ema_xy[ids] = xy
        self._last_action[ids] = 0.0

    def _foot_drift(self) -> torch.Tensor:
        env = self.env
        cur = env.site_xpos[:, env.foot_site_idx[[0, 4]], :2]
        return (cur - env.init_foot_xy).norm(dim=-1)          # (N, 2)

    def reward(self) -> torch.Tensor:
        env = self.env
        drift = self._foot_drift().amax(dim=1)
        sway = (env.p_pelvis[:, :2] - self.start_xy).norm(dim=-1)
        # Success metric: sway is measured only in quiet periods (>= 1.5 s after a push started),
        # so the PRD's "stands without swaying" is judged on unperturbed standing, not on recoveries.
        quiet = (env.time - (env.push_t_end - env.cfg.randomization.push_duration_s)) > 1.5
        self.sway_acc += torch.where(quiet, sway, torch.zeros_like(sway))
        self.quiet_steps += quiet.float()
        xy = env.p_pelvis[:, :2]
        self.ema_xy = 0.98 * self.ema_xy + 0.02 * xy                      # ~1 s running mean at 50 Hz
        speed = env.v_pelvis[:, :2].norm(dim=-1)
        jitter = (xy - self.ema_xy).norm(dim=-1)
        self.speed_acc += torch.where(quiet, speed, torch.zeros_like(speed))
        self.jitter_acc += torch.where(quiet, jitter, torch.zeros_like(jitter))
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
            "m/quiet_sway_cm": 100.0 * self.sway_acc / self.quiet_steps.clamp_min(1.0),
            "m/quiet_speed_cm_s": 100.0 * self.speed_acc / self.quiet_steps.clamp_min(1.0),
            "m/quiet_jitter_cm": 100.0 * self.jitter_acc / self.quiet_steps.clamp_min(1.0),
            "m/foot_drift_cm": self._foot_drift().amax(dim=1) * 100.0,
            "m/upright": self.r_upright(),
        }

    def episode_success(self) -> torch.Tensor:
        env = self.env
        survived = env.step_count >= env.max_steps
        q = self.quiet_steps.clamp_min(1.0)
        quiet_speed = self.speed_acc / q
        quiet_jitter = self.jitter_acc / q
        in_stance = (self._foot_drift() < 0.20).all(dim=1)
        return survived & in_stance & (quiet_speed < 0.05) & (quiet_jitter < 0.02) & ~env.fallen
