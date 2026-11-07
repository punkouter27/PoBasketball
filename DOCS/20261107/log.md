# 2026-11-07 — daily log (overnight queue results)

Queue `sim/runs/queue/20261106_2300`, 23:00 → 06:37, ~1.1 B simulated steps. Final report:
`DOCS/20261107/extended_training_report.html` (per-run reports alongside it).

## Results

| Skill | Policy | Runs | Steps | Eval success | Gate | Weights |
|---|---|---|---|---|---|---|
| Tier 1 balance | balance | l0_v4 (before queue) | 29.5 M (+85 M lineage) | 98 % | PASS + Unreal gate PASS | `sim/runs/production/balance.{onnx,pt,json}` |
| Tier 2 traversal | locomotion | l1_traverse_q1, _q2 | 202 M + 137 M (+34 M before) | 72.5 % → **82 %** (gate 90 %), 0 falls, 1.6 m/s | not yet | candidate `production/candidates/locomotion_l1_traverse.pt` |
| Tier 3 dribble (R, L, crossover) | dribble | l2a/l2b/l2c _q1 | 117 + 41 + 73 M | 0 % | no | — |
| Tier 4a moving dribble | dribble | l3a_q1 (stopped early) | 32 M | 0 % | no | candidate |
| Tier 4b scramble | scramble | l3b_q1 | 70 M | 0 % (ball 2.2 m away at the 3 s limit) | no | candidate |
| Tier 5 jump shot | shot | l4_q1 | 102 M | 0 % (ball lost before the trigger) | no | candidate |

Zero falls and zero NaN-gradient batches in every evaluation.

## What was learned overnight

1. **Locomotion works but is slow.** The athlete jogs at ~1.6 m/s and reaches all ten waypoints in 82 % of
   90-second episodes. Return was still rising when both boxes ended, so more steps should close the gap to 90 %.
   Speed is the limiter: the velocity-tracking reward is satisfied by the low end of the 0.8–3.0 m/s command range.
2. **The dribble reward was exploitable three ways**, found and fixed in sequence during the night (see
   `DOCS/20261106/change_self_collision_and_roster.md`): (a) a 20 cm "tap" instead of a waist-high bounce
   (apex shaping was a narrow band), (b) the tap persisted because spot/control terms paid regardless of height
   (now gated, monotonic shaping), (c) the ball was being juggled with feet and shins because the loose-ball
   countdown never armed without an initial grant of control (now granted at reset, as in Unreal).
   **No dribble stage has yet trained from a clean start with all three fixes**: l2a/l2b/l2c trained before fix
   (b)/(c), l3a was stopped at 32 M steps, and every later stage was initialised from the foot-juggling checkpoints.
3. **Scramble and shot depend on dribble** and were effectively untrainable this night (shot episodes end at 2.3 s
   because the ball is lost before the trigger).

## Recommended next steps (in order)

1. Re-run the dribble family **from the locomotion checkpoint, not from the tap checkpoints**, with the fixed
   reward; give L2a at least 150 M steps and watch `m/apex` and `m/in_control` (should rise above 0.8 m and 0.8).
2. Give L1 another 150–200 M steps and raise the floor of the commanded speed range to 1.2 m/s so the
   policy cannot satisfy the task by jogging slowly.
3. Scramble: shorten the initial ball distance range to 0.5–2.5 m for the first 50 M steps (curriculum), then widen.
4. Shot only after dribble passes.

## Housekeeping

- Production manifest: `sim/runs/production/production_manifest.json` (balance only).
- All queue runs are < 24 h old; nothing deleted (UU_AGENT §4). `l1_v1_resume.pt`, `l0_v*_*.pt` copies can be
  pruned after 2026-11-08.
- One operational mistake during the night: I killed the pre-fix l3a stage early on purpose; the clock in my notes
  was ~20 min ahead of the real time, so the DOCS timestamps for the 03:xx/04:xx entries are approximate.

## 15:50 — "play scene": athlete falls every 1.4 s in Tier 1 (diagnosed, not yet fixed)

Observed in `-game`: `HARD_RESET (fallen) in tier 1` every 41 frames with the production balance policy.

| Start condition (same policy, 64 envs, no pushes, 10 s) | Falls |
|---|---|
| Training reset (ball 3 m away, joint noise, randomisation) | 1.6 % |
| Exact `stand` keyframe, ball moved 3 m away | 0 % |
| Exact `stand` keyframe, ball left beside the right foot (what Unreal Tier 1 does) | **100 %**, at 1.36 s |

Root cause: Unreal's Tier 1/2 hard reset leaves the ball at its keyframe spot (0.45 m ahead, 0.35 m right, on the floor).
L0 always trained with the ball parked 3 m away, so the athlete trips over a ball it has never seen. Sim/Unreal
mismatch in reset rules, not physics: obs (5e-8), ONNX vs PyTorch actions (3e-7) and CPU vs Warp trajectories agree.

Two tooling defects found on the way:
1. `shared/golden/replay_l0.json` (the Step 4 live-physics golden) itself falls at 1.4 s. The gate checked Unreal-vs-Python
   parity only, so it passed while both sides fell. The gate needs an "athlete still upright" assertion.
2. `env_base.step()` returns `info["fallen"]` as a reference to `self.fallen`, which the auto-reset clears in place.
   Every reported fall rate (evaluate.py, queue reports) therefore reads 0 %. Success rates are unaffected
   (computed before the reset). Fix: clone the flag in `info`.

Proposed fix (awaiting approval): park the ball 3 m away on Tier 1/2 resets in the Unreal director (mirror of
`l0_stand.on_reset`), clone `fallen` in `info`, add the upright assertion to the gate, re-run eval + gate.
