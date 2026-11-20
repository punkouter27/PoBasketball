# Reward penalties and curriculum gates (2026-11-20)

One source: `shared/reward_config.json`. The trainer reads it through `sim/streetball/reward_config.py`
(`Level.penalties()` and `Level.pass_fraction`); the Unreal DataAsset `UStreetballRewardConfig` mirrors the same values so
they can be inspected and tuned in the editor. `sim/tests/test_reward_config.py` checks that the trainer uses the file.

| Term | Weight | Definition |
|---|---|---|
| `torque_sq` | -1e-5 | mean over actuators of actuator force² |
| `joint_ang_vel_sq` | -0.001 (l0_stand: -0.002) | mean over hinge joints of joint velocity² |
| `action_rate_sq` | -0.05 | mean of (a_t − a_{t−1})² |
| `foot_slip` | -0.1 | Σ feet contact × planar foot speed² (new) |

Unchanged from before except `foot_slip`, which is new. `l4_jump_shot` keeps its post-release penalty set (torque,
action rate, foot slip; no joint-velocity term), and every level keeps its action-jerk term (not one of the four).

Curriculum gates (eval success rate a level must hold before its policy is promoted): l0_stand 0.95, l1_traverse 0.90,
l2a_dribble_r 0.85, l2c_crossover 0.80, l3a_moving_dribble 0.75, l3b_scramble 0.80, l4_jump_shot 0.30. Level variants
(l2b_dribble_l, l2a_cycles, l1_traverse_amp, …) use their parent level's gate, as before.

**Shipped policies were not retrained.** Every policy in `shared/policies/` was trained before the foot-slip term
existed; their behaviour is unchanged (inference only). The term takes effect on the next training run of any level.
