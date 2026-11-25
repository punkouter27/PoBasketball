"""Annotated stills + GIFs for the 2026-11-25 progress report."""
import glob
import os

from PIL import Image, ImageDraw, ImageFont

SHOTS = r"C:\Users\punko\Downloads\_CODEMATT\PoBasketball\unreal\StreetballGym\Saved\Screenshots"
ED = r"C:\Users\punko\AppData\Local\Temp\claude\3d95cc0ddc13cb6d\06e1312c-b761-4b1e-82b6-1399c21456a8\scratchpad\rep\editor"
OUT = r"C:\Users\punko\Downloads\_CODEMATT\PoBasketball\SCREENSHOTS\20261125_progress"
os.makedirs(OUT, exist_ok=True)
F = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 22)
FS = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 18)
ACC = (255, 196, 0)


def label(d, xy, text, anchor_pt=None, font=F):
    x, y = xy
    l, t, r, b = d.textbbox((x, y), text, font=font)
    d.rounded_rectangle((l - 10, t - 6, r + 10, b + 6), 8, fill=(20, 20, 24), outline=ACC, width=3)
    d.text((x, y), text, font=font, fill=(255, 255, 255))
    if anchor_pt:
        # arrow from the box edge to the point
        bx = l - 10 if anchor_pt[0] < l else (r + 10 if anchor_pt[0] > r else (l + r) / 2)
        by = (t + b) / 2 if bx in (l - 10, r + 10) else (b + 6 if anchor_pt[1] > b else t - 6)
        d.line((bx, by, *anchor_pt), fill=ACC, width=4)
        d.ellipse((anchor_pt[0] - 7, anchor_pt[1] - 7, anchor_pt[0] + 7, anchor_pt[1] + 7), fill=ACC)


def ring(d, box):
    d.rounded_rectangle(box, 10, outline=ACC, width=4)


def game(name):
    return Image.open(os.path.join(SHOTS, f"cap_{name}_000.png")).convert("RGB")  # 1280x720


def save(im, name, w=None):
    if w:
        im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    im.save(os.path.join(OUT, name), quality=86)


# 1 Dribble Lab panel
im = game("r_lab"); d = ImageDraw.Draw(im); s = im.width / 1600
ring(d, (20 * s, 88 * s, 304 * s, 225 * s)); label(d, (420 * s, 110 * s), "Behaviour buttons (keys 1-4): trained / untrained", (304 * s, 160 * s))
ring(d, (20 * s, 255 * s, 304 * s, 390 * s)); label(d, (420 * s, 300 * s), "Humanoid buttons (key H): 5 skins, same body + brain", (304 * s, 320 * s))
ring(d, (20 * s, 400 * s, 304 * s, 555 * s)); label(d, (420 * s, 470 * s), "Live stats: bounces, clean streak, run time, resets", (304 * s, 480 * s))
label(d, (900 * s, 820 * s), "Trained brain dribbling (dribble.onnx via NNE)", (int(640 * 1.0), int(470)))
save(im, "a_lab.jpg")

# 2 face camera mood
for src, txt, out in (("r_smile", "Clean streak 29: full grin (MetaHuman RigLogic face controls)", "a_smile.jpg"),
                      ("r_frown", "0.3 s after a reset: frown, fades over 2.5 s", "a_frown.jpg")):
    im = game(src); d = ImageDraw.Draw(im)
    label(d, (330, 640), txt, (700, 470))
    label(d, (330, 30), "Face camera (key F)", None)
    save(im, out)

# 3 untrained left hand
im = game("r_left"); d = ImageDraw.Draw(im)
label(d, (330, 600), "Untrained behaviour flagged in red; she loses the ball and scrambles", (1060, 260))
save(im, "a_left.jpg")

# 4 humanoids strip
names = [("r_lab", "Grandma (original, MetaHuman)"), ("r_skin_grace", "Grandma (MetaHuman)"), ("r_skin_cc", "Grandma"),
         ("r_skin_manny", "Manny"), ("r_skin_quinn", "Quinn")]
