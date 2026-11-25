"""One-off chain (DOCS/20261118): wait for the L0 ablation, evaluate each ablation's final model.pt, pick the settings
that kept balance best, then run tools/posture_overnight.py with them so training + checkpoint evals end before 09:00."""

import datetime as dt
import json
import pathlib
import subprocess
import time

SIM = pathlib.Path(__file__).resolve().parents[1]
REP = SIM.parent / "DOCS" / "phase_reports"
PY = str(SIM / ".venv" / "Scripts" / "python.exe")
LOG = SIM / "runs" / "chain_until_0900.log"
ABL_LOG = SIM / "runs" / "ablation_20261118.log"
FLAGS = {
    "abl_toe": "--init-std 0.15 --toe-std 0.01",
    "abl_nopen": "--init-std 0.15 --no-v2-penalties",
    "abl_lowstd": "--init-std 0.05",
}
FALLBACK = "--init-std 0.02 --toe-std 0.01 --no-v2-penalties"
END_TRAIN = dt.time(8, 10)  # leaves ~45 min for the checkpoint evals


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def evaluate(ckpt):
    keep = {p: p.read_bytes() for p in (REP / "eval_l0_stand.json", REP / "eval_l0_stand.md")}
    try:
        (REP / "eval_l0_stand.json").unlink()
        subprocess.run(
            [PY, "-m", "streetball.evaluate", "--level", "l0_stand", "--ckpt", str(ckpt), "--push-max", "100"],
            cwd=SIM,
            capture_output=True,
        )
        p = REP / "eval_l0_stand.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    finally:
        for p, b in keep.items():
            p.write_bytes(b)


def main():
    import ctypes

    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # keep Windows awake while waiting
    deadline = time.time() + 3 * 3600
    while "ALL DONE" not in (ABL_LOG.read_text(encoding="utf-8") if ABL_LOG.exists() else ""):
        if time.time() > deadline:
            log("ablation did not finish in 3 h; continuing with what exists")
            break
        time.sleep(30)
    results = {}
    for r in FLAGS:
        ck = SIM / "runs" / f"l0_{r}" / "model.pt"
        if not ck.exists():
            log(f"{r}: no model.pt")
            continue
        j = evaluate(ck)
        if j is None:
            log(f"{r}: eval failed")
            continue
        m = j["metrics"]
        results[r] = j["success_rate"]
        log(
            f"RESULT {r} model.pt success {j['success_rate']:.3f} falls {j['fall_rate']:.3f} "
            f"jitter {m['m/quiet_jitter_cm']:.2f} speed {m['m/quiet_speed_cm_s']:.2f} torso {m['m/torso_upright']:.3f}"
        )
    best = max(results, key=results.get) if results else None
    if best is not None and results[best] >= 0.95:
        extra = FLAGS[best]
        log(f"winner {best} ({results[best]:.1%}) -> extra [{extra}]")
    else:
        extra = FALLBACK
        log(f"no ablation held 95 % (best {best}: {results.get(best)}) -> fallback [{extra}]")
    now = dt.datetime.now()
    end = dt.datetime.combine(now.date() + dt.timedelta(days=1 if now.time() > END_TRAIN else 0), END_TRAIN)
    train_min = max(30.0, (end - now).total_seconds() / 60.0)
    log(f"launch posture run: {train_min:.0f} min of training")
    subprocess.run(
        [
            PY,
            "tools/posture_overnight.py",
            "--run-name",
            "l0_v2w_posture_0900",
            "--train-min",
            f"{train_min:.0f}",
            "--ramp-steps",
            "300e6",
            "--extra",
            extra,
        ],
        cwd=SIM,
    )
    log("chain done")


if __name__ == "__main__":
    main()
