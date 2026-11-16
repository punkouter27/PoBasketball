"""Compare two bone dumps from dump_mannequin_bones.py on the joints the physics body is built from.

    python compare_bones.py <reference.json> <candidate.json> [--tol-cm 1.0]

Exit 0 when every mapped joint (pelvis, spine, neck, head, clavicles, arms, hands, legs, feet, balls) of the
candidate's bind pose is within tol of the reference, i.e. the skin fits the MuJoCo body exactly as Manny does.
"""
import argparse
import json
import math

JOINTS = ["pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head"] + [
    f"{b}_{s}" for s in ("l", "r") for b in ("clavicle", "upperarm", "lowerarm", "hand", "thigh", "calf", "foot", "ball")]

ap = argparse.ArgumentParser()
ap.add_argument("reference")
ap.add_argument("candidate")
ap.add_argument("--tol-cm", type=float, default=1.0)
a = ap.parse_args()
ref = {b["name"]: b["component_space"]["pos_cm"] for b in json.load(open(a.reference, encoding="utf-8"))["bones"]}
cand = {b["name"]: b["component_space"]["pos_cm"] for b in json.load(open(a.candidate, encoding="utf-8"))["bones"]}
worst = 0.0
for j in JOINTS:
    if j not in cand:
        print(f"{j:12s} MISSING")
        worst = math.inf
        continue
    d = math.dist(ref[j], cand[j])
    worst = max(worst, d)
    print(f"{j:12s} {d:6.2f} cm")
ok = worst <= a.tol_cm
print(f"max joint offset {worst:.2f} cm (tolerance {a.tol_cm} cm): {'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)
