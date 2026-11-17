"""Builds annotated screenshots and animated GIFs for the new-features showcase page
from Unreal captures (unreal/StreetballGym/Saved/Screenshots/cap_*.png).

    uv run --with pillow python SCREENSHOTS/20261117_features/make_media.py annotations.json
"""
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "unreal", "StreetballGym", "Saved", "Screenshots")
W_OUT = 1280
ACCENT = (255, 196, 48)
INK = (16, 20, 26)


def font(size):
    for f in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def load(name):
    return Image.open(os.path.join(SRC, name)).convert("RGB")


def save_jpg(im, out, w=W_OUT):
    h = round(im.height * w / im.width)
    im.resize((w, h), Image.LANCZOS).save(os.path.join(HERE, out), quality=88, optimize=True)


def annotate(spec):
    im = load(spec["src"])
    d = ImageDraw.Draw(im)
    f = font(28)
    for i, c in enumerate(spec["callouts"], 1):
        x0, y0, x1, y1 = c["box"]
        d.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=ACCENT, width=5)
        lx, ly = c.get("label_at", (x0, max(8, y0 - 52)))
        text = f"{i}  {c['label']}"
        tw = d.textlength(text, font=f)
        lx = max(8, min(lx, im.width - tw - 40))
        ly = max(8, min(ly, im.height - 54))
        d.rounded_rectangle((lx, ly, lx + tw + 28, ly + 44), radius=8, fill=ACCENT)
        d.text((lx + 14, ly + 6), text, fill=INK, font=f)
        if "label_at" in c:
            bx = min(max(lx + 20, x0), x1)
            by = y0 if ly + 44 < y0 else (y1 if ly > y1 else (y0 + y1) // 2)
            d.line((lx + 20, ly + 44 if ly + 44 < by else ly, bx, by), fill=ACCENT, width=5)
    save_jpg(im, spec["out"])


def gif(burst, out, fps, width=840, crop=None):
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
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pattern, "-vf", vf, "-loop", "0", os.path.join(HERE, out)],
        check=True,
    )
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    print(f"{out}: {len(frames)} frames, {os.path.getsize(os.path.join(HERE, out)) / 1e6:.2f} MB")


def main():
    spec = json.load(open(os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "annotations.json"), encoding="utf-8"))
    for a in spec.get("annotate", []):
        if os.path.exists(os.path.join(SRC, a["src"])):
            annotate(a)
            print("annotated", a["out"])
        else:
            print("missing src:", a["src"])
    for p in spec.get("plain", []):
        if os.path.exists(os.path.join(SRC, p["src"])):
            save_jpg(load(p["src"]), p["out"])
            print("plain", p["out"])
        else:
            print("missing src:", p["src"])
    for g in spec.get("gifs", []):
        gif(g["burst"], g["out"], g.get("fps", 8), g.get("width", 840), g.get("crop"))


if __name__ == "__main__":
    main()
