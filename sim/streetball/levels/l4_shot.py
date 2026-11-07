"""L4 Pull-up jump shot (PRD Tier 5).

Each episode is one shot: start dribbling at a random spot inside the 6.75 m arc facing
the east hoop (±30°). After a random 1-3 s the shoot trigger turns on; the athlete must
gather (both palms on the ball), jump, and release toward the rim. Episode ends when the
ball scores, hits the floor after the release, or 8 s elapse.

Task block (12): hoop (rim centre) position relative to the pelvis in the heading frame (3),
shoot trigger (0/1), time since trigger (s), 7 zeros.

Pass target: >= 30 % of evaluation episodes (shots) score. The PRD milestone (30 % over 20
shots) is checked in the showcase by the Unreal state machine; here pass_fraction = 0.30.
"""
from __future__ import annotations

import torch

from streetball import obs as obs_spec
from streetball.levels.l2_dribble import L2Dribble


class L4JumpShot(L2Dribble):
    name = "l4_jump_shot"
    prd_tier = 5
    episode_s = 8.0
    pass_fraction = 0.30
    rim_h = 3.05
    rim_r = 0.2286

    def setup(self) -> None:
        super().setup()
        N, dev = self.N, self.dev
        self.rim = self.env.rim_center["e"]                 # (3,) world
        self.trigger_t = torch.zeros(N, device=dev)
        self.triggered = torch.zeros(N, dtype=torch.bool, device=dev)
        self.released = torch.zeros(N, dtype=torch.bool, device=dev)
        self.scored = torch.zeros(N, dtype=torch.bool, device=dev)
        self.missed = torch.zeros(N, dtype=torch.bool, device=dev)
        self.jumped = torch.zeros(N, dtype=torch.bool, device=dev)
        self.gathered = torch.zeros(N, dtype=torch.bool, device=dev)
        self.prev_ball_z = torch.zeros(N, device=dev)
        self.release_pos = torch.zeros(N, 3, device=dev)
        self.hold_steps = torch.zeros(N, device=dev)

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = ids.numel()
        # spot inside the arc: 2.0-6.5 m from the rim, random angle in the half court
        ang = env.rand(k, lo=0.35, hi=2.80)                   # radians around the rim, away from the baseline
        dist = env.rand(k, lo=2.0, hi=6.5)
        xy = torch.stack([self.rim[0] - dist * torch.sin(ang), self.rim[1] + dist * torch.cos(ang)], -1)
        xy[:, 0] = xy[:, 0].clamp(max=self.rim[0] - 1.5)
        yaw = torch.atan2(self.rim[1] - xy[:, 1], self.rim[0] - xy[:, 0]) + env.rand(k, lo=-0.5, hi=0.5)
        env.set_root_pose(ids, xy, yaw)
        env.qpos[ids[:, None], env.qadr[None, :]] += env.randn(k, env.N_ACT) * 0.02
        self._set_hand(ids)
        c, s_ = torch.cos(yaw), torch.sin(yaw)
        fwd = torch.stack([c, s_], -1); left = torch.stack([-s_, c], -1)
        spot = xy + self.hand_offset[0] * fwd - self.hand[ids, None] * self.hand_offset[1] * left
        h = env.rand(k, lo=0.4, hi=0.95)
        vz = -torch.sqrt(2 * 9.81 * (1.0 - h)) * torch.where(env.rand(k) < 0.5, 1.0, -1.0)
        env.set_ball(ids, torch.cat([spot, h[:, None]], -1), torch.cat([torch.zeros(k, 2, device=self.dev), vz[:, None]], -1))
        self.start_xy[ids] = xy
        self.streak[ids] = 0; self.bounces[ids] = 0; self.switches[ids] = 0
        self.apex[ids] = h; self.palm_since[ids] = True; self.near_since[ids] = True; self.prev_floor[ids] = False
        self.trigger_t[ids] = env.rand(k, lo=1.0, hi=3.0)
        for t in (self.triggered, self.released, self.scored, self.missed, self.jumped, self.gathered):
            t[ids] = False
        self.prev_ball_z[ids] = h
        self.hold_steps[ids] = 0.0
        self._last_action[ids] = 0.0

    def task_block(self, ids):
        env = self.env
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        rel = self.rim[None] - torch.cat([env.p_pelvis[:, :2], env.p_pelvis[:, 2:3]], -1)
        tb[:, 0:3] = torch.einsum("nji,nj->ni", env.H, rel)
        tb[:, 3] = self.triggered.float()
        tb[:, 4] = ((env.time - self.trigger_t).clamp(min=0.0)) * self.triggered.float()
        return tb if ids is None else tb[ids]

    def reward(self) -> torch.Tensor:
        env = self.env
        self.triggered |= env.time >= self.trigger_t
        pre = ~self.triggered
        ball = env.p_ball; ball_z = ball[:, 2]
        # ---- pre-trigger: plain dribble shaping (parent)
        r_dribble = super().reward()

        # ---- post-trigger phases
        pc = env.palm_ball_contact
        both = (pc[:, 0] > 0) & (pc[:, 1] > 0)
        self.gathered |= self.triggered & both
        self.hold_steps = torch.where(self.triggered & both & ~self.released, self.hold_steps + 1, self.hold_steps)
        pelvis_z = env.p_pelvis[:, 2]
        in_air = (env.foot_contact.sum(dim=1) == 0)
        self.jumped |= self.triggered & self.gathered & in_air & (pelvis_z > env.nominal_root_z + 0.15)
        # release: ball leaves both palms while above shoulder height after a gather
        no_contact = pc.sum(dim=1) == 0
        newly_released = self.triggered & self.gathered & ~self.released & no_contact & (ball_z > 1.6)
        self.release_pos = torch.where(newly_released[:, None], ball, self.release_pos)
        self.released |= newly_released

        # score: ball centre crosses rim height downward inside the rim
        rel = ball - self.rim[None]
        horiz = rel[:, :2].norm(dim=-1)
        crossing = (self.prev_ball_z > self.rim_h) & (ball_z <= self.rim_h) & (horiz < self.rim_r - 0.08)
        newly_scored = self.released & crossing & ~self.scored
        self.scored |= newly_scored
        self.prev_ball_z = ball_z.clone()
        newly_missed = self.released & (env.ball_floor_contact > 0) & ~self.scored & ~self.missed
        self.missed |= newly_missed

        # shaping after release: direction of the ball velocity toward a point above the rim, and arc
        v = env.v_ball
        to_rim = self.rim[None] + torch.tensor([0.0, 0.0, 0.3], device=self.dev) - ball
        cos_dir = (v * to_rim).sum(-1) / (v.norm(dim=-1).clamp_min(1e-3) * to_rim.norm(dim=-1).clamp_min(1e-3))
        r_aim = (cos_dir.clamp(min=0.0) ** 2) * newly_released.float()
        # ballistic closeness at the rim plane (evaluated at release): where would it cross z = rim_h?
        vz = v[:, 2]; dz = self.rim_h - ball_z
        disc = (vz ** 2 - 2 * 9.81 * dz).clamp(min=0.0)
        t_hit = (vz + torch.sqrt(disc)) / 9.81
        land = ball[:, :2] + v[:, :2] * t_hit[:, None]
        miss_d = (land - self.rim[None, :2]).norm(dim=-1)
        r_land = torch.exp(-(miss_d / 0.5) ** 2) * newly_released.float()

        r_post = (
            1.0 * both.float() * (~self.released).float()                   # gather / hold
            + 2.0 * (self.triggered & self.gathered & in_air & ~self.released).float()  # jump with ball
            + 3.0 * r_aim
            + 10.0 * r_land
            + 50.0 * newly_scored.float()
            - 1.0 * (self.triggered & ~self.gathered & (ball_z < 0.3)).float()      # lost it at the gather
            + 0.3 * self.r_upright()
        )
        r = torch.where(pre, r_dribble, r_post - 0.05 * self.p_action_rate() - 1e-5 * self.p_torque())
        return r

    def terminated(self) -> torch.Tensor:
        env = self.env
        horiz = (env.p_ball[:, :2] - env.p_pelvis[:, :2]).norm(dim=-1)
        lost_pre = ~self.triggered & ((env.countdown_frac <= 0.0) | (horiz > 1.5))
        lost_post = self.triggered & ~self.released & (env.time - self.trigger_t > 3.0)
        done_shot = self.scored | self.missed
        return lost_pre | lost_post | done_shot

    def metrics(self):
        return {"m/gathered": self.gathered.float(), "m/jumped": self.jumped.float(), "m/released": self.released.float(),
                "m/scored": self.scored.float(), "m/streak": self.streak.float()}

    def episode_success(self) -> torch.Tensor:
        return self.scored & ~self.env.fallen
