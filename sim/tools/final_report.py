"""Final report for an unattended training queue: one HTML page with plain-language charts.

    uv run python tools/final_report.py --queue-dir runs/queue/<stamp> [--out DOCS/<YYYYMMDD>/extended_training_report.html]

For every skill family / stage: the training curves (return, episode length, the level's own
progress metric) with a sentence that says what the curve means, the gate result, and where the
production weights are. Single-hue line charts, light/dark aware, hover tooltips, table views.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_report import read_run, svg_panel, tail_mean, LIGHT, DARK  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
DOCS = ROOT.parent / "DOCS"

# What each level's key metric means, in plain language, and which column carries it.
LEVEL_INFO = {
    "l0_stand": ("Tier 1 - Upright balance", "m/upright", "How upright the athlete stays (1.0 = perfectly vertical). Episodes end at 60 s or on a fall."),
    "l1_traverse": ("Tier 2 - Court traversal", "m/waypoints", "Average number of waypoints reached per episode out of 10. The athlete must walk or jog to random spots across the whole court."),
    "l2a_dribble_r": ("Tier 3a - Right-hand dribble", "m/streak", "Average consecutive clean bounces (target 50): ball returns to waist height, stays near the body, and the right palm touches it between bounces."),
    "l2b_dribble_l": ("Tier 3b - Left-hand dribble", "m/streak", "Same clean-bounce streak with the left hand."),
    "l2c_crossover": ("Tier 3c - Crossover dribble", "m/streak", "Clean-bounce streak while switching hands on command every 2-4 bounces."),
    "l3a_moving_dribble": ("Tier 4a - Dribble on the move", "m/dist_m", "Metres covered per episode while keeping the ball under control (target 100 m at 1.5 m/s or faster)."),
    "l3b_scramble": ("Tier 4b - Loose-ball scramble", "m/regained", "Fraction of episodes in which the athlete regains a loose ball inside the 3-second window."),
    "l4_jump_shot": ("Tier 5 - Pull-up jump shot", "m/scored", "Fraction of shots that go through the rim (target 30 %)."),
}
FAMILY_OF = {"l0_stand": "balance", "l1_traverse": "locomotion", "l2a_dribble_r": "dribble", "l2b_dribble_l": "dribble",
             "l2c_crossover": "dribble", "l3a_moving_dribble": "dribble", "l3b_scramble": "scramble", "l4_jump_shot": "shot"}


def badge(ok: bool | None, text_ok="PASSED GATE", text_no="not yet passing", text_na="not run") -> str:
    if ok is None:
        return f'<span class="badge na">{text_na}</span>'
    return f'<span class="badge {"ok" if ok else "no"}">{text_ok if ok else text_no}</span>'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue-dir", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    qdir = pathlib.Path(args.queue_dir)
    state = json.loads((qdir / "queue_state.json").read_text(encoding="utf-8"))
    out = pathlib.Path(args.out) if args.out else DOCS / time.strftime("%Y%m%d") / "extended_training_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    # ---- overview table + per-stage sections
    rows_html = ""
    sections = ""
    panel_idx = 0
    # include the balance policy that graduated before the queue, if present
    pre = DOCS / "phase_reports" / "eval_l0_stand.json"
    overview = []
    if pre.exists():
        e = json.loads(pre.read_text(encoding="utf-8"))
        overview.append(("l0_stand", "balance", "l0_v4 (before queue)", e.get("success_rate"), e.get("passed"), "runs/production/balance.onnx" if (RUNS / "production" / "balance.onnx").exists() else "shared/policies/l0_stand.onnx"))
    for level, st in state["stages"].items():
        last = st["attempts"][-1] if st["attempts"] else None
        ev = (last or {}).get("eval") or {}
        prod = RUNS / "production" / f"{st.get('family')}.onnx" if st.get("family") else None
        overview.append((level, st.get("family") or FAMILY_OF.get(level, "?"), ", ".join(a["run"] for a in st["attempts"]),
                         ev.get("success_rate"), st.get("passed"), str(prod.relative_to(ROOT)) if prod and prod.exists() else "-"))
    for level, fam, runs, succ, passed, prodpath in overview:
        title = LEVEL_INFO.get(level, (level, "", ""))[0]
        rows_html += (f"<tr><td>{html.escape(title)}</td><td>{html.escape(fam)}</td><td>{html.escape(runs)}</td>"
                      f"<td>{'' if succ is None else f'{succ*100:.1f} %'}</td><td>{badge(passed)}</td><td><code>{html.escape(prodpath)}</code></td></tr>")

    for level, st in state["stages"].items():
        title, key, meaning = LEVEL_INFO.get(level, (level, "", ""))
        sec = f'<section><h2>{html.escape(title)} <small>({html.escape(st.get("family") or FAMILY_OF.get(level, ""))} policy)</small> {badge(st.get("passed"))}</h2>'
        for a in st["attempts"]:
            run = RUNS / a["run"]
            if not (run / "log.csv").exists():
                continue
            rows, cfg = read_run(run)
            ev = a.get("eval") or {}
            steps = rows[-1]["steps"] / 1e6 if rows else 0
            sec += (f'<p class="attempt"><b>{html.escape(a["run"])}</b>: {steps:.0f} M steps in {a.get("wall_min", a.get("minutes", 0)):.0f} min'
                    f' ({html.escape(str(a.get("stop_reason", "")))}). ')
            if ev:
                sec += (f'Evaluation over 200 fresh episodes: success {ev.get("success_rate", 0)*100:.1f} %, falls {ev.get("fall_rate", 0)*100:.1f} %, '
                        f'mean episode {ev.get("mean_episode_s", 0):.1f} s, NaN-gradient batches {ev.get("nan_grads", 0)}.')
            sec += "</p>"
            panels = ""
            for col, ttl, unit, expl in [
                ("ep_return", "Reward per episode", "", "Total reward the policy collects per episode. Rising and flattening means the behaviour is converging."),
                ("ep_len_s", "Episode length", "s", "How long episodes last before a fall, a loss of the ball, or the time limit. Longer is better for every level."),
                (key, ttl_for(key), "", meaning),
                ("ppo/std", "Exploration noise", "", "How much random exploration the policy still adds. It shrinks as the policy becomes confident."),
            ]:
                if not col:
                    continue
                p = svg_panel(rows, col, ttl, unit, panel_idx)
                panel_idx += 1
                if p:
                    panels += f'<div class="pwrap">{p}<p class="expl">{html.escape(expl)}</p></div>'
            sec += f'<div class="panels">{panels}</div>'
        sec += "</section>"
        sections += sec

    events = "".join(f"<li>{html.escape(e)}</li>" for e in state.get("events", [])[-400:])
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Extended training report</title>
<style>
:root{{--surface:{LIGHT['surface']};--text:{LIGHT['text']};--text2:{LIGHT['text2']};--grid:{LIGHT['grid']};--series:{LIGHT['series']};--ok:#0ca30c;--no:#d03b3b}}
@media (prefers-color-scheme: dark){{:root:not([data-theme=light]){{--surface:{DARK['surface']};--text:{DARK['text']};--text2:{DARK['text2']};--grid:{DARK['grid']};--series:{DARK['series']}}}}}
:root[data-theme=dark]{{--surface:{DARK['surface']};--text:{DARK['text']};--text2:{DARK['text2']};--grid:{DARK['grid']};--series:{DARK['series']}}}
body{{background:var(--surface);color:var(--text);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1400px}}
h1{{font-size:24px;margin:0 0 6px}} h2{{font-size:18px;margin:28px 0 6px}} small{{color:var(--text2);font-weight:400}}
.lead{{color:var(--text2);max-width:900px}} table{{border-collapse:collapse;font-size:14px;margin:12px 0}} td,th{{border:1px solid var(--grid);padding:6px 10px;text-align:left}}
.badge{{display:inline-block;font-size:12px;padding:2px 8px;border-radius:10px;border:1px solid;vertical-align:middle}} .badge.ok{{color:var(--ok);border-color:var(--ok)}} .badge.no{{color:var(--no);border-color:var(--no)}} .badge.na{{color:var(--text2);border-color:var(--grid)}}
.panels{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:18px}} .pwrap{{}} .expl{{font-size:13px;color:var(--text2);margin:4px 0 0}}
figure.panel{{margin:0;position:relative}} figcaption{{font-size:13px;color:var(--text2);margin-bottom:2px}} .last{{float:right;color:var(--text)}}
svg{{max-width:100%;height:auto;display:block}} .grid{{stroke:var(--grid)}} .tick{{fill:var(--text2);font-size:10px}} .series{{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round}}
.xhair{{stroke:var(--text2);stroke-dasharray:3 3}} .dot{{fill:var(--series);stroke:var(--surface);stroke-width:2}}
.tip{{position:absolute;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--grid);border-radius:6px;padding:4px 8px;font-size:12px;white-space:nowrap}}
.attempt{{margin:6px 0 10px}} details{{margin-top:24px}} li{{font-family:ui-monospace,monospace;font-size:12px}}
</style></head><body>
<h1>Extended training report</h1>
<p class="lead">Unattended queue started {html.escape(state.get("started", ""))}, budget {state.get("hours")} h, generated {time.strftime("%Y-%m-%d %H:%M")}.
The athlete learns one skill at a time, in order of urgency. Each skill trains until its time box ends, is then tested on 200 fresh randomised episodes, and only a skill that passes its gate (target held over every 100-episode window, no NaN gradients) becomes a production policy. A failed skill gets more time after the first pass through the ladder.</p>
<h2>Overview</h2>
<table><thead><tr><th>Skill</th><th>Policy family</th><th>Training runs</th><th>Eval success</th><th>Gate</th><th>Production weights</th></tr></thead><tbody>{rows_html}</tbody></table>
<p class="lead">How to read the charts: the x-axis is millions of simulated steps (4096 athletes practise in parallel, 50 decisions per second each). Every point is one training iteration. A curve that rises and then flattens has converged; a curve still rising when the time box ended would benefit from more training.</p>
{sections}
<details><summary>Queue event log</summary><ul>{events}</ul></details>
<script>
document.querySelectorAll("figure.panel").forEach(fig => {{
  const data = JSON.parse(fig.querySelector(".data").textContent);
  const svg = fig.querySelector("svg"), hit = fig.querySelector(".hit"), xh = fig.querySelector(".xhair"), dot = fig.querySelector(".dot"), tip = fig.querySelector(".tip");
  const pl = fig.querySelector(".series").getAttribute("points").split(" ").map(p => p.split(",").map(Number));
  hit.addEventListener("mousemove", e => {{
    const r = svg.getBoundingClientRect(); const x = (e.clientX - r.left) * (svg.viewBox.baseVal.width / r.width);
    let best = 0; for (let i = 1; i < pl.length; i++) if (Math.abs(pl[i][0] - x) < Math.abs(pl[best][0] - x)) best = i;
    xh.setAttribute("x1", pl[best][0]); xh.setAttribute("x2", pl[best][0]); xh.removeAttribute("visibility");
    dot.setAttribute("cx", pl[best][0]); dot.setAttribute("cy", pl[best][1]); dot.removeAttribute("visibility");
    tip.hidden = false; tip.textContent = data[best][0].toFixed(2) + " M steps: " + data[best][1].toPrecision(5);
    tip.style.left = (pl[best][0] / svg.viewBox.baseVal.width * r.width + 10) + "px"; tip.style.top = "22px";
  }});
  hit.addEventListener("mouseleave", () => {{ xh.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true; }});
}});
</script>
</body></html>'''
    out.write_text(page, encoding="utf-8")
    print("wrote", out)


def ttl_for(key: str) -> str:
    return {"m/upright": "Upright score", "m/waypoints": "Waypoints reached", "m/streak": "Clean-bounce streak",
            "m/dist_m": "Distance with the ball (m)", "m/regained": "Loose balls regained", "m/scored": "Shots scored"}.get(key, key)


if __name__ == "__main__":
    main()
