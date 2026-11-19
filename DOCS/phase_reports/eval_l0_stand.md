# Evaluation — l0_stand: PASS

Checkpoint `runs\production\balance_quiet.pt`, 200 randomised episodes, deterministic policy, pushes up to 100 N x scale 1.0.

| Metric | Value |
|---|---|
| Success rate | 97.0 % (need >= 95 %) |
| Holds for 100 straight episodes | yes |
| NaN-gradient batches in training | 0 (must be 0) |
| Fall rate | 1.0 % |
| Mean episode length | 59.3 s of 60 s |
| Failed: fell | 1.0 % |
| Failed: feet_moved_35cm | 2.0 % |
| Failed: stance_over_20cm | 2.5 % |
| Failed: quiet_speed | 1.0 % |
| Failed: quiet_jitter | 1.0 % |
| Failed: ended_early | 2.5 % |
| Failed: failed_without_falling | 2.0 % |
| sway_cm | 4.787 |
| quiet_sway_cm | 4.328 |
| quiet_speed_cm_s | 1.351 |
| quiet_jitter_cm | 0.636 |
| foot_drift_cm | 5.835 |
| upright | 0.999 |
| torso_upright | 0.903 |
