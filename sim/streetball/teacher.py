"""Composite locomotion + dribble teacher (2026-11-25, dribble approach #7).

The 2026-11-21 `walk_1h` run showed that PPO on `l3a_walk` alone cannot find a gait while dribbling:
the dribble brain has never moved, so the legs have nothing to exploit and every episode ended in a fall
(0 % success, 0.01 waypoints per episode, 12.7k fps). The locomotion brain (`l1_traverse`) does have a gait
and shares the observation space, the joint order, the action layout and the step rate, so the missing skill
can be *composed* instead of discovered:

    legs + torso                        <- locomotion actor, fed the L1 task block [dir_x, dir_y, dist, speed]
    both arms + lumbar flexion          <- dribble actor,    fed the L2 task block (dribble in place)

Both teachers are frozen and read the *same* environment observation; only the 12-float task block at the end
differs, which is exactly the difference the level's `task_block()` would have produced for each of them. The
composite action is therefore a legal action for the dribble family, so it can be (a) probed to see whether the
body carries the ball while it walks (`tools/teacher_probe.py`) and (b) imitated by the dribble network with
behaviour cloning (`tools/bc_train.py`), which is what `tools/scripted_dribble.py` already does for the arm alone.

TTL note: nothing here trains; the teachers and the student are plain inference.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import torch

from streetball import obs as obs_spec
from streetball.ppo import Actor

ROOT = pathlib.Path(__file__).resolve().parents[1]

# humanoid_spec joint order: left arm 0-5, right arm 6-11, legs 12-25, lumbar 26-28
ARM_JOINTS = {1: (6, 7, 8, 9, 10, 11), -1: (0, 1, 2, 3, 4, 5)}
ALL_ARM_JOINTS = tuple(range(12))
LUMBAR_FLEX = 26


@dataclass
class TeacherConfig:
    """Which joints the dribble teacher drives, and the dribble command it is fed."""

    hand: int = 1  # +1 right (the stationary brain and l3a_walk are right-handed), -1 left
    apex_target: float = 0.8  # L2Dribble.apex_target == L3MovingDribble.apex_target
    both_arms: bool = True
    include_lumbar: bool = True
    joints: tuple[int, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        if self.hand not in ARM_JOINTS:
            raise ValueError(f"hand must be +1 or -1, got {self.hand}")
        if not self.joints:
            arms = ALL_ARM_JOINTS if self.both_arms else ARM_JOINTS[self.hand]
            self.joints = arms + ((LUMBAR_FLEX,) if self.include_lumbar else ())

    @property
    def joint_index(self) -> torch.Tensor:
        return torch.as_tensor(self.joints, dtype=torch.long)


def loco_task_block(task: torch.Tensor) -> torch.Tensor:
    """L1Traverse task block `[dir_x, dir_y, distance_m, speed_cmd]` from a DRIBBLE FAMILY task block
    `[hand, apex, bounces_to_switch, speed_cmd, dir_x, dir_y, distance_m, ...]`: the walk command is
    already there in slots 3-6, it just sits in different places."""
    out = torch.zeros_like(task)
    out[:, 0:2] = task[:, 4:6]
    out[:, 2] = task[:, 6]
    out[:, 3] = task[:, 3]
    return out


def dribble_task_block(task: torch.Tensor, cfg: TeacherConfig) -> torch.Tensor:
    """L2Dribble task block for the arm teacher: dribble in place.

    Slots 3-6 are the stationary command (speed 0, "at your anchor" - the 2026-11-21 drift encoding) so the
    dribble brain does not fight the legs that are walking underneath it. Slots 7-11 stay zero: the dribble
    brain never saw a non-zero value there (its normaliser var is 0, so any other value would be clamped to
    +-10 sigma)."""
    out = torch.zeros_like(task)
    out[:, 0] = cfg.hand
    out[:, 1] = cfg.apex_target
    return out


def load_actor(ckpt: pathlib.Path | str, device: torch.device, hidden=(512, 256, 128)) -> Actor:
    """Load a train.py checkpoint or rebuild an exported ONNX policy with its parity-checked weights."""
    path = pathlib.Path(ckpt)
    if path.suffix.lower() == ".onnx":
        from tools.onnx_to_ckpt import rebuild

        actor, diff = rebuild(path, hidden=hidden)
        if diff >= 1e-5:
            raise ValueError(f"ONNX actor reconstruction parity failed for {path}: max abs diff {diff:.2e}")
        return actor.to(device).eval()
    sd = torch.load(path, map_location=device, weights_only=False)
    actor = Actor(obs_spec.N_OBS, obs_spec.N_JOINTS, hidden).to(device)
    actor.load_state_dict({k[len("actor.") :]: v for k, v in sd["ac"].items() if k.startswith("actor.")})
    return actor.eval()


def open_walk_inputs(actor: Actor) -> Actor:
    """Make stationary-dribble task inputs safe for l3a_walk without changing its zero-command action."""
    start = obs_spec.N_BASE
    slots = (3, 4, 5, 6)
    stds = (1.0, 1.0, 1.0, 3.0)
    first = next(m for m in actor.net if isinstance(m, torch.nn.Linear))
    with torch.no_grad():
        for slot, std in zip(slots, stds):
            i = start + slot
            first.weight[:, i] = 0.0
            actor.norm.mean[i] = 0.0
            actor.norm.var[i] = std**2
    return actor


class CompositeTeacher:
    """Frozen locomotion + dribble pair producing one dribble-family action."""

    def __init__(self, locomotion: Actor, dribble: Actor, cfg: TeacherConfig | None = None):
        self.loco = locomotion.eval()
        self.dribble = dribble.eval()
        self.cfg = cfg or TeacherConfig()
        self.joints = self.cfg.joint_index.to(next(locomotion.parameters()).device)

    def author_obs(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """(obs for the locomotion actor, obs for the dribble actor) from one dribble-family observation."""
        base, task = obs[:, : obs_spec.N_BASE], obs[:, obs_spec.N_BASE : obs_spec.N_OBS]
        return (
            torch.cat([base, loco_task_block(task)], -1),
            torch.cat([base, dribble_task_block(task, self.cfg)], -1),
        )

    @torch.no_grad()
    def act(self, obs: torch.Tensor) -> torch.Tensor:
        o_loco, o_drib = self.author_obs(obs)
        a = self.loco(o_loco).clone()
        a[:, self.joints] = self.dribble(o_drib)[:, self.joints]
        return a

    __call__ = act

    def eval(self) -> CompositeTeacher:
        return self


def production_teacher(device: torch.device, cfg: TeacherConfig | None = None) -> CompositeTeacher:
    """Build the l3a_walk teacher from the shipped locomotion and stationary-dribble policies."""
    cfg = cfg or TeacherConfig()
    policies = ROOT.parent / "shared" / "policies"
    return CompositeTeacher(
        load_actor(policies / "locomotion.onnx", device),
        load_actor(policies / "dribble.onnx", device),
        cfg,
    )


class BCEntryBuffer:
    """Ring buffer of (observation the student visited, action the teacher wants there).

    DAgger: the observations come from the *student's* rollout, so the cloned policy is fitted on the states it
    actually reaches (a pure teacher rollout drifts off the teacher's path and never sees them)."""

    def __init__(self, capacity: int, n_obs: int, n_act: int, device: torch.device):
        self.obs = torch.zeros(capacity, n_obs, device=device)
        self.act = torch.zeros(capacity, n_act, device=device)
        self.capacity = capacity
        self.ptr = 0
        self.size = 0
        self.total_added = 0

    def add(self, obs: torch.Tensor, act: torch.Tensor) -> None:
        k = obs.shape[0]
        if k == 0:
            return
        self.total_added += k
        if k > self.capacity:  # keep the newest `capacity` rows
            obs, act, k = obs[-self.capacity :], act[-self.capacity :], self.capacity
        i = self.ptr
        first = min(k, self.capacity - i)
        self.obs[i : i + first] = obs[:first]
        self.act[i : i + first] = act[:first]
        if k > first:
            self.obs[: k - first] = obs[first:]
            self.act[: k - first] = act[first:]
        self.ptr = (i + k) % self.capacity
        self.size = min(self.capacity, self.size + k)

    def sample(self, n: int, gen: torch.Generator | None = None) -> tuple[torch.Tensor, torch.Tensor]:
        idx = torch.randint(0, self.size, (n,), device=self.obs.device, generator=gen)
        return self.obs[idx], self.act[idx]


@dataclass
class RolloutStats:
    """Episode-level statistics of one rollout, in the shape evaluate.py reports them."""

    episodes: int = 0
    success: float = 0.0
    falls: float = 0.0
    episode_s: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)
    fail_reasons: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "episodes": self.episodes,
            "success": round(self.success, 4),
            "falls": round(self.falls, 4),
            "episode_s": round(self.episode_s, 2),
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "fail_reasons": {k: round(v, 4) for k, v in self.fail_reasons.items()},
        }


