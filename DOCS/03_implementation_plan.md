# Step 3 — Implementation Plan

Project: Autonomous Streetball Humanoid Gym
Status: DRAFT, awaiting sign-off before any code is written
Date: 2026-11-06
Depends on: `01_requirements_contract.md`, `02_character_blueprint.md` (both approved)

---

## 0. Repository layout

```
PoBasketball/
├── docs/                      # steps 1–5 documents, verification reports
├── sim/                       # Python: MJCF, envs, training, export, tests
│   ├── assets/
│   │   ├── humanoid.xml       # character (bodies, joints, actuators)
│   │   ├── court.xml          # floor, hoops, fence, ball
│   │   └── scene.xml          # includes the two above + options block
│   ├── streetball/
│   │   ├── obs.py             # THE observation spec (single source of truth)
│   │   ├── env_base.py        # Warp-backed vectorised env, randomisation, resets
│   │   ├── levels/            # l0_stand.py … l4_shot.py (reward, task block, termination)
│   │   ├── train.py           # PPO driver, checkpoints, logging
│   │   ├── evaluate.py        # 200-episode pass test per level
│   │   └── export_onnx.py
│   ├── tests/                 # drop-bounce test, obs golden test, determinism test
│   └── tools/                 # dump_mannequin_bones.py, tune_ball.py, replay_recorder.py
├── unreal/
│   └── StreetballGym/         # UE 5.4+ project
│       ├── Plugins/MuJoCoRuntime/   # thin C++ wrapper around libmujoco
│       └── Source/StreetballGym/    # sim driver, bone mapper, policy runner, state machine, cameras, audio, HUD
└── shared/
    ├── obs_spec.json          # generated from obs.py; consumed by C++ at build time
    └── golden/                # recorded sim states + expected obs/actions for cross-checks
```

Python environment: `uv` managed, Python 3.11, pinned `mujoco`, `mujoco_warp`, `warp-lang`, `torch`, `onnx`, `onnxruntime`. Versions are pinned in `sim/pyproject.toml` on first install and the same `mujoco` version's `libmujoco.dll` is vendored into the UE plugin.

---

## Phase A — Assets (sim side, no engine yet)

| ID | Task | Output | Done when |
|---|---|---|---|
| A1 | Install toolchain on Windows: CUDA, `uv` env, `mujoco_warp` smoke test (step 4096 copies of the stock humanoid) | `sim/pyproject.toml`, `docs/env_setup.md` | 4096 envs step at > 1 M steps/s on the RTX card. If install fails natively, switch to WSL2 and record it |
| A2 | Dump UE5 Manny skeleton: bone names, parent, bind-pose world transforms, bone lengths | `shared/mannequin_bones.json` (via UE Python script, run once in the editor) | JSON has all bones in blueprint B.3 |
| A3 | Author `humanoid.xml` from blueprint A.2–A.4 with lengths from A2; capsule/box colliders; PD actuators; contact exclusion between adjacent bodies | `sim/assets/humanoid.xml` | Loads in `mujoco.viewer`, stands in nominal pose under gravity with zero action for 10 s (PD holds it) |
| A4 | Author `court.xml`: floor, two hoops with 12-capsule rims, backboards, poles, fence, ball, rim sensor sites | `sim/assets/court.xml` | Ball dropped from 1.80 m rebounds to 1.30 ± 0.05 m (automated test); ball-rim bounce doesn't tunnel at 10 m/s |
| A5 | Tune ball `solref`/`solimp` and friction by script | `sim/tools/tune_ball.py`, values written into `court.xml` | A4 bounce test passes for 10 random drop heights |
| A6 | Axis alignment check: load scene, convert every body quaternion by B.1, apply B.2 offsets against A2 bind pose, print max angular error | `sim/tools/check_axes.py` | Error < 0.1° in reference pose; a 90° hip flexion in sim produces thigh pointing forward in UE coordinates |
| A7 | Observation spec: implement `obs.py`, generate `shared/obs_spec.json`, record 1000 random states + expected obs | `sim/streetball/obs.py`, `shared/golden/obs_*.npz` | Spec JSON lists each slot name, index, scale; golden file written |
| A8 | Warp vs libmujoco drift test: same XML, same 250-step action sequence, measure divergence | `sim/tests/test_determinism.py`, `docs/determinism_report.md` | Root < 2 cm, joints < 1° over 5 s (contract §6). If it fails, lower `timestep` or raise solver iterations and re-run |

Phase A exit: A3–A8 tests green, `scene.xml` frozen (hash recorded).

---

## Phase B — Engine Integration (Unreal, no policy yet, scripted actions)

