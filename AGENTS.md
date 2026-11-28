# UU_AGENT

Three parts: **1. Coding standard** (the UU_AGENT rules, project notes, CI/CD and the Po Game Standard),
**2. Concurrent work**, **3. Verify the repo** (exact commands).

## 1. Coding standard

### UU_AGENT rules

Scope: RL-trained humanoids and animals with realistic motion on Earth, deployed exclusively in Unreal Engine using MuJoCo Warp / URLab.

#### 1. Workflow & Setup
- **Target Engine:** Unreal Engine exclusively. Built-in engine physics (Chaos) is strictly disabled; UE5 serves solely as an audiovisual rendering, camera tracking, and input layer.
- **Git:** Work on `master`. Commit before syncing or pulling. Check `/docs` first.
- **Automation:** Set up levels, actors, and MJCF bindings via CLI and headless Blender. UI changes require before/after screenshots and an HTML report in `SCREENSHOTS/`.
- **Build stamp:** Render the build date (`YYMMDD`) in the bottom-right corner.
- **Paths & Toolchain:**
  - Raw assets: `Content/Art/Raw/`
  - Exported assets / MJCF: `Content/Art/Exports/`
  - Physics runtime: MuJoCo C++ Plugin / URLab runtime (no Chaos)
  - Policy inference: UE5 NNE / ONNX Runtime via Native C++
  - Editor settings: Disable "Use Less CPU when in Background"

#### 2. Physics & Transform Conventions
- **Coordinate & Unit Space:** UE5 uses Z-Up, Left-Handed coordinates in centimeters. MuJoCo / URLab uses Z-Up (or Y-Up depending on model XML), Right-Handed coordinates in meters. Apply an explicit 100× unit scale factor and axis transformation in the bridge layer.
- **Deterministic Allocation:** Pre-allocate all character skeletal meshes, ground collision surfaces, and props from simulation definitions at startup. Dynamic runtime spawning or actor destruction is forbidden.
- **Collision:** Primitive colliders only (capsules, spheres, boxes). Non-adjacent bodies collide. Zero penetration at rest, at joint limits, and during active motion.
- **Fidelity:** Gravity −9.81 m/s², anatomical mass distributions, strict torque, velocity, and joint-limit envelopes. Visual skeletal bones strictly mirror physics body transforms.
- **Smooth Motion:** Policy rewards must enforce action-rate/jerk penalties (or low-pass filtering) to prevent high-frequency jitter.

#### 3. Policy Architecture & Hand-Overs
- **Hierarchy:** Lean policies divided by motor skill family (Level 0 balance, locomotion, task skills). Variances are handled via command vectors (target velocity, gait style), not separate networks.
- **Directors:** Layered rule-based state machines (game flow → body state → skill selector) switch policies based on physical sensors (contact flags, center of mass, foot slip). Policies never switch or invoke each other directly.
- **Hand-Overs:** All policies for a given character share the observation space, joint ordering, action layout, step rate ($dt$), and style rewards. Preload all policies at level initialization. Carry over the last action vector; never snap poses or blend bone transforms. Train recovery/get-up skills starting from real simulated falls.
- **Interface Stability:** Append new observation features only at the end with zero-initialized weights; never reorder or delete inputs. Breakages require policy distillation.
- **Isolation:** Each character trains from scratch with its own policy weights and character card traits. No policy sharing across different character bodies. Avoid full retraining once a baseline character passes all gates.
- **Audit Trail:** Log all affected policies, state machine rows, and interface revisions in `/docs` prior to modifications. Re-run task and kinematic regression benchmarks after any update.

#### 4. Training, Gates & Optimization
- **Execution & Resources:** Close the UE5 editor during headless training runs exceeding 30 minutes or when available system RAM drops below 4 GB. Save and commit state beforehand.
- **Cleanup:** Purge failed runs, short checks (<5,000 steps), and redundant checkpoints. Never delete a run modified within the last 24 hours or one tied to an active training queue.
- **Verification Gate:** Export the final ONNX model only after holding target rewards for 100 consecutive episodes with zero NaN gradients. Validate a 5-second rollout ensuring:
  1. *Kinematics:* Root velocity, angular momentum, and joint angles match the MuJoCo/URLab baseline.
  2. *Contacts:* No foot sliding, ground clipping, or contact chatter.
