"""L5 get-up (2026-11-24): stand up from a real simulated fall (UU_AGENT §3).

Every episode starts from a state in data/fall_states.npz, recorded by tools/record_fall_states.py: the shipped
balance policy knocked over by a large push and left to settle. Falling is not a termination here (that is the
starting point), so the level sets `terminate_on_fall = False`; the env still ends episodes on NaN and on time.

Task block: all zeros (no command). Reward: pelvis height toward the nominal stance, torso upright, both feet down
once up, plus the standard penalties. Pass: by the end of the episode the body has stood (pelvis >= 90 % of
nominal height, torso upright, both feet on the floor) for 1 s without interruption.

Untrained: no policy, no director row. A director hand-over (fallen -> getup -> balance) is added only once a policy
passes this gate (the curriculum row l5_getup in shared/reward_config.json).
"""

from __future__ import annotations

import pathlib

import numpy as np
import torch

from streetball.levels.base import Level

BANK = pathlib.Path(__file__).resolve().parents[2] / "data" / "fall_states.npz"


class L5GetUp(Level):
    name = "l5_getup"
    episode_s = 6.0
    prd_tier = 1
    terminate_on_fall = False
    stand_hold_s = 1.0

    def setup(self) -> None:
        if not BANK.exists():
            raise FileNotFoundError(f"{BANK} missing: run `uv run python tools/record_fall_states.py` in sim/")
        bank = np.load(BANK)
        env = self.env
        if bank["qpos"].shape[1] != env.mjm.nq or bank["qvel"].shape[1] != env.mjm.nv:
            raise ValueError(f"{BANK} was recorded for another body (nq/nv differ): re-record it")
        self.bank_qpos = torch.as_tensor(bank["qpos"], device=self.dev, dtype=torch.float32)
        self.bank_qvel = torch.as_tensor(bank["qvel"], device=self.dev, dtype=torch.float32)
        self.stood_t = torch.zeros(self.N, device=self.dev)
        self.best_stood_t = torch.zeros(self.N, device=self.dev)
        self._last_action = torch.zeros(self.N, env.N_ACT, device=self.dev)

    def on_reset(self, ids: torch.Tensor) -> None:
        env = self.env
        k = torch.randint(0, self.bank_qpos.shape[0], (ids.numel(),), device=self.dev, generator=env.gen)
        env.qpos[ids] = self.bank_qpos[k]
        env.qvel[ids] = self.bank_qvel[k]
        # recentre on the origin: the bank's x/y are wherever the fall ended
        env.qpos[ids, env.root_q : env.root_q + 2] = 0.0
        env.set_ball(ids, torch.tensor([3.0, 3.0, 0.12], device=self.dev).expand(ids.numel(), 3))
        self.stood_t[ids] = 0.0
        self.best_stood_t[ids] = 0.0
        self._last_action[ids] = 0.0

    def standing(self) -> torch.Tensor:
        env = self.env
        tall = env.p_pelvis[:, 2] >= 0.9 * env.nominal_root_z
        upright = self.r_torso_upright() > 0.9
        feet = env.foot_contact.sum(1) >= 2
        return tall & upright & feet

    def reward(self) -> torch.Tensor:
        env = self.env
        up = self.standing()
        self.stood_t = torch.where(up, self.stood_t + env.control_dt, torch.zeros_like(self.stood_t))
        self.best_stood_t = torch.maximum(self.best_stood_t, self.stood_t)
        z = (env.p_pelvis[:, 2] / env.nominal_root_z).clamp(0.0, 1.0)
        r = 0.5 * z + 0.3 * self.r_torso_upright() + 0.2 * up.float()
        r = r + self.penalties() - 0.02 * self.p_action_jerk()
        self.track_action()
        return r

    def metrics(self) -> dict[str, torch.Tensor]:
        return {"m/standing": self.standing().float(), "m/pelvis_z": self.env.p_pelvis[:, 2].clone()}

    def episode_success(self) -> torch.Tensor:
        return self.best_stood_t >= self.stand_hold_s
