"""Extended (8 h) training report, 2026-11-08 night (UU_AGENT section 4): one self-contained HTML page that explains in
plain language, with charts, what each policy ("agent") learned during the unattended queue run.

    uv run python tools/extended_report.py --queue-dir runs/queue/20261108_2206 [--notes notes.html]
        [--out ../DOCS/20261108/extended_training_report_night.html]

Inputs: the queue's queue_state.json / queue_log.md, runs/<run>/log.csv + eval.json, runs/production/production_manifest.json.
Before/after lineages: dribble = l2a_cycles c1-c3 (best earlier approach) vs tonight's l2a_push runs; scramble = the
2026-11-06 queue attempt vs tonight's runs. Charts reuse tools/night_report.py (inline SVG, hover crosshair, table view).
--notes: an HTML fragment with the written verdict, inserted under the summary tiles.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import time

from night_report import RUNS, TEMPLATE, line_chart, lineage, tile

ROOT = pathlib.Path(__file__).resolve().parents[1]

BEFORE_DRIBBLE = ("Before tonight: l2a_cycles (3 runs)", ["l2a_cycles_c1", "l2a_cycles_c2", "l2a_cycles_c3"])
BEFORE_SCRAMBLE = ("Before: 2026-11-06 queue", ["l3b_scramble_q1"])


def ev(run: str) -> dict:
    p = RUNS / run / "eval.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def gantt(attempts: list[dict], t0: float, hours: float) -> str:
    """One horizontal bar per stage attempt on an 8 h axis (magnitude = minutes; color = which agent)."""
    W, L, R, rowh = 760, 170, 20, 30
    H = 34 + rowh * len(attempts)
    span = hours * 60
    X = lambda m: L + (W - L - R) * m / span
    g = []
    for h in range(int(hours) + 1):
        x = X(h * 60)
        g.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="8" y2="{H - 22}" class="grid"/>'
                 f'<text x="{x:.1f}" y="{H - 6}" class="tick" text-anchor="middle">{time.strftime("%H:%M", time.localtime(t0 + h * 3600))}</text>')
    for i, a in enumerate(attempts):
        y = 12 + i * rowh
        var = "--s1" if a["family"] == "dribble" else "--s3"
        x0, x1 = X(a["start_min"]), X(min(span, a["start_min"] + a["minutes"]))
        ok = a.get("passed")
        g.append(f'<text x="{L - 8}" y="{y + 15}" class="dlabel" text-anchor="end">{html.escape(a["label"])}</text>'
                 f'<rect x="{x0:.1f}" y="{y + 3}" width="{max(2, x1 - x0 - 2):.1f}" height="18" rx="4" fill="var({var})">'
                 f'<title>{html.escape(a["label"])}: {a["minutes"]:.0f} min, gate {"PASSED" if ok else "not passed"}</title></rect>'
                 f'<text x="{x1 + 4:.1f}" y="{y + 16}" class="tick">{a["minutes"]:.0f} min · {"✓ gate" if ok else "✕ gate"}</text>')
    return (f'<figure class="chart"><figcaption><b>What ran when</b><span>Each bar is one training stage of the queue; '
            f'blue = dribble, green = scramble. Most urgent agent first.</span></figcaption>'
            f'<div class="legend"><span class="lg"><i style="background:var(--s1)"></i>Dribble</span>'
            f'<span class="lg"><i style="background:var(--s3)"></i>Scramble</span></div>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Queue timeline">{"".join(g)}</svg></figure>')


def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def delta_row(name: str, before: float | None, after: float | None, unit: str, better_up: bool = True) -> str:
    def f(v):
        if v is None:
            return "—"
        return pct(v) if unit == "%" else f"{v:.2f}{(' ' + unit) if unit else ''}"
    if before is None or after is None:
        d = "—"
    else:
        diff = after - before
        good = (diff > 0) == better_up and abs(diff) > 1e-9
        arrow = "▲" if diff > 0 else "▼" if diff < 0 else "="
        dv = f"{diff * 100:+.1f} pts" if unit == "%" else f"{diff:+.2f}"
        d = f'<span class="{"dgood" if good else "dbad" if abs(diff) > 1e-9 else ""}">{arrow} {dv}</span>'
    return f"<tr><td>{html.escape(name)}</td><td>{f(before)}</td><td>{f(after)}</td><td>{d}</td></tr>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue-dir", required=True)
    ap.add_argument("--notes", default=None)
    ap.add_argument("--out", default=str(ROOT.parent / "DOCS" / "20261108" / "extended_training_report_night.html"))
    args = ap.parse_args()
    qdir = pathlib.Path(args.queue_dir)
    if not qdir.is_absolute():
        qdir = ROOT / qdir
    state = json.loads((qdir / "queue_state.json").read_text(encoding="utf-8"))
    t0 = time.mktime(time.strptime(state["started"], "%Y-%m-%d %H:%M:%S"))
    hours = float(state.get("hours", 8))

    # ---- attempts in run order (from the log: "stage X attempt N: M min")
    attempts, clock = [], 0.0
    log = (qdir / "queue_log.md").read_text(encoding="utf-8")
    starts = {}
    for m in re.finditer(r"\[(\d\d):(\d\d):(\d\d)\] stage (\S+) attempt (\d+): (\d+) min", log):
        hh, mm, ss, lv, n = int(m[1]), int(m[2]), int(m[3]), m[4], int(m[5])
        t = time.mktime(time.strptime(state["started"][:10] + f" {hh:02d}:{mm:02d}:{ss:02d}", "%Y-%m-%d %H:%M:%S"))
        if t < t0 - 60:
            t += 86400                                     # past midnight
        starts[(lv, n)] = (t - t0) / 60
    for lv, st in state["stages"].items():
        for n, a in enumerate(st["attempts"], 1):
            attempts.append({"level": lv, "n": n, "run": a["run"], "family": st.get("family") or "", "passed": a.get("passed"),
                             "minutes": a.get("minutes", 0), "start_min": starts.get((lv, n), clock), "eval": a.get("eval") or {},
                             "label": f'{"Dribble" if (st.get("family") == "dribble") else "Scramble"} #{n} ({lv})'})
    attempts.sort(key=lambda a: a["start_min"])
    drib_runs = [a["run"] for a in attempts if a["family"] == "dribble"]
    scr_runs = [a["run"] for a in attempts if a["family"] == "scramble"]

    drib = [(BEFORE_DRIBBLE[0], "--s2", lineage(BEFORE_DRIBBLE[1])), ("Tonight: l2a_push (push scored at release)", "--s1", lineage(drib_runs))]
    drib = [d for d in drib if d[2]]
    scr = [(BEFORE_SCRAMBLE[0], "--s2", lineage(BEFORE_SCRAMBLE[1])), ("Tonight: from walking + reach reward", "--s3", lineage(scr_runs))]
    scr = [s for s in scr if s[2]]
    tonight_steps = sum((lineage([r])[-1]["steps"] if lineage([r]) else 0) for r in drib_runs + scr_runs)

    # ---- real-gate evaluations, before vs best of tonight
    ev_before_d, ev_before_s = ev("l2a_cycles_c3"), ev("l3b_scramble_q1")
    evs_d = [(r, ev(r)) for r in drib_runs if ev(r)]
    evs_s = [(r, ev(r)) for r in scr_runs if ev(r)]
    best_d = max(evs_d, key=lambda x: (x[1].get("success_rate", 0), x[1].get("metrics", {}).get("m/bounces", 0)), default=(None, {}))
    best_s = max(evs_s, key=lambda x: (x[1].get("success_rate", 0), x[1].get("metrics", {}).get("m/regained", 0)), default=(None, {}))
    md_b, md_a = ev_before_d.get("metrics", {}), best_d[1].get("metrics", {})
    ms_b, ms_a = ev_before_s.get("metrics", {}), best_s[1].get("metrics", {})
    gate_d = "".join([
        delta_row("Gate success (50 clean bounces in a row)", ev_before_d.get("success_rate"), best_d[1].get("success_rate"), "%"),
        delta_row("Bounces per episode", md_b.get("m/bounces"), md_a.get("m/bounces"), ""),
        delta_row("Clean-bounce streak", md_b.get("m/streak"), md_a.get("m/streak"), ""),
        delta_row("Ball under control", md_b.get("m/in_control"), md_a.get("m/in_control"), "%"),
        delta_row("Palm touching the ball", md_b.get("m/palm_touch"), md_a.get("m/palm_touch"), "%"),
        delta_row("Bounce height (apex)", md_b.get("m/apex"), md_a.get("m/apex"), "m"),
        delta_row("Episode length before the ball is lost", ev_before_d.get("mean_episode_s"), best_d[1].get("mean_episode_s"), "s"),
        delta_row("Falls", ev_before_d.get("fall_rate"), best_d[1].get("fall_rate"), "%", better_up=False),
    ])
    gate_s = "".join([
        delta_row("Gate success (ball regained in time)", ev_before_s.get("success_rate"), best_s[1].get("success_rate"), "%"),
        delta_row("Regained the ball", ms_b.get("m/regained"), ms_a.get("m/regained"), "%"),
        delta_row("Distance to the ball at the end", ms_b.get("m/ball_dist"), ms_a.get("m/ball_dist"), "m", better_up=False),
        delta_row("Falls", ev_before_s.get("fall_rate"), best_s[1].get("fall_rate"), "%", better_up=False),
    ])

    # ---- tiles
    d_pass = any(a["passed"] for a in attempts if a["family"] == "dribble")
    s_pass = any(a["passed"] for a in attempts if a["family"] == "scramble")
    sd = best_d[1].get("success_rate"); ss = best_s[1].get("success_rate")
    tiles = "".join([
        tile("Balance", "Graduated", "good", "In production since 2026-11-07. Not retrained tonight."),
        tile("Locomotion", "Graduated (AMP)", "good", "AMP version promoted today; passes the Unreal 5 s rollout gate."),
        tile("Dribble", "Passed gate" if d_pass else ("Improving" if (md_a.get("m/bounces", 0) > md_b.get("m/bounces", 0)) else "Not learned yet"),
             "good" if d_pass else ("warn" if md_a.get("m/bounces", 0) > md_b.get("m/bounces", 0) else "bad"),
             f"Best gate success {pct(sd)} (needs 85%). {md_a.get('m/bounces', 0):.2f} bounces per test episode vs {md_b.get('m/bounces', 0):.2f} before."),
        tile("Scramble", "Passed gate" if s_pass else ("Improving" if ms_a.get("m/regained", 0) > ms_b.get("m/regained", 0) else "Not learned yet"),
             "good" if s_pass else ("warn" if ms_a.get("m/regained", 0) > ms_b.get("m/regained", 0) else "bad"),
             f"Best gate success {pct(ss)} (needs 80%). Ball regained in {pct(ms_a.get('m/regained'))} of test episodes."),
        tile("Shot", "Not scheduled", "idle", "Needs a working dribble first (the shot starts from a dribble)."),
    ])

    sec_d = "".join([
        line_chart("Gate-style success inside training: clean push cycles", "Share of push → bounce → peak cycles that were clean (palm touch, right height, near the spot).",
                   drib, "m/cycle_ok"),
        line_chart("Palm touches the ball", "Share of moments the dribbling palm is on the ball. A rhythm needs a touch every bounce.", drib, "m/palm_touch", "%"),
        line_chart("Ball under control", "Share of time the ball counts as controlled (target above 80%).", drib, "m/in_control", "%",
                   target=(0.8, "target 80%"), y_max=1.0),
        line_chart("Bounce height (apex)", "How high the ball comes back. Target 0.8–1.15 m.", drib, "m/apex", "m", target=(0.8, "target ≥ 0.8 m")),
        line_chart("Push reward (new tonight)", "Reward paid the moment the palm releases the ball, for a push that will bounce to the right height and spot.",
                   drib[-1:], "m/push_reward"),
        line_chart("Reward per episode", "Total reward collected (the reward changed tonight, so compare shapes, not levels).", drib, "ep_return"),
        line_chart("Value loss (critic error)", "How wrong the value predictions are. Spikes = the task got harder (more cycles per episode).", drib, "loss/value"),
        line_chart("Exploration (action noise)", "When it shrinks the policy stops trying new things.", drib, "ppo/std"),
    ])
    sec_s = "".join([
        line_chart("Ball regained", "Share of episodes in which the athlete got the loose ball back under control.", scr, "m/regained", "%"),
        line_chart("Palm reach (new tonight)", "How close the nearest palm gets to the ball once the athlete is within 1.2 m.", scr[-1:], "m/reach"),
        line_chart("Distance to the ball", "Horizontal distance from pelvis to ball (lower is better).", scr, "m/ball_dist", "m"),
        line_chart("Reward per episode", "Total reward collected (the reward changed tonight).", scr, "ep_return"),
        line_chart("Value loss (critic error)", "Critic prediction error.", scr, "loss/value"),
        line_chart("Episode length", "Seconds per episode (ends when the ball is regained and settled, or after the 3 s countdown).", scr, "ep_len_s", "s"),
    ])
    gate_rows = "".join(
        f"<tr><td>{html.escape(a['label'])}</td><td>{html.escape(a['run'])}</td><td>{a['eval'].get('level', '—')}</td><td>{a['minutes']:.0f} min</td>"
        f"<td>{pct(a['eval'].get('success_rate'))}</td><td>{pct(a['eval'].get('fall_rate'))}</td>"
        f"<td>{a['eval'].get('nan_grads', '—')}</td><td>{'<b class=good>✓ pass</b>' if a['passed'] else '✕ no'}</td></tr>" for a in attempts)
    man_p = RUNS / "production" / "production_manifest.json"
    prod = ""
    if man_p.exists():
        man = json.loads(man_p.read_text(encoding="utf-8"))
        prod = "".join(f"<tr><td>{html.escape(f)}</td><td>{html.escape(str(m.get('level')))}</td><td>{html.escape(str(m.get('checkpoint')))}</td>"
                       f"<td>{(m.get('train_steps') or 0) / 1e6:.0f}M</td><td>{m.get('nan_grads', '—')}</td></tr>" for f, m in man.get("families", {}).items())
    notes = pathlib.Path(args.notes).read_text(encoding="utf-8") if args.notes else ""

    head = TEMPLATE.split("<main>")[0].replace("{{", "{").replace("}}", "}")
    head = head.replace("<title>Night Training Report</title>", "<title>Extended Training Report</title>")
    head = head.replace("</style>", ".dgood{color:var(--goodtxt);font-weight:600}.dbad{color:var(--bad);font-weight:600}h3{font-size:16px;margin:22px 0 4px}</style>")
    script = TEMPLATE.split("<script>")[1].replace("{{", "{").replace("}}", "}")
    body = f"""<h1>Extended training report — night of 8–9 November 2026</h1>
