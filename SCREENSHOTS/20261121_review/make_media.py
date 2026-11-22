"""Media for the 2026-11-21 review page, from engine-rendered captures only (no desktop capture).

Game captures (Saved/Screenshots/cap_n21*.png), one run per brain, seed 7, tier 3, right hand, 1600x900, -game:
    -StreetballSeed=7 -StreetballStartTier=3 -StreetballMaxTier=3 -StreetballDribbleHand=right -StreetballQuitAfter=40
    -StreetballCapture=4:0:0:body:n21<b>_start+6:4:12:body:n21<b>_gif+12:0:0:bc:n21<b>_bc12+...      (stills)
    same with -ExecCmds="slomo 0.25" and n21s<b>_* for the GIF bursts (quarter speed: ~12 frames per game second)
    old brain: -StreetballPolicy_dribble=policies/dribble_drift250.onnx
Editor captures (raw/): Simulate-In-Editor session, editor window only (PrintWindow on the editor's HWND), plus the
engine high-res shot of Play-In-Editor after moving the PCG volume and rotating the sun (Saved/Screenshots/WindowsEditor).

    sim/.venv/Scripts/python.exe SCREENSHOTS/20261121_review/make_media.py
"""

import glob
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SS = os.path.join(HERE, "..", "..", "unreal", "StreetballGym", "Saved", "Screenshots")
RAW = os.path.join(HERE, "raw")
NEW = (255, 196, 48)
OLD = (170, 176, 186)
EDIT = (120, 200, 255)
INK = (16, 20, 26)


def font(size):
    for f in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def frames(pattern):
    return sorted(glob.glob(os.path.join(SS, pattern)))


def tag(im, title, sub, colour, scale=1.0):
    d = ImageDraw.Draw(im)
    f1, f2 = font(int(30 * scale)), font(int(21 * scale))
    pad = int(16 * scale)
    w = max(d.textlength(title, font=f1), d.textlength(sub, font=f2)) + 2 * pad
    h = int(88 * scale)
    x0, y0 = int(12 * scale), im.height - h - int(14 * scale)
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=int(10 * scale), fill=colour)
    d.text((x0 + pad, y0 + int(8 * scale)), title, fill=INK, font=f1)
    d.text((x0 + pad, y0 + int(48 * scale)), sub, fill=INK, font=f2)
    return im


def callout(im, box, text, colour):
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, radius=8, outline=colour, width=5)
    f = font(22)
    tw = d.textlength(text, font=f) + 24
    x, y = box[0], box[3] + 10
    d.rounded_rectangle((x, y, x + tw, y + 38), radius=8, fill=colour)
    d.text((x + 12, y + 7), text, fill=INK, font=f)


def gif(paths, out, size, fps, label=None):
    ims = []
    for p in paths:
        im = Image.open(p).convert("RGB").resize(size, Image.LANCZOS)
        if label:
            tag(im, *label, scale=size[0] / 1600)
        ims.append(im.convert("P", palette=Image.ADAPTIVE, colors=128))
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=int(1000 / fps), loop=0, optimize=True)
    return len(ims)


def side_by_side(left, right, out, size, fps, llab, rlab):
    n = min(len(left), len(right))
    ims = []
    for a, b in zip(left[:n], right[:n]):
        A = tag(Image.open(a).convert("RGB").resize(size, Image.LANCZOS), *llab, scale=size[0] / 1600)
        B = tag(Image.open(b).convert("RGB").resize(size, Image.LANCZOS), *rlab, scale=size[0] / 1600)
        c = Image.new("RGB", (size[0] * 2 + 8, size[1]), (16, 20, 26))
        c.paste(A, (0, 0))
        c.paste(B, (size[0] + 8, 0))
        ims.append(c.convert("P", palette=Image.ADAPTIVE, colors=128))
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=int(1000 / fps), loop=0, optimize=True)
    return n


def main():
    made = []
    # 1. GIFs (quarter-speed bursts: 12 frames per game second -> played at 12 fps = real time)
    n = gif(
        frames("cap_n21snew_gif_*.png"),
        os.path.join(HERE, "gif_new_dribble.gif"),
        (640, 360),
        12,
        ("New dribble brain", "ckpt_600M - gate 71 % - real time", NEW),
    )
    made.append(("gif_new_dribble.gif", n))
    n = side_by_side(
        frames("cap_n21snew_bcgif_*.png"),
        frames("cap_n21sold_bcgif_*.png"),
        os.path.join(HERE, "gif_new_vs_old.gif"),
        (480, 270),
        12,
        ("NEW (ckpt_600M)", "gate 71 %", NEW),
        ("OLD (dribble_drift 250M)", "gate 9 %", OLD),
    )
    made.append(("gif_new_vs_old.gif", n))

    # 2. annotated gameplay stills
    im = Image.open(frames("cap_n21new_bc12_*.png")[0]).convert("RGB")
    callout(im, (12, 104, 168, 132), "Counts clean bounces: ball within 0.3 m of the dribble spot (new rule)", NEW)
    tag(im, "New dribble brain in Unreal", "Tier 3 stationary dribble - seed 7 - 12 s in", NEW)
    im.save(os.path.join(HERE, "ann_new_dribble.jpg"), quality=88)
    made.append(("ann_new_dribble.jpg", 1))
    for b, lab, col, sub in (
        ("new", "NEW brain", NEW, "same seed, 32 s in"),
        ("old", "OLD brain", OLD, "same seed, 32 s in"),
    ):
        im = Image.open(frames(f"cap_n21{b}_bc32_*.png")[0]).convert("RGB").resize((800, 450), Image.LANCZOS)
        tag(im, lab, sub, col, scale=0.5).save(os.path.join(HERE, f"still_{b}_32s.jpg"), quality=88)
        made.append((f"still_{b}_32s.jpg", 1))

    # 3. editor shots
    ed = [
        ("sie01_running.png", "ed_sie_running.jpg", "Simulate-In-Editor", "game running inside the editor viewport"),
        (
            "sie02_prop_selected.png",
            "ed_sie_selected.jpg",
            "Runtime actor selected",
            "spectator 6 picked while the game runs",
        ),
        ("sie04_sun_rotated.png", "ed_sie_sun.jpg", "Sun rotated -15 / +70 deg", "shadows move, the game carries on"),
    ]
    for src, dst, t, s in ed:
        p = os.path.join(RAW, src)
        if os.path.exists(p):
            im = Image.open(p).convert("RGB")
            tag(im, t, s, EDIT, scale=0.8).save(os.path.join(HERE, dst), quality=88)
            made.append((dst, 1))
    p = os.path.join(SS, "WindowsEditor", "rev_ed07_pie_running.png")
    if os.path.exists(p):
        im = Image.open(p).convert("RGB")
        tag(im, "Play-In-Editor after editing the level", "PCG volume moved 12 m, sun rotated", EDIT)
        im.save(os.path.join(HERE, "ed_pie_after_edits.jpg"), quality=88)
        made.append(("ed_pie_after_edits.jpg", 1))
    for name, k in made:
        print(f"{name}: {k} frame(s), {os.path.getsize(os.path.join(HERE, name)) // 1024} KB")


if __name__ == "__main__":
    main()
