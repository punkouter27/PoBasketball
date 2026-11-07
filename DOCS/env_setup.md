# Environment Setup (task A1)

Recorded 2026-11-06 on the training/dev machine.

## Hardware and drivers

| Item | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12 GB, sm_120 (Blackwell) |
| Driver | 616.87 (reports CUDA 13.4 capability) |
| CUDA toolkit on PATH | 12.8 (nvcc 12.8.93). Warp ships its own runtime, so this is only needed for other tooling |
| OS | Windows 11 Pro 10.0.26300 |
| C++ toolchain | Visual Studio 2022 Build Tools 17.14, MSVC x64, Windows SDK 10.0.26100 |
| Unreal | UE 5.8.4 (Epic Launcher install, `C:\Program Files\Epic Games\UE_5.8`) with NNE, NNERuntimeORT and PythonScriptPlugin available |

## Python (sim/)

Managed by `uv`. Python is pinned to 3.12 because `onnxruntime` had no 3.15 wheel and the PyTorch CUDA index stops at 2.14.1 for 3.12.

```
cd sim
uv sync            # creates .venv from pyproject.toml / uv.lock
uv run python -c "import mujoco_warp, torch; print(torch.cuda.is_available())"
```

Pinned packages (see `sim/uv.lock` for the full tree):

| Package | Version | Note |
|---|---|---|
| mujoco | 4.0.0 | Same major.minor must be vendored as `mujoco.dll` into the UE plugin |
| mujoco-warp | 4.0.0 | GPU simulator |
| warp-lang | 1.19.0 | Detected `cuda:0` with sm_120 |
| torch | 2.14.1+cu130 | From `https://download.pytorch.org/whl/cu130` (explicit index in `pyproject.toml`) |
| onnx / onnxruntime | 1.23.2 / 1.31.1 | Export + CPU parity check |

## A1 smoke benchmark

Stock `mujoco_warp` test humanoid (`nq=28`), 4096 worlds, CUDA-graph captured `step`:

| Metric | Result | Target |
|---|---|---|
| Throughput | 1.49 M physics steps/s | > 1 M |
| First-run kernel compile | about 60 s (cached afterwards in `%LOCALAPPDATA%\NVIDIA\warp\Cache`) | n/a |

Warning seen: `linesearch iterations limit reached` on the stock model. Our `scene.xml` sets `ls_iterations="10"` per the blueprint and we will raise it if the warning appears with our model.

## Native Windows vs WSL2

MuJoCo Warp installed and ran natively on Windows without issue. WSL2 fallback was not needed and is not set up.

## Known quirks

* `uv init` picked CPython 3.15 by default; `.python-version` now pins 3.12.
* `Data.ncon` was renamed `Data.nacon` in mujoco_warp 4.0.
