# Step 4 verification gate - Unreal side

Written by the Streetball.Gate.* automation tests (libmujoco 4.0.0 in UE 5.8.4).

## Live physics (closed loop)

SKIPPED - input file(s) absent: replay: C:/Users/punko/Downloads/CODE_MATT/PoBasketball/shared/golden/replay_l0.json. Set CVars streetball.GateReplay / streetball.GatePolicy or produce them with sim/tools/replay_recorder.py policy and export_onnx.py.

## Preset actions (open loop)

Replay: `C:/Users/punko/Downloads/CODE_MATT/PoBasketball/shared/golden/replay_random.json` (mode random, 250 steps x 10 substeps = 5.0 s)

| Metric | Value | Gate |
|---|---|---|
| Max root position error | 0.0000 cm | < 2 cm |
| Max joint error | 0.00000 deg | < 1 deg |
| Root error at 1 s / end | 0.0000 / 0.0000 cm | - |

**PASS**

