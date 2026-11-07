"""L2 Stationary dribble (PRD Tier 3): L2a right hand, L2b left hand, L2c crossover.

Task block (12) -- the DRIBBLE FAMILY layout, shared with L3a moving dribble (one exported
policy, variants by command): [hand (+1 right / -1 left), target apex height (m), bounces until
the next hand switch (0 when not commanded), commanded speed (m/s, 0 = stationary),
waypoint dir x, dir y (heading frame, 0 when stationary), waypoint distance (m, 0), 5 zeros].

A *bounce* is the rising edge of ball-floor contact. It is *clean* when the apex after
the previous bounce was within the target band, the ball stayed within 0.6 m of the
pelvis horizontally, and the active palm touched the ball between the two bounces.
Pass target: 50 consecutive clean bounces in 85 % (L2a/b) or 80 % with >= 10 hand
switches (L2c) of evaluation episodes.
"""
from __future__ import annotations

import torch

from streetball import obs as obs_spec
from streetball.levels.base import Level


class L2Dribble(Level):
    name = "l2a_dribble_r"
    prd_tier = 3
    episode_s = 30.0
    pass_fraction = 0.85
    mode = "right"               # right | left | crossover
    target_bounces = 50
    apex_band = (0.80, 1.15)
    apex_target = 1.0
    hand_offset = (0.25, 0.35)   # dribble spot: forward, lateral (toward the active hand)

    def setup(self) -> None:
        N, dev = self.N, self.dev
        z = lambda *s, **k: torch.zeros(*s, device=dev, **k)
        self._last_action = z(N, self.env.N_ACT)
        self.hand = torch.ones(N, device=dev)          # +1 right, -1 left
        self.start_xy = z(N, 2)
        self.streak = z(N, dtype=torch.long)
        self.bounces = z(N, dtype=torch.long)
        self.switches = z(N, dtype=torch.long)
        self.until_switch = z(N, dtype=torch.long)
        self.apex = z(N)                               # highest ball z since the last bounce
        self.palm_since = z(N, dtype=torch.bool)       # active palm touched ball since the last bounce
        self.near_since = torch.ones(N, dtype=torch.bool, device=dev)
        self.prev_floor = z(N, dtype=torch.bool)
        self.bounce_event = z(N, dtype=torch.bool)
        self.clean_event = z(N, dtype=torch.bool)

    def _set_hand(self, ids: torch.Tensor):
        env = self.env
        k = ids.numel()
        if self.mode == "right":
            self.hand[ids] = 1.0
        elif self.mode == "left":
            self.hand[ids] = -1.0
        else:
            self.hand[ids] = torch.where(env.rand(k) < 0.5, 1.0, -1.0)
            self.until_switch[ids] = torch.randint(2, 5, (k,), device=self.dev, generator=env.gen)

    def _spot(self) -> torch.Tensor:
        """World-space dribble spot for the active hand (N, 2)."""
        env = self.env
        fwd, left = env.H[:, :2, 0], env.H[:, :2, 1]
        return env.p_pelvis[:, :2] + self.hand_offset[0] * fwd - self.hand[:, None] * self.hand_offset[1] * left

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = ids.numel()
        xy = torch.stack([env.rand(k, lo=-10.0, hi=10.0), env.rand(k, lo=-5.0, hi=5.0)], -1)
        yaw = env.rand(k, lo=-3.1416, hi=3.1416)
        env.set_root_pose(ids, xy, yaw)
        env.qpos[ids[:, None], env.qadr[None, :]] += env.randn(k, env.N_ACT) * 0.02
        self._set_hand(ids)
        # ball just below the active hand at a random point of a dribble cycle
        c, s_ = torch.cos(yaw), torch.sin(yaw)
        fwd = torch.stack([c, s_], -1); left = torch.stack([-s_, c], -1)
        spot = xy + self.hand_offset[0] * fwd - self.hand[ids, None] * self.hand_offset[1] * left
        h = env.rand(k, lo=0.4, hi=0.95)
        vz = -torch.sqrt(2 * 9.81 * (1.0 - h)) * torch.where(env.rand(k) < 0.5, 1.0, -1.0)
        pos = torch.cat([spot, h[:, None]], -1)
        vel = torch.cat([torch.zeros(k, 2, device=self.dev), vz[:, None]], -1)
        env.set_ball(ids, pos, vel)
        self.start_xy[ids] = xy
        self.streak[ids] = 0; self.bounces[ids] = 0; self.switches[ids] = 0
        self.apex[ids] = h; self.palm_since[ids] = True; self.near_since[ids] = True
        self.prev_floor[ids] = False
        self._last_action[ids] = 0.0

    def task_block(self, ids):
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        tb[:, 0] = self.hand
        tb[:, 1] = self.apex_target
        tb[:, 2] = self.until_switch.float() if self.mode == "crossover" else 0.0
        return tb if ids is None else tb[ids]

    def _active_palm_contact(self) -> torch.Tensor:
        pc = self.env.palm_ball_contact            # (N, 2) = (left, right)
        return torch.where(self.hand > 0, pc[:, 1], pc[:, 0]) > 0

    def _active_palm_dist(self) -> torch.Tensor:
        o = self.env.obs
        return torch.where(self.hand > 0, o[:, 98], o[:, 97])

    def reward(self) -> torch.Tensor:
        env = self.env
        ball_z = env.p_ball[:, 2]
        horiz = (env.p_ball[:, :2] - env.p_pelvis[:, :2]).norm(dim=-1)
        spot_d = (env.p_ball[:, :2] - self._spot()).norm(dim=-1)

        # ---- bounce bookkeeping
        floor = env.ball_floor_contact > 0
        self.bounce_event = floor & ~self.prev_floor
        self.prev_floor = floor
        apex_before = self.apex.clone()                        # apex of the flight that just ended
        self.apex = torch.where(self.bounce_event, ball_z, torch.maximum(self.apex, ball_z))
        self.palm_since |= self._active_palm_contact()
        self.near_since &= horiz < 0.6
        clean = self.bounce_event & self.palm_since & self.near_since & (apex_before >= self.apex_band[0]) & (apex_before <= self.apex_band[1])
        self.clean_event = clean
        self.streak = torch.where(clean, self.streak + 1, torch.where(self.bounce_event, torch.zeros_like(self.streak), self.streak))
        self.bounces += self.bounce_event.long()
        if self.mode == "crossover":
            self.until_switch = torch.where(clean, self.until_switch - 1, self.until_switch)
            sw = clean & (self.until_switch <= 0)
            if sw.any():
                ids = sw.nonzero(as_tuple=False).squeeze(-1)
                self.hand[ids] = -self.hand[ids]
                self.switches[ids] += 1
                self.until_switch[ids] = torch.randint(2, 5, (ids.numel(),), device=self.dev, generator=env.gen)
        self.palm_since = torch.where(self.bounce_event, torch.zeros_like(self.palm_since), self.palm_since)
        self.near_since = torch.where(self.bounce_event, torch.ones_like(self.near_since), self.near_since)

        # ---- shaping
        r_spot = torch.exp(-(spot_d / 0.25) ** 2)
        r_palm = torch.exp(-(self._active_palm_dist() / 0.25) ** 2) * (ball_z > 0.5).float()
        r_apex = torch.exp(-((apex_before - self.apex_target) / 0.15) ** 2) * self.bounce_event.float()
        p_high = (ball_z - 1.25).clamp(min=0.0)                   # carrying / holding
        p_drift = (env.p_pelvis[:, :2] - self.start_xy).norm(dim=-1)
        r = (
            1.0 * r_spot
            + 0.5 * r_palm
            + 5.0 * r_apex
            + 3.0 * clean.float()
            + 0.5 * self.r_upright()
            + 0.3 * self.r_height(width=0.1)
            - 2.0 * p_high
            - 0.5 * p_drift
            - 0.05 * self.p_action_rate()
            - 0.001 * self.p_joint_vel()
            - 0.02 * self.p_pose()
            - 1e-5 * self.p_torque()
            + 0.1
        )
        self.track_action()
        return r

    def terminated(self) -> torch.Tensor:
        env = self.env
        horiz = (env.p_ball[:, :2] - env.p_pelvis[:, :2]).norm(dim=-1)
        lost = (env.countdown_frac <= 0.0) | (horiz > 1.5)
        drifted = (env.p_pelvis[:, :2] - self.start_xy).norm(dim=-1) > 0.5
        return lost | drifted | (self.streak >= self.target_bounces)

    def metrics(self):
        return {"m/streak": self.streak.float(), "m/bounces": self.bounces.float(),
                "m/apex": self.apex, "m/switches": self.switches.float(),
                "m/in_control": self.env.in_control}

    def episode_success(self) -> torch.Tensor:
        ok = self.streak >= self.target_bounces
        if self.mode == "crossover":
            ok &= self.switches >= 10
        return ok


class L2DribbleLeft(L2Dribble):
    name = "l2b_dribble_l"
    mode = "left"


class L2Crossover(L2Dribble):
    name = "l2c_crossover"
    mode = "crossover"
    pass_fraction = 0.80
