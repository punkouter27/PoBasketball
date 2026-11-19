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
