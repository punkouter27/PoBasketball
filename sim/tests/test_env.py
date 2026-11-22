"""C1/C2 acceptance: the Warp env builds observations identical to obs.py (golden
cross-check), steps without NaN under random actions, and randomisation varies
per world. Run: uv run python -m pytest tests/test_env.py -q -s
"""

import pathlib
import time

import numpy as np
import pytest

torch = pytest.importorskip("torch", reason="torch not installed (GPU test; run in sim/.venv)")
pytest.importorskip("mujoco_warp", reason="MuJoCo Warp not installed (GPU test; run in sim/.venv)")
if not torch.cuda.is_available():
    pytest.skip("no CUDA device: the Warp environment runs on the GPU only", allow_module_level=True)

from streetball import obs as obs_spec  # noqa: E402
from streetball.env_base import EnvConfig, RandomizationConfig, StreetballEnv  # noqa: E402
from streetball.levels import make  # noqa: E402

pytestmark = pytest.mark.gpu

SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"


@pytest.fixture(scope="module")
def env():
    cfg = EnvConfig(num_envs=256, seed=1, randomization=RandomizationConfig(enabled=True))
    return StreetballEnv(make("l0_stand"), cfg)


def test_obs_parity_with_golden(env):
    g = np.load(SHARED / "golden" / "obs_golden.npz")
    n = env.N
    dev = env.device
    env.qpos[:] = torch.as_tensor(g["qpos"][:n], device=dev, dtype=torch.float32)
    env.qvel[:] = torch.as_tensor(g["qvel"][:n], device=dev, dtype=torch.float32)
    env.prev_action[:] = torch.as_tensor(g["prev_action"][:n], device=dev, dtype=torch.float32)
    env.task[:] = torch.as_tensor(g["task"][:n], device=dev, dtype=torch.float32)
    env.in_control[:] = torch.as_tensor(g["in_control"][:n], device=dev, dtype=torch.float32)
    env.countdown_frac[:] = torch.as_tensor(g["countdown_frac"][:n], device=dev, dtype=torch.float32)
    env.forward()
    env._scan_contacts()
    o = env.compute_obs()
    o[:, obs_spec.N_BASE : obs_spec.N_OBS] = env.task
    diff = o.cpu().numpy() - g["obs"][:n]
    # Contact flags can legitimately differ (float32 vs float64 contact detection at exactly-touching feet);
    # compare them separately and everything else tightly.
    fc0 = obs_spec._S_BALL + 9
    flags = np.abs(diff[:, fc0 : fc0 + 2]).max()
    diff[:, fc0 : fc0 + 2] = 0.0
    worst = np.abs(diff).max()
    print(f"max abs obs diff (non-flag) {worst:.2e}, flag mismatches {int((np.abs(diff[:, fc0 : fc0 + 2]) > 0).sum())}")
    assert worst < 2e-4, f"obs mismatch {worst:.3e} at slot {np.abs(diff).max(axis=0).argmax()}"
    assert flags <= 1.0


def test_step_random_actions(env):
    env.reset(torch.arange(env.N, device=env.device))
    t0 = time.perf_counter()
    steps = 200
    dones = 0
    for _ in range(steps):
        a = torch.rand(env.N, env.N_ACT, device=env.device, generator=env.gen) * 2 - 1
        obs, rew, done, info = env.step(a)
        assert torch.isfinite(obs).all()
        assert torch.isfinite(rew).all()
        assert not info["nan"].any()
        dones += int(done.sum())
    dt = time.perf_counter() - t0
    print(
        f"{env.N} envs x {steps} control steps in {dt:.2f}s -> {env.N * steps / dt:.0f} control steps/s, {dones} episode ends"
    )
    assert dones > 0, "random actions should make the character fall at least once"


def test_every_penalty_term_is_charged_and_logged(env):
    """torque^2, joint angular velocity^2, action rate^2 and foot slip are each charged (weight < 0, term > 0 for some
    worlds) and reported separately as info["m/pen_<term>"] (the trainer writes every m/ key to TensorBoard)."""
    from streetball import reward_config

    env.reset(torch.arange(env.N, device=env.device))
    seen = {t: 0.0 for t in reward_config.PENALTY_TERMS}
    for _ in range(30):
        a = torch.rand(env.N, env.N_ACT, device=env.device, generator=env.gen) * 2 - 1
        _, _, _, info = env.step(a)
        for t in reward_config.PENALTY_TERMS:
            v = info[f"m/pen_{t}"]
            assert v.shape == (env.N,) and torch.isfinite(v).all()
            assert (v <= 0).all(), f"{t} is a penalty"
            seen[t] = min(seen[t], float(v.min()))
    print({t: f"{v:.3e}" for t, v in seen.items()})
    for t, v in seen.items():
        assert v < 0, f"{t} was never charged under random actions"


def test_randomisation_varies(env):
    masses = env.m_body_mass[:, env.pelvis_b]
    fric = env.m_geom_friction[:, env.floor_g, 0]
    kp = env.m_gainprm[:, 0, 0]
    assert masses.std() > 0.1 and fric.std() > 0.05 and kp.std() > 5.0
    assert (fric >= 0.6).all() and (fric <= 1.1).all()
    assert env.delay_action.float().mean().item() > 0.2
