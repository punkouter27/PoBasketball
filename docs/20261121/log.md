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
