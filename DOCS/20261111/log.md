# 2026-11-11 — Daily Training Log

## Extended policy optimization — 8-hour unattended run

### Before launch

- Latest available evaluations: dribble policies have not passed; scramble is at 79% success against an 80% gate. Balance and locomotion are already graduated and are excluded from retraining.
- Queue priority: resume `l2a_push` from `sim/runs/l2a_push_n9q2/model.pt`, then `l3b_scramble` from `sim/runs/l3b_scramble_n9q2/model.pt`; revisit each in priority order with the remaining budget.
- Each stage uses 4096 environments, periodic checkpoints, TensorBoard scalars, and the existing 200-episode evaluation gate. Only passing policies may be exported to production.
- The frozen observation and physics contracts are unchanged. This run changes policy weights only.
- Current preflight: PyTorch 2.14.1 imports with CUDA available; MuJoCo Warp imports; GPU has 10.7 GiB free; available system RAM is 5.3 GiB; no Unreal Editor process was found.
- The prior Code Integrity block was resolved in the latest daily log; no recent 3033/3118 block events were found.

The queue writes its machine state and event log under `sim/runs/queue/`, hourly status to this directory, per-run reward/loss curves and checkpoints under `sim/runs/`, and the final HTML report here as `extended_training_report.html`.
