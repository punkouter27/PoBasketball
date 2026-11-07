# Step 4 verification gate - Unreal side

Written by the Streetball.Gate.* automation tests (libmujoco 4.0.0 in UE 5.8.4).

## Live physics (closed loop)

Replay: `C:/Users/punko/Downloads/CODE_MATT/PoBasketball/shared/golden/replay_l0_stand.json`, policy: `C:/Users/punko/Downloads/CODE_MATT/PoBasketball/shared/policies/l0_stand.onnx` (250 steps x 10 substeps = 5.0 s, closed loop in Unreal with NNE ORT-CPU)

| Metric | Value | Gate |
|---|---|---|
| Max root position error vs recorded | 0.0000 cm | < 2 cm |
| Max joint error vs recorded | 0.00004 deg | < 1 deg |
| Root error at 1 s / end | 0.0000 / 0.0000 cm | - |
| Max abs obs diff (C++ builder vs Python) | 5.336e-06 (slot 38, step 129) | report |
| Max abs action diff (NNE vs onnxruntime) | 1.669e-06 | report |
| Foot-contact flag mismatched steps | 0 / 250 | report |
| Mean inference | 0.082 ms | < 2 ms |

**PASS**

## Preset actions (open loop)

Replay: `C:/Users/punko/Downloads/CODE_MATT/PoBasketball/shared/golden/replay_l0_stand.json` (mode policy, 250 steps x 10 substeps = 5.0 s)

| Metric | Value | Gate |
|---|---|---|
| Max root position error | 0.0000 cm | < 2 cm |
| Max joint error | 0.00000 deg | < 1 deg |
| Root error at 1 s / end | 0.0000 / 0.0000 cm | - |

**PASS**

