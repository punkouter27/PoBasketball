import torch

from streetball import obs as obs_spec
from streetball.levels import make


class ApproachEnv:
    N = 2
    N_ACT = obs_spec.N_JOINTS
    device = torch.device("cpu")
    control_dt = 0.25

    def __init__(self):
        self.H = torch.eye(3).repeat(self.N, 1, 1)
        self.p_pelvis = torch.tensor([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
        self.p_ball = torch.tensor([[2.0, 0.0, 0.1205], [0.4, 0.0, 0.1205]])
        self.v_pelvis = torch.zeros(self.N, 3)
        self.prev_action = torch.zeros(self.N, self.N_ACT)


def test_approach_level_targets_ball_and_stops_without_pickup_objective():
    level = make("l3_approach")
    env = ApproachEnv()
    env.v_pelvis[1, 0] = 0.5
    level.attach(env)
    level.prev_dist[:] = torch.tensor([2.0, 0.4])
    level.r_torso_upright = lambda: torch.ones(env.N)
    level.r_height = lambda **kwargs: torch.ones(env.N)
    level.r_heel_toe_stride = lambda: torch.ones(env.N)
    level.penalties = lambda: torch.zeros(env.N)
    level.p_action_jerk = lambda: torch.zeros(env.N)

    task = level.task_block(None)
    assert torch.allclose(task[:, 0], torch.ones(env.N))
    assert torch.equal(task[:, 1], torch.zeros(env.N))
    assert task[0, 2].item() == 2.0
    assert task[0, 3] > task[1, 3]
    assert level.task_mirror()[1][1] == -1.0

    level.reward()
    assert level.episode_success().tolist() == [False, False]
    assert level.terminated().tolist() == [False, False]
    level.reward()
    assert level.episode_success().tolist() == [False, False]
    env.v_pelvis[1, 0] = 0.0
    level.reward()
    assert level.episode_success().tolist() == [False, False]
    level.reward()
    assert level.episode_success().tolist() == [False, True]
    assert level.terminated().tolist() == [False, True]
    assert level.pass_fraction == 0.8
