# Step 4 verification gate - Unreal side

Written by the Streetball.Gate.* automation tests (libmujoco 4.0.0 in UE 5.8.4).

## Live physics (closed loop)

Replay: `C:/Users/punko/Downloads/_CODEMATT/PoBasketball/shared/golden/replay_balance.json`, policy: `C:/Users/punko/Downloads/_CODEMATT/PoBasketball/shared/policies/balance.onnx` (250 steps x 10 substeps = 5.0 s, closed loop in Unreal with NNE ORT-CPU)

| Metric | Value | Gate |
|---|---|---|
| Max root position error vs recorded | 0.0000 cm | < 2 cm |
| Max joint error vs recorded | 0.00002 deg | < 1 deg |
| Root error at 1 s / end | 0.0000 / 0.0000 cm | - |
| Max abs obs diff (C++ builder vs Python) | 8.196e-07 (slot 85, step 12) | report |
| Max abs action diff (NNE vs onnxruntime) | 8.196e-07 | report |
| Foot-contact flag mismatched steps | 0 / 250 | report |
| Mean inference | 0.073 ms | < 2 ms |
| Lowest pelvis height (athlete upright) | 0.929 m | >= 0.70 m |

**PASS**

### 5 s rollout gate (UU_AGENT section 4) - report only, thresholds to be set from these baselines

Level `l0_stand`, 5.00 s.

| Metric | Value |
|---|---|
| Max root linear velocity error vs recorded | 3.00e-07 m/s |
| Max whole-body angular momentum error vs recorded | 5.17e-06 kg m^2/s |
| Max whole-body angular momentum (Unreal) | 7.449 kg m^2/s |
| Foot sliding while planted: max / mean | 0.261 / 0.008 m/s (498 samples) |
| Max ground penetration (any geom vs floor) | 1.19 mm |
| Foot contact flips (chatter): left / right | 0 / 0 (0.0 / 0.0 per s) |

## Preset actions (open loop)

Replay: `C:/Users/punko/Downloads/_CODEMATT/PoBasketball/shared/golden/replay_balance.json` (mode policy, 250 steps x 10 substeps = 5.0 s)

| Metric | Value | Gate |
|---|---|---|
| Max root position error | 0.0000 cm | < 2 cm |
| Max joint error | 0.00000 deg | < 1 deg |
| Root error at 1 s / end | 0.0000 / 0.0000 cm | - |

**PASS**

