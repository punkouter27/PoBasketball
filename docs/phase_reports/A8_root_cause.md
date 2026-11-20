# A8 world-to-world drift: root cause (2026-11-20)

The old `sim/tests/test_determinism.py` failed locally with "Warp world-to-world max |Δqpos| over 8 identical worlds:
4.38e-01 (gate 1e-3)". It also rewrote the tracked `A8_determinism.md` on every run. Measured on the RTX 2060
(sim/.venv: mujoco 4.0.0, mujoco-warp 4.0.0, warp-lang 1.19.0, CUDA 13.4):

| Probe | Result |
|---|---|
| Worlds at t = 0 (after `put_data`, keyframe `stand`) | bit-identical (max diff 0.0) |
| Spread after the first control step (10 substeps) | 3e-10 to 5e-10: float32 round-off, not an input difference |
| Spread growth over the 5 s replay | 3e-8 (0.1 s), 2e-7 (0.2 s), 1.5e-4 (2 s), 0.1 to 0.4 (3 to 5 s) |
| Where the 4.38e-01 came from | qpos[0:7] = the ball's free joint; the largest entry is the ball's quaternion (a sphere's orientation) |
| Same run repeated with `nworld = 1` | run-to-run difference 0.46: not a cross-world effect at all |
| Ball parked 20 m away | humanoid still spreads 0.01 to 0.08 cm root, 0.07 to 0.33 deg joints between runs |
| Humanoid vs CPU libmujoco, worst of 8 worlds | 0.005 to 0.07 cm root, 0.03 to 0.5 deg joints (gates 2 cm / 1 deg) |
| `wp.config.deterministic = RUN_TO_RUN` | MuJoCo Warp kernels do not compile in deterministic mode (`constraint.py` reads `nefc_out` it atomically increments) |

Root cause: MuJoCo Warp accumulates contact and constraint quantities with float32 atomics on the GPU, so the summation
order (and the last bits) changes from launch to launch. The scene is contact-rich (feet, ball on the court) and the
solver often stops at its line-search iteration limit, so those round-off differences grow chaotically; the free,
bouncing ball amplifies them fastest. Nothing differs between the worlds' inputs: same seed, no per-world
randomisation in this test, identical start state.

What the test now checks (like-for-like, same device, fixed seed 0):

* every world (not just world 0) stays within the contract gate against CPU libmujoco: root 2 cm, joints 1 degree;
* the worlds start bit-identical and, after one control step, differ by less than 1e-6 (round-off only). A real
  per-world difference (seed, randomisation, uninitialised buffer) breaks this immediately;
* over the whole replay any two worlds agree within the same contract gate (root 2 cm, joints 1 degree). This is the
  property training relies on: worlds are interchangeable samples of the same physics within the tolerance accepted
  against the CPU reference. The ball's position is reported, its orientation ignored.

The old 1e-3 gate on the full qpos (ball quaternion included, after 5 s of chaotic contact) could not be met by any
GPU run and did not measure a contract property, so it was replaced rather than loosened. The test writes its report
to pytest's `tmp_path`; `sim/tools/a8_determinism_report.py` refreshes `A8_determinism.md` on purpose.
