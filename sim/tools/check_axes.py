"""Task A6: verify the sim -> Unreal frame conversion and the bone-driving rule.

Implements blueprint B.1 / B.2 in numpy, exactly as the UE plugin will:

    toUE(pos)  = ( x*100, -y*100, z*100 )
    toUE(quat) = FQuat( X=-qx, Y=qy, Z=-qz, W=qw )          # MuJoCo (w,x,y,z) in
    offset[b]  = inverse( toUE(q_ref_sim[b]) ) * q_bind_ue[b]  # captured once at qpos = 0
    q_bone[b]  = toUE( q_sim[b] ) * offset[b]                   # every frame

Checks
  1. Reference pose: driven bone orientation == bind orientation (max error < 0.1 deg).
  2. 90 deg left hip flexion in sim: the UE thigh bone's child direction (thigh->calf)
     ends up pointing along the mannequin's forward axis (+Y in mesh space) and
     horizontal; same for a 90 deg shoulder pitch (upper arm forward).
  3. Positions: toUE(sim body pos at qpos = 0) == bind bone pos within 1 mm, after the
     constant yaw between the sim frame (+X forward) and mesh space (+Y forward).

Usage: uv run python tools/check_axes.py
"""
import json
import pathlib
import sys

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"

# UE FQuat stored as (X, Y, Z, W) everywhere below.


def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ])


def q_inv(q):
    x, y, z, w = q
    return np.array([-x, -y, -z, w])


def q_rot(q, v):
    """Rotate vector v by quaternion q (X,Y,Z,W). Valid for either handedness because
    the formula is purely algebraic; handedness is already in the quaternion."""
    qv = np.array([v[0], v[1], v[2], 0.0])
    return q_mul(q_mul(q, qv), q_inv(q))[:3]


def q_angle_deg(a, b):
    d = abs(float(np.dot(a, b)))
    return np.degrees(2 * np.arccos(min(1.0, d)))


def to_ue_pos(p):
    return np.array([p[0] * 100.0, -p[1] * 100.0, p[2] * 100.0])


def to_ue_quat(q_wxyz):
    w, x, y, z = q_wxyz
    return np.array([-x, y, -z, w])


def yaw_quat_ue(deg):
    """UE quaternion for a yaw (about +Z) of `deg` degrees in UE's left-handed frame."""
    h = np.radians(deg) / 2
    return np.array([0.0, 0.0, np.sin(h), np.cos(h)])


