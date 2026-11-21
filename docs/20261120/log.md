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

## ~23:40 dribble_time10 stopped at 13 M (17 min): exploration std 0.15 was far above the trained std -> restart as dribble_time10b

- Symptom: training episodes 2.8-3.3 s (gate eval of the same actor: 17 s); return 517 -> 393 after the critic warm-up; KL 0.04-0.06
  with the LR on its 1e-5 floor. Already 3.3 s during the frozen-actor critic warm-up, so the actor was not the cause.
- Probe (scratch `std_probe.py`: frozen actor, mu + std*N(0,1), l2a_dribble_r, 256 envs, 10 s, 150 N pushes):
  | std | survive 5 s | survive 10 s | mean ep |
  |---|---|---|---|
  | 0.00 | 85 % | 68 % | 8.6 s |
  | 0.05 | 77 % | 51 % | 7.8 s |
  | 0.10 | 44 % | 13 % | 5.3 s |
  | 0.15 | 12 % | 0 % | 3.3 s |
  The ONNX export drops log_std, so the trained std is unknown; the 11-20 smoke test (original ckpt, its own std: 87 % reached 5 s)
  puts it at <= 0.05. Lesson: a warm start rebuilt from ONNX needs `--init-std` near the trained std, not the 0.5 default or a guess.
- `dribble_time10` kept (13 M steps, not deleted).
- `dribble_time10b`: same as dribble_time10 but `--init-std 0.05 --epochs 2 --lr-min 1e-6` (KL ~ 1/std^2: at std 0.05 a 1e-5 floor
  would still overshoot; settings of the 11-19 l0_quiet_posture fine-tune that passed), `--train-min 480` (evals ~1 h after).

## ~23:52 dribble_time10b stopped at 9 M: first actor update at lr 3e-4 broke the actor -> dribble_time10c with lr_max 2e-5

- Critic warm-up (actor frozen, std 0.05): horizon 5 -> 7.5 -> 11.2 s within 3 M steps, episodes up to 10.6 s, return 1937. The std fix works.
- First actor iterations (it 61+): the LR starts at --lr 3e-4 (clamped only to lr_max 1e-3); at std 0.05 that update gave KL 0.07-0.11 and
  episodes fell to 3.2 s (return 341) before the adaptive schedule cut the LR. Kept (not deleted).
- `dribble_time10c`: as 10b plus `--lr-max 2e-5 --lr-min 1e-7` (ppo.py clamps the LR to lr_max when actor updates start; the critic
  warm-up keeps 3e-4). At std 0.05 a KL of 0.02 is a mean action step of ~0.002 per joint, so the LR will sit near 1e-6..1e-5. `--train-min 470`.

## 00:04 dribble_time10c stopped at 20 M: the fresh critic was not ready -> dribble_time10d with a 400-iteration critic warm-up + anchor

- 10c (std 0.05, lr_max 2e-5): first update fine (it 75: ep 9.8 s, return 1727), then a steady slide to ep 3.3 s / return 446 by it 195
  with KL only 0.001-0.005 (streak 5.9 -> 0.7, in_control 0.98 -> 0.75).
- Cause: value loss during the 60-iteration critic warm-up 1029 -> 795 and still falling (it 195: 473), clip fraction 0.42 at it 90; the
  advantages were mostly critic error. The other machine's dribble_time resumed with its trained critic (not in the ONNX). Kept.
- `dribble_time10d`: as 10c plus `--critic-warmup-iters 400` (~35 min, until the value loss plateaus) and `--anchor-coef 1.0`
  (penalty toward the start actor, as in the 11-19 l0_quiet_posture fine-tune that passed). `--train-min 450`, training ends ~07:35, gate evals after (~1 h).
- 00:23 check (10d): driver alive, it 280 / 27.5 M steps, ~27k fps, still in the critic warm-up (actor frozen until it 400).
  Frozen-actor baseline at horizon 16.9 s: return ~1800, episode ~10.2 s, streak ~6.4. Value loss 908 (it 25) -> 707 (100) -> ~555-590 (it 225-275),
  levelling off. Nothing abnormal.
