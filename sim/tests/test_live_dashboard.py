import json

import pytest
from tools.live_dashboard import read_snapshot, render_dashboard


@pytest.fixture
def run(tmp_path):
    config = {
        "level": "l1_traverse",
        "args": {"time_budget_min": 480},
        "control_dt": 0.02,
        "max_steps": 4500,
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "log.csv").write_text(
        "iter,steps,fps,ep_len_s,ep_return,push_scale,ppo/nan_grads_total,m/waypoints\n"
        "1,60000,1000,25,100,0.5,0,2\n"
        "2,120000,1000,35,200,1,0,3\n",
        encoding="utf-8",
    )
    return tmp_path


def test_dashboard_shows_training_metrics_and_not_a_success_rate(run):
    updated = (run / "log.csv").stat().st_mtime
    page = render_dashboard(run, now=updated + 10)

    assert 'http-equiv="refresh" content="600"' in page
    assert "Receiving updates" in page
    assert "35.0 s" in page
    assert "2 / 480 min" in page
    assert "100%" in page
    assert "3.0" in page
    assert "not the percentage of completed episodes" in page
    assert "not assessed by this dashboard" in page


def test_dashboard_handles_partial_last_write_and_stale_or_finished_runs(run):
    with (run / "log.csv").open("a", encoding="utf-8") as f:
        f.write("3,180000")
    rows, _, _, updated = read_snapshot(run)
    assert len(rows) == 2
    assert "Updates delayed" in render_dashboard(run, now=updated + 181)

    (run / "done.json").write_text(json.dumps({"stop_reason": "time budget reached"}), encoding="utf-8")
    page = render_dashboard(run, now=updated + 181)
    assert "Finished" in page
    assert "time budget reached" in page


def test_dashboard_rejects_bad_metrics(run):
    path = run / "log.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("120000,1000", "120000,nan"), encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        render_dashboard(run)
