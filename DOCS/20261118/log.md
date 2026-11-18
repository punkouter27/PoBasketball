# 2026-11-18

## humanoid_v2 regression fix (Unreal tests)

After `7db8307` (29-DoF humanoid_v2, nq 43 / nv 41 / nu 29, N_OBS 125) the `Streetball` automation suite ran 15 of 22:
`C3.WorldLoop` failed and `Gate.PresetActions` crashed the editor ("index 41 into an array of size 41").

Root cause
- `Gate.PresetActions` loads the default replay `shared/golden/replay_balance.json`, still recorded on the 27-DoF body
  (nq 41). The `nq` check was a non-fatal `TestEqual`, so `CompareQ` indexed every 41-value qpos row with the new
  model's qpos addresses (up to 42) and went out of bounds.
- `C3.WorldLoop` hard-coded the old action size and prev_action slot (`27`, `63`); v2 is 29 at slot 67.
- `LearningAgents.ModelAndReset` (never reached) had the same problem: the Chaos import stopped at body `foot_r`, so
  `toe_r` was missing (28 of 29 joints), and `Observe` / the test hard-coded 15 bodies, 119 obs and old slots.
- `Gate.LivePhysics` hard-coded foot-contact slots 99/100 (now 105/106).

Fix (no contract change, no policy or state-machine row affected)
- `ObsBuilder.h`: public slot offsets derived from `NumJoints`; `Initialize` checks them and `n_obs` against `obs_spec.json`.
- Gate tests: replay dimensions (nq, nv, nu, every ctrl/qpos/qvel/obs/action row) are validated against the loaded
  model; a replay from another body is SKIPPED with a warning and the gate report says to re-record it.
- WorldLoop, LearningAgents comparison and its test: sizes, body counts and slots from the model / `FObsBuilder`;
  toes map to mannequin `ball_l` / `ball_r` (as `humanoid_spec.json` body_bone_map) and count as foot contact.

Results: 22 / 22 run and pass. With the matched v2 pair (`-GateReplay=golden/replay_balance_preview.json
-GatePolicy=policies/balance_preview.onnx`) the gates pass for real: open loop 0.0000 cm / 0.00000 deg, closed loop
0.0001 cm / 0.00025 deg, obs diff 8.1e-6. With the defaults they skip (stale `replay_balance.json`, no v2 `balance.onnx`).

Still open
- 5 golden replays (`balance`, `l0`, `l0_stand`, `locomotion`, `locomotion_ppo`) are 27-DoF policy recordings; they need
  v2 policies (GPU training) before `sim/tools/replay_recorder.py policy` can re-record them. `web/build.py` skips them.
- `test_warp_vs_cpu_drift`: the Warp world-to-world gate (1e-3) fails on the v2 body. Contact/constraint buffers do not
  overflow (peak 104 of 384 contacts, 78 of 160 efc rows); divergence varies 3.5e-2 to 4.6e-1 run to run while Warp
  reports the line-search iteration limit. Unrelated to the Unreal crash; needs a solver-settings look.
