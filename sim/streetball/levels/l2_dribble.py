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
        self.last_apex = torch.full((N,), 1.0, device=dev)   # apex of the most recent completed flight

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
        self._assist_reset(ids)
        # Grant ball control at the start (mirrors the Unreal director): a ball not touched by a palm
        # within 0.6 s becomes loose and the 3 s countdown ends the episode. This rules out foot/shin
        # juggling, which the first queue run learned instead of a hand dribble.
        env.in_control[ids] = 1.0
        env.last_palm_contact_t[ids] = env.time[ids]
        self.start_xy[ids] = xy
        self.streak[ids] = 0; self.bounces[ids] = 0; self.switches[ids] = 0
        self.apex[ids] = h; self.palm_since[ids] = True; self.near_since[ids] = True
        self.prev_floor[ids] = False
        self.last_apex[ids] = 1.0
        self._last_action[ids] = 0.0

    def assist_prob(self) -> float:
        """Start-state curriculum (2026-11-08, queue r4): share of TRAINING resets that launch the ball up into the
        active palm, so the policy experiences touches it never found by exploration (r2/r3: palm touched the ball in
        < 0.1 % of steps after 250 M steps). 75 % -> 15 % over 150 M steps; 0 in evaluation (train_steps = inf)."""
        if self.train_steps == float("inf"):
            return 0.0
        return 0.15 + 0.60 * max(0.0, 1.0 - self.train_steps / 150e6)

    def _assist_reset(self, ids: torch.Tensor) -> None:
        p = self.assist_prob()
        if p <= 0.0:
            return
        env = self.env
        aid = ids[env.rand(ids.numel()) < p]
        if aid.numel() == 0:
            return
        env.forward()                                   # palm site positions for the new root pose
        palm = torch.where((self.hand[aid] > 0)[:, None], env.site_xpos[aid, env.palm_r_s], env.site_xpos[aid, env.palm_l_s])
        # ball in hand: centre one radius (12 cm) under the palm site, rising 0.8 m/s into it
        z0 = (palm[:, 2] - 0.15).clamp(min=0.15)          # 3 cm gap: spawning in overlap ejects the ball
        vel = torch.zeros(aid.numel(), 3, device=self.dev)
        vel[:, 2] = 0.8
        env.set_ball(aid, torch.cat([palm[:, :2], z0[:, None]], -1), vel)

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
        self.last_apex = torch.where(self.bounce_event, apex_before, self.last_apex)
        healthy = (self.last_apex >= 0.6).float()              # a real dribble, not a micro-bounce tap
        # proportional, not a step: every centimetre of extra height reduces the cost
        p_tap = self.bounce_event.float() * ((0.6 - apex_before) / 0.6).clamp(min=0.0)
        touch = self._active_palm_contact()
        first_touch = touch & ~self.palm_since                 # first active-palm touch of this bounce cycle
        self.palm_since |= touch
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
        r_spot = torch.exp(-(spot_d / 0.25) ** 2) * (0.3 + 0.7 * healthy)   # staying near the spot pays mostly for real dribbles
        r_palm = torch.exp(-(self._active_palm_dist() / 0.25) ** 2) * (ball_z > 0.5).float()
        # Reach shaping (2026-11-08, queue r3): r_palm is ~0 at the 0.7 m palm-ball gap the policy starts with and
        # the ball rarely rises above 0.5 m, so nothing pulled the hand to the ball (palm touched it in 0.1 % of
        # steps). Wide kernel to a point 12 cm ABOVE the ball (pressing from above, not carrying from below).
        palm_site = torch.where((self.hand > 0)[:, None], self.env.site_xpos[:, self.env.palm_r_s], self.env.site_xpos[:, self.env.palm_l_s])
        above = env.p_ball + torch.tensor([0.0, 0.0, 0.12], device=self.dev)
        r_reach = torch.exp(-((palm_site - above).norm(dim=-1) / 0.4) ** 2) * (ball_z > 0.25).float()
        r_apex = torch.exp(-((apex_before - self.apex_target) / 0.25) ** 2) * self.bounce_event.float()
        # Dense shaping (added after the first queue run learned a 20 cm "tap" dribble): while the ball
        # rises, reward the apex it is heading for, apex_pred = z + vz^2 / 2g, against the target.
        vz = env.v_ball[:, 2]
        apex_pred = ball_z + (vz.clamp(min=0.0) ** 2) / (2 * 9.81)
        rising = (vz > 0.2) & (ball_z > 0.13)
        # monotonic up to the target (linear), then a penalty above 1.3 m (carrying / throwing)
        r_apex_dense = ((apex_pred / self.apex_target).clamp(max=1.0) - 2.0 * (apex_pred - 1.3).clamp(min=0.0)) * rising.float()
        p_high = (ball_z - 1.25).clamp(min=0.0)                   # carrying / holding
        p_drift = (env.p_pelvis[:, :2] - self.start_xy).norm(dim=-1)
        r = (
            1.0 * r_spot
            + 0.5 * r_palm
            + 1.0 * r_reach
            + 2.0 * first_touch.float()                               # one touch bonus per bounce cycle at most
            + 5.0 * r_apex
            + 2.0 * r_apex_dense
            + 3.0 * clean.float()
            - 1.0 * p_tap                                             # micro-bounces (< 0.5 m apex) cost
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
        self._m_touch, self._m_reach = touch.float(), r_reach
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
                "m/in_control": self.env.in_control,
                "m/palm_touch": getattr(self, "_m_touch", torch.zeros(self.N, device=self.dev)),
                "m/reach": getattr(self, "_m_reach", torch.zeros(self.N, device=self.dev))}

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


