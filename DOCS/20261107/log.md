# 2026-11-07 — daily log (overnight queue results)

Queue `sim/runs/queue/20261106_2300`, 23:00 → 06:37, ~1.1 B simulated steps. Final report:
`DOCS/20261107/extended_training_report.html` (per-run reports alongside it).

## Results

| Skill | Policy | Runs | Steps | Eval success | Gate | Weights |
|---|---|---|---|---|---|---|
| Tier 1 balance | balance | l0_v4 (before queue) | 29.5 M (+85 M lineage) | 98 % | PASS + Unreal gate PASS | `sim/runs/production/balance.{onnx,pt,json}` |
| Tier 2 traversal | locomotion | l1_traverse_q1, _q2 | 202 M + 137 M (+34 M before) | 72.5 % → **82 %** (gate 90 %), 0 falls, 1.6 m/s | not yet | candidate `production/candidates/locomotion_l1_traverse.pt` |
| Tier 3 dribble (R, L, crossover) | dribble | l2a/l2b/l2c _q1 | 117 + 41 + 73 M | 0 % | no | — |
| Tier 4a moving dribble | dribble | l3a_q1 (stopped early) | 32 M | 0 % | no | candidate |
| Tier 4b scramble | scramble | l3b_q1 | 70 M | 0 % (ball 2.2 m away at the 3 s limit) | no | candidate |
| Tier 5 jump shot | shot | l4_q1 | 102 M | 0 % (ball lost before the trigger) | no | candidate |

Zero falls and zero NaN-gradient batches in every evaluation.

## What was learned overnight

1. **Locomotion works but is slow.** The athlete jogs at ~1.6 m/s and reaches all ten waypoints in 82 % of
   90-second episodes. Return was still rising when both boxes ended, so more steps should close the gap to 90 %.
   Speed is the limiter: the velocity-tracking reward is satisfied by the low end of the 0.8–3.0 m/s command range.
2. **The dribble reward was exploitable three ways**, found and fixed in sequence during the night (see
   `DOCS/20261106/change_self_collision_and_roster.md`): (a) a 20 cm "tap" instead of a waist-high bounce
   (apex shaping was a narrow band), (b) the tap persisted because spot/control terms paid regardless of height
   (now gated, monotonic shaping), (c) the ball was being juggled with feet and shins because the loose-ball
   countdown never armed without an initial grant of control (now granted at reset, as in Unreal).
   **No dribble stage has yet trained from a clean start with all three fixes**: l2a/l2b/l2c trained before fix
   (b)/(c), l3a was stopped at 32 M steps, and every later stage was initialised from the foot-juggling checkpoints.
3. **Scramble and shot depend on dribble** and were effectively untrainable this night (shot episodes end at 2.3 s
   because the ball is lost before the trigger).

## Recommended next steps (in order)

1. Re-run the dribble family **from the locomotion checkpoint, not from the tap checkpoints**, with the fixed
   reward; give L2a at least 150 M steps and watch `m/apex` and `m/in_control` (should rise above 0.8 m and 0.8).
2. Give L1 another 150–200 M steps and raise the floor of the commanded speed range to 1.2 m/s so the
   policy cannot satisfy the task by jogging slowly.
3. Scramble: shorten the initial ball distance range to 0.5–2.5 m for the first 50 M steps (curriculum), then widen.
4. Shot only after dribble passes.

## Housekeeping

- Production manifest: `sim/runs/production/production_manifest.json` (balance only).
- All queue runs are < 24 h old; nothing deleted (UU_AGENT §4). `l1_v1_resume.pt`, `l0_v*_*.pt` copies can be
  pruned after 2026-11-08.
- One operational mistake during the night: I killed the pre-fix l3a stage early on purpose; the clock in my notes
  was ~20 min ahead of the real time, so the DOCS timestamps for the 03:xx/04:xx entries are approximate.

## 15:50 — "play scene": athlete falls every 1.4 s in Tier 1 (diagnosed, not yet fixed)

Observed in `-game`: `HARD_RESET (fallen) in tier 1` every 41 frames with the production balance policy.

| Start condition (same policy, 64 envs, no pushes, 10 s) | Falls |
|---|---|
| Training reset (ball 3 m away, joint noise, randomisation) | 1.6 % |
| Exact `stand` keyframe, ball moved 3 m away | 0 % |
| Exact `stand` keyframe, ball left beside the right foot (what Unreal Tier 1 does) | **100 %**, at 1.36 s |

Root cause: Unreal's Tier 1/2 hard reset leaves the ball at its keyframe spot (0.45 m ahead, 0.35 m right, on the floor).
L0 always trained with the ball parked 3 m away, so the athlete trips over a ball it has never seen. Sim/Unreal
mismatch in reset rules, not physics: obs (5e-8), ONNX vs PyTorch actions (3e-7) and CPU vs Warp trajectories agree.

