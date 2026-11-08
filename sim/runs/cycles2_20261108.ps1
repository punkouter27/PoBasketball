# 2026-11-08 ~14:45 (via WMI, hidden): dribble approach #6 - one-bounce curriculum (l2a_cycles), 120 min, then eval on the real L2a gate.
Set-Location "C:\Users\punko\Downloads\CODE_MATT\PoBasketball\sim"
$log = "runs\cycles2_20261108.txt"
function Say($m) { "[$(Get-Date -Format HH:mm:ss)] $m" | Out-File -FilePath $log -Append -Encoding utf8 }
Say "train l2a_cycles_c2 (60 min, full resume from l2a_cycles_c1; K-promotion bug fixed)"
uv run python -m streetball.train --level l2a_cycles --steps 1e9 --num-envs 4096 --run-name l2a_cycles_c2 --time-budget-min 60 --push-max 80 --init runs/l2a_cycles_c1/model.pt *>> runs\l2a_cycles_c2_stdout.txt
Say "train rc $LASTEXITCODE; evaluating on the real gate level l2a_dribble_r"
uv run python -m streetball.evaluate --level l2a_dribble_r --ckpt runs/l2a_cycles_c2/model.pt *> runs\l2a_cycles_c2_eval.txt
Say "eval rc $LASTEXITCODE"
Copy-Item ..\DOCS\phase_reports\eval_l2a_dribble_r.json runs\l2a_cycles_c2\eval.json
uv run python tools/run_report.py runs/l2a_cycles_c2 *>> runs\l2a_cycles_c2_stdout.txt
Say "report rc $LASTEXITCODE; all done"
