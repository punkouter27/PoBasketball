"""Level interface (blueprint C.2). A level owns the task block, reward, termination,
reset placement and evaluation metrics; the environment owns physics and the shared
observation. Every method is batched over worlds and returns torch tensors."""
from __future__ import annotations

import torch

from streetball import obs as obs_spec


class Level:
    name: str = "base"
    episode_s: float = 20.0
    prd_tier: int = 0

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

    pass_fraction: float = 0.95   # fraction of eval episodes that must succeed

    # ---- shared reward terms ---------------------------------------------------
    def r_upright(self) -> torch.Tensor:
        """1 when the pelvis +Z points up (gravity in pelvis frame == (0,0,-1))."""
        return (-self.env.obs[:, 2]).clamp(0.0, 1.0)

    def r_height(self, target: float | None = None, width: float = 0.05) -> torch.Tensor:
        target = self.env.nominal_root_z if target is None else target
        return torch.exp(-((self.env.p_pelvis[:, 2] - target) / width) ** 2)

    def p_action_rate(self) -> torch.Tensor:
        a = self.env.prev_action
        return ((a - self._last_action) ** 2).mean(dim=1)

    def p_joint_vel(self) -> torch.Tensor:
        return (self.env.joint_vel() ** 2).mean(dim=1)

    def p_torque(self) -> torch.Tensor:
        return (self.env.actuator_force ** 2).mean(dim=1)

    def p_pose(self) -> torch.Tensor:
        return ((self.env.joint_pos() - self.env.nominal) ** 2).mean(dim=1)

    def track_action(self) -> None:
        """Call at the end of reward() so p_action_rate sees the previous action next step."""
        self._last_action = self.env.prev_action.clone()
