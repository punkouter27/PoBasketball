# 2026-11-08 — daily log

## 02:15 — 8-hour unattended queue `r2`: dribble → scramble → shot (user: "EXTENDED TRAINING (8 hours) ... prioritizing urgent policies")

Urgent policies = the families with no passing gate: **dribble** (L2a/L2b/L2c/L3a), **scramble** (L3b), **shot** (L4).
Balance (100 %) and locomotion (97 %) are graduated and are not trained or exported by this queue.

Policies touched (UU_AGENT §3):
| Change | Kind | Policies |
|---|---|---|
| Dribble family restarted from `runs/production/locomotion.pt` (actor only), not from the foot-juggling `_q1` checkpoints | training init | dribble |
| L3b scramble: ball distance 0.5–2.5 m for the first 50 M training steps, then 0.5–4 m (`Level.train_steps`; evaluation unchanged, always 0.5–4 m) | training reset curriculum | scramble |
| Physics, obs interface, rewards, Unreal | — | none (interface `ccfa18d6f9aaf2a5`, physics `ac1c8d03c1e036df`) |

Tooling: `queue.py` gains `--tag` (run names `<level>_r2q<N>`, never overwrite last night's `_q<N>`), `--init-actor-only`,
and an hourly status grid in `DOCS/20261108/hourly_status.md`. First-pass budgets: L2a 150 min (hand-off asked for ≥150 M steps),
L2b 40, L2c 60, L3a 80, L3b 50, L4 60; leftover time retries the earliest failed stage. Gate unchanged (target held 100 straight
episodes, 0 NaN grads) → export ONNX to `shared/policies/` + `runs/production/` + Unreal.

GPU note: an unrelated app (`Maestro\launch.py`, ~5 GB VRAM, ~40 % util) was already running; throughput will be below last night's.

Command (from `sim/`): `uv run python -m streetball.queue --hours 8 --start-from l2a_dribble_r --init runs/production/locomotion.pt --init-actor-only --tag r2`
Watch: `DOCS/20261108/hourly_status.md`, `sim/runs/queue/<stamp>/queue_log.md`, TensorBoard `--logdir sim/runs` (port 6006).

## 02:48 — r2 stopped at 40 min: L2a was learning to ignore the ball

| L2a metric (r2, from locomotion) | 1 M steps | 70 M steps | needed |
|---|---|---|---|
| apex | 0.71 m | 0.47 m | 0.80–1.15 m |
| in_control | 0.82 | 0.17 | > 0.8 |
| episode | 0.4 s | 3.3 s of 30 s | — |

Diagnostic (256 envs, deterministic, 12 s): palm-ball contact registers (46 % of envs touch at least once; contact buffer peak
900/12,288, no overflow), but the right palm is 0.73 m from the ball on average and touches it in 0.1 % of steps; every episode
ends by losing the ball (717 countdown, 368 rolled away), none by falling. The existing `r_palm` term is ~0 at that distance and
is gated on ball z > 0.5 m while the ball averages 0.43 m, so nothing pulled the hand to the ball.

## 03:05 — dribble reward: reach + touch shaping (training only; pass test and gate unchanged)

Policies touched: **dribble** only (L2a/L2b/L2c share `L2Dribble.reward`). No production dribble policy exists.
- `r_reach` (w 1.0): exp(-(|active palm - (ball + 12 cm up)| / 0.4)^2) while ball z > 0.25 m. Logged `m/reach`.
- `first_touch` (w 2.0): first active-palm touch per bounce cycle (at most one per bounce). Logged `m/palm_touch`.
12-min A/B vs r2 at equal steps (20 M): apex/in_control/episode length unchanged, but `m/reach` 0.05 → 0.11 and rising
(r2 had no such signal). Slow, so L2a gets 240 min first pass in queue r3, resumed from that check run (`runs/l2a_reachcheck`).
Queue r3: `--tag r3 --start-from l2a_dribble_r --init runs/l2a_reachcheck/model.pt --stage-minutes l2a_dribble_r=240 --hours 6.75`.
Run `l2a_dribble_r_r2q1` (70 M steps, pre-shaping) kept for the report comparison.

## 04:40 — r3 stopped at 93 min (≈180 M steps): hand hovers, never touches

| L2a metric (r3) | 0 M | 180 M |
|---|---|---|
| `m/reach` | 0.33 | 0.47 (hand moved toward the ball) |
| `m/palm_touch` (per step) | 0.0012 | 0.0005 |
| apex / in_control / episode | 0.73 m / 0.96 / 0.4 s | 0.46 m / 0.18 / 3.4 s |
Ball contacts by geom (256 envs, 12 s): floor 3.8 %, palm_r 0.09 %, lowerarm_r 0.08 % of env-steps; palm 36 cm above the ball.
Shaping alone cannot fix a touch the policy never experiences → start-state curriculum.

## 04:45 — dribble start-state curriculum "ball in hand" (training only; evaluation never assisted)

Policies touched: **dribble** (L2a/L2b/L2c). `L2Dribble._assist_reset`: in a share of TRAINING resets the ball starts 15 cm under the
active palm site rising at 0.8 m/s (first attempts spawned it overlapping the palm box → ejected; or launched it from 45 cm below →
policy's hand had moved). Share 75 % → 15 % over 150 M steps (`assist_prob`, 0 when `train_steps = inf`, i.e. evaluation).
Check: palm contact in the first 0.5 s for 69.5 % of envs with the locomotion actor (75 % expected).
Queue r4 from `production/locomotion.pt` (actor only), 4.75 h: L2a 150, L2b 30, L2c 35, L3a 45 min first pass.

## 05:20 — r4 stopped at 37 min (65 M steps); dribble parked for a method decision

r4 (ball-in-hand assist) repeated the r2/r3 curve: palm touches 1 % → 0.2 % of steps, in_control 0.82 → 0.19, episode → 3.3 s.
Episode-end analysis with the assist on (512 envs, 15 s): touched episodes last as long as untouched ones (3.63 vs 3.50 s), both
end on the loose-ball countdown (811/830 and 1171/1232). So touching is not punished; the policy never makes a **second** touch
after the ball's first bounce. Rhythm/timing credit assignment, not reach, is the blocker. Three shaping/curriculum attempts in
3.3 h did not move it; the next step is a method choice for the user (see proposal in the final report).

Rest of the window (runner `sim/runs/night_20261108_part2.ps1`, log `night_20261108_part2.txt`):
1. AMP locomotion resume `l1_amp_v3` (40 min from `l1_amp_v2`, 34 M steps) → `l1_traverse` evaluation → `DOCS/20261108/amp_vs_baseline.html`.
   The baseline's `DOCS/phase_reports/eval_l1_traverse.*` is backed up and restored around the AMP evaluation.
2. Queue r5 until 10:00: L2a continued from `l2a_dribble_r_r4q1/model.pt` (assist curriculum restarts at 75 %), then the ladder.

## 06:05 — AMP locomotion `l1_amp_v3` finished (~95 min total, same budget as the baseline) and PASSES the gate

| `l1_traverse` test, 200 episodes | Hand-tuned `l1_v3_armcarry` (production) | AMP `l1_amp_v3` |
|---|---|---|
| Success (10 waypoints, 90 s) | 97.0 % | **97.0 %** |
| Holds 100 straight | yes | **yes** |
| Falls | 2.5 % | 2.0 % |
| Speed | 1.91 m/s | 1.87 m/s |
| Arm-swing symmetry (L/R) | 38 % | **52 %** |
| Arm-carry deviation (lower = more relaxed) | **0.068** | 0.113 |
| Fresh mocap classifier "human" score | 0.0006 | 0.0005 (both fully separable from mocap) |
NaN grads 0. Comparison page: `DOCS/20261108/amp_vs_baseline.html`. Verdict: task-equal, mixed on style.
Exported as a graduated **candidate**, not production: `shared/policies/locomotion_amp.{onnx,json}`, `runs/production/candidates/locomotion_amp.*`,
Unreal `Content/Sim/policies/locomotion_amp.onnx` (ORT vs torch 1.6e-6). Production `locomotion.onnx` unchanged — user decision.
Baseline `DOCS/phase_reports/eval_l1_traverse.*` restored after the AMP evaluation (checked).

## 09:40 — Night window closed: queue r5 results (dribble continuation)
Policies touched: dribble (training only; nothing exported). Locomotion/balance production unchanged.

| Stage | Run | Steps | Success | Falls | Palm touch (end) | In control (end) |
|---|---|---|---|---|---|---|
| L2a dribble R | l2a_dribble_r_r5q1 (150 min, from r4q1) | 248 M | 0 % | 0 % | 0.24 % | 23 % |
| L2b dribble L | l2b_dribble_l_r5q1 (30 min) | 49 M | 0 % | 0 % | 0.19 % | 19 % |
| L2c crossover | l2c_crossover_r5q1 (30 min) | 49 M | 0 % | 0 % | 0.20 % | 18 % |

L3a/L3b/L4 skipped (24 min left < reserve). No NaN gradients. Reward rose (168 → 371) while touch stayed ~0.2 %:
same "stand still, let the ball die" optimum as r2–r4. More time on this reward will not fix it.
Final report: `DOCS/20261108/night_training_report.html` (tools/night_report.py). Open: dribble teaching method
(scripted hand–ball reference recommended) and whether to promote `locomotion_amp` — both await the user.

## 11:49 — Dribble approach #5 (user said "go"): scripted hand–ball teacher, feasibility findings
Policies touched: none (analysis only). New tool `sim/tools/scripted_dribble.py` (WIP teacher; not used in training yet).
Legs/torso from `l2a_dribble_r_r5q1` (stands with a ball, 0 % falls); right arm (+lumbar) from IK toward a palm target
computed from observable ball state. Best result so far: 2 consecutive touched bounces; never sustained.
Findings that also explain the four failed RL runs:
1. **Ball lands on the right foot.** Dribble spot (0.25 fwd, 0.35 lat) overlaps the policy's wide stance (foot_r at
   y = -0.23): a ball dropped there leaves the foot sideways at 3.7 m/s. Every RL run was rewarded for the ball being there.
2. **Reach floor ~0.85 m standing.** Palm at 0.75 m needs 54 deg lumbar flex + full shoulder rotation; the stroke window
   between ball top at apex (~1.0 m) and the reach floor is only ~15 cm.
3. **Arm servo is slow.** kp 150 / kv 15 gives ~0.8 m/s palm speed when commanded straight to a target; a dribble push
   needs ~2.8 m/s at release (restitution ~0.87, apex 0.9 m). Commanding past the target (5x error) restores speed and
   did add energy (apex 0.87 -> 1.11 m), but the joint-space path swings the palm 15-20 cm sideways first.
4. The base leg policy turns/walks while the arm is overridden (pelvis drifted 0.6 m in 2 s).

## 11:53 — Correction to finding 1 (ball hits foot); spot-move retrain NOT started
Measured in the real GPU env (`l2a_dribble_r`, policy r5q1, 512 envs x 1000 steps): the ball touches a leg on
**8 % of floor bounces** at the current spot (0.25, 0.35) and 11 % at (0.40, 0.30). Settled-stance CPU drops: 0/10 leg hits
at both spots. The 3.7 m/s foot deflection seen at 13:00 came from the t = 0 keyframe stance under the balance policy,
not from normal play. Moving the spot is therefore not the main fix; the approved 2 h retrain was held back and the
user asked to choose again. Findings 2-4 (reach floor, slow arm servo, leg drift) stand.

## 12:11 — Stiffer-arm test (sim only, user approved): no meaningful gain
Policies touched: none. Shared humanoid spec / Unreal untouched (actuators overridden in memory only).
Scripted two-pose and Cartesian stroke dribblers, torso free and pinned, 16 settings per arm:
| Arm shoulder+elbow kp/kv/force | Best consecutive touched bounces | Longest run |
|---|---|---|
| 150/15/100 (current) | 2 | 5.8 s |
| 300/10/150 | 3 | 5.8 s |
| 500/10/200 | 2 | 4.2 s |
| 800/15/300 | 2 | 4.4 s |
Conclusion: arm stiffness is not the blocker; the hand-written controller (contact timing + steering) is. The
actuator contract stays as is. Scratch harness: scratchpad/bang.py (not committed).

## 12:17 — Dribble approach #6 (user approved): one-bounce curriculum `l2a_cycles`
Policies touched: dribble (training only). New TRAINING-ONLY level `L2DribbleCycles` (sim/streetball/levels/l2_dribble.py):
episodes of K push->bounce->peak cycles, K doubles 1 -> 16 when > 60 % of finished episodes are fully clean; each push is
scored at the very next peak (~0.4 s) instead of at the floor contact two flights later; every episode starts with the
ball rising into the palm. Obs/action interface and task block unchanged; graduation still judged on `l2a_dribble_r`.
Run `l2a_cycles_c1`: 120 min, actor from l2a_dribble_r_r5q1 (fresh critic), hidden runner runs/cycles_20261108.ps1,
then eval on l2a_dribble_r + run report. 3-min smoke test OK (episode 0.8 s, K = 1); smoke run deleted.

## 13:20 — l2a_cycles: K-promotion bug fixed, run resumed as l2a_cycles_c2
Bug: `env.reset()` zeroes `step_count` before calling `level.on_reset`, so the "episode ran" filter was always false and
K never left 1 (`m/succ_ema` stayed exactly 0). Fix: the level keeps its own per-episode step counter (`ep_steps`).
c1 stopped at 72 M steps (13:09). Its checkpoint already succeeds on **51.5 %** of one-bounce episodes (200-episode eval
on l2a_cycles, 0 % falls; eval file removed afterwards so the gate reports stay L2a only). Palm touch 0.2 % (r5) -> 4 %;
mean apex 0.67 -> 0.78 m; in-control 79 % -> 95 %. Resumed with full optimiser state as `l2a_cycles_c2` (60 min, runner
runs/cycles2_20261108.ps1), then eval on l2a_dribble_r + run report. (Headings above re-timed from commit times.)

## 14:20 — l2a_cycles_c2 result (60 min resume, K-promotion fix)
- Policies touched: none in production. Training-only level `l2a_cycles`; checkpoint `sim/runs/l2a_cycles_c2/model.pt`.
- The promotion fix works: K went 1 -> 2 early in the run ("success > 60%: K -> 2"). It never reached the next step (4).
- Two-bounce training success rose from 1 % to 6.5 % (EMA) by the end. Per-peak success (`m/cycle_ok`) is 0.31, mean peak 0.77 m, ball in control 0.71, palm touch 2.9 %.
- Real gate `l2a_dribble_r` (200 episodes): **0 % success, not passed**. Falls 0.5 %, no NaN gradients. Mean episode 1.56 s; r5q1 lasted 3.78 s.
  - Mean bounces per episode 1.05: the first push works, then the ball is lost before the second.
  - Compared with r5q1: apex 0.47 -> 0.65 m, in-control 0.23 -> 0.42.
- No ONNX export: the gate failed. `DOCS/phase_reports/eval_l2a_dribble_r.*` now holds this c2 evaluation. HTML report: `DOCS/20261108/report_l2a_cycles_c2.html`.
- Open issue: chaining the second push. The two-bounce curve was still rising when the time budget ran out.

## 14:42 — l2a_cycles_c3 started (user approved)
- 120 min full resume from `l2a_cycles_c2`, no code changes. Launcher: `sim/runs/cycles3_20261108.ps1`, started hidden via WMI. Log: `sim/runs/cycles3_20261108.txt`.
- The run then evaluates on the real gate `l2a_dribble_r` and writes the HTML report. Expected finish around 16:45.
- Note: K (bounces per episode) is level state and is not saved in the checkpoint, so it starts at 1 again. It should promote back to 2 within minutes, as in c2.
- Decision rule: if two-bounce success is still under 20 %, change the reward instead of adding GPU time.

## 16:00 — l2a_cycles_c3 stopped early (user request), result, Unreal preview
- Stopped at 54 M steps (about 76 of 120 min) because two-bounce success had been flat at about 15 % for 45 min. `model.pt` was saved at 15:58:13, 35 s before the stop, and it loads cleanly (no NaN gradients).
- Real gate `l2a_dribble_r` (200 episodes): **0 % success, not passed**. Falls 2 %, mean episode 1.29 s, 0.89 bounces, apex 0.70 m, ball in control 0.60. No improvement over c2. HTML report: `DOCS/20261108/report_l2a_cycles_c3.html`.
- Unreal preview (user asked to play it): exported a **preview-only** ONNX (not production, nothing in `shared/policies`) to `unreal/StreetballGym/Content/Sim/policies/dribble_c3_preview.onnx`. The onnxruntime-vs-torch check passed.
  - Launched with `-StreetballStartTier=3 -StreetballMaxTier=3 -StreetballPolicy_dribble=policies/dribble_c3_preview.onnx`.
  - In Unreal the character **falls about 1.2 s after every reset** (HARD_RESET "fallen", 13 in the first 15 s), against 2 % falls in the sim.
  - Likely cause: a sim-to-engine reset mismatch. The tier-3 start (ball at the hand, `GrantControl`) does not mirror the sim's L2a reset, the same class of bug as the earlier tier 1/2 ball-placement issue.
- Conclusion: the l2a_cycles curriculum is stuck at about 15 % two-bounce success. Next: score each push right after the palm contact (dense, immediate credit) instead of at the floor bounce two flights later.

## AGENTS.md updated to the revised UU_AGENT standard (user paste)
- Scope is now Unreal-only (Unity column dropped). Project notes are kept unchanged.
- New rules: explicit cm↔m / left↔right-handed bridge transform; deterministic pre-allocation (no runtime spawn or destroy); visual bones mirror the physics bodies; a 5 s rollout validation (kinematics + contacts) before ONNX export; zero heap allocation in the C++ inference loop; a `**Current Phase: Step X of 5**` header and `[STOP]` gates.
- No policies, director rows or interfaces were touched (docs only). Compliance with the new rules has not been audited yet.

## Session: "do all" (user approved items 1-4 from the "what next" list)
Planned changes logged before any edit (UU_AGENT §3 audit trail):
- **Item 3, AMP promotion (user approved):** `locomotion` family → `l1_amp_v3` (AMP, 97 % on `l1_traverse`). The old `l1_v3_armcarry` is kept as `locomotion_ppo.{onnx,json}` for rollback. Director row affected: ROAM (tier 2) only. Interface `ccfa18d6f9aaf2a5` and physics `ac1c8d03…` are identical on both sides. Regression: Unreal gate (preset + live) re-run with the new file.
- **Item 1, tier-3 reset parity:** Unreal director/world reset for tiers 3–4 only. Ball at the dribble spot with a dribble-cycle height and velocity, as in `l2_dribble.on_reset`. New `-StreetballDribbleHand=right|left` override for single-hand previews. New 5 s dribble-start golden and gate check. Policies touched: none (start state only). Director rows: DRIBBLE_STATIONARY and DRIBBLE_MOVING reset spec.
- **Item 2, dribble reward:** `l2a_cycles` level only (training curriculum). Graduation is still judged on `l2a_dribble_r`.
- **Item 4:** compliance audit of the revised AGENTS.md (docs only).

## Results so far (evening session)
- **Item 3, AMP promoted:** `shared/policies/locomotion.onnx` is now `l1_amp_v3` (sha ff2531b7…). The old PPO policy is kept as `locomotion_ppo.onnx` (edf545eb…). Synced to Unreal.
  - **Regression NOT yet verified.** `replay_recorder.py policy` holds the task block at zero, and both the AMP and the PPO locomotion policies fall under that (pelvis 0.11 m). Locomotion never trained on a zero command (speed 1.2–3.0 m/s), so the check is invalid for any non-balance policy. Fix planned: record the task block and ball-control flags per step in the replay, and have `Streetball.Gate.LivePhysics` read them.
- **Item 1, root cause confirmed (no code yet).** The tier-3 Unreal reset leaves the ball resting on the floor at the keyframe spot (0.45 m forward, 0.35 m right, v = 0). Sim `l2_dribble.on_reset` puts it at the dribble spot (0.25 m forward, 0.35 m right), 0.4–0.95 m high, with vz = ±sqrt(2g(1−h)). Second mismatch: the tier-3 table row commands crossovers with a random starting hand, but the preview policy is right-hand only.
- **Item 2, code written, NOT trained.** New level `l2a_push` (`L2DribblePush`) gives immediate credit at the palm release: predicted rebound apex (e² = 0.72) plus predicted landing point near the spot, once per bounce cycle. It compiles but has not been run.
  - **BLOCKER:** from 21:07, Windows Smart App Control blocks the unsigned `torch\lib\shm.dll` (CodeIntegrity events 3033/3118). No training or evaluation can run until the user allows it.
- **Item 4, audit done** (Explore agent). Gaps, ranked:
  1. Heap allocation in the control step: FString PolicyName copies (`StreetballDirector.cpp:359,492`, `StreetballWorld.cpp:306`) and `TArray<float> Ctrl` (`StreetballWorld.cpp:314`).
  2. The 5 s gate lacks root velocity, angular momentum, foot sliding, clipping and chatter checks.
  3. Chaos still ticks (`DefaultEngine.ini:20-22`).
  4. `ApplyReset` allocates and logs inside the step.
  5. Bones are not strictly 1:1: spine slerp, head undriven, display interpolation.

  Minor gaps: coordinate bridge duplicated in `BroadcastCamera.cpp:10` and `CourtAudio.cpp:49`; TensorBoard events are not mirrored to `DOCS/<date>`. Meets: allocate-at-startup, build stamp, action-rate penalty, self-collision.

## Evening, continued: item 1 done, AMP regression verified, allocation fixes (user answers: hand switch, report-first gate, zero-alloc now, user fixes Smart App Control)
- **Tier-3/4 reset parity (Unreal).** New `UStreetballDirector::PrepareReset` mirrors `l2_dribble.on_reset` / `L3MovingDribble.on_reset`:
  - Ball at the active hand's spot (0.25 m forward in tier 3, 0.30 m in tier 4; 0.35 m to the side), h ~ U(0.40, 0.95), vz = ∓sqrt(2g(1−h)).
  - The hand is chosen before the reset and kept by the following EnterTier.
  - New switch `-StreetballDribbleHand=right|left` (no commanded switches; task slot 2 = 0, as in sim l2a).
  - New assert in `Streetball.C3.WorldLoop`: spot error 0.0000 m, ball z 0.659 m, in control.
- **Dribble preview diagnosis corrected.** From the correct reset, the c3 preview loses the ball at 0.6 s and falls at 3.5 s **in the sim too**. The sim episode ends earlier on drift > 0.5 m (1.9 s here, 1.29 s on average), so the "2 % falls" figure hid this. The policy never trained on what happens after a lost ball. The reset fix removes the early 1.2 s fall in Unreal; the rest is item 2.
- **5 s rollout gate.**
  - The recorder now has `--level l0_stand|l1_traverse|l2a_dribble_r`. It records the per-step task block, in_control, countdown, qvel and whole-body angular momentum. l1 uses a waypoint 10 m ahead and 2 m left at 1.5 m/s.
  - `Gate.LivePhysics` replays those inputs and reports root-velocity and angular-momentum error, foot sliding, floor penetration and contact flips (report-only). It asserts duration ≥ 5 s.
  - New goldens: `replay_balance.json`, `replay_locomotion.json` (AMP), `replay_locomotion_ppo.json`.
  - The default gate pair is now balance + `replay_balance.json`. The old default `replay_l0.json` + `l0_stand.onnx` was a stale pair: the replay was recorded with balance.onnx, and its action diff against l0_stand is 0.43. That made the full-suite gate fail.

| 5 s rollout (Unreal vs sim) | balance | locomotion AMP (production) | locomotion PPO (old) |
|---|---|---|---|
| Root / joint error | 0.0000 cm / 0.00002° PASS | 0.0127 cm / 0.028° **PASS** | — / 2.86° **FAIL** |
| Root velocity error | 3.0e-7 m/s | 1.2e-3 m/s | 8.3e-2 m/s |
| Angular momentum error / max | 5e-6 / 7.4 | 1.7e-2 / 12.1 kg m²/s | — / 17.6 |
| Foot slide while planted, max / mean | 0.26 / 0.008 m/s | 1.04 / 0.37 m/s | 1.18 / 0.33 m/s |
| Max floor penetration | 1.2 mm | 6.4 mm | 10.2 mm |
| Foot contact flips per s (L/R) | 0 / 0 | 12.4 / 12.6 | 12.0 / 12.6 |

- AMP regression **verified**: it passes parity, and the old PPO policy does not. Both gaits slide about 0.35 m/s mean while "planted" and flip contacts about 12 times a second (expected about 4/s at this cadence). Next: check whether that is real slipping or heel/toe contact toggling, before setting thresholds.
- **Zero-alloc control step.**
  - Policy family is now an `FName`, and reset reasons are `const TCHAR*`.
  - Ctrl, qpos and qvel scratch buffers are pre-sized; `PolicyRunner` uses memcpy instead of TArray assignment.
  - Audio events use literal pair names and a reused TSet. Reset logging is deferred to Tick.
  - Bridge: new `UMuJoCoSim::GetSubtreeAngMomSim`.
- Tests: full `Streetball` suite **15/15 pass**; Gate balance PASS; Gate locomotion (AMP) PASS.
- **Item 2:** `sim/runs/push_20261108.ps1` is ready (l2a_push, 120 min from c3, then gate eval and report). It starts with a torch import check and **waits for the user to fix Smart App Control**.

## 21:50 — 8 h unattended training started (user request: "EXTENDED TRAINING (8 hours)")
Smart App Control no longer blocks torch (`import torch` OK, CUDA on the RTX 5070 Ti). Unreal editor closed, 14 GB RAM free.
Changes logged before launch (audit trail):
- `streetball/queue.py`: `--plan` mode with named explicit stage lists. Each stage is judged on its REAL gate level (`eval_level`) and has an explicit init checkpoint.
- `l3b_scramble` reward: + palm-reach shaping (1.0 · exp(−(palm–ball/0.4)²) within 1.2 m). The first queue regained the ball 0 % of the time; a regain needs a palm touch that was never found by chance. Policies touched: scramble only (no production scramble exists yet).
- `runs/production/locomotion.*` is now AMP, matching `shared/policies`. PPO kept in `runs/production/candidates/locomotion_ppo.*`.
- Smoke tests (2 M steps each, deleted afterwards): `m/push_reward` 0.023/step (fires), scramble `m/reach` > 0.

Plan `urgent_20261108` (run tag `n9`, priority order):
1. `l2a_push` 150 min, from `l2a_cycles_c3` → gate `l2a_dribble_r`
2. `l3b_scramble` 100 min, from production AMP locomotion → gate `l3b_scramble`
3. `l2a_push` 130 min, resume
4. `l3b_scramble`, rest of the budget, resume

Shot is not scheduled (it needs a working dribble). Passing stages export production ONNX and sync to Unreal; others are saved as candidates. Reserve 25 min for evaluation and the report.
Watch: `sim/runs/queue/<stamp>/queue_log.md`, `DOCS/20261108/hourly_status.md`, TensorBoard http://localhost:6006. Launcher: `sim/runs/night_20261108.ps1`.
