# Step 1 — Requirements Contract

Project: Autonomous Streetball Humanoid Gym
Status: DRAFT, awaiting sign-off before Step 2 (Character & Skill Blueprint)
Date: 2026-11-06

---

## 1. What we are training

| Item | Decision |
|---|---|
| Character | One bipedal athletic humanoid, visually the UE5 Mannequin (Manny / Quinn), physically a MuJoCo rigid-body model built to match the mannequin's bone lengths |
| Actions (skills) | Tier 1 balance → Tier 2 court traversal → Tier 3 stationary dribble (R / L / crossover) → Tier 4 moving dribble with loose-ball scramble → Tier 5 pull-up jump shot |
| Interaction objects | One basketball, one court floor, two hoops (pole, backboard, rim), perimeter fence |
| User input | None. Fully autonomous showcase at 1.0x real time |

## 2. Technical setup

| Layer | Choice |
|---|---|
| Physics simulator (training) | MuJoCo Warp (GPU, NVIDIA Warp backend), thousands of parallel environments |
| Physics simulator (runtime) | libmujoco C library, same model XML, same timestep and solver settings, embedded in Unreal via a thin C++ plugin module |
| Game engine | Unreal Engine 5.4 or newer (exact minor version confirmed when the project is created) |
| Engine physics | Chaos disabled for all gameplay actors. Chaos may remain enabled only for cosmetic items that never touch the sim (e.g. cloth on the jersey) |
| Policy runtime | NNE (Neural Network Engine) with the ONNX Runtime CPU provider |
| Training GPU | Local NVIDIA RTX 40/50-series |
| Training framework | Python 3.11+, PyTorch, PPO. Candidate stacks: MuJoCo Playground (Warp backend) or mjlab. Final pick made in Phase C after a smoke test on the local GPU |
| Export | PyTorch → ONNX (opset 17), single fixed observation vector in, single action vector out |

## 3. Coordinate and unit mapping (MuJoCo → Unreal)

| Property | MuJoCo | Unreal | Conversion |
|---|---|---|---|
| Up axis | +Z | +Z | none |
| Handedness | right | left | negate Y |
| Units | metres | centimetres | × 100 |
| Quaternion layout | (w, x, y, z) | FQuat(X, Y, Z, W) | reorder, and flip the sign of the X and Z components for the handedness change |
| Angular velocity | rad/s, world frame | rad/s | negate Y component, sign-flip X and Z (axial vector under reflection) |

Full per-joint mapping table is a Step 2 deliverable.

## 4. Simulation rates

| Loop | Rate | Note |
|---|---|---|
| Physics step | 500 Hz (dt = 0.002 s) | Same in training and runtime. Fixed, never scaled by frame time |
| Policy (control) step | 50 Hz | 10 physics substeps per policy action |
| Render | 30 FPS target | Visuals interpolate between the last two physics states; the physics loop runs a fixed accumulator so a slow frame never changes the sim result |
| Policy inference budget | ≤ 2 ms per step on CPU | Network sized to fit (MLP, 2–3 hidden layers of 256–512) |

## 5. Pre-allocation rule

Every body the sim will ever need exists in the XML at load time: humanoid, ball, floor, two hoops, fence segments. Resets move bodies with `qpos`/`qvel` writes; nothing is created or destroyed during play. The scramble countdown, HUD, cameras and audio are engine-side systems reading sim state, never writing to it except through the reset API.

## 6. Determinism and "behaves identically"

* Same `model.xml`, same libmujoco major.minor, same `timestep`, `integrator`, `solver`, `iterations`, `cone` settings in training and runtime.
* MuJoCo Warp computes in float32; libmujoco runs in float64. Open-loop trajectories will drift after a few hundred steps even with identical inputs. The policy is closed-loop, so this does not affect behaviour, but the Step 4 "Preset Actions" gate is therefore defined as **bounded error** (root position within 2 cm and joint angles within 1° over a 5-second replay), not bit-exact equality.
* The observation vector is assembled by one shared function spec, implemented once in Python and once in C++, with a golden test that feeds the same sim state to both and diff-checks the output.

## 7. Assumptions (correct me if any are wrong)

1. **Windows training.** MuJoCo Warp will be installed natively on Windows 11 with the CUDA toolkit. If the Windows build is flaky, fall back to WSL2 (Ubuntu) on the same GPU.
2. **No reference animations.** The mannequin ships with locomotion clips but no basketball clips. Tiers 1–2 train from rewards alone. For Tiers 3–5 (dribble, scramble, shot), pure reward-driven RL tends to produce unnatural motion and converges slowly; we reserve the option to add a few reference clips (hand-authored or marketplace) as style rewards. Decision deferred to the Tier 3 review.
3. **Simplified hands.** The sim hand is a single rigid palm geom (box or ellipsoid) per side, no fingers. Dribbling is palm-on-ball. Finger bones on the mannequin are posed to a fixed cupped shape.
4. **Visual-only chain net.** The net is a visual and audio effect in Unreal. A score is detected in the sim by the ball passing a sensor site inside the rim from above.
5. **Fence is a static boundary.** Four static box geoms; the ball bouncing off it is simulated, the character is reset if the ball leaves the fence.
6. **Cameras, audio, HUD are not trained.** They are deterministic engine-side logic driven by sim state (character position, ball velocity, contact events exposed by the plugin).
7. **One environment at runtime.** The Unreal showcase runs exactly one humanoid and one ball; parallelism is training-only.
8. **Tier milestones are measured in sim**, then confirmed in Unreal via the Step 4 verification gate, not re-trained in Unreal.

## 8. Out of scope

* Human player input of any kind.
* Multiplayer, opponents, defenders.
* Weather, wind, wet surfaces.
* Full anatomical hands, cloth sim affecting physics.
* Mobile or console targets (desktop Windows only).

## 9. Deliverables by step

| Step | Deliverable |
|---|---|
| 2 | `docs/02_character_blueprint.md`: body/joint table, actuator table, joint-to-mannequin-bone map, skill hierarchy with pass/fail metrics |
| 3 | `docs/03_implementation_plan.md`: Phase A / B / C task list |
| 4 | `sim/` (MJCF + Python env + training scripts + ONNX export), `unreal/` (plugin + project), verification recordings and error reports |
| 5 | Final polish, profiling report |

---

**[STOP] Awaiting approval before Step 2.**
