# Phase C — Training Setup: C1–C8 implemented

Date: 2026-11-06 (evening)

| Task | Status | Evidence |
|---|---|---|
| C1 Vectorised Warp env | DONE | `sim/streetball/env_base.py`; `tests/test_env.py` (3 passed): obs parity with `obs.py` golden 1.6e-6, 200 random-action steps without NaN |
| C2 Domain randomisation | DONE | per-world body mass ±10 %, floor friction 0.6–1.1, motor kp ±10 %, ball mass ±5 %, ball contact damping ±10 %, 1-step action latency (p = 0.5), pushes 0–150 N × 0.2 s every 3–8 s with a curriculum scale |
| C3 PPO trainer | DONE | `streetball/ppo.py`, `streetball/train.py`; smoke run `runs/smoke_l0` (3 M steps) learns (return 29 → 95) |
| C4 Levels L0–L4 | DONE (untrained) | `streetball/levels/`: l0_stand, l1_traverse, l2a/b/c dribble, l3a moving dribble, l3b scramble, l4 jump shot; each stepped 100–150 control steps at 64 envs without NaN |
| C5 Evaluation harness | DONE | `streetball/evaluate.py` → `docs/phase_reports/eval_<level>.{md,json}` |
| C6 ONNX export | DONE | `streetball/export_onnx.py`, opset 17, `obs[1,119] -> action[1,27]`, normalisation folded, onnxruntime parity check |
| C7 Replay recorder | DONE | `sim/tools/replay_recorder.py`; `shared/golden/replay_random.json` (250 steps) |
| C8 Curriculum ladder | DONE | `streetball/curriculum.py` with resume via `runs/curriculum.json` |

## Measured throughput (RTX 5070 Ti Laptop, 12 GB)

| Setting | Control steps / s | Note |
|---|---|---|
| Physics only, 4096 worlds | 72 k | 10 substeps per control step, CUDA graph |
| Env step incl. obs/contacts/reward, 4096 worlds, standing | 66 k | |
| Env step, 4096 worlds, random actions (bodies on floor, more contacts) | 47 k | |
| Full PPO loop, 4096 envs (rollout + update) | 38 k (alone), 18–25 k while the GPU is shared with tests/UE | |

**Deviation from plan C1 ("> 200 k policy-steps/s")**: not reachable on this GPU; the physics alone caps at 72 k control steps/s for the full scene (humanoid + ball + hoops). 150 M steps for L0 therefore takes about 1 h instead of ~12 min. Budgets in `curriculum.py` (0.15–0.5 B steps per level) assume ~40 k fps, i.e. 1–3.5 h per level.

## Decisions / deviations

1. **Warp data budgets**: `njmax` is *per world* in `mujoco_warp.put_data` (it allocates a dense njmax² block per world); passing a global number allocated 22 GB. Now njmax = 160 per world, naconmax = 24 × N. Observed maxima under random actions: 55 constraint rows, 27 k contacts for 4096 worlds.
2. **Warp world-to-world nondeterminism** (5e-4 rad over 5 s): accepted, gate at 1e-3 (A8).
3. **Policy output**: `tanh` mean with Gaussian exploration, samples clipped to [-1, 1] by the env (blueprint said tanh output; exploration noise is added after the tanh).
4. **Adaptive LR** capped at 1e-3 after the smoke run showed oscillation between 1e-5 and 3e-3.
5. **L0 foot-drift termination** relaxed from 0.15 m to 0.20 m.
6. **L4 pass criterion** is per-shot: each episode is one shot, pass = ≥ 30 % scored over 200 shots. The "20 shots" PRD framing is applied in the Unreal showcase counter.
7. **Ball-floor contact flag** added to the env contact scan (bounce detection for L2–L4); assets unchanged.

## Training runs

| Run | Level | Envs | Steps | Status |
|---|---|---|---|---|
| `runs/smoke_l0` | l0_stand | 2048 | 3 M | smoke only |
| `runs/l0_v1` | l0_stand | 4096 | 150 M, push curriculum | **in progress** (detached process; log in `sim/runs/l0_v1/log.csv`) |
