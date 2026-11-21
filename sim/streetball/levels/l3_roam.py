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


class L3MovingDribble(L1Traverse):
    name = "l3a_moving_dribble"
    prd_tier = 4
    episode_s = 90.0
    speed_range = (1.5, 2.5)
    course_m = 100.0
    hand_offset = (0.5, 0.35)
    # 2026-11-21: was a hard-coded 1.0 m; the 11-19 user decision moved the dribble target to 0.8 m (band 0.65-1.00), and the
    # Unreal director already sends 0.8 in every dribble tier.
    apex_target = 0.8
    hand_mode = "random"  # "random" (+1/-1 per episode) or "right"

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
        if self.hand_mode == "right":
            self.hand[ids] = 1.0
        else:
            self.hand[ids] = torch.where(env.rand(k) < 0.5, 1.0, -1.0)
        yaw = torch.atan2(env.qpos[ids, env.root_q + 6], env.qpos[ids, env.root_q + 3]) * 2  # from yaw quat (w,0,0,z)
        c, s_ = torch.cos(yaw), torch.sin(yaw)
        xy = env.qpos[ids, env.root_q : env.root_q + 2]
        fwd = torch.stack([c, s_], -1)
        left = torch.stack([-s_, c], -1)
        # 2026-11-21: start ball at the level's own spot, capped at 0.75 m (was 0.3 m forward and up to 0.95 m, inside the palm;
        # the same start bug L2 fixed on 11-19)
        spot = xy + self.hand_offset[0] * fwd - self.hand[ids, None] * self.hand_offset[1] * left
        h = env.rand(k, lo=0.30, hi=0.75)
        vz = -torch.sqrt(2 * 9.81 * (self.apex_target - h)) * torch.where(env.rand(k) < 0.5, 1.0, -1.0)
        env.set_ball(
            ids, torch.cat([spot, h[:, None]], -1), torch.cat([torch.zeros(k, 2, device=self.dev), vz[:, None]], -1)
        )
        env.in_control[ids] = 1.0  # control granted at reset (see l2_dribble.py)
        env.last_palm_contact_t[ids] = env.time[ids]
        self.dist_travelled[ids] = 0.0
        self.control_steps[ids] = 0.0
        self.prev_xy[ids] = xy
        self.prev_floor[ids] = False
        self.apex[ids] = h
        self.bounces[ids] = 0

    def task_block(self, ids):
        loco = super().task_block(None)  # [dir_x, dir_y, dist, speed, ...]
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        tb[:, 0] = self.hand
        tb[:, 1] = self.apex_target
        tb[:, 2] = 0.0  # no commanded hand switches while moving
        tb[:, 3] = loco[:, 3]  # commanded speed
        tb[:, 4:6] = loco[:, 0:2]  # waypoint direction (heading frame)
        tb[:, 6] = loco[:, 2]  # waypoint distance
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
        r_apex = torch.exp(-(((apex_before - self.apex_target) / 0.2) ** 2)) * bounce.float()
        pc = env.palm_ball_contact
        r_palm = torch.where(self.hand > 0, pc[:, 1], pc[:, 0])
        xy = env.p_pelvis[:, :2]
        self.dist_travelled += (xy - self.prev_xy).norm(dim=-1)
        self.prev_xy = xy.clone()
        self.control_steps += env.in_control
        r = (
            r_loco
            + 1.0 * torch.exp(-((spot_d / 0.35) ** 2))
            + 3.0 * r_apex
            + 0.3 * r_palm
            + 0.5 * env.in_control
            - 2.0 * (ball_z - 1.25).clamp(min=0.0)
        )
        return r

    def metrics(self):
        m = super().metrics()
        m.update(
            {
                "m/dist_m": self.dist_travelled,
                "m/control_frac": self.control_steps / self.env.step_count.clamp_min(1).float(),
                "m/bounces": self.bounces.float(),
            }
        )
        return m

    def episode_success(self) -> torch.Tensor:
        env = self.env
        t = env.step_count.clamp_min(1).float() * env.control_dt
        return (
            (self.dist_travelled >= self.course_m)
            & (self.dist_travelled / t >= 1.5)
            & (self.control_steps / env.step_count.clamp_min(1).float() >= 0.9)
            & ~env.fallen
        )

    def terminated(self) -> torch.Tensor:
        env = self.env
        done = self.dist_travelled >= self.course_m
        lost = env.countdown_frac <= 0.0
        off = (env.p_pelvis[:, 0].abs() > 15.5) | (env.p_pelvis[:, 1].abs() > 9.0)
        return done | lost | off