def main() -> int:
    bones = {b["name"]: b for b in json.load(open(SHARED / "mannequin_bones.json", encoding="utf-8"))["bones"]}
    spec = json.load(open(SHARED / "humanoid_spec.json", encoding="utf-8"))
    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    mujoco.mj_resetData(m, d)
    mujoco.mj_forward(m, d)

    body_ids = {name: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, name) for name in spec["body_bone_map"]}
    bind_q = {n: np.array(b["component_space"]["quat_xyzw"]) for n, b in bones.items()}
    bind_p = {n: np.array(b["component_space"]["pos_cm"]) for n, b in bones.items()}

    # The sim character faces +X; the mannequin mesh faces +Y (mesh space). In UE the
    # mesh component is yawed so both face actor +X; the equivalent constant here is a
    # -90 deg yaw applied to the UE-converted sim quantities to land in mesh space.
    # (Sign: converting sim +X forward to UE gives +X; mesh forward is +Y; UE left-handed
    # yaw of +90 deg takes +X to +Y. We fold this into the offset capture, which is why
    # the plugin never needs it explicitly, but we need it to compare against bind data.)
    yaw = yaw_quat_ue(90.0)
    yaw_mat = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)   # +90 deg about Z (left-handed UE basis)

    # ---- offsets at the reference pose
    offsets = {}
    for body, entry in spec["body_bone_map"].items():
        bone = entry.get("anchor", entry["bones"][0])
        q_ref = q_mul(yaw, to_ue_quat(d.xquat[body_ids[body]]))
        offsets[body] = q_mul(q_inv(q_ref), bind_q[bone])

    worst = 0.0
    bad = []

    # ---- check 1 + 3: reference pose reproduces the bind pose
    for body, entry in spec["body_bone_map"].items():
        bone = entry.get("anchor", entry["bones"][0])
        q = q_mul(q_mul(yaw, to_ue_quat(d.xquat[body_ids[body]])), offsets[body])
        worst = max(worst, q_angle_deg(q, bind_q[bone]))
        p = yaw_mat @ to_ue_pos(d.xpos[body_ids[body]])
        # pelvis bind sits at (0, 2.28, 95.9); sim pelvis is at the same place by construction
        perr = np.linalg.norm(p - bind_p[bone])
        if perr > 0.1:   # cm
            bad.append(f"position mismatch {body}->{bone}: {perr:.3f} cm")
    print(f"[1] reference pose: max bone orientation error {worst:.4f} deg", "PASS" if worst < 0.1 else "FAIL")
    print(f"[3] reference pose: body positions within 1 mm of bind bones", "PASS" if not bad else "FAIL")
    for line in bad:
        print("    ", line)

    # ---- check 2: a 90 deg joint motion lands where anatomy says it should
    def bone_child_dir_after(joint, deg, body, bone, child_bone):
        mujoco.mj_resetData(m, d)
        jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, joint)
        d.qpos[m.jnt_qposadr[jid]] = np.radians(deg)
        mujoco.mj_forward(m, d)
        q = q_mul(q_mul(yaw, to_ue_quat(d.xquat[body_ids[body]])), offsets[body])
        bind_dir = bind_p[child_bone] - bind_p[bone]
        # bind_dir expressed in the bind bone frame, then re-expressed with the driven orientation
        local = q_rot(q_inv(bind_q[bone]), bind_dir)
        return q_rot(q, local) / np.linalg.norm(bind_dir)

    ok2 = True
    anat = spec["joints"]
    hip_offset = 0.0
    v = bone_child_dir_after("hip_flex_l", 90.0, "thigh_l", "thigh_l", "calf_l")
    fwd = v[1] > 0.95 and abs(v[2]) < 0.2    # mesh forward is +Y, horizontal
    ok2 &= fwd
    print(f"[2] hip_flex_l = 90 deg -> UE thigh direction (mesh space) = {np.round(v, 3)}  expect ~(0, +1, 0)", "PASS" if fwd else "FAIL")
    v = bone_child_dir_after("knee_l", 90.0 - spec["reference_pose_info"]["knee_flexion_in_ref_pose_deg"]["l"], "calf_l", "calf_l", "foot_l")
    back = v[1] < -0.9
    ok2 &= back
    print(f"[2] knee_l = 90 deg anatomical -> UE calf direction = {np.round(v, 3)}  expect ~(0, -1, 0) (heel kicks back)", "PASS" if back else "FAIL")
    v = bone_child_dir_after("shoulder_pitch_l", 90.0, "upperarm_l", "upperarm_l", "lowerarm_l")
    fwd = v[1] > 0.6 and v[2] > -0.4
    ok2 &= fwd
    print(f"[2] shoulder_pitch_l = 90 deg -> UE upper arm direction = {np.round(v, 3)}  expect forward (+Y) and roughly level", "PASS" if fwd else "FAIL")

    passed = worst < 0.1 and not bad and ok2
    report = ROOT.parent / "docs" / "phase_reports" / "A6_axis_check.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"# A6 — Axis alignment check: {'PASS' if passed else 'FAIL'}\n\n"
        f"Conversion: `pos_ue = (x*100, -y*100, z*100)`, `quat_ue(X,Y,Z,W) = (-qx, qy, -qz, qw)`, "
        f"bone drive `q_bone = toUE(q_sim) * offset`, offsets captured at qpos = 0.\n\n"
        f"| Check | Result |\n|---|---|\n"
        f"| Reference pose orientation error | {worst:.4f} deg (< 0.1) |\n"
        f"| Reference pose position error | {'all < 1 mm' if not bad else '; '.join(bad)} |\n"
        f"| 90 deg hip flexion / knee flexion / shoulder pitch | {'anatomically correct in UE mesh space' if ok2 else 'WRONG, see console'} |\n",
        encoding="utf-8",
    )
    print("wrote", report)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
