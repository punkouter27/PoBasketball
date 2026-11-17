"""Items 8-11: Niagara effects for the court, headlessly, plus the visual net (item 9) and DA_CourtFXBank.

    run_headless.ps1 -EditorArgs @("-run=pythonscript", "-script=<this file>")     (after import_env_assets.py)

Every system is a copy of an engine Lightweight (stateless) template whose modules are retuned through
unreal.StreetballEditorLibrary (Source/StreetballGymEditor): Python cannot reach stateless modules directly.
FCourtFXPlayer (CourtFX.cpp) pools them at startup and fires them from sim contact/game events; nothing here feeds
back into the sim.
"""
import os as _os
import re
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import unreal  # noqa: E402
import sbmat  # noqa: E402
from sbmat import Graph  # noqa: E402

L = unreal.StreetballEditorLibrary
EAL = unreal.EditorAssetLibrary
PKG = "/Game/VFX"
BURST = "/Niagara/DefaultAssets/Templates/Systems/DirectionalBurstLightweight"
LOOP = "/Niagara/DefaultAssets/Templates/Systems/FountainLightweight"


# ---------------------------------------------------------------- distribution text helpers
def f(v):
    return f"{float(v):.6f}"


def rng(lo, hi=None):
    hi = lo if hi is None else hi
    if lo == hi:
        return f"(Min={f(lo)},Max={f(lo)},Mode=UniformConstant,ChannelConstantsAndRanges=({f(lo)}))"
    return f"(Min={f(lo)},Max={f(hi)},Mode=UniformRange,ChannelConstantsAndRanges=({f(lo)},{f(hi)}))"


def v3(lo, hi=None):
    hi = lo if hi is None else hi
    mode = "NonUniformConstant" if lo == hi else "NonUniformRange"
    ch = ",".join(f(x) for x in (lo if lo == hi else tuple(lo) + tuple(hi)))
    return (f"(Min=(X={f(lo[0])},Y={f(lo[1])},Z={f(lo[2])}),Max=(X={f(hi[0])},Y={f(hi[1])},Z={f(hi[2])}),"
            f"Mode={mode},ChannelConstantsAndRanges=({ch}))")


def v2(lo, hi=None):
    hi = lo if hi is None else hi
    mode = "NonUniformConstant" if lo == hi else "NonUniformRange"
    ch = ",".join(f(x) for x in (lo if lo == hi else tuple(lo) + tuple(hi)))
    return f"(Min=(X={f(lo[0])},Y={f(lo[1])}),Max=(X={f(hi[0])},Y={f(hi[1])}),Mode={mode},ChannelConstantsAndRanges=({ch}))"


def color(c, c2=None):
    c2 = c2 or c
    def one(x):
        return f"(R={f(x[0])},G={f(x[1])},B={f(x[2])},A={f(x[3])})"
    mode = "NonUniformConstant" if c2 == c else "NonUniformRange"
    return f"(Values=({one(c)},{one(c2)}),Mode={mode})"


