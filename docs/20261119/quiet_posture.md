# L0 posture curriculum overnight (l0_quiet_posture)

Train 40.0 min from `runs/production/balance_v1w.pt`, posture blend v1->v2 over 0 M steps after a 60-iteration critic warm-up; normaliser frozen. Gate: >= 95 % success, holds 100 straight, 0 NaN.

Baseline (widened v1, production): success 99.0%, falls 0.5%, torso_upright 0.875

| Checkpoint | Success | Holds 100 | Falls | Torso upright | Jitter cm | Speed cm/s | Drift cm |
|---|---|---|---|---|---|---|---|
| ckpt_5M.pt | 99.0% | yes | 0.5% | 0.875 | 0.59 | 1.32 | 4.8 |
| ckpt_10M.pt | 99.0% | yes | 0.5% | 0.873 | 0.59 | 1.33 | 4.7 |
| ckpt_15M.pt | 99.0% | yes | 0.5% | 0.885 | 0.60 | 1.31 | 4.9 |
| ckpt_20M.pt | 97.0% | no | 1.0% | 0.888 | 0.61 | 1.32 | 5.3 |
| ckpt_25M.pt | 97.0% | yes | 1.0% | 0.903 | 0.64 | 1.35 | 5.8 |
| ckpt_30M.pt | 97.0% | no | 1.5% | 0.908 | 0.66 | 1.35 | 5.8 |
| ckpt_35M.pt | 96.5% | no | 1.0% | 0.908 | 0.66 | 1.35 | 5.9 |
| ckpt_40M.pt | 95.0% | no | 1.5% | 0.907 | 0.65 | 1.34 | 6.0 |
| ckpt_45M.pt | 94.0% | no | 1.5% | 0.904 | 0.66 | 1.35 | 6.2 |
| best.pt | 99.5% | yes | 0.5% | 0.886 | 0.60 | 1.33 | 4.8 |
| model.pt | 93.0% | no | 0.5% | 0.897 | 0.67 | 1.36 | 6.5 |

**Pick:** `ckpt_25M.pt` (torso 0.903 vs baseline 0.875). Better than production: review, then export with run_gate.
