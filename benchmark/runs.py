"""Training runs grid: sim/runs/runs.html, one row per real training run under sim/runs/, newest first.

    python benchmark/runs.py                                   rebuild sim/runs/runs.html from the run folders
    python benchmark/runs.py --record <run-id> --ended "<how>" [--launcher <script>] [--started <epoch s>]
                                                               note this machine and how the run ended, then rebuild

The grid is rebuilt from what sim/streetball/train.py (and train_amp.py) leave in each run folder (config.json: the
arguments, written once the env is built; log.csv: one row per PPO iteration with steps and fps; done.json: written
only when the loop ends normally; ckpt_<N>M.pt / model.pt; the TensorBoard file name, which carries the host name), so
a run started by hand, or one whose process was killed, still gets a row. What the folder cannot tell (which commit,
which GPU, how the run ended) comes from sim/runs/<run>/run_meta.json, which --record writes; train.py and
train_amp.py call it when they end, crash or not. Without it those cells read "-".

Speed is the run's own: env steps per second over this session's PPO iterations (log.csv steps / sum of the iteration
times train.py measured; train.py rewrites log.csv each session, so an --init warm start is not credited with the steps
of its parent run). Benchmark is the newest benchmark/history.json result on the same machine from before the run
started (ms per batched env step of all envs + env steps/s), for comparison. Stdlib only; core.py next to this file
supplies the machine description.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import html
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = ROOT / "sim" / "runs"
OUT = RESULTS / "runs.html"
BENCH = HERE / "history.json"
META = "run_meta.json"
TITLE = "PoBasketball"
SKIP = {"_benchmark"}  # the Benchmark's own throwaway run dir (benchmark/workload.py NAME)
# What the trainer writes while it trains (eval_*.json etc. are written later by the gate tools; they are not training).
TRAINING_FILES = ("log.csv", "done.json", "model.pt", "best.pt", "ckpt_*.pt", "events.out.tfevents.*")
# Console logs the launchers (tools/skill_run.py, posture_overnight.py, hand-run shells) keep next to the run dir.
SIDE_LOGS = (".train.out", ".out", ".stderr.log", ".console.err", ".console.out")


# ---------------------------------------------------------------- collect


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _log_csv(path: Path) -> tuple[int | None, float | None]:
    """(env steps reached, env steps/s this session) from train.py's log.csv: steps / sum of iteration times."""
    steps, prev, secs = None, 0, 0.0
    try:
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    s, fps = int(float(row["steps"])), float(row["fps"])
                except (KeyError, TypeError, ValueError):
                    continue
                if fps > 0 and s > prev:
                    secs += (s - prev) / fps
                steps, prev = s, s
    except OSError:
        return None, None
    return steps, (steps / secs if steps and secs > 0 else None)


def _ckpt_steps(d: Path) -> int | None:
    found = [float(m.group(1)) for p in d.glob("ckpt_*M.pt") if (m := re.fullmatch(r"ckpt_([\d.]+)M\.pt", p.name))]
    return int(max(found) * 1e6) if found else None


def _side_logs(d: Path) -> tuple[str | None, str | None]:
    """(traceback note, GPU name) from the console logs a launcher kept next to the run dir, if any."""
    crash, gpu = None, None
    for suffix in SIDE_LOGS:
        p = d.parent / (d.name + suffix)
        if not p.is_file():
            continue
        try:
            with p.open("rb") as f:
                head = f.read(4096).decode("utf-8", "replace")
                f.seek(max(0, p.stat().st_size - 16384))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        m = re.search(r'"cuda:0"\s*:\s*"([^"]+)"', head)
        gpu = gpu or (m.group(1) if m else None)
        if not crash and "Traceback (most recent call last)" in tail:
            last = [ln.strip() for ln in tail.splitlines() if re.match(r"\w*(Error|Exception|Interrupt)\b", ln.strip())]
            crash = f"crashed: {last[-1][:120]}" if last else f"crashed (traceback in {p.name})"
    return crash, gpu


def _bench_for(host: str | None, before: float) -> dict | None:
    runs = [r for r in _json(BENCH).get("runs", []) if r.get("ok") and r.get("result")]
    if host:
        runs = [r for r in runs if r.get("machine", {}).get("hostname") == host]
    if not runs:
        return None
    stamp = lambda r: datetime.datetime.fromisoformat(r["when"]).timestamp()
    earlier = [r for r in runs if stamp(r) <= before]
    return (earlier or runs)[-1]


