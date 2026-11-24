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

Each weighted term is also kept separately (`Level.penalty_terms`) and reported per step as `info["m/pen_<term>"]`, so
`train.py` logs `m/pen_torque_sq`, `m/pen_joint_ang_vel_sq`, `m/pen_action_rate_sq` and `m/pen_foot_slip` to TensorBoard
and progress.csv (2026-11-22, logging only: the reward is unchanged). `sim/tests/test_env.py::
test_every_penalty_term_is_charged_and_logged` (GPU) checks all four are charged under random actions.

**Shipped policies were not retrained.** Every policy in `shared/policies/` was trained before the foot-slip term
existed; their behaviour is unchanged (inference only). The term takes effect on the next training run of any level.

## 2026-11-24: shaping terms, symmetry loss, kd randomisation, get-up level (all off by default)

Five more penalty terms, **weight 0** in `shared/reward_config.json` and in the DataAsset (`PowerAbsWeight`,
`ComOffsetWeight`, `ComVelZSqWeight`, `AngVelXYSqWeight`, `ShortSwingWeight`). At weight 0 they are charged exactly 0
and the reward of every level is unchanged; they are still logged (`m/pen_<term>`, all zeros).

| Term | Definition | Raw peak, random actions (256 worlds, 60 steps) | Suggested first weight |
|---|---|---|---|
| `power_abs` | mean over actuators of \|force × velocity\| (W) | 383 | -2e-4 |
| `com_offset` | \|CoM_xy − support centre_xy\|² (m²) | 2.0 | -0.5 |
| `com_vel_z_sq` | vertical CoM speed² | 0.04 | -1.0 |
| `ang_vel_xy_sq` | pelvis roll/pitch rate² (rad/s)² | 126 | -0.05 |
| `short_swing` | at touchdown, max(0, 0.35 s − swing time), summed over feet | 0.66 | -1.0 (locomotion levels only) |

The suggested weights are starting points for a trial run, not tuned values.

- **Symmetry loss**: `train.py --sym-coef 1.0` adds `sym_coef · mean‖μ(M_o·o) − M_a·μ(o)‖²` to the PPO loss
  (logged as `loss/symmetry`). The left/right mirror (`sim/streetball/mirror.py`) is derived from the MJCF joint axes and
  checked against the physics (`tests/test_mirror.py`: the obs of a mirrored state equals the mirrored obs to 1e-4).
  Only levels that declare `Level.task_mirror()` allow it: `l0_stand` (empty task block) and `l1_traverse` /
  `l1_traverse_amp`. One-handed dribble, crossover, scramble and shot levels are not mirror-symmetric and refuse it.
- **kd randomisation**: `--motor-kd 0.8 1.2` scales actuator damping separately from kp. Default `1 1` draws no random
  number, so existing runs keep their random stream.
- **Get-up level `l5_getup`** (gate 0.80): episodes start from `sim/data/fall_states.npz`, real falls recorded by
  `sim/tools/record_fall_states.py` (the shipped `l0_stand` policy knocked over by 250–600 N pushes, saved 0.3–1.5 s
  after the fall). Falling does not end its episodes (`Level.terminate_on_fall = False`). Pass: standing (pelvis
  ≥ 90 % of nominal height, torso upright, both feet down) for 1 s. Untrained; no director row until a policy passes.

**No gait-phase clock**: it would add observation inputs, and the obs contract stays frozen (owner decision,
2026-11-24). `short_swing` shapes swing timing without new inputs.
