"""Media for the 2026-11-19 standing-brain page, from Unreal captures (Saved/Screenshots/cap_n19<brain>_*.png).

Captured with (one run per brain, seed 7, 1600x900, -game):
    -StreetballDemoFeatures -StreetballSeed=7 -StreetballQuitAfter=36 [-StreetballPolicy_balance=policies/<file>.onnx]
    -StreetballCapture=2.5:0:0:body:<n>_stand+12.3:3.6:8:bc:<n>_push+16.0:4.0:8:bc:<n>_push2+20.4:0:0:bc:<n>_quiet+24:10:5:bc:<n>_play

    sim/.venv/Scripts/python.exe SCREENSHOTS/20261119_posture/make_media.py
"""

import glob
import os
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "unreal", "StreetballGym", "Saved", "Screenshots")
ACCENT = (255, 196, 48)
INK = (16, 20, 26)
BRAINS = [
    ("v1w", "Old brain (v1w)", "99.0 % balance - torso 0.875"),
    ("pos", "Posture brain (this morning)", "81.5 % balance - torso 0.978"),
    ("qp", "Quiet-posture brain (NEW)", "97.0 % balance - torso 0.903"),
]


def font(size):
    for f in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def frames(name):
    return sorted(glob.glob(os.path.join(SRC, f"cap_n19{name}_*.png")))


def tag(im, title, sub, colour=ACCENT):
    d = ImageDraw.Draw(im)
    f1, f2 = font(30), font(22)
    w = max(d.textlength(title, font=f1), d.textlength(sub, font=f2)) + 32
    d.rounded_rectangle((12, 12, 12 + w, 98), radius=10, fill=colour)
    d.text((28, 20), title, fill=INK, font=f1)
    d.text((28, 60), sub, fill=INK, font=f2)


def callout(im, box, n, label, at):
    d = ImageDraw.Draw(im)
    f = font(24)
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=10, outline=ACCENT, width=5)
    text = f"{n}  {label}"
    lx, ly = at
    tw = d.textlength(text, font=f)
    lx = max(8, min(lx, im.width - tw - 36))
    d.rounded_rectangle((lx, ly, lx + tw + 24, ly + 40), radius=8, fill=ACCENT)
    d.text((lx + 12, ly + 6), text, fill=INK, font=f)
    bx, by = min(max(lx + 20, x0), x1), (y0 if ly < y0 else y1)
    d.line((lx + 20, ly + (40 if ly < y0 else 0), bx, by), fill=ACCENT, width=4)


def stand_triptych():
    # full-body stills at 2.5 s (quiet stand, no push yet); crop around the character
    notes = {
        "v1w": ("chest folds forward", 1),
        "pos": ("chest stacked over hips", 2),
        "qp": ("a little straighter than old", 3),
    }
    tiles = []
    for key, title, sub in BRAINS:
        im = Image.open(frames(f"{key}_stand")[0]).convert("RGB").crop((420, 40, 1100, 880))
        tag(im, title, sub)
        label, n = notes[key]
        callout(im, (170, 110, 520, 420), n, label, (40, 780))
        tiles.append(im)
    W = Image.new("RGB", (sum(t.width for t in tiles) + 2 * 12, tiles[0].height), (24, 24, 28))
    x = 0
    for t in tiles:
        W.paste(t, (x, 0))
        x += t.width + 12
    W.save(os.path.join(HERE, "ann_stand_triptych.jpg"), quality=88, optimize=True)


def gameplay_still():
    fs = frames("qp_play")
    im = Image.open(fs[-2]).convert("RGB")
    callout(im, (1190, 10, 1590, 40), 1, "the active brain is shown live", (980, 70))
    callout(im, (700, 280, 900, 680), 2, "shot / scramble still run placeholder brains", (480, 760))
    callout(im, (0, 50, 380, 210), 3, "tier 5 of the director's ladder", (430, 150))
    im.resize((1280, 720), Image.LANCZOS).save(os.path.join(HERE, "ann_gameplay.jpg"), quality=88, optimize=True)


def ffmpeg_gif(frame_paths, out, fps, width):
    if shutil.which("ffmpeg") is None:  # Pillow fallback: one shared adaptive palette, no dithering noise
        ims = [im.resize((width, round(im.height * width / im.width)), Image.LANCZOS) for im in frame_paths]
        pal = ims[len(ims) // 2].quantize(colors=200, method=Image.Quantize.MEDIANCUT)
        q = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in ims]
        q[0].save(
            os.path.join(HERE, out), save_all=True, append_images=q[1:], duration=int(1000 / fps), loop=0, optimize=True
        )
        print(f"{out}: {len(ims)} frames, {os.path.getsize(os.path.join(HERE, out)) / 1e6:.2f} MB")
        return
    tmp = os.path.join(HERE, "_frames")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for i, im in enumerate(frame_paths):
        im.save(os.path.join(tmp, f"f_{i:03d}.png"))
    vf = f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            os.path.join(tmp, "f_%03d.png"),
            "-vf",
            vf,
            "-loop",
            "0",
            os.path.join(HERE, out),
        ],
        check=True,
    )
    shutil.rmtree(tmp)
    print(f"{out}: {len(frame_paths)} frames, {os.path.getsize(os.path.join(HERE, out)) / 1e6:.2f} MB")


def push_side_by_side():
    # both 110 N shoves (0.5x slow motion), the three brains in step, cropped around the character
    seqs = {k: frames(f"{k}_push") + frames(f"{k}_push2") for k, _, _ in BRAINS}
    n = min(len(s) for s in seqs.values())
    out = []
    for i in range(n):
        W = Image.new("RGB", (3 * 640 + 24, 520), (24, 24, 28))
        for j, (key, title, sub) in enumerate(BRAINS):
            src = seqs[key][int(i * (len(seqs[key]) - 1) / max(1, n - 1))]
            im = Image.open(src).convert("RGB").crop((480, 180, 1120, 700))
            tag(im, title, sub)
            W.paste(im, (j * 652, 0))
        out.append(W)
    ffmpeg_gif(out, "gif_push_side_by_side.gif", 5, 1200)


def gameplay_gif():
    ims = [Image.open(f).convert("RGB") for f in frames("qp_play")]
    ffmpeg_gif(ims, "gif_gameplay.gif", 5, 720)


if __name__ == "__main__":
    stand_triptych()
    gameplay_still()
    push_side_by_side()
    gameplay_gif()
