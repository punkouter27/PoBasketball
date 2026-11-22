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

## 09:20 Roadmap: dribble toward the basket, pick up, shoot (user request); decisions and stage 1 (walking dribble)

User goal: dribble while walking toward the basket, then gather the ball and shoot. Existing design already has the pieces
(`l3a_moving_dribble` = dribble family + waypoint/speed command, `l4_jump_shot` + `JUMP_SHOT` director state), all untrained.
User decisions (AGENTS 3-question protocol): (1) **walk first** - a speed curriculum from 0.3-0.8 m/s up to the PRD's 1.5-2.5 m/s;
(2) **close set shot** (stop 1.5-3 m out, two-hand gather, no jump) instead of the pull-up jump shot, for the first shot brain;
(3) **keep the tier ladder** in Unreal (no new director mode); previews via `-StreetballStartTier=4/5`.

Stage 1 changes (affected policy: dribble family; no obs/action/physics change; interface unchanged):
- `L3MovingDribble` (gate `l3a_moving_dribble`) fixes, same reasons as L2 on 11-19: apex target 1.0 -> `apex_target = 0.8` (task input
  and r_apex; the Unreal director already sends 0.8 in every dribble tier); start ball at the level's own spot and h ~ U(0.30, 0.75)
  m with vz from the apex target (was 0.3 m forward and up to 0.95 m: inside the palm); `hand_mode` attribute (default random = old).
- New TRAINING-ONLY level `l3a_walk` (`L3DribbleWalk`): right hand, stationary brain's spot (0.45, 0.30), waypoints 2-6 m away,
  4 per episode, 30 s, no arm-carry/pose style penalties (they pull the dribbling arm to the rest pose), speed stages
  (0.3-0.8) -> (0.5-1.2) -> (0.8-1.6) -> (1.2-2.0) -> (1.5-2.5), promoted when 60 % of finished episodes reach all 4 waypoints
  with the ball in control >= 90 % of the time and no fall.
- Warm start: `runs/dribble_time10d/ckpt_600M.pt` (actor only: different level), critic warm-up 400 iterations, std ~0.05-0.06,
  lr_max 2e-5, anchor - the settings that worked for dribble_time10d.

## 09:45 Stage 1 first hour: `walk_1h` (user: "what can you do with 1 hour" -> option A, a go/no-go test of l3a_walk)

- `_sample_speed`: 75 % current speed band, 25 % from 0.3 m/s up to the current top (keeps the slow walk for the later stop-and-shoot).
- Smoke run found episodes of 2.0 s. Probe (scratch `walk_probe.py`, ckpt_600M frozen, 256 envs): **239 / 256 fell, mean 2.05 s**;
  98 % lost control by ~1.0 s. Cause: the stationary stages never set speed / dir / distance, so the normaliser has std 3e-8 on
  them (a 0.5 m/s command = 5000 sigma) and their first-layer columns are untrained random weights (|w| up to 0.09).
- New `tools/open_task_inputs.py` (UU_AGENT section 3, zero-initialised new inputs): zero the first-layer columns of task slots
  3-6 and set their normaliser to mean 0 / std 1, 1, 1, 3 m; parity: actions identical to the original actor (0 diff).
  `runs/production/dribble_walk_init.pt`. Re-probe: **252 / 256 still dribbling at 12 s, mean 11.9 s, 4 falls** (she stands
  and dribbles, ignoring the command: the starting point PPO needs).
- Same trap exists in Unreal: the 09:00 preview brain (folded normaliser) would blow up on a tier-4 speed command. Do not preview
  tier 4 with it; preview tier 4 only with a brain trained on l3a_walk.
- `l3a_walk` evaluates at speed stage `eval_stage` = 0 (0.3-0.8 m/s): the training level's own check; the PRD jog is the
  `l3a_moving_dribble` gate.
- Run `walk_1h`: `skill_run --level l3a_walk --gate l3a_walk --train-min 48 --ckpt-every-steps 25e6`, extra `--init
  runs/production/dribble_walk_init.pt --init-actor-only --critic-warmup-iters 200 --freeze-norm --init-std 0.05 --kl-target 0.02
  --epochs 2 --lr-max 2e-5 --lr-min 1e-7 --anchor-coef 0.3` (anchor 1.0 -> 0.3: the anchor actor ignores the command, so a strong
  anchor would hold her still). ~12 min critic warm-up, ~36 min learning, ~8 min evals.
