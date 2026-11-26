"""PPO symmetry loss (ppo.PPO.symmetry_loss): zero for a mirror-equivariant actor, and descending it makes a random
actor more symmetric. CPU only."""

import pathlib

import mujoco
import pytest

torch = pytest.importorskip("torch", reason="torch not installed (runs in sim/.venv)")

from streetball import mirror as mr  # noqa: E402
from streetball import obs as obs_spec  # noqa: E402
from streetball.ppo import PPO, PPOConfig  # noqa: E402

SCENE = pathlib.Path(__file__).resolve().parents[1] / "assets" / "scene.xml"


def _agent():
    m = mujoco.MjModel.from_xml_path(str(SCENE))
    M = mr.build(m, obs_spec.ObsIndex(m))
    torch.manual_seed(0)
    agent = PPO(obs_spec.N_OBS, obs_spec.N_JOINTS, 8, PPOConfig(sym_coef=1.0, hidden=(64, 64)), torch.device("cpu"))
    agent.set_mirror(M)
    return agent


def test_symmetric_actor_has_zero_loss():
    agent = _agent()
    op, os_, ap, as_ = agent.mirror
    base = agent.ac.actor

    class Symmetrised(torch.nn.Module):  # f_sym(o) = (f(o) + M_a f(M_o o)) / 2 is mirror-equivariant
        def forward(self, o):
            return 0.5 * (base(o) + base(o[:, op] * os_)[:, ap] * as_)

    agent.ac.actor = Symmetrised()
    obs = torch.randn(256, obs_spec.N_OBS)
    with torch.no_grad():
        loss = agent.symmetry_loss(obs, agent.ac.actor(obs))
    assert loss.item() < 1e-10


def test_descending_the_loss_makes_the_actor_symmetric():
    agent = _agent()
    obs = torch.randn(512, obs_spec.N_OBS)
    opt = torch.optim.Adam(agent.ac.actor.parameters(), lr=1e-3)
    first = None
    for _ in range(200):
        loss = agent.symmetry_loss(obs, agent.ac.actor(obs))
        first = loss.item() if first is None else first
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert loss.item() < 0.1 * first, (first, loss.item())
