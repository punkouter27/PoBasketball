# A8 — Warp vs libmujoco determinism: PASS

Scene `scene.xml`, keyframe `stand`, 250 control steps × 10 substeps (dt 0.002), smooth random PD targets. Warp float32 on GPU vs libmujoco float64 on CPU.

| Time | Root pos error | Max joint error | Ball pos error |
|---|---|---|---|
| 1 s | 0.001 cm | 0.002° | 0.00 cm |
| 2 s | 0.007 cm | 0.005° | 0.00 cm |
| 3 s | 0.008 cm | 0.062° | 0.04 cm |
| 4 s | 0.014 cm | 0.038° | 0.09 cm |
| 5 s | 0.028 cm | 0.043° | 0.11 cm |

Max over the run: root 0.030 cm (gate 2 cm), joints 0.147° (gate 1°), ball 0.11 cm (informational).

Warp world-to-world max |Δqpos| over 8 identical worlds: 8.20e-04 (gate 1e-3; Warp sums contact forces with atomics, so it is not bit-exact).
