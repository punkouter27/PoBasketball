# 2026-11-16 — Daily Log

## 00:xx — 10-hour training queue + grandma character skin (user request)

### Audit (before changes)

| Item | Change | Affects |
|---|---|---|
| Main character visual | `grandmaRIGGED_fixed.fbx` replaces `SKM_Manny_Simple` as the skinned mesh. **Visual skin only** (user choice): re-proportioned in headless Blender so her joints and bind pose sit on the mannequin joints the physics body was built from. | Unreal presentation only |
| Physics body / MJCF | none (`humanoid.xml`, `court.xml` unchanged; physics_sha unchanged) | — |
| Observation / action interface | none (`obs_spec.json` unchanged) | — |
| Policies touched (training only) | scramble (`l3b_scramble`), dribble (`l2a_dribble_r` -> `l2a_cycles` -> `l2a_push`) | candidates; production export only if the 200-episode gate + 100-consecutive hold pass |
| Production weights | balance / locomotion left unchanged | — |
| State machine rows | none | — |

### Why the dribble lineage restarts

This checkout is a fresh clone. `sim/runs/` is gitignored and empty, and the previous project folder no longer
exists, so the Nov 11 candidates (`l3b_scramble_n11q2` at 81.5 %, `l2a_push_n11q2`) are lost. Both families restart
from the production locomotion actor. No `.pt` survived either, so `sim/tools/onnx_to_ckpt.py` rebuilds an
actor-only checkpoint from `shared/policies/locomotion.onnx` (normaliser unfolded from the graph constants; it refuses
to write unless the PyTorch/onnxruntime max abs diff is < 1e-5).

### Queue

Plan `grandma_20261116` in `sim/streetball/queue.py`, tag `n16`, 10 h budget (25 min reserve):

1. `l3b_scramble` 150 min from locomotion (actor only), gate `l3b_scramble`
2. `l2a_dribble_r` 75 min from locomotion (actor only), gate `l2a_dribble_r`
3. `l2a_cycles` 90 min from step 2, gate `l2a_dribble_r`
4. `l2a_push` 120 min from step 3, gate `l2a_dribble_r`, family dribble
5. `l3b_scramble` 60 min full resume
6. `l2a_push` remaining time, full resume

## 10:33 — queue launched

`sim/runs/queue_n16_20261116.ps1` (hidden, WMI) -> `uv run python -m streetball.queue --hours 10 --plan grandma_20261116 --tag n16`.
Started 10:33, deadline 20:33. TensorBoard on http://localhost:6006 (`sim/runs/tensorboard.ps1`). Hourly status goes to
`DOCS/20261116/hourly_status.md`. Smoke check before launch: 2 min `l3b_scramble` from the rebuilt actor, 29k fps,
interface/physics SHA identical to production (`ccfa18d6f9aaf2a5`, `ac1c8d03c1e036df+1eba556a91fae556`); purged.

## Grandma skin

- Source: `C:\Users\punko\Downloads\grandmaRIGGED_fixed.fbx`, copied to `unreal/StreetballGym/Content/Art/Raw/Grandma/`.
  CC-style rig with mannequin bone names, 118 bones, 24 866 verts, 92 facial shape keys, packed 4K diffuse + normal.
- `Scripts/retarget_grandma_blender.py` (headless Blender 5.3): global scale 1.525 (torso), every main joint moved
  onto Manny's bind joint (max error 0.00 mm), limbs stretched along the segment (thighs 1.6x, upper arms 1.24x /
  1.87x: the source rig's left elbow bone sits high), soles remapped to z = 0 (were 2.2 / 2.8 cm below the court),
  all shape keys deformed with the same maps. Output `Content/Art/Exports/Grandma/SK_Grandma.fbx`, 1.76 m tall.
- Previews (`Scripts/render_character_preview.py`, red dots = Manny joints): `SCREENSHOTS/grandma_before_*.png`,
  `SCREENSHOTS/grandma_after_*.png`.
- Code: `AStreetballCharacter::ApplyMainCharacterMesh()` loads `/Game/Art/Characters/Grandma/SK_Grandma` before the
  bone mapper captures its bind offsets; falls back to Manny if the asset is missing; `-StreetballCharacter=Manny`
  forces the old skin.
