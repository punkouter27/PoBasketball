"""L3 approach: walk toward a stationary ball and stop within 0.5 m of its centre.

This level rewards locomotion and stopping only. It has no ball-control, grasp, or lift
objective, so the policy is not trained to dribble or pick the ball up.
"""

from __future__ import annotations

import torch

from streetball import obs as obs_spec
from streetball.levels.base import Level

BALL_R = 0.1205


class L3Approach(Level):
    name = "l3_approach"
    prd_tier = 3
    episode_s = 12.0
    reach_radius = 0.5
    stop_speed = 0.25
    stop_hold_s = 0.5
    pass_fraction = 0.8
    lost_radius = 8.0

    def setup(self) -> None:
        self._last_action = torch.zeros(self.N, self.env.N_ACT, device=self.dev)
        self._prev2_action = torch.zeros(self.N, self.env.N_ACT, device=self.dev)
        self.prev_dist = torch.zeros(self.N, device=self.dev)
        self.settle_t = torch.zeros(self.N, device=self.dev)
        self.done_ok = torch.zeros(self.N, dtype=torch.bool, device=self.dev)

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = ids.numel()
        xy = torch.stack([env.rand(k, lo=-7.0, hi=7.0), env.rand(k, lo=-1.5, hi=1.5)], -1)
        yaw = env.rand(k, lo=-3.1416, hi=3.1416)
        env.set_root_pose(ids, xy, yaw)
        env.qpos[ids[:, None], env.qadr[None, :]] += env.randn(k, env.N_ACT) * 0.03

        dist = env.rand(k, lo=1.5, hi=5.0)
        rel = torch.where(
            env.rand(k) < 0.8,
            env.rand(k, lo=-1.75, hi=1.75),
            env.rand(k, lo=-3.1416, hi=3.1416),
        )
        angle = yaw + rel
        bxy = xy + dist[:, None] * torch.stack([torch.cos(angle), torch.sin(angle)], -1)
        pos = torch.cat([bxy, torch.full((k, 1), BALL_R, device=self.dev)], -1)
        env.set_ball(ids, pos)
        env.in_control[ids] = 0.0
        env.loose_t[ids] = 0.0
        env.countdown_frac[ids] = 1.0
        self.prev_dist[ids] = dist
        self.settle_t[ids] = 0.0
        self.done_ok[ids] = False
        self._last_action[ids] = 0.0
        self._prev2_action[ids] = 0.0

    def _rel(self) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        env = self.env
        d = env.p_ball[:, :2] - env.p_pelvis[:, :2]
        dist = d.norm(dim=-1)
        dir_world = d / dist.clamp_min(1e-6)[:, None]
        fwd, left = env.H[:, :2, 0], env.H[:, :2, 1]
        dir_heading = torch.stack([(dir_world * fwd).sum(-1), (dir_world * left).sum(-1)], -1)
        return dist, dir_heading, dir_world

    def _speed_target(self, dist: torch.Tensor) -> torch.Tensor:
        return (0.2 + 0.35 * (dist - self.reach_radius).clamp(min=0.0)).clamp(max=1.3)

    def task_block(self, ids: torch.Tensor | None) -> torch.Tensor:
        dist, dir_heading, _ = self._rel()
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        tb[:, :2] = dir_heading
        tb[:, 2] = dist.clamp(max=10.0)
        tb[:, 3] = self._speed_target(dist)
        return tb if ids is None else tb[ids]

    def task_mirror(self) -> tuple[list[int], list[float]]:
        sign = [1.0] * obs_spec.N_TASK
        sign[1] = -1.0
        return list(range(obs_spec.N_TASK)), sign

    def reward(self) -> torch.Tensor:
        env = self.env
        dist, dir_heading, dir_world = self._rel()
        speed_target = self._speed_target(dist)
        speed_toward = (env.v_pelvis[:, :2] * dir_world).sum(-1)
        r_speed = torch.exp(-(((speed_toward - speed_target) / 0.5) ** 2))
        progress = (self.prev_dist - dist).clamp(-0.1, 0.1)
        self.prev_dist = dist.clone()
        speed = env.v_pelvis[:, :2].norm(dim=-1)
        near_slow = (dist <= self.reach_radius) & (speed <= self.stop_speed)
        self.settle_t = torch.where(near_slow, self.settle_t + env.control_dt, torch.zeros_like(self.settle_t))
        newly_ok = (self.settle_t >= self.stop_hold_s) & ~self.done_ok
        self.done_ok |= newly_ok
        r_stop = torch.exp(-((speed / self.stop_speed) ** 2))
        stop_zone = (dist <= self.reach_radius + 0.5).float()
        r = (
            1.5 * r_speed
            + 0.3 * dir_heading[:, 0].clamp(min=0.0)
            + 3.0 * progress
            + stop_zone * r_stop
            + 25.0 * newly_ok.float()
            + 0.8 * self.r_torso_upright()
            + 0.3 * self.r_height(width=0.1)
            + 0.15 * self.r_heel_toe_stride()
            + self.penalties()
            - 0.02 * self.p_action_jerk()
            + 0.1
        )
        self._m = {
            "distance": dist,
            "speed_target": speed_target,
            "speed_toward": speed_toward,
            "settle_time": self.settle_t,
            "success": self.done_ok.float(),
        }
        self.track_action()
        return r

    def terminated(self) -> torch.Tensor:
        dist, _, _ = self._rel()
        return self.done_ok | (dist > self.lost_radius)

    def episode_success(self) -> torch.Tensor:
        return self.done_ok

    def episode_fail_reasons(self) -> dict[str, torch.Tensor]:
        dist, _, _ = self._rel()
        return {"ball_lost": dist > self.lost_radius, "not_reached": ~self.done_ok}

    def metrics(self) -> dict[str, torch.Tensor]:
        z = torch.zeros(self.N, device=self.dev)
        m = getattr(self, "_m", {})
        return {
            "m/approach_distance": m.get("distance", z),
            "m/speed_target": m.get("speed_target", z),
            "m/speed_toward": m.get("speed_toward", z),
            "m/settle_time": m.get("settle_time", z),
            "m/success": self.done_ok.float(),
        }
