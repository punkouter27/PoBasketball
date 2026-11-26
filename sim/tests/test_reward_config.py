"""The trainer reads its penalty weights and curriculum gates from shared/reward_config.json (idea C9/C10)."""

import json
import pathlib

import pytest

from streetball import reward_config

JSON = pathlib.Path(__file__).resolve().parents[2] / "shared" / "reward_config.json"


def test_json_has_every_penalty_all_non_positive():
    cfg = json.loads(JSON.read_text(encoding="utf-8"))
    assert set(cfg["penalties"]) == set(reward_config.PENALTY_TERMS)
    for term, w in cfg["penalties"].items():
        assert w <= 0.0, f"{term} is a penalty: its weight must be <= 0"
    for level, overrides in cfg.get("level_overrides", {}).items():
        assert set(overrides) <= set(reward_config.PENALTY_TERMS), level


def test_loader_matches_json():
    cfg = json.loads(JSON.read_text(encoding="utf-8"))
    assert reward_config.PATH.resolve() == JSON.resolve()
    w = reward_config.penalty_weights("l1_traverse")
    assert w == {t: float(cfg["penalties"][t]) for t in reward_config.PENALTY_TERMS}
    w0 = reward_config.penalty_weights("l0_stand")
    assert w0["joint_ang_vel_sq"] == cfg["level_overrides"]["l0_stand"]["joint_ang_vel_sq"]
    for row in cfg["curriculum"]:
        assert reward_config.curriculum_threshold(row["stage"]) == row["threshold"]
    assert reward_config.curriculum_threshold("no_such_level") is None


def test_levels_take_their_gates_from_the_json():
    pytest.importorskip("torch", reason="torch not installed: level classes need it (runs in sim/.venv)")
    from streetball.levels import LEVELS, make

    cfg = json.loads(JSON.read_text(encoding="utf-8"))
    gates = {row["stage"]: row["threshold"] for row in cfg["curriculum"]}
    for stage, threshold in gates.items():
        assert make(stage).pass_fraction == threshold, stage
    # variants inherit the gate of their parent level
    for name in LEVELS:
        assert 0.0 < make(name).pass_fraction <= 1.0, name
    assert make("l2b_dribble_l").pass_fraction == gates["l2a_dribble_r"]
    assert make("l1_traverse_amp").pass_fraction == gates["l1_traverse"]
