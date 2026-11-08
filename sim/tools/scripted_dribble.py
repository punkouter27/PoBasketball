"""Scripted hand-ball dribble reference (2026-11-08, dribble approach #5).

A state-based controller drives the ACTIVE arm to a palm target computed only from quantities the policy
also observes (ball position/velocity relative to the pelvis, palm distance), via damped least-squares IK on
the arm joints. Legs/torso come from the production balance policy. Purpose:
  1. feasibility: prove the humanoid + ball physics allow a sustained hand dribble at the target apex;
  2. teacher: its actions are imitated by the dribble policy (tools/bc_dribble.py), then refined with PPO.

    uv run python tools/scripted_dribble.py [--seconds 20] [--render out.mp4|frames_dir] [--hand 1]
"""
from __future__ import annotations

import argparse
import pathlib

import mujoco
import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from streetball import obs as obs_spec          # noqa: E402
from streetball.ppo import Actor                # noqa: E402

ARM = {1: list(range(6, 12)) + [24], -1: list(range(0, 6)) + [24]}   # active arm + lumbar_flex (lean to reach)
HAND_OFFSET = [0.45, 0.30]                             # dribble spot: forward, lateral (clear of the foot; --spot)


class ArmTeacher:
    """Palm target from ball state -> arm joint targets (IK). Parameters are tuned by --sweep."""

    def __init__(self, m: mujoco.MjModel, ix: obs_spec.ObsIndex, hand: int = 1,
                 hold_z=1.00, push_depth=0.40, catch_r=0.20, steer=0.6, lead=0.06, push_v=3.0, align=0.10, damp=0.04, gain=0.3, orient_w=0.3, rest_w=0.05, lean=0.1, stroke_t=0.1, gap=0.08, max_step=0.10):
        self.m, self.ix, self.hand = m, ix, hand
        self.site = ix.palm_r if hand > 0 else ix.palm_l
        self.joints = ARM[hand]
        self.dofs = [int(ix.vadr[j]) for j in self.joints]
        self.hold_z, self.push_depth, self.catch_r, self.steer, self.lead, self.push_v = hold_z, push_depth, catch_r, steer, lead, push_v
        self.align, self.damp, self.gain, self.orient_w = align, damp, gain, orient_w
        self.rest_w, self.lean, self.stroke_t, self.gap = rest_w, lean, stroke_t, gap
        self.max_step = max_step
        # relaxed dribble arm (shoulder pitch, abd, rot, elbow, wrist flex, dev), mirrored for the left arm
        self.q_rest = np.array([0.55, -0.45, 0.3, 0.25, -0.7, 0.0, self.lean])
        self.jac = np.zeros((3, m.nv))
        self.pushing = False

    def spot(self, d) -> np.ndarray:
        H = obs_spec.heading_mat(d.qpos[self.ix.root_q + 3:self.ix.root_q + 7])
        p = d.qpos[self.ix.root_q:self.ix.root_q + 3]
        return p[:2] + HAND_OFFSET[0] * H[:2, 0] - self.hand * HAND_OFFSET[1] * H[:2, 1]

    def target(self, d) -> np.ndarray:
        ix = self.ix
        b = d.qpos[ix.ball_q:ix.ball_q + 3]
        vb = d.qvel[ix.ball_v:ix.ball_v + 3]
        palm = d.site_xpos[self.site]
        spot = self.spot(d)
        dist = np.linalg.norm(palm - b)
        apex_pred = b[2] + max(vb[2], 0.0) ** 2 / (2 * 9.81)
        t_apex = max(vb[2], 0.0) / 9.81
        over = np.linalg.norm(palm[:2] - b[:2]) < self.align and palm[2] > b[2]
        # STROKE: start the downward slap shortly before the ball peaks, so the palm is already moving down
        # at contact (a ball needs ~2.8 m/s downward at 0.75 m to come back to ~0.9 m after the floor).
        if not self.pushing and b[2] > 0.4 and (vb[2] > 0 and t_apex < self.stroke_t or dist < self.catch_r) and over:
            self.pushing = True
        if self.pushing and (vb[2] < -self.push_v or b[2] < 0.45):
            self.pushing = False
        dv = (spot - b[:2]) / 0.6 - vb[:2]
        if self.pushing:
            # A downward push from a palm offset by +d (horizontally) sends the ball toward -d: to change the
            # ball's horizontal velocity by dv (back to the spot, cancelling drift) the palm sits at b - k*dv.
            xy = b[:2] - self.damp * dv
            z = b[2] + 0.12 - self.push_depth              # drive through the top of the ball
        else:
            xy = b[:2] + vb[:2] * self.lead
            # wait a little above where the ball top will peak (capped), leaving room to accelerate down
            z = float(np.clip(apex_pred + 0.12 + self.gap, 0.6, self.hold_z)) if vb[2] > 0 else self.hold_z
        return np.array([xy[0], xy[1], z])

    def action(self, d, a: np.ndarray) -> np.ndarray:
        """Overwrite the arm entries of action vector a (in place): absolute IK solution for the palm target
        (iterated on a scratch copy of the state) plus gravity compensation (qfrc_bias / kp) so the PD
        servo actually arrives there instead of sagging."""
        ix, m = self.ix, self.m
        tgt = self.target(d)
        # straight-line palm motion: never ask the IK for a point more than max_step from the palm (absolute
        # targets out of reach made it pick postures that swung the hand the wrong way first)
        step = tgt - d.site_xpos[self.site]
        n = np.linalg.norm(step)
        if n > self.max_step:
            tgt = d.site_xpos[self.site] + step * (self.max_step / n)
        if not hasattr(self, "scratch"):
            self.scratch = mujoco.MjData(m)
            self.qa = [int(ix.qadr[j]) for j in self.joints]
            self.kp = np.array([m.actuator_gainprm[k, 0] for k in self.joints])
        sd = self.scratch
        sd.qpos[:] = d.qpos
        lo, hi = ix.lo[self.joints], ix.hi[self.joints]
        if not hasattr(self, "geom"):
            self.geom = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "palm_r" if self.hand > 0 else "palm_l")
            self.gbody = int(m.geom_bodyid[self.geom])
            self.jacr = np.zeros((3, m.nv))
        for _ in range(15):
            mujoco.mj_kinematics(m, sd)
            mujoco.mj_comPos(m, sd)
            ep = tgt - sd.site_xpos[self.site]
            # palm face level: the box's thin axis (either sign) should point straight down/up
            n = sd.geom_xmat[self.geom].reshape(3, 3)[:, 2]
            n = n if n[2] < 0 else -n
            er = np.cross(n, np.array([0.0, 0.0, -1.0]))
            if np.linalg.norm(ep) < 0.005 and np.linalg.norm(er) < 0.05:
                break
            mujoco.mj_jacSite(m, sd, self.jac, None, self.site)
            mujoco.mj_jacBody(m, sd, None, self.jacr, self.gbody)
            w = self.orient_w
            J = np.vstack([self.jac[:, self.dofs], w * self.jacr[:, self.dofs]])
            e = np.concatenate([ep, w * er])
            # damped least squares with a pull toward the relaxed dribble posture (picks one IK branch)
            mu = self.rest_w
            A = J.T @ J + (0.02 + mu) * np.eye(len(self.dofs))
            dq = np.linalg.solve(A, J.T @ e + mu * (self.q_rest - sd.qpos[self.qa]))
            sd.qpos[self.qa] = np.clip(sd.qpos[self.qa] + np.clip(dq, -0.3, 0.3), lo, hi)
        q_star = sd.qpos[self.qa].copy()
        self.q_prev = q_star
        self.ik_err = float(np.linalg.norm(ep)); self.q_err = float(np.abs(q_star - d.qpos[self.qa]).max())
        q_now = d.qpos[self.qa]
        # gravity compensation + a lead term so the servo gets there within ~0.1 s
        q_cmd = q_star + self.gain * (q_star - q_now) + d.qfrc_bias[self.dofs] / self.kp
        nom, half = ix.nominal[self.joints], 0.5 * (ix.hi - ix.lo)[self.joints]
        a[self.joints] = np.clip((np.clip(q_cmd, lo, hi) - nom) / half, -1, 1)
        return a


