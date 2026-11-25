# both_dribble_1124: l2_both_time -> gate l2_both

Train 150.0 min, extra `--init runs/production/dribble_anchor10.pt --init-actor-only --freeze-norm --kl-target 0.02 --epochs 3 --lr-max 1e-4 --lr-min 1e-6 --anchor-coef 0.05 --assist-anneal-steps 1 --init-std 0.1 --sym-coef 0.1`. Every checkpoint evaluated on `l2_both` (200 episodes).

| Checkpoint | Success | Holds 100 | Falls | Episode s | apex | bounces | in_control | palm_touch | pen_action_rate_sq | pen_ang_vel_xy_sq | pen_com_offset | pen_com_vel_z_sq | pen_foot_slip | pen_joint_ang_vel_sq | pen_power_abs | pen_short_swing | pen_torque_sq | reach | streak | switches |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ckpt_50M.pt | 0.0% | no | 4.0% | 2.5 | 0.441 | 2.055 | 0.457 | 0.004 | -0.000 | -0.010 | -0.035 | 0.000 | -0.007 | -0.001 | 0.000 | 0.000 | -0.007 | 0.294 | 0.227 | 0.000 |
| ckpt_100M.pt | 0.0% | no | 1.5% | 3.4 | 0.379 | 3.337 | 0.378 | 0.004 | -0.000 | -0.010 | -0.034 | 0.000 | -0.008 | -0.001 | 0.000 | 0.000 | -0.008 | 0.277 | 0.127 | 0.000 |
| ckpt_150M.pt | 0.0% | no | 1.5% | 3.7 | 0.353 | 3.867 | 0.298 | 0.002 | -0.000 | -0.005 | -0.030 | 0.000 | -0.003 | -0.001 | 0.000 | 0.000 | -0.004 | 0.186 | 0.119 | 0.000 |
| best.pt | 47.5% | no | 0.0% | 15.9 | 0.586 | 13.462 | 0.893 | 0.063 | -0.001 | -0.032 | -0.037 | 0.000 | -0.020 | -0.003 | 0.000 | 0.000 | -0.014 | 0.419 | 11.976 | 0.000 |
| model.pt | 0.0% | no | 1.5% | 4.0 | 0.341 | 4.125 | 0.261 | 0.000 | -0.000 | -0.002 | -0.028 | 0.000 | -0.003 | -0.001 | 0.000 | 0.000 | -0.005 | 0.175 | 0.101 | 0.000 |

Failure reasons (share of all episodes, not exclusive):

| Checkpoint | ball_lost_countdown | ball_over_1_5m | failed_without_falling | fell | out_of_time | pelvis_drifted |
|---|---|---|---|---|---|---|
| ckpt_50M.pt | 4.0% | 22.0% | 96.0% | 4.0% | 0.0% | 72.0% |
| ckpt_100M.pt | 36.0% | 0.0% | 98.5% | 1.5% | 0.0% | 63.5% |
| ckpt_150M.pt | 75.5% | 9.5% | 98.5% | 1.5% | 0.0% | 15.5% |
| best.pt | 0.0% | 0.5% | 52.5% | 0.0% | 1.0% | 51.0% |
| model.pt | 92.5% | 1.0% | 98.5% | 1.5% | 0.0% | 6.0% |

**Passed the gate:** none.
