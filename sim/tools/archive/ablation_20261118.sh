#!/usr/bin/env bash
# L0 fine-tune ablation (DOCS/20261118): which change keeps the production balance brain at 99 %?
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
REP=../DOCS/phase_reports
BASE="--level l0_stand --init runs/production/balance_v1w.pt --init-actor-only --freeze-norm --critic-warmup-iters 60
      --push-max 100 --lr 3e-4 --lr-max 1e-4 --kl-target 0.005 --posture-ramp-steps 1e15 --steps 15e6 --ckpt-every-steps 5e6"
declare -A EXTRA=( [abl_toe]="--init-std 0.15 --toe-std 0.01" [abl_nopen]="--init-std 0.15 --no-v2-penalties" [abl_lowstd]="--init-std 0.05" )
for r in abl_toe abl_nopen abl_lowstd; do
  echo "$(date +%H:%M) train $r ${EXTRA[$r]}"
  $PY -m streetball.train $BASE ${EXTRA[$r]} --run-name l0_$r > runs/l0_$r.out 2>&1
  for c in ckpt_5M ckpt_10M ckpt_15M; do
    cp $REP/eval_l0_stand.json /tmp/keep.json; cp $REP/eval_l0_stand.md /tmp/keep.md
    $PY -m streetball.evaluate --level l0_stand --ckpt runs/l0_$r/$c.pt --push-max 100 > /dev/null 2>&1
    $PY -c "import json; j=json.load(open('$REP/eval_l0_stand.json')); m=j['metrics']; print('RESULT $r $c', f\"success {j['success_rate']:.3f} falls {j['fall_rate']:.3f} jitter {m['m/quiet_jitter_cm']:.2f} speed {m['m/quiet_speed_cm_s']:.2f} torso {m['m/torso_upright']:.3f}\")"
    cp /tmp/keep.json $REP/eval_l0_stand.json; cp /tmp/keep.md $REP/eval_l0_stand.md
  done
done
echo "$(date +%H:%M) ALL DONE"
