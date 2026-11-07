"""Baseline RL vs AMP comparison report for the locomotion policy.

    uv run python tools/compare_amp.py --baseline runs/l1_v3_armcarry --amp runs/l1_amp_v1 --out ../DOCS/<day>/amp_vs_baseline.html

Measures, for each checkpoint, with identical rollouts (level l1_traverse, 1024 envs, 20 s, no pushes):
  * task results from each run's 200-episode evaluation (eval.json): success, falls, speed
  * motion style:
      - human-likeness: a FRESH classifier (same architecture as the AMP discriminator, trained from scratch for each
        policy with the same seed and budget) tries to tell the policy's transitions from the LocoMuJoCo mocap; its
        held-out accuracy is reported (50 % = indistinguishable from mocap, 100 % = trivially different). Using a fresh
        classifier avoids scoring AMP with its own discriminator.
      - arm-carry penalty (the hand-written term), arm swing amplitude and left/right symmetry
  * training curves from both runs' log.csv
  * filmstrips (MuJoCo render): mocap walk reference, baseline, AMP
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import pathlib
import sys

import mujoco
import numpy as np
import torch
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from run_report import read_run  # noqa: E402
from streetball.amp import KEY_BODIES, Discriminator, FixedNormalizer, amp_features  # noqa: E402
from streetball.env_base import EnvConfig, RandomizationConfig, StreetballEnv  # noqa: E402
from streetball.levels import make  # noqa: E402
from streetball.ppo import Actor  # noqa: E402

COL = {"baseline": ("#2a78d6", "#3987e5"), "amp": ("#eb6834", "#d95926")}   # dataviz categorical slots 1, 2 (light, dark)
NAMES = {"baseline": "Original RL (hand-tuned reward)", "amp": "AMP (motion-capture style)"}


def rollout(ckpt: pathlib.Path, seconds: float = 20.0, n: int = 1024):
    level = make("l1_traverse")
    env = StreetballEnv(level, EnvConfig(num_envs=n, seed=11, randomization=RandomizationConfig(enabled=True, push_force=(0.0, 0.0))))
    sd = torch.load(ckpt, map_location=env.device)
    actor = Actor(env.N_OBS, env.N_ACT).to(env.device)
    actor.load_state_dict({k[6:]: v for k, v in sd["ac"].items() if k.startswith("actor.")}); actor.eval()
    keyb = torch.as_tensor([mujoco.mj_name2id(env.mjm, mujoco.mjtObj.mjOBJ_BODY, b) for b in KEY_BODIES], device=env.device)
    rq, rv = env.root_q, env.root_v
    feats = lambda: amp_features(env.qpos[:, rq:rq + 3], env.qpos[:, rq + 3:rq + 7], env.qvel[:, rv:rv + 3],
                                 env.qvel[:, rv + 3:rv + 6], env.joint_pos(), env.joint_vel(), env.xpos[:, keyb])
    obs = env.obs
    f_prev = feats().clone()
    pairs, carry, sp_l, sp_r, speed, film = [], [], [], [], [], []
    with torch.no_grad():
        for t in range(int(seconds / env.control_dt)):
            obs, _, done, _ = env.step(actor(obs))
            f = feats()
            if t > 50:                                           # skip the first second (start transient)
                pairs.append(torch.cat([f_prev, f], -1)[~done])
                jp = env.joint_pos()
                dev = jp - env.nominal
                carry.append(((dev[:, [1, 2, 7, 8]] ** 2).mean(1) + 0.2 * (dev[:, [3, 9]] ** 2).mean(1)).mean().item())
                sp_l.append(jp[:, 0].cpu()); sp_r.append(jp[:, 6].cpu())
                speed.append(env.v_pelvis[:, :2].norm(dim=-1).mean().item())
            f_prev = f.clone()
            film.append(env.qpos[0].cpu().numpy().copy())
    sp_l, sp_r = torch.stack(sp_l), torch.stack(sp_r)
    amp_l, amp_r = sp_l.std(0).mean().item(), sp_r.std(0).mean().item()
    return {"pairs": torch.cat(pairs, 0), "arm_carry": float(np.mean(carry)), "swing_l_deg": np.degrees(amp_l),
            "swing_r_deg": np.degrees(amp_r), "swing_symmetry": min(amp_l, amp_r) / max(amp_l, amp_r),
            "speed": float(np.mean(speed)), "film": np.array(film)}


def two_sample_acc(pol: torch.Tensor, demo: torch.Tensor, device, steps: int = 400, seed: int = 0) -> float:
    g = torch.Generator(device="cpu").manual_seed(seed)
    m = min(len(pol), len(demo), 200_000)
    pol = pol[torch.randperm(len(pol), generator=g)[:m]].to(device)
    demo = demo[torch.randperm(len(demo), generator=g)[:m]].to(device)
    h = m // 2
    norm = FixedNormalizer(demo[:h]).to(device)
    torch.manual_seed(seed)
    D = Discriminator(demo.shape[1]).to(device)
    opt = torch.optim.Adam(D.parameters(), lr=1e-4)
    bce = torch.nn.functional.binary_cross_entropy_with_logits
    for _ in range(steps):
        i = torch.randint(0, h, (4096,), device=device)
        la, ld = D(norm(pol[i])), D(norm(demo[i]))
        loss = 0.5 * (bce(la, torch.zeros_like(la)) + bce(ld, torch.ones_like(ld)))
        opt.zero_grad(); loss.backward(); opt.step()
    with torch.no_grad():
        lp, ld = D(norm(pol[h:])), D(norm(demo[h:]))
        acc = 0.5 * ((lp < 0).float().mean().item() + (ld > 0).float().mean().item())
        # held-out cross-entropy relative to chance (ln 2): 1.0 = classifier is guessing (indistinguishable),
        # 0.0 = perfectly confident. Unlike accuracy it keeps ranking policies once accuracy saturates at 100 %.
        bce = 0.5 * (torch.nn.functional.softplus(lp).mean() + torch.nn.functional.softplus(-ld).mean()).item()
    return acc, min(1.0, bce / float(np.log(2)))


def filmstrip(qs: np.ndarray, start: int, frames: int = 6, step: int = 6) -> str:
    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml")); d = mujoco.MjData(m)
    root = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    r = mujoco.Renderer(m, 300, 250); cam = mujoco.MjvCamera(); tiles = []
    for i in range(frames):
        d.qpos[:] = qs[min(len(qs) - 1, start + i * step)]; mujoco.mj_forward(m, d)
        w, x, y, z = d.qpos[root + 3:root + 7]
        cam.lookat[:] = [d.qpos[root], d.qpos[root + 1], 0.9]; cam.distance, cam.elevation = 3.0, -8.0
        cam.azimuth = np.degrees(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))) + 90.0
        r.update_scene(d, cam); tiles.append(r.render())
    buf = io.BytesIO(); Image.fromarray(np.concatenate(tiles, 1)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def line_chart(series: dict[str, list[tuple[float, float]]], title: str, unit: str, caption: str, idx: int) -> str:
    W, H, L, R, T, B = 460, 220, 52, 96, 16, 30
    allx = [x for s in series.values() for x, _ in s]; ally = [y for s in series.values() for _, y in s]
    if not allx:
        return ""
    x0, x1 = min(allx), max(allx); y0, y1 = min(ally), max(ally)
    if y1 == y0:
        y1 = y0 + 1
    pad = 0.08 * (y1 - y0); y0, y1 = y0 - pad, y1 + pad
    sx = lambda x: L + (x - x0) / ((x1 - x0) or 1) * (W - L - R)
    sy = lambda y: T + (1 - (y - y0) / (y1 - y0)) * (H - T - B)
    g = ""
    for k in range(4):
        gy = y0 + (y1 - y0) * k / 3
        g += f'<line x1="{L}" y1="{sy(gy):.1f}" x2="{W-R}" y2="{sy(gy):.1f}" class="grid"/><text x="{L-6}" y="{sy(gy)+4:.1f}" class="tick" text-anchor="end">{gy:.3g}</text>'
    for k in range(4):
        gx = x0 + (x1 - x0) * k / 3
        g += f'<text x="{sx(gx):.1f}" y="{H-10}" class="tick" text-anchor="middle">{gx:.0f}M</text>'
    lines, labels, data = "", "", {}
    for key, pts in series.items():
        if len(pts) < 2:
            continue
        lines += f'<polyline points="{" ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)}" class="s-{key}"/>'
        lx, ly = pts[-1]
        labels += f'<text x="{sx(lx)+6:.1f}" y="{sy(ly)+4:.1f}" class="dl">{"AMP" if key == "amp" else "Original"} {ly:.3g}</text>'
        data[key] = [[round(x, 2), round(y, 4)] for x, y in pts]
    return f'''<figure class="panel" data-idx="{idx}"><figcaption><b>{html.escape(title)}</b>{f" ({unit})" if unit else ""}</figcaption>
<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}: original vs AMP over training steps">{g}{lines}{labels}
<line class="xhair" x1="0" y1="{T}" x2="0" y2="{H-B}" visibility="hidden"/><rect class="hit" x="{L}" y="{T}" width="{W-L-R}" height="{H-T-B}" fill="transparent"/></svg>
<div class="tip" hidden></div><p class="cap">{caption}</p><script type="application/json" class="data">{json.dumps(data)}</script></figure>'''


def bar_pair(title: str, vals: dict[str, float], fmt: str, caption: str, lo: float = 0.0, hi: float | None = None, ref: float | None = None, ref_label: str = "") -> str:
    W, L, R, rowh = 460, 150, 70, 34
    hi = hi if hi is not None else max(vals.values()) * 1.15
    sx = lambda v: L + (v - lo) / (hi - lo) * (W - L - R)
    rows = ""
    for i, (k, v) in enumerate(vals.items()):
        y = 10 + i * rowh
        rows += (f'<text x="{L-8}" y="{y+17}" class="lab" text-anchor="end">{"AMP" if k == "amp" else "Original RL"}</text>'
                 f'<rect x="{L}" y="{y+4}" width="{max(2, sx(v)-L):.1f}" height="20" rx="4" class="b-{k}"><title>{fmt.format(v)}</title></rect>'
                 f'<text x="{sx(v)+6:.1f}" y="{y+18}" class="val">{fmt.format(v)}</text>')
    refl = ""
    if ref is not None:
        refl = (f'<line x1="{sx(ref):.1f}" y1="4" x2="{sx(ref):.1f}" y2="{10+len(vals)*rowh}" class="ref"/>'
                f'<text x="{sx(ref):.1f}" y="{20+len(vals)*rowh}" class="tick" text-anchor="middle">{html.escape(ref_label)}</text>')
    Hh = 30 + len(vals) * rowh
    return f'<figure class="panel"><figcaption><b>{html.escape(title)}</b></figcaption><svg viewBox="0 0 {W} {Hh}" role="img" aria-label="{html.escape(title)}">{rows}{refl}</svg><p class="cap">{caption}</p></figure>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--amp", required=True)
    ap.add_argument("--demo", default=str(ROOT / "data" / "mocap" / "amp_demo.npz"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--interim", action="store_true", help="AMP still training: no eval.json yet; fewer rollout envs")
    args = ap.parse_args()
    runs = {"baseline": pathlib.Path(args.baseline), "amp": pathlib.Path(args.amp)}
    demo = torch.as_tensor(np.load(args.demo)["pairs"], dtype=torch.float32)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    res = {}
    for k, run in runs.items():
        r = rollout(run / "model.pt", n=256 if args.interim else 1024)
        r["human_acc"], r["human_score"] = two_sample_acc(r["pairs"], demo, dev)
        ev_path = run / "eval.json"
        r["eval"] = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {"success_rate": float("nan"), "fall_rate": float("nan"), "holds_100_straight": "pending"}
        res[k] = r
        print(f"{k}: classifier acc {r['human_acc']:.3f}, human score {r['human_score']:.3f}, arm carry {r['arm_carry']:.3f}, swing L/R {r['swing_l_deg']:.1f}/{r['swing_r_deg']:.1f} deg, "
              f"success {r['eval']['success_rate']:.3f}", flush=True)
    perm = torch.randperm(len(demo), generator=torch.Generator().manual_seed(1))
    mocap_self, mocap_self_score = two_sample_acc(demo[perm[: len(demo) // 2]], demo[perm[len(demo) // 2:]], dev)
    print(f"mocap vs mocap (sanity, should be ~0.5): {mocap_self:.3f}")

    mocap_q = np.load(ROOT / "data" / "mocap" / "default_walk_seg0_qpos.npz")["qpos"]
    strips = {"mocap": filmstrip(mocap_q, 1000), "baseline": filmstrip(res["baseline"]["film"], 300), "amp": filmstrip(res["amp"]["film"], 300)}

    logs = {k: read_run(run)[0] for k, run in runs.items()}
    def ser(col):
        return {k: [(r["steps"] / 1e6, r[col]) for r in rows if col in r][::3] for k, rows in logs.items()}
    charts = [
        line_chart(ser("m/arm_carry"), "Arm-carry penalty", "lower = arms nearer a natural pose",
                   "How far the shoulders and elbows sit from a relaxed pose. The original run is paid to keep this low; AMP is not told about it at all.", 0),
        line_chart(ser("m/speed"), "Jog speed", "m/s", "Average pelvis speed during training rollouts.", 1),
        line_chart(ser("ep_len_s"), "Episode length", "s", "How long episodes last before a fall, a finish or the 90 s limit.", 2),
        line_chart(ser("m/waypoints"), "Waypoints per episode (running mean)", "", "Task progress during training.", 3),
        line_chart({"amp": [(r["steps"] / 1e6, r["amp/r_style"]) for r in logs["amp"] if "amp/r_style" in r][::3]},
                   "AMP style reward", "per step", "What the motion-capture discriminator pays AMP per step. Rising = moving more like the mocap.", 4),
    ]
    ev = {k: r["eval"] for k, r in res.items()}
    pending = args.interim or ev['amp']['holds_100_straight'] == 'pending'
    bars = [] if pending else [
        bar_pair("Task success (200 episodes)", {k: 100 * ev[k]["success_rate"] for k in runs}, "{:.1f} %",
                 "Episodes that reached all 10 waypoints in 90 s without falling. The graduation gate is 90 %.", 0, 100, 90, "gate 90 %"),
        bar_pair("Falls (200 episodes)", {k: 100 * ev[k]["fall_rate"] for k in runs}, "{:.1f} %", "Lower is better.", 0, max(5.0, max(100 * ev[k]["fall_rate"] for k in runs) * 1.3)),
    ]
    bars += [
        bar_pair("Human-likeness score", {k: 100 * res[k]["human_score"] for k in runs}, "{:.1f}",
                 f"A classifier trained from scratch tries to tell the policy's motion from the LocoMuJoCo motion capture. The score is how unsure it stays on held-out data: 100 = it is guessing (moves like the mocap), 0 = completely sure it is not mocap. Higher is more human-like. Mocap against itself scores {100*mocap_self_score:.0f}; classifier accuracy is {100*res['baseline']['human_acc']:.0f} % original vs {100*res['amp']['human_acc']:.0f} % AMP.",
                 0, 100),
        bar_pair("Arm-carry penalty (rollouts)", {k: res[k]["arm_carry"] for k in runs}, "{:.3f}", "Lower = shoulders and elbows nearer a relaxed pose.", 0),
        bar_pair("Arm swing left/right symmetry", {k: 100 * res[k]["swing_symmetry"] for k in runs}, "{:.0f} %",
                 "Smaller arm swing divided by the larger one. 100 % = both arms swing equally (the original policy favoured carrying the right arm).", 0, 100),
    ]
    rows = "".join(f"<tr><td>{n}</td><td>{100*ev['baseline'][f]:.1f} %</td><td>{100*ev['amp'][f]:.1f} %</td></tr>" for n, f in (("Success", "success_rate"), ("Falls", "fall_rate")))
    rows += "".join(f"<tr><td>{n}</td><td>{fmt.format(res['baseline'][f])}</td><td>{fmt.format(res['amp'][f])}</td></tr>" for n, f, fmt in (
        ("Human-likeness score (100 best)", "human_score", "{:.3f}"), ("Classifier accuracy vs mocap (50 % best)", "human_acc", "{:.3f}"), ("Arm-carry penalty", "arm_carry", "{:.3f}"),
        ("Arm swing left (deg, std)", "swing_l_deg", "{:.1f}"), ("Arm swing right (deg, std)", "swing_r_deg", "{:.1f}"),
        ("Arm swing symmetry", "swing_symmetry", "{:.2f}"), ("Speed in style rollouts (m/s)", "speed", "{:.2f}")))
    rows += f"<tr><td>Holds 100 straight</td><td>{ev['baseline']['holds_100_straight']}</td><td>{ev['amp']['holds_100_straight']}</td></tr>"
    better_task = "AMP" if ev["amp"]["success_rate"] > ev["baseline"]["success_rate"] else "the original RL"
    better_style = "AMP" if res["amp"]["human_score"] > res["baseline"]["human_score"] else "the original RL"
    if pending:
        amp_steps = logs["amp"][-1]["steps"] / 1e6 if logs["amp"] else 0
        tldr = (f"Interim snapshot: AMP is still training ({amp_steps:.0f} M steps so far) and has no 200-episode evaluation yet. "
                f"Style so far: human-likeness {100*res['baseline']['human_score']:.0f} original vs {100*res['amp']['human_score']:.0f} AMP (100 = indistinguishable from mocap); "
                f"arm-swing symmetry {100*res['baseline']['swing_symmetry']:.0f} % vs {100*res['amp']['swing_symmetry']:.0f} %.")
    else:
        tldr = (f"Task: {better_task} scores higher ({100*ev['baseline']['success_rate']:.0f} % original vs {100*ev['amp']['success_rate']:.0f} % AMP, gate 90 %). "
                f"Style: {better_style} moves more like the motion capture (human-likeness {100*res['baseline']['human_score']:.0f} vs {100*res['amp']['human_score']:.0f}; 100 = indistinguishable).")
    (pathlib.Path(args.out).with_suffix(".json")).write_text(json.dumps({k: {kk: (vv if not isinstance(vv, (np.ndarray, torch.Tensor)) else None)
        for kk, vv in r.items() if kk not in ("pairs", "film")} for k, r in res.items()} | {"mocap_self_acc": mocap_self, "mocap_self_score": mocap_self_score}, indent=2, default=float), encoding="utf-8")
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Original RL vs AMP</title><style>
:root{{--surface:#fcfcfb;--text:#0b0b0b;--text2:#52514e;--grid:#e6e5e1;--c1:{COL['baseline'][0]};--c2:{COL['amp'][0]}}}
@media (prefers-color-scheme: dark){{:root:not([data-theme=light]){{--surface:#1a1a19;--text:#f0efec;--text2:#c3c2b7;--grid:#34332f;--c1:{COL['baseline'][1]};--c2:{COL['amp'][1]}}}}}
:root[data-theme=dark]{{--surface:#1a1a19;--text:#f0efec;--text2:#c3c2b7;--grid:#34332f;--c1:{COL['baseline'][1]};--c2:{COL['amp'][1]}}}
body{{margin:0;background:var(--surface);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px 64px}} h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 8px}}
.sub,.cap,figcaption{{color:var(--text2)}} .cap{{font-size:13px;margin:4px 0 0}} .tldr{{border-left:4px solid var(--c2);padding:8px 12px;margin:16px 0}}
.legend span{{display:inline-flex;align-items:center;gap:6px;margin-right:16px}} .sw{{width:12px;height:12px;border-radius:3px;display:inline-block}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:16px}}
figure.panel{{margin:0;position:relative}} svg{{width:100%;height:auto;overflow:visible}}
.grid{{stroke:var(--grid);stroke-width:1}} .tick,.dl,.lab,.val{{fill:var(--text2);font-size:11px}} .val,.lab{{fill:var(--text);font-size:12px}}
.s-baseline{{fill:none;stroke:var(--c1);stroke-width:2}} .s-amp{{fill:none;stroke:var(--c2);stroke-width:2}}
.b-baseline{{fill:var(--c1)}} .b-amp{{fill:var(--c2)}} .ref{{stroke:var(--text2);stroke-dasharray:4 3}}
.xhair{{stroke:var(--text2);stroke-width:1}} .tip{{position:absolute;top:28px;right:8px;background:var(--surface);border:1px solid var(--grid);border-radius:6px;padding:4px 8px;font-size:12px;pointer-events:none}}
.film img{{width:100%;border-radius:6px;display:block}} .film p{{margin:8px 0 2px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{border-bottom:1px solid var(--grid);padding:6px 8px;text-align:left}}
.stamp{{position:fixed;right:8px;bottom:6px;font-size:11px;color:var(--text2)}}
</style></head><body><main>
<h1>Walking policy: original RL vs AMP</h1>
<p class="sub">Both started from the same checkpoint (<code>l1_v2_armstop</code>) and trained for 90 minutes on the same environment, pushes and speed commands.
The original run adds hand-written arm penalties; the AMP run instead learns style from {len(demo)//50//60} minutes of LocoMuJoCo motion capture (MimicKit's Adversarial Motion Priors).</p>
<p class="legend"><span><i class="sw" style="background:var(--c1)"></i>{NAMES['baseline']}</span><span><i class="sw" style="background:var(--c2)"></i>{NAMES['amp']}</span></p>
<p class="tldr"><b>TL;DR</b> {html.escape(tldr)}</p>
<h2>Results</h2><div class="grid2">{"".join(bars)}</div>
<h2>How they move</h2><div class="film">
<p><b>Motion capture reference</b> (LocoMuJoCo walk, retargeted to our humanoid)</p><img src="{strips['mocap']}" alt="mocap walk filmstrip">
<p><b>Original RL</b></p><img src="{strips['baseline']}" alt="original RL filmstrip">
<p><b>AMP</b></p><img src="{strips['amp']}" alt="AMP filmstrip"></div>
<h2>Training curves</h2><div class="grid2">{"".join(charts)}</div>
<h2>Table view</h2><table><tr><th>Metric</th><th>Original RL</th><th>AMP</th></tr>{rows}</table>
<p class="cap">Mocap data: LocoMuJoCo (robfiras/loco-mujoco-datasets, CC BY-NC-ND 4.0, non-commercial; not redistributed). AMP method: MimicKit (xbpeng/MimicKit).</p>
</main><div class="stamp">{__import__("time").strftime("%y%m%d")}</div>
<script>
document.querySelectorAll('figure.panel').forEach(f=>{{const d=f.querySelector('script.data');if(!d)return;const data=JSON.parse(d.textContent);
const svg=f.querySelector('svg'),hit=f.querySelector('.hit'),xh=f.querySelector('.xhair'),tip=f.querySelector('.tip');if(!hit)return;
const pl=[...svg.querySelectorAll('polyline')];
hit.addEventListener('mousemove',e=>{{const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());
xh.setAttribute('x1',p.x);xh.setAttribute('x2',p.x);xh.setAttribute('visibility','visible');
const x0=+hit.getAttribute('x'),w=+hit.getAttribute('width');const keys=Object.keys(data);let out=[];
keys.forEach(k=>{{const s=data[k];const xs=s.map(v=>v[0]);const xmin=Math.min(...keys.flatMap(kk=>data[kk].map(v=>v[0]))),xmax=Math.max(...keys.flatMap(kk=>data[kk].map(v=>v[0])));
const xv=xmin+(p.x-x0)/w*(xmax-xmin);let best=s[0];s.forEach(v=>{{if(Math.abs(v[0]-xv)<Math.abs(best[0]-xv))best=v}});out.push((k==='amp'?'AMP':'Original')+': '+best[1]+' @ '+best[0]+'M')}});
tip.textContent=out.join(' | ');tip.hidden=false}});
hit.addEventListener('mouseleave',()=>{{xh.setAttribute('visibility','hidden');tip.hidden=true}})}});
</script></body></html>'''
    pathlib.Path(args.out).write_text(page, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
