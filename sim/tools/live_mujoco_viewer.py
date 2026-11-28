"""Show a CPU MuJoCo preview driven by the latest checkpoint in a training run.

    uv run python tools/live_mujoco_viewer.py runs/l1_traverse_q1
    uv run python tools/live_mujoco_viewer.py runs/l3_approach_run

The viewer is a separate single-world preview; it does not display the trainer's
vectorized MuJoCo Warp worlds.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

import mujoco
import mujoco.viewer
import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from streetball import obs as obs_spec
from streetball.ppo import Actor

SUBSTEPS = 10
RELOAD_SECONDS = 2.0
SUPPORTED_LEVELS = {"l1_traverse", "l3_approach"}


def load_actor(actor: Actor, checkpoint: pathlib.Path) -> tuple[str, int, tuple[int, int]]:
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    level = state.get("level")
    if level not in SUPPORTED_LEVELS:
        raise ValueError(f"{checkpoint} has unsupported level {level!r}; expected one of {sorted(SUPPORTED_LEVELS)}")
    actor_state = {k.removeprefix("actor."): v for k, v in state["ac"].items() if k.startswith("actor.")}
    actor.load_state_dict(actor_state)
    actor.eval()
    stat = checkpoint.stat()
    return level, int(state.get("steps", 0)), (stat.st_mtime_ns, stat.st_size)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=pathlib.Path, help="training run directory containing model.pt")
    args = parser.parse_args()
    checkpoint = (args.run / "model.pt").resolve(strict=True)

    torch.set_num_threads(1)
    model = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    data = mujoco.MjData(model)
    index = obs_spec.ObsIndex(model)
    actor = Actor(obs_spec.N_OBS, obs_spec.N_JOINTS)
    level, steps, loaded_stat = load_actor(actor, checkpoint)
    print(f"Loaded {checkpoint.name} at {steps / 1e6:.1f}M training steps", flush=True)

    key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "stand")
    root_q = index.root_q
    ball_q = index.ball_q
    rng = np.random.default_rng(42)
    previous_action = np.zeros(obs_spec.N_JOINTS)
    waypoint = np.zeros(2)
    speed_command = 1.5
    episode_time = 0.0
    reached = 0
    settle_time = 0.0

    def reset_episode() -> None:
        nonlocal waypoint, speed_command, episode_time, reached, previous_action, settle_time
        mujoco.mj_resetDataKeyframe(model, data, key)
        data.qpos[root_q : root_q + 2] = [0.0, 0.0]
        data.qpos[root_q + 3 : root_q + 7] = [1.0, 0.0, 0.0, 0.0]
        data.qpos[index.qadr] += rng.normal(0.0, 0.03, obs_spec.N_JOINTS)
        if level == "l3_approach":
            distance = rng.uniform(1.5, 5.0)
            angle = rng.uniform(-1.75, 1.75)
            waypoint = np.array([distance * np.cos(angle), distance * np.sin(angle)])
            data.qpos[ball_q : ball_q + 3] = [waypoint[0], waypoint[1], 0.1205]
        else:
            data.qpos[ball_q : ball_q + 3] = [0.0, 8.0, 0.1205]
        data.qvel[:] = 0.0
        data.ctrl[:] = index.nominal
        previous_action = np.zeros(obs_spec.N_JOINTS)
        episode_time = 0.0
        reached = 0
        settle_time = 0.0
        if level == "l1_traverse":
            waypoint = rng.uniform([-13.0, -6.5], [13.0, 6.5])
            speed_command = float(rng.uniform(1.2, 3.0))
        mujoco.mj_forward(model, data)

    def task_block() -> np.ndarray:
        target = data.qpos[ball_q : ball_q + 2] if level == "l3_approach" else waypoint
        rel = target - data.qpos[root_q : root_q + 2]
        distance = float(np.linalg.norm(rel))
        heading = obs_spec.heading_mat(data.qpos[root_q + 3 : root_q + 7])
        direction = rel / max(distance, 1e-6)
        task = np.zeros(obs_spec.N_TASK)
        task[:3] = [
            direction @ heading[:2, 0],
            direction @ heading[:2, 1],
            min(distance, 10.0),
        ]
        task[3] = (
            float(np.clip(0.2 + 0.35 * max(distance - 0.5, 0.0), 0.2, 1.3))
            if level == "l3_approach"
            else speed_command
        )
        return task

    reset_episode()
    control_dt = model.opt.timestep * SUBSTEPS
    last_reload = time.monotonic()
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.distance = 12.0
        viewer.cam.elevation = -18.0
        viewer.cam.azimuth = 135.0
        print("MuJoCo live preview open. It follows the newest saved training checkpoint.", flush=True)
        while viewer.is_running():
            now = time.monotonic()
            if now - last_reload >= RELOAD_SECONDS:
                last_reload = now
                try:
                    stat = checkpoint.stat()
                    current_stat = (stat.st_mtime_ns, stat.st_size)
                    if current_stat != loaded_stat:
                        time.sleep(0.2)
                        stable = checkpoint.stat()
                        if current_stat == (stable.st_mtime_ns, stable.st_size):
                            new_level, steps, loaded_stat = load_actor(actor, checkpoint)
                            if new_level != level:
                                raise ValueError(f"checkpoint level changed from {level!r} to {new_level!r}")
                            print(f"Reloaded checkpoint at {steps / 1e6:.1f}M steps", flush=True)
                except (OSError, RuntimeError, EOFError) as exc:
                    print(f"Checkpoint reload deferred: {exc}", flush=True)

            obs = obs_spec.compute_obs(model, data, index, previous_action, task_block(), 0.0, 1.0)
            with torch.inference_mode():
                action = actor(torch.from_numpy(obs.astype(np.float32))[None, :])[0].numpy()
            action = np.clip(action, -1.0, 1.0)
            data.ctrl[:] = index.action_to_ctrl(action)
            for _ in range(SUBSTEPS):
                mujoco.mj_step(model, data)
            previous_action = action
            episode_time += control_dt

            target = data.qpos[ball_q : ball_q + 2] if level == "l3_approach" else waypoint
            distance = np.linalg.norm(target - data.qpos[root_q : root_q + 2])
            if level == "l1_traverse" and distance < 0.5:
                reached += 1
                waypoint = rng.uniform([-13.0, -6.5], [13.0, 6.5])
                speed_command = float(rng.uniform(1.2, 3.0))
            if level == "l3_approach":
                speed = np.linalg.norm(data.qvel[root_q : root_q + 2])
                settle_time = settle_time + control_dt if distance <= 0.5 and speed <= 0.25 else 0.0
            root_pos = data.qpos[root_q : root_q + 3]
            viewer.cam.lookat[:] = [root_pos[0], root_pos[1], 0.8]
            if (
                (level == "l1_traverse" and (reached >= 10 or episode_time >= 90.0))
                or (level == "l3_approach" and (settle_time >= 0.5 or episode_time >= 12.0))
                or root_pos[2] < 0.55
            ):
                reset_episode()

            viewer.sync()
            delay = control_dt - (time.monotonic() - now)
            if delay > 0:
                time.sleep(delay)


if __name__ == "__main__":
    main()
