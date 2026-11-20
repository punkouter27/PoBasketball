# A6 — Axis alignment check: PASS

Conversion: `pos_ue = (x*100, -y*100, z*100)`, `quat_ue(X,Y,Z,W) = (-qx, qy, -qz, qw)`, bone drive `q_bone = toUE(q_sim) * offset`, offsets captured at qpos = 0.

| Check | Result |
|---|---|
| Reference pose orientation error | 0.0000 deg (< 0.1) |
| Reference pose position error | all < 1 mm |
| 90 deg hip flexion / knee flexion / shoulder pitch | anatomically correct in UE mesh space |