- 00:35 check (10d, it 400-500, first 100 actor iterations): **sliding again, slower than 10c.** Return 1850 -> 1257, episode 10.5 -> 7.5 s,
  streak 6.5 -> 4.2, in_control 0.99 -> 0.96; KL 0.005-0.022, clip 0.07-0.26, LR at its 2e-5 cap; value loss 650 -> 1226 (rising as the
  return distribution shifts). Not restarted: this lineage has dipped and recovered before (dribble_overnight 31 % -> 5 % -> 43 %;
  dribble_drift's gate episodes 4.4 -> 10.2 s over 250 M), and every 50 M checkpoint is gate-evaluated against the 9 % start brain.
  Reading: PPO's own objective (return) falls, so this is an optimisation problem, not reward hacking: the advantage estimate over
  ~850-step horizons with a critic that never saw this actor's returns is too noisy for a policy this precise (std 0.05).
  Options if it has not turned by ~100 M steps (user to choose): (a) restart with a stronger anchor (5.0) + lr_max 5e-6 (safe, slow);
  (b) shorter credit horizon: cap l2a_time at 7.5 s (where the critic is accurate) and let drift_w do the long-episode work;
  (c) behaviour cloning from the start brain's own successful gate episodes (filtered BC), then PPO with --init.
- 01:23 check (10d): driver alive, it 1263 / 124 M steps; ckpt_50M, ckpt_100M saved. **Dip turned:** low point it 600 (59 M: return 1147,
  episode 7.0 s), now return 1948 / episode 10.9 s (it 1250), above the frozen-actor baseline (~1850 / 10.3 s). Value loss back to ~710
  (peak 1250). Clean streak 5.1 (baseline 6.4) still below; in_control 0.98. KL 0.009-0.02 at the 2e-5 LR cap; horizon still 16.9 s
  (no promotion yet: needs > 60 % survival). No restart needed; options (a)-(c) above stay on hold.
- 02:23 check (10d): driver alive, it 2255 / 221 M steps; ckpts 50-200M saved. **Steady improvement:** return 2064 -> 2734, training
  episode 11.5 -> 14.5 s (of a 16.9 s horizon), clean streak 5.2 -> 9.2 (start brain 6.4), in_control 1.00, survival EMA 0.24 -> 0.59;
  **horizon promoted 16.9 -> 25.3 s** at ~it 2250 (first promotion since the warm-up). Value loss 380-830, KL 0.004-0.03 (LR mostly at
  the 2e-5 cap, briefly cut to 3-9e-6). Nothing abnormal.
- 03:23 check (10d): driver alive, it 3246 / 320 M steps; ckpts 50-300M saved. At the 25.3 s horizon: training episode 14.6 -> ~19 s,
  return 2748 -> ~3600 (peak 3861 @275M), clean streak 9.4 -> ~13.5 (peak 14.7), in_control 1.00, survival EMA 0.27-0.45 (promotion to
  38 s needs > 0.60). Plateau-ish since ~260 M (ep 18-20 s). Value loss 320-660, KL 0.008-0.03. Nothing abnormal.
- 04:23 check (10d): driver alive, it 4240 / 417 M steps; ckpts 50-400M saved. **Horizon promoted 25.3 -> 38.0 s** at ~it 4110 (~404 M,
  survival EMA reached 0.58-0.60). At 38 s: training episode 25.2 s, return 4803, clean streak ~19.5-20 (start brain 6.4), in_control 1.00.
  Before the promotion (it 3220-4060): episode 19.4 -> 21.2 s, return 3678 -> 4071. Value loss 260-470, KL 0.008-0.037. Nothing abnormal.
- 05:23 check (10d): driver alive, it 5244 / 515 M steps; ckpts 50-500M saved. Plateau at the 38 s horizon: training episode 23-27 s,
  return 4390-5126, clean streak 15-19.5 (dip to 14.7 @489M, back to 19.1 @509M), in_control 1.00, survival EMA 0.28-0.40 (no promotion
  to 45 s). Value loss 450-690, KL 0.009-0.041. No collapse; nothing abnormal.
- 06:23 check (10d): driver alive, it 6255 / 614 M steps; ckpts 50-600M saved. Still on the 38 s plateau, slowly up: training episode
  25-28 s (peak 27.9 @585M), return 4.8-5.3k, clean streak 16-19 (19.2 @599M), in_control 1.00, survival EMA 0.34-0.45. Value loss
  410-600, KL 0.009-0.034 (LR cut to 4-9e-6 at times). Training ends ~07:35, then gate evals of 14 checkpoints. Nothing abnormal.
- 07:23 check (10d): driver alive, it 7260 / 714 M steps (437 of 450 min). Flat on the 38 s plateau since ~550 M: training episode 25-28 s,
  return 4.8-5.3k, clean streak 17-19, survival EMA 0.34-0.43, std 0.049. Value loss 400-660, KL 0.006-0.028. Training ends ~07:36;
  the driver then gate-evaluates ~16 checkpoints (200 episodes each). Nothing abnormal.

## 07:54 dribble_time10d result: gate l2a_dribble_r 9 % -> **71 %** (ckpt_600M); not passed (needs 85 % + hold 100)

Full table: `docs/20261121/dribble_time10d.md` (200 episodes per checkpoint, 45 s, new near-the-spot rule).
| Checkpoint | Success | Falls | Episode s | Clean streak | pelvis_drifted |
|---|---|---|---|---|---|
| start brain (dribble_drift_250M, 100 eps) | 9 % | 2 % | 17.1 | 9.9 | 88 % |
| ckpt_200M | 14 % | 9.5 % | 19.1 | 12.6 | 75.5 % |
| ckpt_300M | 31.5 % | 1 % | 25.6 | 17.9 | 67.5 % |
| ckpt_400M | 57 % | 2 % | 29.4 | 21.0 | 39.5 % |
| **ckpt_600M** | **71 %** | **0 %** | 30.8 | 21.6 | **28.5 %** |
| ckpt_700M / model.pt | 58.5 % / 54 % | 1 % / 0.5 % | 30.4 / 29.0 | 20.7 / 19.7 | 38.5 % / 43.5 % |
| best.pt | 64.5 % | 1 % | 30.8 | 21.0 | 29.5 % |

- The gate climbs with the training horizon (16.9 -> 25.3 s at ~220 M, -> 38 s at ~404 M: the 400 M jump), then plateaus at 57-71 %
  (ckpt_600M looks like the good end of the noise: 650/700 M are back at 58.5 %).
- **Only blocker left: pelvis drift** (> 0.75 m from the start) ends 28-40 % of gate episodes; falls 0-3 %, ball lost 0-1 %, in_control 1.00.
- Nothing exported or promoted (UU_AGENT: export only after the gate). `runs/dribble_time10d/ckpt_600M.pt` is the candidate warm start; it
  carries its own critic + optimiser + std, so a resume needs none of the ONNX-rebuild workarounds above.
- Proposed next (user decision): resume from ckpt_600M with the horizon at 45 s (= the gate) and a stronger drift term in `l2a_time`
  (drift_w 2.0 -> 4.0, or a quadratic drift cost near 0.75 m), 3-4 h, gate every 50 M.
