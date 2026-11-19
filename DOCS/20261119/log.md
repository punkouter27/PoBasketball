# 2026-11-19

## Production balance swapped to the posture brain (user-approved gate waiver)

User decision ("use new brain", options 1 + 2): promote `runs/l0_v2w_posture_0900/ckpt_375M.pt` to production
`balance` / `l0_stand` although it **does not pass** the L0 gate (UU_AGENT §4 waived by the user).

| Brain | Success (200 ep, 100 N) | Holds 100 | Falls | Torso upright |
|---|---|---|---|---|
| previous `balance_v1w` | 99.0 % | yes | 0.5 % | 0.875 |
| new `balance` (ckpt_375M) | 81.5 % | **no** | 10.0 % | **0.978** |

Affected policies: `balance`, `l0_stand` (shared/policies + Unreal Content/Sim/policies). `locomotion` unchanged.
Interface 32f5b79d3216e8a3 and physics 319cd05af6f00d17+c1c2207912c56781 unchanged, 0 NaN gradients, 375 M steps.
- Export: ORT vs torch 1.32e-6. Replays re-recorded: replay_balance, replay_l0_stand, replay_l0 (final pelvis 0.943 m).
- Side-by-side / rollback: previous brain kept as `shared/policies/balance_v1w.onnx` + `shared/golden/replay_balance_v1w.json`
  (both shown in the web viewer); checkpoint `sim/runs/production/balance_v1w.pt`.
- Unreal `Streetball.*` all pass: closed loop 0.0000 cm / 0.00001 deg, inference 0.031 ms. CPU CI tests 10 / 10.
- Open: recover >= 95 % balance on this posture (proposed 1 h fine-tune with smaller updates + KL-to-start penalty).

## Balance-recovery fine-tune (planned, 1 h)

Goal: bring production `balance` (posture brain, 81.5 %) back to >= 95 % on L0 while keeping torso_upright ~0.97.
Affected policy: `balance` / `l0_stand` only if a checkpoint passes; otherwise nothing changes. Interface unchanged.
Code: `ppo.py` gains `lr_min` (adaptive-LR floor, was hard-coded 1e-5) and `anchor_coef` (penalty
`coef * mean(sum((mu - mu_anchor)^2))` toward the frozen starting actor); `train.py` gains `--epochs`, `--lr-min`,
`--anchor-coef`. Defaults reproduce the old behaviour exactly.
Run `l0_posture_recover`: init `runs/production/balance_posture.pt` (actor only), frozen normaliser, 60-iter critic
warm-up, std 0.02 / toe 0.01, no v2 penalties, full v2 posture reward, epochs 2, lr 1e-5 (max 1e-5, min 1e-6),
anchor 5.0, 40 min training, a checkpoint every 5 M steps, each evaluated over 200 episodes.

### Result (l0_posture_recover, 10:20-11:18): no improvement, production unchanged

40 min / ~50 M steps, 0 NaN. All 12 checkpoints are 64-81.5 % (best ckpt_10M 81.5 %, the same as the start brain), with falls 8-13 % and torso
0.965-0.980. The anchor held the posture, but PPO found no balance gain: the result is flat noise around the start brain.
- KL is hypersensitive at std 0.019: an action change of about 0.003 already reads as KL 0.01, so the adaptive LR sits on its floor.
  Last night's "large updates" were largely this artifact, not oversized steps.
- Success != 1 - falls: about 8-10 % of episodes fail without falling (foot drift >= 20 cm / foot-move termination, or quiet speed >= 5 cm/s / jitter >= 2 cm).
  evaluate.py does not report the failure reason yet.
Report: DOCS/20261119/posture_recover.md.

## Failure breakdown (evaluate.py now reports `fail_reasons`)

L0 levels expose `episode_fail_reasons()`; env info carries `fail/<reason>`, and evaluate.py writes the share of all episodes
that failed each condition (not exclusive). 200 episodes, 100 N:

| Brain | Success | Fell | Feet 20-35 cm off (standing) | Quiet speed | Quiet jitter | Failed without falling |
|---|---|---|---|---|---|---|
| `balance_v1w` (old) | 99.0 % | 0.5 % | 0.5 % | 1.0 % | 0.5 % | 0.5 % |
| `balance` (posture, production) | 82.0 % | 10.0 % | 8.0 % | 3.5 % | 2.5 % | 8.0 % |

Reading: the posture brain loses balance both ways. It falls (10 %), and it steps its feet more than 20 cm to recover (8 %). This fits
losing the hip strategy: the v2 torso term applies during push recoveries too, so bending at the waist to absorb a shove is
penalised. Python tests 13 / 14 (same `test_warp_vs_cpu_drift` failure as before).