tiles = []
for src, txt in names:
    t = game(src).crop((420, 120, 1060, 720)).resize((320, 300))
    dt = ImageDraw.Draw(t); label(dt, (12, 262), txt, None, FS); tiles.append(t)
strip = Image.new("RGB", (320 * 5, 300))
for i, t in enumerate(tiles):
    strip.paste(t, (320 * i, 0))
save(strip, "a_humanoids.jpg")

# 5 behaviours
for src, txt, out in (("r_moving", "Behaviour 4: moving dribble (tier 4, untrained)", "a_moving.jpg"),
                      ("r_crossover", "Behaviour 3: crossover (commanded hand switches, untrained)", "a_crossover.jpg")):
    im = game(src); d = ImageDraw.Draw(im); label(d, (330, 650), txt, None); save(im, out)

# 6 editor
def ed(n):
    return Image.open(os.path.join(ED, n + ".png")).convert("RGB").crop((0, 0, 1920, 1032))  # no taskbar

im = ed("e1_selected_gizmo"); d = ImageDraw.Draw(im)
label(d, (300, 700), "StreetballNeighbourhood (PCG volume) selected: bounds + move gizmo", (766, 486))
ring(d, (1535, 628, 1910, 702)); label(d, (1060, 470), "Details > Transform: Location / Rotation", (1535, 660))
save(im, "e_selected.jpg", 1600)
im = ed("e2_moved_regenerated"); d = ImageDraw.Draw(im)
label(d, (120, 900), "Moved +20 m x, +8 m y, rotated 25 deg: neighbourhood regenerates around it", (640, 640))
ring(d, (1535, 628, 1910, 702)); label(d, (1020, 470), "Location 2000 / 800 / 500, yaw 25", (1535, 660))
save(im, "e_moved.jpg", 1600)
im = ed("e3_sun_rotated"); d = ImageDraw.Draw(im)
label(d, (120, 900), "Sun (DirectionalLight) rotated with the gizmo: pitch -75, yaw 95", (763, 631))
save(im, "e_sun.jpg", 1600)
im = ed("e4_pie_running"); d = ImageDraw.Draw(im)
label(d, (820, 380), "Play-In-Editor with the moved scenery: 57 bounces, 55 clean, 0 resets", (500, 1250 * 0 + 640))
label(d, (820, 450), "All 5 policies loaded (NNE / ONNX), Dribble Lab on", None, FS)
save(im, "e_pie.jpg", 1600)
im = ed("e6_restored"); d = ImageDraw.Draw(im)
label(d, (120, 900), "Transforms restored, level never saved (git: no change to Court.umap)", None)
save(im, "e_restored.jpg", 1600)

# GIFs
for name, cap in (("g_right", "Right hand (trained): clean dribble"), ("g_smile", "Face camera: grin grows with the streak"),
                  ("g_frown", "Reset -> frown, then fading"), ("g_left", "Left hand (untrained): ball lost, scramble"),
                  ("g_moving", "Moving dribble (untrained)")):
    src = name.replace("g_", "r_gif_")
    frames = sorted(glob.glob(os.path.join(SHOTS, f"cap_{src}_*.png")))
    imgs = []
    for f in frames:
        fr = Image.open(f).convert("RGB").resize((640, 360), Image.LANCZOS)
        dd = ImageDraw.Draw(fr); label(dd, (14, 322), cap, None, FS)
        imgs.append(fr.quantize(colors=160, method=Image.Quantize.MEDIANCUT))
    imgs[0].save(os.path.join(OUT, name + ".gif"), save_all=True, append_images=imgs[1:], duration=int(3000 / max(1, len(imgs))), loop=0, optimize=True)
    print(name, len(imgs), "frames", os.path.getsize(os.path.join(OUT, name + ".gif")) // 1024, "KB")
