"""Media for the 2026-11-24 time-of-day page, from engine-rendered captures only (-ShowcaseCapture PNGs, kept in raw/ as quality-95 JPGs).

    before/   : the previous build (time of day did not exist), captured from a stash of the C++/config changes
    h_<hour>/ : unreal/StreetballGym/Scripts/capture_time_of_day.ps1 -OutDir SCREENSHOTS/20261124_time_of_day/raw

    sim/.venv/Scripts/python.exe SCREENSHOTS/20261124_time_of_day/make_media.py
Writes labelled JPGs next to this file and prints the before-vs-ref pixel difference.
"""

import glob
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
SHOTS = [
    ("before", "Before", "previous build, fixed sun"),
    ("h_ref", "13:34", "start hour = the level's own sun"),
    ("h_17.6", "17:36", "golden hour"),
    ("h_18.3", "18:18", "dusk, lamps on"),
    ("h_22.5", "22:30", "night: moon + streetlights"),
]


def font(size):
    for f in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def tag(im, title, sub):
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(
        (16, im.height - 74, 16 + 14 + max(len(title) * 17, len(sub) * 10), im.height - 16), 8, fill=(16, 20, 26)
    )
    d.text((28, im.height - 70), title, font=font(26), fill=(255, 196, 48))
    d.text((28, im.height - 40), sub, font=font(17), fill=(235, 235, 235))
    return im


def load(name, shot="overlay_off"):
    return Image.open(os.path.join(RAW, name, f"{shot}.jpg")).convert("RGB")


def main():
    # fresh captures arrive as PNG (1600x900, ~2 MB each): keep the two used per run, as quality-95 JPG
    for p in glob.glob(os.path.join(RAW, "*", "*.png")):
        if os.path.basename(p) in ("overlay_off.png", "demo_b.png"):
            Image.open(p).convert("RGB").save(p[:-4] + ".jpg", quality=95)
        os.remove(p)
    for key, title, sub in SHOTS:
        tag(load(key).resize((1200, 675), Image.LANCZOS), title, sub).save(os.path.join(HERE, f"{key}.jpg"), quality=86)
    tag(load("h_22.5", "demo_b").resize((1200, 675), Image.LANCZOS), "22:30", "demo camera at night").save(
        os.path.join(HERE, "night_demo.jpg"), quality=86
    )
    # strip of the day, for the page header
    keys = ["h_ref", "h_17.6", "h_18.3", "h_22.5"]
    strip = Image.new("RGB", (4 * 400, 225))
    for i, k in enumerate(keys):
        strip.paste(load(k).resize((400, 225), Image.LANCZOS), (i * 400, 0))
    strip.save(os.path.join(HERE, "strip.jpg"), quality=86)
    # before vs the start hour: the court below the HUD rows (the character's pose differs a little between runs)
    a = np.asarray(load("before"), dtype=np.float32)[120:820]
    b = np.asarray(load("h_ref"), dtype=np.float32)[120:820]
    print(
        f"before vs start hour: mean |diff| {np.abs(a - b).mean():.2f} / 255, mean luminance {a.mean():.1f} vs {b.mean():.1f}"
    )


if __name__ == "__main__":
    main()
