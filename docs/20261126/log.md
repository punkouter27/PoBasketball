# 2026-11-26 — Moving-dribble BC and set-shot curriculum

## Plan and audit trail

The `l3a_walk` PPO-only attempt failed to learn a gait (0% success; 0.01 waypoints per episode), while the production
locomotion and stationary-dribble policies provide the missing capabilities. The next training path uses a composite
teacher: locomotion controls the body, while the stationary-dribble actor controls both arms and lumbar flexion. A
DAgger-style BC trainer labels student-visited `l3a_walk` observations; BC is a training initialization only and is not
exported. The probe must show that the teacher carries the ball while moving; the BC runner repeats this preflight and
refuses to train on a failing teacher.

Add a separate `l4_set_shot` training level at 1.5–3.0 m from the rim. It keeps two-hand gather and shot scoring but
discourages jumping. Keep `l4_jump_shot`, the `shot` export, Unreal behavior, observation/action contracts and shipped
policies unchanged; only expose the new level in the training ladder, with no export family.

| Area | Change | Affected policy | Interface |
|---|---|---|---|
| `streetball/teacher.py`, BC tool and probe | Compose locomotion + dribble actions, then behavior-clone on `l3a_walk` | Dribble (training only) | None |
| `levels/l4_shot.py`, level registry and training ladder | Add the close, no-jump set-shot variant as an unexported stage | Shot (training only) | None |

Available source policies are `shared/policies/locomotion.onnx` and `shared/policies/dribble.onnx`; both declare 125
observations and 29 actions. The locomotion sidecar has an older observation-contract hash than the current shared spec.
The ONNX-to-PyTorch parity check validates numerical reconstruction, not semantic compatibility, so the teacher probe
must pass before BC or an eight-hour training run. No model is promoted or synchronized to Unreal by this work.

## Validation and run gate

The current interface/physics tags are `c766c7d32fb36d2e` / `bd7cf5274215544f+6fa7a3aaae076514`. The locomotion
policy sidecar reports `32f5b79d3216e8a3` / `319cd05af6f00d17+c1c2207912c56781`; the dribble sidecar reports the
current interface hash but an older humanoid hash (`319cd05af6f00d17+6fa7a3aaae076514`).

On `l3a_walk` at speed stage 0, the selected both-arms/lumbar composite fell in 95.3% of episodes (1.65 s mean);
the one-arm/no-lumbar comparison still fell in 80.1% (2.09 s mean). Locomotion-only fell in 99.6% (1.30 s mean).
The dribble-only starting actor completed 30 s without falling but averaged only 0.28 m/s and 0.016 waypoints. All
teacher configurations are no-go, so L3a BC training was withheld. The BC runner's built-in preflight independently
rejected the selected teacher at control 0.841, distance 0.53 m and 87.5% falls; no BC checkpoint was written. Its
earlier 80-sample smoke check is not a training result and its checkpoint was deleted.

## Current-version locomotion prerequisite

User selected retraining L1 locomotion before retrying the moving-dribble teacher. Because the shipped locomotion actor
has stale interface/physics tags, this run starts from scratch rather than importing it. Run `l1_teacher_gate_8h` was
started at 12:45 on the RTX 2000 Ada with a 480-minute budget, 4096 environments, push curriculum, initial std 0.3,
and 50 M-step checkpoints. Step ceiling is 1 B; current tags are the interface/physics versions above. Startup completed
without OOM: iteration 1 reached 0.1 M steps at 33.5k fps; the 30k-fps estimate is 556 minutes. No policy export or
promotion is part of this run. Evaluate the resulting checkpoint on `l1_traverse` and rerun the composite-teacher probe
before starting L3a BC.

## Live training dashboard

`sim/tools/live_dashboard.py` serves an automatically refreshing, read-only view of a run's training log. For this
run, start it from `sim` with `.venv\Scripts\python.exe tools\live_dashboard.py runs\l1_teacher_gate_8h` and open
`http://127.0.0.1:8765/`. The page refreshes every 10 minutes and shows training speed, episode length, reward,
waypoints, push difficulty and numerical errors. Runtime is an estimate based on iteration timings, and the dashboard
does not claim that training metrics are an evaluation result. It warns if log updates stop and shows the stop reason
when `done.json` appears. Stop the dashboard server separately when it is no longer needed; it does not control training.

## 2026-11-27: completed run and evaluation

The eight-hour L1 run finished at 716.1 M steps with zero NaN gradient batches. No model was exported or promoted.
The checkpoint teaches locomotion, not moving dribble or shooting.

Deterministic `l1_traverse` evaluation on the current simulator: 200 episodes per actor, seed 123, randomization on,
150 N maximum pushes. The shipped actor was reconstructed from ONNX with 1.62e-6 maximum absolute parity error.

| Locomotion actor | Success | Falls | Mean episode | Gate |
|---|---:|---:|---:|---|
| Shipped ONNX | 97.0% | 2.5% | 60.35 s | PASS |
| New final `model.pt` | 99.0% | 0.0% | 59.29 s | PASS |
| New `best.pt` | 97.5% | 1.5% | 61.29 s | PASS |

Both new checkpoints and the shipped actor passed the 90% gate, including its 100-episode rolling-window requirement.
The new final actor performed slightly better in this sample, though a single 200-episode comparison does not establish
the size of any general improvement. Importantly, the shipped actor still works on L1 in the current simulator despite
older metadata hashes; the earlier failures were measured in the L3a setup, not an L1 evaluation.

Moving-dribble composite check: 256 environments, `l3a_walk` stage 0, seed 7, no pushes, up to 30 s. Both arms and
lumbar come from the same shipped stationary-dribble actor in all three trials.

| Locomotion actor | Falls | Mean episode | Control fraction | Distance | Clone gate |
|---|---:|---:|---:|---:|---|
| Shipped ONNX | 96.1% | 1.73 s | 0.851 | 0.46 m | FAIL |
| New final `model.pt` | 99.6% | 1.36 s | 0.902 | 0.34 m | FAIL |
| New `best.pt` | 99.6% | 1.49 s | 0.882 | 0.38 m | FAIL |

The distance requirement is 3.0 m and the control requirement is 0.9. The new final actor clears the control threshold
but fails distance, and neither new teacher provides a viable moving-dribble initialization. No L3a BC run was started.
