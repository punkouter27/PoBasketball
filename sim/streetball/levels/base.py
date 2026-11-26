"""Level interface (blueprint C.2). A level owns the task block, reward, termination,
reset placement and evaluation metrics; the environment owns physics and the shared
observation. Every method is batched over worlds and returns torch tensors."""

from __future__ import annotations

import torch

from streetball import obs as obs_spec
from streetball import reward_config


class Level:
    name: str = "base"
    episode_s: float = 20.0
    prd_tier: int = 0
    terminate_on_fall: bool = True  # False: a fall does not end the episode (l5_getup starts fallen)
    train_steps: float = float("inf")  # set by train.py each iteration; stays inf in evaluation (curricula off)

    def attach(self, env) -> None:
        self.env = env
        self.N = env.N
        self.dev = env.device
        self.setup()

    # ---- hooks ---------------------------------------------------------------
    def setup(self) -> None:
        """Allocate per-world state. Called once after attach."""

    def on_reset(self, ids: torch.Tensor) -> None:
        """Place root/ball and reset task state for `ids`. qpos may be edited directly."""

    def task_block(self, ids: torch.Tensor | None) -> torch.Tensor:
        """(len(ids) or N, 12) task observation. Must be zero-padded to 12."""
        n = self.N if ids is None else ids.numel()
        return torch.zeros(n, obs_spec.N_TASK, device=self.dev)

    def task_mirror(self) -> tuple[list[int], list[float]] | None:
        """(perm, sign) of the 12 task slots under the left/right mirror (streetball/mirror.py), or None when the
        level is not mirror-symmetric (one-handed dribbling, a fixed hoop side...): the symmetry loss is then off.
        The base level's task block is all zeros, so the identity is right for it."""
        if type(self).task_block is not Level.task_block:
            return None  # a level with its own task block must declare its mirror
        return list(range(obs_spec.N_TASK)), [1.0] * obs_spec.N_TASK

    def reward(self) -> torch.Tensor:
        raise NotImplementedError

    def terminated(self) -> torch.Tensor:
        """Level-specific terminations (the env adds fallen / NaN)."""
        return torch.zeros(self.N, dtype=torch.bool, device=self.dev)

    def metrics(self) -> dict[str, torch.Tensor]:
        """Per-step scalars for logging (means are taken by the trainer)."""
        return {}

    # ---- evaluation ------------------------------------------------------------
    def episode_success(self) -> torch.Tensor:
        """(N,) bool: did the *current* episode meet the PRD milestone so far."""
        return torch.zeros(self.N, dtype=torch.bool, device=self.dev)

    @property
    def pass_fraction(self) -> float:
        """Fraction of eval episodes that must succeed: the curriculum gate in shared/reward_config.json for this
        level, or for the nearest parent level class (variants such as l2b_dribble_l share their parent's gate)."""
        for cls in type(self).__mro__:
            t = reward_config.curriculum_threshold(getattr(cls, "name", ""))
            if t is not None:
                return t
        raise KeyError(f"no curriculum threshold for level {self.name!r} in {reward_config.PATH}")

    # ---- shared reward terms ---------------------------------------------------
    def r_upright(self) -> torch.Tensor:
        """1 when the pelvis +Z points up (gravity in pelvis frame == (0,0,-1))."""
        return (-self.env.obs[:, 2]).clamp(0.0, 1.0)

    def r_torso_upright(self) -> torch.Tensor:
        """Pure-RL posture reward: pelvis +Z AND torso +Z upright (cures ~40 deg lumbar hunch)."""
        pelvis_up = self.r_upright()
        R_torso = self.env.quat_to_mat(self.env.xquat[:, self.env.torso_b])
        torso_up = R_torso[:, 2, 2].clamp(0.0, 1.0)
        return 0.4 * pelvis_up + 0.6 * torso_up

    def r_height(self, target: float | None = None, width: float = 0.05) -> torch.Tensor:
        target = self.env.nominal_root_z if target is None else target
        return torch.exp(-(((self.env.p_pelvis[:, 2] - target) / width) ** 2))

    def p_action_rate(self) -> torch.Tensor:
        a = self.env.prev_action
        return ((a - self._last_action) ** 2).mean(dim=1)

    def p_action_jerk(self) -> torch.Tensor:
        """Second-order action smoothness penalty (UU_AGENT section 2)."""
        prev2 = getattr(self, "_prev2_action", None)
        if prev2 is None:
            return torch.zeros(self.N, device=self.dev)
        a = self.env.prev_action
        return ((a - 2.0 * self._last_action + prev2) ** 2).mean(dim=1)

    def p_toe_stand(self) -> torch.Tensor:
        """Keep toe hinges flat near 0 rad during stationary balance."""
        toe_q = self.env.joint_pos()[:, self.env.toe_j_idx]
        return (toe_q**2).mean(dim=1)

    def r_heel_toe_stride(self) -> torch.Tensor:
        """Pure-RL gait shaping: gently dorsiflex toes on airborne swing foot to clear floor."""
        toe_q = self.env.joint_pos()[:, self.env.toe_j_idx]  # (N, 2), + = toes up
        swing = (1.0 - self.env.foot_contact).clamp(0.0, 1.0)  # (N, 2), 1 when off floor
        want = torch.exp(-(((toe_q - 0.25) / 0.25) ** 2))
        return (swing * want).mean(dim=1)

    def p_joint_vel(self) -> torch.Tensor:
        return (self.env.joint_vel() ** 2).mean(dim=1)

    def p_torque(self) -> torch.Tensor:
        return (self.env.actuator_force**2).mean(dim=1)

    def p_foot_slip(self) -> torch.Tensor:
        """Foot sliding: sum over feet of contact * planar foot speed^2 (speed from the foot-centre site between
        control steps; 0 on the first step after a reset)."""
        env = self.env
        xy = env.site_xpos[:, env.foot_site_idx[[0, 4]], :2]  # (N, 2 feet, 2)
        prev = getattr(self, "_prev_foot_xy", None)
        if prev is None or prev.shape != xy.shape:
            prev = xy
        speed2 = (((xy - prev) / env.control_dt) ** 2).sum(-1)  # (N, 2)
        speed2 = torch.where((env.step_count <= 1)[:, None], torch.zeros_like(speed2), speed2)
        self._prev_foot_xy = xy.clone()
        return (env.foot_contact * speed2).sum(dim=1)

    # ---- 2026-11-24 shaping terms (weight 0 in shared/reward_config.json until a run switches them on) ----------
    def p_power(self) -> torch.Tensor:
        """Mechanical power: mean over actuators of |force * velocity| (W). Unlike torque^2 it is free to hold a
        load still and charges fast, forceful motion, which gives lower-energy gaits."""
        return (self.env.actuator_force * self.env.actuator_velocity).abs().mean(dim=1)

    def _support_centre(self) -> torch.Tensor:
        env = self.env
        corners = env.site_xpos[:, env.foot_site_idx, :2]  # (N, 8, 2): 4 corners per foot, l then r
        w = env.foot_contact.repeat_interleave(4, dim=1)  # (N, 8)
        w = torch.where(w.sum(1, keepdim=True) > 0, w, torch.ones_like(w))  # airborne: centre of both feet
        return (corners * w[..., None]).sum(1) / w.sum(1, keepdim=True)

    def p_com_offset(self) -> torch.Tensor:
        """Static stability: squared horizontal distance from the CoM to the centre of the feet on the ground."""
        com = self.env.subtree_com[:, self.env.pelvis_b, :2]
        return ((com - self._support_centre()) ** 2).sum(-1)

    def p_com_vel_z(self) -> torch.Tensor:
        """Vertical CoM bounce (finite difference; 0 on the first step after a reset)."""
        env = self.env
        z = env.subtree_com[:, env.pelvis_b, 2].clone()
        prev = getattr(self, "_prev_com_z", None)
        if prev is None or prev.shape != z.shape:
            prev = z
        v2 = ((z - prev) / env.control_dt) ** 2
        self._prev_com_z = z
        return torch.where(env.step_count <= 1, torch.zeros_like(v2), v2)

    def p_ang_vel_xy(self) -> torch.Tensor:
        """Pelvis roll/pitch rate^2 (pelvis frame; obs slots 6:8 hold it scaled by 0.25)."""
        w = self.env.obs[:, 6:8] / 0.25
        return (w**2).sum(-1)

    SWING_MIN_S = 0.35

    def p_short_swing(self) -> torch.Tensor:
        """Shuffling: at each touchdown, how much shorter than SWING_MIN_S the foot's swing was. A foot that never
        lifts is not charged (standing still is fine); one that taps the floor is."""
        env = self.env
        c = env.foot_contact  # (N, 2)
        air = getattr(self, "_air_t", None)
        if air is None or air.shape != c.shape:
            air = torch.zeros_like(c)
            self._prev_contact = c.clone()
        fresh = (env.step_count <= 1)[:, None]
        air = torch.where(fresh, torch.zeros_like(air), air)
        prev = torch.where(fresh, c, self._prev_contact)
        touchdown = (c > 0.5) & (prev < 0.5)
        # air time includes this control step: the foot was in the air for it before touching down
        air_now = air + env.control_dt * (prev < 0.5).float()
        term = (touchdown.float() * (self.SWING_MIN_S - air_now).clamp(min=0.0)).sum(-1)
        self._air_t = torch.where(c > 0.5, torch.zeros_like(air_now), air_now)
        self._prev_contact = c.clone()
        return term

    def penalties(self, terms: tuple[str, ...] = reward_config.PENALTY_TERMS) -> torch.Tensor:
        """Weighted sum of the standard penalty terms (weights from shared/reward_config.json, all <= 0)."""
        w = reward_config.penalty_weights(self.name)
        fn = {
            "torque_sq": self.p_torque,
            "joint_ang_vel_sq": self.p_joint_vel,
            "action_rate_sq": self.p_action_rate,
            "foot_slip": self.p_foot_slip,
            "power_abs": self.p_power,
            "com_offset": self.p_com_offset,
            "com_vel_z_sq": self.p_com_vel_z,
            "ang_vel_xy_sq": self.p_ang_vel_xy,
            "short_swing": self.p_short_swing,
        }
        total = torch.zeros(self.N, device=self.dev)
        charged: dict[str, torch.Tensor] = {}
        for t in terms:
            charged[t] = w[t] * fn[t]()
            total = total + charged[t]
        # each weighted term is kept for logging (env.step -> info["m/pen_<term>"] -> TensorBoard / progress.csv)
        self.penalty_terms = charged
        return total

    def p_pose(self) -> torch.Tensor:
        return ((self.env.joint_pos() - self.env.nominal) ** 2).mean(dim=1)

    def track_action(self) -> None:
        """Call at the end of reward() so p_action_rate / p_action_jerk see previous actions."""
        self._prev2_action = self._last_action.clone()
        self._last_action = self.env.prev_action.clone()