- **Telemetry:** Run TensorBoard alongside all runs. Output training metrics to `/docs/<YYYYMMDD>/`.
- **Runtime Profiling:** Enforce zero heap allocation (no dynamic allocations) inside the real-time C++ inference loop to guarantee consistent frame budgets.
- **Reporting:** Runs over 30 minutes require an HTML report with convergence curves and run-over-run deltas. Provide hourly progress summaries.

#### 5. Communication & Phased Interaction Protocol
- **State Header:** Prefix all task execution responses with `**Current Phase: Step X of 5**`.
- **Approval Protocol:** Stop completely at each designated `[STOP]` gate. Do not output code or subsequent phases until explicit user approval is provided.
- **Large Changes:** For code modifications exceeding 100 lines, provide 3 architectural/roadmap questions before implementation.
- **Summary:** Responses exceeding 100 words must conclude with a concise ~20-word TL;DR.
- **Issue Resolution:** Conclude technical troubleshooting with a direct proposed resolution for the primary open issue and await confirmation before applying it.

---

### Project notes (PoBasketball / Streetball Humanoid Gym)

- Engine: Unreal 5.8.4 with the `MuJoCoRuntime` plugin (libmujoco 4.0.0). Training: MuJoCo Warp in `sim/`.
- `/docs` holds the step documents (`01_…`, `02_…`, `03_…`), `phase_reports/`, and daily logs under `docs/<YYYYMMDD>/`.
- Shared contracts (`shared/obs_spec.json`, `shared/humanoid_spec.json`, assets in `sim/assets/`) are frozen; a change bumps the hashes in `docs/phase_reports/PhaseA_summary.md` and re-runs A5/A6/A8.
- **Cross-app agent interface (UNITE).** `sim/streetball/role_obs.py` builds the portable **131-float /
  28-role** observation and action map from `PoPunkouterSoftware/docs/unite/creatures/streetball_humanoid/contract.json`,
  and reproduces that creature's `golden_role_obs.npz` to 1e-5 (`sim/tests/test_role_obs.py`). It does
  **not** replace `sim/streetball/obs.py`: the 119-float task observation (ball, palm, contact, level
  block) is still what the trainer, the UE plugin and the web twin speak. A portable brain — any creature,
  any app — is played with `python -m streetball.role_agent --policy <run dir>` from `sim/`; a brain trained
  for another body is accepted with `foreign=True` and labelled, never silently called correct.
- Headless Unreal: always go through `unreal/StreetballGym/Scripts/run_headless.ps1`; never pass string CVars through `-ExecCmds`; never use `-nullrhi`.
- Content layout (moved through the editor on 2026-11-22, redirectors fixed up and deleted): everything cooked lives in
  `/Game/Project/` = `Content/Project/`:
  `Agents/` (Grandma, UE Mannequins), `Core/` (Audio, VFX, Cinematics: MRQ broadcast render assets), `DataAssets/` (DA_RewardConfig, DA_ShowcaseConfig,
  DA_CourtAudioBank, DA_CourtFXBank, DA_GrandmaVoiceBank), `Environments/` (Maps, Env proxies, Materials, PCG),
  `RL_Policies/` (not assets: the MJCF scene, obs/humanoid specs, transition table and the ONNX policies that
  `sim/tools/sync_policies_to_unreal.py` copies in; `policies/` is git-ignored), `UI/` (none yet: the HUD and overlay
  are C++ Slate/UMG). Source files stay outside the cooked tree: `Content/Art/Raw/`, `Content/Art/Exports/`,
  `Content/Art/env_slots.json`. Move or rename assets only through the editor (Python `unreal.AssetTools.rename_assets`
  + `fixup_referencers`), never with git or the file system, and update the `/Game/...` strings in `Source/`,
  `Config/`, `Scripts/` and `env_slots.json` in the same commit.
- Gaze tracking: the MuJoCo body has no neck/head joint and the visual bones strictly mirror physics, so there is no
  gaze yet. Adding one needs an owner decision: a neck joint (frozen-contract change + retraining) or a render-only
  head look-at as an exception to the mirroring rule.

### Deliberate deviations

