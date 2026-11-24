# 2026-11-24: feature upgrades (RL shaping, symmetry, get-up level, presentation)

Owner decisions for this batch (asked before implementation, UU_AGENT §5):

- RL items land as **code with every new weight at 0** (or the feature off by default). Shipped policies in
  `shared/policies/` are **not retrained** and behave exactly as before; no gate is re-run because no policy changes.
- **No gait-phase clock**: the observation contract (`shared/obs_spec.json`, PhaseA hashes) stays frozen. Swing timing
  is shaped by a reward term that needs no new inputs.
- Assets behind sign-ins (Fab Megascans, MetaHuman, Audio2Face, NVIDIA ACE) are fetched with the owner signed in.

## Audit trail (written before the changes)

| Area | Change | Affected policies | Interface revision |
|---|---|---|---|
| `shared/reward_config.json` | new penalty terms `power_abs`, `com_offset`, `com_vel_z_sq`, `ang_vel_xy_sq`, `short_swing`, all weight 0 | none (weight 0; shipped policies not retrained) | reward config gains 5 keys; obs/action unchanged |
| `UStreetballRewardConfig` | 5 matching float properties, default 0 | none | DataAsset gains 5 fields |
| `sim/streetball/mirror.py` | left/right mirror of obs and actions, derived from the MJCF joint axes | none | none (read-only use of the obs layout) |
| `sim/streetball/ppo.py` | optional symmetry loss `sym_coef` (default 0) | none | none |
| `RandomizationConfig.motor_kd` | separate kd range, default (1, 1) = off | none | none |
| `levels/l5_getup.py` | new get-up level, reset from recorded real falls | new skill family, untrained; no director row until a policy passes its gate | none (same obs/action layout) |
| curriculum | `l5_getup` gate 0.80 | none | Unreal `AddStage` list gains one row |

## Result (same day)

- Mirror check: obs of a physically mirrored state equals the mirrored obs to < 1e-5 over 20 random poses
  (`sim/tests/test_mirror.py`). Joints that flip sign: wrist_dev_l/r, ankle_roll_l/r, lumbar_lat, lumbar_twist.
- Fall bank: `sim/data/fall_states.npz`, 512 falls from 547 pushes (shipped `l0_stand.onnx`), pelvis 0.11–0.36 m.
- `l5_getup` and `--sym-coef` / `--motor-kd` smoke-trained 3 iterations each on 256 worlds (runs deleted: < 5,000
  steps). `interface_sha` unchanged (`9879b4bebba21aa3` before and after).
- Python: ruff clean, 34 tests pass (GPU included). Unreal: editor target builds; `DA_RewardConfig` re-synced from the
  JSON by the new `Scripts/sync_reward_config_asset.py`; `Streetball.Showcase.*` 4/4 pass.

## Presentation items already present before this batch (no change needed)

Substrate (`r.Substrate=True`, layered court/ball/rim/skin materials), contact-driven MetaSounds (`Impact` input from
`FContactAudioProcessor`), contact-driven pooled Niagara bursts (`CourtFX`), PCG neighbourhood with litter, weeds,
cracks and puddles (`build_environment.py`, `M_CourtAsphalt`), Groom hair and Chaos Cloth hem (2026-11-17).

## Time of day (presentation only; no policy, director row or interface affected)

`UCourtTimeOfDaySubsystem`: sun → moon, sky light scale, 4 streetlight spot lights (one per PCG `SM_StreetLight`
instance; the PCG ring at 17 m spacing yields 4, not 17), night exposure volume. Start hour reproduces the level's sun:
before vs after mean pixel difference 1.7/255 over the court. MegaLights tried and reverted (on-screen warning without
hardware ray tracing). Report: `SCREENSHOTS/20261124_time_of_day/index.html`. `Streetball.Showcase.*` 5/5 pass.
