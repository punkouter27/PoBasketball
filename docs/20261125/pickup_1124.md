# pickup_1124: l3c_pickup -> gate l3c_pickup

Train 150.0 min, extra `--init runs/production/scramble.pt --init-actor-only --freeze-norm --init-std 0.3 --sym-coef 0.1`. Every checkpoint evaluated on `l3c_pickup` (200 episodes).

| Checkpoint | Success | Holds 100 | Falls | Episode s | both_palms | held | lift | pen_action_rate_sq | pen_ang_vel_xy_sq | pen_com_offset | pen_com_vel_z_sq | pen_foot_slip | pen_joint_ang_vel_sq | pen_power_abs | pen_short_swing | pen_torque_sq | reach_both | success |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ckpt_50M.pt | 0.0% | no | 0.0% | 8.0 | 0.000 | 0.000 | 0.000 | -0.000 | -0.005 | -0.028 | 0.000 | -0.003 | -0.002 | 0.000 | 0.000 | -0.009 | 0.000 | 0.000 |
| ckpt_100M.pt | 0.0% | no | 1.5% | 7.9 | 0.000 | 0.000 | 0.000 | -0.000 | -0.002 | -0.026 | 0.000 | -0.003 | -0.001 | 0.000 | 0.000 | -0.004 | 0.000 | 0.000 |
| ckpt_150M.pt | 0.0% | no | 0.5% | 8.0 | 0.000 | 0.000 | 0.000 | -0.000 | -0.001 | -0.026 | 0.000 | -0.002 | -0.001 | 0.000 | 0.000 | -0.003 | 0.000 | 0.000 |
| best.pt | 0.0% | no | 0.0% | 8.0 | 0.000 | 0.000 | 0.000 | -0.000 | -0.001 | -0.025 | 0.000 | -0.001 | -0.000 | 0.000 | 0.000 | -0.003 | 0.000 | 0.000 |
| model.pt | 0.0% | no | 0.0% | 8.0 | 0.000 | 0.000 | 0.000 | -0.000 | -0.001 | -0.026 | 0.000 | -0.001 | -0.000 | 0.000 | 0.000 | -0.003 | 0.000 | 0.000 |

Failure reasons (share of all episodes, not exclusive):

| Checkpoint | ball_got_away | failed_without_falling | lifted_not_held | never_both_palms | touched_not_lifted |
|---|---|---|---|---|---|
| ckpt_50M.pt | 0.0% | 100.0% | 0.0% | 100.0% | 0.0% |
| ckpt_100M.pt | 0.5% | 98.5% | 0.0% | 100.0% | 0.0% |
| ckpt_150M.pt | 0.0% | 99.5% | 0.0% | 100.0% | 0.0% |
| best.pt | 0.0% | 100.0% | 0.0% | 100.0% | 0.0% |
| model.pt | 0.0% | 100.0% | 0.0% | 100.0% | 0.0% |

**Passed the gate:** none.
