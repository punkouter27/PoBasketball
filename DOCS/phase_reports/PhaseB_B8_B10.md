# Phase B — State machine (C.3), B8 camera, B9 audio, B10 HUD: PASS (12/12 automation tests)

Date: 2026-11-06. Builds on `PhaseB_B1_B7.md` (same project, same build/test commands, real RHI only).

## Results

| Item | Test | Result | Numbers |
|---|---|---|---|
| C.3 state machine | `Streetball.C3.Director.ScrambleAndResets` | PASS | DRIBBLE_STATIONARY → loose → SCRAMBLE (policy `l3b_scramble`, task[0] = countdown) → regain → back; expiry → HARD_RESET with reason "scramble countdown expired"; fallen and ball-past-fence each force HARD_RESET; after reset the tier-3 state resumes and tier stays 3 |
| Tier progression | `Streetball.C3.Director.TierProgression` | PASS | Tier 1 passes after 60 s of balance (a 0.3 m foot drift restarts the timer); Tier 2 passes after 10 waypoints driven from the task block (speed cmd within 0.8–3.0); Tier 3 passes at 50 consecutive clean bounces with 16 hand switches, then DRIBBLE_MOVING |
| End-to-end loop | `Streetball.C3.WorldLoop` | PASS | 6 state policies resolved (0 trained, all dummy fallback); 1 s STAND on `l0_stand`; forced tier 3 → control lost (dummy policy) → SCRAMBLE → hard reset after 99 control steps (the dummy policy made the athlete fall before the 3 s expiry) → DRIBBLE_STATIONARY resumes |
| B8 camera | `Streetball.B8.CameraCuts` | PASS | first frame SIDELINE at UE y = +930 cm; JUMP_SHOT cut refused inside 2 s, accepted at 2.5 s → BASELINE (z < 1 m); ROAM > 2 m/s → PRESS BOX (z > 6 m); slow roam → SIDELINE; SCRAMBLE → PRESS BOX; within 6 m of a rim → BASELINE; `streetball.ForceCamera` CVar overrides; critically damped tracking converges with no overshoot |
| B9 audio | `Streetball.B9.ContactAudio` | PASS | scripted 1.0 m drop: first ball-floor event at t = 0.454 s (free fall predicts 0.452), impact speed 3.96 m/s, volume 0.57, pitch 1.00; 5 ball-floor bounces all ≥ 60 ms apart and decreasing in volume; 13 events total incl. shoe/body contacts as the PD-held athlete falls; mapping: full volume at high speed, min volume at zero, pitch rises with speed |
| B10 HUD | `Streetball.B10.HUD` | PASS | tier text, "Clean dribbles: 17", "123.4 m", milestone row `[x] T1  [x] T2  [x] T3  [ ] T4`, 55 %, countdown visible only while loose |
| B1–B7 regression | the 6 earlier tests | PASS | unchanged numbers (mj_step 0.036 ms, hash `5d7e083b888b663b`, replay 0.0000 cm / 0.00000°, obs golden 4.76e-7, NNE diff 0.0, inference 0.035 ms) |

Headless run: `UnrealEditor-Cmd.exe <uproject> -ExecCmds="Automation RunTests Streetball; Quit" -unattended -nosplash -nop4` → `TEST COMPLETE. EXIT CODE: 0`.

## What was built