Two tooling defects found on the way:
1. `shared/golden/replay_l0.json` (the Step 4 live-physics golden) itself falls at 1.4 s. The gate checked Unreal-vs-Python
   parity only, so it passed while both sides fell. The gate needs an "athlete still upright" assertion.
2. `env_base.step()` returns `info["fallen"]` as a reference to `self.fallen`, which the auto-reset clears in place.
   Every reported fall rate (evaluate.py, queue reports) therefore reads 0 %. Success rates are unaffected
   (computed before the reset). Fix: clone the flag in `info`.

Proposed fix (awaiting approval): park the ball 3 m away on Tier 1/2 resets in the Unreal director (mirror of
`l0_stand.on_reset`), clone `fallen` in `info`, add the upright assertion to the gate, re-run eval + gate.

## 16:00 — fix applied: ball parked away from the feet (user: "focus on balance; ball has nothing to do with it")

Policies touched: none (Unreal director reset rule only; physics, interface and weights unchanged).
- `UStreetballDirector::ParkBallForTier`: tier 1 parks the ball 3 m from the start spot (mirror of `l0_stand.on_reset`),
  tier 2 parks it off court at (0, 8) (mirror of `l1_traverse.on_reset`). Applied on hard resets and at startup.
- New launch switch `-StreetballMaxTier=N`: the run never advances past tier N; a mastered tier at the cap restarts its goal.
- Verified in `-game -StreetballMaxTier=1`: 0 falls in 150 s (two full 60 s balance goals), T1 mastered.
  Screenshot `SCREENSHOTS/20261107_tier1_ball_parked.png`.
- Without the cap the run advances to tier 2, which has no trained locomotion policy in Unreal yet and falls every 2 s.

Still open from the diagnosis: `info["fallen"]` cleared by the auto-reset (reported fall rates read 0 %), and the
Step 4 gate needs an "athlete still upright" assertion.

## 16:30 — physics change: forearm/torso self-collision + shoulder stop (user: "right arm intersecting body during locomotion, fix")

Cause: `humanoid.xml` excluded torso-lowerarm and pelvis-hand from self-collision ("overlap in the A-pose", which no longer
holds: 8.4 cm clearance at the stand keyframe). Measured on CPU with the locomotion candidate: right forearm 15.5 cm inside the torso.

Policies touched (UU_AGENT §3): **balance** (production), **locomotion** (candidate). Dribble/scramble/shot untrained.
| Change | Kind | Action |
|---|---|---|
| Removed excludes torso-lowerarm_l/r, pelvis-hand_l/r (pelvis-calf kept) | body physics | re-evaluate + fine-tune balance and locomotion |
| shoulder_abd physical stop at -5 deg anatomical (was -30); actuator ctrlrange and obs spec **unchanged** | body physics | same; interface sha unchanged |
| `env_base.step`: `info["fallen"]` is now a clone (was cleared by the auto-reset; all past fall rates read 0 %) | tooling | evaluations now report real falls |

Results on the new physics: walking forearm-torso min distance -3 mm (contact, was -155 mm); locomotion still walks.
New humanoid.xml sha `ac1c8d03c1e036df`. Tests: 13/14 pass; `test_warp_vs_cpu_drift` fails on the OLD model too (Warp worlds diverge 2.7e-2) — pre-existing, open.

Balance re-evaluation with real fall counting (200 episodes, 100 N pushes):
| Physics | Success | Falls |
|---|---|---|
| old (frozen 01a3f59b) | 91.5 % | 5.5 % |
| new (arm collision) | 87.5 % | 9.0 % |
Balance was already below its 95 % gate once falls were counted correctly; the 98 % graduation figure did not reproduce.
Plan: fine-tune balance 45 min (`l0_v5_armstop`) then locomotion 90 min (`l1_v2_armstop`) from their checkpoints, evaluate both.

## Session wrap-up (balance fine-tune ~40 min in)

Still running unattended: `sim/runs/armstop_finetune.ps1` → balance fine-tune `l0_v5_armstop` (45 min) + eval, then locomotion
`l1_v2_armstop` (90 min) + eval. Progress: `sim/runs/armstop_log.txt`; evals in `sim/runs/*_armstop_eval.txt`.

Next session, in order:
1. Read both evals. If balance >= 95 % and holds 100 straight: export to `runs/production/balance.*` and Unreal `Content/Sim/policies/`.
2. Export locomotion to Unreal (preview unless >= 90 %), launch
   `-game -StreetballStartTier=2 -StreetballMaxTier=2` and check the right arm visually.
3. Regenerate goldens on the new physics (`replay_recorder.py`, obs golden) and add an "upright at end" assertion to the Step 4 gate.
4. Locomotion below 90 %: more steps with the commanded-speed floor at 1.2 m/s.
5. Dribble family from the locomotion checkpoint with the fixed reward.

