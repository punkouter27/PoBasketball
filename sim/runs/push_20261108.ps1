# l2a_push (dribble approach #7): 120 min from l2a_cycles_c3, then eval on the real L2a gate and an HTML report.
# Prerequisite: Windows Smart App Control must allow torch\lib\shm.dll (blocked from 2026-11-08 21:07).
# Launch hidden (survives the Claude session): Win32_Process.Create with ShowWindow=0, as for cycles3.
Set-Location "C:\Users\punko\Downloads\CODE_MATT\PoBasketball\sim"
$log = "runs\push_20261108.txt"
function Say($m) { "[$(Get-Date -Format HH:mm:ss)] $m" | Out-File -FilePath $log -Append -Encoding utf8 }
Say "torch import check"
uv run python -c "import torch; assert torch.cuda.is_available()" *>> $log
if ($LASTEXITCODE -ne 0) { Say "torch unavailable (Smart App Control?) - aborting"; exit 1 }
Say "train l2a_push_p1 (120 min, init from l2a_cycles_c3)"
uv run python -m streetball.train --level l2a_push --steps 1e9 --num-envs 4096 --run-name l2a_push_p1 --time-budget-min 120 --push-max 80 --init runs/l2a_cycles_c3/model.pt *>> runs\l2a_push_p1_stdout.txt
Say "train rc $LASTEXITCODE; evaluating on the real gate level l2a_dribble_r"
uv run python -m streetball.evaluate --level l2a_dribble_r --ckpt runs/l2a_push_p1/model.pt *> runs\l2a_push_p1_eval.txt
Say "eval rc $LASTEXITCODE"
Copy-Item ..\DOCS\phase_reports\eval_l2a_dribble_r.json runs\l2a_push_p1\eval.json
uv run python tools/run_report.py runs/l2a_push_p1 *>> runs\l2a_push_p1_stdout.txt
Say "report rc $LASTEXITCODE; all done"
