"""PoBasketball Workload: the real sim/streetball/train.py (own PPO on MuJoCo Warp), with the settings of the current
main training run - the stationary dribble resume planned in docs/20261121/log.md (15:00, "Next run"), which repeats
the dribble_45b / dribble_time10d PPO settings: level l2a_time, 4096 envs, 24 steps per env, 45 s horizon.

Run by serve.py with the training venv:  sim/.venv/Scripts/python.exe benchmark/workload.py
train.py times each iteration inline (t_roll, t_upd) and only logs fps = steps_per_iter / (t_roll + t_upd). The hooks
below time PPO.update (= t_upd, Learn time) and take the iteration total from the "fps" scalar, so Sim time is
exactly train.py's t_roll (env stepping + policy inference + GAE). One iteration = steps_per_env Steps.
The run writes only to sim/runs/_benchmark (gitignored, removed afterwards); the --init checkpoint is only read.
"""

from __future__ import annotations

import gc
import io
import os
import runpy
import shutil
import sys
import time
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "sim"
NAME = "_benchmark"
INIT = "runs/production/dribble_anchor_init.pt"
# Same settings as the main training run (docs/20261121/log.md 15:00). Change these and the Workload ID changes.
# --steps / --ckpt-every-steps / --save-every only stop checkpoint writes inside the window; they do not change the work.
ARGS = [
    "--level", "l2a_time", "--num-envs", "4096", "--steps-per-env", "24",
    "--init", INIT, "--freeze-norm", "--horizon0", "45", "--kl-target", "0.02", "--epochs", "2",
    "--lr-max", "2e-5", "--lr-min", "1e-7", "--anchor-coef", "1.0", "--assist-anneal-steps", "1",
    "--run-name", NAME, "--steps", "5e9", "--ckpt-every-steps", "0", "--save-every", "1000000",
]  # fmt: skip


def version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def remove_run_dir(run_dir: Path) -> None:
    """train.py keeps log.csv and the TensorBoard file open; Windows cannot delete open files, so close them first."""
    for obj in gc.get_objects():
        try:
            name = getattr(obj, "name", None) if isinstance(obj, io.IOBase) else None
            if isinstance(name, str) and Path(name).resolve().is_relative_to(run_dir):  # train.py opens it relative
                obj.close()
            elif type(obj).__name__ == "SummaryWriter":
                obj.close()
        except Exception:  # noqa: BLE001 - best effort; a leftover gitignored dir is harmless
            pass
    shutil.rmtree(run_dir, ignore_errors=True)


def main() -> None:
    os.chdir(SIM)
    sys.path.insert(0, str(SIM))
    run_dir = SIM / "runs" / NAME
    shutil.rmtree(run_dir, ignore_errors=True)

    from torch.utils.tensorboard import SummaryWriter

    from streetball.ppo import PPO

    meter: core.Meter | None = None
    learn = {"s": 0.0}
    ppo_init, ppo_update, add_scalar = PPO.__init__, PPO.update, SummaryWriter.add_scalar

    def init_(self, n_obs, n_act, num_envs, cfg, device):
        nonlocal meter
        ppo_init(self, n_obs, n_act, num_envs, cfg, device)
        from dataclasses import asdict

        workload = dict(
            repo="PoBasketball",
            trainer="streetball PPO (own) on mujoco_warp " + str(version("mujoco-warp")),
            script="sim/streetball/train.py",
            args=" ".join(ARGS),
            num_envs=num_envs,
            horizon=cfg.steps_per_env,
            net=list(cfg.hidden),
            n_obs=n_obs,
            n_act=n_act,
            init=INIT,
            config_hash=core.workload_id({"ppo": asdict(cfg), "args": ARGS}),
        )
        versions = dict(
            python=sys.version.split()[0],
            torch=version("torch"),
            mujoco=version("mujoco"),
            mujoco_warp=version("mujoco-warp"),
            warp=version("warp-lang"),
        )
        meter = core.Meter(workload, versions)
        meter.on_exit.append(lambda: remove_run_dir(run_dir))

    def update_(self, *a, **k):
        if self.device.type == "cuda":  # pending rollout kernels belong to Sim time
            import torch

            torch.cuda.synchronize()
        t = time.time()
        out = ppo_update(self, *a, **k)  # returns float stats (.item() syncs), so the time below is real GPU time
        learn["s"] = time.time() - t
        return out

    def add_scalar_(self, tag, value, *a, **k):
        add_scalar(self, tag, value, *a, **k)
        if tag == "fps" and meter is not None:
            steps = meter.workload["horizon"]
            total = steps * meter.workload["num_envs"] / value
            meter.block(max(total - learn["s"], 0.0), learn["s"], steps)

    PPO.__init__, PPO.update, SummaryWriter.add_scalar = init_, update_, add_scalar_
    sys.argv = ["streetball/train.py", *ARGS]
    try:
        runpy.run_path(str(SIM / "streetball" / "train.py"), run_name="__main__")
        raise RuntimeError("training ended before the measured window was complete")
    except BaseException as e:  # noqa: BLE001 - every failure becomes a failed row, never a silent miss
        if meter is None:
            meter = core.Meter({"repo": "PoBasketball", "args": " ".join(ARGS)}, {"python": sys.version.split()[0]})
            meter.on_exit.append(lambda: remove_run_dir(run_dir))
        meter.finish(ok=False, error=core.fail_text(e))


if __name__ == "__main__":
    main()
