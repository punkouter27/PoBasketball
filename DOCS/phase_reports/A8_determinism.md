# A8 — Warp vs libmujoco determinism: PASS

Scene `scene.xml`, keyframe `stand`, 250 control steps × 10 substeps (dt 0.002), smooth random PD targets. Warp float32 on GPU vs libmujoco float64 on CPU.

| Time | Root pos error | Max joint error | Ball pos error |
|---|---|---|---|
| 1 s | 0.003 cm | 0.009° | 0.00 cm |
| 2 s | 0.022 cm | 0.009° | 0.00 cm |
| 3 s | 0.063 cm | 0.368° | 4.98 cm |
| 4 s | 0.062 cm | 0.265° | 10.90 cm |
| 5 s | 0.062 cm | 0.073° | 17.16 cm |

Max over the run: root 0.074 cm (gate 2 cm), joints 0.533° (gate 1°), ball 17.16 cm (informational).

Warp world-to-world max |Δqpos| over 8 identical worlds: 4.61e-01 (gate 1e-3; Warp sums contact forces with atomics, so it is not bit-exact).