| Deviation | Why | Commit sha / date | How to undo |
|---|---|---|---|
| Headless Unreal never uses `-nullrhi`; automation runs through `Scripts/run_headless.ps1` with the RHI | owner rule, kept over the audit's `-nullrhi` suggestion | — | — |
| The Unreal game draws `PoBasketball` top-left and `vYYMMDD` bottom-right in its own window; the web page shows them once outside the canvas | a desktop game has no page (UU_AGENT build-stamp rule) | `51df776` 2026-11-22 | — |
| `Content/Art/{Raw,Exports}` and `Content/Art/env_slots.json` stay outside `/Game/Project` | source files and the PCG swap table, not cooked assets | `c630dfa` 2026-11-22 | — |
| `Content/Project/RL_Policies` holds plain files (MJCF, specs, git-ignored ONNX); no `UI/` folder | the runtime loads policies from disk via NNE; the HUD is C++ | `c630dfa` 2026-11-22 | — |
| `shared/mannequin_bones.json` keeps its old `/Game/Characters/Mannequins` provenance path; dated `docs/<date>` logs keep old paths | frozen Phase A2 dump, not used for lookups; history | `c630dfa` 2026-11-22 | — |
| Gate tests write `Saved/Reports/Step4_gate_unreal.md`; the committed copy (owner `edc8f53`) refreshes only with `-StreetballGateReportToDocs` | tests must not rewrite tracked files | `51df776` 2026-11-22 | — |
| Unreal is built and tested locally only; CI runs the Python checks and the web viewer | no Unreal Engine on GitHub runners | — | — |
| No gaze; no BC/AMP training (mocap set not on this machine); shipped policies not retrained | neck joint = frozen-contract change + retraining; owner decision | — | owner decision |

**Hosting:** Azure Static Web App `pobasketball`, Free tier. Never run test suites against the live site; live checks =
at most 6 page loads + /diag + X-Commit.

### CI/CD and Azure

- One workflow, `.github/workflows/deploy.yml`, on a GitHub-hosted runner. Every push and pull request: Python checks
  (`ruff check .`, `ruff format --check .`, `pytest` on CPU; GPU tests skip with a message), then `web/build.py` bakes
  `shared/golden/replay_*.json` into the three.js replay viewer and `web/dist/`. Push to `master` only: deploy to the
  Azure Static Web App `pobasketball` (resource group `PoBasketball`), then check that the live site serves this
  commit (`X-Commit` header, stamped on every response by `web/build.py` via `staticwebapp.config.json`), the page
  version and `/diag` (which also shows the deployed commit).
