# L0 posture curriculum overnight (l0_v2w_posture_0900)

Train 515.0 min from `runs/production/balance_v1w.pt`, posture blend v1->v2 over 300 M steps after a 60-iteration critic warm-up; normaliser frozen. Gate: >= 95 % success, holds 100 straight, 0 NaN.

Baseline (widened v1, production): success 99.0%, falls 0.5%, torso_upright 0.875

| Checkpoint | Success | Holds 100 | Falls | Torso upright | Jitter cm | Speed cm/s | Drift cm |
|---|---|---|---|---|---|---|---|
| ckpt_25M.pt | 75.5% | no | 23.5% | 0.867 | 0.98 | 2.00 | 5.3 |
| ckpt_50M.pt | 36.5% | no | 62.0% | 0.831 | 2.39 | 6.41 | 6.2 |
| ckpt_75M.pt | 88.5% | no | 10.0% | 0.819 | 0.77 | 1.85 | 8.3 |
| ckpt_100M.pt | 76.5% | no | 5.0% | 0.832 | 0.89 | 2.50 | 12.8 |
| ckpt_125M.pt | 69.5% | no | 12.5% | 0.840 | 1.19 | 3.62 | 12.9 |
| ckpt_150M.pt | 80.0% | no | 5.0% | 0.826 | 0.93 | 3.19 | 10.5 |
| ckpt_175M.pt | 72.5% | no | 9.5% | 0.825 | 0.84 | 2.27 | 11.4 |
| ckpt_200M.pt | 62.0% | no | 21.5% | 0.863 | 1.09 | 2.89 | 10.7 |
| ckpt_225M.pt | 68.5% | no | 18.5% | 0.890 | 0.83 | 2.16 | 10.1 |
| ckpt_250M.pt | 75.5% | no | 9.5% | 0.886 | 0.77 | 1.88 | 9.9 |
| ckpt_275M.pt | 71.5% | no | 13.0% | 0.913 | 0.70 | 1.63 | 10.5 |
| ckpt_300M.pt | 65.0% | no | 24.0% | 0.931 | 0.79 | 1.81 | 10.5 |
| ckpt_325M.pt | 38.0% | no | 40.5% | 0.940 | 1.09 | 2.63 | 11.0 |
| ckpt_350M.pt | 61.0% | no | 22.0% | 0.962 | 0.83 | 1.65 | 10.1 |
| ckpt_375M.pt | 81.5% | no | 10.0% | 0.978 | 0.74 | 1.47 | 9.0 |
| ckpt_400M.pt | 78.5% | no | 18.0% | 0.980 | 0.89 | 2.05 | 9.0 |
| ckpt_425M.pt | 71.0% | no | 18.5% | 0.971 | 0.90 | 1.92 | 9.2 |
| ckpt_450M.pt | 59.0% | no | 30.0% | 0.969 | 0.84 | 1.67 | 9.1 |
| ckpt_475M.pt | 50.5% | no | 37.5% | 0.967 | 0.88 | 1.72 | 9.5 |
| ckpt_500M.pt | 47.0% | no | 44.0% | 0.971 | 0.84 | 1.61 | 8.6 |
| ckpt_525M.pt | 52.0% | no | 42.0% | 0.971 | 0.75 | 1.53 | 8.2 |
| ckpt_550M.pt | 56.0% | no | 37.0% | 0.968 | 0.84 | 1.78 | 8.0 |
| ckpt_575M.pt | 59.0% | no | 32.5% | 0.968 | 0.85 | 1.81 | 8.4 |
| best.pt | 78.0% | no | 20.0% | 0.981 | 0.85 | 1.92 | 8.7 |
| model.pt | 61.5% | no | 31.5% | 0.966 | 0.89 | 2.00 | 8.5 |

**No checkpoint passed the gate.** Production balance stays the widened v1 brain.
