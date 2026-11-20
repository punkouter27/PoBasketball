# A5 — Ball tuning: PASS

Ball-floor `solref = (-24649.0, -17.130)` (direct spring-damper, omega=157.0 rad/s, zeta=0.0546, contact ~20 ms), timestep 0.002.

| Test | Result |
|---|---|
| 1.80 m drop apex | 1.270 m (target 1.30 ± 0.05) |
| 10 random drops 0.8–2.5 m, apex ratio | mean 0.722, min 0.703, max 0.760 (mean target 0.722 ± 0.02; every drop inside FIBA band 0.667–0.778) |

Note: single-drop restitution varies about ±3 % with impact phase relative to the 2 ms step. This is inside the FIBA tolerance and is identical in training and runtime (same timestep).