- The Unreal project is not built in CI (GitHub's runners have no Unreal Engine); build it locally and from a fresh clone
  (its `MuJoCoRuntime` plugin and libmujoco 4.0.0 are vendored in `unreal/StreetballGym/Plugins/`).
- GPU tests (`sim/tests/test_env.py`, `test_determinism.py`) run locally in `sim/.venv`
  (`uv run python -m pytest tests -q`). `test_determinism` writes its report to a temp dir only; refresh
  `docs/phase_reports/A8_determinism.md` on purpose with `uv run python tools/a8_determinism_report.py`
  (why Warp worlds are not bit-identical: `docs/phase_reports/A8_root_cause.md`).
- Reward penalty weights and curriculum gates: `shared/reward_config.json`, read by `sim/streetball/reward_config.py`
  and mirrored by the Unreal DataAsset `/Game/Project/DataAssets/DA_RewardConfig` (Project Settings > Game >
  Streetball Showcase, `Config/DefaultGame.ini`); `Streetball.Showcase.ConfigDataAssets` fails when the asset and the
  JSON differ. Each weighted penalty term is logged separately (`m/pen_<term>` in TensorBoard / progress.csv).
  Changing them does not retrain the shipped policies.
- Diagnostics overlay (Tab / corner "i"): FPS, episode reward, inference latency, curriculum stage, and a
  "Benchmark sim speed [B]" button: a bounded (1.5 s) CPU MuJoCo run of `scene.xml` reported as physics steps/s.
  Training runs MuJoCo Warp on the GPU, so this is a local proxy, labelled as such. Demo mode starts after 30 s without
  input; frames longer than 0.25 s (shader warm-up, loads) do not count as idle time.
- Web viewer (the live site): the same Tab / corner "i" overlay (FPS, episode reward = n/a because replays record no
  reward, inference latency, policy-vs-recorded action check, stage) and the same 30 s demo mode (`web/idle.js`,
  frames > 0.25 s ignored, tested by `web/idle.test.mjs` through pytest, needs `node`). `web/build.py` ships each
  policy replay's ONNX (`shared/policies/<name>.onnx`) and its recorded obs/action; the page runs it with
  onnxruntime-web (WASM, CDN-pinned in the import map) and logs `[policy] ... inference in the browser` to the console.
  /diag caches its results for 60 s per tab (sessionStorage, `web/diag.html` CACHE_S); "Re-check" probes again.
- The Unreal gate tests (`Streetball.Gate.*`) write `Saved/Reports/Step4_gate_unreal.md`; refresh the committed
  `docs/phase_reports/Step4_gate_unreal.md` on purpose with `-StreetballGateReportToDocs`.
- Version: one stamp, UTC `yyMMdd` of the HEAD commit, computed by `web/build.py` (index.html, diag.html) with the same
  rule as the Unreal build. /diag checks are listed in `web/diag_checks.json`.
- A replay recorded against an older body (qpos length differs from `sim/assets/scene.xml`) is skipped with a warning;
  re-record it with `sim/tools/replay_recorder.py` after changing the humanoid. `replay_locomotion_ppo.json` is a
  27-DoF v1-only PPO-vs-AMP comparison with no v2 counterpart and stays skipped (docs/20261118/log.md).
- Repo secret: `AZURE_STATIC_WEB_APPS_API_TOKEN`.

### Po Game Standard (Unity / Unreal RL games)

This repo is one of several independent Po games. It follows the conventions below, but it owns every file:
nothing is generated from, synced with, or required to stay identical to another repository (no "same file in
every game" headers, no sync scripts that copy into other repos). Third-party code it needs (ML-Agents, MuJoCo
plugins, URLab) is vendored INSIDE this repo at a pinned version. Azure resources may be shared through `PoShared`.

#### Repo skeleton
```
README.md   AGENTS.md (this standard + repo notes)   CLAUDE.md ("Read AGENTS.md.")
docs/       lowercase, all prose (no DOCS/, no root DESIGN.md/SPEC.md/tasks.md — move them into docs/)
scripts/    build/publish/helper scripts (Unity: Tools/ is renamed scripts/ unless Unity itself needs it)
.github/workflows/<one file>.yml   the ONLY workflow
pyproject.toml with a [tool.ruff] section for any Python in the repo
```
No absolute local paths (C:\Users\...) committed anywhere. No build outputs or node_modules tracked.

#### Web page around the game (WebGL template / web viewer)
- The page chrome is drawn ONCE, by the HTML page, OUTSIDE the game canvas, so it can never overlap the HUD:
  a 44px top bar (game name top-left, settings gear / fullscreen top-right) and the version `vYYMMDD` bottom-right
  in the bar's counterpart or a 20px footer strip. The canvas fills the remaining viewport.
- The in-game HUD does NOT repeat the game name or version (it may show them inside menus, not as corner chrome).
- Same tokens as the web apps: dark background `#0b0f17`, surface `#121826`, text `#e6e9f2`, muted `#9aa3b5`,
  accent `#6366f1`, Inter/system-ui font. Text ≥ 4.5:1 contrast.

#### Orientation (C11)
The canvas fills any viewport (no fixed portrait aspect, no pillarboxing). UI is anchored and DPI-scaled
(Unity: CanvasScaler "Scale With Screen Size" or UI Toolkit PanelSettings scale-with-screen; Unreal: UMG anchors +
DPI curve). Must be checked at 1600x900 (landscape) and 450x800 (portrait) — screenshots in the PR/commit notes.

#### Version
One stamp, UTC `yyMMdd`, computed once by the publish/build script and injected into: index.html, diag.html,
and the player (`PlayerSettings.bundleVersion` / Unreal ProjectVersion) so `Application.version` matches the page.

#### /diag (games)
`/diag` (static `diag.html` generated by the publish script) titled **System status**, same layout as the web apps:
overall banner, then **API / Data / Services** sections. It must LIVE-probe (fetch from the browser, with latency)
every external dependency the game really calls (leaderboard tables/functions, weather APIs, AI APIs, replay bundles,
model files), plus the WebGL2 capability and that the build bundle files exist. Nothing hard-coded as "Ready".
The checks are listed in the repo's own config (e.g. `scripts/webgl.json` → `diagChecks`).

#### In-game diagnostics overlay (C12)
`Tab` (and a 44px corner button on touch devices) toggles an overlay showing: FPS, current episode reward,
inference latency (ms, rolling average), curriculum stage. Readable text (≥ 4.5:1 on an opaque panel).

#### Demo mode (C13)
After 30 s with no input (keyboard, mouse, touch, gamepad) from load or from last input: hide non-essential HUD,
all agents are driven by the trained policy (inference only), showcase cameras cycle (~6–8 s each); any input
returns control and the HUD. Idle threshold, camera list and dwell time are editor-tunable assets.

#### Rewards + editor-first config (C9, C10)
Reward includes penalties for joint torque², joint angular velocity², action rate ‖a_t − a_{t−1}‖², and foot sliding
(foot planar speed while in contact), each with its own weight. Reward weights, curriculum thresholds, cameras and UI
references live in ScriptableObjects / `[SerializeField]` (Unity) or DataAssets / `UPROPERTY(EditAnywhere,
BlueprintReadWrite)` (Unreal); Python trainers read the same values from the repo's training config. Changing a
penalty does not retrain shipped policies — note this in docs when shipped models predate the change.

#### Workflow
- Unity: the WebGL player is built locally with the EXACT pinned editor (Unity cannot be licensed in CI) by
  `scripts/publish_webgl.ps1`, which runs EditMode tests first, then builds, zips and publishes a `webgl-*` release.
  The one workflow: on release → deploy to the game's Static Web App → check the live page AND /diag; on push →
  Python checks (`ruff check`, `ruff format --check`, `pytest`) only.
- Unreal: the one workflow builds and deploys the repo's web front (viewer / showcase + /diag) to its Static Web App,
  after Python checks. The Unreal project must compile from a fresh clone (all plugins vendored in `Plugins/`).

#### Tests
Python: real pytest tests (collected by pytest, not ad-hoc scripts), ruff clean. Unity: EditMode tests pass before
every publish. Tests never write into tracked files.

## 2. Concurrent work

- One engine at a time: close the Unreal editor before a headless run, a `-game` capture or a browser test, and never
  run two `UnrealEditor*` processes on this project (they lock the same packages and DDC).
- Training runs (`sim/`, GPU) and Unreal runs compete for the RTX 2060: check `nvidia-smi` and the training queue
  (`sim/streetball/queue.py`) before starting anything heavy; never delete a run modified in the last 24 h.
- `git status` before you start; commit your own files only (never `Saved/`, `Intermediate/`, `sim/runs/`,
  `web/dist/`, screenshots outside `SCREENSHOTS/`). Pull/rebase before pushing; never force-push.
- Asset moves touch many `.uasset` files at once: do them in their own commit while nobody else has the editor open.
- Live site: see **Hosting** in section 1 for the live-check budget.

## 3. Verify the repo

The command sequences below verify the repo, from the repo root (PowerShell or Git Bash). Last full run (2026-11-23):
pytest 28 passed locally incl. GPU (CI: GPU tests skip without CUDA); Unreal `Streetball.*` 26/26; build 0 code
warnings.

```
uvx ruff@0.17.6 check .
uvx ruff@0.17.6 format --check .
uv run --project sim python -m pytest -q -rs          # all Python tiers; GPU tests need CUDA (sim/.venv)
uv run --project sim python web/build.py              # web viewer + /diag into web/dist
python -m http.server -d web/dist 8000                # local check: http://localhost:8000/ and /diag.html
```

Unreal (UE 5.8, close the editor first):

```
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" StreetballGymEditor Win64 Development `
    "-Project=$PWD\unreal\StreetballGym\StreetballGym.uproject" -WaitMutex          # 0 warnings expected
& unreal/StreetballGym/Scripts/run_headless.ps1 -TimeoutSec 1500 -LogFile $env:TEMP\sb_tests.log `
    -- "-ExecCmds=Automation RunTests Streetball; Quit"                                # 26 tests, exit code 0
# 16:9 and 9:16 runtime check (overlay, benchmark, demo mode screenshots into <dir>, then quits):
& "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" `
    unreal/StreetballGym/StreetballGym.uproject -game -windowed -ResX=1600 -ResY=900 `
    -ShowcaseCapture=<dir> -ShowcaseTouch -ShowcaseBenchmark                           # and -ResX=450 -ResY=800
```

Live (after a push to master): the workflow run must end with `Live: ... at X-Commit <sha>, /diag OK`.
