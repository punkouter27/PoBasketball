# 2026-11-08 — daily log

## 02:15 — 8-hour unattended queue `r2`: dribble → scramble → shot (user: "EXTENDED TRAINING (8 hours) ... prioritizing urgent policies")

Urgent policies = the families with no passing gate: **dribble** (L2a/L2b/L2c/L3a), **scramble** (L3b), **shot** (L4).
Balance (100 %) and locomotion (97 %) are graduated and are not trained or exported by this queue.

Policies touched (UU_AGENT §3):
| Change | Kind | Policies |
|---|---|---|
| Dribble family restarted from `runs/production/locomotion.pt` (actor only), not from the foot-juggling `_q1` checkpoints | training init | dribble |
| L3b scramble: ball distance 0.5–2.5 m for the first 50 M training steps, then 0.5–4 m (`Level.train_steps`; evaluation unchanged, always 0.5–4 m) | training reset curriculum | scramble |
| Physics, obs interface, rewards, Unreal | — | none (interface `ccfa18d6f9aaf2a5`, physics `ac1c8d03c1e036df`) |

Tooling: `queue.py` gains `--tag` (run names `<level>_r2q<N>`, never overwrite last night's `_q<N>`), `--init-actor-only`,
and an hourly status grid in `DOCS/20261108/hourly_status.md`. First-pass budgets: L2a 150 min (hand-off asked for ≥150 M steps),
L2b 40, L2c 60, L3a 80, L3b 50, L4 60; leftover time retries the earliest failed stage. Gate unchanged (target held 100 straight
episodes, 0 NaN grads) → export ONNX to `shared/policies/` + `runs/production/` + Unreal.

GPU note: an unrelated app (`Maestro\launch.py`, ~5 GB VRAM, ~40 % util) was already running; throughput will be below last night's.

Command (from `sim/`): `uv run python -m streetball.queue --hours 8 --start-from l2a_dribble_r --init runs/production/locomotion.pt --init-actor-only --tag r2`
Watch: `DOCS/20261108/hourly_status.md`, `sim/runs/queue/<stamp>/queue_log.md`, TensorBoard `--logdir sim/runs` (port 6006).

## 02:48 — r2 stopped at 40 min: L2a was learning to ignore the ball

| L2a metric (r2, from locomotion) | 1 M steps | 70 M steps | needed |
|---|---|---|---|
| apex | 0.71 m | 0.47 m | 0.80–1.15 m |
| in_control | 0.82 | 0.17 | > 0.8 |
| episode | 0.4 s | 3.3 s of 30 s | — |

Diagnostic (256 envs, deterministic, 12 s): palm-ball contact registers (46 % of envs touch at least once; contact buffer peak
900/12,288, no overflow), but the right palm is 0.73 m from the ball on average and touches it in 0.1 % of steps; every episode
ends by losing the ball (717 countdown, 368 rolled away), none by falling. The existing `r_palm` term is ~0 at that distance and
is gated on ball z > 0.5 m while the ball averages 0.43 m, so nothing pulled the hand to the ball.

## 03:05 — dribble reward: reach + touch shaping (training only; pass test and gate unchanged)

Policies touched: **dribble** only (L2a/L2b/L2c share `L2Dribble.reward`). No production dribble policy exists.
- `r_reach` (w 1.0): exp(-(|active palm - (ball + 12 cm up)| / 0.4)^2) while ball z > 0.25 m. Logged `m/reach`.
- `first_touch` (w 2.0): first active-palm touch per bounce cycle (at most one per bounce). Logged `m/palm_touch`.
12-min A/B vs r2 at equal steps (20 M): apex/in_control/episode length unchanged, but `m/reach` 0.05 → 0.11 and rising
(r2 had no such signal). Slow, so L2a gets 240 min first pass in queue r3, resumed from that check run (`runs/l2a_reachcheck`).
Queue r3: `--tag r3 --start-from l2a_dribble_r --init runs/l2a_reachcheck/model.pt --stage-minutes l2a_dribble_r=240 --hours 6.75`.
Run `l2a_dribble_r_r2q1` (70 M steps, pre-shaping) kept for the report comparison.

## 04:40 — r3 stopped at 93 min (≈180 M steps): hand hovers, never touches

| L2a metric (r3) | 0 M | 180 M |
|---|---|---|
| `m/reach` | 0.33 | 0.47 (hand moved toward the ball) |
| `m/palm_touch` (per step) | 0.0012 | 0.0005 |
| apex / in_control / episode | 0.73 m / 0.96 / 0.4 s | 0.46 m / 0.18 / 3.4 s |
Ball contacts by geom (256 envs, 12 s): floor 3.8 %, palm_r 0.09 %, lowerarm_r 0.08 % of env-steps; palm 36 cm above the ball.
Shaping alone cannot fix a touch the policy never experiences → start-state curriculum.

## 04:45 — dribble start-state curriculum "ball in hand" (training only; evaluation never assisted)

Policies touched: **dribble** (L2a/L2b/L2c). `L2Dribble._assist_reset`: in a share of TRAINING resets the ball starts 15 cm under the
active palm site rising at 0.8 m/s (first attempts spawned it overlapping the palm box → ejected; or launched it from 45 cm below →
policy's hand had moved). Share 75 % → 15 % over 150 M steps (`assist_prob`, 0 when `train_steps = inf`, i.e. evaluation).
Check: palm contact in the first 0.5 s for 69.5 % of envs with the locomotion actor (75 % expected).
Queue r4 from `production/locomotion.pt` (actor only), 4.75 h: L2a 150, L2b 30, L2c 35, L3a 45 min first pass.

## 05:20 — r4 stopped at 37 min (65 M steps); dribble parked for a method decision

r4 (ball-in-hand assist) repeated the r2/r3 curve: palm touches 1 % → 0.2 % of steps, in_control 0.82 → 0.19, episode → 3.3 s.
Episode-end analysis with the assist on (512 envs, 15 s): touched episodes last as long as untouched ones (3.63 vs 3.50 s), both
end on the loose-ball countdown (811/830 and 1171/1232). So touching is not punished; the policy never makes a **second** touch
after the ball's first bounce. Rhythm/timing credit assignment, not reach, is the blocker. Three shaping/curriculum attempts in
3.3 h did not move it; the next step is a method choice for the user (see proposal in the final report).

Rest of the window (runner `sim/runs/night_20261108_part2.ps1`, log `night_20261108_part2.txt`):
1. AMP locomotion resume `l1_amp_v3` (40 min from `l1_amp_v2`, 34 M steps) → `l1_traverse` evaluation → `DOCS/20261108/amp_vs_baseline.html`.
   The baseline's `DOCS/phase_reports/eval_l1_traverse.*` is backed up and restored around the AMP evaluation.
2. Queue r5 until 10:00: L2a continued from `l2a_dribble_r_r4q1/model.pt` (assist curriculum restarts at 75 %), then the ladder.

## 06:05 — AMP locomotion `l1_amp_v3` finished (~95 min total, same budget as the baseline) and PASSES the gate

| `l1_traverse` test, 200 episodes | Hand-tuned `l1_v3_armcarry` (production) | AMP `l1_amp_v3` |
|---|---|---|
| Success (10 waypoints, 90 s) | 97.0 % | **97.0 %** |
| Holds 100 straight | yes | **yes** |
| Falls | 2.5 % | 2.0 % |
| Speed | 1.91 m/s | 1.87 m/s |
| Arm-swing symmetry (L/R) | 38 % | **52 %** |
| Arm-carry deviation (lower = more relaxed) | **0.068** | 0.113 |
| Fresh mocap classifier "human" score | 0.0006 | 0.0005 (both fully separable from mocap) |
NaN grads 0. Comparison page: `DOCS/20261108/amp_vs_baseline.html`. Verdict: task-equal, mixed on style.
Exported as a graduated **candidate**, not production: `shared/policies/locomotion_amp.{onnx,json}`, `runs/production/candidates/locomotion_amp.*`,
Unreal `Content/Sim/policies/locomotion_amp.onnx` (ORT vs torch 1.6e-6). Production `locomotion.onnx` unchanged — user decision.
Baseline `DOCS/phase_reports/eval_l1_traverse.*` restored after the AMP evaluation (checked).

## 09:40 — Night window closed: queue r5 results (dribble continuation)
Policies touched: dribble (training only; nothing exported). Locomotion/balance production unchanged.

| Stage | Run | Steps | Success | Falls | Palm touch (end) | In control (end) |
|---|---|---|---|---|---|---|
| L2a dribble R | l2a_dribble_r_r5q1 (150 min, from r4q1) | 248 M | 0 % | 0 % | 0.24 % | 23 % |
| L2b dribble L | l2b_dribble_l_r5q1 (30 min) | 49 M | 0 % | 0 % | 0.19 % | 19 % |
| L2c crossover | l2c_crossover_r5q1 (30 min) | 49 M | 0 % | 0 % | 0.20 % | 18 % |

L3a/L3b/L4 skipped (24 min left < reserve). No NaN gradients. Reward rose (168 → 371) while touch stayed ~0.2 %:
same "stand still, let the ball die" optimum as r2–r4. More time on this reward will not fix it.
Final report: `DOCS/20261108/night_training_report.html` (tools/night_report.py). Open: dribble teaching method
(scripted hand–ball reference recommended) and whether to promote `locomotion_amp` — both await the user.
