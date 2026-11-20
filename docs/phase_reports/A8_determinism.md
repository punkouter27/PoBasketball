# A8 — Warp vs libmujoco determinism: PASS

Scene `scene.xml`, keyframe `stand`, 250 control steps × 10 substeps (dt 0.002), smooth random PD targets. Warp float32 on GPU vs libmujoco float64 on CPU.

| Time | Root pos error | Max joint error | Ball pos error |
|---|---|---|---|
| 1 s | 0.000 cm | 0.000° | 0.00 cm |
| 2 s | 0.001 cm | 0.001° | 0.00 cm |
| 3 s | 0.001 cm | 0.006° | 0.04 cm |
| 4 s | 0.002 cm | 0.003° | 0.12 cm |
| 5 s | 0.001 cm | 0.003° | 0.09 cm |

Max over the run: root 0.005 cm (gate 2 cm), joints 0.023° (gate 1°), ball 0.13 cm (informational).

Warp world-to-world max |Δqpos| over 8 identical worlds: 3.73e-01 (gate 1e-3; Warp sums contact forces with atomics, so it is not bit-exact).
