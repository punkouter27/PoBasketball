# dribble_45b: l2a_time -> gate l2a_dribble_r

Train 90.0 min, extra `--init runs/dribble_time10d/ckpt_600M.pt --freeze-norm --horizon0 45 --drift-w 4.0 --kl-target 0.02 --epochs 2 --lr-max 2e-5 --lr-min 1e-7 --anchor-coef 1.0 --assist-anneal-steps 1`. Every checkpoint evaluated on `l2a_dribble_r` (200 episodes).

| Checkpoint | Success | Holds 100 | Falls | Episode s | apex | bounces | in_control | palm_touch | reach | streak | switches |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ckpt_25M.pt | 72.5% | no | 0.0% | 29.7 | 0.650 | 23.649 | 0.999 | 0.111 | 0.684 | 21.131 | 0.000 |
| ckpt_50M.pt | 67.5% | no | 0.0% | 29.3 | 0.671 | 23.137 | 0.999 | 0.118 | 0.685 | 19.967 | 0.000 |
| best.pt | 59.5% | no | 1.0% | 28.2 | 0.671 | 22.033 | 0.999 | 0.113 | 0.685 | 19.731 | 0.000 |
| model.pt | 60.5% | no | 0.5% | 28.0 | 0.654 | 21.951 | 1.000 | 0.105 | 0.684 | 19.558 | 0.000 |

Failure reasons (share of all episodes, not exclusive):

| Checkpoint | ball_lost_countdown | ball_over_1_5m | failed_without_falling | fell | out_of_time | pelvis_drifted |
|---|---|---|---|---|---|---|
| ckpt_25M.pt | 0.0% | 0.5% | 27.5% | 0.0% | 2.5% | 24.5% |
| ckpt_50M.pt | 0.0% | 0.0% | 32.5% | 0.0% | 3.5% | 29.0% |
| best.pt | 0.0% | 0.0% | 39.5% | 1.0% | 1.5% | 38.0% |
| model.pt | 0.0% | 0.5% | 39.0% | 0.5% | 2.0% | 36.5% |

**Passed the gate:** none.