- 10:25 `walk_1h` result (`docs/20261121/walk_1h.md`, 200 episodes at 0.3-0.8 m/s): **no-go for PPO alone.** 0 % success,
  0.01 waypoints per episode. ckpt_25M / best.pt (~ the start brain): 21 s episodes, falls 66-70 % (within 30 s), ball control 0.99,
  speed 0.34 m/s, 3 m covered (sway, not walking). model.pt (41 M): falls 95 %, 2.8 s episodes, speed 0.62 m/s. Training after the
  warm-up: speed 0.29 -> 0.57 m/s while episodes fell 28 -> 3.1 s and the waypoint distance never shrank (3.7 m): PPO pushed the legs
  to move but the dribble network has no gait to find. Throughput 12.7k fps on l3a_walk (vs 27k on l2a_time).
- Next (proposed): borrow the gait of the production `locomotion` brain (same obs/action layout) instead of discovering one:
  probe a composite teacher (legs + torso from locomotion, arms from dribble) and, if it carries the ball, behaviour-clone it into
  the dribble network before PPO.

## 10:30-12:05 Review page (user: REVIEW) - `SCREENSHOTS/20261121_review/index.html`

- Game captures (engine `-StreetballCapture`, seed 7, tier 3): new dribble brain vs dribble_drift250. First 40 s: new 1 hard reset / 4 loose
  balls, previous 7 / 17. GIF bursts re-recorded at `slomo 0.25` (12 fps game time).
- Editor: Court holds 5 placed actors (sun, sky light, sky atmosphere, PCGVolume, StreetballWorld); everything else spawns at Play.
  StreetballWorld has no root component (no transform, no gizmo). Simulate-In-Editor session (seed 7): spectator moved 3 m and sun rotated
  mid-game -> director timeline identical to the untouched game run (22.44 / 24.16 / 24.28 / 27.06 s, same resets). Spawned spectators
  re-place themselves each frame (the move does not stick). PIE after moving the PCGVolume 12 m + rotating the sun: runs normally.
- Capture lessons: `-ExecutePythonScript` quits the editor after the script (use `-ExecCmds="py <file>"`); editor viewport screenshots
  only complete on a forced redraw when the editor is in the background; window-only capture (PrintWindow on the editor HWND) works.
  A desktop screen capture was tried once and grabbed a browser window instead; it was deleted immediately and never published.

## 12:13 `dribble_45` (user: "training as needed for another 2.5 hours"): push the stationary dribble from 71 % toward the 85 % gate

Affected policy: dribble (stationary) only; nothing exported unless the gate passes. No obs/action/physics change.
- `train.py`: `--horizon0` (l2a_time starting horizon; the curriculum state is not saved in a checkpoint) and `--drift-w` (L2 drift
  penalty weight). Defaults leave behaviour unchanged.
- Resume `runs/dribble_time10d/ckpt_600M.pt` on the SAME level (l2a_time), so actor, critic, optimiser and std all load (no warm-up).
  Horizon starts at 45 s (= gate; 10d never got past 38 s), drift_w 2.0 -> 4.0 (drift ends 28 % of gate episodes), same PPO settings as
  10d (KL 0.02, epochs 2, lr_max 2e-5, lr_min 1e-7, anchor 1.0 to ckpt_600M). 135 min training + gate evals every 25 M.
- 13:00 `dribble_45` stopped at 18 M (my error): **collapsed in the first 20 iterations** (episodes 1.2 s, KL 0.29 at the 1e-7 LR floor,
  value loss 7.8k). Cause: the resume omitted `--freeze-norm` (10d had it). ckpt_600M's normaliser count is only 1e6 (set by
  onnx_to_ckpt) and each iteration adds ~1e5, so the stats re-fitted within a few iterations: means moved up to 5.1 sigma, 25 inputs
  > 0.5 sigma; the shifted inputs broke the actor and its failures skewed the stats further. Kept on disk.
