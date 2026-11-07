# PoBasketball — agent instructions

Follow `AGENTS.md` (the UU_AGENT standard) for every change in this repository. Read `/DOCS` first:
`DOCS/01_requirements_contract.md`, `DOCS/02_character_blueprint.md`, `DOCS/03_implementation_plan.md`,
`DOCS/phase_reports/`, and the latest `DOCS/<YYYYMMDD>/` log.

Quick map
- `sim/` — MuJoCo Warp training (`uv run python -m streetball.train --level <name>`), evaluation, ONNX export, gate runner (`sim/tools/run_gate.py`).
- `unreal/StreetballGym/` — UE 5.8 project + `Plugins/MuJoCoRuntime`. Build with `Engine/Build/BatchFiles/Build.bat StreetballGymEditor Win64 Development -Project=...`. Headless runs only through `Scripts/run_headless.ps1`.
- `shared/` — frozen contracts between sim and engine (obs spec, humanoid spec, golden data, exported policies).
