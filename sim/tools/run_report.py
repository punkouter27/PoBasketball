"""UU_AGENT section 4: HTML report for a training run (metric charts + run-over-run deltas).

    uv run python tools/run_report.py runs/l0_v4 [--compare runs/l0_v3] [--out ../DOCS/<YYYYMMDD>/report_<run>.html]

Reads runs/<run>/log.csv and config.json (and DOCS/phase_reports/eval_<level>.json if present).
Charts: one metric per panel (single series, one hue, 2 px line, recessive grid, crosshair tooltip),
light/dark via prefers-color-scheme, plus a table view and a deltas table against the comparison run
(the previous run of the same level by default). No external libraries.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
DOCS = ROOT.parent / "DOCS"

PANELS = [  # (column, title, unit)
    ("ep_return", "Episode return", ""),
    ("ep_len_s", "Episode length", "s"),
    ("fps", "Throughput", "steps/s"),
    ("ppo/kl", "PPO KL", ""),
    ("ppo/std", "Policy std", ""),
    ("loss/value", "Value loss", ""),
]
# level metrics (m/...) are added automatically
LIGHT = dict(surface="#fcfcfb", text="#0b0b0b", text2="#52514e", grid="#e6e5e1", series="#2a78d6")
DARK = dict(surface="#1a1a19", text="#f0efec", text2="#c3c2b7", grid="#34332f", series="#3987e5")


def read_run(run: pathlib.Path) -> tuple[list[dict], dict]:
    rows = []
    with open(run / "log.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({k: float(v) for k, v in r.items() if v not in ("", None)})
    cfg = json.loads((run / "config.json").read_text(encoding="utf-8")) if (run / "config.json").exists() else {}
    return rows, cfg


def tail_mean(rows: list[dict], col: str, n: int = 20) -> float | None:
    vals = [r[col] for r in rows[-n:] if col in r]
    return sum(vals) / len(vals) if vals else None


def svg_panel(rows: list[dict], col: str, title: str, unit: str, idx: int) -> str:
    xs = [r["steps"] / 1e6 for r in rows if col in r]
    ys = [r[col] for r in rows if col in r]
    if len(xs) < 2:
        return ""
    W, H, L, R, T, B = 420, 200, 48, 12, 28, 30
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if y1 == y0:
        y1 = y0 + 1.0
    pad = 0.06 * (y1 - y0)
    y0, y1 = y0 - pad, y1 + pad
    sx = lambda x: L + (x - x0) / (x1 - x0 or 1) * (W - L - R)
    sy = lambda y: T + (1 - (y - y0) / (y1 - y0)) * (H - T - B)
    pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, ys))
    grid = ""
    for k in range(4):
        gy = y0 + (y1 - y0) * k / 3
        grid += f'<line x1="{L}" y1="{sy(gy):.1f}" x2="{W-R}" y2="{sy(gy):.1f}" class="grid"/>'
        grid += f'<text x="{L-6}" y="{sy(gy)+4:.1f}" class="tick" text-anchor="end">{gy:.3g}</text>'
    for k in range(4):
        gx = x0 + (x1 - x0) * k / 3
        grid += f'<text x="{sx(gx):.1f}" y="{H-10}" class="tick" text-anchor="middle">{gx:.1f}M</text>'
    last = ys[-1]
    data = json.dumps([[round(x, 3), round(y, 5)] for x, y in zip(xs, ys)])
    return f'''
<figure class="panel" data-idx="{idx}">
  <figcaption>{html.escape(title)}{f" ({unit})" if unit else ""} <span class="last">last {last:.4g}</span></figcaption>
  <svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{html.escape(title)} over training steps">
    {grid}
    <polyline points="{pts}" class="series"/>
    <line class="xhair" x1="0" y1="{T}" x2="0" y2="{H-B}" visibility="hidden"/>
    <circle class="dot" r="4" visibility="hidden"/>
    <rect class="hit" x="{L}" y="{T}" width="{W-L-R}" height="{H-T-B}" fill="transparent"/>
  </svg>
  <div class="tip" hidden></div>
  <script type="application/json" class="data">{data}</script>
</figure>'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--compare", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    run = pathlib.Path(args.run)
    rows, cfg = read_run(run)
    level = cfg.get("level", "?")
    comp = pathlib.Path(args.compare) if args.compare else None
    if comp is None:
        cands = sorted([p for p in RUNS.iterdir() if p.is_dir() and p != run and (p / "log.csv").exists()
                        and json.loads((p / "config.json").read_text(encoding="utf-8")).get("level") == level]
                       if RUNS.exists() else [], key=lambda p: p.stat().st_mtime)
        comp = cands[-1] if cands else None
    crow, _ = read_run(comp) if comp else ([], {})

    cols = [c for c, _, _ in PANELS] + sorted({k for r in rows for k in r if k.startswith("m/")})
    titles = {c: t for c, t, _ in PANELS}
    units = {c: u for c, _, u in PANELS}
    panels = "".join(svg_panel(rows, c, titles.get(c, c[2:].replace("_", " ")), units.get(c, ""), i) for i, c in enumerate(cols))

    total_steps = rows[-1]["steps"] if rows else 0
    per_iter = [rows[i]["steps"] - (rows[i - 1]["steps"] if i else 0.0) for i in range(len(rows))]
    wall_min = sum(n / max(r.get("fps", 1.0), 1.0) for n, r in zip(per_iter, rows)) / 60
    eval_json = DOCS / "phase_reports" / f"eval_{level}.json"
    ev = json.loads(eval_json.read_text(encoding="utf-8")) if eval_json.exists() else {}

    def tile(label, value):
        return f'<div class="tile"><div class="lbl">{html.escape(label)}</div><div class="val">{value}</div></div>'
    tiles = tile("Steps", f"{total_steps/1e6:.1f} M") + tile("Wall time (est.)", f"{wall_min:.0f} min") + \
        tile("Final return", f"{tail_mean(rows, 'ep_return') or 0:.1f}") + tile("Final episode", f"{tail_mean(rows, 'ep_len_s') or 0:.1f} s")
    if ev:
        tiles += tile("Eval success", f"{ev.get('success_rate', 0)*100:.1f} %") + tile("Gate", "PASS" if ev.get("passed") else "FAIL")

    delta_rows = ""
    for c in cols:
        a, b = tail_mean(rows, c), tail_mean(crow, c)
        if a is None:
            continue
        d = "" if b is None else f"{a - b:+.4g}"
        delta_rows += f"<tr><td>{html.escape(c)}</td><td>{a:.4g}</td><td>{'' if b is None else f'{b:.4g}'}</td><td>{d}</td></tr>"

    table_head = "".join(f"<th>{html.escape(c)}</th>" for c in ["iter", "steps"] + cols)
    table_rows = "".join("<tr>" + "".join(f"<td>{r.get(c, ''):.5g}</td>" if isinstance(r.get(c, ''), float) else f"<td></td>"
                                         for c in ["iter", "steps"] + cols) + "</tr>" for r in rows[::max(1, len(rows) // 200)])

    out = pathlib.Path(args.out) if args.out else DOCS / time.strftime("%Y%m%d") / f"report_{run.name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Run {html.escape(run.name)}</title>
<style>
:root{{--surface:{LIGHT['surface']};--text:{LIGHT['text']};--text2:{LIGHT['text2']};--grid:{LIGHT['grid']};--series:{LIGHT['series']}}}
@media (prefers-color-scheme: dark){{:root:not([data-theme=light]){{--surface:{DARK['surface']};--text:{DARK['text']};--text2:{DARK['text2']};--grid:{DARK['grid']};--series:{DARK['series']}}}}}
:root[data-theme=dark]{{--surface:{DARK['surface']};--text:{DARK['text']};--text2:{DARK['text2']};--grid:{DARK['grid']};--series:{DARK['series']}}}
body{{background:var(--surface);color:var(--text);font:14px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1400px}}
h1{{font-size:20px;margin:0 0 4px}} .meta{{color:var(--text2);margin-bottom:16px}}
.tiles{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0 20px}} .tile{{border:1px solid var(--grid);border-radius:8px;padding:10px 14px;min-width:120px}}
.tile .lbl{{color:var(--text2);font-size:12px}} .tile .val{{font-size:22px;font-weight:600}}
.panels{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}}
figure.panel{{margin:0;position:relative}} figcaption{{font-size:13px;color:var(--text2);margin-bottom:2px}} .last{{float:right;color:var(--text)}}
svg{{max-width:100%;height:auto;display:block}} .grid{{stroke:var(--grid);stroke-width:1}} .tick{{fill:var(--text2);font-size:10px}}
.series{{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round}} .xhair{{stroke:var(--text2);stroke-dasharray:3 3}} .dot{{fill:var(--series);stroke:var(--surface);stroke-width:2}}
.tip{{position:absolute;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--grid);border-radius:6px;padding:4px 8px;font-size:12px;white-space:nowrap}}
table{{border-collapse:collapse;font-size:12px}} td,th{{border:1px solid var(--grid);padding:3px 8px;text-align:right}} th:first-child,td:first-child{{text-align:left}}
details{{margin-top:20px}} .wrap{{overflow:auto;max-height:420px}}
</style></head><body>
<h1>Training run {html.escape(run.name)} — level {html.escape(level)}</h1>
<div class="meta">{len(rows)} iterations · compared with {html.escape(comp.name) if comp else "nothing (first run of this level)"} · generated {time.strftime("%Y-%m-%d %H:%M")}</div>
<div class="tiles">{tiles}</div>
<div class="panels">{panels}</div>
<h2 style="font-size:16px;margin-top:24px">Run-over-run deltas (mean of the last 20 iterations)</h2>
<table><thead><tr><th>metric</th><th>{html.escape(run.name)}</th><th>{html.escape(comp.name) if comp else "—"}</th><th>delta</th></tr></thead><tbody>{delta_rows}</tbody></table>
<details><summary>Table view (every {max(1, len(rows)//200)} iterations)</summary><div class="wrap"><table><thead><tr>{table_head}</tr></thead><tbody>{table_rows}</tbody></table></div></details>
<script>
document.querySelectorAll("figure.panel").forEach(fig => {{
  const data = JSON.parse(fig.querySelector(".data").textContent);
  const svg = fig.querySelector("svg"), hit = fig.querySelector(".hit"), xh = fig.querySelector(".xhair"), dot = fig.querySelector(".dot"), tip = fig.querySelector(".tip");
  const pl = fig.querySelector(".series").getAttribute("points").split(" ").map(p => p.split(",").map(Number));
  const show = e => {{
    const r = svg.getBoundingClientRect(); const x = (e.clientX - r.left) * (svg.viewBox.baseVal.width / r.width);
    let best = 0; for (let i = 1; i < pl.length; i++) if (Math.abs(pl[i][0] - x) < Math.abs(pl[best][0] - x)) best = i;
    xh.setAttribute("x1", pl[best][0]); xh.setAttribute("x2", pl[best][0]); xh.removeAttribute("visibility");
    dot.setAttribute("cx", pl[best][0]); dot.setAttribute("cy", pl[best][1]); dot.removeAttribute("visibility");
    tip.hidden = false; tip.textContent = data[best][0].toFixed(2) + " M steps: " + data[best][1].toPrecision(5);
    tip.style.left = (pl[best][0] / svg.viewBox.baseVal.width * r.width + 10) + "px"; tip.style.top = "22px";
  }};
  hit.addEventListener("mousemove", show); hit.addEventListener("mouseleave", () => {{ xh.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true; }});
}});
</script>
</body></html>''', encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