class L3DribbleWalk(L3MovingDribble):
    """TRAINING-ONLY curriculum for the moving dribble (2026-11-21, user decision "walk first"). The stationary brain
    (l2a_time, gate 71 %) has never moved with the ball, so the commanded speed starts at a walk and widens toward the PRD's
    1.5-2.5 m/s. Short legs to nearby waypoints (2-6 m) instead of a 100 m course; right hand only (the stationary brain is
    right-handed); the stationary brain's dribble spot; no arm-carry/pose style penalties (they pull the dribbling arm to the
    rest pose). Promotion: 60 % of finished episodes reach all n_waypoints with the ball in control >= 90 % and no fall.
    Evaluation (train_steps = inf) uses speed stage `eval_stage` (default 0 = walking; the PRD jog is the l3a_moving_dribble gate)."""

    name = "l3a_walk"
    episode_s = 30.0
    n_waypoints = 4
    wp_dist = (2.0, 6.0)
    hand_offset = (0.45, 0.30)
    hand_mode = "right"
    style_penalty_w = 0.0
    speed_stages = ((0.3, 0.8), (0.5, 1.2), (0.8, 1.6), (1.2, 2.0), (1.5, 2.5))
    promote_at = 0.6
    control_min = 0.9
    eval_stage = 0

    def setup(self) -> None:
        self.stage = 0
        self.succ_ema = 0.0
        super().setup()
        self.ep_steps = torch.zeros(self.N, dtype=torch.long, device=self.dev)

    def _stage(self) -> int:
        return self.eval_stage if self.train_steps == float("inf") else self.stage

    def _sample_speed(self, k: int) -> torch.Tensor:
        """Commanded walking speed (m/s) for k new waypoints, given the curriculum stage self._stage(). 75 % from the current
        band, 25 % from the slowest speed up to the current top, so a promoted brain keeps its slow walk (needed to stop
        and shoot later)."""
        env = self.env
        lo, hi = self.speed_stages[self._stage()]
        cur = env.rand(k, lo=lo, hi=hi)
        slow = env.rand(k, lo=self.speed_stages[0][0], hi=hi)
        return torch.where(env.rand(k) < 0.25, slow, cur)

    def _new_waypoint(self, ids: torch.Tensor):
        env = self.env
        k = ids.numel()
        ang = env.rand(k, lo=-3.1416, hi=3.1416)
        d = env.rand(k, lo=self.wp_dist[0], hi=self.wp_dist[1])
        base = env.qpos[ids, env.root_q : env.root_q + 2]  # current root xy (p_pelvis is stale right after set_root_pose)
        wp = base + d[:, None] * torch.stack([torch.cos(ang), torch.sin(ang)], -1)
        wp[:, 0] = wp[:, 0].clamp(-self.court[0], self.court[0])
        wp[:, 1] = wp[:, 1].clamp(-self.court[1], self.court[1])
        self.wp[ids] = wp
        self.speed_cmd[ids] = self._sample_speed(k)

    def on_reset(self, ids: torch.Tensor) -> None:
        if self.train_steps != float("inf") and hasattr(self, "ep_steps"):
            ran = self.ep_steps[ids] > 0  # skip the initial reset of all envs
            if ran.any():
                ok = self.episode_success()[ids][ran].float().mean().item()
                a = min(1.0, int(ran.sum()) / 2000.0)
                self.succ_ema = (1 - a) * self.succ_ema + a * ok
                if self.succ_ema > self.promote_at and self.stage < len(self.speed_stages) - 1:
                    self.stage += 1
                    self.succ_ema = 0.0
                    print(f"[l3a_walk] success > {self.promote_at:.0%}: speed stage -> {self.speed_stages[self.stage]} m/s", flush=True)
        super().on_reset(ids)
        self.ep_steps[ids] = 0

    def reward(self) -> torch.Tensor:
        self.ep_steps += 1
        return super().reward()

    def episode_success(self) -> torch.Tensor:
        ctrl = self.control_steps / self.ep_steps.clamp_min(1).float()
        return (self.reached >= self.n_waypoints) & (ctrl >= self.control_min) & ~self.env.fallen

    def terminated(self) -> torch.Tensor:
        env = self.env
        lost = env.countdown_frac <= 0.0
        off = (env.p_pelvis[:, 0].abs() > 15.5) | (env.p_pelvis[:, 1].abs() > 9.0)
        return (self.reached >= self.n_waypoints) | lost | off

    def metrics(self):
        m = super().metrics()
        m["m/speed_stage"] = torch.full((self.N,), float(self._stage()), device=self.dev)
        m["m/speed_cmd"] = self.speed_cmd.clone()
        m["m/succ_ema"] = torch.full((self.N,), self.succ_ema, device=self.dev)
        return m


class L3Scramble(Level):
    name = "l3b_scramble"
    prd_tier = 4
    episode_s = 5.0

    def setup(self) -> None:
        N, dev = self.N, self.dev
        self._last_action = torch.zeros(N, self.env.N_ACT, device=dev)
        self._prev2_action = torch.zeros(N, self.env.N_ACT, device=dev)
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
        self._prev2_action[ids] = 0.0

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
        sb = obs_spec._S_BALL
        palm = torch.minimum(env.obs[:, sb + 7], env.obs[:, sb + 8])
        r_reach = torch.exp(-((palm / 0.4) ** 2)) * (d < 1.2).float()
        self._m_reach = r_reach
        r = (
            2.0 * progress
            + 1.0 * r_reach
            + 0.3 * torch.exp(-((d / 0.5) ** 2))
            + 0.5 * touch
            + 20.0 * newly.float()
            + 0.7 * self.r_torso_upright()
            + self.penalties()  # torque^2, joint vel^2, action rate^2, foot slip
            - 0.02 * self.p_action_jerk()
        )
        self.track_action()
        return r

    def terminated(self) -> torch.Tensor:
        env = self.env
        # end a bit after regaining so the policy also learns to settle
        settled = self.regained & (env.in_control > 0.5) & (env.v_pelvis[:, :2].norm(dim=-1) < 0.5)
        return settled | (env.countdown_frac <= 0.0)

    def metrics(self):
        return {
            "m/regained": self.regained.float(),
            "m/ball_dist": (self.env.p_ball[:, :2] - self.env.p_pelvis[:, :2]).norm(dim=-1),
            "m/reach": getattr(self, "_m_reach", torch.zeros(self.N, device=self.dev)),
        }

    def episode_success(self) -> torch.Tensor:
        return self.regained & ~self.env.fallen
