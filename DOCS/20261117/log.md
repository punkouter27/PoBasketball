# 2026-11-17

## Overnight queue `n16b` (20:38 -> 06:14) results

| Stage | Run | Result |
|---|---|---|
| l3b_scramble 150 min from locomotion | `l3b_scramble_n16bq1` | 91.5 %, holds 100, but 40 NaN-gradient batches -> FAIL |
| l2a_dribble_r 75 min from locomotion | `l2a_dribble_r_n16bq1` | 0 %, no falls, mean episode 3.7 s -> FAIL |
| l2a_cycles 90 min | `l2a_cycles_n16bq1` | **did not run**: init `runs/l2a_dribble_r_n16q1` not found |
| l2a_push 120 min | `l2a_push_n16bq1` | **did not run**: init `runs/l2a_cycles_n16q1` not found |
| l3b_scramble 60 min full resume | `l3b_scramble_n16bq2` | **95.0 %, holds 100, 0 NaN, falls 1.5 % -> PASS**; exported `shared/policies/scramble.onnx`, synced to Unreal |
| l2a_push 288 min (rest) | `l2a_push_n16bq2` | started from scratch (init None); training curriculum reached K = 4 cycles, succ_ema about 0.55, but gate `l2a_dribble_r` 0 %, mean episode 1.1 s -> FAIL |

Cause of the two skipped stages: plan `grandma_20261116` hard-coded `n16` in the dribble lineage paths, the queue was
launched with `--tag n16b`. Fix in `sim/streetball/queue.py`: plan init paths use `{tag}`, and a stage whose init
checkpoint is missing is skipped with a log line instead of crashing the trainer.
Open question: `l2a_push` training reports cycles succeeding (ep 3.0 s) while the `l2a_dribble_r` gate ends episodes
after 1.1 s on average -> check the train/gate termination mismatch before the next dribble run.

## 16:30 — play-through, all tiers + controls (grandma, `-game` 1600x900, seed 7)

Runs: tier 1 (2x, controls test), tiers 2-5 via `-StreetballStartTier`, 48 s each, Manny tier 1 for comparison.
Policies loaded: balance, locomotion, scramble (trained); dribble, shot -> dummy fallback. 60 fps throughout, NaN/Inf 0,
no Streetball warnings/errors in any log.

| # | Severity | Finding |
|---|---|---|
| 1 | High | F1-F4 also trigger UE's built-in debug view modes in Development builds (F1 wireframe, F2 unlit, F3 lit, F4 lighting only): every press of Mode/Camera/Telemetry/Policy also changes the rendering. Needs different keys or the debug view-mode bindings removed. |
| 2 | Medium | F1 app mode (Watch/Play/Testbed) only changes the HUD label; `AppMode` is read nowhere else. |
| 3 | Medium | Broadcast camera in tier 5 sometimes frames the athlete from about 1 m (face/torso fill the screen); camera cuts carry heavy motion blur (tiers 3 and 5). |
| 4 | Medium | Tiers 3-5: dummy dribble/shot policies -> falls/resets every 4-8 s (tier 3: 5 falls + 2 scramble timeouts in 48 s). Training issue, known. |
| 5 | Low | Free camera W/S moves along the view direction with no floor clamp -> camera ends up in the floor. |
| 6 | Low | Tier 1 "Upright Balance": balance policy stands hunched (~40 deg forward). Same with Manny, so a policy trait, not the skin. |
| 7 | Low | `Distance` keeps counting across resets and tiers (26 m after 9 s of "stationary" dribble); Balance/Waypoints show 0 for tiers skipped with StartTier. |
| 8 | Low | Ball looks pale tan under lit view (orange in unlit); dark shadow blobs on the floor with no visible caster in high broadcast shots. |

