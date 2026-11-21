# walk_1h: l3a_walk -> gate l3a_walk

Train 48.0 min, extra `--init runs/production/dribble_walk_init.pt --init-actor-only --critic-warmup-iters 200 --freeze-norm --init-std 0.05 --kl-target 0.02 --epochs 2 --lr-max 2e-5 --lr-min 1e-7 --anchor-coef 0.3`. Every checkpoint evaluated on `l3a_walk` (200 episodes).

| Checkpoint | Success | Holds 100 | Falls | Episode s | arm_carry | bounces | control_frac | dist_m | speed | speed_cmd | speed_stage | succ_ema | waypoints | wp_dist |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ckpt_25M.pt | 0.0% | no | 69.5% | 21.0 | 0.141 | 15.155 | 0.989 | 3.045 | 0.342 | 0.545 | 0.000 | 0.000 | 0.011 | 3.626 |
| best.pt | 0.0% | no | 66.0% | 20.9 | 0.137 | 15.068 | 0.992 | 3.002 | 0.335 | 0.544 | 0.000 | 0.000 | 0.008 | 3.644 |
| model.pt | 0.0% | no | 95.0% | 2.8 | 0.365 | 2.465 | 0.905 | 0.586 | 0.618 | 0.545 | 0.000 | 0.000 | 0.005 | 3.601 |

**Passed the gate:** none.
