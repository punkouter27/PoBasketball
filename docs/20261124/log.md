# 2026-11-24: feature upgrades (RL shaping, symmetry, get-up level, presentation)

Owner decisions for this batch (asked before implementation, UU_AGENT §5):

- RL items land as **code with every new weight at 0** (or the feature off by default). Shipped policies in
  `shared/policies/` are **not retrained** and behave exactly as before; no gate is re-run because no policy changes.
- **No gait-phase clock**: the observation contract (`shared/obs_spec.json`, PhaseA hashes) stays frozen. Swing timing
  is shaped by a reward term that needs no new inputs.
- Assets behind sign-ins (Fab Megascans, MetaHuman, Audio2Face, NVIDIA ACE) are fetched with the owner signed in.

## Audit trail (written before the changes)

| Area | Change | Affected policies | Interface revision |
|---|---|---|---|
| `shared/reward_config.json` | new penalty terms `power_abs`, `com_offset`, `com_vel_z_sq`, `ang_vel_xy_sq`, `short_swing`, all weight 0 | none (weight 0; shipped policies not retrained) | reward config gains 5 keys; obs/action unchanged |
| `UStreetballRewardConfig` | 5 matching float properties, default 0 | none | DataAsset gains 5 fields |
| `sim/streetball/mirror.py` | left/right mirror of obs and actions, derived from the MJCF joint axes | none | none (read-only use of the obs layout) |
| `sim/streetball/ppo.py` | optional symmetry loss `sym_coef` (default 0) | none | none |
| `RandomizationConfig.motor_kd` | separate kd range, default (1, 1) = off | none | none |
| `levels/l5_getup.py` | new get-up level, reset from recorded real falls | new skill family, untrained; no director row until a policy passes its gate | none (same obs/action layout) |
| curriculum | `l5_getup` gate 0.80 | none | Unreal `AddStage` list gains one row |

## Result (same day)

- Mirror check: obs of a physically mirrored state equals the mirrored obs to < 1e-5 over 20 random poses
  (`sim/tests/test_mirror.py`). Joints that flip sign: wrist_dev_l/r, ankle_roll_l/r, lumbar_lat, lumbar_twist.
- Fall bank: `sim/data/fall_states.npz`, 512 falls from 547 pushes (shipped `l0_stand.onnx`), pelvis 0.11–0.36 m.
- `l5_getup` and `--sym-coef` / `--motor-kd` smoke-trained 3 iterations each on 256 worlds (runs deleted: < 5,000
  steps). `interface_sha` unchanged (`9879b4bebba21aa3` before and after).
- Python: ruff clean, 34 tests pass (GPU included). Unreal: editor target builds; `DA_RewardConfig` re-synced from the
  JSON by the new `Scripts/sync_reward_config_asset.py`; `Streetball.Showcase.*` 4/4 pass.

## Presentation items already present before this batch (no change needed)

Substrate (`r.Substrate=True`, layered court/ball/rim/skin materials), contact-driven MetaSounds (`Impact` input from
`FContactAudioProcessor`), contact-driven pooled Niagara bursts (`CourtFX`), PCG neighbourhood with litter, weeds,
cracks and puddles (`build_environment.py`, `M_CourtAsphalt`), Groom hair and Chaos Cloth hem (2026-11-17).

## Time of day (presentation only; no policy, director row or interface affected)

`UCourtTimeOfDaySubsystem`: sun → moon, sky light scale, 4 streetlight spot lights (one per PCG `SM_StreetLight`
instance; the PCG ring at 17 m spacing yields 4, not 17), night exposure volume. Start hour reproduces the level's sun:
before vs after mean pixel difference 1.7/255 over the court. MegaLights tried and reverted (on-screen warning without
hardware ray tracing). Report: `SCREENSHOTS/20261124_time_of_day/index.html`. `Streetball.Showcase.*` 5/5 pass.

## Broadcast replays (presentation only)

Movie Render Queue plugin enabled; `LS_Broadcast` + `MRQ_Broadcast` in `/Game/Project/Core/Cinematics` (built by
`Scripts/make_broadcast_render.py`), rendered by `Scripts/render_broadcast.ps1`: 360 frames, 1920x1080, tier 3 dribble at
17:36. Sample in `SCREENSHOTS/20261124_time_of_day/` (mrq_frame.jpg, mrq_broadcast.gif).

## Megascans (local only; presentation)

Fab library (owner signed in and accepted the Fab EULA): Asphalt, Brick Wall Worn, Graffiti, Graffiti Tag, Chain Link (a
single chain-link ring, not a fence: added by mistake, unused). Downloaded at 2K: Asphalt only (Chrome blocked the
other downloads). Repo is public, so the files are git-ignored (owner decision); `M_CourtAsphalt` takes the scan through
parameters, applied at startup from `Content/Art/megascans.json`. Fresh-clone render unchanged (0.72/255).
Streetball.* automation 27/27.

