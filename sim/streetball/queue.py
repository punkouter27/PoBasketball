"""Unattended training queue (UU_AGENT section 4): works down the skill ladder in priority order
inside a wall-clock budget, checkpoints, gates, exports production weights, retries the most
urgent failed stage with leftover time, and writes the final HTML report.

    uv run python -m streetball.queue --hours 8 [--start-from l1_traverse] [--num-envs 4096]

State and logs
  runs/queue/<YYYYMMDD_HHMM>/queue_state.json   machine-readable progress (resumable by inspection)
  runs/queue/<...>/queue_log.md                 human log, one line per event
  runs/production/<family>.onnx + manifest      final production weights (passing stages)
  DOCS/<YYYYMMDD>/extended_training_report.html final report (tools/final_report.py)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
SHARED = ROOT.parent / "shared"
DOCS = ROOT.parent / "DOCS"
PY = sys.executable

# Priority order = ladder order. minutes = first-pass time box. init = previous stage unless given.
STAGES = [
    # level, family (export name) or None, minutes, extra train args
    ("l1_traverse", "locomotion", 120, ["--push-curriculum", "--init-std", "0.3"]),
    ("l2a_dribble_r", None, 150, ["--push-max", "80"]),
    ("l2b_dribble_l", None, 40, ["--push-max", "80"]),
    ("l2c_crossover", None, 60, ["--push-max", "80"]),
    ("l3a_moving_dribble", "dribble", 80, ["--push-max", "80"]),
    ("l3b_scramble", "scramble", 50, []),
    ("l4_jump_shot", "shot", 60, ["--push-max", "0"]),
]
# Named plans (--plan): explicit stage list, each (level, family, minutes or None = rest, extra args,
# eval_level = the REAL gate level the stage is judged on, init = checkpoint for the first attempt).
# A level listed twice resumes from its own checkpoint (full optimiser state).
PLANS = {
    # 2026-11-08 night: most urgent first. Dribble blocks tiers 3-5; scramble runs every time the ball is lost in Unreal
    # (today a dummy policy). Shot needs a working dribble first, so it is not scheduled.
    "urgent_20261108": [
        ("l2a_push", "dribble", 150, ["--push-max", "80"], "l2a_dribble_r", "runs/l2a_cycles_c3/model.pt"),
        ("l3b_scramble", "scramble", 100, [], "l3b_scramble", "runs/production/locomotion.pt"),
        ("l2a_push", "dribble", 130, ["--push-max", "80"], "l2a_dribble_r", None),
        ("l3b_scramble", "scramble", None, [], "l3b_scramble", None),
    ],
}
RESERVE_MIN = 25          # kept free at the end for evaluation/report
MIN_STAGE_MIN = 12        # never start a stage with less than this


class Queue:
    def __init__(self, hours: float, num_envs: int, start_from: str | None, init_ckpt: str | None,
                 tag: str = "", init_actor_only: bool = False):
        self.t0 = time.time()
        self.tag = tag
        self.current_run: str | None = None
        self.deadline = self.t0 + hours * 3600
        self.num_envs = num_envs
        stamp = time.strftime("%Y%m%d_%H%M")
        self.dir = RUNS / "queue" / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "queue_state.json"
        self.log_path = self.dir / "queue_log.md"
        self.state = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "hours": hours, "stages": {}, "events": []}
        self.prev_ckpt = init_ckpt
        self.start_from = start_from
        if init_ckpt and start_from and not init_actor_only:
            # same-level checkpoint: resume with the full optimiser state instead of actor-only
            self.state["stages"][start_from] = {"family": None, "attempts": [], "passed": False, "checkpoint": init_ckpt}
            for lv, fam, _, _ in STAGES:
                if lv == start_from:
                    self.state["stages"][start_from]["family"] = fam
        self.log(f"queue started, budget {hours} h, deadline {time.strftime('%H:%M', time.localtime(self.deadline))}")

    # ------------------------------------------------------------------ utils
    def minutes_left(self) -> float:
        return (self.deadline - time.time()) / 60

    def log(self, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.state["events"].append(line)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def run(self, cmd: list[str], timeout_s: float | None = None) -> int:
        self.log("+ " + " ".join(str(c) for c in cmd))
        try:
            return subprocess.call([str(c) for c in cmd], cwd=ROOT, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.log("  timeout; process killed")
            return 124

    # ------------------------------------------------------------------ one stage attempt
    def train_stage(self, level: str, family: str | None, minutes: float, extra: list[str], attempt: int,
                    eval_level: str | None = None, init_override: str | None = None) -> dict:
        eval_level = eval_level or level
        run_name = f"{level}_{self.tag}q{attempt}"
        self.current_run = run_name
        st = self.state["stages"].setdefault(level, {"family": family, "attempts": [], "passed": False, "checkpoint": None})
        steps = 1e9  # the time budget is the real limit
        cmd = [PY, "-m", "streetball.train", "--level", level, "--steps", str(steps), "--num-envs", str(self.num_envs),
               "--run-name", run_name, "--time-budget-min", f"{minutes:.1f}"] + extra
        init = st["checkpoint"] or init_override or self.prev_ckpt
        if init:
            same_level = st["checkpoint"] is not None
            cmd += ["--init", init] + ([] if same_level else ["--init-actor-only"])
        self.log(f"stage {level} attempt {attempt}: {minutes:.0f} min, init={init}")
        rc = self.run(cmd, timeout_s=minutes * 60 + 900)
        ckpt = RUNS / run_name / "model.pt"
        rec = {"run": run_name, "minutes": minutes, "train_rc": rc, "checkpoint": str(ckpt) if ckpt.exists() else None}
        done = RUNS / run_name / "done.json"
        if done.exists():
            rec.update(json.loads(done.read_text(encoding="utf-8")))
        if ckpt.exists():
            st["checkpoint"] = str(ckpt)
            # evaluation (200 episodes) with a hard cap so a slow level cannot eat the budget
            rc_eval = self.run([PY, "-m", "streetball.evaluate", "--level", eval_level, "--ckpt", str(ckpt)], timeout_s=1200)
            ev = DOCS / "phase_reports" / f"eval_{eval_level}.json"
            if ev.exists():
                e = json.loads(ev.read_text(encoding="utf-8"))
                rec["eval"] = {k: e.get(k) for k in ("success_rate", "passed", "holds_100_straight", "fall_rate", "mean_episode_s", "nan_grads")}
                rec["eval"]["level"] = eval_level
                rec["eval"]["metrics"] = {k: v for k, v in e.items() if isinstance(v, (int, float)) and k not in rec["eval"]}
                shutil.copy2(ev, RUNS / run_name / "eval.json")
            rec["passed"] = rc_eval == 0
            st["passed"] = st["passed"] or rec["passed"]
            if rec["passed"] and family:
                self.export(level, family, ckpt)
            elif family and not st["passed"]:
                self.save_candidate(family, ckpt, level)
            self.run([PY, "tools/run_report.py", str(RUNS / run_name)], timeout_s=300)
        st["attempts"].append(rec)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        self.log(f"stage {level} attempt {attempt} finished: passed={rec.get('passed')} eval={rec.get('eval')}")
        return rec

    def export(self, level: str, family: str, ckpt: pathlib.Path):
        prod = RUNS / "production"
        prod.mkdir(exist_ok=True)
        onnx = SHARED / "policies" / f"{family}.onnx"
        rc = self.run([PY, "-m", "streetball.export_onnx", str(ckpt), "--out", str(onnx)], timeout_s=600)
        if rc == 0:
            shutil.copy2(onnx, prod / f"{family}.onnx")
            shutil.copy2(onnx.with_suffix(".json"), prod / f"{family}.json")
            shutil.copy2(ckpt, prod / f"{family}.pt")
            self.run([PY, "tools/sync_policies_to_unreal.py"], timeout_s=300)
            self.log(f"PRODUCTION: {family} <- {level} ({ckpt})")
        self.write_manifest()

    def save_candidate(self, family: str, ckpt: pathlib.Path, level: str):
        cand = RUNS / "production" / "candidates"
        cand.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ckpt, cand / f"{family}_{level}.pt")
        self.write_manifest()

    def write_manifest(self):
        prod = RUNS / "production"
        prod.mkdir(exist_ok=True)
        man = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "families": {}}
        for f in sorted(p for p in prod.glob("*.json") if p.name != "production_manifest.json"):
            man["families"][f.stem] = json.loads(f.read_text(encoding="utf-8"))
        man["stages"] = self.state["stages"]
        (prod / "production_manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ hourly status (UU_AGENT section 4)
    def hourly_status(self):
        day = time.strftime("%Y%m%d")
        path = DOCS / day / "hourly_status.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            time.sleep(3600)
            lines = [f"\n## {time.strftime('%H:%M')} - {self.minutes_left():.0f} min left, current run {self.current_run}\n",
                     "| Stage | Attempts | Passed | Last eval success |", "|---|---|---|---|"]
            for lv, st in self.state["stages"].items():
                ev = (st["attempts"][-1].get("eval") or {}) if st["attempts"] else {}
                lines.append(f"| {lv} | {len(st['attempts'])} | {st['passed']} | {ev.get('success_rate')} |")
            csvp = RUNS / str(self.current_run) / "log.csv"
            if csvp.exists():
                rows = csvp.read_text(encoding="utf-8").splitlines()
                if len(rows) > 1:
                    hdr, last = rows[0].split(","), rows[-1].split(",")
                    keep = [k for k in hdr if k in ("steps", "fps", "ep_return", "ep_len_s") or k.startswith("m/")]
                    lines.append("\nLatest iteration: " + ", ".join(f"{k}={last[hdr.index(k)][:8]}" for k in keep))
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    # ------------------------------------------------------------------ main loop
    def run_plan(self, plan: list):
        threading.Thread(target=self.hourly_status, daemon=True).start()
        attempts: dict[str, int] = {}
        for level, family, minutes, extra, eval_level, init in plan:
            left = self.minutes_left() - RESERVE_MIN
            budget = left if minutes is None else min(minutes, left)
            if budget < MIN_STAGE_MIN:
                self.log(f"skipping {level}: only {self.minutes_left():.0f} min left")
                continue
            attempts[level] = attempts.get(level, 0) + 1
            init_path = str(ROOT / init) if init else None
            self.train_stage(level, family, budget, extra, attempts[level], eval_level, init_path)
        self.log("plan finished; writing the final report")
        self.write_manifest()
        self.run([PY, "tools/final_report.py", "--queue-dir", str(self.dir)], timeout_s=600)
        self.log("done")

    def main(self):
        threading.Thread(target=self.hourly_status, daemon=True).start()
        started = self.start_from is None
        for level, family, minutes, extra in STAGES:
            if not started:
                started = level == self.start_from
                if not started:
                    continue
            budget = min(minutes, self.minutes_left() - RESERVE_MIN)
            if budget < MIN_STAGE_MIN:
                self.log(f"skipping {level}: only {self.minutes_left():.0f} min left")
                continue
            rec = self.train_stage(level, family, budget, extra, attempt=1)
            if rec.get("checkpoint"):
                self.prev_ckpt = rec["checkpoint"]
        # retry loop: most urgent (earliest) failed stage first, split the leftover time
        attempt = 2
        while self.minutes_left() - RESERVE_MIN >= MIN_STAGE_MIN and attempt <= 6:
            failed = [(lv, fam, mins, ex) for lv, fam, mins, ex in STAGES
                      if lv in self.state["stages"] and not self.state["stages"][lv]["passed"]]
            if not failed:
                self.log("all attempted stages passed; spending leftover time on the last family")
                failed = [STAGES[-1]]
            level, family, minutes, extra = failed[0]
            budget = min(max(minutes, 30), self.minutes_left() - RESERVE_MIN)
            self.train_stage(level, family, budget, extra, attempt=attempt)
            attempt += 1
        self.log("queue finished; writing the final report")
        self.write_manifest()
        self.run([PY, "tools/final_report.py", "--queue-dir", str(self.dir)], timeout_s=600)
        self.log("done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--num-envs", type=int, default=4096)
    ap.add_argument("--start-from", default=None)
    ap.add_argument("--init", default=None, help="checkpoint to initialise the first stage from")
    ap.add_argument("--init-actor-only", action="store_true",
                    help="--init is another level's checkpoint (actor weights only, fresh critic)")
    ap.add_argument("--stage-minutes", default="", help="first-pass overrides, e.g. l2a_dribble_r=240,l4_jump_shot=30")
    ap.add_argument("--tag", default="", help="run-name prefix so a new queue never overwrites older runs, e.g. r2")
    ap.add_argument("--plan", default=None, choices=sorted(PLANS), help="run a named explicit stage plan instead of the ladder")
    args = ap.parse_args()
    if args.plan:
        Queue(args.hours, args.num_envs, None, None, args.tag).run_plan(PLANS[args.plan])
        return
    over = dict(kv.split("=") for kv in args.stage_minutes.split(",") if kv)
    STAGES[:] = [(lv, fam, float(over.get(lv, mins)), ex) for lv, fam, mins, ex in STAGES]
    Queue(args.hours, args.num_envs, args.start_from, args.init, args.tag, args.init_actor_only).main()


if __name__ == "__main__":
    main()
