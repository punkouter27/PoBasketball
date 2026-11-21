# 2026-11-20 (evening, laptop RTX 5070 Ti)

## 23:15 10 h dribble run `dribble_time10` (user: "do 10 hours training as needed for pobasketball")

Context: the 11-18..11-20 runs (`dribble_drift`, `dribble_time`, ...) were trained on the other machine; `sim/runs/` is gitignored
and none of them are on this PC. The only copy of the best dribble actor is the preview export `shared/policies/dribble.onnx`
(= `dribble_drift/ckpt_250M`, 250 M steps, interface 32f5b79d3216e8a3).

- Warm start rebuilt with `tools/onnx_to_ckpt.py ../shared/policies/dribble.onnx --out runs/production/dribble_drift_250M.pt`
  (onnxruntime vs torch 1.48e-6, parity PASS). Actor + normaliser only: no critic, optimiser or exploration std.
- Affected policy: dribble (L2a) only. No obs / action / physics / reward-code change. Nothing is exported or promoted by this run.
- Differences from `dribble_time` (other machine, stopped at 31 M): rule `ball_in_control` palm window 1.0 s (11-20 11:00), and the
  new `foot_slip` penalty (-0.1, `shared/reward_config.json`, fc49523) that this actor never trained with.
- Run: `tools/skill_run.py --level l2a_time --gate l2a_dribble_r --run-name dribble_time10 --train-min 540 --ckpt-every-steps 50e6`,
  extra `--init runs/production/dribble_drift_250M.pt --init-actor-only --critic-warmup-iters 60 --freeze-norm --init-std 0.15
  --kl-target 0.02 --assist-anneal-steps 1`. std 0.15 (not the 0.5 default: the ckpt carries no std) and KL 0.02 so the adaptive LR
  is not pinned at its floor (11-19 finding: KL ~ 1/std^2). Every 50 M checkpoint is evaluated on the gate after training.
- 23:14 started (PID 37160 driver). train.py warns interface/physics sha differ: **line endings only** (the shas hash raw bytes).
  This checkout: humanoid.xml CRLF (LF = bd7cf5274215544f, the ckpt value), court.xml LF (CRLF = 7e9b5753773f66b7, the ckpt
  value), obs_spec.json LF c766c7d32fb36d2e (CRLF = 9879b4bebba21aa3 = the 11-20 text-only edit). Same physics, same layout.
  ~20k fps on this laptop (530 M-650 M steps expected).
- Gate caveat (open user decision from 11-20 10:45): a clean bounce needs the ball < 0.6 m from the pelvis all cycle, but the dribble
  spot is 0.54 m from the pelvis (3 % of bounces qualify), so `l2a_dribble_r` stays 0 % whatever the policy does until that rule changes.
