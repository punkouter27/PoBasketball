# Phase B — Engine Integration, tasks B1–B7: PASS (6/6 automation tests)

Date: 2026-11-06. Engine: Unreal 5.8.4. Library: libmujoco 4.0.0 (matches the Python wheel).

## How to build and test (no GUI)

```
"C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" StreetballGymEditor Win64 Development ^
    -Project="<repo>\unreal\StreetballGym\StreetballGym.uproject" -WaitMutex

"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
    "<repo>\unreal\StreetballGym\StreetballGym.uproject" ^
    -ExecCmds="Automation RunTests Streetball; Quit" -unattended -nosplash -nop4 -stdout -FullStdOutLogOutput
```

Do **not** pass `-nullrhi`: in 5.8 the editor dies with `Null assigned to TNotNull` on its first frame under the null RHI, before any test runs. With the real RHI the whole run takes about 60 s. Exit code 0 = all pass.

## Results

| Task | Test | Result | Numbers |
|---|---|---|---|
| B1 Project | build | PASS | `StreetballGymEditor` builds clean; `Content/Maps/Court.umap` created headlessly by `Scripts/make_court_level.py` (sun, sky light, atmosphere, one `AStreetballWorld`) |
| B2 Plugin | `Streetball.B2.SimLoad` | PASS | scene.xml loads (nq 41, nv 39, nu 27, 21 bodies, 53 geoms); `mj_step` 0.036 ms/step (budget 1 ms); DLL version check header 4000000 == library 4000000 |
| B3 Pre-load | covered by B5 | PASS | `AStreetballWorld::Setup` creates 1 character + 38 geom actors in BeginPlay; no `SpawnActor` elsewhere except the game mode spawning the world actor itself when the level has none |
| B4 Fixed step | `Streetball.B4.ClockDeterminism` | PASS | qpos FNV hash at physics step 1500 identical for jittered 10 / 30 / 60 / 144 FPS frame times: `5d7e083b888b663b` |
| B5 Bone mapper | `Streetball.B5.BoneMapper` | PASS | 16 driven bones; reference-pose error 0.00000°; hip_flex_l 90° → thigh (0.999, −0.055, 0.001) actor-space forward; knee 90° → calf (−0.999, −0.042, 0); shoulder_pitch 90° → arm (0.817, −0.576, 0.023); anim-proxy thigh_l vs mapper 0.0000°; pelvis bone at sim pelvis (2.281, 0, 95.897) cm, 0.000 cm off |
| B6 Replay | `Streetball.B6.Replay` | PASS | `shared/golden/replay_random.json`, 250 × 10 steps: max root error 0.0000 cm, max joint error 0.00000° (same libmujoco build on both sides, so bit-identical) |
| B7 Obs + policy | `Streetball.B7.ObsGolden`, `Streetball.B7.PolicyRunner` | PASS | 1000 golden states: max abs diff 4.76e−7 (gate 1e−5), worst slot 98 (palm distance); NNE ORT-CPU vs Python onnxruntime max abs diff 0.0; inference 0.086 ms mean over 200 runs (budget 2 ms) |

## What was built

