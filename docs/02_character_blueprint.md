# Step 2 — Character & Skill Blueprint

Project: Autonomous Streetball Humanoid Gym
Status: DRAFT, awaiting sign-off before Step 3 (Implementation Plan)
Date: 2026-11-06
Depends on: `01_requirements_contract.md` (approved)

---

## Part A — Body & Joint Setup

### A.1 Global parameters

| Parameter | Value | Why |
|---|---|---|
| Stature | 1.80 m (UE5 Manny) | Mannequin height; exact bone lengths are read from the skeleton asset in Phase A and override the estimates below |
| Total mass | 80 kg | Athletic build; segment masses use Winter's anthropometric fractions |
| Physics timestep | 0.002 s (500 Hz) | Stiff enough for ball contact, cheap enough for thousands of envs |
| Policy step | 0.02 s (50 Hz) | 10 substeps per action |
| Integrator | `implicitfast` | Stable with PD actuators and joint damping |
| Solver | Newton, 8 iterations, 10 line-search iterations | Supported by both MuJoCo Warp and libmujoco |
| Contact cone | elliptic | Needed for realistic ball spin and palm grip; Warp supports it |
| Gravity | −9.81 m/s² on Z | |
| Default contact `solref` | (0.01, 1) | Firm but not chattering at 500 Hz |
| Default contact `solimp` | (0.9, 0.95, 0.001) | |

### A.2 Rigid bodies (sim → mannequin bone)

Lengths are along the bone; masses follow Winter (1990) fractions of 80 kg. Collision shapes are deliberately simple.

| # | Sim body | Parent | Mannequin bone | Length (m) | Mass (kg) | Collision geom |
|---|---|---|---|---|---|---|
| 0 | `pelvis` (root, free joint) | world | `pelvis` | — | 11.2 | box 0.20 × 0.28 × 0.16 |
| 1 | `torso` | pelvis | `spine_01` … `spine_05` (distributed, see B.3) | 0.50 | 28.6 | capsule r 0.12, len 0.30 |
| 2 | `head` | torso (fixed) | `neck_01`, `neck_02`, `head` | 0.25 | 6.5 | sphere r 0.11 |
| 3/4 | `upperarm_l/r` | torso | `upperarm_l/r` | 0.30 | 2.24 | capsule r 0.045 |
| 5/6 | `lowerarm_l/r` | upperarm | `lowerarm_l/r` | 0.27 | 1.28 | capsule r 0.035 |
| 7/8 | `hand_l/r` | lowerarm | `hand_l/r` (fingers posed fixed) | 0.18 | 0.48 | box 0.10 × 0.09 × 0.03 (palm) |
| 9/10 | `thigh_l/r` | pelvis | `thigh_l/r` | 0.44 | 8.0 | capsule r 0.07 |
| 11/12 | `calf_l/r` | thigh | `calf_l/r` | 0.43 | 3.72 | capsule r 0.05 |
| 13/14 | `foot_l/r` | calf | `foot_l/r` (+ `ball_l/r` fixed) | 0.27 (heel to toe) | 1.16 | box 0.27 × 0.10 × 0.05, 4 corner contact sites |

Total: 15 bodies, 80.1 kg. Clavicles are fixed to the torso in sim and follow it in UE.

### A.3 Joints (27 actuated DoF + 6 root)

Convention: angles in degrees, positive = anatomical flexion / abduction-away / external rotation. Zero pose = mannequin reference pose (arms at sides, feet flat, knees straight) so that `qpos = 0` matches the bind pose after the offset described in B.2.

| Joint | DoF | Axis (body frame) | Range (deg) | Nominal stance (deg) |
|---|---|---|---|---|
| `lumbar_flex` | 1 | Y | −20 … +60 | +5 |
| `lumbar_lat` | 1 | X | −30 … +30 | 0 |
| `lumbar_twist` | 1 | Z | −40 … +40 | 0 |
| `shoulder_pitch_l/r` | 1 | Y | −60 … +180 | +15 |
| `shoulder_abd_l/r` | 1 | X | −30 … +150 | +10 |
| `shoulder_rot_l/r` | 1 | Z | −90 … +90 | 0 |
| `elbow_l/r` | 1 | Y | 0 … +145 | +30 |
| `wrist_flex_l/r` | 1 | Y | −70 … +80 | 0 |
| `wrist_dev_l/r` | 1 | Z | −25 … +25 | 0 |
| `hip_flex_l/r` | 1 | Y | −30 … +120 | +15 |
| `hip_abd_l/r` | 1 | X | −30 … +45 | +5 |
| `hip_rot_l/r` | 1 | Z | −40 … +40 | 0 |
| `knee_l/r` | 1 | Y | 0 … +150 | +25 |
| `ankle_pitch_l/r` | 1 | Y | −45 … +25 | −10 |
| `ankle_roll_l/r` | 1 | X | −25 … +25 | 0 |

`nq = 7 + 27 = 34`, `nv = 6 + 27 = 33`. Neck is fixed in this blueprint; a 2-DoF neck can be added later without changing anything else.

