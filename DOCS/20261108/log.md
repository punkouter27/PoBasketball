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