<div class="meta">8-hour unattended queue {html.escape(state['started'])} → {time.strftime('%H:%M', time.localtime(t0 + hours * 3600))} ·
about {tonight_steps / 1e6:.0f} M simulated steps tonight · generated {time.strftime('%Y-%m-%d %H:%M')}</div>
<p class="lead">The streetball athlete is controlled by five skill policies ("agents"). Two were already finished. Tonight's GPU time went to the
two most urgent unfinished ones: <b>dribble</b> (it blocks every later tier) and <b>scramble</b> (chasing a loose ball, which today runs a placeholder
policy in Unreal). Each was trained, then tested on its real 200-episode gate.</p>
<div class="tiles">{tiles}</div>
{notes}
{gantt(attempts, t0, hours)}

<h2>1. Dribble</h2>
<p>What changed tonight: the policy now gets credit <i>the moment the palm lets go of the ball</i>, from where the ball is going to bounce and how
high, instead of only when the ball comes back up ~0.5 s later. Orange = the best earlier method (l2a_cycles), blue = tonight. The horizontal axis is
training experience in millions of simulated steps; tonight's line continues from the earlier one's weights.</p>
<div class="grid2">{sec_d}</div>
<h3>Real gate, before vs after (200 test episodes on <code>l2a_dribble_r</code>)</h3>
<div class="scroll"><table><tr><th>Measure</th><th>Before (l2a_cycles_c3)</th><th>Tonight (best: {html.escape(str(best_d[0]))})</th><th>Change</th></tr>{gate_d}</table></div>