## 12:15 (local) — balance re-graduated on the arm-collision physics

The first runner was killed with the agent session at 43.5 of 45 min (model.pt saved at 12:02); evaluation run by hand.
| Checkpoint | Success (200 ep, 100 N pushes) | Holds 100 straight | Falls (now counted correctly) | NaN grads |
|---|---|---|---|---|
| `l0_v5_armstop/model.pt` (63.9 M steps) | **100 %** | yes | 0 % | 0 |
Exported → `shared/policies/balance.onnx`, `runs/production/balance.*`, Unreal `Content/Sim/policies/balance.onnx`
(physics_sha `ac1c8d03c1e036df`, ORT vs torch 1.0e-6).

Locomotion fine-tune `l1_v2_armstop` (90 min) restarted at 12:16 via WMI `Win32_Process.Create` so it survives the agent
session (Start-Process children die with it). Runner `sim/runs/l1_armstop_finetune.ps1`; log `sim/runs/armstop_log.txt`.

## 13:50 — locomotion fine-tune on the arm-collision physics (`l1_v2_armstop`, 90 min, ~170 M steps)

| Metric (200 episodes) | Before (`l1_traverse_q2`) | After |
|---|---|---|
| Success (10 waypoints in 90 s) | 82 % | **86.5 %** (gate 90 %, not passed) |
| Falls (counted correctly) | n/a (counter bug) | 4 % |
| Speed | 1.6 m/s | 1.66 m/s |
| Right forearm vs torso, 10 s CPU walk | 155 mm inside | 6 mm contact |

Exported as an Unreal preview (`Content/Sim/policies/locomotion.onnx`), candidate checkpoint updated; not production.
Unreal `-StreetballStartTier=2 -StreetballMaxTier=2`: 0 falls in 60 s, 5 waypoints. Screenshots:
`SCREENSHOTS/20261107_tier2_arm_collision.png` (right forearm carried across the chest, resting on it, no deep clipping),
`SCREENSHOTS/20261107_tier2_camera_lost.png` (broadcast camera framed the fence, athlete out of shot).

Open: (a) the policy still carries the right arm across the chest — posture, not penetration; needs an arm-posture
reward term (locomotion only) — awaiting approval; (b) broadcast camera loses the athlete in Tier 2.

## 14:00 — locomotion reward change: arm carry + speed floor (user: "continue" on the proposal)

Policies touched: **locomotion only** (reward + command range; physics and interface unchanged). Balance untouched.
- `l1_traverse.py`: new `p_arm_carry` (weight 0.5) = mean squared deviation from nominal of shoulder abduction/rotation
  (both arms) + 0.2 x elbow; shoulder pitch (fore-aft swing) stays free. Logged as `m/arm_carry`.
- Commanded speed 0.8–3.0 → **1.2–3.0 m/s** in the level, `shared/transition_table.json` ROAM row, the Unreal copy, and
  the director's built-in fallback table (mirror rule).
Run `l1_v3_armcarry`: 90 min fine-tune from `l1_v2_armstop/model.pt` (runner `sim/runs/l1_armcarry.ps1`, via WMI).

## 14:25 — camera fix + Unreal re-gate of balance on the new physics

- Broadcast camera framed the athlete–ball midpoint; with the ball parked off court in Tier 2 it pointed at empty court.
  `FBroadcastLogic::TargetFor` now frames only the athlete in STAND/ROAM; new assertions in `Streetball.B8.CameraCuts`.
- Headless `Automation RunTests Streetball`: **15/15 pass**. Step 4 live-physics gate with the re-graduated balance policy
  on the arm-collision physics: root 0.0000 cm, joints 0.00002°, obs 8.2e-7, 0/250 foot mismatches, 0.054 ms inference,
  **lowest pelvis 0.929 m** (new upright requirement ≥ 0.70 m). Report: `DOCS/phase_reports/Step4_gate_unreal.md`.

## 15:26 — locomotion GRADUATED (`l1_v3_armcarry`, arm-carry penalty + 1.2 m/s floor, 90 min from `l1_v2_armstop`)

| Metric (200 episodes) | `l1_v2_armstop` | `l1_v3_armcarry` |
|---|---|---|
| Success (10 waypoints, 90 s) | 86.5 % | **97 %** (gate 90 %) |
| Holds 100 straight | no | **yes** |
| Falls | 4 % | 2.5 % |
| Speed | 1.66 m/s | 1.87 m/s |
| Arm-carry penalty | ~0.30 | 0.068 |
Exported → `shared/policies/locomotion.onnx`, `runs/production/locomotion.*`, Unreal. NaN grads 0.
This is the hand-tuned-reward **baseline** for the AMP comparison requested next.