## MetaHuman grandma (local only; presentation)

Grace preset -> MHC_Grandma (cloud auto-rig + texture sources, owner signed in), body constraints x1.152 (180 cm),
Optimized build; body + outfit exported and re-proportioned onto Manny's joints by `retarget_grandma_blender.py` with
global scale 1.0 (new optional arg; feet-less meshes now skipped by the sole fix), 0.00 mm joint error. Native face with
ABP_Face (copies the pose from the body), grooms rigid on the head at helmet LOD 5 (bound grooms render nothing here;
unbound card LODs crashed at a close-up camera cut). `AStreetballCharacter` tries the MetaHuman body first
(`Content/Art/Exports/GrandmaMH/parts.json`), `-StreetballNoMetaHuman` opts out. No policy, obs, director row or physics
change. Skin cache enabled for the project. Streetball.* 27/27 with the MetaHuman active.
Open: groom binding, outfit (default tee/shorts), lip-sync (Audio2Face).

## Dribble Lab HUD (presentation/UI only; audit trail written before the change)

User request: "simplify the ui with a focus only on the dribble behaviours ... switch dribble behaviours and switch humanoids".
Owner answers: live skin swap on the same MuJoCo body; the 4 director modes; clickable panel + hotkeys, old scoreboard hidden.

| Area | Change | Affected policies | Interface revision |
|---|---|---|---|
| `UStreetballHUDWidget` | new "Dribble Lab" panel (behaviour + humanoid buttons, live dribble stats); tier scoreboard, milestone bar and mode banner hidden while it is on | none | none |
| `AStreetballWorld` | dribble focus (game only, not automation worlds; `-StreetballClassicHUD` opts out): starts in stationary right-hand dribble, keys 1-4 behaviour, H humanoid | dribble (no change to the brain: same `dribble.onnx`) | none |
| director rows | none: the behaviours only set the existing `ForcedHand` / `MaxTier` / start tier (same as `-StreetballDribbleHand`, `-StreetballMaxTier`, `-StreetballStartTier`) | none | none |
| `AStreetballCharacter` | all skins (MetaHuman grandma, grandma, Manny, Quinn) preloaded at startup; swap = mesh asset change on the one component + bone-mapper re-init; extras toggled by visibility | none (visual only; bones still mirror physics) | none |

Behaviours: 1 Right hand (tier 3, hand +1), 2 Left hand (tier 3, hand -1), 3 Crossover (tier 3, table hand switches),
4 Moving (tier 4, right hand). Only 1 passed its gate (`dribble_anchor10`); 2-4 are shown as untrained.
Pre-change playlist (60 s each, seed 7): resets right 0 (after startup), left 67, crossover 34, moving 26.

Result (same day): editor target builds; `Streetball.*` automation 28/28 pass (new `Streetball.B10.DribbleLab`: behaviour ->
tier/hand/cap mapping, skin switch leaves sim time and qpos bit-identical with no reset, panel highlights/stats/delegate).
Found while testing: `UMuJoCoBoneMapper::Initialize` called `Sim->ResetData()` on every call (time, ctrl, warm start cleared,
only qpos/qvel restored); the reference rotations are now cached per sim, so only the first call touches the sim.
Scripted run (`-StreetballLabSteps`) switching all behaviours and skins: right hand 0 resets, Grandma skin 35 clean bounces
over a 21.6 s run spanning two skin swaps. Report: `SCREENSHOTS/20261124_dribble_lab/index.html`.

## Face camera + grandma smile/frown (presentation only)

Owner: "camera view that zooms in on her face, use metahuman to add smile and frown"; "when training is going well have
grandma slowly smile more and more, when training fails show frown". Owner choices: signal = the live dribble, camera
mode + F key, exaggerated, all grandmas. No policy, observation, action, director row or physics change.

- `UStreetballAnimInstance` emits extra animation curves with the pose; the MetaHuman face's `ABP_Face`
  (CopyPoseFromMesh, copies curves) passes them to `ABP_Face_PostProcess` (RigLogic). `AStreetballCharacter::BuildFaceRig`
  turns ARKit poses of Epic's `PA_MetaHuman_ARKit_Mapping` (MouthSmile, CheekSquint, MouthFrown, BrowDown, ...) into
  weights on 133 `CTRL_expressions_*` curves. Epic's Blueprints are not edited.
