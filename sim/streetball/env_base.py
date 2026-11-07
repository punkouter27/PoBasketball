"""C1/C2: vectorised Streetball environment on MuJoCo Warp with per-world domain randomisation.

One `StreetballEnv` holds N worlds of `assets/scene.xml`. The physics runs as a
CUDA graph of 10 substeps (500 Hz) per 50 Hz control step. Observations are built
in torch from zero-copy views of the Warp arrays, slot-for-slot identical to
`streetball/obs.py` (verified by tests/test_env_obs_parity.py).

Level-specific behaviour (task block, reward, termination, reset placement) lives
in `streetball/levels/*.py` behind the `Level` interface in `levels/base.py`.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

import mujoco
import mujoco_warp as mjw
import numpy as np
import torch
import warp as wp

from streetball import obs as obs_spec
from streetball.levels.base import Level

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"


@dataclass
class RandomizationConfig:
    """Blueprint C.1 domain randomisation. All ranges are multiplicative unless noted."""
    enabled: bool = True
    body_mass: tuple[float, float] = (0.9, 1.1)
    floor_friction: tuple[float, float] = (0.6, 1.1)          # absolute sliding friction
    motor_kp: tuple[float, float] = (0.9, 1.1)
    ball_mass: tuple[float, float] = (0.95, 1.05)
    ball_restitution: tuple[float, float] = (0.9, 1.1)        # scales contact damping (lower = bouncier)
    action_latency_prob: float = 0.5                          # per episode: one control step of delay
    push_force: tuple[float, float] = (0.0, 150.0)            # N, horizontal, random direction
    push_duration_s: float = 0.2
    push_interval_s: tuple[float, float] = (3.0, 8.0)


@dataclass
class EnvConfig:
    num_envs: int = 4096
    seed: int = 0
    device: str = "cuda:0"
    substeps: int = 10
    episode_s: float = 20.0
    naconmax_per_world: int = 48
    njmax_per_world: int = 160
    randomization: RandomizationConfig = field(default_factory=RandomizationConfig)


class StreetballEnv:
    N_OBS = obs_spec.N_OBS
    N_ACT = obs_spec.N_JOINTS

    def __init__(self, level: Level, cfg: EnvConfig):
        self.cfg = cfg
        self.level = level
        self.N = cfg.num_envs
        self.device = torch.device(cfg.device)
        self.gen = torch.Generator(device=self.device).manual_seed(cfg.seed)
        wp.init()

        # ---- CPU model & reference data
        self.mjm = mujoco.MjModel.from_xml_path(str(ROOT / "assets" / "scene.xml"))
        self.mjd = mujoco.MjData(self.mjm)
        self.key = mujoco.mj_name2id(self.mjm, mujoco.mjtObj.mjOBJ_KEY, "stand")
        mujoco.mj_resetDataKeyframe(self.mjm, self.mjd, self.key)
        mujoco.mj_forward(self.mjm, self.mjd)
        self.ix = obs_spec.ObsIndex(self.mjm)
        self.dt = float(self.mjm.opt.timestep)
        self.control_dt = self.dt * cfg.substeps
        self.max_steps = int(round(level.episode_s / self.control_dt)) if level.episode_s else int(round(cfg.episode_s / self.control_dt))
        spec = json.load(open(SHARED / "humanoid_spec.json", encoding="utf-8"))
        self.nominal_root_z = float(spec["nominal_root_height_m"])

        # ---- GPU model (batched fields for randomisation) & data
        N = self.N
        self.wm = mjw.put_model(self.mjm, batch_sizes={
            "body_mass": N, "body_inertia": N, "geom_friction": N,
            "actuator_gainprm": N, "actuator_biasprm": N, "pair_solref": N,
        })
        # naconmax is a global budget, njmax is PER WORLD (it sizes a dense njmax x njmax block per
        # world, so never pass N * something here).
        self.wd = mjw.put_data(self.mjm, self.mjd, nworld=N,
                               naconmax=N * cfg.naconmax_per_world, njmax=cfg.njmax_per_world)
        self.wm.opt.warn_overflow = 0  # overflow is checked explicitly in step()

        # ---- torch views (zero copy)
        t = wp.to_torch
        self.qpos = t(self.wd.qpos)                 # (N, nq)
        self.qvel = t(self.wd.qvel)                 # (N, nv)
        self.ctrl = t(self.wd.ctrl)                 # (N, nu)
        self.xpos = t(self.wd.xpos)                 # (N, nbody, 3)
        self.xquat = t(self.wd.xquat)               # (N, nbody, 4) wxyz
        self.site_xpos = t(self.wd.site_xpos)       # (N, nsite, 3)
        self.xfrc = t(self.wd.xfrc_applied)         # (N, nbody, 6)
        self.actuator_force = t(self.wd.actuator_force)
        self.con_geom = t(self.wd.contact.geom)     # (naconmax, 2)
        self.con_world = t(self.wd.contact.worldid) # (naconmax,)
        self.nacon = t(self.wd.nacon)               # (1,)
        self.m_body_mass = t(self.wm.body_mass)     # (N, nbody)
        self.m_body_inertia = t(self.wm.body_inertia)  # (N, nbody, 3)
        self.m_geom_friction = t(self.wm.geom_friction)  # (N, ngeom, 3)
        self.m_gainprm = t(self.wm.actuator_gainprm)   # (N, nu, 10)
        self.m_biasprm = t(self.wm.actuator_biasprm)   # (N, nu, 10)
        self.m_pair_solref = t(self.wm.pair_solref)    # (N, npair, 2)
        self.base_body_mass = self.m_body_mass[0].clone()
        self.base_body_inertia = self.m_body_inertia[0].clone()
        self.base_gainprm = self.m_gainprm[0].clone()
        self.base_biasprm = self.m_biasprm[0].clone()
        self.base_pair_solref = self.m_pair_solref[0].clone()

        # ---- indices as tensors
        dev = self.device
        ix = self.ix
        self.qadr = torch.as_tensor(ix.qadr, device=dev)
        self.vadr = torch.as_tensor(ix.vadr, device=dev)
        self.nominal = torch.as_tensor(ix.nominal, device=dev, dtype=torch.float32)
        self.lo = torch.as_tensor(ix.lo, device=dev, dtype=torch.float32)
        self.hi = torch.as_tensor(ix.hi, device=dev, dtype=torch.float32)
        self.half = 0.5 * (self.hi - self.lo)
        self.key_qpos = torch.as_tensor(self.mjm.key_qpos[self.key], device=dev, dtype=torch.float32)
        self.root_q, self.root_v = int(ix.root_q), int(ix.root_v)
        self.ball_q, self.ball_v = int(ix.ball_q), int(ix.ball_v)
        self.pelvis_b, self.ball_b = int(ix.pelvis), int(ix.ball)
        self.palm_l_s, self.palm_r_s = int(ix.palm_l), int(ix.palm_r)
        self.floor_g = int(ix.floor_geom)
        self.foot_g = [int(g) for g in ix.foot_geom]
        self.ball_g = mujoco.mj_name2id(self.mjm, mujoco.mjtObj.mjOBJ_GEOM, "ball")
        self.palm_g = [mujoco.mj_name2id(self.mjm, mujoco.mjtObj.mjOBJ_GEOM, f"palm_{s}") for s in "lr"]
        hum_bodies = set()
        for b in range(self.mjm.nbody):
            r = b
            while r != 0 and r != self.pelvis_b:
                r = self.mjm.body_parentid[r]
            if r == self.pelvis_b:
                hum_bodies.add(b)
        self.hum_geoms = [g for g in range(self.mjm.ngeom) if self.mjm.geom_bodyid[g] in hum_bodies]
        bad = [g for g in self.hum_geoms if g not in self.foot_g and g not in self.palm_g]
        self.bad_floor_mask = torch.zeros(self.mjm.ngeom, dtype=torch.bool, device=dev)
        self.bad_floor_mask[bad] = True
        self.foot_site_idx = torch.as_tensor(
            [mujoco.mj_name2id(self.mjm, mujoco.mjtObj.mjOBJ_SITE, f"foot_{s}_c{i}") for s in "lr" for i in range(4)],
            device=dev)
        self.rim_center = {s: torch.as_tensor(self.mjm.site_pos[mujoco.mj_name2id(self.mjm, mujoco.mjtObj.mjOBJ_SITE, f"rim_center_{s}")],
                                              device=dev, dtype=torch.float32) for s in "ew"}

        # ---- episode state
        z = lambda *s, **k: torch.zeros(*s, device=dev, **k)
        self.obs = z(N, self.N_OBS)
        self.task = z(N, obs_spec.N_TASK)
        self.prev_action = z(N, self.N_ACT)
        self.prev_ctrl = z(N, self.N_ACT)
        self.step_count = z(N, dtype=torch.long)
        self.episode_count = z(N, dtype=torch.long)
        self.in_control = z(N)
        self.last_palm_contact_t = torch.full((N,), -10.0, device=dev)
        self.loose_t = torch.full((N,), -1.0, device=dev)     # time the ball became loose (-1: not loose)
        self.countdown_frac = torch.ones(N, device=dev)
        self.bad_contact_t = z(N)                             # continuous time a non-foot/palm part touches the floor
        self.time = z(N)
        self.foot_contact = z(N, 2)
        self.palm_ball_contact = z(N, 2)
        self.ball_floor_contact = z(N)
        self.fallen = z(N, dtype=torch.bool)
        self.delay_action = z(N, dtype=torch.bool)
        self.push_force = z(N, 3)
        self.push_t_end = z(N)
        self.push_t_next = z(N)
        self.push_scale = 1.0                                 # curriculum knob (0..1)
        self.init_foot_xy = z(N, 2, 2)
        self.ep_return = z(N)
        self.ep_len = z(N)
        self.extras: dict[str, torch.Tensor] = {}

        # ---- CUDA graph for the substeps
        self._graph = None
        self._capture_graph()

        self.level.attach(self)
        self.reset(torch.arange(N, device=dev))

    # ------------------------------------------------------------------ physics
    def _capture_graph(self):
        with wp.ScopedCapture() as cap:
            for _ in range(self.cfg.substeps):
                mjw.step(self.wm, self.wd)
        self._graph = cap.graph

    def _physics(self):
        wp.capture_launch(self._graph)

    def forward(self):
        mjw.forward(self.wm, self.wd)

    # ------------------------------------------------------------------ helpers
    def rand(self, *shape, lo=0.0, hi=1.0):
        return torch.rand(*shape, device=self.device, generator=self.gen) * (hi - lo) + lo

    def randn(self, *shape):
        return torch.randn(*shape, device=self.device, generator=self.gen)

    @staticmethod
    def quat_to_mat(q: torch.Tensor) -> torch.Tensor:
        w, x, y, z = q.unbind(-1)
        return torch.stack([
            torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
            torch.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
            torch.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1),
        ], -2)

    @staticmethod
    def heading_mat(R: torch.Tensor) -> torch.Tensor:
        fwd = R[..., :, 0].clone()
        fwd[..., 2] = 0.0
        n = fwd.norm(dim=-1, keepdim=True)
        fwd = torch.where(n > 1e-6, fwd / n.clamp_min(1e-6), torch.tensor([1.0, 0.0, 0.0], device=fwd.device))
        left = torch.stack([-fwd[..., 1], fwd[..., 0], torch.zeros_like(fwd[..., 0])], -1)
        up = torch.zeros_like(fwd); up[..., 2] = 1.0
        return torch.stack([fwd, left, up], -1)

    @staticmethod
    def yaw_quat(yaw: torch.Tensor) -> torch.Tensor:
        return torch.stack([torch.cos(yaw / 2), torch.zeros_like(yaw), torch.zeros_like(yaw), torch.sin(yaw / 2)], -1)

    # ------------------------------------------------------------------ contacts
    def _scan_contacts(self):
        """Fill foot_contact, palm_ball_contact and bad-floor contact flags from the Warp contact buffer."""
        n = int(self.nacon[0].item())
        N = self.N
        self.foot_contact.zero_()
        self.palm_ball_contact.zero_()
        self.ball_floor_contact.zero_()
        bad = torch.zeros(N, dtype=torch.bool, device=self.device)
        if n > 0:
            g = self.con_geom[:n].long()
            w = self.con_world[:n].long()
            g0, g1 = g[:, 0], g[:, 1]
            floor = (g0 == self.floor_g) | (g1 == self.floor_g)
            other = torch.where(g0 == self.floor_g, g1, g0)
            for k, fg in enumerate(self.foot_g):
                m = floor & (other == fg)
                self.foot_contact[:, k].index_fill_(0, w[m], 1.0)
            bad.index_fill_(0, w[floor & self.bad_floor_mask[other]], True)
            self.ball_floor_contact.index_fill_(0, w[floor & (other == self.ball_g)], 1.0)
            ballc = (g0 == self.ball_g) | (g1 == self.ball_g)
            otherb = torch.where(g0 == self.ball_g, g1, g0)
            for k, pg in enumerate(self.palm_g):
                m = ballc & (otherb == pg)
                self.palm_ball_contact[:, k].index_fill_(0, w[m], 1.0)
        self._bad_floor = bad

    # ------------------------------------------------------------------ obs
    def compute_obs(self):
        """Torch mirror of obs.compute_obs (see obs.py for the slot table)."""
        qpos, qvel = self.qpos, self.qvel
        rq = self.root_q; rv = self.root_v
        q = qpos[:, rq + 3:rq + 7]
        R = self.quat_to_mat(q)                        # (N,3,3) world <- pelvis
        H = self.heading_mat(R)                        # (N,3,3) world <- heading
        p_pelvis = qpos[:, rq:rq + 3]
        v_pelvis = qvel[:, rv:rv + 3]
        w_pelvis = qvel[:, rv + 3:rv + 6]
        o = self.obs
        g = torch.tensor([0.0, 0.0, -1.0], device=self.device)
        o[:, 0:3] = torch.einsum("nji,j->ni", R, g)
        o[:, 3:6] = torch.einsum("nji,nj->ni", R, v_pelvis)
        o[:, 6:9] = 0.25 * w_pelvis
        o[:, 9:36] = qpos[:, self.qadr] - self.nominal
        o[:, 36:63] = 0.1 * qvel[:, self.vadr]
        o[:, 63:90] = self.prev_action
        bq, bv = self.ball_q, self.ball_v
        p_ball = qpos[:, bq:bq + 3]
        v_ball = qvel[:, bv:bv + 3]
        w_ball = qvel[:, bv + 3:bv + 6]
        o[:, 90:93] = torch.einsum("nji,nj->ni", H, p_ball - p_pelvis)
        o[:, 93:96] = 0.5 * torch.einsum("nji,nj->ni", H, v_ball - v_pelvis)
        o[:, 96] = self.in_control
        o[:, 97] = (self.site_xpos[:, self.palm_l_s] - p_ball).norm(dim=-1)
        o[:, 98] = (self.site_xpos[:, self.palm_r_s] - p_ball).norm(dim=-1)
        o[:, 99:101] = self.foot_contact
        o[:, 101] = p_pelvis[:, 2]
        o[:, 102:105] = 0.05 * torch.einsum("nji,nj->ni", H, w_ball)
        o[:, 105] = self.countdown_frac
        o[:, 106] = 0.0
        o[:, 107:119] = self.task
        # cache a few derived quantities for levels
        self.R, self.H = R, H
        self.p_pelvis, self.v_pelvis, self.p_ball, self.v_ball = p_pelvis, v_pelvis, p_ball, v_ball
        return o

    # ------------------------------------------------------------------ ball control bookkeeping
    def _update_ball_state(self):
        touched = self.palm_ball_contact.amax(dim=1) > 0
        self.last_palm_contact_t = torch.where(touched, self.time, self.last_palm_contact_t)
        horiz = (self.p_ball[:, :2] - self.p_pelvis[:, :2]).norm(dim=-1)
        ctrl = (horiz < 0.75) & (self.p_ball[:, 2] < 1.3) & (self.time - self.last_palm_contact_t < 0.6)
        newly_loose = (~ctrl) & (self.in_control > 0.5)
        self.loose_t = torch.where(newly_loose, self.time, self.loose_t)
        self.loose_t = torch.where(ctrl, torch.full_like(self.loose_t, -1.0), self.loose_t)
        self.in_control = ctrl.float()
        loose = self.loose_t >= 0
        self.countdown_frac = torch.where(loose, (1.0 - (self.time - self.loose_t) / 3.0).clamp(0, 1), torch.ones_like(self.countdown_frac))

    # ------------------------------------------------------------------ randomisation
    def _randomize_model(self, ids: torch.Tensor):
        rc = self.cfg.randomization
        if not rc.enabled:
            return
        k = ids.numel()
        f = self.rand(k, 1, lo=rc.body_mass[0], hi=rc.body_mass[1])
        self.m_body_mass[ids] = self.base_body_mass[None] * f
        self.m_body_inertia[ids] = self.base_body_inertia[None] * f[..., None]
        fb = self.rand(k, lo=rc.ball_mass[0], hi=rc.ball_mass[1])
        self.m_body_mass[ids, self.ball_b] = self.base_body_mass[self.ball_b] * fb
        self.m_body_inertia[ids, self.ball_b] = self.base_body_inertia[self.ball_b][None] * fb[:, None]
        mu = self.rand(k, lo=rc.floor_friction[0], hi=rc.floor_friction[1])
        self.m_geom_friction[ids, self.floor_g, 0] = mu
        fk = self.rand(k, 1, lo=rc.motor_kp[0], hi=rc.motor_kp[1])
        gp = self.base_gainprm[None].repeat(k, 1, 1); bp = self.base_biasprm[None].repeat(k, 1, 1)
        gp[..., 0] *= fk; bp[..., 1] *= fk
        self.m_gainprm[ids] = gp; self.m_biasprm[ids] = bp
        fr = self.rand(k, lo=rc.ball_restitution[0], hi=rc.ball_restitution[1])
        ps = self.base_pair_solref[None].repeat(k, 1, 1)
        ps[:, 0, 1] *= fr
        self.m_pair_solref[ids] = ps
        self.delay_action[ids] = self.rand(k) < rc.action_latency_prob

    def _schedule_push(self, ids: torch.Tensor):
        rc = self.cfg.randomization
        self.push_t_next[ids] = self.time[ids] + self.rand(ids.numel(), lo=rc.push_interval_s[0], hi=rc.push_interval_s[1])
        self.push_t_end[ids] = -1.0
        self.push_force[ids] = 0.0

    def _apply_pushes(self):
        rc = self.cfg.randomization
        if not rc.enabled:
            return
        start = self.time >= self.push_t_next
        if start.any():
            ids = start.nonzero(as_tuple=False).squeeze(-1)
            k = ids.numel()
            ang = self.rand(k, lo=0.0, hi=2 * np.pi)
            mag = self.rand(k, lo=rc.push_force[0], hi=rc.push_force[1]) * self.push_scale
            self.push_force[ids] = torch.stack([mag * torch.cos(ang), mag * torch.sin(ang), torch.zeros_like(mag)], -1)
            self.push_t_end[ids] = self.time[ids] + rc.push_duration_s
            self.push_t_next[ids] = self.time[ids] + self.rand(k, lo=rc.push_interval_s[0], hi=rc.push_interval_s[1])
        active = (self.time < self.push_t_end).float()[:, None]
        self.xfrc[:, self.pelvis_b, :3] = self.push_force * active

    # ------------------------------------------------------------------ reset / step
    def reset(self, ids: torch.Tensor):
        if ids.numel() == 0:
            return
        k = ids.numel()
        self.qpos[ids] = self.key_qpos[None]
        self.qvel[ids] = 0.0
        self.ctrl[ids] = self.nominal[None]
        self.xfrc[ids] = 0.0
        self.prev_action[ids] = 0.0
        self.prev_ctrl[ids] = self.nominal[None]
        self.step_count[ids] = 0
        self.time[ids] = 0.0
        self.in_control[ids] = 0.0
        self.last_palm_contact_t[ids] = -10.0
        self.loose_t[ids] = -1.0
        self.countdown_frac[ids] = 1.0
        self.bad_contact_t[ids] = 0.0
        self.fallen[ids] = False
        self.ep_return[ids] = 0.0
        self.ep_len[ids] = 0.0
        self._randomize_model(ids)
        self._schedule_push(ids)
        self.level.on_reset(ids)          # may move root / ball, set task state
        self.forward()
        self._scan_contacts()
        self.compute_obs()
        self.init_foot_xy[ids] = self.site_xpos[ids][:, self.foot_site_idx[[0, 4]], :2]
        self.task[ids] = self.level.task_block(ids)
        self.obs[ids, 107:119] = self.task[ids]

    def step(self, action: torch.Tensor):
        """action: (N, 27) in [-1, 1]. Returns obs, reward, done, info."""
        action = action.clamp(-1.0, 1.0)
        ctrl = (self.nominal + action * self.half).clamp(self.lo, self.hi)
        applied = torch.where(self.delay_action[:, None], self.prev_ctrl, ctrl)
        self.ctrl[:] = applied
        self.prev_ctrl[:] = ctrl
        self._apply_pushes()
        self._physics()
        self.time += self.control_dt
        self.step_count += 1

        self._scan_contacts()
        self.prev_action[:] = action
        self.compute_obs()
        self._update_ball_state()
        self.task[:] = self.level.task_block(None)
        self.obs[:, 107:119] = self.task

        # fallen: pelvis low, or non-foot/palm body on the floor for > 0.2 s
        self.bad_contact_t = torch.where(self._bad_floor, self.bad_contact_t + self.control_dt, torch.zeros_like(self.bad_contact_t))
        self.fallen = (self.p_pelvis[:, 2] < 0.55) | (self.bad_contact_t > 0.2)
        nan = ~torch.isfinite(self.qpos).all(dim=1)

        reward = self.level.reward()
        term = self.level.terminated() | self.fallen | nan
        trunc = self.step_count >= self.max_steps
        done = term | trunc
        self.ep_return += reward
        self.ep_len += 1
        info = {"terminated": term, "truncated": trunc, "fallen": self.fallen, "nan": nan,
                "time_outs": trunc & ~term}
        info.update(self.level.metrics())
        info["success"] = done & self.level.episode_success()   # evaluated before the auto-reset
        done_ids = done.nonzero(as_tuple=False).squeeze(-1)
        if done_ids.numel() > 0:
            info["ep_return"] = self.ep_return[done_ids].clone()
            info["ep_len"] = self.ep_len[done_ids].clone()
            self.episode_count[done_ids] += 1
            self.reset(done_ids)
        return self.obs, reward, done, info

    # ------------------------------------------------------------------ convenience
    def joint_pos(self) -> torch.Tensor:
        return self.qpos[:, self.qadr]

    def joint_vel(self) -> torch.Tensor:
        return self.qvel[:, self.vadr]

    def set_root_pose(self, ids: torch.Tensor, xy: torch.Tensor, yaw: torch.Tensor):
        rq = self.root_q
        self.qpos[ids, rq:rq + 2] = xy
        self.qpos[ids, rq + 3:rq + 7] = self.yaw_quat(yaw)

    def set_ball(self, ids: torch.Tensor, pos: torch.Tensor, vel: torch.Tensor | None = None):
        bq, bv = self.ball_q, self.ball_v
        self.qpos[ids, bq:bq + 3] = pos
        self.qpos[ids, bq + 3:bq + 7] = torch.tensor([1.0, 0, 0, 0], device=self.device)
        self.qvel[ids, bv:bv + 6] = 0.0
        if vel is not None:
            self.qvel[ids, bv:bv + 3] = vel