## 15:40 — AMP (MimicKit) + LocoMuJoCo mocap, alongside the original RL (user request: compare the two)

Approach: MimicKit's AMP agent (xbpeng/MimicKit `learning/amp_agent.py`, `amp_model.py`) ported into our trainer as a
**second driver** `sim/streetball/train_amp.py`; the baseline `train.py` is untouched. MimicKit itself runs on Isaac
Gym/Lab/Newton and its policies would not fit the frozen 119-float interface Unreal uses, so only its method is ported.
Same env, PPO, policy interface and checkpoint format → evaluate/export/Unreal unchanged.

- `streetball/amp.py`: style features (pelvis height, pelvis tilt, heading-frame velocities, 21 joint angles + velocities,
  hands/feet/head relative to the pelvis), discriminator (1024-512), MimicKit losses (BCE + gradient penalty 5 + logit reg),
  style reward `-log(1-sigmoid(D)) x 2`, replay buffer. Two-frame transitions at 50 Hz.
- `tools/retarget_loco_mujoco.py`: LocoMuJoCo **SkeletonTorque** clips → our humanoid by joint name, signs calibrated
  functionally (effector displacement), elbow by convention, wrists zeroed; root re-framed and scaled (0.965); floor re-levelled;
  resampled 40/30 Hz → 50 Hz. 14 clips, 55 min (walk, run, sprint, walkturn, random walk, balance, step-in-place).
  Visual check `tools/render_mocap.py`. Wrists and ankle roll are excluded from the features (constant in the mocap; the first
  smoke test showed the discriminator separating on them instantly).
- Level `l1_traverse_amp` = `l1_traverse` without the hand-written pose/arm-carry penalties (style comes from AMP).
- **Data licence**: LocoMuJoCo datasets are CC BY-NC-ND 4.0 — non-commercial; retargeted data in `sim/data/mocap/` is
  git-ignored and must not be redistributed or shipped. Raw clips/models live outside the repo in `../ext/`.

Comparison run `l1_amp_v1`: 90 min from `l1_v2_armstop/model.pt` (same init, budget, envs, pushes, speeds as the
baseline `l1_v3_armcarry`), evaluated with the same `l1_traverse` success test.

## 15:53 — AMP restarted on clean mocap (`l1_amp_v2`)

`l1_amp_v1` was stopped at ~8 M steps: its arm-carry measure rose 0.30 → 0.62. Cause in the data, not the method: the
**LAFAN1** SkeletonTorque clips use a different arm-rotation convention (mean shoulder rotation −76° vs ~0° in LocoMuJoCo's
own walk), which retargets as a "phone at the ear" arm during plain walking (render checked). The Default **balance** clip is
one-leg yoga-style balancing (arms flung out), not walking style. Both dropped.
Demo now: LocoMuJoCo Default walk, run, walkturn, random_walk, stepinplace1 = 22 min, 66,890 transitions.
Arm-carry measure on these clips: 0.05–0.09 (walks), 0.39 (run). Same init/budget as the baseline; run dir of the discarded
attempt kept as `runs/l1_amp_v1_lafanarms_discarded`. Expected finish ~17:25 incl. evaluation.

## 16:55 — AMP stopped on request (resume later)

`l1_amp_v2` stopped at **34.4 M steps** (~55 of 90 min), NaN grads 0. Last trends: arm-carry 0.30 → 0.12 (no hand-written
penalty), arm-swing symmetry 68 % vs 39 % for the original, style reward plateaued ~0.42, episode length ~57 s, speed 1.86 m/s.
Not yet evaluated. Preview exported to Unreal as `Content/Sim/policies/locomotion_amp.onnx`.
`train_amp.py` now restores the discriminator when `--init` points at an AMP checkpoint.

**To resume** (from `sim/`):
```
uv run python -m streetball.train_amp --level l1_traverse_amp --init runs/l1_amp_v2/model.pt --run-name l1_amp_v3 --time-budget-min 40 --push-curriculum --init-std 0.3
uv run python -m streetball.evaluate --level l1_traverse --ckpt runs/l1_amp_v3/model.pt
copy ..\DOCS\phase_reports\eval_l1_traverse.json runs\l1_amp_v3\eval.json
uv run python tools/compare_amp.py --baseline runs/l1_v3_armcarry --amp runs/l1_amp_v3 --out ../DOCS/<day>/amp_vs_baseline.html
```
Watch in Unreal: `-StreetballStartTier=2 -StreetballMaxTier=2 -StreetballPolicy_locomotion=policies/locomotion_amp.onnx`.
Launch long jobs without a visible console next time (Windows Terminal ignores -WindowStyle Hidden).
Mocap data lives in `sim/data/mocap/` (git-ignored, CC BY-NC-ND) and `../ext/`; rebuild with `tools/retarget_loco_mujoco.py`.
