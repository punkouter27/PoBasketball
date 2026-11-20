# A1 — Toolchain: PASS

Date: 2026-11-06

| Check | Result |
|---|---|
| MuJoCo Warp sees GPU | yes, `cuda:0` RTX 5070 Ti Laptop (sm_120) |
| torch CUDA | yes, 2.14.1+cu130 |
| 4096-env humanoid benchmark | 1.49 M steps/s (target > 1 M) |
| Native Windows install | worked, no WSL2 fallback needed |

Details in `docs/env_setup.md`. Reproduce with `cd sim && uv sync && uv run python tools/bench_warp.py`.