def load_actor(path: pathlib.Path) -> Actor:
    sd = torch.load(path, map_location="cpu", weights_only=False)
    act = Actor(obs_spec.N_OBS, obs_spec.N_JOINTS)
    act.load_state_dict({k[len("actor."):]: v for k, v in sd["ac"].items() if k.startswith("actor.")})
    return act.eval()


def palm_ball(m, d, ix, palm_geom, ball_geom) -> bool:
    for c in range(d.ncon):
        g = (d.contact[c].geom1, d.contact[c].geom2)
        if ball_geom in g and palm_geom in g:
            return True
    return False


BASE = ROOT / "runs" / "l2a_dribble_r_r5q1" / "model.pt"   # legs/torso: last dribble policy (stands with a ball; 0 % falls)


def run(seconds=20.0, hand=1, seed=0, render=None, quiet=False, base=None, trace=False, **kw) -> dict:
    m = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "stand"))
    ix = obs_spec.ObsIndex(m)
    teacher = ArmTeacher(m, ix, hand, **kw)
    mujoco.mj_forward(m, d)
    rng = np.random.default_rng(seed)
    sp = teacher.spot(d)
    h = 0.4 + 0.3 * rng.random()                        # as L2Dribble.on_reset: mid-cycle, apex 1.0 m
    d.qpos[ix.ball_q:ix.ball_q + 3] = [sp[0], sp[1], h]
    d.qvel[ix.ball_v:ix.ball_v + 3] = [0, 0, np.sqrt(2 * 9.81 * (1.0 - h)) * (1 if rng.random() < 0.5 else -1)]
    mujoco.mj_forward(m, d)
    actor = load_actor(pathlib.Path(base) if base else BASE)
    ball_g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "ball")
    palm_g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "palm_r" if hand > 0 else "palm_l")
    floor_g = ix.floor_geom
    prev_a = np.zeros(obs_spec.N_JOINTS)
    task = np.zeros(obs_spec.N_TASK); task[0] = hand; task[1] = 1.0
    sub = int(round(0.02 / m.opt.timestep))
    stats = {"bounces": 0, "apexes": [], "touch_steps": 0, "steps": 0, "touched_cycles": 0, "fell": False, "lost": False}
    apex, on_floor, touched = 0.0, False, False
    frames, r = [], None
    if render:
        r = mujoco.Renderer(m, 480, 640)
        cam = mujoco.MjvCamera(); cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.azimuth, cam.elevation, cam.distance = 150, -12, 3.0
    for t in range(int(seconds / 0.02)):
        o = obs_spec.compute_obs(m, d, ix, prev_a, task, 1.0, 1.0)
        o[98 if hand > 0 else 97] = np.linalg.norm(d.site_xpos[teacher.site] - d.qpos[ix.ball_q:ix.ball_q + 3])
        with torch.no_grad():
            a = actor(torch.as_tensor(o, dtype=torch.float32)[None])[0].numpy().astype(np.float64)
        a = teacher.action(d, a)
        d.ctrl[:] = ix.action_to_ctrl(a)
        for _ in range(sub):
            mujoco.mj_step(m, d)
        prev_a = a
        if trace:
            print(t, 'ball', np.round(d.qpos[ix.ball_q:ix.ball_q + 3], 2), 'vb', np.round(d.qvel[ix.ball_v:ix.ball_v + 3], 2),
                  'palm', np.round(d.site_xpos[teacher.site], 2), 'tgt', np.round(teacher.target(d), 2), 'push', teacher.pushing, 'pel', np.round(d.qpos[ix.root_q:ix.root_q + 3], 2), 'spot', np.round(teacher.spot(d), 2), 'ik', round(teacher.ik_err, 3), 'qerr', round(teacher.q_err, 2), 'q', np.round(d.qpos[teacher.qa], 2))
        stats["steps"] += 1
        bz = d.qpos[ix.ball_q + 2]
        apex = max(apex, bz)
        tp = palm_ball(m, d, ix, palm_g, ball_g)
        stats["touch_steps"] += tp
        touched |= tp
        fl = any(floor_g in (d.contact[c].geom1, d.contact[c].geom2) and ball_g in (d.contact[c].geom1, d.contact[c].geom2) for c in range(d.ncon))
        if fl and not on_floor:
            stats["bounces"] += 1
            stats["apexes"].append(apex)
            stats["touched_cycles"] += touched
            apex, touched = bz, False
        on_floor = fl
        pel = d.qpos[ix.root_q:ix.root_q + 3]
        if pel[2] < 0.55:
            stats["fell"] = True; break
        if np.linalg.norm(d.qpos[ix.ball_q:ix.ball_q + 2] - pel[:2]) > 1.5:
            stats["lost"] = True; break
        if r is not None and t % 2 == 0:
            cam.lookat[:] = [pel[0], pel[1], 0.8]
            r.update_scene(d, camera=cam)
            frames.append(r.render().copy())
    stats["seconds"] = stats["steps"] * 0.02
    ap = np.array(stats["apexes"][1:]) if len(stats["apexes"]) > 1 else np.array([0.0])
    stats["apex_mean"] = float(ap.mean())
    stats["apex_in_band"] = float(((ap >= 0.8) & (ap <= 1.15)).mean())
    stats["touch_frac"] = stats["touch_steps"] / max(1, stats["steps"])
    if not quiet:
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items() if k != "apexes"},
              "apexes", np.round(stats["apexes"][:12], 2))
    if render and frames:
        out = pathlib.Path(render)
        from PIL import Image
        sel = frames[::max(1, len(frames) // 12)][:12]
        rows = [np.concatenate(sel[i:i + 4], axis=1) for i in range(0, len(sel) - len(sel) % 4, 4)]
        Image.fromarray(np.concatenate(rows, axis=0)).save(out)
        print("wrote", out)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--hand", type=int, default=1)
    ap.add_argument("--render", default=None)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--spot", default="0.45,0.30")
    ap.add_argument("--base", default=None)
    ap.add_argument("--trace", action="store_true")
    a = ap.parse_args()
    HAND_OFFSET[:] = [float(x) for x in a.spot.split(",")]
    if a.sweep:
        best = None
        for hold in (0.9, 1.0, 1.1):
            for depth in (0.3, 0.45, 0.6):
                for cr in (0.16, 0.22):
                    s = run(a.seconds, a.hand, quiet=True, hold_z=hold, push_depth=depth, catch_r=cr)
                    score = s["bounces"] * s["apex_in_band"] * (s["touched_cycles"] / max(1, s["bounces"])) + s["seconds"] / 100
                    print(f"hold {hold} depth {depth} catch {cr}: {s['seconds']:.1f}s bounces {s['bounces']} touched {s['touched_cycles']} "
                          f"apex {s['apex_mean']:.2f} band {s['apex_in_band']:.2f} fell {s['fell']} lost {s['lost']}")
                    if best is None or score > best[0]:
                        best = (score, hold, depth, cr)
        print("best", best)
    else:
        run(a.seconds, a.hand, render=a.render, base=a.base, trace=a.trace)


if __name__ == "__main__":
    main()
