# PoBasketball

Streetball humanoid gym: a MuJoCo-driven humanoid trained with RL plays streetball in Unreal Engine 5.8.

- Live replay viewer: https://lively-flower-0ec39e30f.8.azurestaticapps.net (status: `/diag`)
- `unreal/StreetballGym/` — the game (UE 5.8 + vendored `Plugins/MuJoCoRuntime`, libmujoco 4.0.0, NNE/ONNX inference)
- `sim/` — MuJoCo Warp training, evaluation, ONNX export (`uv run python -m streetball.train --level <name>`)
- `shared/` — frozen sim/engine contracts, exported policies, golden replays, `reward_config.json`
- `web/` — static three.js viewer of the golden replays + `/diag` (built by `web/build.py`)
- `docs/` — requirements, phase reports, daily logs

## Run locally

```
uv run --project sim python -m pytest -q        # all tests (GPU ones skip without CUDA)
uvx ruff check . && uvx ruff format --check .
python web/build.py && python -m http.server -d web/dist 8000   # viewer at http://localhost:8000
```

Unreal: `Engine/Build/BatchFiles/Build.bat StreetballGymEditor Win64 Development -Project=<repo>/unreal/StreetballGym/StreetballGym.uproject`.

## Deploy

A push to `master` runs `.github/workflows/deploy.yml`: Python checks, web build, deploy to the Azure Static Web App,
live check of `/` and `/diag`. Conventions: `AGENTS.md`.
