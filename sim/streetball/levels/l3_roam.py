"""L3a Moving dribble and L3b Scramble (PRD Tier 4).

L3a task block uses the DRIBBLE FAMILY layout (see l2_dribble.py): [hand, apex target,
bounces-to-switch (0), commanded speed, dir_x, dir_y, distance, 5 zeros]. L3a is the last
curriculum stage of the single exported "dribble" policy. Success: >= 100 m of waypoint course
covered at >= 1.5 m/s mean speed with the ball in control >= 90 % of the time, no fall.

L3b task block: [countdown remaining fraction, 11 zeros] (ball state is in the base obs).
Starts from a loose ball 0.5-4 m away, rolling or bouncing, countdown already running.
Success: control regained within 3.0 s.
"""
from __future__ import annotations

import torch

from streetball import obs as obs_spec
from streetball.levels.base import Level
from streetball.levels.l1_traverse import L1Traverse
from streetball.levels.l2_dribble import L2Dribble


class L3MovingDribble(L1Traverse):
    name = "l3a_moving_dribble"
    prd_tier = 4
    episode_s = 90.0
    pass_fraction = 0.75
    speed_range = (1.5, 2.5)
    course_m = 100.0
    hand_offset = (0.5, 0.35)

    def setup(self) -> None:
        super().setup()
        N, dev = self.N, self.dev
        self.hand = torch.ones(N, device=dev)
        self.dist_travelled = torch.zeros(N, device=dev)
        self.control_steps = torch.zeros(N, device=dev)
        self.prev_xy = torch.zeros(N, 2, device=dev)
        self.prev_floor = torch.zeros(N, dtype=torch.bool, device=dev)
        self.apex = torch.zeros(N, device=dev)
        self.bounces = torch.zeros(N, dtype=torch.long, device=dev)

    def on_reset(self, ids: torch.Tensor) -> None:
        super().on_reset(ids)
        env = self.env
        k = ids.numel()
        self.hand[ids] = torch.where(env.rand(k) < 0.5, 1.0, -1.0)
        yaw = torch.atan2(env.qpos[ids, env.root_q + 6], env.qpos[ids, env.root_q + 3]) * 2  # from yaw quat (w,0,0,z)
        c, s_ = torch.cos(yaw), torch.sin(yaw)
        xy = env.qpos[ids, env.root_q:env.root_q + 2]
        fwd = torch.stack([c, s_], -1); left = torch.stack([-s_, c], -1)
        spot = xy + 0.3 * fwd - self.hand[ids, None] * self.hand_offset[1] * left
        h = env.rand(k, lo=0.4, hi=0.95)
        vz = -torch.sqrt(2 * 9.81 * (1.0 - h)) * torch.where(env.rand(k) < 0.5, 1.0, -1.0)
        env.set_ball(ids, torch.cat([spot, h[:, None]], -1), torch.cat([torch.zeros(k, 2, device=self.dev), vz[:, None]], -1))
        env.in_control[ids] = 1.0                      # control granted at reset (see l2_dribble.py)
        env.last_palm_contact_t[ids] = env.time[ids]
        self.dist_travelled[ids] = 0.0; self.control_steps[ids] = 0.0
        self.prev_xy[ids] = xy; self.prev_floor[ids] = False; self.apex[ids] = h; self.bounces[ids] = 0

    def task_block(self, ids):
        loco = super().task_block(None)                 # [dir_x, dir_y, dist, speed, ...]
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        tb[:, 0] = self.hand
        tb[:, 1] = 1.0                                  # apex target
        tb[:, 2] = 0.0                                  # no commanded hand switches while moving
        tb[:, 3] = loco[:, 3]                           # commanded speed
        tb[:, 4:6] = loco[:, 0:2]                       # waypoint direction (heading frame)
        tb[:, 6] = loco[:, 2]                           # waypoint distance
        return tb if ids is None else tb[ids]

    def reward(self) -> torch.Tensor:
        env = self.env
        r_loco = super().reward()
        # ball terms (dribble spot ahead and to the hand side)
        fwd, left = env.H[:, :2, 0], env.H[:, :2, 1]
        spot = env.p_pelvis[:, :2] + self.hand_offset[0] * fwd - self.hand[:, None] * self.hand_offset[1] * left
        spot_d = (env.p_ball[:, :2] - spot).norm(dim=-1)
        ball_z = env.p_ball[:, 2]
        floor = env.ball_floor_contact > 0
        bounce = floor & ~self.prev_floor
        self.prev_floor = floor
        apex_before = self.apex.clone()
        self.apex = torch.where(bounce, ball_z, torch.maximum(self.apex, ball_z))
        self.bounces += bounce.long()
        r_apex = torch.exp(-((apex_before - 1.0) / 0.2) ** 2) * bounce.float()
        pc = env.palm_ball_contact
        r_palm = torch.where(self.hand > 0, pc[:, 1], pc[:, 0])
        xy = env.p_pelvis[:, :2]
        self.dist_travelled += (xy - self.prev_xy).norm(dim=-1)
        self.prev_xy = xy.clone()
        self.control_steps += env.in_control
        r = (r_loco
             + 1.0 * torch.exp(-(spot_d / 0.35) ** 2)
             + 3.0 * r_apex
             + 0.3 * r_palm
             + 0.5 * env.in_control
             - 2.0 * (ball_z - 1.25).clamp(min=0.0))
        return r

    def metrics(self):
        m = super().metrics()
        m.update({"m/dist_m": self.dist_travelled, "m/control_frac": self.control_steps / self.env.step_count.clamp_min(1).float(),
                  "m/bounces": self.bounces.float()})
        return m

    def episode_success(self) -> torch.Tensor:
        env = self.env
        t = env.step_count.clamp_min(1).float() * env.control_dt
        return ((self.dist_travelled >= self.course_m) & (self.dist_travelled / t >= 1.5)
                & (self.control_steps / env.step_count.clamp_min(1).float() >= 0.9) & ~env.fallen)

    def terminated(self) -> torch.Tensor:
        env = self.env
        done = self.dist_travelled >= self.course_m
        lost = env.countdown_frac <= 0.0
        off = (env.p_pelvis[:, 0].abs() > 15.5) | (env.p_pelvis[:, 1].abs() > 9.0)
        return done | lost | off