```
unreal/StreetballGym/
  StreetballGym.uproject                 plugins: PythonScriptPlugin, NNERuntimeORT, MuJoCoRuntime (NNE core is an engine module in 5.8, not a plugin)
  Config/DefaultEngine.ini               Chaos effectively disabled (gravity 0, CCD off, default collision Ignore), startup map Court, game mode StreetballGameMode
  Content/Sim/                           scene.xml, humanoid.xml, court.xml, obs_spec.json, humanoid_spec.json (copies of sim/assets and shared/)
  Content/Maps/Court.umap
  Scripts/make_court_level.py            headless level creation
  Plugins/MuJoCoRuntime/
    ThirdParty/mujoco/{include,lib,bin}  official 4.0.0 Windows release (mujoco.lib + mujoco.dll)
    Source/MuJoCoLib                     external module rules (delay-load DLL, RuntimeDependencies)
    Source/MuJoCoRuntime                 UMuJoCoSim: LoadXml/Step/Forward/ResetToKeyframe, id lookups, UE-space body/site/geom reads,
                                         qpos/qvel/ctrl access, contact enumeration with normal force, qpos hash, static frame helpers
  Source/StreetballGym/
    StreetballGameMode                   spectator pawn, no input; ensures one AStreetballWorld
    StreetballWorld                      owns sim + clock + mapper + policy; pre-allocates character and geom proxies; Tick -> clock -> visuals
    SimClock                             0.002 s accumulator, control callback every 10 steps, per-step snapshot pair + slerp/lerp interpolation
    StreetballAnimInstance               AnimInstance proxy that writes component-space bone targets directly (no AnimBP)
    MuJoCoBoneMapper                     B.1/B.2/B.3: toUE, offsets at qpos=0, world-space drive, spine_01..03 slerp split, pelvis position
    ObsBuilder                           119-float observation, slot-for-slot twin of sim/streetball/obs.py; action -> ctrl rule
    PolicyRunner                         NNE ORT-CPU ONNX loader from disk (UNNEModelData::Init("onnx")), RunSync, timing
    Tests/StreetballTests.cpp            the six automation tests above
sim/tools/export_obs_golden_bin.py       obs_golden.npz -> shared/golden/obs_golden.bin for the C++ test
sim/tools/make_dummy_policy.py           random MLP -> shared/dummy_policy.onnx + sidecar json (obs_spec sha256, check I/O pair)
```

## Decisions and deviations

1. **Bone drive is world-space-by-body, converted to component space per frame.** The character actor only translates (follows pelvis XY) and never rotates; the mesh component carries the standard −90° yaw so Manny faces actor +X = sim +X. Offsets are captured in that frame, so the mapper never needs an explicit mesh yaw (the blueprint said the same).
2. **Pelvis position is driven directly in component space**; all other bone positions come from the skeleton's reference local translations (blueprint B.2). Pelvis bone lands within 0.000 cm of the sim pelvis.
3. **Undriven bones keep their reference local transform** (spine_04/05, clavicles, neck, head, twist, finger, toe, IK bones), which realises the "rigid with parent" rule without listing them. The blueprint's "lowerarm_twist takes 50 % of wrist rotation" refinement is not implemented (twist bones are rigid with the forearm).
4. **Court visuals are engine primitives** (cube/sphere/cylinder/plane scaled to geom size) coloured from geom rgba; capsules are drawn as cylinders of length 2·half+2·r. Good enough for Phase B; Phase C/5 can swap in real meshes without touching the sim path.
5. **Static geoms are set to Static mobility after placement**, dynamic ones stay Movable; humanoid geoms are hidden unless `bShowHumanoidGeoms` (the skeletal mesh is the visual).
6. **Obs builder also lives on `AStreetballWorld`** and runs the policy with a zero task block and `in_control=0`, `countdown=1` placeholders; the level/state machine (B8+) will fill those.
7. **The `-nullrhi` headless path does not work on 5.8** (engine fatal on first frame). Tests run with the real RHI, which is fine on this machine.
8. **Interpolation keeps Prev exactly one physics step behind Curr** (snapshot rotated after every step), so a 30 FPS frame that takes 16–17 steps still blends across a 2 ms span. `MaxFrameDelta` = 0.1 s clamps hitch frames (slow-motion instead of spiral of death).

## Not verified / known gaps

* No interactive run was done (no GUI allowed). `Court.umap` + `AStreetballWorld` were exercised only through the automation world; the Tick → clock → visuals loop ran in Setup/UpdateVisuals but no frames were rendered. Zero-allocation-in-Tick (plan B3 "profiler shows zero allocations") was **not** profiled.
* `USimClock` frame-rate independence is verified by hash; render interpolation correctness is only verified by construction.
* The packaged-build DLL staging (`RuntimeDependencies` → `$(BinaryOutputDir)/mujoco.dll`) is written but a packaged build was not produced.
* Mannequin content was copied from the 5.8 template resources (`Content/Characters/Mannequins`, meshes/materials/textures/rigs only, no animations).
