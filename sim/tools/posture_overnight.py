"""Overnight L0 posture curriculum (DOCS/20261118, step 3): fine-tune the production v2 balance brain while the posture
reward is blended from v1 (pelvis upright) to v2 (pelvis + torso upright), then evaluate every checkpoint and pick the
straightest-torso one that still passes the L0 gate. Never exports: the pick is written up for review.

    uv run python tools/posture_overnight.py [--train-min 330] [--ramp-steps 200e6]

Outputs: runs/<run>/ (checkpoints, log.csv, eval_<ckpt>.json) and DOCS/<YYYYMMDD>/posture_overnight.md.
Keeps Windows awake for its own lifetime (SetThreadExecutionState); restores nothing else.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
REPORTS = REPO / "DOCS" / "phase_reports"
PY = sys.executable
BASELINE = {"success_rate": 0.99, "fall_rate": 0.005, "torso_upright": 0.875}   # widened v1, no training (DOCS/20261118)


def keep_awake() -> None:
    if sys.platform == "win32":
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def log(run_dir: pathlib.Path, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(run_dir.parent / f"{run_dir.name}.driver.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def evaluate(run_dir: pathlib.Path, ckpt: pathlib.Path) -> dict:
    # evaluate.py writes DOCS/phase_reports/eval_l0_stand.*; keep the production report intact around it
    keep = {p: p.read_bytes() for p in (REPORTS / "eval_l0_stand.json", REPORTS / "eval_l0_stand.md") if p.exists()}
    try:
        subprocess.run([PY, "-m", "streetball.evaluate", "--level", "l0_stand", "--ckpt", str(ckpt), "--push-max", "100"],
                       cwd=ROOT, capture_output=True, text=True)
        res = json.loads((REPORTS / "eval_l0_stand.json").read_text(encoding="utf-8"))
        shutil.copy(REPORTS / "eval_l0_stand.json", run_dir / f"eval_{ckpt.stem}.json")
    finally:
        for p, b in keep.items():
            p.write_bytes(b)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", default="l0_v2w_posture")
    ap.add_argument("--train-min", type=float, default=330.0)
    ap.add_argument("--ramp-steps", type=float, default=200e6)
    ap.add_argument("--init", default="runs/production/balance_v1w.pt")
    ap.add_argument("--extra", default="", help="extra train.py args appended last (later flags win), e.g. \"--init-std 0.05\"")
    args = ap.parse_args()
    keep_awake()
    run_dir = ROOT / "runs" / args.run_name
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    log(run_dir, f"start: train {args.train_min} min, ramp {args.ramp_steps / 1e6:.0f} M steps, init {args.init}, extra [{args.extra}]")

    cmd = [PY, "-m", "streetball.train", "--level", "l0_stand", "--run-name", args.run_name,
           "--init", args.init, "--init-actor-only", "--freeze-norm", "--critic-warmup-iters", "60",
           "--init-std", "0.15", "--push-max", "100", "--lr", "3e-4", "--lr-max", "1e-4", "--kl-target", "0.005",
           "--posture-ramp-steps", str(args.ramp_steps), "--steps", "2e9", "--time-budget-min", str(args.train_min),
           "--ckpt-every-steps", "25e6"] + args.extra.split()
    with open(run_dir.parent / f"{args.run_name}.train.out", "w", encoding="utf-8") as out:
        rc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT).returncode
    log(run_dir, f"training exit {rc}")

    ckpts = sorted(run_dir.glob("ckpt_*M.pt"), key=lambda p: float(p.stem[5:-1])) + \
        [p for p in (run_dir / "best.pt", run_dir / "model.pt") if p.exists()]
    rows = []
    for c in ckpts:
        r = evaluate(run_dir, c)
        m = r["metrics"]
        row = {"ckpt": c.name, "success": r["success_rate"], "holds_100": r["holds_100_straight"], "passed": r["passed"],
               "falls": r.get("fall_rate"), "torso": m["m/torso_upright"], "jitter": m["m/quiet_jitter_cm"],
               "speed": m["m/quiet_speed_cm_s"], "drift": m["m/foot_drift_cm"], "nan_grads": r["nan_grads"]}
        rows.append(row)
        log(run_dir, "eval " + json.dumps(row))

    ok = [r for r in rows if r["passed"] and r["holds_100"] and r["nan_grads"] == 0]
    pick = max(ok, key=lambda r: r["torso"]) if ok else None
    better = pick is not None and pick["torso"] > BASELINE["torso_upright"] + 0.02
    (run_dir / "pick.json").write_text(json.dumps({"pick": pick, "rows": rows, "baseline": BASELINE}, indent=2), encoding="utf-8")

    day = REPO / "DOCS" / time.strftime("%Y%m%d")
    day.mkdir(parents=True, exist_ok=True)
    lines = [f"# L0 posture curriculum overnight ({args.run_name})", "",
             f"Train {args.train_min} min from `{args.init}`, posture blend v1->v2 over {args.ramp_steps / 1e6:.0f} M steps "
             "after a 60-iteration critic warm-up; normaliser frozen. Gate: >= 95 % success, holds 100 straight, 0 NaN.", "",
             f"Baseline (widened v1, production): success {BASELINE['success_rate']:.1%}, falls {BASELINE['fall_rate']:.1%}, "
             f"torso_upright {BASELINE['torso_upright']:.3f}", "",
             "| Checkpoint | Success | Holds 100 | Falls | Torso upright | Jitter cm | Speed cm/s | Drift cm |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['ckpt']} | {r['success']:.1%} | {'yes' if r['holds_100'] else 'no'} | {r['falls']:.1%} | "
                     f"{r['torso']:.3f} | {r['jitter']:.2f} | {r['speed']:.2f} | {r['drift']:.1f} |")
    lines += ["", ("**Pick:** `" + pick["ckpt"] + f"` (torso {pick['torso']:.3f} vs baseline {BASELINE['torso_upright']:.3f}). "
                   + ("Better than production: review, then export with run_gate." if better else
                      "Not meaningfully straighter than production (< +0.02): keep production."))
              if pick else "**No checkpoint passed the gate.** Production balance stays the widened v1 brain."]
    (day / "posture_overnight.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(run_dir, f"done; pick {pick['ckpt'] if pick else None}; report {day / 'posture_overnight.md'}")


if __name__ == "__main__":
    main()
