"""Broadcast replay renders with Movie Render Queue (2026-11-24): builds the two assets a command-line MRQ render needs.

    LS_Broadcast  (/Game/Project/Core/Cinematics): an empty Level Sequence, DURATION_S long at FPS. With no camera-cut
                  track MRQ renders through the player's camera, i.e. the live broadcast camera (ABroadcastCamera), so
                  the clip is the real game: MuJoCo + policies stepping on MRQ's fixed frame time (USimClock is a
                  fixed-step accumulator, so the same frames come out every time).
    MRQ_Broadcast (same folder): 1920x1080 PNG frames to Saved/MovieRenders/<date>, 8 temporal samples (motion blur +
                  anti-aliasing), 2 s of engine warm-up so PCG and shaders have settled.

    pwsh Scripts/run_headless.ps1 -TimeoutSec 600 "-ExecutePythonScript=<abs path>/Scripts/make_broadcast_render.py"
Then render with Scripts/render_broadcast.ps1.
"""

import unreal

PKG = "/Game/Project/Core/Cinematics"
FPS = 30
DURATION_S = 12
WARMUP_FRAMES = 60
TEMPORAL_SAMPLES = 8

tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary


def fresh(name, cls, factory):
    """Load the asset if it exists (every setting below is re-applied), else create it. Deleting and re-creating in one
    session fails: the deleted package is still in memory."""
    path = f"{PKG}/{name}"
    if eal.does_asset_exist(path):
        return eal.load_asset(path)
    asset = tools.create_asset(name, PKG, cls, factory)
    if asset is None:
        raise RuntimeError(f"could not create {path}")
    return asset


seq = fresh("LS_Broadcast", unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
seq.set_display_rate(unreal.FrameRate(FPS, 1))
seq.set_playback_start(0)
seq.set_playback_end(FPS * DURATION_S)
eal.save_loaded_asset(seq)

cfg = fresh("MRQ_Broadcast", unreal.MoviePipelinePrimaryConfig, unreal.MoviePipelinePrimaryConfigFactory())
out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
out.output_resolution = unreal.IntPoint(1920, 1080)
out.use_custom_frame_rate = True
out.output_frame_rate = unreal.FrameRate(FPS, 1)
out.output_directory = unreal.DirectoryPath("{project_dir}/Saved/MovieRenders/{date}_{time}")
out.file_name_format = "broadcast.{frame_number}"
out.zero_pad_frame_numbers = 4
cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
aa.spatial_sample_count = 1
aa.temporal_sample_count = TEMPORAL_SAMPLES
aa.override_anti_aliasing = True
aa.anti_aliasing_method = unreal.AntiAliasingMethod.AAM_TEMPORAL_AA
aa.engine_warm_up_count = WARMUP_FRAMES
aa.render_warm_up_frames = True
game = cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
# MRQ's default game mode override would replace StreetballGameMode, which sets the broadcast camera as view target
game.game_mode_override = unreal.load_class(None, "/Script/StreetballGym.StreetballGameMode")
game.cinematic_quality_settings = True
game.texture_streaming = unreal.MoviePipelineTextureStreamingMethod.DISABLED
eal.save_loaded_asset(cfg)
unreal.log(f"make_broadcast_render: {PKG}/LS_Broadcast ({DURATION_S} s @ {FPS} fps), {PKG}/MRQ_Broadcast")
