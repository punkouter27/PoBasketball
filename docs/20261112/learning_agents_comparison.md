# Learning Agents comparison

## Approved scope and audit (before implementation)

The user approved an isolated Learning Agents + Chaos comparison on 2026-11-12
("do it", following the proposed balance/walking comparison and Chaos exception).
The no-Chaos rule still applies to the original Court/MuJoCo showcase.

- New experimental map and game mode only; do not change the default Court map.
- Import the existing humanoid geometry, masses, actuator order, nominal pose,
  gains, and torque limits from the frozen model/contracts without modifying them.
- Learning Agents PPO trains independent comparison weights from scratch.
  MuJoCo is used to read the model and reference poses, not to step this environment.
- Initial skills: balance and commanded walking. Basketball tiers are not included.
- Existing production policies, director rows, and frozen shared interfaces: unchanged.
- Comparison interface revision: `chaos_la_v1`, 119 observation slots and 27 actions
  following the existing slot/joint order. Weights are not interchangeable.
- Chaos multi-axis constraints and collision/integration behavior are not identical
  to MuJoCo. Results are an experimental full-stack comparison, not a determinism gate.
- Initial verification is a bounded smoke run, not an eight-hour training job and
  not a claim that the humanoid has learned balance or walking.

## Implementation

The new [LearningAgentsComparison map](../../unreal/StreetballGym/Content/Maps/LearningAgentsComparison.umap)
uses its own game mode, tracking camera, Manny renderer and experimental HUD.
Open this map and press Play, or use the launcher below. The default map remains Court.
Only comparison actors enable Chaos. Physics/timestep process settings are restored
when the comparison world ends.

[LearningAgentsComparison.cpp](../../unreal/StreetballGym/Source/StreetballGym/LearningAgentsComparison.cpp)
imports 15 collision bodies, 14 constraints and 27 actuator definitions from the
existing MJCF. It converts metres to centimetres and reflects polar/axial vectors
explicitly. Bodies are pooled at initialization, not spawned on episode resets.
Control is 50 Hz; Chaos uses 2 ms substeps and torque-limited native angular servos.
The existing XML gains and torque limits are converted to UE units.
The native constraint approximates ordered multi-axis hinges; inertia, rotor
armature, damping, swing limits and contact solving are not MuJoCo-equivalent.
The torque reward term estimates PD effort, not measured solver motor torque.

The final physics revision is `native_drive_v2`. Validation fixed anatomical
constraint frames being overwritten on reset, explicit 20 ms-held torque
instability, and Chaos's child-first/parent-second constraint convention.
Snapshots from earlier development revisions are rejected. No frozen contract,
production policy or state-machine row was revised.

Learning Agents PPO uses independent 2x256 policy networks, CPU training,
TensorBoard, reward/action-rate penalties and separate balance/walking weights.
The 119-slot layout is retained, but this is a separate comparison interface,
not policy interchangeability or an exact observation-parity gate.
Unused basketball slots contain a stationary task reference; no ball skill is trained.
Walking commands +X velocity at 1.6 m/s. Balance terminates on excessive foot drift;
both tasks terminate on falls/out-of-bounds and truncate at the episode time limit.

## Try it

Run these commands from the repository root in PowerShell:

```powershell
# Separate preview; no training process. Starts with an untrained network.
.\unreal\StreetballGym\Scripts\run_learning_agents.ps1 -Mode Preview -Tier 1

# Commanded walking comparison (also initially untrained).
.\unreal\StreetballGym\Scripts\run_learning_agents.ps1 -Mode Preview -Tier 2

# Bounded PPO smoke: 16 agents, 8,192 transitions, 5-second episode limit.
.\unreal\StreetballGym\Scripts\run_learning_agents.ps1 -Mode Smoke -Tier 1 -Agents 16

# Preview the locally verified balance candidate. It is NOT a trained skill.
.\unreal\StreetballGym\Scripts\run_learning_agents.ps1 -Mode Preview -Tier 1 `
  -Resume .\unreal\StreetballGym\Saved\LearningAgents\balance_comparison_verified

# Example longer bounded training command; not executed as part of this task.
.\unreal\StreetballGym\Scripts\run_learning_agents.ps1 -Mode Train -Tier 1 `
  -Agents 16 -Steps 1000000 -TimeoutSec 3600
```