- Mood (`AStreetballWorld::UpdateFaceMood`): smile target = clean streak / 8, rises at 0.35/s; a reset or lost ball
  sets frown = 1, fading over 2.5 s (held at >= 0.75 while the ball is loose). CC grandma: same moods on CC morph names
  in `FGrandmaVoicePlayer` (a frown wins over a voice line's mood; lip-sync keeps the jaw).
- Camera mode `Face` (5th in the C cycle, F toggles): yaw from the head bone's facing blended with the body heading,
  1.1 m out, 25 deg below the face, cuts instead of gliding when the target jumps > 60 cm (reset teleports).
- Fixed on the way: `ResetEpisode` (R) now prepares the ball like the director's resets (`PrepareReset`); before, a manual
  reset in a dribble tier always started with a lost ball, and in tier 1 with the ball beside the foot.
- Found, not fixed: `SK_Grandma` / `SK_Grandma_Cloth` have 0 morph targets in Unreal although their FBX exports carry the
  CC blend shapes (`Mouth_Smile_L`, ...); the CC face, voice lip-sync and blinks never moved. Needs a re-import.
- Result: `Streetball.*` 28/28 (DribbleLab test extended: frown on reset and fade, face camera cycle and framing).
  Captures in `SCREENSHOTS/20261124_dribble_lab/` (face_mh_*.jpg).

## The original grandma as a MetaHuman (presentation only, local assets)

Owner: "keep the look of the original grandma and make her a metahuman", "do all", headless. No policy, observation,
action, director row or physics change. Assets git-ignored (public repo): `Content/Project/Agents/GrandmaCCMH/`,
`Content/Art/{Raw,Exports}/GrandmaCCMH/`.

- Her face in the base mesh already smiles (all 92 CC shape keys at 0); the grin and teeth are mostly painted in the
  scan texture, the geometry only mildly smiles.
- `Scripts/classify_grandma_skin_blender.py`: face skin by diffuse-texture hue (< 21 deg; her blonde hair is 25-35 deg) ->
  1,064-vertex face patch, mapped onto `SK_Grandma` exactly (Blender (x,-y,z)/100 = UE, median error 0.0 cm).
- `Scripts/render_grandma_portrait_blender.py`: front portrait (the headless editor's scene capture rendered her
  material black). Epic's tracker: 16 contours (eyelids, lips, philtrum, nasolabial).
- `Scripts/build_grandma_cc_metahuman.py`: `conform_to_target_meshes` HEAD_ONLY (pipeline `head_only`, as the editor's
  Mesh Import tool sets it), cloud auto-rig joints + blend shapes (37 s), textures, hair `WI_Hair_L_Straight` made blonde
  on the built material instances (`hairMelanin` 0.8 -> 0.2, `hairRedness` 0.35), build (221 assets). Gotcha:
  `commit_skin_settings` discards downloaded textures, so textures must be requested after the look stage.
- `Scripts/make_grandma_headless_blender.py`: her body and clothes without head and hair (21,470 of 24,866 vertices).
- Game: `AStreetballCharacter` now has MetaHuman slots (one face / outfit / groom set each, tagged `MetaHuman<n>`):
  slot 0 "Grandma (original, MetaHuman)" (new default skin), slot 1 "Grandma (MetaHuman)" (Grace). Smile/frown and the
  face camera work on both. `Streetball.*` 28/28.

## Overnight training queue: dribble both hands, moving dribble, two-hand pickup (audit trail, written before the run)

Owner: "Search for what needs training and train 9 hours as needed / focus on moving on the court, dribbling, picking up
a ball with both hands". State found: balance, locomotion and scramble pass; right-hand dribble passes only as the
dribble_anchor10 preview (not promoted); left hand, crossover, moving dribble 0 %; no two-hand pickup skill exists.

| Area | Change | Affected policies | Interface revision |
|---|---|---|---|
| `levels/l2_dribble.py` | `task_mirror` for the two-hand modes (hand and anchor-y flip); new `l2_both` (gate, hand per episode) and `l2_both_time` (training) | dribble (training only) | none |
| `levels/l3_roam.py` | fix: `L3MovingDribble.task_mirror` inherited L1's mirror (flipped slot 1 = apex height); now hand + waypoint-y; new `l3a_walk_both` | dribble (training only) | none |
| `levels/l3_pickup.py` | new level `l3c_pickup`: ball on the floor 0.4-2.5 m away, both palms on it, lift above 0.75 m, hold 1 s; gate 80 % (class override, no reward_config row) | new family "pickup" (preview only; no director row until it passes) | none (same obs/action; task slot 0 = 1.0) |
| `tools/overnight_dribble_pickup.py` | A `l2_both_time` 150 min from dribble_anchor10 (rebuilt from shared/policies/dribble.onnx, parity 1.6e-6) with symmetry loss 0.2; B `l3a_walk_both` 150 min from A's best; C `l3c_pickup` 150 min from scramble; every checkpoint gated | none exported | none |

Smoke: each level 32 iterations on 256 worlds (runs deleted, < 5,000 steps); `interface_sha` 9879b4bebba21aa3 unchanged.
Python: ruff clean, 34 tests pass. Hourly notes: docs/<day>/overnight_dribble_pickup.md.
