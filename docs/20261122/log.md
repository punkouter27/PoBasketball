# 2026-11-22 - consistency audit (Po Game Standard v3)

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
