"""Serve a simple, automatically refreshing dashboard for an existing training run.

    python tools/live_dashboard.py runs/l1_teacher_gate_8h

The server reads the trainer's files; it does not start, stop, or modify training.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import pathlib
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.run_report import svg_panel  # noqa: E402


def read_snapshot(run: pathlib.Path) -> tuple[list[dict[str, float]], dict, dict | None, float]:
    cfg = json.loads((run / "config.json").read_text(encoding="utf-8"))
    log = run / "log.csv"
    with log.open("rb") as f:
        contents = f.read()
        updated = log.stat().st_mtime
    if b"\n" not in contents:
        raise ValueError("Training log has no complete CSV rows yet")
    complete = contents.rsplit(b"\n", 1)[0].decode("utf-8")
    reader = csv.DictReader(io.StringIO(complete, newline=""))
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Training log contains an incomplete CSV row")
        values = {key: float(value) for key, value in row.items() if value != ""}
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("Training log contains a non-finite metric")
        rows.append(values)
    if not rows:
        raise ValueError("Training log has no completed iterations yet")
    done_path = run / "done.json"
    done = json.loads(done_path.read_text(encoding="utf-8")) if done_path.exists() else None
    return rows, cfg, done, updated


def render_dashboard(run: pathlib.Path, now: float | None = None) -> str:
    rows, cfg, done, updated = read_snapshot(run)
    now = time.time() if now is None else now
    latest = rows[-1]
    required = ("steps", "fps", "ep_len_s", "ep_return", "push_scale", "ppo/nan_grads_total")
    for key in required:
        if key not in latest:
            raise ValueError(f"Training log is missing required metric {key}")
    age = max(0, now - updated)
    if done is not None:
        status = "Finished"
        status_detail = html.escape(str(done["stop_reason"]))
        status_class = "finished"
    elif age > 180:
        status = "Updates delayed"
        status_detail = f"No new training log data for {age / 60:.1f} minutes; the run may be paused or stopped."
        status_class = "warning"
    else:
        status = "Receiving updates"
        status_detail = "The training log is being updated. This does not establish that the policy passes evaluation."
        status_class = "active"

    total_s = 0.0
    previous_steps = 0.0
    for row in rows:
        delta = row["steps"] - previous_steps
        if delta <= 0 or row["fps"] <= 0:
            raise ValueError("Training log steps and throughput must be positive and increasing")
        total_s += delta / row["fps"]
        previous_steps = row["steps"]
    budget = float(cfg["args"]["time_budget_min"])
    elapsed_min = total_s / 60
    budget_text = f"{elapsed_min:.0f} / {budget:.0f} min" if budget > 0 else f"{elapsed_min:.0f} min"
    horizon_s = float(cfg["max_steps"]) * float(cfg["control_dt"])
    charts = "".join(
        svg_panel(rows, column, title, unit, index)
        for index, (column, title, unit) in enumerate(
            [
                ("ep_len_s", "Episode length", "s"),
                ("ep_return", "Episode reward", ""),
                ("fps", "Training speed", "steps/s"),
                ("m/waypoints", "Waypoints during episodes", ""),
            ]
        )
        if column in latest
    )
    waypoints = ""
    if cfg["level"] == "l1_traverse" and "m/waypoints" in latest:
        waypoints = f"""
        <div class="tile"><span class="label">Waypoints</span><strong>{latest["m/waypoints"]:.1f}</strong>
          <span class="hint">Average waypoint count across active training states, not final per-episode success.</span></div>"""
    last_updated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(updated))
    level = html.escape(str(cfg["level"]))
    name = html.escape(run.name)
    progress = min(100.0, 100.0 * elapsed_min / budget) if budget > 0 else 0.0
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="600"><title>Live training — {name}</title>
<style>
:root {{ color-scheme: light; --bg:#f4f7fa; --panel:#fff; --text:#192739; --muted:#607285; --border:#d9e3eb; --blue:#2875c7; --green:#147d5c; --amber:#a76309; }}
@media (prefers-color-scheme:dark) {{ :root {{ color-scheme:dark; --bg:#111a23; --panel:#1b2935; --text:#e9f1f8; --muted:#a9bac8; --border:#364858; --blue:#6ab0ff; --green:#77d9ae; --amber:#ffc574; }} }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,sans-serif }}
main {{ max-width:1100px; padding:24px 18px 40px; margin:auto }} h1 {{ font-size:clamp(25px,4vw,36px); line-height:1.15; margin:4px 0 8px }}
h2 {{ font-size:19px; margin:0 0 12px }} p {{ margin:0 }} .eyebrow {{ color:var(--blue); font-size:12px; font-weight:750; letter-spacing:.12em; text-transform:uppercase }}
.meta,.hint {{ color:var(--muted); font-size:13px }} .status {{ margin:20px 0 14px; padding:14px 16px; border:1px solid var(--border); border-left:4px solid var(--green); border-radius:10px; background:var(--panel) }}
.status.warning {{ border-left-color:var(--amber) }} .status.finished {{ border-left-color:var(--blue) }} .status strong {{ display:block; font-size:16px }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin:16px 0 }}
.tile,.card {{ border:1px solid var(--border); border-radius:10px; background:var(--panel); padding:15px }}
.tile strong {{ display:block; font-size:25px; letter-spacing:-.03em }} .label {{ color:var(--muted); font-size:12px; font-weight:650 }}
.hint {{ display:block }} .track {{ height:8px; background:var(--border); border-radius:8px; overflow:hidden; margin:8px 0 }}
.track span {{ display:block; height:100%; background:var(--blue) }} .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr)); gap:12px }}
figure.panel {{ margin:0; min-width:0 }} figcaption {{ font-size:13px; font-weight:650 }} .last {{ float:right; color:var(--muted) }}
svg {{ display:block; width:100%; height:auto }} .grid {{ stroke:var(--border); stroke-width:1 }} .tick {{ fill:var(--muted); font-size:10px }}
.series {{ fill:none; stroke:var(--blue); stroke-width:2; stroke-linejoin:round }} .card p {{ color:var(--muted); font-size:13px }}
.explain {{ margin-top:16px }} .explain p+p {{ margin-top:8px }} .foot {{ margin-top:15px; color:var(--muted); font-size:12px }}
</style></head><body><main>
<header><div class="eyebrow">PoBasketball · live training</div><h1>{name}</h1>
<p class="meta">Level {level} · last training data {last_updated} · page refreshes every 10 minutes</p></header>
<section class="status {status_class}"><strong>{status}</strong><span class="hint">{status_detail}</span></section>
<section class="tiles" aria-label="Training summary">
<div class="tile"><span class="label">Training steps</span><strong>{latest["steps"] / 1e6:.1f}M</strong><span class="hint">Simulated actions, not real-world seconds.</span></div>
<div class="tile"><span class="label">Time budget (estimated)</span><strong>{budget_text}</strong>
<div class="track" role="progressbar" aria-label="Estimated time budget used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{progress:.0f}"><span style="width:{progress:.1f}%"></span></div>
<span class="hint">Estimated from logged iteration speeds; excludes some overhead.</span></div>
<div class="tile"><span class="label">Episode length</span><strong>{latest["ep_len_s"]:.1f} s</strong><span class="hint">Rolling training average; episode limit {horizon_s:.0f} s. Shorter can also mean success.</span></div>
<div class="tile"><span class="label">Training speed</span><strong>{latest["fps"] / 1000:.1f}k/s</strong><span class="hint">Latest iteration; speed changes with workload.</span></div>
<div class="tile"><span class="label">Episode reward</span><strong>{latest["ep_return"]:.0f}</strong><span class="hint">Rolling training average; useful for trends, not a pass rate.</span></div>
<div class="tile"><span class="label">Push difficulty</span><strong>{latest["push_scale"] * 100:.0f}%</strong><span class="hint">Current share of the configured maximum push force.</span></div>
<div class="tile"><span class="label">Numerical errors</span><strong>{int(latest["ppo/nan_grads_total"])}</strong><span class="hint">Cumulative non-finite gradient batches; zero is desired.</span></div>
{waypoints}</section>
<section class="card"><h2>How behavior is changing</h2><p>Each chart plots the training metric against millions of simulated steps.</p>
<div class="cards">{charts}</div></section>
<section class="card explain"><h2>How to read this</h2>
<p><strong>Episode length:</strong> measures how long training episodes last. A longer episode can mean better survival, but this level also ends episodes when the goal is reached, so length alone is not a success score.</p>
<p><strong>Reward:</strong> combines several training objectives. Improvements can be useful, but a high reward does not guarantee that the player is completing the task.</p>
<p><strong>Waypoints:</strong> for L1, the training chart is a time-averaged count across environments, not the percentage of completed episodes or a measure of the final waypoint total.</p>
<p><strong>Evaluation:</strong> not assessed by this dashboard. For L1, the goal is 10 waypoints in 90 seconds; deterministic evaluation and its pass gate are separate from training metrics.</p>
</section><p class="foot">Read-only monitor · no policy is exported or promoted by this page. Stop the dashboard server separately when finished.</p>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=pathlib.Path, help="training run directory containing config.json and log.csv")
    parser.add_argument("--port", type=int, default=8765, help="localhost port (default: 8765)")
    args = parser.parse_args()
    run = args.run.resolve(strict=True)
    render_dashboard(run)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            try:
                body = render_dashboard(run).encode("utf-8")
            except (OSError, ValueError, KeyError, csv.Error) as exc:
                self.send_error(503, f"Could not read training data: {exc}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Dashboard for {run}: http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
