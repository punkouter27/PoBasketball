"""Task A3: generate sim/assets/humanoid.xml from the UE5 Manny skeleton dump.

Reads shared/mannequin_bones.json (task A2) so every sim joint sits exactly on
its mannequin bone. Writes:

  sim/assets/humanoid.xml      MJCF body/joint/actuator tree (blueprint A.2-A.4)
  sim/assets/scene.xml         options + includes humanoid.xml and court.xml
  shared/humanoid_spec.json    joint order, ranges, nominal pose, actuator gains,
                               body->bone map; consumed by obs.py and the UE plugin

Frames
------
UE mesh space (cm, left-handed, Z-up, Manny faces +Y, +X is the character's left)
is converted to the sim frame (m, right-handed, Z-up, character faces +X, +Y is
the character's left):

    sim = Rz(+90 deg) * ( ue_x, -ue_y, ue_z ) / 100

All sim bodies are created with identity orientation, so at qpos = 0 every body
frame equals the world frame and the pose equals Manny's reference (A-)pose.

Usage: uv run python tools/build_humanoid.py
"""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"
ASSETS = ROOT / "assets"

# ----------------------------------------------------------------------------- blueprint A.2 / A.4
MASS = dict(pelvis=11.2, torso=28.6, head=6.5, upperarm=2.24, lowerarm=1.28, hand=0.48,
            thigh=8.0, calf=3.72, foot=1.16)
RADIUS = dict(torso=0.12, upperarm=0.045, lowerarm=0.035, thigh=0.07, calf=0.05, head=0.11)
GAINS = {  # group: (kp, kv, torque)
    "hip": (400, 40, 300), "knee": (400, 40, 300), "ankle": (200, 20, 150),
    "lumbar": (300, 30, 200), "shoulder": (150, 15, 100), "elbow": (100, 10, 80), "wrist": (30, 3, 20),
}
D2R = math.pi / 180.0


# ----------------------------------------------------------------------------- frame helpers
def ue_to_sim(p_cm) -> np.ndarray:
    x, y, z = (float(v) / 100.0 for v in p_cm)
    # (x, -y, z) then rotate +90 deg about Z: (a, b) -> (-b, a)
    a, b = x, -y
    return np.array([-b, a, z])


def unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def quat_from_mat(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> MuJoCo quaternion (w, x, y, z)."""
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def f3(v) -> str:
    return " ".join(f"{float(x):.5f}" for x in v)


def angle_between(a, b) -> float:
    return math.degrees(math.acos(np.clip(np.dot(unit(a), unit(b)), -1, 1)))


# ----------------------------------------------------------------------------- build
def main() -> None:
    bones = {b["name"]: b for b in json.load(open(SHARED / "mannequin_bones.json", encoding="utf-8"))["bones"]}
    P = {n: ue_to_sim(b["component_space"]["pos_cm"]) for n, b in bones.items()}

    # Convenience positions
    pelvis = P["pelvis"]
    lumbar = P["spine_02"]
    chest_top = P["spine_05"]
    neck = P["neck_01"]
    head = P["head"]

    joints: list[dict] = []     # ordered joint spec rows for humanoid_spec.json
    actuators: list[str] = []

    def hinge(name, group, axis, lo, hi, nominal, offset_deg=0.0) -> str:
        """Add a hinge joint. lo/hi/nominal are anatomical degrees; offset_deg is the
        anatomical angle already present in the reference pose, so the joint range
        stored in the model is shifted by -offset."""
        lo_m, hi_m, nom_m = lo - offset_deg, hi - offset_deg, nominal - offset_deg
        kp, kv, tq = GAINS[group]
        joints.append(dict(name=name, group=group, axis=[float(a) for a in axis],
                           range_deg=[lo_m, hi_m], nominal_deg=nom_m, anatomical_offset_deg=offset_deg,
                           kp=kp, kv=kv, torque=tq))
        actuators.append(
            f'    <position name="{name}" joint="{name}" kp="{kp}" kv="{kv}" '
            f'ctrlrange="{lo_m * D2R:.4f} {hi_m * D2R:.4f}" forcerange="{-tq} {tq}"/>'
        )
        return (f'<joint name="{name}" axis="{f3(axis)}" range="{lo_m:.2f} {hi_m:.2f}"/>')

    def capsule(name, a, b, r, mass, origin) -> str:
        return (f'<geom name="{name}" type="capsule" fromto="{f3(a - origin)} {f3(b - origin)}" '
                f'size="{r}" mass="{mass}"/>')

    # ---- arms (computed per side so axes follow the A-pose geometry) --------
    def arm(side: str) -> tuple[str, dict]:
        s = side
        sgn = 1.0 if s == "l" else -1.0           # left = +Y
        sh, el, wr = P[f"upperarm_{s}"], P[f"lowerarm_{s}"], P[f"hand_{s}"]
        fingertip = P[f"middle_03_{s}"]
        u, f = wr - sh, wr - el                   # placeholders, refined below
        u = el - sh                                # upper arm direction
        f = wr - el                                # forearm direction
        elbow_axis = unit(np.cross(f, u))          # positive = flexion (hand toward shoulder)
        elbow_now = angle_between(u, f)            # flexion already in the A-pose
        abd_now = angle_between(u, [0, 0, -1])     # abduction already in the A-pose
        hand_dir = unit(fingertip - wr)
        palm_n = unit(np.cross(elbow_axis, f))     # roughly the palm normal
        wrist_dev_axis = palm_n
        # palm box frame: x along hand, y along elbow axis, z = palm normal
        Rm = np.column_stack([hand_dir, unit(np.cross(palm_n, hand_dir)), palm_n])
        palm_q = quat_from_mat(Rm)
        palm_c = wr + 0.07 * hand_dir

        j_pitch = hinge(f"shoulder_pitch_{s}", "shoulder", [0, -1, 0], -60, 180, 15)
        j_abd = hinge(f"shoulder_abd_{s}", "shoulder", [sgn, 0, 0], -30, 150, 10, offset_deg=abd_now)
        j_rot = hinge(f"shoulder_rot_{s}", "shoulder", [0, 0, sgn], -90, 90, 0)
        j_elb = hinge(f"elbow_{s}", "elbow", elbow_axis, 0, 145, 30, offset_deg=elbow_now)
        j_wf = hinge(f"wrist_flex_{s}", "wrist", elbow_axis, -70, 80, 0)
        j_wd = hinge(f"wrist_dev_{s}", "wrist", wrist_dev_axis, -25, 25, 0)

        xml = f"""
        <body name="upperarm_{s}" pos="{f3(sh - chest_top)}">
          {j_pitch}
          {j_abd}
          {j_rot}
          {capsule(f"upperarm_{s}", sh, el, RADIUS["upperarm"], MASS["upperarm"], sh)}
          <body name="lowerarm_{s}" pos="{f3(el - sh)}">
            {j_elb}
            {capsule(f"lowerarm_{s}", el, wr, RADIUS["lowerarm"], MASS["lowerarm"], el)}
            <body name="hand_{s}" pos="{f3(wr - el)}">
              {j_wf}
              {j_wd}
              <geom name="palm_{s}" type="box" pos="{f3(palm_c - wr)}" quat="{f3(palm_q)}" size="0.05 0.045 0.015" mass="{MASS["hand"]}"/>
              <site name="palm_{s}" pos="{f3(palm_c - wr + 0.015 * palm_n)}" size="0.01" rgba="0 0 1 0.5"/>
            </body>
          </body>
        </body>"""
        info = dict(elbow_now=elbow_now, abd_now=abd_now)
        return xml, info

    # ---- legs ---------------------------------------------------------------
    def leg(side: str) -> tuple[str, dict]:
        s = side
        sgn = 1.0 if s == "l" else -1.0
        hp, kn, an, toe = P[f"thigh_{s}"], P[f"calf_{s}"], P[f"foot_{s}"], P[f"ball_{s}"]
        t, c = kn - hp, an - kn
        knee_now = angle_between(t, c)
        foot_dir = unit([toe[0] - an[0], toe[1] - an[1], 0.0])
        yaw = math.atan2(foot_dir[1], foot_dir[0])
        foot_q = np.array([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)])
        heel_back, toe_fwd = 0.05, 0.22            # metres from ankle along foot_dir
        half_len = (heel_back + toe_fwd) / 2
        foot_c = an * np.array([1, 1, 0]) + foot_dir * (toe_fwd - heel_back) / 2 + np.array([0, 0, 0.025])

        j_hf = hinge(f"hip_flex_{s}", "hip", [0, -1, 0], -30, 120, 15)
        j_ha = hinge(f"hip_abd_{s}", "hip", [sgn, 0, 0], -15, 45, 5)   # adduction capped where the other leg blocks it
        j_hr = hinge(f"hip_rot_{s}", "hip", [0, 0, sgn], -40, 40, 0)
        j_kn = hinge(f"knee_{s}", "knee", [0, 1, 0], 0, 150, 25, offset_deg=knee_now)
        j_ap = hinge(f"ankle_pitch_{s}", "ankle", [0, -1, 0], -45, 25, 10)   # + = dorsiflexion
        j_ar = hinge(f"ankle_roll_{s}", "ankle", [1, 0, 0], -25, 25, 0)

        corners = []
        for i, (dx, dy) in enumerate([(-heel_back, -0.045), (-heel_back, 0.045), (toe_fwd, -0.045), (toe_fwd, 0.045)]):
            R = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
            cp = an * np.array([1, 1, 0]) + R @ np.array([dx, dy, 0.0]) - an
            corners.append(f'<site name="foot_{s}_c{i}" pos="{f3(cp)}" size="0.005" rgba="1 1 0 0.5"/>')

        xml = f"""
      <body name="thigh_{s}" pos="{f3(hp - pelvis)}">
        {j_hf}
        {j_ha}
        {j_hr}
        {capsule(f"thigh_{s}", hp, kn, RADIUS["thigh"], MASS["thigh"], hp)}
        <body name="calf_{s}" pos="{f3(kn - hp)}">
          {j_kn}
          {capsule(f"calf_{s}", kn, an, RADIUS["calf"], MASS["calf"], kn)}
          <body name="foot_{s}" pos="{f3(an - kn)}">
            {j_ap}
            {j_ar}
            <geom name="foot_{s}" type="box" pos="{f3(foot_c - an)}" quat="{f3(foot_q)}" size="{half_len:.4f} 0.045 0.025" mass="{MASS["foot"]}"/>
            {" ".join(corners)}
          </body>
        </body>
      </body>"""
        return xml, dict(knee_now=knee_now, foot_yaw_deg=math.degrees(yaw))

    arm_l, arm_l_info = arm("l")
    arm_r, arm_r_info = arm("r")
    leg_l, leg_l_info = leg("l")
    leg_r, leg_r_info = leg("r")

    # Lumbar joints (torso body sits at spine_02)
    j_lf = hinge("lumbar_flex", "lumbar", [0, 1, 0], -20, 60, 5)
    j_ll = hinge("lumbar_lat", "lumbar", [1, 0, 0], -30, 30, 0)
    j_lt = hinge("lumbar_twist", "lumbar", [0, 0, 1], -40, 40, 0)

    pelvis_box_c = pelvis + np.array([0.0, 0.0, 0.02])
    head_c = head + np.array([0.0, 0.0, 0.09])

    humanoid = f"""<!-- GENERATED by tools/build_humanoid.py from shared/mannequin_bones.json. Edit the script, not this file. -->
<mujoco model="streetball_humanoid">
  <compiler angle="degree" autolimits="true"/>
  <default>
    <default class="humanoid">
      <!-- contype=1 / conaffinity=1: collides with the court, the ball AND itself. MuJoCo's default
           filterparent flag removes parent-child pairs (and welded bodies count as their parent), so only
           NON-ADJACENT parts collide (UU_AGENT section 2). Explicit excludes below cover pairs that
           overlap in the reference pose. -->
      <geom contype="1" conaffinity="1" condim="3" friction="0.9 0.01 0.002" solref="0.006 1" solimp="0.95 0.99 0.001" rgba="0.75 0.75 0.78 1"/>
      <joint type="hinge" armature="0.01" damping="0.5" limited="true"/>
      <site size="0.01" group="4"/>
    </default>
  </default>

  <worldbody>
    <body name="pelvis" pos="{f3(pelvis)}" childclass="humanoid">
      <freejoint name="root"/>
      <site name="pelvis" pos="0 0 0"/>
      <geom name="pelvis" type="box" pos="{f3(pelvis_box_c - pelvis)}" size="0.10 0.14 0.08" mass="{MASS["pelvis"]}"/>
      <body name="torso" pos="{f3(lumbar - pelvis)}">
        {j_lf}
        {j_ll}
        {j_lt}
        {capsule("torso", lumbar + np.array([0, 0, 0.06]), chest_top, RADIUS["torso"], MASS["torso"], lumbar)}
        <body name="head" pos="{f3(neck - lumbar)}">
          <geom name="head" type="sphere" pos="{f3(head_c - neck)}" size="{RADIUS["head"]}" mass="{MASS["head"]}"/>
          <site name="head" pos="{f3(head_c - neck)}"/>
        </body>
        <body name="chest_anchor" pos="{f3(chest_top - lumbar)}">{arm_l}{arm_r}
        </body>
      </body>{leg_l}{leg_r}
    </body>
  </worldbody>

  <contact>
    <!-- Non-adjacent pairs that touch or overlap in the A-pose; everything else self-collides. -->
    <exclude body1="pelvis" body2="calf_l"/>
    <exclude body1="pelvis" body2="calf_r"/>
    <exclude body1="torso" body2="lowerarm_l"/>
    <exclude body1="torso" body2="lowerarm_r"/>
    <exclude body1="pelvis" body2="hand_l"/>
    <exclude body1="pelvis" body2="hand_r"/>
  </contact>

  <actuator>
{chr(10).join(actuators)}
  </actuator>

  <sensor>
    <framequat name="pelvis_quat" objtype="site" objname="pelvis"/>
    <velocimeter name="pelvis_linvel" site="pelvis"/>
    <gyro name="pelvis_angvel" site="pelvis"/>
  </sensor>
</mujoco>
"""
    # chest_anchor is a massless, jointless body -> MuJoCo welds it to torso. Give it a tiny mass to avoid warnings.
    humanoid = humanoid.replace('<body name="chest_anchor"', '<body name="chest_anchor"').replace(
        f'<body name="chest_anchor" pos="{f3(chest_top - lumbar)}">',
        f'<body name="chest_anchor" pos="{f3(chest_top - lumbar)}"><inertial pos="0 0 0" mass="0.001" diaginertia="1e-6 1e-6 1e-6"/>',
    )

    scene = """<!-- GENERATED by tools/build_humanoid.py -->
<mujoco model="streetball_scene">
  <option timestep="0.002" integrator="implicitfast" solver="Newton" iterations="8" ls_iterations="10" cone="elliptic" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="1280" offheight="720"/>
    <quality shadowsize="4096"/>
    <map znear="0.05"/>
  </visual>
  <statistic center="0 0 1" extent="4"/>
  <include file="court.xml"/>
  <include file="humanoid.xml"/>
</mujoco>
"""

    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "humanoid.xml").write_text(humanoid, encoding="utf-8")
    (ASSETS / "scene.xml").write_text(scene, encoding="utf-8")

    # ---- nominal "stand" keyframe: joints at nominal, root lowered so the lowest foot corner is on the floor
    import mujoco  # local import keeps the builder importable without a compiled model

    m = mujoco.MjModel.from_xml_path(str(ASSETS / "scene.xml"))
    d = mujoco.MjData(m)
    mujoco.mj_resetData(m, d)
    for j in joints:
        jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, j["name"])
        d.qpos[m.jnt_qposadr[jid]] = j["nominal_deg"] * D2R
    mujoco.mj_forward(m, d)
    foot_sites = [i for i in range(m.nsite) if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SITE, i) or "").startswith("foot_")]
    zmin = min(d.site_xpos[i][2] for i in foot_sites)
    root_adr = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "root")]
    d.qpos[root_adr + 2] -= zmin
    ball_adr = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "ball")]
    d.qpos[ball_adr:ball_adr + 3] = [0.45, -0.35, 0.1205]        # resting by the right hand
    d.qpos[ball_adr + 3:ball_adr + 7] = [1, 0, 0, 0]
    ctrl = [j["nominal_deg"] * D2R for j in joints]
    qs = " ".join(f"{v:.5f}" for v in d.qpos)
    cs = " ".join(f"{v:.5f}" for v in ctrl)
    nl = chr(10)
    key = f'  <keyframe>{nl}    <key name="stand" qpos="{qs}" ctrl="{cs}"/>{nl}  </keyframe>{nl}'
    scene = scene.replace("</mujoco>", key + "</mujoco>")
    (ASSETS / "scene.xml").write_text(scene, encoding="utf-8")
    spec_nominal_root_z = float(d.qpos[root_adr + 2])

    # ---- spec JSON (single source of truth for obs.py and the UE plugin) ----
    body_bone_map = {
        "pelvis": {"bones": ["pelvis"], "rule": "position+rotation"},
        "torso": {"anchor": "spine_02", "bones": ["spine_01", "spine_02", "spine_03"], "rule": "lumbar slerp 1/3, 2/3, 1; spine_04, spine_05, clavicle_l, clavicle_r rigid"},
        "head": {"bones": ["neck_01", "neck_02", "head"], "rule": "rigid with torso"},
        "upperarm_l": {"bones": ["upperarm_l"], "rule": "rotation"}, "upperarm_r": {"bones": ["upperarm_r"], "rule": "rotation"},
        "lowerarm_l": {"bones": ["lowerarm_l"], "rule": "rotation"}, "lowerarm_r": {"bones": ["lowerarm_r"], "rule": "rotation"},
        "hand_l": {"bones": ["hand_l"], "rule": "rotation; fingers fixed"}, "hand_r": {"bones": ["hand_r"], "rule": "rotation; fingers fixed"},
        "thigh_l": {"bones": ["thigh_l"], "rule": "rotation"}, "thigh_r": {"bones": ["thigh_r"], "rule": "rotation"},
        "calf_l": {"bones": ["calf_l"], "rule": "rotation"}, "calf_r": {"bones": ["calf_r"], "rule": "rotation"},
        "foot_l": {"bones": ["foot_l", "ball_l"], "rule": "rotation"}, "foot_r": {"bones": ["foot_r", "ball_r"], "rule": "rotation"},
    }
    spec = {
        "generated_from": "shared/mannequin_bones.json",
        "frame": {
            "sim": "metres, right-handed, Z-up, character faces +X at qpos=0, +Y is character left",
            "ue_from_sim": "pos_ue = (x*100, -y*100, z*100); quat_ue(X,Y,Z,W) = (-qx, qy, -qz, qw)",
            "ue_mesh_from_ue_sim": "mesh faces +Y in mesh space; sim faces +X; the UE bone mapper captures per-bone offsets at init so no manual yaw is needed",
        },
        "timestep": 0.002,
        "control_dt": 0.02,
        "nominal_root_height_m": spec_nominal_root_z,
        "n_joints": len(joints),
        "joints": joints,
        "reference_pose_info": {
            "elbow_flexion_in_ref_pose_deg": {"l": arm_l_info["elbow_now"], "r": arm_r_info["elbow_now"]},
            "shoulder_abduction_in_ref_pose_deg": {"l": arm_l_info["abd_now"], "r": arm_r_info["abd_now"]},
            "knee_flexion_in_ref_pose_deg": {"l": leg_l_info["knee_now"], "r": leg_r_info["knee_now"]},
            "foot_yaw_deg": {"l": leg_l_info["foot_yaw_deg"], "r": leg_r_info["foot_yaw_deg"]},
        },
        "body_bone_map": body_bone_map,
        "masses_kg": MASS,
    }
    SHARED.mkdir(parents=True, exist_ok=True)
    (SHARED / "humanoid_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"wrote {ASSETS / 'humanoid.xml'}, {ASSETS / 'scene.xml'}, {SHARED / 'humanoid_spec.json'}")
    print(f"{len(joints)} actuated joints; ref-pose offsets: elbow {arm_l_info['elbow_now']:.1f} deg, "
          f"shoulder abd {arm_l_info['abd_now']:.1f} deg, knee {leg_l_info['knee_now']:.1f} deg, foot yaw {leg_l_info['foot_yaw_deg']:.1f} deg")


if __name__ == "__main__":
    main()