class L2DribbleCycles(L2Dribble):
    """TRAINING-ONLY curriculum for L2a (2026-11-08, dribble approach #6): short episodes of K push->bounce->peak
    cycles, K doubling 1 -> 16 as the policy succeeds. Why: in L2Dribble a push is only scored at the floor contact
    after the NEXT flight (~2 bounces, ~1.5 s later), and four runs never linked pushing to reward. Here each cycle is
    scored at the very next peak (~0.4 s after the push), and short episodes keep the credit horizon short.

    Cycle: starts at a peak (or at reset, ball rising into the palm), ends at the next peak after a floor bounce.
    Success: the active palm touched the ball during the cycle, the new peak is in the apex band, and the ball is
    within 0.3 m of the dribble spot. Episode ends after K cycles (success = all K clean) or on the usual loss rules.
    Same obs/action interface and task block as L2Dribble; graduation is still judged on l2a_dribble_r."""
    name = "l2a_cycles"
    k_max = 16
    promote_at = 0.6           # rolling success rate of finished episodes that doubles K

    def setup(self) -> None:
        super().setup()
        N, dev = self.N, self.dev
        self.armed = torch.zeros(N, dtype=torch.bool, device=dev)      # ball has bounced and is rising again
        self.touch_cycle = torch.zeros(N, dtype=torch.bool, device=dev)
        self.peak = torch.zeros(N, device=dev)
        self.cycles = torch.zeros(N, dtype=torch.long, device=dev)
        self.cycles_ok = torch.zeros(N, dtype=torch.long, device=dev)
        self.k = 1
        self.succ_ema = 0.0
        self.peak_event = torch.zeros(N, dtype=torch.bool, device=dev)

    def assist_prob(self) -> float:
        return 1.0                                  # every episode starts with the ball rising into the palm

    def on_reset(self, ids: torch.Tensor) -> None:
        if self.train_steps != float("inf") and hasattr(self, "cycles"):
            ran = self.env.step_count[ids] > 0      # skip the initial reset of all envs
            if ran.any():
                ok = (self.cycles_ok[ids][ran] >= self.k).float().mean().item()
                n = int(ran.sum())
                a = min(1.0, n / 2000.0)
                self.succ_ema = (1 - a) * self.succ_ema + a * ok
                if self.succ_ema > self.promote_at and self.k < self.k_max:
                    self.k *= 2
                    self.succ_ema = 0.0
                    print(f"[l2a_cycles] success > {self.promote_at:.0%}: K -> {self.k} cycles per episode", flush=True)
        super().on_reset(ids)
        self.armed[ids] = False; self.touch_cycle[ids] = False; self.peak[ids] = 0.0
        self.cycles[ids] = 0; self.cycles_ok[ids] = 0

    def reward(self) -> torch.Tensor:
        r = super().reward()
        env = self.env
        bz, vz = env.p_ball[:, 2], env.v_ball[:, 2]
        self.touch_cycle |= self._active_palm_contact()
        self.armed |= self.bounce_event
        self.peak = torch.where(self.bounce_event, bz, torch.maximum(self.peak, bz))
        # the peak after a bounce: ball starts falling, or the palm meets it on the way up
        ev = self.armed & ~self.bounce_event & ((vz <= 0.0) | self._active_palm_contact())
        near = (env.p_ball[:, :2] - self._spot()).norm(dim=-1) < 0.3
        in_band = (self.peak >= self.apex_band[0]) & (self.peak <= self.apex_band[1])
        ok = ev & self.touch_cycle & in_band & near
        r_peak = (6.0 * torch.exp(-((self.peak - self.apex_target) / 0.2) ** 2) + 2.0 * near.float()) * (ev & self.touch_cycle).float()
        self.cycles += ev.long()
        self.cycles_ok += ok.long()
        self.peak_event = ev
        self.armed &= ~ev
        self.touch_cycle &= ~ev
        return r + r_peak + 4.0 * ok.float()

    def terminated(self) -> torch.Tensor:
        return super().terminated() | (self.cycles >= self.k)

    def episode_success(self) -> torch.Tensor:
        return self.cycles_ok >= self.k

    def metrics(self):
        m = super().metrics()
        m["m/k_cycles"] = torch.full((self.N,), float(self.k), device=self.dev)
        m["m/cycle_ok"] = self.cycles_ok.float()
        m["m/succ_ema"] = torch.full((self.N,), self.succ_ema, device=self.dev)
        return m
