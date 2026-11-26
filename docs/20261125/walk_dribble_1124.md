# walk_dribble_1124: l3a_walk_both -> gate l3a_walk_both

Train 150.0 min, extra `--init C:\Users\punko\Downloads\_CODEMATT\PoBasketball\sim\runs\both_dribble_1124\best.pt --init-actor-only --freeze-norm --kl-target 0.02 --epochs 3 --lr-max 1e-4 --lr-min 1e-6 --anchor-coef 0.05 --assist-anneal-steps 1 --init-std 0.1 --sym-coef 0.1`. Every checkpoint evaluated on `l3a_walk_both` (200 episodes).

| Checkpoint | Success | Holds 100 | Falls | Episode s | arm_carry | bounces | control_frac | dist_m | pen_action_rate_sq | pen_ang_vel_xy_sq | pen_com_offset | pen_com_vel_z_sq | pen_foot_slip | pen_joint_ang_vel_sq | pen_power_abs | pen_short_swing | pen_torque_sq | speed | speed_cmd | speed_stage | succ_ema | waypoints | wp_dist |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ckpt_50M.pt | 0.0% | no | 100.0% | 2.2 | 0.255 | 1.693 | 0.815 | 0.341 | -0.000 | -0.025 | -0.069 | 0.000 | -0.010 | -0.001 | 0.000 | 0.000 | -0.007 | 0.608 | 0.545 | 0.000 | 0.000 | 0.005 | 3.562 |
| ckpt_100M.pt | 0.0% | no | 73.5% | 3.3 | 0.142 | 3.287 | 0.671 | 0.350 | -0.000 | -0.014 | -0.061 | 0.000 | -0.010 | -0.001 | 0.000 | 0.000 | -0.006 | 0.386 | 0.545 | 0.000 | 0.000 | 0.005 | 3.526 |
| ckpt_150M.pt | 0.0% | no | 3.5% | 4.0 | 0.143 | 4.116 | 0.596 | 0.251 | -0.000 | -0.002 | -0.046 | 0.000 | -0.002 | -0.000 | 0.000 | 0.000 | -0.009 | 0.106 | 0.545 | 0.000 | 0.000 | 0.005 | 3.526 |
| best.pt | 0.0% | no | 5.0% | 4.0 | 0.144 | 4.107 | 0.595 | 0.244 | -0.000 | -0.002 | -0.046 | 0.000 | -0.002 | -0.000 | 0.000 | 0.000 | -0.009 | 0.105 | 0.545 | 0.000 | 0.000 | 0.005 | 3.527 |
| model.pt | 0.0% | no | 2.5% | 4.0 | 0.174 | 4.139 | 0.593 | 0.260 | -0.000 | -0.002 | -0.046 | 0.000 | -0.002 | -0.001 | 0.000 | 0.000 | -0.012 | 0.105 | 0.545 | 0.000 | 0.000 | 0.005 | 3.532 |

**Passed the gate:** none.