def teacher_is_cloneable(stats: RolloutStats) -> bool:
    return (
        stats.episodes > 0
        and stats.metrics.get("m/control_frac", 0.0) >= 0.9
        and stats.metrics.get("m/dist_m", 0.0) >= 3.0
    )


@torch.no_grad()
def rollout(
    env,
    policy,
    steps: int,
    buffer: BCEntryBuffer | None = None,
    teacher=None,
    action_noise: float = 0.0,
    gen: torch.Generator | None = None,
) -> RolloutStats:
    """Run `env` for `steps` control steps with `policy(obs) -> action`.

    With a `buffer`, each visited observation is stored together with `teacher(obs)` (the DAgger label).
    Episode statistics are per finished episode, like streetball.evaluate."""
    N, dev = env.N, env.device
    finished = torch.zeros(N, dtype=torch.bool, device=dev)
    success = torch.zeros(N, dtype=torch.bool, device=dev)
    fell = torch.zeros(N, dtype=torch.bool, device=dev)
    ep_len = torch.zeros(N, device=dev)
    metrics: dict[str, torch.Tensor] = {}
    fails: dict[str, torch.Tensor] = {}
    obs = env.obs
    for step_i in range(1, steps + 1):
        a = policy(obs)
        if action_noise > 0.0:
            a = (a + torch.randn(a.shape, device=dev, generator=gen) * action_noise).clamp(-1.0, 1.0)
        if buffer is not None and teacher is not None:
            alive = ~finished
            buffer.add(obs[alive], teacher(obs)[alive])
        obs, _rew, done, info = env.step(a)
        just = done & ~finished
        success |= just & info["success"]
        fell |= just & info["fallen"]
        ep_len = torch.where(just, torch.full_like(ep_len, float(step_i)), ep_len)
        for k, v in info.items():
            if k.startswith("m/"):
                metrics[k] = metrics.get(k, torch.zeros(N, device=dev)) + torch.where(finished, 0.0, v.float())
            elif k.startswith("fail/"):
                fails[k[5:]] = fails.get(k[5:], torch.zeros(N, dtype=torch.bool, device=dev)) | (just & v)
        finished |= just
        if finished.all():
            break
    n = int(finished.sum())
    steps_run = ep_len.clamp_min(1)
    stats = RolloutStats(episodes=n)
    if n:
        stats.success = success[finished].float().mean().item()
        stats.falls = fell[finished].float().mean().item()
        stats.episode_s = (ep_len[finished] * env.control_dt).mean().item()
        stats.metrics = {k: (v / steps_run).mean().item() for k, v in metrics.items()}  # mean over all worlds
        stats.fail_reasons = {k: (v & ~success).float().mean().item() for k, v in fails.items()}
    return stats
