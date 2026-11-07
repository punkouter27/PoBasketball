"""C8: one-command training ladder with resume.

    uv run python -m streetball.curriculum [--from l2a_dribble_r] [--steps-scale 1.0]

For each level in LADDER (in order): train (initialised from the previous level's actor),
evaluate with the C5 harness, export ONNX to shared/policies/<level>.onnx, and stop the
ladder if the level fails its pass target. Progress is recorded in runs/curriculum.json so a
re-run skips levels already marked passed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
STATE = RUNS / "curriculum.json"
POLICIES = ROOT.parent / "shared" / "policies"

# level name -> (env steps, extra train args)
LADDER: list[tuple[str, float, list[str]]] = [
    ("l0_stand", 150e6, ["--push-curriculum", "--push-max", "100", "--init-std", "0.3"]),
    ("l1_traverse", 300e6, ["--push-curriculum"]),
    ("l2a_dribble_r", 400e6, []),
    ("l2b_dribble_l", 200e6, []),
    ("l2c_crossover", 300e6, []),
    ("l3a_moving_dribble", 500e6, []),
    ("l3b_scramble", 300e6, []),
    ("l4_jump_shot", 500e6, []),
]


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=None, help="restart the ladder at this level")
    ap.add_argument("--steps-scale", type=float, default=1.0)
    ap.add_argument("--num-envs", type=int, default=4096)
    args = ap.parse_args()

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    prev_ckpt = None
    py = [sys.executable, "-m"]
    started = args.start is None
    for name, steps, extra in LADDER:
        if not started:
            started = name == args.start
            if not started:
                prev_ckpt = state.get(name, {}).get("checkpoint", prev_ckpt)
                continue
        if state.get(name, {}).get("passed") and args.start != name:
            print(f"[{name}] already passed, skipping")
            prev_ckpt = state[name]["checkpoint"]
            continue
        run_name = f"{name}_cur"
        cmd = py + ["streetball.train", "--level", name, "--steps", str(steps * args.steps_scale),
                    "--num-envs", str(args.num_envs), "--run-name", run_name] + extra
        if prev_ckpt:
            cmd += ["--init", prev_ckpt, "--init-actor-only"]
        if run(cmd) != 0:
            print(f"[{name}] training failed"); sys.exit(1)
        ckpt = str(RUNS / run_name / "model.pt")
        ok = run(py + ["streetball.evaluate", "--level", name, "--ckpt", ckpt]) == 0
        onnx = str(POLICIES / f"{name}.onnx")
        run(py + ["streetball.export_onnx", ckpt, "--out", onnx])
        state[name] = {"checkpoint": ckpt, "onnx": onnx, "passed": ok}
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        if not ok:
            print(f"[{name}] FAILED its pass target; ladder stopped. Fix the level and re-run with --from {name}")
            sys.exit(2)
        prev_ckpt = ckpt
    print("ladder complete")


if __name__ == "__main__":
    main()
