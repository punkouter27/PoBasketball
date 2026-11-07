"""L1 Traverse (PRD Tier 2): walk/jog to 10 random waypoints across the 28 x 15 m court.

Task block (12): [dir_x, dir_y] to waypoint in heading frame, distance (m, clipped 10),
commanded speed (m/s), 8 zeros.
Pass target (blueprint C.2): 90 % of episodes reach 10 waypoints within 90 s without a fall.
"""
from __future__ import annotations

import torch

from streetball import obs as obs_spec
from streetball.levels.base import Level


class L1Traverse(Level):
    name = "l1_traverse"
    prd_tier = 2
    episode_s = 90.0
    pass_fraction = 0.90
    n_waypoints = 10
    reach_radius = 0.5
    speed_range = (1.2, 3.0)     # floor raised from 0.8 (2026-11-07): slow jogging satisfied the task
    # arm carry (2026-11-07): the policy held the right forearm across the chest. Shoulder pitch (fore-aft
    # swing) stays free; adduction/rotation and, lightly, elbow bend are pulled toward the nominal pose.
    arm_carry_idx = (1, 2, 7, 8)          # shoulder_abd_l, shoulder_rot_l, shoulder_abd_r, shoulder_rot_r
    elbow_idx = (3, 9)
    style_penalty_w = 1.0        # 0 in the AMP variant: style comes from the motion-capture discriminator instead
    court = (13.0, 6.5)          # keep waypoints a metre inside the lines

    def setup(self) -> None:
        N, dev = self.N, self.dev
        self._last_action = torch.zeros(N, self.env.N_ACT, device=dev)
        self.wp = torch.zeros(N, 2, device=dev)
        self.speed_cmd = torch.ones(N, device=dev)
        self.reached = torch.zeros(N, dtype=torch.long, device=dev)
        self.prev_dist = torch.zeros(N, device=dev)
        self.prev_pelvis_z = torch.zeros(N, device=dev)

    def _new_waypoint(self, ids: torch.Tensor):
        env = self.env
        k = ids.numel()
        self.wp[ids] = torch.stack([env.rand(k, lo=-self.court[0], hi=self.court[0]),
                                    env.rand(k, lo=-self.court[1], hi=self.court[1])], -1)
        self.speed_cmd[ids] = env.rand(k, lo=self.speed_range[0], hi=self.speed_range[1])

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = ids.numel()
        xy = torch.stack([env.rand(k, lo=-self.court[0], hi=self.court[0]), env.rand(k, lo=-self.court[1], hi=self.court[1])], -1)
        yaw = env.rand(k, lo=-3.1416, hi=3.1416)
        env.set_root_pose(ids, xy, yaw)
        env.qpos[ids[:, None], env.qadr[None, :]] += env.randn(k, env.N_ACT) * 0.03
        env.set_ball(ids, torch.stack([torch.full((k,), 0.0, device=self.dev), torch.full((k,), 8.0, device=self.dev),
                                       torch.full((k,), 0.1205, device=self.dev)], -1))   # parked off court
        self.reached[ids] = 0
        self._new_waypoint(ids)
        self._last_action[ids] = 0.0
        self.prev_dist[ids] = -1.0

    def _rel(self):
        env = self.env
        d = self.wp - env.p_pelvis[:, :2]
        dist = d.norm(dim=-1)
        # heading frame: env.H columns are (fwd, left, up) in world
        fwd, left = env.H[:, :2, 0], env.H[:, :2, 1]
        dirw = d / dist.clamp_min(1e-6)[:, None]
        return dist, torch.stack([(dirw * fwd).sum(-1), (dirw * left).sum(-1)], -1), fwd

    def task_block(self, ids):
        dist, dir_h, _ = self._rel()
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        tb[:, 0:2] = dir_h
        tb[:, 2] = dist.clamp(max=10.0)
        tb[:, 3] = self.speed_cmd
        return tb if ids is None else tb[ids]

    def reward(self) -> torch.Tensor:
        env = self.env
        dist, dir_h, fwd = self._rel()
        v = env.v_pelvis[:, :2]
        v_toward = (v * (self.wp - env.p_pelvis[:, :2]) / dist.clamp_min(1e-6)[:, None]).sum(-1)
        speed_err = (v_toward - self.speed_cmd).abs()
        r_vel = torch.exp(-(speed_err / 0.5) ** 2)
        r_head = dir_h[:, 0].clamp(min=0.0)                       # facing the waypoint
        progress = torch.where(self.prev_dist >= 0, self.prev_dist - dist, torch.zeros_like(dist))
        self.prev_dist = dist.clone()
        # waypoint reached
        hit = dist < self.reach_radius
        if hit.any():
            ids = hit.nonzero(as_tuple=False).squeeze(-1)
            self.reached[ids] += 1
            self._new_waypoint(ids)
            self.prev_dist[ids] = -1.0
        r = (
            1.0 * r_vel
            + 0.3 * r_head
            + 2.0 * progress
            + 10.0 * hit.float()
            + 0.5 * self.r_upright()
            + 0.3 * self.r_height(width=0.1)
            - 0.05 * self.p_action_rate()
            - 0.001 * self.p_joint_vel()
            - 0.02 * self.style_penalty_w * self.p_pose()
            - 0.5 * self.style_penalty_w * self.p_arm_carry()
            - 1e-5 * self.p_torque()
            + 0.1
        )
        self.track_action()
        return r

    def p_arm_carry(self) -> torch.Tensor:
        dev = self.env.joint_pos() - self.env.nominal
        return (dev[:, list(self.arm_carry_idx)] ** 2).mean(dim=1) + 0.2 * (dev[:, list(self.elbow_idx)] ** 2).mean(dim=1)

    def metrics(self):
        dist, _, _ = self._rel()
        return {"m/waypoints": self.reached.float(), "m/wp_dist": dist,
                "m/speed": self.env.v_pelvis[:, :2].norm(dim=-1), "m/arm_carry": self.p_arm_carry()}

    def episode_success(self) -> torch.Tensor:
        return (self.reached >= self.n_waypoints) & ~self.env.fallen

    def terminated(self) -> torch.Tensor:
        done = self.reached >= self.n_waypoints
        off = (self.env.p_pelvis[:, 0].abs() > 15.5) | (self.env.p_pelvis[:, 1].abs() > 9.0)
        return done | off


class L1TraverseAMP(L1Traverse):
    """Same task, resets, commands and success test as L1Traverse; the hand-written style penalties (pose, arm carry)
    are off because train_amp.py adds the AMP style reward learned from LocoMuJoCo motion capture."""
    name = "l1_traverse_amp"
    style_penalty_w = 0.0