- `dribble_45b`: identical plus `--freeze-norm`, 90 min training (budget ends ~14:45 with evals).
- 14:08 check (45b): driver alive, it 502 / 49 M steps, 13.8k fps (45 s episodes; half of 10d's rate, so ~75 M steps by the end).
  Training (stochastic, 45 s horizon): episode 26-30 s, return 4.2-4.8k, streak 16-19, 41-53 % of episodes reach 45 s; KL 0.003-0.008,
  value loss 310-570. Flat, no collapse; a small dip at 49 M (episode 25.9 s, streak 15.9). Gate evals of ckpt_25/50/75M after ~14:31.
- 14:44 `dribble_45b` result (`docs/20261121/dribble_45b.md`, ~70 M steps, gate 200 episodes): **no real gain.** ckpt_25M 72.5 %
  (drift 24.5 %), ckpt_50M 67.5 % (29 %), best.pt 59.5 %, model.pt 60.5 % (36.5 %); falls 0-1 %. ckpt_600M (71 %, drift 28.5 %) stays
  the reference: 72.5 % is inside the +-3 % noise of 200 episodes. Doubling drift_w and 45 s episodes did not move drift.
- Why (new finding): drift is **not observable**. shared/obs_spec.json has no position or start-spot input (gravity, pelvis vel/angvel,
  joints, ball rel, contacts, height, countdown, task) and the actor is a memoryless MLP, so the drift penalty can only teach "move less",
  never "step back to the spot". Proposal (user decision; obs layout unchanged): put the vector to the start spot into the dribble task
  block's existing dir_x / dir_y / distance slots when speed_cmd = 0 (stationary = "stay at this point", the same meaning as the walk
  waypoint), zero-init those inputs with tools/open_task_inputs.py, train; mirror in the Unreal director (tier 3 sends the reset spot).

## 15:00 Make drift visible (user: "make drift visable")

Affected: dribble family (L2 stationary levels + gate l2a_dribble_r; L3 walking keeps its waypoint), Unreal director tier-3 task fields.
Obs/action LAYOUT unchanged (interface hash unchanged); the meaning of task slots dir_x / dir_y / distance_m is extended: for the
stationary dribble (speed_cmd 0) they are the vector from the pelvis back to its anchor ("stay at this point" = a waypoint at your own
spot; same encoding as L1/L3 waypoints: unit direction in the heading frame + distance in m; zero direction when distance < 1 mm).
- Sim: `L2Dribble.anchor_obs = True` fills them from `start_xy` (pelvis at reset). Old checkpoints (before this entry) have untrained
  weights on these slots and must go through `tools/open_task_inputs.py --slot 4:.. --slot 5:.. --slot 6:..` before evaluation.
- Unreal: director anchors the pelvis xy whenever DRIBBLE_STATIONARY starts (reset or scramble hand-back) and sends the same vector.
- `tools/open_task_inputs.py --keep-critic`: also zeroes the critic's first-layer columns and keeps critic / optimiser / std (resume
  without warm-up). The in-game preview is re-exported from the opened ckpt_600M (identical actions) so Unreal never feeds the new
  inputs to a brain with untrained weights.
- Applied + verified: `runs/production/dribble_anchor_init.pt` (open_task_inputs --keep-critic, slots 4:0.7 5:0.7 6:0.25; parity 0 diff).
  Gate level task values over 10 s (256 envs): distance mean 0.246 m, max 0.749 m, direction unit or zero. Preview `dribble.onnx`
  re-exported from it (ORT 2.1e-6) and synced; UE build OK; Unreal `Streetball.*` 22/22; CPU tests 13/13.
- NOT trained yet (user: finish up). Next run: `skill_run --level l2a_time --gate l2a_dribble_r` with `--init
  runs/production/dribble_anchor_init.pt --freeze-norm --horizon0 45 --kl-target 0.02 --epochs 2 --lr-max 2e-5 --lr-min 1e-7
  --anchor-coef 1.0 --assist-anneal-steps 1` (drift_w default 2.0), 2-3 h; compare with ckpt_600M 71 %.

## 21:25 `dribble_anchor10` (user: "train this dribbling another 10 hours"): first training with observable drift

Affected policy: dribble (stationary, right hand) only. State machine rows, interface, physics: unchanged. Nothing exported unless the gate passes.
- Start check: `runs/production/dribble_anchor_init.pt` on `l2a_dribble_r`, 200 episodes: 68.5 % success, falls 0 %, drift 30.5 %.
- Run: the 15:00 plan, 600 min of training (evals of every checkpoint follow): `skill_run --level l2a_time --gate l2a_dribble_r`,
  extra `--init runs/production/dribble_anchor_init.pt --freeze-norm --horizon0 45 --kl-target 0.02 --epochs 2 --lr-max 2e-5
  --lr-min 1e-7 --anchor-coef 1.0 --assist-anneal-steps 1`. Reference: ckpt_600M 71 %, gate 85 % + holds 100.
- Found before the run (Unreal, not fixed): tier 3 without `-StreetballDribbleHand=right` sends left hand / hand switches, which this
  brain never trained on: 34 resets in ~1 min. With the flag, seed 7: first dribble 22.44 s (same as 09:00), 3 resets in 60 s.
- Found before the run (Unreal, not fixed): `Content/Sim/court.xml` (11-17) lacks the soft ball-palm contact pairs of
  `sim/assets/court.xml` (50ab00d, 11-19), so the game's dribble physics differs from the training physics.