| File | Purpose |
|---|---|
| `StreetballTracker.{h,cpp}` | Per-control-step physics facts in the sim frame, mirroring `env_base.py`: contact flags (foot/floor, palm/ball, ball/floor, bad-floor, ball/rim, ball/board), ball-in-control rule (horizontal < 0.75 m, ball z < 1.3 m, last palm contact < 0.6 s), loose time, 3 s countdown fraction, fallen (pelvis z < 0.55 m or non-foot/palm body on the floor > 0.2 s), ball past the fence (|x| > 16, |y| > 9.5), heading frame, rim centres. `GrantControl()` marks the ball as just-touched when a tier starts with the ball at the hand, so a policy that never touches it loses control after 0.6 s and the countdown runs (otherwise a never-controlled ball would never be "loose") |
| `StreetballDirector.{h,cpp}` | The state machine: STAND, ROAM, DRIBBLE_STATIONARY, DRIBBLE_MOVING, JUMP_SHOT, SCRAMBLE, HARD_RESET. One policy name per state (`l0_stand`, `l1_traverse`, `l2c_crossover`, `l3a_moving_dribble`, `l4_jump_shot`, `l3b_scramble`). Task blocks per blueprint C.2 (L1/L3a: waypoint dir in heading frame, distance ≤ 10, speed cmd, hand; L2: hand, apex target 1.0, bounces-to-switch; L3b: countdown; L4: rim-relative position in heading frame (3), trigger, time since trigger). Bounce / clean-bounce / hand-switch bookkeeping copied from `l2_dribble.py` (rising edge of ball-floor, apex in 0.80–1.15 m, active palm touched since last bounce, ball stayed within 0.6 m). Tier milestones per PRD section 4; a hard reset restarts the active tier's counters, mastered tiers persist; tier 5 shot attempts persist across resets. Shot resets place the athlete at a random spot inside the 6.75 m arc facing the east rim with the ball at the right hand, through `ApplyReset` (qpos/qvel writes only) |
| `BroadcastCamera.{h,cpp}` | `FBroadcastLogic` (cut rules, 2 s hysteresis, framing/FOV from subject spread) + `ABroadcastCamera` actor (pre-allocated, critically damped position/look-at/FOV, snap on cut). CVar `streetball.ForceCamera` (-1 auto, 0 sideline, 1 baseline, 2 press box) |
| `CourtAudio.{h,cpp}` | `UCourtAudioBank` data asset (6 sound slots + speed→volume/pitch mapping), `FContactAudioProcessor` (per-physics-step rising-edge detection per geom pair, 60 ms debounce, impact speed = ball speed / foot lateral speed with the 0.5 m/s shoe threshold), `FCourtAudioPlayer` (pool of 8 `UAudioComponent`s created at setup; no per-event allocation). Score → net-rattle event raised by the director |
| `StreetballHUDWidget.{h,cpp}` | C++-built UMG widget: tier, state, counters, milestone row, progress bar, loose-ball countdown text + ring drawn in `NativePaint` |
| `StreetballWorld.{h,cpp}` | Integration: tracker → director → reset → policy per state → obs (task block, in_control, countdown) → ctrl; per-physics-step audio sampling via the new `USimClock::OnPhysicsStep`; camera + HUD per frame; `Resnapshot()` after resets so interpolation never blends across a teleport. HUD and view target are only created when a player controller exists (not in automation worlds) |
| `Scripts/make_audio_assets.py` | Pure-python WAV synthesis (sine/noise bursts, chain rattle) → imported as `SW_*` sound waves → `DA_CourtAudioBank` created and wired, all headless |
| `sim/tools/sync_policies_to_unreal.py` | Copies `shared/policies/*.onnx` (+ sidecars) and the spec JSONs into `Content/Sim`; warns if a sidecar's obs_spec hash differs |

## Trained policies

`shared/policies/` does not exist yet (L0 still training when this report was written), so every state currently runs `Content/Sim/policies/dummy_policy.onnx` and the loop exercises resets rather than skills. When `l0_stand.onnx` appears: `cd sim && uv run python tools/sync_policies_to_unreal.py`, then rerun the test group; `Streetball.C3.WorldLoop` prints `trained policies present: [l0_stand]` and the world log shows `Policy l0_stand: trained model ...`.

## Decisions / deviations

1. **Scramble is only armed in ball states** (DRIBBLE_*, JUMP_SHOT); STAND and ROAM ignore the ball. A tier that starts with the ball at the hand calls `GrantControl()` so an untouched ball counts as lost after 0.6 s (see tracker note).
2. **Tier 3 runs the crossover policy** (`l2c_crossover`, hand switches every 2–4 clean bounces) rather than separate right/left stages; the PRD lists all three as one tier.
3. **Jump shot: loss of the ball before release goes to SCRAMBLE** (returning to the shot), after release it cannot (the ball is supposed to leave the hands). A fall during a shot counts as a missed attempt. After 20 attempts under 30 %, the 20-shot block restarts.
4. **Pre-release scoring rule** is the training one: ball centre crosses 3.05 m downward within rim radius − 8 cm.
5. **Shoe squeaks** fire on foot touchdown with lateral speed > 0.5 m/s only; quiet touchdowns are suppressed and do not retrigger later.
6. **Camera sideline dolly sits at y = −9.3 m (sim)**, i.e. just inside the fence; the brief said −9.5, which is the fence plane itself.
7. `mj_objectVelocity` is declared in the 4.0 headers but not exported by the shipped import library; body velocities are derived from `cvel` (`UMuJoCoSim::GetBodyLinearVelocitySim`).

## Not verified

* No frame was rendered and no sound was played (headless only): camera motion, HUD layout and audio playback are verified by logic tests, not by eye/ear. `AudioPlayer.PlayedCount` increments only from `Tick`, which the automation tests do not drive.
* Tier 4 (course + saves) and tier 5 (shots) transitions are implemented but only exercised through the generic scramble/reset paths; no trained policy exists to drive a real shot or a 100 m course, so those milestones were not observed end-to-end.
* The HUD countdown ring's `NativePaint` is not exercised without a viewport.