### A.4 Motor controls (actuators)

Policy outputs a 27-vector in [−1, 1]. Each value becomes a PD position target:

```
target_i = clip( nominal_i + a_i * scale_i , lo_i , hi_i )
scale_i  = 0.5 * (hi_i − lo_i)
```

MuJoCo `<position>` actuators with `kp` and `kv`, `forcerange` = ±τ_max. Identical actuator block in training and runtime.

| Joint group | kp (N·m/rad) | kv (N·m·s/rad) | τ_max (N·m) |
|---|---|---|---|
| hip (3) | 400 | 40 | 300 |
| knee | 400 | 40 | 300 |
| ankle (2) | 200 | 20 | 150 |
| lumbar (3) | 300 | 30 | 200 |
| shoulder (3) | 150 | 15 | 100 |
| elbow | 100 | 10 | 80 |
| wrist (2) | 30 | 3 | 20 |

Armature 0.01 on every hinge for solver stability.

### A.5 Objects

| Object | Geom | Mass | Key parameters |
|---|---|---|---|
| Basketball | sphere r 0.1205 m (size 7) | 0.62 kg | friction (0.6, 0.02, 0.005) vs asphalt, (0.8, 0.02, 0.01) vs palm. `solref`/`solimp` tuned in Phase A so a drop from 1.80 m rebounds to 1.30 m (±0.05), the FIBA/NBA spec |
| Court floor | plane 28 × 15 m | static | friction 0.9 vs feet |
| Hoop ×2 | pole capsule, backboard box 1.80 × 1.05 m, rim as 12 capsules in a ring r 0.2286 m at height 3.05 m, scoring sensor site 0.1 m below rim centre | static | rim friction 0.5 |
| Fence | 4 static boxes, 3 m tall, 2 m outside the court lines | static | ball bounces, character resets if ball passes beyond |

All objects exist in the XML from load; nothing is spawned.

### A.6 Fall and contact definitions (used by every skill)

* **Fallen:** pelvis height < 0.55 m, OR any body other than `foot_l/r`, `hand_l/r` touches the floor for > 0.2 s.
* **Ball in control:** ball centre within 0.75 m horizontally of pelvis AND ball height < 1.3 m AND last palm contact < 0.6 s ago.
* **Loose ball:** control lost; starts the 3.0 s scramble countdown.
* **Scored:** ball passes the rim sensor site moving downward.

---

## Part B — Position & Movement Mapping (sim → Unreal)

### B.1 Frame conversion (per vector / quaternion)

```
UE.pos  = ( x * 100,  -y * 100,  z * 100 )             // cm, left-handed
UE.quat = FQuat( X = -qx,  Y = qy,  Z = -qz,  W = qw )  // handedness flip
UE.vel  = ( vx * 100, -vy * 100, vz * 100 )
UE.angv = ( -wx, wy, -wz )                              // axial vector
```

### B.2 Bone driving rule

Bones are driven in **world space from sim body orientations**, not by copying joint angles. This removes any dependence on how the mannequin's local bone axes are oriented.

```
at init (reference pose, all qpos = 0):
    offset[b] = inverse( toUE(sim_body_quat_ref[b]) ) * bone_world_quat_bind[b]

every render frame:
    R = toUE( sim_body_quat[b] )
    bone_world_quat[b] = R * offset[b]
    bone_world_pos[root] = toUE( sim_root_pos )      // only the root gets a position
```

Child bones inherit position from the skeleton hierarchy, so lengths come from the mannequin mesh; the sim lengths are matched to it in Phase A so the two never disagree visibly.

### B.3 Body → bone table

| Sim body | Drives bone(s) | Rule |
|---|---|---|
| `pelvis` | `root`, `pelvis` | position + rotation |
| `torso` | `spine_01`, `spine_02`, `spine_03` | lumbar rotation q split as slerp(I, q, 1/3), slerp(I, q, 2/3), q; `spine_04`, `spine_05`, `clavicle_l/r` rigid with torso |
| `head` | `neck_01`, `neck_02`, `head` | rigid with torso (fixed joint) |
| `upperarm_l/r` | `upperarm_l/r` | rotation |
| `lowerarm_l/r` | `lowerarm_l/r` | rotation; `lowerarm_twist_*` bones take 50 % of wrist rotation |
| `hand_l/r` | `hand_l/r` | rotation; finger bones fixed cupped pose |
| `thigh_l/r` | `thigh_l/r` | rotation; `thigh_twist_*` rigid |
| `calf_l/r` | `calf_l/r` | rotation; `calf_twist_*` rigid |
| `foot_l/r` | `foot_l/r`, `ball_l/r` | rotation; toe bone rigid |

### B.4 Non-skeletal objects

| Sim | Unreal actor | Update |
|---|---|---|
| ball | StaticMeshActor, Chaos off | pos + quat every frame (quat matters for seam spin) |
| hoops, fence, floor | static | placed once from sim geom positions at load |
| contacts (ball-floor, ball-palm, ball-rim, foot-floor) | audio/VFX events | read from `data.contact` each physics step, debounced, with impact speed for pitch/volume |

