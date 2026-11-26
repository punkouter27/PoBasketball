# Evaluation — l1_traverse: PASS

Checkpoint `runs\production\locomotion.pt`, 200 randomised episodes, deterministic policy, pushes up to 150 N x scale 1.0.

| Metric | Value |
|---|---|
| Success rate | 96.0 % (need >= 90 %) |
| Holds for 100 straight episodes | yes |
| NaN-gradient batches in training | 0 (must be 0) |
| Fall rate | 2.0 % |
| Mean episode length | 60.1 s of 90 s |
| waypoints | 4.514 |
| wp_dist | 7.388 |
| speed | 1.865 |
| arm_carry | 0.116 |
| pen_torque_sq | -0.028 |
| pen_joint_ang_vel_sq | -0.004 |
| pen_action_rate_sq | -0.002 |
| pen_foot_slip | -0.195 |
| pen_power_abs | 0.000 |
| pen_com_offset | -0.040 |
| pen_com_vel_z_sq | 0.000 |
| pen_ang_vel_xy_sq | -0.018 |
| pen_short_swing | 0.000 |