Tier 1 means balance and tier 2 means commanded walking **in this map only**.
These are not the Court director's five basketball tiers. Preview renders only
the first agent; the remaining training agents are independent pooled environments.
Press Alt+F4 to close a standalone preview.

`-Resume` accepts a matching Learning Agents output directory, never a MuJoCo
ONNX/checkpoint. It restores encoder/policy/decoder/critic weights, not optimizer,
replay buffers or cumulative training counters. Tier, interface, physics revision,
snapshot shape and network compatibility are checked. Do not warm-start walking
from the balance checkpoint with this launcher.

`-Output` must be a new directory. Without it, timestamped runs go under
[Saved/LearningAgents](../../unreal/StreetballGym/Saved/LearningAgents).
Snapshots and summary are saved periodically and at bounded completion.
The headless wrapper checks the explicit completion log and summary, because
graceful Unreal failures can otherwise appear to have a zero Windows exit code.
Timeouts remain failures; choose a timeout appropriate to the training budget.
For >30-minute training, follow the existing save/commit/editor-close and reporting
requirements first. No additional long run is authorized or running here.

Each run saves `metrics.csv`, `episodes.csv`, `summary.json`, and four `.bin`
network snapshots. Partial `buffer_reset`/`run_end` episode records are not success
episodes; `foot_drift` is a balance failure even if `fallen` is zero.
`foot_contact_steps` counts control frames with a recent foot-ground hit.
Loss/reward TensorBoard event files are retained under
[Intermediate/LearningCore/TensorBoard](../../unreal/StreetballGym/Intermediate/LearningCore/TensorBoard).

```powershell
.\unreal\StreetballGym\Intermediate\PipInstall\Scripts\python.exe -m tensorboard.main `
  --logdir .\unreal\StreetballGym\Intermediate\LearningCore\TensorBoard `
  --host 127.0.0.1 --port 6006
```

Learning Agents, LearningCore, NNERuntimeBasicCpu and Tensorboard are enabled.
Unreal installed their required Python packages into its managed environment.
The comparison map is included; its one-time generation script refuses to
overwrite a finished map. Headless execution still exclusively uses
[run_headless.ps1](../../unreal/StreetballGym/Scripts/run_headless.ps1).

## Verified results

- Win64 Development editor build: **PASS**.
- All 16 `Streetball` automation tests: **PASS**, including the new import/reset
  regression and the original MuJoCo observation, live-physics and presentation gates.
- Balance: 16 agents, **8,192 transitions, 1 PPO update**, 30.9 seconds wall time.
  242 foot-drift failures, 15 falls, 29 partial episode records; 7,179 contact frames.
- Walking: 16 agents, **8,192 transitions, 1 PPO update**, 31.3 seconds wall time.
  110 falls and 31 partial episode records; 6,814 contact frames.
- Both tasks: finite recorded physics states, actual floor contacts, four nonempty
  snapshots and saved CSV/TensorBoard metrics. Each TensorBoard run has 15 finite
  scalar series, including policy and critic loss. Neither reached the 5-second limit.
- Weight restore: 250-transition / 5-second preview completed, with two falls.
  An additional 8,192-transition resumed training smoke completed and updated weights.
- Wrong-tier restore: rejected explicitly; the launcher returned a nonzero failure.
- Visible preview: Manny, camera, separate experimental HUD and `261112` build stamp
  verified; original Court and new comparison captured before/after.

The two task smokes ran concurrently; wall times are not controlled throughput
benchmarks. Older debugging runs are excluded and retained because they are less
than 24 hours old. Only `native_drive_v2` candidates should be used.

See the [HTML comparison report](../../SCREENSHOTS/learning_agents_comparison.html)
for screenshots and four progress graphs, and
[recorded daily metrics](learning_agents_metrics.json) for source data.
The new tests are in
[LearningAgentsComparisonTests.cpp](../../unreal/StreetballGym/Source/StreetballGym/Tests/LearningAgentsComparisonTests.cpp).
The latest existing MuJoCo live-physics regression output is
[Step4_gate_unreal.md](../phase_reports/Step4_gate_unreal.md).

**No convergence, production qualification or equal-budget comparison is claimed.**
The existing MuJoCo balance evaluation passed 200 60-second episodes; the new
Learning Agents candidates only passed pipeline smoke checks. They still fall
and slide. Matching task randomization/rewards, longer training and the required
100-consecutive-episode/contact/kinematic gates remain necessary before a fair
policy-quality comparison or any production export.
