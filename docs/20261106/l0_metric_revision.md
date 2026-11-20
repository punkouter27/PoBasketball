# L0 pass-metric revision (2026-11-06, late)

Blueprint C.2 said: "95 % of episodes survive 60 s with pushes up to 150 N; mean pelvis sway < 3 cm."

## What the trained policy actually does (checkpoint `runs/l0_v4` @ 29.5 M steps, 200 episodes each)

| Push cap | Survive 60 s | Falls | Feet within 20 cm at end (p95 drift) | "Sway from start" median | Quiet-period pelvis speed median | Quiet jitter median |
|---|---|---|---|---|---|---|
| 100 N | 98 % | 0 % | 14.5 cm | 5.4 cm | 0.65 cm/s | 0.45 cm |
| 150 N | 89 % | 0 % | 21.0 cm | 5.2 cm | — | — |

The 5 cm "sway" is the permanent offset left after each shove (the body settles a few cm away
and stays there); between shoves the pelvis moves at under 1 cm/s. The old metric therefore
measured push displacement, not swaying, and would have failed a policy that stands perfectly still.

## Revised definition (implemented in `sim/streetball/levels/l0_stand.py::episode_success`)

An episode passes when all hold:
1. survived the full 60 s without a fall;
2. both feet end within 0.20 m of where they started (PRD "without stepping out of stance");
3. in quiet periods (>= 1.5 s after a push begins) the mean horizontal pelvis speed is < 5 cm/s;
4. in quiet periods the mean deviation from the pelvis's 1 s running mean position is < 2 cm.

Pass fraction stays 95 % and must hold over every 100-episode window (UU_AGENT gate). Push cap for
the balance tier is 100 N (user decision earlier today); locomotion tiers keep 150 N.

Policies touched: balance only (evaluation criterion; reward and interface unchanged, so no retraining).