def _fmt_num(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def _config(cfg: dict) -> tuple[str | None, str]:
    """(level, key arguments) for the Config cell."""
    a = cfg.get("args", {})
    level = cfg.get("level") or a.get("level")
    if cfg.get("method"):
        level = f"{level} (AMP)"
    bits = []
    if a.get("steps"):
        bits.append(f"{a['steps'] / 1e6:g}M steps")
    if a.get("time_budget_min"):
        bits.append(f"{a['time_budget_min']:g} min")
    for key, label in (("steps_per_env", "T"), ("lr", "lr"), ("kl_target", "kl"), ("epochs", "ep")):
        if a.get(key) is not None:
            bits.append(f"{label} {_fmt_num(a[key])}")
    for key, label in (("anchor_coef", "anchor"), ("horizon0", "horizon0"), ("style_w", "style_w")):
        if a.get(key):
            bits.append(f"{label} {_fmt_num(a[key])}")
    bits += [flag for flag in ("freeze_norm", "push_curriculum", "quiet_posture", "no_randomization") if a.get(flag)]
    return level, " · ".join(bits)


def collect() -> list[dict]:
    rows = []
    if not RESULTS.is_dir():
        return rows
    for d in RESULTS.iterdir():
        cfg_file = d / "config.json"
        if d.name in SKIP or not cfg_file.is_file():
            continue
        cfg = _json(cfg_file)
        a = cfg.get("args", {})
        meta = _json(d / META)
        done = _json(d / "done.json")
        start = float(meta.get("started") or cfg_file.stat().st_mtime)
        written = [p.stat().st_mtime for pat in TRAINING_FILES for p in d.glob(pat)]
        end = max([cfg_file.stat().st_mtime, *written])
        steps, rate = _log_csv(d / "log.csv")
        if steps is None:
            steps = done.get("steps") or _ckpt_steps(d)
        if rate is None and done.get("steps") and done.get("wall_min"):
            rate = done["steps"] / (done["wall_min"] * 60)
        events = sorted(d.glob("events.out.tfevents.*"))
        tb_host = events[-1].name.split(".")[4] if events and len(events[-1].name.split(".")) > 5 else None
        crash, log_gpu = _side_logs(d)
        ended = meta.get("ended")
        if ended == "finished" and done.get("stop_reason"):
            ended = f"finished: {done['stop_reason']}"
        ended = (
            ended
            or (f"finished: {done.get('stop_reason', 'done')}" if done else None)
            or crash
            or "still running or killed"
        )
        host = meta.get("host") or tb_host
        level, args_text = _config(cfg)
        init = a.get("init")
        rows.append(
            dict(
                run=d.name,
                start=start,
                wall=max(0.0, end - start),
                ended=ended,
                trainer="train_amp.py" if cfg.get("method") else "train.py",
                steps=steps,
                rate=rate,
                bench=_bench_for(host, start),
                config=level,
                config_args=args_text,
                envs=cfg.get("env", {}).get("num_envs") or a.get("num_envs"),
                warm=[f"{init}{' (actor only)' if a.get('init_actor_only') else ''}"] if init else [],
                commit=meta.get("commit"),
                host=host,
                host_known=bool(meta.get("host")),
                gpu=meta.get("gpu") or log_gpu,
                device=meta.get("device"),
                launcher=meta.get("launcher"),
            )
        )
    rows.sort(key=lambda r: r["start"], reverse=True)
    return rows


# ---------------------------------------------------------------- render


def _dur(s: float) -> str:
    h, m = divmod(int(s) // 60, 60)
    return f"{h} h {m:02d} m" if h else f"{m} m"


def _num(n: float | None, digits: int = 0) -> str:
    return "-" if n is None else f"{n:,.{digits}f}"


def render(rows: list[dict]) -> str:
    e = html.escape
    body = []
    for r in rows:
        b = r["bench"]
        if b:
            notes = [f"{b['result']['env_steps_per_s']} env steps/s", e(b["when"][:10])]
            if datetime.datetime.fromisoformat(b["when"]).timestamp() > r["start"]:
                notes.append("taken after the run")
            if not r["host"]:
                notes.append("machine unknown")
            bench = f"{b['result']['step_time_ms']} ms<small>{' · '.join(notes)}</small>"
        else:
            bench = "-<small>no benchmark on this machine</small>"
        ended = e(r["ended"])
        cls = "bad" if re.search(r"crash|died|killed|HALT|error|exception", r["ended"], re.I) else ""
        body.append(
            "<tr>"
            f"<td><b>{e(r['run'])}</b><small>{e(r['trainer'])}</small></td>"
            f"<td>{datetime.datetime.fromtimestamp(r['start']).strftime('%Y-%m-%d %H:%M')}</td>"
            f'<td class="n">{_dur(r["wall"])}</td>'
            f'<td class="{cls}">{ended}</td>'
            f'<td class="n">{_num(r["steps"])}<small>env steps</small></td>'
            f'<td class="n"><b>{_num(r["rate"])}</b><small>env steps/s</small></td>'
            f'<td class="n">{bench}</td>'
            f"<td>{e(r['config'] or '-')}<small>{e(r['config_args'])}</small></td>"
            f'<td class="n">{e(str(r["envs"] or "-"))}</td>'
            f"<td>{e(', '.join(r['warm']) or 'cold')}</td>"
            f'<td class="mono">{e(r["commit"] or "-")}</td>'
            f"<td>{e(r['host'] or '-')}<small>{e(r['gpu'] or '')}{' · ' + e(r['device']) if r['device'] else ''}"
            f"</small></td>"
            "</tr>"
        )
    latest = rows[0] if rows else None
    prev = next((r for r in rows[1:] if r["rate"]), None) if rows else None
    delta = ""
    if latest and latest["rate"] and prev:
        pct = 100 * (latest["rate"] / prev["rate"] - 1)
        delta = f'<span class="{"up" if pct >= 0 else "down"}">{pct:+.0f}% vs {e(prev["run"])}</span>'
    summary = (
        f'<div class="sum"><div><span>Latest run</span><b>{e(latest["run"])}</b></div>'
        f"<div><span>Speed</span><b>{_num(latest['rate'])} steps/s</b>{delta}</div>"
        f"<div><span>Wall-clock</span><b>{_dur(latest['wall'])}</b></div>"
        f"<div><span>Runs listed</span><b>{len(rows)}</b></div></div>"
        if latest
        else "<p>No training runs under sim/runs/ yet.</p>"
    )
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(TITLE)} training runs</title>
<style>
:root{{--bg:#f5f7f6;--card:#fff;--ink:#18211f;--muted:#5d6b67;--line:#d8e0dd;--accent:#0f6b5c;--bad:#b42318;--up:#1f7a43}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1514;--card:#161e1c;--ink:#e2eae7;--muted:#91a19c;--line:#27332f;
--accent:#5cc9b0;--bad:#ff8a7a;--up:#5fcf8a;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Segoe UI",system-ui,sans-serif;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0;color:var(--muted)}} .wrap{{max-width:1500px;margin:auto;display:grid;gap:16px}}
.sum{{display:flex;flex-wrap:wrap;gap:12px 40px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px}}
.sum span{{display:block;color:var(--muted);font-size:12px}} .sum b{{font-size:20px}} .sum .up,.sum .down{{display:block;font-size:12px}}
.up{{color:var(--up)}} .down{{color:var(--bad)}}
.t{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);position:sticky;top:0;background:var(--card)}}
tr:last-child td{{border-bottom:0}} td.n{{text-align:right}} td small{{display:block;color:var(--muted);font-size:11px}}
td.bad{{color:var(--bad)}} .mono{{font-family:Consolas,monospace}}
</style></head><body><div class="wrap">
<div><h1>{e(TITLE)} training runs</h1><p>Every real training run under sim/runs/, newest first. Rebuilt {now} by
benchmark/runs.py. Speed = env steps/s over this session's PPO iterations (train.py's own timing); Benchmark = the
newest benchmark.ps1 result on the same machine before the run (ms per batched step of all 4096 envs).</p></div>
{summary}
<div class="t"><table><thead><tr><th>Run</th><th>Started</th><th>Wall-clock</th><th>Ended</th><th>Steps</th>
<th>Speed</th><th>Benchmark</th><th>Config</th><th>Envs</th><th>Warm start</th><th>Commit</th><th>Machine</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div></div></body></html>
"""


def build() -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(render(collect()), encoding="utf-8")
    os.replace(tmp, OUT)
    return OUT


def record(run_id: str, ended: str, launcher: str | None, started: float | None = None) -> None:
    """Write sim/runs/<run>/run_meta.json: this machine, the commit and how the run ended."""
    sys.path.insert(0, str(HERE))
    import core

    m = core.machine()
    d = RESULTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    meta = dict(
        host=m["hostname"],
        gpu=m["gpu"],
        cpu=m["cpu"],
        device="CPU" if os.environ.get("CUDA_VISIBLE_DEVICES") == "-1" else None,
        commit=core.git_commit(),
        ended=ended,
        launcher=launcher,
        started=started,
        recorded=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    (d / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Rebuild sim/runs/runs.html (the training runs grid).")
    p.add_argument("--record", metavar="RUN_ID", help="note this machine and how the run ended first")
    p.add_argument("--ended", default="exited", help="how the run ended, in words")
    p.add_argument("--launcher", help="the script that ran it")
    p.add_argument("--started", type=float, help="process start, epoch seconds (default: config.json's time)")
    a = p.parse_args()
    if a.record:
        record(a.record, a.ended, a.launcher, a.started)
    print(f"Training runs grid: {build()}")


if __name__ == "__main__":
    main()
