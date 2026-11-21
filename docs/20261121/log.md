# 2026-11-21

## 08:10 Unreal preview of the new dribble brain (user: "play unreal with new brains")

PREVIEW export, gate NOT passed (l2a_dribble_r 71 % < 85 %), same as the 11-20 10:45 preview. Affected policy: dribble only
(director falls back to it in tier 3 / 4 dribble states). Interface unchanged (32f5b79d layout).
- Previous preview kept for side-by-side: `shared/policies/dribble.onnx` -> `dribble_drift250.onnx` (+ sidecar);
  compare with `-StreetballPolicy_dribble=policies/dribble_drift250.onnx`.
- `runs/dribble_time10d/ckpt_600M.pt` -> `shared/policies/dribble.onnx` (+ sidecar), synced to Content/Sim/policies.