# ---------------------------------------------------------------- materials
def soft_material(path, additive=False, leaf=False):
    blend = unreal.BlendMode.BLEND_ADDITIVE if additive else (unreal.BlendMode.BLEND_MASKED if leaf else unreal.BlendMode.BLEND_TRANSLUCENT)
    shading = unreal.MaterialShadingModel.MSM_DEFAULT_LIT if leaf else unreal.MaterialShadingModel.MSM_UNLIT
    m = sbmat.new_material(path, blend=blend, shading=shading, two_sided=True)
    m.set_editor_property("used_with_niagara_sprites", True)
    g = Graph(m)
    pc = g.e(unreal.MaterialExpressionParticleColor)
    uv = g.e(unreal.MaterialExpressionTextureCoordinate)
    if leaf:
        shape = g.custom("float2 d = (UV - 0.5) * float2(2.0, 3.4); return 1.0 - dot(d, d);", [("UV", (uv, ""))], desc="LeafShape")
        g.to(pc, "", unreal.MaterialProperty.MP_BASE_COLOR)
        g.to(g.const(0.75), "", unreal.MaterialProperty.MP_ROUGHNESS)
        g.to(shape, "", unreal.MaterialProperty.MP_OPACITY_MASK)
        return g.finish()
    disc = g.custom("float2 d = (UV - 0.5) * 2.0; return saturate(1.0 - dot(d, d)) * saturate(1.0 - dot(d, d));", [("UV", (uv, ""))], desc="SoftDisc")
    op = g.e(unreal.MaterialExpressionMultiply)
    g.link(disc, "", op, "A")
    g.link(pc, "A", op, "B")          # the default output is RGB only: masking A from it does not compile
    rgb = g.e(unreal.MaterialExpressionComponentMask, r=True, g=True, b=True)
    g.link(pc, "", rgb, "")
    if additive:
        em = g.e(unreal.MaterialExpressionMultiply)
        g.link(rgb, "", em, "A")
        g.link(op, "", em, "B")
        g.to(em, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    else:
        g.to(rgb, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        g.to(op, "", unreal.MaterialProperty.MP_OPACITY)
    return g.finish()


NET_HLSL = r"""
float swish = saturate(1.0 - (T - SwishT) / 1.3); swish *= swish;
float hit = saturate(1.0 - (T - HitT) / 0.7); hit *= hit;
float amp = (5.5 * swish + 2.2 * hit + 0.25) * VC;
float ph = T * 23.0 + WP.z * 0.18;
return float3(sin(ph) * amp, cos(ph * 0.87) * amp, -abs(sin(ph * 0.5)) * swish * 3.0 * VC);
"""


def net_material(path):
    m = sbmat.new_material(path, two_sided=True)
    g = Graph(m)
    t = g.e(unreal.MaterialExpressionTime)
    vc = g.e(unreal.MaterialExpressionVertexColor)
    wp = sbmat.world_pos(g)
    wpo = g.custom(NET_HLSL, [("T", (t, "")), ("SwishT", (g.scalar("SwishTime", -100.0), "")), ("HitT", (g.scalar("HitTime", -100.0), "")),
                              ("VC", (vc, "R")), ("WP", (wp, ""))], unreal.CustomMaterialOutputType.CMOT_FLOAT3, "NetWobble")
    g.front(g.slab(albedo=(g.const3(0.88, 0.88, 0.85), ""), roughness=(g.const(0.85), "")))
    g.to(wpo, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    return g.finish()


# ---------------------------------------------------------------- systems
def stateless_parts(system):
    em = [o for o in L.get_inner_objects(system) if o.get_class().get_name() == "NiagaraStatelessEmitter"]
    if not em:
        raise RuntimeError(f"{system.get_name()}: no lightweight emitter")
    em = em[0]
    mods, renderer = {}, None
    for o in L.get_inner_objects(em):
        cname = o.get_class().get_name()
        if cname.startswith("NiagaraStatelessModule_"):
            mods[cname.replace("NiagaraStatelessModule_", "")] = o
        elif cname == "NiagaraSpriteRendererProperties":
            renderer = o
    return em, mods, renderer


def setp(obj, path, value):
    if not L.set_property_text(obj, path, value):
        raise RuntimeError(f"{obj.get_name()}.{path} <- {value[:120]}")


def make_system(name, template, spec):
    path = f"{PKG}/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    sysobj = EAL.duplicate_asset(template, path)
    em, mods, rend = stateless_parts(sysobj)
    # spawning
    spawn = L.get_property_text(em, "SpawnInfos")
    if "burst" in spec:
        spawn = re.sub(r"Amount=\(Min=\d+,Max=\d+\)", f"Amount=(Min={spec['burst'][0]},Max={spec['burst'][1]})", spawn)
    if "rate" in spec:
        spawn = re.sub(r"Rate=\(Min=[-0-9.e]+,Max=[-0-9.e]+", f"Rate=(Min={f(spec['rate'])},Max={f(spec['rate'])}", spawn)
        spawn = re.sub(r"ChannelConstantsAndRanges=\([-0-9.e,]+\)", f"ChannelConstantsAndRanges=({f(spec['rate'])})", spawn, count=1)
    setp(em, "SpawnInfos", spawn)
    b = spec.get("bounds", 300.0)
    bz = spec.get("bounds_z", b)
    setp(em, "FixedBounds", f"(Min=(X={-b},Y={-b},Z={-bz}),Max=(X={b},Y={b},Z={bz}),IsValid=True)")
    # modules: enable the ones we use, configure, disable the rest that would fight
    for mod, props in spec["modules"].items():
        if mod not in mods:
            raise RuntimeError(f"{name}: template has no {mod}")
        setp(mods[mod], "bModuleEnabled", "True")
        for k, v in props.items():
            setp(mods[mod], k, v)
    for mod in spec.get("disable", []):
        if mod in mods:
            setp(mods[mod], "bModuleEnabled", "False")
    if rend is not None:
        setp(rend, "Material", f"/Script/Engine.Material'{spec['material']}'")
        setp(rend, "Alignment", spec.get("alignment", "Unaligned"))
        setp(rend, "FacingMode", "FaceCamera")
        setp(rend, "bCastShadows", "False")
        setp(rend, "SortMode", "ViewDistance" if not spec.get("additive") else "None")
    L.compile_niagara_system(sysobj)
    EAL.save_loaded_asset(sysobj)
    unreal.log(f"NIAGARA built {path}")
    return sysobj


def dust(col, n, size, speed, life, up=True, grav=-60.0):
    return {
        "burst": n, "material": f"{PKG}/Materials/M_FX_Soft",
        "modules": {
            "InitializeParticle": {"LifetimeDistribution": rng(*life), "ColorDistribution": color(col),
                                   "SpriteSizeDistribution": v2((size[0], size[0]), (size[1], size[1])), "MassDistribution": rng(1.0)},
            "ShapeLocation": {"ShapePrimitive": "Sphere", "SphereRadius": rng(6.0)},
            "AddVelocity": {"VelocityType": "InCone", "ConeVelocityDistribution": rng(*speed), "ConeAngle": "75.0" if up else "180.0"},
            "GravityForce": {"GravityDistribution": v3((0, 0, grav))},
            "Drag": {"DragDistribution": rng(2.5, 3.5)},
            "ScaleSpriteSize": {},
            "ScaleColor": {},
            "SolveVelocitiesAndForces": {},
        },
        "disable": ["CurlNoiseForce", "AccelerationForce", "SpriteRotationRate", "ScaleSpriteSizeBySpeed", "CameraOffset"],
    }


def specs():
    S = {}
    S["NS_BallDust"] = dust((0.36, 0.33, 0.29, 0.35), (10, 16), (14, 34), (60, 170), (0.7, 1.4))
    S["NS_FootDust"] = dust((0.36, 0.33, 0.29, 0.28), (6, 10), (10, 24), (40, 120), (0.5, 1.0))
    S["NS_BoardDust"] = dust((0.85, 0.84, 0.80, 0.30), (8, 12), (6, 16), (40, 110), (0.5, 1.0), up=False, grav=-30.0)
    S["NS_Swish"] = {
        "burst": (14, 20), "material": f"{PKG}/Materials/M_FX_Soft",
        "modules": {
            "InitializeParticle": {"LifetimeDistribution": rng(0.35, 0.7), "ColorDistribution": color((0.95, 0.95, 0.92, 0.65)),
                                   "SpriteSizeDistribution": v2((2.5, 2.5), (5.0, 5.0))},
            "ShapeLocation": {"ShapePrimitive": "Sphere", "SphereRadius": rng(18.0)},
            "AddVelocity": {"VelocityType": "Linear", "LinearVelocityDistribution": v3((-50, -50, -260), (50, 50, -110))},
            "GravityForce": {"GravityDistribution": v3((0, 0, -400))},
            "ScaleColor": {}, "SolveVelocitiesAndForces": {},
        },
        "disable": ["CurlNoiseForce", "Drag", "AccelerationForce", "CameraOffset"],
    }
    S["NS_RimSparks"] = {
        "burst": (14, 24), "material": f"{PKG}/Materials/M_FX_Additive", "additive": True, "alignment": "VelocityAligned",
        "modules": {
            "InitializeParticle": {"LifetimeDistribution": rng(0.2, 0.55), "ColorDistribution": color((6.0, 2.6, 0.6, 1.0)),
                                   "SpriteSizeDistribution": v2((1.2, 4.0), (2.4, 10.0))},
            "ShapeLocation": {"ShapePrimitive": "Sphere", "SphereRadius": rng(3.0)},
            "AddVelocity": {"VelocityType": "InCone", "ConeVelocityDistribution": rng(220, 560), "ConeAngle": "80.0"},
            "GravityForce": {"GravityDistribution": v3((0, 0, -980))},
            "ScaleColor": {}, "SolveVelocitiesAndForces": {},
        },
        "disable": ["CurlNoiseForce", "Drag", "AccelerationForce", "CameraOffset"],
    }
    S["NS_Sweat"] = {
        "burst": (8, 12), "material": f"{PKG}/Materials/M_FX_Soft",
        "modules": {
            "InitializeParticle": {"LifetimeDistribution": rng(0.35, 0.7), "ColorDistribution": color((0.82, 0.9, 1.0, 0.75)),
                                   "SpriteSizeDistribution": v2((1.0, 1.0), (2.2, 2.2))},
            "ShapeLocation": {"ShapePrimitive": "Sphere", "SphereRadius": rng(10.0)},
            "AddVelocity": {"VelocityType": "InCone", "ConeVelocityDistribution": rng(120, 300), "ConeAngle": "65.0"},
            "GravityForce": {"GravityDistribution": v3((0, 0, -980))},
            "ScaleColor": {}, "SolveVelocitiesAndForces": {},
        },
        "disable": ["CurlNoiseForce", "Drag", "AccelerationForce", "CameraOffset"],
    }
    S["NS_Pigeons"] = {
        "burst": (7, 10), "material": f"{PKG}/Materials/M_FX_Soft", "bounds": 3000.0,
        "modules": {
            "InitializeParticle": {"LifetimeDistribution": rng(3.0, 4.0), "ColorDistribution": color((0.10, 0.10, 0.12, 0.95)),
                                   "SpriteSizeDistribution": v2((18.0, 9.0), (26.0, 13.0))},
            "ShapeLocation": {"ShapePrimitive": "Sphere", "SphereRadius": rng(120.0)},
            "AddVelocity": {"VelocityType": "InCone", "ConeVelocityDistribution": rng(300, 650), "ConeAngle": "55.0"},
            "AccelerationForce": {"AccelerationDistribution": v3((60, 40, 120))},
            "CurlNoiseForce": {"NoiseStrength": rng(150.0), "NoiseFrequency": rng(0.02)},
            "SolveVelocitiesAndForces": {},
        },
        "disable": ["GravityForce", "Drag", "ScaleColor", "CameraOffset"],
    }
    # ambience loops (fountain template: rate based, infinite)
    S["NS_Leaves"] = {
        "rate": 2.5, "material": f"{PKG}/Materials/M_FX_Leaf", "bounds": 4500.0, "bounds_z": 1200.0,
        "modules": {
            "InitializeParticle": {"LifetimeDistribution": rng(9.0, 14.0), "ColorDistribution": color((0.30, 0.22, 0.06, 1.0)),
                                   "SpriteSizeDistribution": v2((5.0, 3.0), (9.0, 5.0))},
            "ShapeLocation": {"ShapePrimitive": "Box", "BoxSize": v3((6000, 4000, 300))},
            "AddVelocity": {"VelocityType": "Linear", "LinearVelocityDistribution": v3((20, -30, -60), (90, 30, -30))},
            "CurlNoiseForce": {"NoiseStrength": rng(70.0), "NoiseFrequency": rng(0.004)},
            "SpriteRotationRate": {"RotationRateDistribution": rng(-180.0, 180.0)},
            "SolveVelocitiesAndForces": {},
        },
        "disable": ["GravityForce", "Drag", "ScaleColor", "ScaleSpriteSize", "AccelerationForce", "CameraOffset"],
    }
    S["NS_Motes"] = {
        "rate": 30.0, "material": f"{PKG}/Materials/M_FX_Additive", "additive": True, "bounds": 2500.0, "bounds_z": 600.0,
        "modules": {
            "InitializeParticle": {"LifetimeDistribution": rng(6.0, 10.0), "ColorDistribution": color((0.9, 0.8, 0.6, 0.18)),
                                   "SpriteSizeDistribution": v2((0.4, 0.4), (1.1, 1.1))},
            "ShapeLocation": {"ShapePrimitive": "Box", "BoxSize": v3((3200, 2000, 300))},
            "AddVelocity": {"VelocityType": "Linear", "LinearVelocityDistribution": v3((-6, -6, -3), (6, 6, 6))},
            "CurlNoiseForce": {"NoiseStrength": rng(12.0), "NoiseFrequency": rng(0.01)},
            "SolveVelocitiesAndForces": {},
        },
        "disable": ["GravityForce", "Drag", "AccelerationForce", "CameraOffset"],
    }
    return S


def main():
    EAL.make_directory(f"{PKG}/Materials")
    soft_material(f"{PKG}/Materials/M_FX_Soft")
    soft_material(f"{PKG}/Materials/M_FX_Additive", additive=True)
    soft_material(f"{PKG}/Materials/M_FX_Leaf", leaf=True)
    net_mat = net_material(f"{PKG}/Materials/M_Net")
    # log the template layouts once (property text formats differ between engine versions)
    for t in (BURST, LOOP):
        em, _, _ = stateless_parts(unreal.load_asset(t))
        unreal.log(f"NIAGARA template {t}: SpawnInfos={L.get_property_text(em, 'SpawnInfos')} "
                   f"Loop={L.get_property_text(em, 'EmitterState.LoopBehavior')}")
    built = {}
    for name, spec in specs().items():
        template = LOOP if "rate" in spec else BURST
        try:
            built[name] = make_system(name, template, spec)
        except Exception as e:
            unreal.log_error(f"NIAGARA {name} FAILED: {e}")
    bank_path = f"{PKG}/DA_CourtFXBank"
    if EAL.does_asset_exist(bank_path):
        EAL.delete_asset(bank_path)
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.CourtFXBank)
    bank = unreal.AssetToolsHelpers.get_asset_tools().create_asset("DA_CourtFXBank", PKG, unreal.CourtFXBank, factory)
    for prop, name in (("ball_dust", "NS_BallDust"), ("rim_sparks", "NS_RimSparks"), ("board_dust", "NS_BoardDust"), ("swish", "NS_Swish"),
                       ("foot_dust", "NS_FootDust"), ("sweat", "NS_Sweat"), ("leaves", "NS_Leaves"), ("motes", "NS_Motes"), ("pigeons", "NS_Pigeons")):
        if name in built:
            bank.set_editor_property(prop, built[name])
    net = unreal.load_asset("/Game/Art/Env/Proxy/SM_BasketballNet")
    if net:
        net.set_material(0, net_mat)
        EAL.save_loaded_asset(net)
        bank.set_editor_property("net_mesh", net)
    bank.set_editor_property("net_material", net_mat)
    EAL.save_loaded_asset(bank)
    unreal.log(f"NIAGARA_FX OK {len(built)}/9 systems, net {'yes' if net else 'missing'}")


main()
