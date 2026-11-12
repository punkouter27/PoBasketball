"""Create a separate Chaos comparison map without modifying Court or its game mode."""
import unreal

level = "/Game/Maps/LearningAgentsComparison"
editor = unreal.EditorLevelLibrary
if unreal.EditorAssetLibrary.does_asset_exist(level):
    if not editor.load_level(level):
        raise RuntimeError(f"Could not load {level}")
    if any(actor.get_actor_label() == "LearningAgentsChaosComparison"
           for actor in editor.get_all_level_actors()):
        raise RuntimeError(f"{level} already contains the comparison; refusing to overwrite it")
elif not editor.new_level(level):
    raise RuntimeError(f"Could not create {level}")

comparison_class = unreal.load_class(None, "/Script/StreetballGym.LAComparisonWorld")
game_mode = unreal.load_class(None, "/Script/StreetballGym.LAComparisonGameMode")
if comparison_class is None or game_mode is None:
    raise RuntimeError("Build StreetballGymEditor with Learning Agents before generating the map")

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
settings = world.get_world_settings()
settings.set_editor_property("default_game_mode", game_mode)
settings.set_editor_property("global_gravity_set", True)
settings.set_editor_property("global_gravity_z", -981.0)

sun = editor.spawn_actor_from_class(
    unreal.DirectionalLight, unreal.Vector(0, 0, 1000), unreal.Rotator(0, -55, 35)
)
light = sun.get_component_by_class(unreal.DirectionalLightComponent)
light.set_mobility(unreal.ComponentMobility.MOVABLE)
light.set_intensity(10)
light.set_editor_property("atmosphere_sun_light", True)
sky = editor.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 800))
sky_light = sky.get_component_by_class(unreal.SkyLightComponent)
sky_light.set_mobility(unreal.ComponentMobility.MOVABLE)
sky_light.set_editor_property("real_time_capture", True)
editor.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector())

floor = editor.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(175000, 75000, -25))
floor.set_actor_label("ChaosComparisonFloor")
mesh = floor.get_component_by_class(unreal.StaticMeshComponent)
mesh.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
mesh.set_world_scale3d(unreal.Vector(4000, 2000, 0.5))
mesh.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
mesh.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
mesh.set_collision_response_to_all_channels(unreal.CollisionResponseType.ECR_BLOCK)
mesh.set_simulate_physics(False)
editor.spawn_actor_from_class(comparison_class, unreal.Vector()).set_actor_label(
    "LearningAgentsChaosComparison"
)

if not editor.save_current_level():
    raise RuntimeError(f"Could not save {level}")
unreal.log(f"Saved {level}; original Court/default map unchanged")