- Unreal import + editor build are **deferred until the queue exits**: with training running the machine had 5.8 GB
  free RAM and only 2.9 GB commit headroom, so an editor commandlet or MSVC build risked killing the training
  process. `Scripts/post_queue_grandma.ps1` waits for the queue, imports, builds, checks the bind joints against
  Manny (<= 1 cm), runs the Streetball automation tests, and writes `DOCS/<day>/post_queue_grandma.md`.

## 10:49 — run stopped early (user: "finish up all in 15 mins")

- Queue and trainer killed at 10:49 after 16 min. Last checkpoint `sim/runs/l3b_scramble_n16q1/model.pt`
  (19.7 M steps, 0 NaN-gradient batches). Dribble stages never started.
- 200-episode gate `l3b_scramble`: **0 % success, failed** (falls 2 %, mean episode 3.0 s). Result saved as
  `eval_l3b_scramble_n16q1.{json,md}` in this folder; `DOCS/phase_reports/eval_l3b_scramble.*` keeps the Nov 11
  record. No ONNX exported; production weights unchanged.
- Post-queue runner fixes: arguments now go through `-EditorArgs` (after `--` PowerShell bound `-run=pythonscript`
  to `-Editor`, so Unreal never started), and the editor build now runs before the import (a fresh clone has no
  `Binaries/`). Relaunched at 11:01 with `-NoWait`; progress in `post_queue_grandma.md`.

## 11:20 — grandma live in Unreal, verified

- Build `StreetballGymEditor`: succeeded (215 s). Import: `/Game/Art/Characters/Grandma/SK_Grandma` (+ skeleton,
  material, diffuse/normal textures).
- Bind-joint check of the imported mesh vs `shared/mannequin_bones.json`: max offset **0.00 cm** on all 25 mapped joints, PASS.
- Automation `Streetball.*`: **16/16 pass** with `Character mesh: SK_Grandma`. B5.BoneMapper: reference pose error
  0.00000 deg, pelvis bone = sim pelvis (95.897 cm). The first pass had 2 failures (B5, C3) caused only by the
  fresh clone missing `Content/Sim/policies/` (gitignored): fixed by running `sim/tools/sync_policies_to_unreal.py`,
  which now also copies `dummy_policy.onnx`.
- Runner fixes: bone-dump output path uses forward slashes (UE's `-script=` parsing turned `\2` into a control char).

## 12:30 — play-through issues fixed (presentation only; no sim/contract change)

Found by playing tiers 1-5 with grandma (`-game`, 40 s each, plus a Manny run for comparison).

| Issue | Cause | Fix |
|---|---|---|
| Every MJCF colour ignored (ball, rims grey; boards dark) | the engine shapes' slot material is `DefaultMaterial`, which has no `Color` parameter, so the dynamic material's colour was dropped | `AStreetballWorld::Setup` builds the dynamic material from `/Engine/BasicShapes/BasicShapeMaterial`; the textured floor keeps its own material. The ball now renders orange (court.xml rgba). |
| Loose ball out of frame in the press-box shot | fixed 62 deg FOV | FOV sized from the athlete-ball spread (`PressBoxFovMax` 80 deg), camera x follows 0.5 x midpoint |
| Black void above the fence in the high shot | nothing rendered outside the court | visual-only 400 m ground apron 2 cm under the court (no sim body, no collision), allocated once in Setup |
| Reset log "dribble hand +0" | printed the command-line override, not the hand | `UStreetballDirector::GetHand()`; log prints left/right (tiers 3-4) or n/a, plus "(forced)" |
| Tier 3 "Distance 8.5 m" while stationary | not a bug: `TotalDistance` is pelvis travel and the dummy dribble policy falls about every 2 s; reset teleports are already excluded | none |
| Tiers 3-5 fall and reset every 2-5 s | no trained dribble/scramble/shot policy; the dummy fallback runs | needs training (queue `grandma_20261116`) |

Build OK, `Streetball.*` 16/16 pass. Tier 1/3 replays show the orange ball and real colours; the apron in the
high shot is built and tested but has no clean screenshot (the capture grabbed the desktop).
