"""Reward penalty weights and curriculum gates, read from shared/reward_config.json.

The same numbers are mirrored by the Unreal DataAsset UStreetballRewardConfig, so the trainer and the editor show one
set of values (sim/tests/test_reward_config.py keeps them equal).
"""

from __future__ import annotations

import functools
import json
import pathlib

PATH = pathlib.Path(__file__).resolve().parents[2] / "shared" / "reward_config.json"
PENALTY_TERMS = ("torque_sq", "joint_ang_vel_sq", "action_rate_sq", "foot_slip")


@functools.cache
def load(path: pathlib.Path = PATH) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    missing = [t for t in PENALTY_TERMS if t not in cfg["penalties"]]
    if missing:
        raise ValueError(f"{path}: penalties missing {missing}")
    return cfg


def penalty_weights(level_name: str) -> dict[str, float]:
    """The four penalty weights for a level: defaults, then that level's overrides."""
    cfg = load()
    w = {t: float(cfg["penalties"][t]) for t in PENALTY_TERMS}
    w.update({t: float(v) for t, v in cfg.get("level_overrides", {}).get(level_name, {}).items()})
    return w


def curriculum_threshold(stage: str) -> float | None:
    for row in load()["curriculum"]:
        if row["stage"] == stage:
            return float(row["threshold"])
    return None
