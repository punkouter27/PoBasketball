# 2026-11-22

## Consistency audit (Po Game Standard v3)

Affected: no policy, observation, action or reward value changed; no retraining.

- Content moved through the editor into `/Game/Project/{Agents,Core,DataAssets,Environments,RL_Policies}` (170 assets,
  0 redirectors left, 0 load failures, no dependency on an old path); `Content/Sim` -> `Content/Project/RL_Policies`
  (plain files: MJCF, specs, transition table, git-ignored ONNX copies). `/Game/...` strings updated in `Source/`,
  `Config/`, `Scripts/`, `env_slots.json`; `sim/tools/sync_policies_to_unreal.py` copies to the new folder.
- New DataAssets `DA_RewardConfig`, `DA_ShowcaseConfig` (from the C++ defaults), selected in `Config/DefaultGame.ini`.
- Diagnostics overlay: "Benchmark sim speed [B]" (bounded CPU MuJoCo run, physics steps/s); idle clock ignores frames
  longer than 0.25 s; HUD stacks bottom-left in portrait (9:16) so nothing overlaps.
- Reward: each penalty term logged separately (`m/pen_<term>`); gate tests write their report to `Saved/Reports/`.
- Web: every response carries `X-Commit`; the workflow and `/diag` check it.
- Gaze tracking: not added (no neck joint; bones mirror physics) - owner decision, see AGENTS.md.

## 08:30 `dribble_anchor10` finished: training gate passed, NOT promoted

Affected policy: dribble (stationary, right hand) only. No code, exported policy, state machine row, interface or physics changed.
Report: `dribble_anchor10_report.html` (curves, deltas, verification); every checkpoint: `dribble_anchor10.md`.

- Run: 600 min (11-21 21:24 to 11-22 07:25), 1336.1M steps, exit 0, 0 NaN gradients.
- Gate `l2a_dribble_r` (seed 123, 200 episodes): 54 of 55 checkpoints pass; first pass ckpt_50M 93.5 %. Start brain 68.5 %.
  Previous bests: dribble_time10d 71.0 %, dribble_45b 72.5 %. Drift failures went from 30.5 % to 0-2 % in most later checkpoints.
- Re-test, two unused seeds x 1000 episodes: start brain 67.2 / 67.2 %; `best.pt` (1332.0M steps) 98.7 / 98.6 %, pass;
  `model.pt` and ckpt_850M 98.6 / 98.3 %, pass; ckpt_1175M 96.9 / 97.0 %, fails the 100-in-a-row rule.
  Candidate: `runs/dribble_anchor10/best.pt`.
- CPU MuJoCo, ONNX, 50 starts, no pushes or randomisation: `best.pt` 50/50 on the training court, 15/50 on
  `unreal/StreetballGym/Content/Sim` (stale court.xml). Start brain 49/50 and 2/50.
- 5 s contacts, `best.pt`: load-weighted foot slide 0.110 m/s (start brain 0.103), per-start max foot penetration 7.7 mm on average,
  8.4 contact changes/s over both feet. Not clean under UU_AGENT section 4; the Unreal probe is report-only, no thresholds set.
  Unreal kinematics parity not run.

Open, none applied (each needs approval):
1. Sync `court.xml` into Unreal and add it to `tools/sync_policies_to_unreal.py`.
2. `tools/run_gate.py` does not pass `--level` to `replay_recorder.py` (a dribble gets the standing start).
3. `tools/replay_recorder.py` leaves the dribble anchor inputs (task slots 4-6) at zero.
4. `tools/run_gate.py` exports `l2a_dribble_r.onnx`; the sync copies `dribble.onnx`, so the game would keep the old brain.
5. Decide contact thresholds for the dribble, or train the sliding out.
6. Low priority: in `l2a_time` a 50-bounce success is a non-bootstrapped terminal. It did not prevent a pass.

## Show the new dribble in Unreal (user: "show in unreal"), open items 1 and preview

Affected: dribble preview policy (Unreal tier 3); Unreal physics XML (court only). State machine rows, interface, shot/balance/
locomotion/scramble policies: unchanged. NOT a promotion: no run_gate, no golden replay, the gate bugs (items 2-4) stay open.
- `shared/policies/dribble.onnx` <- `runs/dribble_anchor10/best.pt` (preview, as on 11-21 15:00). The previous preview is kept as
  `shared/policies/dribble_anchor_init.onnx`.
- `unreal/StreetballGym/Content/Sim/court.xml` (now `Content/Project/RL_Policies/court.xml` after the merge) <- `sim/assets/court.xml` (adds the `ball_palm_l` / `ball_palm_r` contact pairs).
- `tools/sync_policies_to_unreal.py` also copies `sim/assets/{scene,humanoid,court}.xml`, so the court cannot go stale again.
- Then: Unreal `Streetball.*` tests, and the game at tier 3 with `-StreetballDribbleHand=right`.
- Result 16:30: export parity 1.6e-6; ruff clean. Unreal tests NOT run: Windows Smart App Control blocked the unsigned
  `Binaries/Win64/UnrealEditor-StreetballGymEditor.dll` (unchanged since 11-17) for UnrealEditor-Cmd (GetLastError 4551, CodeIntegrity
  event 3077). The game (`-game`, seed 7) loads the new `dribble.onnx`: 1 reset (startup) in the first 2 min, a tier-up event at
  30.5 s and the director re-entering DRIBBLE_STATIONARY every ~30 s. On 11-21 the old brain on the old court had 3 resets in 60 s.