### B.5 Render interpolation

Physics advances on a fixed 0.002 s accumulator. The renderer stores the last two sim states and interpolates (lerp for position, slerp for quaternion) with `alpha = accumulator / dt`. Visuals never extrapolate.

---

## Part C — Skill Hierarchy

### C.1 Shared training setup

* **Policy:** one MLP per level (obs → 512 → 256 → 128 → 27), tanh output. Each level is initialised from the previous level's weights.
* **Observation (shared base, 107 floats):** gravity direction in pelvis frame (3), pelvis linear velocity local (3), pelvis angular velocity local (3), joint positions (27), joint velocities (27), previous action (27), ball position relative to pelvis (3), ball velocity relative to pelvis (3), ball-in-control flag (1), left/right palm-to-ball distance (2), feet contact flags (2), plus a level-specific task block (see table, padded to 12). Total 119.
* **Domain randomisation (all levels):** body mass ±10 %, floor friction 0.6–1.1, motor kp ±10 %, ball mass ±5 %, ball restitution ±10 %, action latency 0 or 1 policy step, random external push 0–150 N for 0.2 s every 3–8 s (levels 0–1 heavier pushes).
* **Pass test:** 200 evaluation episodes with randomisation on, deterministic policy. Thresholds below are per-level.

### C.2 Levels

| Level | PRD tier | Task block (12) | Reward sketch | Termination | **Pass target** |
|---|---|---|---|---|---|
| **L0 Stand** | 1 | none | upright (gravity·z), pelvis height ≈ 0.95 m, feet stay within 0.15 m of start, low joint velocity, low torque | fallen, or either foot moves > 0.15 m | 95 % of episodes survive 60 s with pushes up to 150 N; mean pelvis sway < 3 cm |
| **L1 Traverse** | 2 | waypoint direction (2), distance (1), commanded speed (1) | velocity tracking toward waypoint (0.8–3.0 m/s), heading alignment, foot clearance, no fall, energy penalty | fallen, out of court | 90 % of episodes reach 10 random waypoints (whole 28 × 15 m) within 90 s, no fall |
| **L2a Dribble right** | 3 | hand flag (1), target apex height (1) | ball apex in 0.9–1.1 m, ball horizontal distance to pelvis < 0.5 m, palm contact on downstroke, pelvis stays within 0.3 m of start, upright | fallen, ball loose > 3 s, ball out of 1.5 m radius | 50 consecutive bounces in 85 % of episodes |
| **L2b Dribble left** | 3 | same | same, mirrored | same | same |
| **L2c Crossover** | 3 | hand flag toggles every N bounces | same + bonus for alternating hand on command | same | 50 consecutive with ≥ 10 hand switches in 80 % |
| **L3a Moving dribble** | 4 | waypoint (2), distance (1), speed (1), hand flag (1) | L1 velocity tracking + L2 ball terms, ball allowed up to 0.8 m ahead | fallen, loose > 3 s | 100 m course (sequence of waypoints) at ≥ 1.5 m/s with ball in control ≥ 90 % of the time, in 75 % of episodes |
| **L3b Scramble** | 4 | ball relative pos/vel (already in base), countdown remaining (1) | approach ball, palm contact, regain control, return upright; starts from randomised loose-ball states (ball 0.5–4 m away, rolling or bouncing) | fallen, countdown expired | regain control within 3.0 s in 80 % of starts |
| **L4 Jump shot** | 5 | hoop relative position (3), shoot trigger (1) | on trigger: gather (both palms on ball), vertical jump ≥ 0.25 m, release velocity toward rim with arc 45–55°, bonus on score, land without fall | fallen, ball loose before trigger > 3 s | ≥ 30 % scored over 20 shots per episode, from random spots inside the 6.75 m arc, in 60 % of episodes (mean FG ≥ 30 %) |

### C.3 Runtime state machine (Unreal)

One policy loaded per level; the engine selects which one runs each 50 Hz step.

```
STAND --(L1 passed)--> ROAM --(ball present)--> DRIBBLE_STATIONARY --> DRIBBLE_MOVING --> JUMP_SHOT
                                                       |                     |
                                                       +----- loose ball ----+--> SCRAMBLE --(control regained)--> previous state
                                                                                      |
                                                                                      +--(3 s expired / fallen / ball out)--> HARD_RESET
```

The showcase advances a tier only when the live counter hits the PRD milestone (60 s, 10 waypoints, 50 bounces, 100 m + 3 saves, 30 % of 20). HUD reads these counters directly.

### C.4 Known risks

1. **Palm-only dribbling.** Flat-box palms with no fingers may make crossover control marginal. Mitigation: ellipsoid palm with slightly concave contact via two offset geoms; evaluate at L2a before committing.
2. **Natural-looking motion** for L2–L4 without reference clips (contract assumption 2). Revisit after L2a results.
3. **Rim as capsule ring.** Ball-rim bounces will be slightly polygonal; 12 segments is a starting point, raise to 16 if shot evaluation looks wrong.

---

**[STOP] Awaiting approval before Step 3.**