class L3Scramble(Level):
    name = "l3b_scramble"
    prd_tier = 4
    episode_s = 5.0
    pass_fraction = 0.80

    def setup(self) -> None:
        N, dev = self.N, self.dev
        self._last_action = torch.zeros(N, self.env.N_ACT, device=dev)
        self.regained = torch.zeros(N, dtype=torch.bool, device=dev)
        self.prev_dist = torch.zeros(N, device=dev)

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = ids.numel()
        xy = torch.stack([env.rand(k, lo=-9.0, hi=9.0), env.rand(k, lo=-4.0, hi=4.0)], -1)
        yaw = env.rand(k, lo=-3.1416, hi=3.1416)
        env.set_root_pose(ids, xy, yaw)
        env.qpos[ids[:, None], env.qadr[None, :]] += env.randn(k, env.N_ACT) * 0.03
        ang = env.rand(k, lo=-3.1416, hi=3.1416)
        # curriculum: nearer balls for the first 50 M training steps (evaluation always uses 0.5-4 m)
        dist = env.rand(k, lo=0.5, hi=2.5 if self.train_steps < 50e6 else 4.0)
        bxy = xy + dist[:, None] * torch.stack([torch.cos(ang), torch.sin(ang)], -1)
        bouncing = env.rand(k) < 0.5
        bz = torch.where(bouncing, env.rand(k, lo=0.2, hi=1.0), torch.full((k,), 0.1205, device=self.dev))
        vxy = env.randn(k, 2) * 1.5
        pos = torch.cat([bxy, bz[:, None]], -1)
        vel = torch.cat([vxy, torch.zeros(k, 1, device=self.dev)], -1)
        env.set_ball(ids, pos, vel)
        # countdown is already running
        env.in_control[ids] = 0.0
        env.loose_t[ids] = 0.0
        env.countdown_frac[ids] = 1.0
        self.regained[ids] = False
        self.prev_dist[ids] = dist
        self._last_action[ids] = 0.0

    def task_block(self, ids):
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        tb[:, 0] = self.env.countdown_frac
        return tb if ids is None else tb[ids]

    def reward(self) -> torch.Tensor:
        env = self.env
        d = (env.p_ball[:, :2] - env.p_pelvis[:, :2]).norm(dim=-1)
        progress = self.prev_dist - d
        self.prev_dist = d.clone()
        newly = (env.in_control > 0.5) & ~self.regained
        self.regained |= newly
        touch = env.palm_ball_contact.amax(dim=1)
        # Reach shaping (2026-11-08): regaining needs a palm touch, which the first queue never found (0 % regained).
        # Pulls the nearer palm to the ball once the athlete is within 1.2 m of it (obs 97/98 = palm-ball distances).
        palm = torch.minimum(env.obs[:, 97], env.obs[:, 98])
        r_reach = torch.exp(-(palm / 0.4) ** 2) * (d < 1.2).float()
        self._m_reach = r_reach
        r = (2.0 * progress
             + 1.0 * r_reach
             + 0.3 * torch.exp(-(d / 0.5) ** 2)
             + 0.5 * touch
             + 20.0 * newly.float()
             + 0.5 * self.r_upright()
             - 0.05 * self.p_action_rate()
             - 0.001 * self.p_joint_vel()
             - 1e-5 * self.p_torque())
        self.track_action()
        return r

    def terminated(self) -> torch.Tensor:
        env = self.env
        # end a bit after regaining so the policy also learns to settle
        settled = self.regained & (env.in_control > 0.5) & (env.v_pelvis[:, :2].norm(dim=-1) < 0.5)
        return settled | (env.countdown_frac <= 0.0)

    def metrics(self):
        return {"m/regained": self.regained.float(), "m/ball_dist": (self.env.p_ball[:, :2] - self.env.p_pelvis[:, :2]).norm(dim=-1),
                "m/reach": getattr(self, "_m_reach", torch.zeros(self.N, device=self.dev))}

    def episode_success(self) -> torch.Tensor:
        return self.regained & ~self.env.fallen
