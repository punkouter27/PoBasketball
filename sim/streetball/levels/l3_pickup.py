"""L3c two-handed pickup (2026-11-24, owner: "picking up a ball with both hands"). New skill, own policy family (preview
only until it passes; no director row yet).

A ball rests (or rolls slowly) on the court 0.4-2.5 m away. Walk to it, crouch, take it between BOTH palms, lift it to
chest height and hold it there. Success: both palms on the ball with its centre above hold_z for hold_s seconds.

Task block: slot 0 = 1.0 (the scramble brain this starts from reads its countdown there; a full countdown = "no rush").
The task is left/right symmetric (identity task mirror), so the symmetry loss can be used.
"""

from __future__ import annotations

import torch

from streetball import obs as obs_spec
from streetball.levels.base import Level

BALL_R = 0.1205


class L3Pickup(Level):
    name = "l3c_pickup"
    prd_tier = 4
    episode_s = 8.0
    hold_z = 0.75  # ball centre height (m) that counts as lifted: about the navel / lower chest
    hold_s = 1.0
    near_curriculum_steps = 60e6  # nearer balls first (training only; evaluation always 0.4-2.5 m)

    @property
    def pass_fraction(self) -> float:
        return 0.8  # same bar as the scramble (shared/reward_config.json has no row for this new level)

    def setup(self) -> None:
        N, dev = self.N, self.dev
        self._last_action = torch.zeros(N, self.env.N_ACT, device=dev)
        self._prev2_action = torch.zeros(N, self.env.N_ACT, device=dev)
        self.prev_dist = torch.zeros(N, device=dev)
        self.hold_t = torch.zeros(N, device=dev)
        self.max_lift = torch.zeros(N, device=dev)
        self.both_ever = torch.zeros(N, dtype=torch.bool, device=dev)
        self.done_ok = torch.zeros(N, dtype=torch.bool, device=dev)

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = ids.numel()
        xy = torch.stack([env.rand(k, lo=-9.0, hi=9.0), env.rand(k, lo=-4.0, hi=4.0)], -1)
        yaw = env.rand(k, lo=-3.1416, hi=3.1416)
        env.set_root_pose(ids, xy, yaw)
        env.qpos[ids[:, None], env.qadr[None, :]] += env.randn(k, env.N_ACT) * 0.03
        far = 1.0 if self.train_steps < self.near_curriculum_steps else 2.5
        dist = env.rand(k, lo=0.4, hi=far)
        # mostly in front (+-100 deg of the heading), sometimes anywhere
        rel = torch.where(env.rand(k) < 0.8, env.rand(k, lo=-1.75, hi=1.75), env.rand(k, lo=-3.1416, hi=3.1416))
        ang = yaw + rel
        bxy = xy + dist[:, None] * torch.stack([torch.cos(ang), torch.sin(ang)], -1)
        pos = torch.cat([bxy, torch.full((k, 1), BALL_R, device=self.dev)], -1)
        rolling = env.rand(k) < 0.3
        vxy = env.randn(k, 2) * 0.3 * rolling[:, None].float()
        vel = torch.cat([vxy, torch.zeros(k, 1, device=self.dev)], -1)
        env.set_ball(ids, pos, vel)
        env.in_control[ids] = 0.0
        env.loose_t[ids] = 0.0
        env.countdown_frac[ids] = 1.0
        self.prev_dist[ids] = dist
        self.hold_t[ids] = 0.0
        self.max_lift[ids] = 0.0
        self.both_ever[ids] = False
        self.done_ok[ids] = False
        self._last_action[ids] = 0.0
        self._prev2_action[ids] = 0.0

    def task_block(self, ids):
        tb = torch.zeros(self.N, obs_spec.N_TASK, device=self.dev)
        tb[:, 0] = 1.0
        return tb if ids is None else tb[ids]

    def task_mirror(self):
        return list(range(obs_spec.N_TASK)), [1.0] * obs_spec.N_TASK

    def _both(self) -> torch.Tensor:
        pc = self.env.palm_ball_contact
        return (pc[:, 0] > 0) & (pc[:, 1] > 0)

    def reward(self) -> torch.Tensor:
        env = self.env
        dt = env.control_dt
        d = (env.p_ball[:, :2] - env.p_pelvis[:, :2]).norm(dim=-1)
        progress = (self.prev_dist - d).clamp(-0.1, 0.1)
        self.prev_dist = d.clone()
        sb = obs_spec._S_BALL
        pl, pr = env.obs[:, sb + 7], env.obs[:, sb + 8]
        near = (d < 1.0).float()
        # BOTH palms: the farther palm sets the reward, so one hand alone earns half at best
        r_reach2 = torch.exp(-((torch.maximum(pl, pr) / 0.25) ** 2)) * near
        r_reach1 = torch.exp(-((torch.minimum(pl, pr) / 0.25) ** 2)) * near
        both = self._both()
        self.both_ever |= both
        z = env.p_ball[:, 2]
        lift = ((z - BALL_R) / (self.hold_z - BALL_R)).clamp(0.0, 1.0)
        self.max_lift = torch.maximum(self.max_lift, lift * both.float())
        held = both & (z > self.hold_z)
        self.hold_t = torch.where(held, self.hold_t + dt, torch.zeros_like(self.hold_t))
        newly_ok = (self.hold_t >= self.hold_s) & ~self.done_ok
        self.done_ok |= newly_ok
        r = (
            2.0 * progress
            + 0.4 * r_reach1
            + 1.0 * r_reach2
            + 1.0 * both.float()
            + 3.0 * lift * both.float()
            + 2.0 * held.float()
            + 25.0 * newly_ok.float()
            + 0.6 * self.r_torso_upright()
            + self.penalties()
            - 0.02 * self.p_action_jerk()
        )
        self._m = {"both": both.float(), "lift": lift * both.float(), "held": held.float(), "reach2": r_reach2}
        self.track_action()
        return r

    def terminated(self) -> torch.Tensor:
        env = self.env
        d = (env.p_ball[:, :2] - env.p_pelvis[:, :2]).norm(dim=-1)
        return self.done_ok | (d > 4.0)  # success, or the ball got away

    def episode_success(self) -> torch.Tensor:
        return self.done_ok

    def episode_fail_reasons(self) -> dict[str, torch.Tensor]:
        env = self.env
        d = (env.p_ball[:, :2] - env.p_pelvis[:, :2]).norm(dim=-1)
        return {
            "never_both_palms": ~self.both_ever,
            "touched_not_lifted": self.both_ever & (self.max_lift < 0.5),
            "lifted_not_held": (self.max_lift >= 0.5) & ~self.done_ok,
            "ball_got_away": d > 4.0,
        }

    def metrics(self):
        z = torch.zeros(self.N, device=self.dev)
        m = getattr(self, "_m", {})
        return {
            "m/both_palms": m.get("both", z),
            "m/lift": m.get("lift", z),
            "m/held": m.get("held", z),
            "m/reach_both": m.get("reach2", z),
            "m/success": self.done_ok.float(),
        }
