# 2026-11-17

## Overnight queue `n16b` (20:38 -> 06:14) results

| Stage | Run | Result |
|---|---|---|
| l3b_scramble 150 min from locomotion | `l3b_scramble_n16bq1` | 91.5 %, holds 100, but 40 NaN-gradient batches -> FAIL |
| l2a_dribble_r 75 min from locomotion | `l2a_dribble_r_n16bq1` | 0 %, no falls, mean episode 3.7 s -> FAIL |
| l2a_cycles 90 min | `l2a_cycles_n16bq1` | **did not run**: init `runs/l2a_dribble_r_n16q1` not found |
| l2a_push 120 min | `l2a_push_n16bq1` | **did not run**: init `runs/l2a_cycles_n16q1` not found |
| l3b_scramble 60 min full resume | `l3b_scramble_n16bq2` | **95.0 %, holds 100, 0 NaN, falls 1.5 % -> PASS**; exported `shared/policies/scramble.onnx`, synced to Unreal |
| l2a_push 288 min (rest) | `l2a_push_n16bq2` | started from scratch (init None); training curriculum reached K = 4 cycles, succ_ema about 0.55, but gate `l2a_dribble_r` 0 %, mean episode 1.1 s -> FAIL |

Cause of the two skipped stages: plan `grandma_20261116` hard-coded `n16` in the dribble lineage paths, the queue was
launched with `--tag n16b`. Fix in `sim/streetball/queue.py`: plan init paths use `{tag}`, and a stage whose init
checkpoint is missing is skipped with a log line instead of crashing the trainer.
Open question: `l2a_push` training reports cycles succeeding (ep 3.0 s) while the `l2a_dribble_r` gate ends episodes
after 1.1 s on average -> check the train/gate termination mismatch before the next dribble run.
