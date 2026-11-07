"""Task B1: create /Game/Maps/Court headlessly (no GUI).

    UnrealEditor-Cmd.exe StreetballGym.uproject -run=pythonscript
        -script="<this file>" -unattended -nop4 -nosplash

Creates an empty level with sun, sky light, atmosphere and one AStreetballWorld actor
(which pre-allocates every sim-driven actor in its BeginPlay), then saves it.
"""
import unreal

LEVEL = "/Game/Maps/Court"

ell = unreal.EditorLevelLibrary
if not ell.new_level(LEVEL):
    raise SystemExit(f"could not create {LEVEL}")

# All lights are MOVABLE: the project disables static lighting (r.AllowStaticLighting=False), so a
# Static/Stationary light saved from a headless editor would contribute nothing at runtime (the
# first -game launch rendered black until a light was summoned at runtime).
# unreal.Rotator(roll, pitch, yaw): pitch -55 deg points the sun down, yaw 35 deg sets the azimuth.
# (The first version passed (-55, 35, 0) = pitch +35 deg, i.e. a sun shining upward -> black scene.)
sun = ell.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 1000), unreal.Rotator(0.0, -55.0, 35.0))
sun.set_actor_label("Sun")
sun_c = sun.get_component_by_class(unreal.DirectionalLightComponent)
sun_c.set_mobility(unreal.ComponentMobility.MOVABLE)
sun_c.set_intensity(10.0)
sun_c.set_editor_property("atmosphere_sun_light", True)
sun_c.set_editor_property("cast_shadows", True)
sun_c.set_editor_property("dynamic_shadow_distance_movable_light", 6000.0)

sky = ell.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 800))
sky.set_actor_label("SkyLight")
sky_c = sky.get_component_by_class(unreal.SkyLightComponent)
sky_c.set_mobility(unreal.ComponentMobility.MOVABLE)
sky_c.set_editor_property("real_time_capture", True)

atm = ell.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
atm.set_actor_label("SkyAtmosphere")

world_cls = unreal.load_class(None, "/Script/StreetballGym.StreetballWorld")
w = ell.spawn_actor_from_class(world_cls, unreal.Vector(0, 0, 0))
w.set_actor_label("StreetballWorld")

ok = ell.save_current_level()
unreal.log(f"saved {LEVEL}: {ok}")