| ID | Task | Output | Done when |
|---|---|---|---|
| B1 | Create UE 5.4+ C++ project, disable Chaos on all gameplay actors (project setting + per-actor), import Manny | `unreal/StreetballGym/` | Project builds; mannequin visible; no PhysX/Chaos bodies on character or ball |
| B2 | `MuJoCoRuntime` plugin: third-party module wrapping `libmujoco.dll` (vendored, same version as Python); `UMuJoCoSim` object: load XML, `mj_step`, read `xpos/xquat/cvel/contact`, write `ctrl`, reset via `qpos/qvel` | `Plugins/MuJoCoRuntime/` | Loads `scene.xml` from A8, steps 500× per second on the game thread with < 1 ms per step |
| B3 | Pre-load: all actors (character, ball, hoops, fence, floor) spawned at BeginPlay from the XML's body list; no runtime spawn/destroy anywhere | `AStreetballWorld` actor | Grep confirms no `SpawnActor` outside BeginPlay; profiler shows zero allocations in Tick after warm-up |
| B4 | Fixed-step accumulator + render interpolation (blueprint B.5); physics decoupled from frame rate | `USimClock` | Dropping the frame rate to 10 FPS changes nothing in the sim trajectory (hash of qpos after 10 s identical at 10, 30, 60 FPS) |
| B5 | Bone mapper (blueprint B.1–B.3): offset capture at init, world-space bone drive via `AnimNode` / `ModifyBone` in a custom `UAnimInstance`, spine slerp split | `UMuJoCoBoneMapper` | Reference pose matches sim pose visually; A6 check reproduced inside UE prints < 0.1° |
| B6 | Preset-action playback: load a recorded action sequence from Phase A, drive the sim, record `qpos` and compare to Python replay | `tools/replay_recorder.py` + UE replay component | Same tolerance as A8 |
| B7 | NNE policy loader: load an ONNX file (a dummy policy exported from A7 pipeline), run CPU inference at 50 Hz, assemble obs from `obs_spec.json` in C++, diff against golden | `UPolicyRunner`, `obs_builder.cpp` | Golden obs diff < 1e-5 for all 1000 states; inference < 2 ms |
| B8 | Broadcast camera director: sideline dolly, baseline low-angle, press-box wide; state-driven cuts; critically-damped smoothing | `ABroadcastDirector` | Cuts trigger on the PRD rules; no camera acceleration > threshold on scripted trip |
| B9 | Contact-driven audio: read contacts per physics step, debounce, map impact speed to pitch/volume; dribble, palm, shoe, rim, backboard, chain-net rattle on score | `UCourtAudio` | Each PRD sound fires on its contact pair in a scripted test |
| B10 | HUD: tier display, streak counters, scramble countdown ring, milestone bar; all read-only on sim state | `WBP_Scoreboard` | Counters update from a scripted sequence |

Phase B exit: B4, B6, B7 tests pass; mannequin moves correctly under scripted actions at 30 FPS.

---

## Phase C — Training Setup (sim side)

| ID | Task | Output | Done when |
|---|---|---|---|
| C1 | Vectorised env on MuJoCo Warp: N envs, resets, episode bookkeeping, per-level task block hook | `env_base.py` | 4096 envs of the full scene step at > 200 k policy-steps/s |
| C2 | Domain randomisation (blueprint C.1): mass, friction, kp, ball mass/restitution, latency, pushes; all per-env, re-sampled on reset | `randomize.py` | Each parameter visibly varies across envs in a log dump |
| C3 | PPO trainer (PyTorch), checkpoints, TensorBoard/W&B logging, curriculum loader (init level N from N−1) | `train.py` | Trains L0 to pass target; wall-clock recorded |
| C4 | Level definitions L0–L4 with rewards, terminations, task blocks from blueprint C.2 | `levels/*.py` | Each level runs for 1 M steps without NaN or crash |
| C5 | Evaluation harness: 200 randomised episodes, deterministic policy, reports pass/fail against C.2 targets | `evaluate.py` | Produces a JSON + Markdown report per level |
| C6 | ONNX export with fixed input name `obs[1,119]`, output `action[1,27]`, opset 17; runtime check with `onnxruntime` vs PyTorch | `export_onnx.py` | Max abs diff < 1e-5 on 1000 obs |
| C7 | Replay recorder: save 5-second `qpos/qvel/ctrl` traces for the Step 4 gate | `tools/replay_recorder.py` | Produces `.npz` loadable by B6 |
| C8 | Progression stages: scripted curriculum that trains L0 → L1 → L2a → L2b → L2c → L3a → L3b → L4, gating on C5 pass | `curriculum.py` | One command trains the whole ladder with resume |

Phase C exit: L0 trained, exported, loaded in UE through B7, character stands in the showcase.

---

## Order and parallelism

```
A1 ─► A3 ─► A5 ─► A8 ─────────────────┐
A2 ─┘  └─► A6                          ├─► C1 ─► C2 ─► C3 ─► C4 ─► C5 ─► C8
      A4 ─┘       A7 ──────────────────┘            └─► C6 ─► C7
B1 ─► B2 ─► B3 ─► B4 ─► B5 ─► B6                     (B7 needs C6 dummy export)
                        └─► B8, B9, B10 (independent of policy)
```

Phase A and Phase B1–B5 run in parallel. Phase C starts once A8 is green.

---

## Risks and fallbacks

| Risk | Signal | Fallback |
|---|---|---|
| `mujoco_warp` unstable on native Windows | A1 fails or crashes | WSL2 Ubuntu on same GPU; export ONNX and XML across the mount |
| Warp float32 drift exceeds contract tolerance | A8 fails | Reduce `timestep` to 0.001, raise solver iterations; if still failing, redefine gate as closed-loop trajectory similarity (documented and re-approved) |
| NNE ORT CPU too slow for 50 Hz | B7 > 2 ms | Shrink MLP to 256-256; or NNE DML (GPU) provider |
| Palm-only dribble fails to learn | L2a stalls at < 20 bounces after 500 M steps | Ellipsoid/concave palm (blueprint C.4), then short reference clips |
| `ModifyBone` per-bone world-space drive too costly | B5 frame time | Write a custom `FAnimNode` that sets the whole pose once per frame |

---

## Definition of done for Step 3

Tasks A1–A8, B1–B10, C1–C8 completed with their "Done when" checks recorded in `docs/phase_reports/`. Then Step 4 training and the verification gate begin.

---

**[STOP] Awaiting approval before writing code.**
