# 2026-11-21

## 09:00 Unreal preview of the new dribble brain (user: "play unreal with new brains")

PREVIEW export, gate NOT passed (l2a_dribble_r 71 % < 85 %), same as the 11-20 10:45 preview. Affected policy: dribble only
(director falls back to it in tier 3 / 4 dribble states). Interface unchanged (32f5b79d layout).
- Previous preview kept for side-by-side: `shared/policies/dribble.onnx` -> `dribble_drift250.onnx` (+ sidecar);
  compare with `-StreetballPolicy_dribble=policies/dribble_drift250.onnx`.
- `runs/dribble_time10d/ckpt_600M.pt` -> `shared/policies/dribble.onnx` (+ sidecar), synced to Content/Sim/policies.
- Unreal (UE 5.8, `-game -windowed -StreetballStartTier=3 -StreetballMaxTier=3 -StreetballDribbleHand=right`) loads it as
  `dribble` (level l2a_time). First minute: startup dribble held **22.4 s** before the ball went loose (ball-pelvis 0.75 m);
  scramble regained it twice, but each SCRAMBLE -> DRIBBLE hand-over lost it again within 0.1 s (dribble never trained from a
  scramble finish); reset #2 (fallen during scramble) then a loss after 0.94 s; reset #3 by scramble countdown.
  Unreal has no pelvis-drift rule, so drift shows up as the ball drifting > 0.75 m from the pelvis instead.
