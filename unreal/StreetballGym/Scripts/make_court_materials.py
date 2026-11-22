"""Items 3 + 6: Substrate court materials, headlessly. Assigned by AStreetballWorld::GeomMaterialOverrides (geom name
prefix -> MI_*). Visual only: the MJCF friction/contact values are untouched.

    run_headless.ps1 -EditorArgs @("-run=pythonscript", "-script=<this file>")

  M_CourtAsphalt   world-space asphalt: two noise scales, cracks, wet puddle patches (glossy Substrate slab), painted
                   FIBA-style lines and a faded key, rubber scuffs under both hoops and worn paint (item 6 "wear")
  M_Basketball     pebbled orange leather with black seams + dust patches (Substrate horizontal mix of two slabs)
  M_RimPaint       orange paint chipped down to bare steel (Substrate horizontal mix: paint slab / metal slab)
  M_Backboard      white board with the red border and shooter's square
  M_SteelPaint     dark green painted steel with rust flecks (poles, arms, brackets)
  M_ChainLink      masked galvanised diamond mesh for the fence boxes
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import unreal  # noqa: E402
import sbmat  # noqa: E402
from sbmat import Graph

PKG = "/Game/Project/Environments/Materials"
CF4 = unreal.CustomMaterialOutputType.CMOT_FLOAT4
CF1 = unreal.CustomMaterialOutputType.CMOT_FLOAT1


def noise(g, pos, scale, levels=4, lo=0.0, hi=1.0, turb=False):
    n = g.e(unreal.MaterialExpressionNoise, scale=float(scale), levels=levels, output_min=float(lo), output_max=float(hi),
            turbulence=turb, quality=2)
    g.link(pos, "", n, "World Position")
    return n


def mask(g, src, r=False, gg=False, b=False, a=False):
    m = g.e(unreal.MaterialExpressionComponentMask, r=r, g=gg, b=b, a=a)
    g.link(src, "", m, "")
    return m


def mix_or_lerp(g, background, foreground, mix_expr):
    """Substrate horizontal mixing of two slabs (falls back to raising if the operator is unavailable)."""
    h = g.e(unreal.MaterialExpressionSubstrateHorizontalMixing)
    g.link(background, "", h, "Background")
    g.link(foreground, "", h, "Foreground")
    g.link(mix_expr, "", h, "Mix")
    return h


ASPHALT_HLSL = r"""
float2 p = abs(WP.xy) / 100.0;           // metres, court is symmetric in x and y
float w = 0.025;                         // half line width (5 cm lines)
float L = 0;
L = max(L, step(abs(p.x - 14.0), w) * step(p.y, 7.5 + w));                 // baselines
L = max(L, step(abs(p.y - 7.5), w) * step(p.x, 14.0 + w));                 // sidelines
L = max(L, step(p.x, w) * step(p.y, 7.5));                                 // centre line
L = max(L, step(abs(length(p) - 1.8), w));                                 // centre circle
L = max(L, step(abs(p.y - 2.45), w) * step(8.2, p.x) * step(p.x, 14.0));   // key sides
L = max(L, step(abs(p.x - 8.2), w) * step(p.y, 2.45 + w));                 // free-throw line
float2 ft = float2(p.x - 8.2, p.y);
L = max(L, step(abs(length(ft) - 1.8), w) * step(ft.x, 0.0));              // free-throw circle (top half)
float2 rr = float2(p.x - 12.425, p.y);
L = max(L, step(abs(length(rr) - 6.75), w) * step(p.x, 11.009));           // three-point arc
L = max(L, step(abs(p.y - 6.6), w) * step(11.009, p.x) * step(p.x, 14.0)); // three-point corners
float key = step(8.2, p.x) * step(p.x, 14.0) * step(p.y, 2.45) + step(length(p), 1.8);
// wear: rubber scuffs where she lands under the hoops, paint fades with grain noise and scuffs
float scuff = saturate(1.0 - length(float2(p.x - 11.6, p.y)) / 3.2) * saturate(NF * 1.4);
float fade = saturate(NF * 1.7 + 0.15) * (1.0 - 0.6 * scuff);
L *= fade;
key *= 0.55 * fade;
float crack = (1.0 - smoothstep(0.0, 0.006, abs(NC - 0.5))) * smoothstep(0.45, 0.6, NP);
float puddle = 0.0;                      // no puddles on the playing surface (user, 2026-11-17)
float3 base = (0.13 + 0.04 * NF + 0.03 * (NP - 0.5)).xxx * float3(1.0, 0.985, 0.97);
base = lerp(base, float3(0.22, 0.075, 0.06), key);
base = lerp(base, float3(0.66, 0.66, 0.62), L);
base *= 1.0 - 0.35 * scuff;
base *= 1.0 - 0.55 * crack;
base *= 1.0 - 0.45 * puddle;
float rough = lerp(0.86, 0.62, L);
rough = lerp(rough, 0.72, scuff * 0.6);
rough = lerp(rough, 0.07, puddle);
return float4(base, rough);
"""

BALL_HLSL = r"""
float3 n = normalize(LP);
float w = 0.014;
float s = step(abs(n.z), w);                                           // equator
s = max(s, step(abs(n.x), w));                                         // meridian
s = max(s, step(abs(abs(n.y) - (0.58 + 0.30 * n.x * n.x)), w));        // the two curved panel seams
float pebble = NF;
float3 leather = float3(0.62, 0.20, 0.055) * (0.85 + 0.25 * pebble);
float3 c = lerp(leather, float3(0.025, 0.02, 0.02), s);
return float4(c, lerp(0.58 + 0.12 * pebble, 0.42, s));
"""

BOARD_HLSL = r"""
float2 uv = LP.yz / 50.0;                 // engine cube: -50..50 -> -1..1 across the board face
float du = 0.05 / 0.9, dv = 0.05 / 0.525;
float L = step(1.0 - du, abs(uv.x)) + step(1.0 - dv, abs(uv.y));
float ix = 0.295 / 0.9, iy = 0.225 / 0.525;
L += step(abs(abs(uv.x) - ix), du * 0.5) * step(abs(uv.y), iy + dv * 0.5);
L += step(abs(abs(uv.y) - iy), dv * 0.5) * step(abs(uv.x), ix + du * 0.5);
return saturate(L);
"""

FENCE_HLSL = r"""
float s = (WP.x + WP.y) / 6.0;            // one of x/y is constant along each fence side
float z = WP.z / 6.0;
float a = frac(s + z), b = frac(s - z);
float wire = max(step(min(a, 1.0 - a), 0.07), step(min(b, 1.0 - b), 0.07));
float rail = step(abs(WP.z - 296.0), 3.0) + step(WP.z, 4.0);
return saturate(wire + rail);
"""


def asphalt():
    m = sbmat.new_material(f"{PKG}/M_CourtAsphalt")
    g = Graph(m)
    wp = sbmat.world_pos(g)
    nf = noise(g, wp, 0.05)
    nc = noise(g, wp, 0.004, levels=6)
    npd = noise(g, wp, 0.0012, levels=3)
    nw = noise(g, wp, 0.003, levels=3)
    c = g.custom(ASPHALT_HLSL, [("WP", (wp, "")), ("NF", (nf, "")), ("NC", (nc, "")), ("NP", (npd, "")), ("NW", (nw, ""))], CF4, "CourtLinesWear")
    s = g.slab(albedo=(mask(g, c, r=True, gg=True, b=True), ""), roughness=(mask(g, c, a=True), ""))
    g.front(s)
    return g.finish()


def basketball():
    m = sbmat.new_material(f"{PKG}/M_Basketball")
    g = Graph(m)
    lp = sbmat.local_pos(g)
    nf = noise(g, lp, 1.6, levels=2)
    c = g.custom(BALL_HLSL, [("LP", (lp, "")), ("NF", (nf, ""))], CF4, "BallSeams")
    leather = g.slab(albedo=(mask(g, c, r=True, gg=True, b=True), ""), roughness=(mask(g, c, a=True), ""))
    dust = g.slab(albedo=(g.const3(0.46, 0.42, 0.36), ""), roughness=(g.const(0.92), ""))
    wp = sbmat.world_pos(g)
    dmask = g.e(unreal.MaterialExpressionMultiply)
    g.link(noise(g, lp, 0.9, levels=3), "", dmask, "A")
    g.link(g.scalar("DustAmount", 0.3), "", dmask, "B")
    g.front(mix_or_lerp(g, leather, dust, dmask))
    return g.finish()


def rim():
    m = sbmat.new_material(f"{PKG}/M_RimPaint")
    g = Graph(m)
    wp = sbmat.world_pos(g)
    paint = g.slab(albedo=(g.vector("PaintColor", 0.78, 0.17, 0.03), ""), roughness=(g.const(0.42), ""))
    steel = g.slab(albedo=(g.const3(0.0, 0.0, 0.0), ""), f0=(g.const3(0.56, 0.57, 0.58), ""), roughness=(g.const(0.33), ""))
    chips = g.custom("return smoothstep(0.60, 0.64, N);", [("N", (noise(g, wp, 0.35, levels=4), ""))], CF1, "Chips")
    g.front(mix_or_lerp(g, paint, steel, chips))
    return g.finish()


def backboard():
    m = sbmat.new_material(f"{PKG}/M_Backboard")
    g = Graph(m)
    lp = sbmat.local_pos(g)
    lines = g.custom(BOARD_HLSL, [("LP", (lp, ""))], CF1, "BoardMarks")
    alb = g.e(unreal.MaterialExpressionLinearInterpolate)
    g.link(g.const3(0.86, 0.86, 0.84), "", alb, "A")
    g.link(g.const3(0.72, 0.10, 0.05), "", alb, "B")
    g.link(lines, "", alb, "Alpha")
    g.front(g.slab(albedo=(alb, ""), roughness=(g.const(0.3), "")))
    return g.finish()


def steel_paint():
    m = sbmat.new_material(f"{PKG}/M_SteelPaint")
    g = Graph(m)
    wp = sbmat.world_pos(g)
    rust = g.custom("return smoothstep(0.70, 0.78, N);", [("N", (noise(g, wp, 0.12, levels=4), ""))], CF1, "Rust")
    alb = g.e(unreal.MaterialExpressionLinearInterpolate)
    g.link(g.vector("PaintColor", 0.07, 0.11, 0.09), "", alb, "A")
    g.link(g.const3(0.24, 0.11, 0.05), "", alb, "B")
    g.link(rust, "", alb, "Alpha")
    rough = g.e(unreal.MaterialExpressionLinearInterpolate)
    g.link(g.const(0.48), "", rough, "A")
    g.link(g.const(0.85), "", rough, "B")
    g.link(rust, "", rough, "Alpha")
    g.front(g.slab(albedo=(alb, ""), roughness=(rough, "")))
    return g.finish()


def chain_link():
    m = sbmat.new_material(f"{PKG}/M_ChainLink", blend=unreal.BlendMode.BLEND_MASKED, two_sided=True)
    g = Graph(m)
    wp = sbmat.world_pos(g)
    wire = g.custom(FENCE_HLSL, [("WP", (wp, ""))], CF1, "ChainLink")
    g.front(g.slab(albedo=(g.const3(0.0, 0.0, 0.0), ""), f0=(g.const3(0.55, 0.56, 0.57), ""), roughness=(g.const(0.45), "")))
    g.to(wire, "", unreal.MaterialProperty.MP_OPACITY_MASK)
    return g.finish()


def main():
    unreal.EditorAssetLibrary.make_directory(PKG)
    built = {}
    for name, fn in (("CourtAsphalt", asphalt), ("Basketball", basketball), ("RimPaint", rim), ("Backboard", backboard),
                     ("SteelPaint", steel_paint), ("ChainLink", chain_link)):
        try:
            built[name] = fn()
        except Exception as e:
            unreal.log_error(f"MATERIAL {name} FAILED: {e}")
            continue
        sbmat.instance(built[name], f"{PKG}/MI_{name}")
    unreal.log(f"COURT_MATERIALS OK {sorted(built)}")


main()
