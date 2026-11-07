# Tier 1 / L0 balance — graduation and Step 4 gate: PASS (2026-11-06, late)

Checkpoint: `sim/runs/l0_v4_eval.pt` (run `l0_v4` @ 29.5 M steps; lineage v1 → v2 → v3 → v4, ~115 M steps in total).
Tags: `interface_sha ccfa18d6f9aaf2a5`, `physics_sha 01a3f59b037ef5e7+1eba556a91fae556`, `push_max 100`, `nan_grads 0`.

## Graduation (sim, `streetball.evaluate`, 200 episodes, deterministic policy, 100 N pushes)

| Metric | Value | Gate |
|---|---|---|
| Success (60 s, feet within 20 cm, quiet speed < 5 cm/s, quiet jitter < 2 cm) | 98.0 % | ≥ 95 % |
| Holds over every 100-episode window | yes | required |
| Falls | 0 % | |
| Mean episode length | 59.2 s | 60 s max |
| NaN-gradient batches | 0 | 0 |

## Step 4 verification gate (Unreal 5.8.4, libmujoco 4.0.0, NNE ORT-CPU) — `DOCS/phase_reports/Step4_gate_unreal.md`

| Check | Result | Gate |
|---|---|---|
| Preset actions (open loop, 5 s) | root 0.0000 cm, joints 0.00000° | < 2 cm, < 1° |
| Live physics (closed loop, 5 s) | root 0.0000 cm, joints 0.00004° | < 2 cm, < 1° |
| Obs builder C++ vs Python | 5.3e-6 max abs | report |
| Action NNE vs onnxruntime | 1.7e-6 max abs | report |
| Foot-contact flags | 0 / 250 steps mismatched | report |
| Inference | 0.082 ms | < 2 ms |

Exported policy: `shared/policies/l0_stand.onnx` → synced as `Content/Sim/policies/balance.onnx`.

## Next

- L1 traversal training started as `runs/l1_v1` (300 M budget, push curriculum, initialised from the L0 actor).
- Later L0 checkpoints (`l0_v4_final.pt`, 49.5 M steps) exist but were not re-gated; the 29.5 M checkpoint is the exported one.
