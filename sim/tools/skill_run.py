"""Train one level for a time budget, then evaluate every checkpoint on a gate level and write a report.

    .venv/Scripts/python.exe tools/skill_run.py --level l2a_push --gate l2a_dribble_r --run-name dribble_t1 \
        --train-min 120 --report-name dribble_t1 --extra "--init runs/production/balance_quiet.pt --init-actor-only"

Outputs: runs/<run>/ (checkpoints, eval_<ckpt>.json), runs/<run>.driver.log / .train.out, docs/<YYYYMMDD>/<report>.md.
Keeps Windows awake for its lifetime. Never exports: promotion is a reviewed run_gate.py run.
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
REPORTS = REPO / "docs" / "phase_reports"
PY = sys.executable


def log(run_dir: pathlib.Path, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(run_dir.parent / f"{run_dir.name}.driver.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def evaluate(run_dir: pathlib.Path, gate: str, ckpt: pathlib.Path, extra: list[str]) -> dict:
    # evaluate.py writes docs/phase_reports/eval_<gate>.*; keep the committed report intact around it
    names = (REPORTS / f"eval_{gate}.json", REPORTS / f"eval_{gate}.md")
    keep = {p: p.read_bytes() for p in names if p.exists()}
    try:
        subprocess.run(
            [PY, "-m", "streetball.evaluate", "--level", gate, "--ckpt", str(ckpt)] + extra,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        res = json.loads(names[0].read_text(encoding="utf-8"))
        shutil.copy(names[0], run_dir / f"eval_{ckpt.stem}.json")
    finally:
        for p in names:
            if p in keep:
                p.write_bytes(keep[p])
            elif p.exists():
                p.unlink()
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", required=True, help="training level")
    ap.add_argument("--gate", required=True, help="gate level every checkpoint is evaluated on")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--train-min", type=float, required=True)
    ap.add_argument("--ckpt-every-steps", type=float, default=25e6)
    ap.add_argument("--report-name", required=True)
    ap.add_argument("--eval-extra", default="", help="extra evaluate.py args")
    ap.add_argument("--extra", default="", help="extra train.py args, appended last (later flags win)")
    args = ap.parse_args()
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    run_dir = ROOT / "runs" / args.run_name
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    log(run_dir, f"start: {args.level} for {args.train_min} min, gate {args.gate}, extra [{args.extra}]")
    cmd = [
        PY,
        "-m",
        "streetball.train",
        "--level",
        args.level,
        "--run-name",
        args.run_name,
        "--steps",
        "5e9",
        "--time-budget-min",
        str(args.train_min),
        "--ckpt-every-steps",
        str(args.ckpt_every_steps),
    ] + args.extra.split()
    with open(run_dir.parent / f"{args.run_name}.train.out", "w", encoding="utf-8") as out:
        rc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT).returncode
    log(run_dir, f"training exit {rc}")

    ckpts = sorted(run_dir.glob("ckpt_*M.pt"), key=lambda p: float(p.stem[5:-1])) + [
        p for p in (run_dir / "best.pt", run_dir / "model.pt") if p.exists()
    ]
    rows = []
    for c in ckpts:
        r = evaluate(run_dir, args.gate, c, args.eval_extra.split())
        m = r["metrics"]
        row = {
            "ckpt": c.name,
            "success": r["success_rate"],
            "holds_100": r["holds_100_straight"],
            "passed": r["passed"],
            "falls": r.get("fall_rate"),
            "episode_s": r["mean_episode_s"],
            "metrics": {k: round(v, 4) for k, v in m.items()},
            "fail_reasons": {k: round(v, 4) for k, v in r.get("fail_reasons", {}).items()},
            "nan_grads": r["nan_grads"],
        }
        rows.append(row)
        log(run_dir, "eval " + json.dumps(row))
    ok = [r for r in rows if r["passed"]]
    (run_dir / "summary.json").write_text(
        json.dumps({"rows": rows, "passed": [r["ckpt"] for r in ok]}, indent=2), encoding="utf-8"
    )

    keys = sorted({k for r in rows for k in r["metrics"]})
    fkeys = sorted({k for r in rows for k in r["fail_reasons"]})
    day = REPO / "docs" / time.strftime("%Y%m%d")
    day.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {args.run_name}: {args.level} -> gate {args.gate}",
        "",
        f"Train {args.train_min} min, extra `{args.extra}`. Every checkpoint evaluated on `{args.gate}` (200 episodes).",
        "",
        "| Checkpoint | Success | Holds 100 | Falls | Episode s | "
        + " | ".join(k.removeprefix("m/") for k in keys)
        + " |",
        "|---" * (5 + len(keys)) + "|",
    ]
    for r in rows:
        lines.append(
            f"| {r['ckpt']} | {r['success']:.1%} | {'yes' if r['holds_100'] else 'no'} | {r['falls']:.1%} | {r['episode_s']:.1f} | "
            + " | ".join(f"{r['metrics'].get(k, float('nan')):.3f}" for k in keys)
            + " |"
        )
    if fkeys:
        lines += [
            "",
            "Failure reasons (share of all episodes, not exclusive):",
            "",
            "| Checkpoint | " + " | ".join(fkeys) + " |",
            "|---" * (1 + len(fkeys)) + "|",
        ]
        for r in rows:
            lines.append(f"| {r['ckpt']} | " + " | ".join(f"{r['fail_reasons'].get(k, 0):.1%}" for k in fkeys) + " |")
    lines += ["", f"**Passed the gate:** {', '.join(r['ckpt'] for r in ok) if ok else 'none'}."]
    (day / f"{args.report_name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(run_dir, f"done; passed {[r['ckpt'] for r in ok]}; report {day / (args.report_name + '.md')}")


if __name__ == "__main__":
    main()
