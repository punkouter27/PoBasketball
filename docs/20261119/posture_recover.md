# L0 posture curriculum overnight (l0_posture_recover)

Train 40.0 min from `runs/production/balance_posture.pt`, posture blend v1->v2 over 0 M steps after a 60-iteration critic warm-up; normaliser frozen. Gate: >= 95 % success, holds 100 straight, 0 NaN.

Baseline (widened v1, production): success 99.0%, falls 0.5%, torso_upright 0.875

| Checkpoint | Success | Holds 100 | Falls | Torso upright | Jitter cm | Speed cm/s | Drift cm |
|---|---|---|---|---|---|---|---|
| ckpt_5M.pt | 78.5% | no | 13.0% | 0.978 | 0.76 | 1.50 | 8.9 |
| ckpt_10M.pt | 81.5% | no | 10.0% | 0.980 | 0.75 | 1.49 | 9.0 |
| ckpt_15M.pt | 65.0% | no | 8.0% | 0.967 | 0.93 | 1.90 | 10.8 |
| ckpt_20M.pt | 71.0% | no | 9.5% | 0.972 | 0.83 | 1.68 | 9.8 |
| ckpt_25M.pt | 71.0% | no | 12.0% | 0.970 | 0.79 | 1.61 | 9.8 |
| ckpt_30M.pt | 79.0% | no | 10.5% | 0.975 | 0.72 | 1.43 | 9.1 |
| ckpt_35M.pt | 78.0% | no | 12.5% | 0.974 | 0.75 | 1.51 | 9.4 |
| ckpt_40M.pt | 64.0% | no | 8.0% | 0.965 | 0.90 | 1.86 | 10.7 |
| ckpt_45M.pt | 75.5% | no | 9.0% | 0.974 | 0.78 | 1.59 | 10.0 |
| ckpt_50M.pt | 73.0% | no | 12.5% | 0.977 | 0.80 | 1.61 | 10.1 |
| best.pt | 75.0% | no | 10.0% | 0.970 | 0.78 | 1.58 | 9.6 |
| model.pt | 76.5% | no | 11.5% | 0.979 | 0.83 | 1.70 | 10.2 |

**No checkpoint passed the gate.** Production balance stays the widened v1 brain.
