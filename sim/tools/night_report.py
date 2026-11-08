"""Night report for 2026-11-08 (UU_AGENT section 4): one self-contained HTML page that explains, in plain
language and with charts, what each policy family learned during the 8-hour unattended window.

    uv run python tools/night_report.py --out ../DOCS/20261108/night_training_report.html

Inputs (all optional; missing runs are skipped): runs/<run>/log.csv, runs/<run>/eval.json, done.json,
runs/queue/20261108_*/queue_state.json. Charts are inline SVG with a hover crosshair/tooltip and a table view.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"

# Each "attempt" is a lineage of runs; later runs continue the earlier one (steps are offset to line up).
DRIBBLE = [
    ("r2: original reward", ["l2a_dribble_r_r2q1"],
     "Reward as of last night, started from the walking policy."),
    ("r3: + reach & touch reward", ["l2a_reachcheck", "l2a_dribble_r_r3q1"],
     "Adds a reward for bringing the palm to the ball and a bonus for each touch."),
    ("r4/r5: + ball-in-hand starts", ["l2a_dribble_r_r4q1", "l2a_dribble_r_r5q1", "l2a_dribble_r_r5q2", "l2a_dribble_r_r5q3"],
     "Many training episodes start with the ball rising into the palm, so touches actually happen."),
]
AMP = [
    ("Hand-tuned: hand-written posture reward (production)", ["l1_v3_armcarry"], ""),
    ("AMP: style learned from motion capture", ["l1_amp_v2", "l1_amp_v3"], ""),
]
PALETTE = ["--s1", "--s2", "--s3", "--s4"]


def read_csv(run: str) -> list[dict]:
    p = RUNS / run / "log.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [{k: float(v) for k, v in r.items() if v not in ("", None)} for r in csv.DictReader(f)]


def lineage(runs: list[str]) -> list[dict]:
    rows, off = [], 0.0
    for r in runs:
        rs = read_csv(r)
        rs_plot = rs
        if off > 0 and rows:
            # continued run: all envs restart together, so the first finished episodes are the short ones and the
            # running averages read low until one full episode has elapsed (ep_len / 0.02 s / 24 steps per iteration)
            skip = int(rows[-1].get("ep_len_s", 3.0) / 0.02 / 24) + 10
            rs_plot = rs[skip:]
        for x in rs_plot:
            x = dict(x); x["steps"] = x["steps"] + off; rows.append(x)
        if rs:
            off += rs[-1]["steps"]
    return rows


def smooth(xs: list[float], ys: list[float], n: int = 160, win: int = 9):
    if not xs:
        return [], []
    sm = []
    for i in range(len(ys)):
        a = ys[max(0, i - win + 1): i + 1]
        sm.append(sum(a) / len(a))
    step = max(1, len(xs) // n)
    idx = list(range(0, len(xs), step))
    if idx[-1] != len(xs) - 1:
        idx.append(len(xs) - 1)
    return [xs[i] for i in idx], [sm[i] for i in idx]


def nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def fmt(v: float, unit: str = "") -> str:
    if unit == "%":
        return f"{v * 100:.1f}%" if v < 0.1 else f"{v * 100:.0f}%"
    a = abs(v)
    s = f"{v:.0f}" if a >= 100 else f"{v:.2f}" if a >= 1 else f"{v:.3f}"
    return s + (f" {unit}" if unit else "")


CHART_ID = [0]


def line_chart(title: str, sub: str, series: list[tuple[str, str, list[dict]]], key: str, unit: str = "",
               target: tuple[float, str] | None = None, scale: float = 1.0, y_max: float | None = None) -> str:
    """series: (label, css var, rows). One y-axis, x = million steps."""
    CHART_ID[0] += 1
    cid = f"c{CHART_ID[0]}"
    W, H, L, R, T, B = 560, 230, 46, 118, 14, 30
    data = []
    for label, var, rows in series:
        pts = [(r["steps"] / 1e6, r[key] * scale) for r in rows if key in r and math.isfinite(r[key])]
        if not pts:
            continue
        xs, ys = smooth([p[0] for p in pts], [p[1] for p in pts])
        data.append((label, var, xs, ys))
    if not data:
        return ""
    xmax = nice_max(max(d[2][-1] for d in data))
    ymin = min(0.0, min(min(d[3]) for d in data))
    ymax = y_max or nice_max(max(max(d[3]) for d in data + ([("", "", [0], [target[0]])] if target else [])) * 1.05)
    X = lambda x: L + (W - L - R) * x / xmax
    Y = lambda y: T + (H - T - B) * (1 - (y - ymin) / (ymax - ymin))
    g = []
    for i in range(5):
        yv = ymin + (ymax - ymin) * i / 4
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" class="grid"/>'
                 f'<text x="{L - 6}" y="{Y(yv) + 4:.1f}" class="tick" text-anchor="end">{fmt(yv, "%" if unit == "%" else "")}</text>')
    for i in range(5):
        xv = xmax * i / 4
        g.append(f'<text x="{X(xv):.1f}" y="{H - 10}" class="tick" text-anchor="middle">{xv:.0f}M</text>')
    g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(ymin):.1f}" y2="{Y(ymin):.1f}" class="axis"/>')
    if target:
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(target[0]):.1f}" y2="{Y(target[0]):.1f}" class="target"/>'
                 f'<text x="{L + 4}" y="{Y(target[0]) - 5:.1f}" class="tick">{html.escape(target[1])}</text>')
    labels = []
    for label, var, xs, ys in data:
        d = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
        g.append(f'<path d="{d}" fill="none" stroke="var({var})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        labels.append([Y(ys[-1]), label, var, X(xs[-1]), ys[-1]])
    labels.sort()
    for i in range(1, len(labels)):                      # de-collide end labels
        labels[i][0] = max(labels[i][0], labels[i - 1][0] + 13)
    over = labels[-1][0] - (H - B) if labels else 0
    if over > 0:                                        # keep labels inside the plot: shift the stack up
        for lab in labels:
            lab[0] -= over
    for y, label, var, x, v in labels:
        short = label.split(":")[0]
        g.append(f'<circle cx="{x:.1f}" cy="{Y(v):.1f}" r="4" fill="var({var})" stroke="var(--surface)" stroke-width="2"/>'
                 f'<text x="{W - R + 6}" y="{y + 4:.1f}" class="dlabel">{html.escape(short)} {fmt(v, unit)}</text>')
    payload = json.dumps({"xmax": xmax, "L": L, "R": R, "W": W, "unit": unit,
                          "series": [{"label": d[0], "var": d[1], "x": [round(v, 2) for v in d[2]], "y": [round(v, 5) for v in d[3]]} for d in data]})
    legend = "".join(f'<span class="lg"><i style="background:var({d[1]})"></i>{html.escape(d[0])}</span>' for d in data) if len(data) > 1 else ""
    rows = "".join(f"<tr><td>{html.escape(d[0])}</td><td>{d[2][-1]:.0f}M</td><td>{fmt(d[3][0], unit)}</td><td>{fmt(max(d[3]), unit)}</td><td>{fmt(d[3][-1], unit)}</td></tr>" for d in data)
    return f'''<figure class="chart" id="{cid}">
<figcaption><b>{html.escape(title)}</b><span>{html.escape(sub)}</span></figcaption>
<div class="legend">{legend}</div>
<div class="plot"><svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">{"".join(g)}
<line class="xh" y1="{T}" y2="{H - B}" x1="-10" x2="-10"/><rect x="{L}" y="{T}" width="{W - L - R}" height="{H - T - B}" fill="transparent" class="hit"/></svg>
<div class="tip" hidden></div></div>
<details><summary>Table view</summary><table><tr><th>Series</th><th>Steps</th><th>Start</th><th>Best</th><th>End</th></tr>{rows}</table></details>
<script type="application/json" class="data">{payload}</script></figure>'''


def ev(run: str) -> dict:
    p = RUNS / run / "eval.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def queue_states() -> list[dict]:
    out = []
    for d in sorted((RUNS / "queue").glob("20261108_*")):
        p = d / "queue_state.json"
        if p.exists():
            s = json.loads(p.read_text(encoding="utf-8")); s["dir"] = d.name; out.append(s)
    return out


def tile(name: str, status: str, kind: str, detail: str) -> str:
    icon = {"good": "✓", "warn": "!", "bad": "✕", "idle": "–"}[kind]
    return (f'<div class="tile"><div class="tname">{html.escape(name)}</div>'
            f'<div class="tstat {kind}"><span class="ic">{icon}</span>{html.escape(status)}</div>'
            f'<div class="tdet">{detail}</div></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / "DOCS" / "20261108" / "night_training_report.html"))
    args = ap.parse_args()

    drib = [(lab, PALETTE[i], lineage(runs)) for i, (lab, runs, _) in enumerate(DRIBBLE)]
    drib = [d for d in drib if d[2]]
    amp = [(lab, PALETTE[i], lineage(runs)) for i, (lab, runs, _) in enumerate(AMP)]
    amp = [a for a in amp if a[2]]
    total_steps = sum(d[2][-1]["steps"] for d in drib) + (amp[1][2][-1]["steps"] - 34e6 if len(amp) > 1 else 0)

    # gate results from this night's queues
    gate_rows, passed_any = [], []
    for qs in queue_states():
        for lv, st in qs["stages"].items():
            for a in st["attempts"]:
                e = a.get("eval") or {}
                gate_rows.append((qs["dir"], a["run"], lv, a.get("steps"), e.get("success_rate"), e.get("fall_rate"), a.get("passed")))
                if a.get("passed"):
                    passed_any.append((lv, a["run"]))
    amp_ev, base_ev = ev("l1_amp_v3"), ev("l1_v3_armcarry")

    best_touch = max((r.get("m/palm_touch", 0) for d in drib for r in d[2]), default=0)
    last = drib[-1][2][-1] if drib else {}
    dribble_passed = any(lv.startswith("l2") or lv.startswith("l3a") for lv, _ in passed_any)

    tiles = [
        tile("Balance", "Graduated", "good", "100% of 200 test episodes (from 2026-11-07). Not retrained tonight."),
        tile("Locomotion", "Graduated", "good", "97% of test episodes reach all 10 waypoints (2026-11-07). "
             + (f"AMP challenger: {amp_ev.get('success_rate', 0) * 100:.0f}%." if amp_ev else "AMP challenger trained tonight.")),
        tile("Dribble", "Graduated" if dribble_passed else "Not learned yet", "good" if dribble_passed else "bad",
             f"Latest: ball kept in control {last.get('m/in_control', 0) * 100:.0f}% of the time (target 80%); "
             f"palm touches the ball in {best_touch * 100:.1f}% of moments at best."),
        tile("Scramble", "Waiting on dribble", "idle", "Needs the hand-to-ball touch that dribble has not found."),
        tile("Shot", "Waiting on dribble", "idle", "Needs the athlete to hold the ball up to the shot trigger."),
    ]

    sec_drib = "".join([
        line_chart("Palm touches the ball", "Share of moments the dribbling palm is in contact. A real dribble needs a touch every bounce (~5%+).",
                   drib, "m/palm_touch", "%"),
        line_chart("Ball under control", "Share of time the ball counts as controlled. Target above 80%.", drib, "m/in_control", "%",
                   target=(0.8, "target 80%"), y_max=1.0),
        line_chart("Bounce height (apex)", "How high the ball comes back up. Target 0.8–1.15 m (waist high).", drib, "m/apex", "m",
                   target=(0.8, "target ≥ 0.8 m")),
        line_chart("Episode length", "Seconds before the ball is lost. 30 s = a full dribble session.", drib, "ep_len_s", "s"),
        line_chart("Reward per episode", "Total reward the policy collects. Rising reward with flat touches = it found easier points.",
                   drib, "ep_return"),
        line_chart("Value loss (critic error)", "How wrong the critic's predictions are. Spikes mean the task changed under it.",
                   drib, "loss/value"),
        line_chart("Exploration (action noise)", "Policy's random exploration. When it shrinks the policy stops trying new things.",
                   drib, "ppo/std"),
    ])
    sec_amp = "".join([
        line_chart("Reward per episode", "Higher = more of the course covered per episode.", amp, "ep_return"),
        line_chart("Walking speed", "Average speed (target range 1.2–3.0 m/s).", amp, "m/speed", "m/s"),
        line_chart("Arm carry (lower is more natural)", "How far the arms sit from a relaxed carry. AMP gets no hand-written arm penalty.",
                   amp, "m/arm_carry"),
        line_chart("Waypoints reached", "Average waypoints per episode (out of 10).", amp, "m/waypoints"),
    ])

    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"
    gate_html = "".join(f"<tr><td>{q}</td><td>{r}</td><td>{lv}</td><td>{(s or 0) / 1e6:.0f}M</td><td>{pct(sr)}</td><td>{pct(fr)}</td>"
                        f"<td>{'<b class=good>✓ pass</b>' if p else '✕ no'}</td></tr>" for q, r, lv, s, sr, fr, p in gate_rows)
    amp_tbl = ""
    if amp_ev or base_ev:
        def row(name, e):
            return (f"<tr><td>{name}</td><td>{pct(e.get('success_rate'))}</td><td>{pct(e.get('fall_rate'))}</td>"
                    f"<td>{'yes' if e.get('holds_100_straight') else 'no'}</td><td>{e.get('mean_episode_s', 0):.0f} s</td></tr>")
        amp_tbl = ("<table><tr><th>Locomotion policy</th><th>Success (200 ep)</th><th>Falls</th><th>Holds 100 straight</th><th>Mean episode</th></tr>"
                   + row("Hand-tuned (production)", base_ev) + (row("AMP", amp_ev) if amp_ev else "") + "</table>")

    attempts = "".join(f'<li><span class="sw" style="background:var({PALETTE[i]})"></span><b>{html.escape(lab)}</b> — {html.escape(desc)}</li>'
                       for i, (lab, _, desc) in enumerate(DRIBBLE))

    page = TEMPLATE.format(
        generated=time.strftime("%Y-%m-%d %H:%M"), tiles="".join(tiles), sec_drib=sec_drib, sec_amp=sec_amp,
        gate=gate_html or "<tr><td colspan=7>No evaluations recorded.</td></tr>", amp_tbl=amp_tbl, attempts=attempts,
        steps=f"{total_steps / 1e6:.0f} M")
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Night Training Report</title>
<style>
:root{{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--good:#0ca30c;--goodtxt:#006300;--warn:#fab219;--bad:#d03b3b}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--goodtxt:#0ca30c}}}}
:root[data-theme="dark"]{{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--goodtxt:#0ca30c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:19px;margin:40px 0 6px}}
p.lead,.meta{{color:var(--ink2)}}.meta{{font-size:13px}}p{{max-width:78ch}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:20px 0}}
.tile{{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px}}.tname{{font-weight:600}}
.tstat{{font-size:18px;font-weight:600;margin:4px 0}}.tstat .ic{{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;
margin-right:6px;font-size:12px;color:#fff;vertical-align:2px}}.good .ic{{background:var(--good)}}.bad .ic{{background:var(--bad)}}
.warn .ic{{background:var(--warn);color:#0b0b0b}}.idle .ic{{background:var(--muted)}}.tdet{{color:var(--ink2);font-size:13px}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:14px}}
.chart{{margin:0;background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px;min-width:0}}
figcaption b{{display:block}}figcaption span{{color:var(--ink2);font-size:13px}}.legend{{margin:6px 0;font-size:12px;color:var(--ink2)}}
.lg{{margin-right:12px;white-space:nowrap}}.lg i,.sw{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}}
.plot{{position:relative}}svg{{width:100%;height:auto;display:block}}.grid{{stroke:var(--grid);stroke-width:1}}.axis{{stroke:var(--axis)}}
.target{{stroke:var(--muted);stroke-dasharray:4 4}}.tick{{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}}
.dlabel{{fill:var(--ink2);font-size:11px}}.xh{{stroke:var(--muted);stroke-width:1}}
.tip{{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:6px 9px;
font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);white-space:nowrap;z-index:2}}.tip i{{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}}
details{{margin-top:6px;font-size:13px}}summary{{color:var(--ink2);cursor:pointer}}
table{{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums;margin:8px 0}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--grid)}}th{{color:var(--ink2);font-weight:600}}
.scroll{{overflow-x:auto}}b.good{{color:var(--goodtxt)}}ul.att{{padding-left:0;list-style:none}}ul.att li{{margin:4px 0}}
.callout{{background:var(--surface);border:1px solid var(--ring);border-left:4px solid var(--s1);border-radius:8px;padding:12px 16px;margin:14px 0}}
.stamp{{position:fixed;right:10px;bottom:8px;font-size:11px;color:var(--muted)}}
</style></head><body><main>
<h1>Overnight training report — 8 November 2026</h1>
<div class="meta">8-hour unattended window, 02:07 → 10:00 · about {steps} simulated steps · generated {generated}</div>
<p class="lead">Five skills ("policies") make up the streetball athlete. Two were already finished before tonight. The night was spent on
the most urgent unfinished one, <b>dribbling</b>, plus a side-by-side test of a new way to train walking (AMP).</p>
<div class="tiles">{tiles}</div>

<h2>1. Dribble: why it is still the blocker</h2>
<p>To dribble, the athlete must slap the ball down with the palm on every bounce. Three different training set-ups were tried tonight.
Each line below is one attempt; the horizontal axis is training experience (millions of simulated steps).</p>
<ul class="att">{attempts}</ul>
<div class="callout"><b>What the charts show.</b> Every attempt rises in reward, but the touch and control lines fall. The policy learns to
stand still and let the ball die, collecting the "stand nicely" points, because it never discovers the timing of a <i>second</i> touch after
the ball bounces. Giving it the ball in hand (r4/r5) makes the first touch happen, but not the rhythm. More training time on the same set-up
did not change this; it needs a different teaching method (see section 4).</div>
<div class="grid2">{sec_drib}</div>

<h2>2. Walking: hand-tuned reward vs AMP (learning style from motion capture)</h2>
<p>The production walking policy uses hand-written rules for posture. AMP instead learns what "human-like" looks like from motion-capture clips.
Both start from the same checkpoint with the same training budget. Full side-by-side page with filmstrips:
<a href="amp_vs_baseline.html">amp_vs_baseline.html</a>.</p>
{amp_tbl}
<div class="grid2">{sec_amp}</div>

<h2>3. Gate results (200 test episodes each)</h2>
<p>A policy is exported for the game only when it passes its target in 100 straight test episodes with no training errors.</p>
<div class="scroll"><table><tr><th>Queue</th><th>Run</th><th>Skill level</th><th>Steps</th><th>Success</th><th>Falls</th><th>Gate</th></tr>{gate}</table></div>

<h2>4. Recommended next step</h2>
<div class="callout"><b>Teach the dribble rhythm from an example, not from reward alone.</b> Three options, best first:
<ol><li><b>Scripted hand-ball reference</b>: a short procedurally generated dribble (hand follows a sine path synchronised with the ball) used as an
imitation target for the right arm only; the legs keep the walking policy's balance.</li>
<li><b>AMP with a dribble clip</b>: the AMP trainer from section 2 already works; it needs a motion-capture dribble clip (not in the current
data set).</li>
<li><b>Phase signal in the task inputs</b>: tell the policy when the next touch is due (appended input, zero-initialised, per the frozen-interface rule).</li></ol>
Scramble and shot stay parked until dribble passes.</div>
<p class="meta">Data: sim/runs/&lt;run&gt;/log.csv, eval.json; queue state in sim/runs/queue/20261108_*; log DOCS/20261108/log.md. Charts smoothed (9-iteration mean); the first episode-length of each resumed run is hidden (averages refill after a resume).</p>
</main><div class="stamp">Build 261108</div>
<script>
document.querySelectorAll('figure.chart').forEach(fig=>{{
 const d=JSON.parse(fig.querySelector('.data').textContent),svg=fig.querySelector('svg'),hit=fig.querySelector('.hit'),
 xh=fig.querySelector('.xh'),tip=fig.querySelector('.tip'),plot=fig.querySelector('.plot');
 const f=(v)=>d.unit==='%'?(v*100).toFixed(v<0.1?2:1)+'%':(Math.abs(v)>=100?v.toFixed(0):Math.abs(v)>=1?v.toFixed(2):v.toFixed(3))+(d.unit&&d.unit!=='%'?' '+d.unit:'');
 function show(e){{const r=svg.getBoundingClientRect(),sx=(e.clientX-r.left)*(d.W/r.width),x=(sx-d.L)/(d.W-d.L-d.R)*d.xmax;
  if(x<0||x>d.xmax){{hide();return}}xh.setAttribute('x1',sx);xh.setAttribute('x2',sx);
  let h='<b>'+x.toFixed(0)+'M steps</b>';d.series.forEach(s=>{{if(x>s.x[s.x.length-1]+1)return;let j=0,b=1e9;s.x.forEach((v,i)=>{{const q=Math.abs(v-x);if(q<b){{b=q;j=i}}}});
  h+='<br><i style="background:var('+s.var+')"></i>'+s.label+': '+f(s.y[j])}});tip.innerHTML=h;tip.hidden=false;
  const px=e.clientX-plot.getBoundingClientRect().left;tip.style.left=Math.min(px+12,plot.clientWidth-tip.offsetWidth)+'px';tip.style.top='8px'}}
 function hide(){{tip.hidden=true;xh.setAttribute('x1',-10);xh.setAttribute('x2',-10)}}
 hit.addEventListener('pointermove',show);hit.addEventListener('pointerleave',hide);}});
</script></body></html>"""


if __name__ == "__main__":
    main()
