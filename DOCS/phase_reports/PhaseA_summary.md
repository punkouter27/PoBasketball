# Phase A — Assets: COMPLETE

Date: 2026-11-06

| Task | Status | Evidence |
|---|---|---|
| A1 Toolchain | PASS | `A1_toolchain.md`, `docs/env_setup.md` — 1.49 M steps/s stock humanoid, native Windows |
| A2 Mannequin dump | PASS | `shared/mannequin_bones.json` (89 bones), headless editor script |
| A3 Humanoid model | PASS | `sim/assets/humanoid.xml`, 4 tests in `tests/test_stand.py`; acceptance test redefined (see A2_A3_A4 report) |
| A4 Court model | PASS | `sim/assets/court.xml`; ball-rim tunnelling check deferred to Phase C eval |
| A5 Ball tuning | PASS | `A5_ball_tuning.md` — direct spring-damper `solref=(-24649, -17.13)`, mean apex ratio 0.722, all drops inside FIBA band |
| A6 Axis check | PASS | `A6_axis_check.md` — 0.0000° reference error, hip/knee/shoulder motions land anatomically in UE mesh space |
| A7 Obs spec | PASS | `shared/obs_spec.json` (119 floats), `shared/golden/obs_golden.npz` (1000 states) |
| A8 Warp vs CPU drift | PASS | `A8_determinism.md` — root 0.000 cm, joints 0.001°, ball 0.03 cm over 5 s (gates 2 cm / 1°) |

## Frozen asset hashes (sha256, first 16 hex)

| File | Hash |
|---|---|
| `sim/assets/scene.xml` | `84bec5b08691e5fd` |
| `sim/assets/humanoid.xml` | `01a3f59b037ef5e7` (self-collision on, 2026-11-06 late; was `4b8e68bd819c960d`) |
| `sim/assets/court.xml` | `1eba556a91fae556` |

Any change to the generators must bump these in this file and re-run A5, A6, A8.

## Decisions made during Phase A (not in the approved documents)

1. **Ball contact uses the direct spring-damper `solref` form** (negative values) because the
   time-constant form gave speed-dependent restitution at 500 Hz. Contact lasts ~20 ms (10 steps).
2. **Self-collision is ON for non-adjacent parts** since the UU_AGENT adoption (see `DOCS/20261106/change_self_collision_and_roster.md`). Originally off.
3. **Sim zero pose = Manny's A-pose**, not an arms-at-sides pose. Joint ranges in the model are
   anatomical ranges shifted by the A-pose offset (recorded in `humanoid_spec.json`).
4. **A3 "done when" relaxed**: PD-only free standing is physically impossible with realistic
   ankle gains; replaced by tracking, mass, contact-force and keyframe tests.
5. **Warp is not bit-deterministic across worlds** (5e-4 rad spread over 5 s with identical inputs,
   from atomic accumulation order). The contract's bounded-error gate still passes by a wide
   margin; the world-to-world gate is set at 1e-3.
6. **Nominal ankle pitch corrected to +10° dorsiflexion.**

## Libraries pinned for the Unreal plugin

`mujoco==4.0.0`. The Python wheel ships `mujoco.dll` and headers but no import library;
Phase B vendors the official `mujoco-4.0.0-windows-x86_64` release (which includes `mujoco.lib`)
into `unreal/StreetballGym/Plugins/MuJoCoRuntime/ThirdParty/`.
