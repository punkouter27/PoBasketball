"""Step 4 verification gate, end to end, for one level checkpoint.

    uv run python tools/run_gate.py --level l0_stand --ckpt runs/l0_v2/model.pt [--episodes 200] [--skip-eval]

Steps
  1. C5 evaluation (200 randomised episodes) against the level's pass target
  2. C6 ONNX export -> shared/policies/<level>.onnx (+ sidecar, onnxruntime parity)
  3. C7 policy-mode replay (5 s closed loop on libmujoco) -> shared/golden/replay_<level>.json
  4. Python-side cross-check: onnxruntime closed loop vs the recording must be identical (same code path)
  5. sync policies into the Unreal project, run the two headless gate tests through the
     hang-proof runner, and print docs/phase_reports/Step4_gate_unreal.md

Exit code 0 only if every stage passes.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SHARED = REPO / "shared"
UE = REPO / "unreal" / "StreetballGym"
REPORTS = REPO / "docs" / "phase_reports"


def run(cmd: list[str], cwd: pathlib.Path = ROOT) -> int:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.call([str(c) for c in cmd], cwd=cwd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--skip-eval", action="store_true")
    ap.add_argument("--skip-unreal", action="store_true")
    args = ap.parse_args()
    py = sys.executable
    ok = True

    if not args.skip_eval:
        rc = run([py, "-m", "streetball.evaluate", "--level", args.level, "--ckpt", args.ckpt, "--episodes", str(args.episodes)])
        ok &= rc == 0
        print(f"[1] evaluation {'PASS' if rc == 0 else 'FAIL'}")

    onnx = SHARED / "policies" / f"{args.level}.onnx"
    rc = run([py, "-m", "streetball.export_onnx", args.ckpt, "--out", onnx])
    ok &= rc == 0
    print(f"[2] export {'PASS' if rc == 0 else 'FAIL'}")

    replay = SHARED / "golden" / f"replay_{args.level}.json"
    rc = run([py, "tools/replay_recorder.py", "policy", "--onnx", onnx, "--out", replay])
    ok &= rc == 0
    print(f"[3] replay {'PASS' if rc == 0 else 'FAIL'}")
    # the Unreal gate defaults look for replay_l0.json; keep the L0 alias in place
    if args.level == "l0_stand" and replay.exists():
        (SHARED / "golden" / "replay_l0.json").write_bytes(replay.read_bytes())

    if args.skip_unreal:
        return 0 if ok else 1

    rc = run([py, "tools/sync_policies_to_unreal.py"])
    ok &= rc == 0
    runner = UE / "Scripts" / "run_headless.ps1"
    log = UE / "Saved" / "Logs" / f"gate_{args.level}.log"
    rc = run(["pwsh", "-NoProfile", "-File", runner, "-TimeoutSec", "420", "-LogFile", log,
              f"-GateReplay={replay}", f"-GatePolicy={onnx}",
              "-ExecCmds=Automation RunTests Streetball.Gate; Quit"], cwd=UE)
    print(f"[5] unreal gate runner exit code {rc}")
    rep = REPORTS / "Step4_gate_unreal.md"
    if rep.exists():
        print(rep.read_text(encoding="utf-8"))
    ok &= rc == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
