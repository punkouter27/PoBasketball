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

## v2 retrain: balance + locomotion warm-started from v1 (user-approved)

User decisions: (1) warm-start from the graduated 27-DoF brains instead of training from scratch; (2) budget L0 + L1 (~3 h).
Why: the v2 `balance_preview` (`l0_v2_toe_upright`) was trained only 12.1 M steps and fails L0 (0.5 % success, 34.5 % falls);
the v1 balance lineage needed several runs and 150 M+ steps from scratch.

Audit trail (before changes)
- Policies affected: `balance` (L0), `locomotion` (L1) — new v2 weights. `dribble`, `scramble`, `shot` untouched (still v1-only).
- State-machine rows: none (`shared/transition_table.json` unchanged). Interface: none (obs_spec v2 `32f5b79d3216e8a3` unchanged).
- Method (UU_AGENT §3 zero-init rule): new tool `sim/tools/widen_v1_to_v2.py` copies every v1 weight to the slot carrying the
  same quantity in v2; first-layer columns for the 6 new toe inputs and last-layer rows for the 2 toe actions are zero
  (action 0 = nominal toe = flat foot); toe normaliser stats borrowed from the same side's ankle_pitch. Checked against the v1
  ONNX on 1000 random observations before writing. The isolation rule is respected: same character (grandma), same body
  except the two toe hinges.
- `sim/tools/onnx_to_ckpt.py`: `rebuild()` takes optional `n_obs` / `n_act` (defaults unchanged).
- Environment: `sim/.venv` was a partial copy (no python.exe / pyvenv.cfg); moved to `.venv_broken_20261118`, rebuilt with
  `uv sync`. This machine has an RTX 2060 (6 GB, sm_75), not the sm_120 card in `env_setup.md`; throughput re-measured below.

### Baseline and two failed fine-tune attempts

- Widened v1 balance (`runs/production/balance_v1w.pt`), **no training**, on the v2 body (200 ep, 100 N):
  **99.0 % success, holds 100 straight, 0.5 % falls**, quiet speed 1.3 cm/s, jitter 0.59 cm, foot drift 4.8 cm,
  torso_upright 0.875 (the v2 posture reward #6 is what the fine-tune is for). Throughput on the RTX 2060: ~16 k steps/s.
- `l0_v2w_ft1` (actor-only init, std 0.2, lr 1e-4 adaptive): return peaked then collapsed (626 -> 266 by it 39),
  KL spikes 0.15-0.18 with 40-54 % clipping, jitter 0.85 -> 6.3 cm. Stopped.
- `l0_v2w_ft2` (+60-iteration critic warm-up, lr ceiling 1e-4, KL target 0.005): KL was still 0.13 in critic-only
  iterations and jitter reached 11 cm. **Root cause: the observation normaliser keeps updating from rollouts**; the import
  sets count 1e6, so ~10 iterations (1 M samples) halve the weight of the v1 stats the weights were trained under, changing
  the policy with no gradient step. Stopped.
- Both failed run directories were deleted by mistake (AGENTS §4 says keep runs < 24 h old); the numbers above are the record.

Trainer changes (`sim/streetball/ppo.py`, `train.py`; defaults leave existing behaviour unchanged):
`--critic-warmup-iters N` (value loss only, actor/log_std/adaptive LR frozen), `--kl-target`, `--lr-max` (adaptive-LR
ceiling; LR is clamped to it when the actor unfreezes), `--freeze-norm` (observation normaliser fixed).

- `l0_v2w_ft3` (= ft2 + `--freeze-norm`, std 0.15, 40 min): KL exactly 0.0 through warm-up, metrics stable. Running.
- `l0_v2w_ft3` result (40 min, 38.9 M steps, 0 NaN): the posture improved and balance collapsed. Deterministic eval, 200 ep:
  | Checkpoint | Success | Falls | Quiet speed | Jitter | Drift | Torso upright |
  |---|---|---|---|---|---|---|
  | widened v1, no training | **99.0 %** | 0.5 % | 1.3 | 0.59 | 4.8 | 0.875 |
  | ft3 `ckpt_25M` | 25.0 % | 69 % | 4.9 | 1.92 | 8.3 | 0.947 |
  | ft3 `best` | 30.0 % | 44 % | 7.9 | 3.07 | 8.0 | 0.918 |
  | ft3 `model` | 1.0 % | 70.5 % | 10.7 | 3.68 | 7.4 | 0.885 |
  Reading: v1 recovers from shoves partly by hinging at the waist; the v2 torso term penalises exactly that, and at
  lr <= 1e-4 for 39 M steps the policy did not find another recovery. Fine-tuning with the full v2 reward is not viable.

### User decision (step 1-3): ship the widened brains; skip the L1 fine-tune; posture curriculum overnight

Production v2 policies (exported from `runs/production/{balance,locomotion}_v1w.pt`, now tagged interface
`32f5b79d3216e8a3`, physics `319cd05af6f00d17+c1c2207912c56781`):
| Family | Level | Eval (200 ep) | Holds 100 | Falls | ORT vs torch |
|---|---|---|---|---|---|
| `balance` | l0_stand (100 N) | **99.0 %** (gate 95 %) | yes | 0.5 % | 1.04e-6 |
| `locomotion` | l1_traverse (150 N) | **93.0 % / 96.0 %** in two runs, same seed (Warp is not bit-exact; gate 90 %; v1 on v1 body 97.0 %) | yes | 4.0 % / 2.0 % | 1.62e-6 |

Gates and regressions
- `tools/run_gate.py --level l0_stand`: eval, export, policy replay PASS; its Unreal stage failed to start (see below).
- Golden replays re-recorded on v2: `replay_balance`, `replay_locomotion`, `replay_l0_stand`, `replay_l0`.
  Still stale (27-DoF): `replay_locomotion_ppo` (a v1-only PPO-vs-AMP comparison policy; no v2 counterpart, stays skipped).
- Unreal: `Streetball.*` **22 / 22 pass** with the defaults (production `balance.onnx` + `replay_balance.json`, no skips):
  closed loop 0.0000 cm / 0.00001 deg, lowest pelvis 0.929 m, NNE inference 0.049 ms; open loop 0.0000 cm / 0.00000 deg.
- Python: 13 / 14; `test_warp_vs_cpu_drift` fails as before (Warp world-to-world 3.7e-1 vs 1e-3, open since this morning).
- Environment fixes found on the way: `unreal/StreetballGym/Binaries` was missing (module never loaded, suite exited
  without running a test) -> rebuilt `StreetballGymEditor` (162 s); `Saved/Logs` missing made `run_headless.ps1` fail
  to start -> the script now creates the log folder.
- `dribble`, `scramble`, `shot` remain v1-only (dummy fallback in Unreal), unchanged.

Posture curriculum (step 3), tools only (defaults unchanged):
- `l0_stand.py`: `posture_ramp` blends the posture term from v1 (`1.0 * r_upright`) to v2 (`1.5 * r_torso_upright`);
  `train.py --posture-ramp-steps` ramps it after the critic warm-up and logs `posture_alpha`.
- `tools/posture_overnight.py`: trains from the production balance brain, evaluates every 25 M checkpoint into the run
  folder (production eval reports kept intact), picks the straightest-torso checkpoint that still passes, writes
  `DOCS/<date>/posture_overnight.md`. It never exports; promotion is a reviewed `run_gate.py` run.
