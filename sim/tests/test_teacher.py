import sys

import pytest
import torch
from torch import nn

from streetball import obs as obs_spec
from streetball.teacher import CompositeTeacher, RolloutStats, TeacherConfig, open_walk_inputs, teacher_is_cloneable
from tools import bc_train


class ConstantActor(nn.Module):
    def __init__(self, value: float):
        super().__init__()
        self.bias = nn.Parameter(torch.tensor(value))

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        return self.bias.expand(obs.shape[0], obs_spec.N_JOINTS)


def test_composite_teacher_routes_both_arms_and_lumbar_to_dribble_actor():
    teacher = CompositeTeacher(ConstantActor(0.1), ConstantActor(0.8))
    obs = torch.zeros(2, obs_spec.N_OBS)
    action = teacher(obs)
    dribble_joints = set(range(12)) | {26}
    for joint in range(obs_spec.N_JOINTS):
        expected = 0.8 if joint in dribble_joints else 0.1
        torch.testing.assert_close(action[:, joint], torch.full((2,), expected))


def test_teacher_task_blocks_reencode_locomotion_command_and_freeze_dribble_command():
    teacher = CompositeTeacher(ConstantActor(0.1), ConstantActor(0.8))
    obs = torch.zeros(1, obs_spec.N_OBS)
    task = obs[:, obs_spec.N_BASE :]
    task[:, 3:7] = torch.tensor([[0.7, 0.2, -0.3, 4.0]])
    task[:, 0:2] = torch.tensor([[1.0, 0.8]])

    loco_obs, dribble_obs = teacher.author_obs(obs)
    loco = loco_obs[:, obs_spec.N_BASE :]
    dribble = dribble_obs[:, obs_spec.N_BASE :]
    torch.testing.assert_close(loco[:, :4], torch.tensor([[0.2, -0.3, 4.0, 0.7]]))
    torch.testing.assert_close(dribble[:, :2], torch.tensor([[1.0, 0.8]]))
    assert torch.count_nonzero(dribble[:, 2:]).item() == 0


def test_open_walk_inputs_preserves_zero_command_policy_output():
    from streetball.ppo import Actor

    original = Actor(obs_spec.N_OBS, obs_spec.N_JOINTS)
    opened = Actor(obs_spec.N_OBS, obs_spec.N_JOINTS)
    opened.load_state_dict(original.state_dict())
    open_walk_inputs(opened)
    obs = torch.randn(32, obs_spec.N_OBS)
    zero_command = obs.clone()
    start = obs_spec.N_BASE
    zero_command[:, start + 3 : start + 7] = 0.0
    with torch.no_grad():
        expected = original(zero_command)
        actual = opened(obs)
    torch.testing.assert_close(actual, expected)


def test_teacher_config_rejects_invalid_hand():
    with pytest.raises(ValueError, match=r"\+1 or -1"):
        TeacherConfig(hand=0)


def test_teacher_probe_reads_prefixed_rollout_metrics():
    ready = RolloutStats(episodes=200, metrics={"m/control_frac": 0.95, "m/dist_m": 3.2})
    missing_prefix = RolloutStats(episodes=200, metrics={"control_frac": 1.0, "dist_m": 4.0})

    assert teacher_is_cloneable(ready)
    assert not teacher_is_cloneable(missing_prefix)


def test_bc_time_budget_with_zero_rounds_means_run_until_deadline(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["bc_train.py", "--rounds", "0", "--time-budget-min", "1"],
    )

    assert bc_train.parse_args().rounds is None
