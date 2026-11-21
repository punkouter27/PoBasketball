# 2026-11-20 (evening, laptop RTX 5070 Ti)

## 23:15 10 h dribble run `dribble_time10` (user: "do 10 hours training as needed for pobasketball")

Context: the 11-18..11-20 runs (`dribble_drift`, `dribble_time`, ...) were trained on the other machine; `sim/runs/` is gitignored
and none of them are on this PC. The only copy of the best dribble actor is the preview export `shared/policies/dribble.onnx`
(= `dribble_drift/ckpt_250M`, 250 M steps, interface 32f5b79d3216e8a3).

- Warm start rebuilt with `tools/onnx_to_ckpt.py ../shared/policies/dribble.onnx --out runs/production/dribble_drift_250M.pt`
  (onnxruntime vs torch 1.48e-6, parity PASS). Actor + normaliser only: no critic, optimiser or exploration std.
- Affected policy: dribble (L2a) only. No obs / action / physics / reward-code change. Nothing is exported or promoted by this run.
- Differences from `dribble_time` (other machine, stopped at 31 M): rule `ball_in_control` palm window 1.0 s (11-20 11:00), and the
  new `foot_slip` penalty (-0.1, `shared/reward_config.json`, fc49523) that this actor never trained with.
- Run: `tools/skill_run.py --level l2a_time --gate l2a_dribble_r --run-name dribble_time10 --train-min 540 --ckpt-every-steps 50e6`,
  extra `--init runs/production/dribble_drift_250M.pt --init-actor-only --critic-warmup-iters 60 --freeze-norm --init-std 0.15
  --kl-target 0.02 --assist-anneal-steps 1`. std 0.15 (not the 0.5 default: the ckpt carries no std) and KL 0.02 so the adaptive LR
  is not pinned at its floor (11-19 finding: KL ~ 1/std^2). Every 50 M checkpoint is evaluated on the gate after training.
- 23:14 started (PID 37160 driver). train.py warns interface/physics sha differ: **line endings only** (the shas hash raw bytes).
  This checkout: humanoid.xml CRLF (LF = bd7cf5274215544f, the ckpt value), court.xml LF (CRLF = 7e9b5753773f66b7, the ckpt
  value), obs_spec.json LF c766c7d32fb36d2e (CRLF = 9879b4bebba21aa3 = the 11-20 text-only edit). Same physics, same layout.
  ~20k fps on this laptop (530 M-650 M steps expected).
- Gate caveat (was an open user decision from 11-20 10:45; decided 23:30, see below): a clean bounce needs the ball < 0.6 m from the pelvis all cycle, but the dribble
  spot is 0.54 m from the pelvis (3 % of bounces qualify), so `l2a_dribble_r` stays 0 % whatever the policy does until that rule changes.

## 23:30 clean-bounce "near" rule: within 0.3 m of the dribble spot (user decision: "near the spot")

Was: the ball stays < 0.6 m (horizontal) from the pelvis for the whole cycle; the tier-3 spot (0.45 fwd, 0.30 side) is itself
0.54 m from the pelvis, so 3 % of dribble_drift's bounces qualified. Now: the ball stays < 0.3 m from the active hand's dribble spot
(`L2Dribble._spot()`, pelvis + heading-frame offset) for the whole cycle. Same 0.3 m as `l2a_push`'s `near` peak bonus.
Affected: gate/metric `clean` + streak in every L2Dribble subclass (l2a/l2b/l2c, l2a_cycles/push/time) and L4JumpShot (inherits
L2Dribble.step); training reward unchanged (no term uses `near_since`; `l2a_time.clean_frac` = 0). Unreal
`UStreetballDirector::UpdateBounce` mirrored (spot offsets per tier, shared with `PrepareReset`). No obs/action/physics change.
Gate results before this entry are not comparable. The running `dribble_time10` trainer keeps the old code in memory (training is
unaffected); its end-of-run gate evaluations are new subprocesses and use the new rule.
- Applied: `L2Dribble.near_spot_r = 0.3` (`near_since &= spot_d < near_spot_r`); Unreal `NearSpotR = 0.3`,
  `UStreetballDirector::DribbleSpotOffset(tier)` used by both `PrepareReset` and `UpdateBounce` (tier from `TierForState(State)`).
- Verification: UE build OK; Unreal `Streetball.*` **22/22**; CPU tests (stand, penetration, reward_config) 13/13.
- Re-gate of the start brain `dribble_drift_250M` (100 eps, new rule): **9 % success** (was 0 %), clean streak mean **9.9** (was ~0.05),
  episode 17.1 s (other machine, old palm window: 10.2 s), apex 0.68, in_control 0.99, falls 2 %. Fails: **pelvis_drifted 88 %**,
  ball > 1.5 m 2 %. Drift is now the single blocker.
