# UU_AGENT compliance audit — 2026-11-06

Status key: ✅ done · 🔧 applied today · ⏳ planned (no decision needed) · ❓ needs the user's decision (changes the approved blueprint)

## §1 Workflow & Setup

| Rule | Status | Note |
|---|---|---|
| Work on `master`, commit before sync | 🔧 | `git init -b master`, first commit `305e498`; `.gitignore` excludes venv, runs, UE build dirs |
| Check `/DOCS` first | 🔧 | `docs/` renamed to `DOCS/`; `CLAUDE.md` points agents there; daily log `DOCS/20261106/log.md` |
| Scenes/levels via CLI + headless Blender | ✅ / ⏳ | Level, audio assets and skeleton dump are headless scripts. No Blender step yet (no custom meshes); folders `Content/Art/Raw`, `Content/Art/Exports` created |
| UI changes → before/after screenshots + HTML report in `SCREENSHOTS/` | 🔧 | `SCREENSHOTS/` created; first report for today's HUD/lighting change |
| Build stamp YYMMDD bottom-right | 🔧 | `UStreetballHUDWidget::BuildStampYYMMDD()` from `__DATE__` |
| UE: disable "Use Less CPU when in Background" | 🔧 | `Config/DefaultEditorPerProjectUserSettings.ini` |
| Physics MuJoCo not Chaos; NNE/ONNX runtime | ✅ | |

## §2 Physics & Realism

| Rule | Status | Note |
|---|---|---|
| Primitive colliders only | ✅ | capsules, boxes, spheres, plane |
| **Non-adjacent parts collide with each other** | ❓ | Humanoid self-collision is OFF (`contype=1 conaffinity=0`). Turning it on is a physics change (see impact list) |
| Zero penetration at rest / limits / motion | ⏳ | Needs a test: contacts at keyframe, joint-limit sweep, random-motion sweep; add once self-collision decision is made |
| Gravity, anatomical mass, limits | ✅ | 80 kg Winter fractions, anatomical ranges, torque limits per group |
| Skeleton joints match 3D file and simulator | ✅ | joints placed on Manny bones from the skeleton dump; A6 check 0.0000° |
| Action-rate / jerk penalties | ✅ | every level has `p_action_rate`; jerk term can be added without interface change |

## §3 Policy Architecture & Retraining

| Rule | Status | Note |
|---|---|---|
| Few policies, one per skill family; variants via command inputs | ❓ | Current ladder: 8 per-level policies. Proposed roster below |
| Director switches on physical state via one transition table mirrored in every runtime | ⏳ | Director exists in UE only (`UStreetballDirector`). Plan: move the table to `shared/transition_table.json`, load it in UE and in a Python replica used by evaluation |
| Shared obs layout / joint order / action map / timing | ✅ | `shared/obs_spec.json`, one 119-float layout, 12-float task block |
| Preload every policy; pass on the last action; never snap/blend | ✅ / ⏳ | UE preloads at BeginPlay; prev_action carry-over across switches to be verified in a test |
| Train each policy on inherited states (get-up from real falls) | ❓ | No get-up policy in the PRD. Adding one = new skill + director rows |
| Frozen interface, append-only | ✅ | documented in `obs.py`; task block padded to 12 |
| One character, own policies | ✅ | |
| Before any change: list touched policies, log in /DOCS | 🔧 | this file + the impact list below |
| Tag checkpoints with interface + physics versions | ⏳ | add `interface_sha` (obs_spec) and `physics_sha` (scene.xml) to `model.pt` metadata and ONNX sidecar |

## §4 Training, Gates & Reports

| Rule | Status | Note |
|---|---|---|
| Close the editor for long runs | ✅ | headless only; the -game window was closed before training continued |
| Cleanup | ✅ | nothing eligible yet (all runs < 24 h old) |
| Graduation gate: target holds 100 straight episodes, no NaN grads | ⏳ | current gate = ≥ pass fraction over 200 parallel episodes. Add: NaN-gradient counter in PPO, and a "100 consecutive episode" rolling check in `evaluate.py` |
| TensorBoard with every run | 🔧 | server running on http://localhost:6006 over `sim/runs` |
| Log metrics/progress to `/DOCS/<YYYYMMDD>/` | 🔧 | `DOCS/20261106/log.md` |
| HTML report for runs > 30 min, hourly updates, startup time estimate | ⏳ | `train.py` prints iteration count; add ETA line and an HTML report generator from `log.csv` |

## §5 Communication

Adopted from this message on: TL;DR on long replies, 3 roadmap questions for > 100-line changes, end with the main open issue's proposed fix and ask.

---

## Policy impact list for the pending changes (UU_AGENT §3 "before any change")

| Change | Kind | Policies touched | Consequence |
|---|---|---|---|
| Enable humanoid self-collision (non-adjacent pairs) | body physics | **all** (L0 in training, L1–L4 untrained) | `scene.xml` hash changes; re-run A5/A6/A8; L0 restarts from checkpoint (transfer expected, sway/limits may shift) |
| Consolidate L2a/L2b/L2c into one dribble policy with a hand command | rules / roster | L2 only (L2a, L2b become curriculum stages, not exported policies) | director row "DRIBBLE_STATIONARY" already uses `l2c_crossover`; no interface change |
| Merge L1 locomotion and L3a moving dribble into one locomotion-with-ball policy (ball-present command) | roster | L1, L3a | fewer policies, longer training; director rows ROAM/DRIBBLE_MOVING point at one ONNX |
| Add a get-up policy trained from real falls | new skill | new policy + director rows (FALLEN → GET_UP → STAND) | replaces most HARD_RESETs with recoveries; changes PRD §5 "fallen = hard reset" behaviour |
| Shared transition table JSON | rules | none (behaviour unchanged) | UE + Python read the same table |
