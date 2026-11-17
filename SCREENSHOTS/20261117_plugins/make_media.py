"""Builds the media for the plugins-pass feature page from Unreal captures (Saved/Screenshots/cap_*.png).

    uv run --with pillow python SCREENSHOTS/20261117_plugins/make_media.py annotations.json

* annotated stills: callout boxes + numbered labels from annotations.json -> <name>.jpg
* plain before/after pairs -> before_<view>.jpg / after_<view>.jpg
* GIFs from capture bursts via ffmpeg (palettegen/paletteuse) -> <burst>.gif
"""
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "unreal", "StreetballGym", "Saved", "Screenshots")
W_OUT = 1200
ACCENT = (255, 196, 48)
INK = (16, 20, 26)


def font(size):
    for f in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def load(name):
    im = Image.open(os.path.join(SRC, name)).convert("RGB")
    return im


def save_jpg(im, out, w=W_OUT):
    h = round(im.height * w / im.width)
    im.resize((w, h), Image.LANCZOS).save(os.path.join(HERE, out), quality=86, optimize=True)


def annotate(spec):
    im = load(spec["src"])
    d = ImageDraw.Draw(im)
    f = font(30)
    for i, c in enumerate(spec["callouts"], 1):
        x0, y0, x1, y1 = c["box"]
        d.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=ACCENT, width=5)
        lx, ly = c.get("label_at", (x0, max(0, y0 - 52)))
        text = f"{i}  {c['label']}"
        tw = d.textlength(text, font=f)
        lx = max(8, min(lx, im.width - tw - 40))       # keep the label inside the frame
        d.rounded_rectangle((lx, ly, lx + tw + 28, ly + 46), radius=8, fill=ACCENT)
        d.text((lx + 14, ly + 6), text, fill=INK, font=f)
        if "label_at" in c:
            # connector from label to box edge
            bx = min(max(lx + 20, x0), x1)
            by = y0 if ly + 46 < y0 else (y1 if ly > y1 else (y0 + y1) // 2)
            d.line((lx + 20, ly + 46 if ly + 46 < by else ly, bx, by), fill=ACCENT, width=5)
    save_jpg(im, spec["out"])


def gif(burst, out, fps, width=800, crop=None):
    frames = sorted(f for f in os.listdir(SRC) if f.startswith(f"cap_{burst}_") and f.endswith(".png"))
    if not frames:
        print("no frames for", burst)
        return
    tmp = os.path.join(HERE, "_frames")
    os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    for i, f in enumerate(frames):
        im = load(f)
        if crop:
            im = im.crop(crop)
        im.save(os.path.join(tmp, f"f_{i:03d}.png"))
    pattern = os.path.join(tmp, "f_%03d.png")
    vf = f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pattern, "-vf", vf, "-loop", "0",
                    os.path.join(HERE, out)], check=True)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    print(f"{out}: {len(frames)} frames, {os.path.getsize(os.path.join(HERE, out)) / 1e6:.1f} MB")


def main():
    spec = json.load(open(os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "annotations.json"), encoding="utf-8"))
    for a in spec.get("annotate", []):
        annotate(a)
        print("annotated", a["out"])
    for p in spec.get("plain", []):
        save_jpg(load(p["src"]), p["out"])
        print("plain", p["out"])
    for g in spec.get("gifs", []):
        gif(g["burst"], g["out"], g.get("fps", 6), g.get("width", 800), g.get("crop"))


main()
