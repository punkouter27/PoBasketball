# A8 — Warp vs libmujoco determinism: PASS

Scene `scene.xml`, keyframe `stand`, 250 control steps × 10 substeps (dt 0.002), smooth random PD targets (seed 0). Warp float32 on GPU (8 worlds) vs libmujoco float64 on CPU. Errors are the worst world at each time.

| Time | Root pos error | Max joint error | Ball pos error |
|---|---|---|---|
| 1 s | 0.000 cm | 0.001° | 0.00 cm |
| 2 s | 0.001 cm | 0.001° | 0.00 cm |
| 3 s | 0.001 cm | 0.007° | 0.05 cm |
| 4 s | 0.002 cm | 0.003° | 0.34 cm |
| 5 s | 0.002 cm | 0.028° | 0.33 cm |

Max over the run (worst world): root 0.005 cm (gate 2 cm), joints 0.028° (gate 1°), ball 0.38 cm (informational).

World-to-world (identical inputs, same device): start 0.0e+00, after the first control step 3.0e-10 (gate 1e-06: round-off only), over the run root 0.006 cm and joints 0.028° (gates 2 cm / 1°), ball 0.46 cm (informational). Why the worlds are not bit-identical: docs/phase_reports/A8_root_cause.md.
