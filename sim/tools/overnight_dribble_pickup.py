"""Overnight queue 2026-11-24 (owner: "train 9 hours as needed; focus on moving on the court, dribbling, picking up a
ball with both hands"). One GPU, so the stages run back to back through tools/skill_run.py (train, then evaluate every
checkpoint on the gate). Never exports: promotion stays a reviewed run_gate.py step.

    A  l2_both_time  -> gate l2_both         stationary dribble with either hand (from the right-hand brain + mirror loss)
    B  l3a_walk_both -> gate l3a_walk_both   dribble while walking to waypoints, either hand (from A's best)
    C  l3c_pickup    -> gate l3c_pickup      walk to a ball, pick it up with both palms, hold it at chest height

Hourly progress notes: docs/<day>/overnight_dribble_pickup.md. At the end: HTML reports per run (tools/run_report.py).

    .venv/Scripts/python.exe tools/overnight_dribble_pickup.py [--minutes-per-stage 150]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
DAY = ROOT.parent / "docs" / time.strftime("%Y%m%d")
NOTES = DAY / "overnight_dribble_pickup.md"
PY = sys.executable
TAG = time.strftime("%m%d")

# warm-started dribble brains: small steps, the mirror term does the left/right transfer; no strong anchor to the
# right-only start brain (it would hold the left hand back)
DRIBBLE = "--freeze-norm --kl-target 0.02 --epochs 3 --lr-max 1e-4 --lr-min 1e-6 --anchor-coef 0.05 --assist-anneal-steps 1"


def note(msg: str) -> None:
    DAY.mkdir(parents=True, exist_ok=True)
    line = f"- {time.strftime('%H:%M')} {msg}"
    print(line, flush=True)
    with open(NOTES, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def best_ckpt(run: str) -> tuple[pathlib.Path | None, dict | None]:
    s = RUNS / run / "summary.json"
    if not s.exists():
        return None, None
    rows = json.loads(s.read_text(encoding="utf-8"))["rows"]
    if not rows:
        return None, None
    r = max(rows, key=lambda r: (r["passed"], r["success"], r["episode_s"]))
    return RUNS / run / r["ckpt"], r


def tail_metrics(run: str) -> str:
    log = RUNS / run / "log.csv"
    if not log.exists():
        return "no log yet"
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) < 2:
        return "no iterations yet"
    head = lines[0].split(",")
    last = dict(zip(head, lines[-1].split(",")))
    keep = [k for k in head if k in ("step", "steps", "reward", "ep_len") or k.startswith("m/")][:12]
    return ", ".join(f"{k} {float(last[k]):.3g}" for k in keep if last.get(k, "") not in ("", "nan"))


class Hourly(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.t0 = time.time()
        self.stage = "starting"
        self.run_name = ""

    def run(self):
        while True:
            time.sleep(3600)
            h = (time.time() - self.t0) / 3600
            note(f"hourly {h:.1f} h: stage {self.stage}; latest {self.run_name}: {tail_metrics(self.run_name)}")


def stage(hb: Hourly, label: str, level: str, gate: str, run: str, minutes: float, extra: str, ckpt_every: float) -> None:
    hb.stage, hb.run_name = label, run
    note(f"{label}: train {level} for {minutes:.0f} min, gate {gate}, run {run}; extra `{extra}`")
    cmd = [PY, "tools/skill_run.py", "--level", level, "--gate", gate, "--run-name", run, "--train-min", str(minutes),
           "--ckpt-every-steps", str(ckpt_every), "--report-name", run, "--extra", extra]
    rc = subprocess.call(cmd, cwd=ROOT)
    ck, row = best_ckpt(run)
    if row:
        note(f"{label} done (rc {rc}): best {ck.name} success {row['success'] * 100:.1f} %, passed {row['passed']}, "
             f"episode {row['episode_s']:.1f} s, fails {row['fail_reasons']}")
    else:
        note(f"{label} done (rc {rc}): no evaluated checkpoint")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes-per-stage", type=float, default=150.0)
    ap.add_argument("--ckpt-every", type=float, default=50e6)
    args = ap.parse_args()
    m = args.minutes_per_stage
    note(f"queue start: 3 stages x {m:.0f} min training (+ checkpoint evaluation), one GPU")
    hb = Hourly()
    hb.start()

    a = f"both_dribble_{TAG}"
    stage(hb, "A both-hand dribble", "l2_both_time", "l2_both", a, m,
          f"--init runs/production/dribble_anchor10.pt --init-actor-only {DRIBBLE} --sym-coef 0.2", args.ckpt_every)
    a_best, _ = best_ckpt(a)
    if a_best is not None:
        # how each hand does on its own one-hand gate
        for g in ("l2a_dribble_r", "l2b_dribble_l"):
            subprocess.call([PY, "-m", "streetball.evaluate", "--level", g, "--ckpt", str(a_best)], cwd=ROOT)
            res = ROOT.parent / "docs" / "phase_reports" / f"eval_{g}.json"
            if res.exists():
                r = json.loads(res.read_text(encoding="utf-8"))
                note(f"A best on {g}: success {r['success_rate'] * 100:.1f} %, episode {r['mean_episode_s']:.1f} s")
            subprocess.call(["git", "checkout", "--", f"docs/phase_reports/eval_{g}.json", f"docs/phase_reports/eval_{g}.md"],
                            cwd=ROOT.parent)  # keep the committed gate reports; the numbers are in the notes

    b_init = a_best if a_best is not None else RUNS / "production" / "dribble_anchor10.pt"
    b = f"walk_dribble_{TAG}"
    stage(hb, "B moving dribble", "l3a_walk_both", "l3a_walk_both", b, m,
          f"--init {b_init} --init-actor-only {DRIBBLE} --sym-coef 0.1", args.ckpt_every)

    c = f"pickup_{TAG}"
    stage(hb, "C two-hand pickup", "l3c_pickup", "l3c_pickup", c, m,
          "--init runs/production/scramble.pt --init-actor-only --freeze-norm --init-std 0.3 --sym-coef 0.1", args.ckpt_every)

    for run in (a, b, c):
        if (RUNS / run / "log.csv").exists():
            subprocess.call([PY, "tools/run_report.py", f"runs/{run}", "--out", str(DAY / f"report_{run}.html")], cwd=ROOT)
    note("queue done; HTML reports: " + ", ".join(f"report_{r}.html" for r in (a, b, c)))


if __name__ == "__main__":
    main()