<h2>2. Scramble</h2>
<p>What changed tonight: training starts from the graduated walking policy (not from the broken dribble chain of 6 November), and a new reward
pulls the nearest palm toward the ball once the athlete is close, because getting the ball back needs a palm touch.</p>
<div class="grid2">{sec_s}</div>
<h3>Real gate, before vs after (200 test episodes on <code>l3b_scramble</code>)</h3>
<div class="scroll"><table><tr><th>Measure</th><th>Before (2026-11-06)</th><th>Tonight (best: {html.escape(str(best_s[0]))})</th><th>Change</th></tr>{gate_s}</table></div>

<h2>3. Every gate result tonight</h2>
<p>A policy is exported to the game only if it reaches its target in 100 straight test episodes with zero NaN gradients.</p>
<div class="scroll"><table><tr><th>Stage</th><th>Run</th><th>Gate level</th><th>Time</th><th>Success</th><th>Falls</th><th>NaN grads</th><th>Gate</th></tr>{gate_rows}</table></div>

<h2>4. Production weights</h2>
<div class="scroll"><table><tr><th>Family</th><th>Trained on</th><th>Checkpoint</th><th>Steps</th><th>NaN grads</th></tr>{prod}</table></div>
<p class="meta">Data: sim/runs/&lt;run&gt;/log.csv and eval.json; queue {html.escape(qdir.name)}; TensorBoard event files in each run folder.
Charts are smoothed (9-iteration mean); the first moments of each resumed run are hidden while the running averages refill.</p>
</main><div class="stamp">Build {time.strftime('%y%m%d')}</div>
"""
    page = head + "<main>" + body + "<script>" + script
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
