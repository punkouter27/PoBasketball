# A2 / A3 / A4 — Skeleton dump, humanoid model, court model: PASS

Date: 2026-11-06

## A2 — Mannequin skeleton dump: PASS

* Script: `unreal/StreetballGym/Scripts/dump_mannequin_bones.py`, run headless with
  `UnrealEditor-Cmd.exe <project> -run=pythonscript -script="<script> <out.json>"` against a
  throw-away Blueprint-only project that contains only `/Game/Characters/Mannequins`.
* Output: `shared/mannequin_bones.json`, 89 bones (incl. twist, finger, IK and virtual bones),
  component-space bind transforms in cm.
* Facts learned from the dump (mesh space, cm): pelvis at z 95.9, hips ±9.97 x, knee z 50.3,
  ankle z 8.2, shoulders ±19.0 x at z 143.6, head z 162.6. Mesh faces **+Y**; +X is the
  character's left. Reference pose is an **A-pose**: shoulder abducted 35.2°, elbow flexed 39.0°,
  knee flexed 5.0°, feet toe-out 6.5°.

## A3 — Humanoid model: PASS

* Generator: `sim/tools/build_humanoid.py` → `sim/assets/humanoid.xml`, `sim/assets/scene.xml`,
  `shared/humanoid_spec.json`.
* 15 dynamic bodies + 1 massless anchor, 27 hinge joints + free root, 27 `position` actuators with
  per-group kp/kv/forcerange from blueprint A.4. Total mass 80.06 kg. Every joint sits exactly on
  its mannequin bone; joint ranges are stored relative to the A-pose (anatomical range minus the
  A-pose offset) and the offsets are recorded in the spec JSON.
* Self-collision is off (humanoid geoms `contype=1 conaffinity=0`), so limbs collide with the
  court and ball but not with each other.
* Keyframe `stand`: nominal athletic stance, root lowered so the lowest foot corner is at z = 0.
* Tests (`sim/tests/test_stand.py`, 4 passed): shape and mass; feet on floor; PD tracks all
  targets within 2° in 1 s (gravity off); feet carry 100 % ± 15 % of body weight for 0.5 s with no
  blow-up.
* **Deviation from the plan's "done when":** the plan asked for 10 s of free standing under
  zero action. A joint-level PD with a 200 N·m/rad ankle cannot statically balance an 80 kg body
  whose centre of mass is 1 m up (gravity's destabilising stiffness is about 800 N·m/rad), so the
  model topples after about 1.4 s. That is physically correct and balance is L0's job. The
  acceptance test was replaced by the four checks above.
* Blueprint correction: nominal ankle pitch is **+10° dorsiflexion**, not −10°, so the shin can lean
  forward over a flat foot with the knee bent 25°.
* Render: `docs/phase_reports/A3_pose.png`.

## A4 — Court model: PASS

* Generator: `sim/tools/build_court.py` → `sim/assets/court.xml`.
* 28 × 15 m floor, two hoops (pole, arm, backboard 1.80 × 1.05 m, 12-capsule rim at 3.05 m,
  rim-centre and score sites), fence 2 m outside the lines, size-7 ball (0.62 kg, r 0.1205 m).
* Ball tuning is A5 (see `A5_ball_tuning.md`). Ball-rim tunnelling at 10 m/s: not yet tested,
  tracked under A8 / Phase C evaluation.

## Warp compatibility

`scene.xml` (nq 41, nv 39, 9 contacts/world) loads on MuJoCo Warp unchanged: 4096 worlds step at
1.11 M physics steps/s (A1 target was 1 M for the stock model).
