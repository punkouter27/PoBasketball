# 2026-11-11 — Daily Training Log

## Extended policy optimization — 8-hour unattended run

### Before launch

- Latest available evaluations: dribble policies have not passed; scramble is at 79% success against an 80% gate. Balance and locomotion are already graduated and are excluded from retraining.
- Queue priority: resume `l2a_push` from `sim/runs/l2a_push_n9q2/model.pt`, then `l3b_scramble` from `sim/runs/l3b_scramble_n9q2/model.pt`; revisit each in priority order with the remaining budget.
- Each stage uses 4096 environments, periodic checkpoints, TensorBoard scalars, and the existing 200-episode evaluation gate. Only passing policies may be exported to production.
- The frozen observation and physics contracts are unchanged. This run changes policy weights only.
- Current preflight: PyTorch 2.14.1 imports with CUDA available; MuJoCo Warp imports; GPU has 10.7 GiB free; available system RAM is 5.3 GiB; no Unreal Editor process was found.
- The prior Code Integrity block was resolved in the latest daily log; no recent 3033/3118 block events were found.

The queue writes its machine state and event log under `sim/runs/queue/`, hourly status to this directory, and per-run curves and checkpoints under `sim/runs/`. The run crossed midnight; its final HTML report is in `../20261112/extended_training_report.html`.

## Completion

The eight-hour queue used 7 h 35 min elapsed, retaining the configured 25-minute reserve for finalization. It trained only the urgent dribble and scramble policies; frozen contracts and existing production weights were unchanged.

- `l2a_push_n11q1`: 166.2 M steps, final return 279.24; right-hand dribble gate 0%, failed.
- `l2a_push_n11q2`: 171.0 M steps, final return 477.52; right-hand dribble gate 0%, failed.
- `l3b_scramble_n11q1`: 165.4 M steps, final return 183.67; gate success 74.5%, failed.
- `l3b_scramble_n11q2`: 114.9 M steps, final return 215.56; gate success 81.5%, but failed the 100-consecutive-episode hold requirement.
- All four runs had zero NaN-gradient batches. No new production weights were exported because neither family passed its full gate. Latest checkpoints remain in `sim/runs/production/candidates/`.

The complete report and per-attempt charts are in `../20261112/extended_training_report.html`.
