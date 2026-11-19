"""Floating-palm dribble bench: the real ball and floor, plus one palm on 3 slide joints (no humanoid).

Isolates the palm-ball contact from balance. Compares contact models with a scripted
"ride up, push down" hand and an impact test. CPU only, never touches sim/assets.

    .venv/Scripts/python.exe tools/dribble_bench.py
"""
from __future__ import annotations

import math
import pathlib
import re

import mujoco
import numpy as np

COURT = (pathlib.Path(__file__).resolve().parents[1] / "assets" / "court.xml").read_text(encoding="utf-8")
BALL_DEF = re.search(r'<default class="ball">.*?</default>', COURT, re.S).group(0)
FLOOR_PAIR = re.search(r'<pair name="ball_floor".*?/>', COURT).group(0)
R, CTRL_EVERY, APEX_BAND, APEX_TARGET = 0.1205, 10, (0.65, 1.00), 0.8   # 500 Hz physics, 50 Hz control


def direct(omega: float, zeta: float) -> str:
    return f"{-omega * omega:.1f} {-2 * zeta * omega:.2f}"


VARIANTS = {   # name: (palm half-size xy, extra ball-palm pair or "")
    "rigid (now)": ((0.05, 0.045), ""),
    "soft palm": ((0.05, 0.045), f'<pair geom1="ball" geom2="palm" condim="6" friction="0.9 0.9 0.02 0.005 0.005" solref="{direct(45, 1.0)}" solimp="0.9 0.95 0.01"/>'),
    "soft + wide": ((0.075, 0.065), f'<pair geom1="ball" geom2="palm" condim="6" friction="0.9 0.9 0.02 0.005 0.005" solref="{direct(45, 1.0)}" solimp="0.9 0.95 0.01"/>'),
}


def xml(half_xy, pair: str) -> str:
    return f"""<mujoco><option timestep="0.002" integrator="implicitfast" solver="Newton" cone="elliptic"/>
<default>{BALL_DEF}</default><worldbody>
<geom name="floor" type="plane" size="5 5 .1" condim="6" friction="0.9 0.01 0.002" solref="0.01 1" solimp="0.9 0.95 0.001"/>
<body name="palm" pos="0 0 0.95" gravcomp="1">
  <joint name="px" type="slide" axis="1 0 0" damping="1"/><joint name="py" type="slide" axis="0 1 0" damping="1"/>
  <joint name="pz" type="slide" axis="0 0 1" damping="1"/>
  <geom name="palm" type="box" size="{half_xy[0]} {half_xy[1]} 0.015" mass="0.48" condim="3" friction="0.9 0.01 0.002" solref="0.006 1" solimp="0.95 0.99 0.001"/>
</body>
<body name="ball" pos="0 0 0.4"><freejoint/><geom name="ball" class="ball" type="sphere" size="{R}" mass="0.62"/></body>
</worldbody>
<actuator>{''.join(f'<velocity joint="p{a}" kv="60" forcerange="-120 120"/>' for a in 'xyz')}</actuator>
<contact>{FLOOR_PAIR}{pair}</contact></mujoco>"""


def impact(m) -> tuple[float, float]:
    """Ball rising at 3 m/s into a palm held still: contact time (ms) and exit/entry speed ratio."""
    d = mujoco.MjData(m)
    d.qpos[3:6] = (0, 0, 0.95 - 0.015 - R - 0.01); d.qvel[3:6] = (0, 0, 3.0)
    t_on = t_off = None
    for i in range(400):
        d.ctrl[:] = (0, 0, 0)
        mujoco.mj_step(m, d)
        touching = any({m.geom(c.geom1).name, m.geom(c.geom2).name} == {"ball", "palm"} for c in d.contact[:d.ncon])
        if touching and t_on is None: t_on = i
        if t_on is not None and not touching and t_off is None: t_off = i; break
    return ((t_off or i) - (t_on or 0)) * 2.0, abs(d.qvel[5]) / 3.0


def dribble(m, seed: int, seconds: float = 45.0, slop: float = 1.0) -> dict:
    """Scripted hand: wait at hold height, ride the rising ball, push down, return. Noisy sensing/actuation."""
    rng = np.random.default_rng(seed)
    d = mujoco.MjData(m)
    d.qpos[3:6] = (rng.uniform(-.03, .03), rng.uniform(-.03, .03), rng.uniform(0.3, 0.75))
    H, mode, vpush, z_push = 0.95, "return", 2.0, 0.95
    chain = best = bounces = 0
    apex, prev_vz, lost = 0.0, 0.0, False
    for step in range(int(seconds / 0.002)):
        b, bv, p = d.qpos[3:6], d.qvel[3:6], d.qpos[0:3] + (0, 0, 0.95)   # slide qpos is an offset from the body pos
        if step % CTRL_EVERY == 0:
            bn = b + rng.normal(0, 0.01 * slop, 3); bvn = bv + rng.normal(0, 0.05 * slop, 3)
            top, bottom = bn[2] + R, p[2] - 0.015
            if mode == "wait" and bvn[2] > 0 and top > bottom - 0.03: mode = "ride"
            elif mode == "ride" and bvn[2] < 0.3: mode, z_push = "push", p[2]
            elif mode == "push" and (p[2] < z_push - 0.25 or bvn[2] < -vpush): mode = "return"
            elif mode == "return" and bvn[2] > 0 and bn[2] < 0.4: mode = "wait"
            reach = min(H, bn[2] + max(bvn[2], 0) ** 2 / 19.62 + R + 0.015 - 0.04)  # meet the ball just before its apex
            vz = {"wait": 4 * (reach - p[2]), "ride": 0.8 * max(bvn[2], 0), "push": -vpush, "return": 4 * (H - p[2])}[mode]
            d.ctrl[:] = (6 * (bn[0] - p[0]), 6 * (bn[1] - p[1]), vz) + rng.normal(0, 0.1 * slop, 3)
        mujoco.mj_step(m, d)
        apex = max(apex, b[2])
        if prev_vz < 0 <= bv[2] and b[2] < R + 0.02:      # floor bounce: score the previous apex
            bounces += 1
            ok = APEX_BAND[0] <= apex <= APEX_BAND[1]
            chain = chain + 1 if ok else 0
            best = max(best, chain)
            if bounces > 1: vpush = float(np.clip(vpush + 2.0 * (APEX_TARGET - apex), 0.5, 5.0))   # human-like correction
            apex = 0.0
        prev_vz = bv[2]
        if math.hypot(b[0] - p[0], b[1] - p[1]) > 0.35 or b[2] > 1.5:
            lost = True; break
    return {"best_chain": best, "bounces": bounces, "lost": lost}


if __name__ == "__main__":
    SLOPS = (1, 2, 4)     # x sensing/actuation noise: 1 = careful scripted hand, 4 = sloppy (early RL-like) hand
    print(f"{'variant':14s} | impact ms | exit/entry | " + " | ".join(f"50-chain @slop{k} (median, lost)" for k in SLOPS))
    for name, (half, pair) in VARIANTS.items():
        m = mujoco.MjModel.from_xml_string(xml(half, pair))
        ms, ratio = impact(m)
        cells = []
        for k in SLOPS:
            runs = [dribble(m, s, slop=k) for s in range(20)]
            ch = [r["best_chain"] for r in runs]
            cells.append(f"{np.mean([c >= 50 for c in ch]):4.0%} ({np.median(ch):3.0f}, {np.mean([r['lost'] for r in runs]):3.0%})".ljust(30))
        print(f"{name:14s} | {ms:9.0f} | {ratio:10.2f} | " + " | ".join(cells), flush=True)