Working: tier 2 traversal (7 waypoints / 74 m in 45 s, no falls); scramble policy engages on every loose ball (LOOSE BALL
countdown + ring consistent; 1 save in tier 4); Space pause, R reset, F2 camera cycle (Broadcast/Follow/Orbit/Free),
F3 telemetry, F4 policy override all respond. Tier 4 window closed at 32 s by an external close (ViewportClosed), not a crash.

## 17:00 — plugins pass: presentation layer (items 1-6, 8-11, 13-15, 18-20 of the plugin list)

Audit (UU_AGENT §3): **no policy, observation, joint order, action layout, transition-table row, MJCF or shared contract
changed.** Everything below is an engine-side listener of sim state (contract §5). `Streetball.Presentation.AssetsAndSimInvariance`
checks qpos is bit-identical with the presentation layer on and off. Chaos is used only by the grandma's cardigan-hem cloth
(contract §2 allows cosmetic cloth); it has its own gravity because world gravity is 0. Hair physics is Niagara-based.

User decisions (17:05): procedural stand-ins now, Fab/Megascans/MetaHuman swapped in later; Substrate on in this pass;
ACE/Audio2Face as an offline bake (no runtime GPU/network).

| Item | What was built | Where |
|---|---|---|
| 1-2 Megascans/props | 18 Blender stand-in meshes (3 brownstones, bench, trash can, fountain, car, 2 trees, street light, hydrant, litter x3, weeds, net, pigeon, leaf) + Substrate slot materials; `Content/Art/env_slots.json` is the swap table for Fab assets | `Scripts/make_env_proxies_blender.py`, `import_env_assets.py` |
| 3 Substrate (court) | `r.Substrate=True`; Substrate slab materials: asphalt (lines, cracks, wet puddles), ball (leather + dust horizontal mix), rim (paint/steel chip mix), backboard marks, steel paint + rust, chain-link mask | `make_court_materials.py`, `AStreetballWorld::GeomMaterialOverrides` |
| 4 Substrate (grandma) | skin SSS + knit fuzz on the CC textures | `build_grandma_extras.py` |
| 5 PCG | `PCG_Neighbourhood` + PCG Volume in Court.umap (anchors -> noise/filter -> jitter -> weighted spawners), generate on load, seed 1959 | `build_environment.py` |
| 6 wear | rubber scuffs under the hoops, faded paint, cracks, puddles (in the asphalt material) | `make_court_materials.py` |
| 8-11 Niagara | 9 lightweight systems (ball dust, foot dust, board chalk, swish, rim sparks, sweat, pigeons, leaves, sun motes), visual nets with swish/hit wobble, pooled at startup | `make_niagara_fx.py`, `CourtFX.*` |
| 13 MetaHuman | `-StreetballCharacterMesh=<path>` override for a UE5-skeleton body; creation itself is manual (MetaHuman Creator) | `StreetballWorld.cpp` |
| 14 Groom | flyaways (5326 strands) + brows (300) from Blender Alembic, hair sim on, rigid on the head bone | `make_grandma_groom_blender.py`, `build_grandma_extras.py` |
| 15 Chaos Cloth | cardigan hem split into its own section (3997 faces), painted max-distance mask, 6 cm | `split_grandma_cloth_blender.py`, `StreetballGymEditor` |
| 18-19 MetaSounds | 10 sources: 6 impact sounds driven by `Impact`, crowd cheer/groan, grunt, looping city ambience | `make_metasounds.py`, `CourtAudio.*` |
| 20 ACE/A2F | 45 lines (10 events), offline Windows TTS + audio-driven CC morph curves, A2F adapter ready; subtitles on the HUD | `tools/voice_bake/`, `import_voice_bank.py`, `GrandmaVoice.*`, `PresentationEvents.*` |

New editor-only module `StreetballGymEditor` (reflection access to Niagara lightweight modules, cloth-from-section).
One-shot rebuild: `Scripts/build_presentation_assets.ps1`. Flags: `-StreetballNoPresentation`, `-StreetballNoCloth`,
`-StreetballNoGroom`, `-StreetballCharacterMesh=`.
