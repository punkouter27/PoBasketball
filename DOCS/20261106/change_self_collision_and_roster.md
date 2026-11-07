# Change record — self-collision ON, policy roster consolidated (2026-11-06, late)

User decisions: (1) enable self-collision, (2) follow the UU_AGENT roster ("best practice"), (3) falls stay hard resets (no get-up policy).

## Policies touched (UU_AGENT §3 "before any change")

| Change | Kind | Policies touched | Action taken |
|---|---|---|---|
| Humanoid self-collision for non-adjacent parts; hip adduction limit −30° → −15°; humanoid contact `solref 0.006` | body physics | all five families (only L0 had training) | L0 restarted as `runs/l0_v4` from the `l0_v3` checkpoint (17.7 M steps on old physics; actor+critic carried over, tagged with the new physics sha) |
| Dribble family task-block layout unified (L2a/b/c + L3a) | interface (task block only, base 107 untouched) | dribble (untrained) | layout frozen in `shared/transition_table.json` |
| Roster: 8 per-level exports → 5 families (balance, locomotion, dribble, scramble, shot) | rules / director rows | director in Unreal (policy file names) | `shared/transition_table.json` v1 written; Unreal director to load it |
| Graduation gate: 100 straight episodes + zero NaN-gradient batches | tooling | none | `evaluate.py`, `ppo.py`, `export_onnx.py` (export refuses tainted checkpoints) |
| Checkpoint tags `interface_sha`, `physics_sha`, `steps`, `nan_grads` | tooling | none | `train.py` |

## Physics change details

- `humanoid.xml`: geoms `contype=1 conaffinity=1` (MuJoCo `filterparent` removes parent–child and welded pairs); explicit excludes for pelvis–calf, torso–lowerarm, pelvis–hand.
- Verified by `sim/tests/test_penetration.py` (6 tests): primitives only; siblings collide (legs crossed produce a contact); no overlap at rest; no overlap with every joint at either limit; deepest contact under 4 s of random PD targets ≤ 1 cm (two seeds).
- The random-motion test originally failed at 18.7 mm for palm–floor slaps; stiffer humanoid contact (`solref 0.006 1`, `solimp 0.95 0.99 0.001`) brought it inside 1 cm.
- Re-verified: A6 axis check PASS, A8 Warp-vs-CPU drift PASS, obs parity PASS, stand tests PASS (14 tests total).

## New frozen hashes (sha256, first 16 hex)

| File | Old | New |
|---|---|---|
| `sim/assets/humanoid.xml` | `4b8e68bd819c960d` | `01a3f59b037ef5e7` |
| `sim/assets/court.xml` | `1eba556a91fae556` | unchanged |
| `sim/assets/scene.xml` | `84bec5b08691e5fd` | unchanged (includes only) |
| `shared/obs_spec.json` | — | `ccfa18d6f9aaf2a5` (hip range constants changed; slot layout unchanged) |

Goldens regenerated: `shared/golden/obs_golden.npz`, `obs_golden.bin`, `replay_random.json`. Unreal `Content/Sim/*.xml` refreshed from `sim/assets/`.

## Regression scenarios still to run

- Unreal headless group (B2–B7 + gates) on the new assets and goldens.
- L0 evaluation on `l0_v4` once trained.

## 01:45 — dribble reward shaping change (during the 8 h queue)

Observed in `l2a_dribble_r_q1` at 59 M steps: 50 bounces per episode but apex 0.20 m (a low "tap" dribble); the apex bonus only fired inside a 0.15 m band around 1.0 m, so there was no gradient toward waist height. Change in `sim/streetball/levels/l2_dribble.py`: apex-bonus band widened to 0.25 m and a dense term added, 0.5 x exp(-((apex_pred - 1.0)/0.25)^2) while the ball rises, with apex_pred = z + vz^2/2g.

Policies touched: dribble family only (untrained; the running l2a stage keeps the old reward, later stages and the l2a retry import the new one). Interface unchanged.

## 02:30 — second dribble reward fix

L2b (first stage with the dense apex term) still tapped at 25 cm: the tap was paid by the "near the spot" and "in control" terms. Now `r_spot` is scaled by 0.3 + 0.7 x [last apex >= 0.6 m], micro-bounces (apex < 0.5 m) cost -1.0 each, dense apex weight 0.5 -> 2.0. Dribble family only.

## 03:00 — third dribble reward fix (monotonic shaping)

L2c still tapped at 23 cm: the tap penalty was a step at 0.5 m and the dense apex term a narrow bell around 1 m, so bounces between 0.2 and 0.5 m earned nothing. Now p_tap = relu(0.6 - apex)/0.6 per bounce and the dense term is linear in predicted apex up to the target with a penalty above 1.3 m. Dribble family only.
