# 2026-11-12 — Daily Training Log

## Extended policy optimization completed

Queue `sim/runs/queue/20261111_2310` completed at 06:45 after 7 h 35 min elapsed, within its eight-hour budget and 25-minute finalization reserve. It prioritized the two urgent policy families: the right-hand dribble push curriculum and loose-ball scramble. Hourly summaries are in `../20261111/hourly_status.md`.

| Policy run | Steps | Final episode return | 200-episode gate |
|---|---:|---:|---|
| `l2a_push_n11q1` | 166.2 M | 279.24 | 0%; failed |
| `l2a_push_n11q2` | 171.0 M | 477.52 | 0%; failed |
| `l3b_scramble_n11q1` | 165.4 M | 183.67 | 74.5%; failed |
| `l3b_scramble_n11q2` | 114.9 M | 215.56 | 81.5%; failed the 100-consecutive-episode hold |

All runs completed with zero NaN-gradient batches. No production ONNX was exported: the dribble policy remained at 0% on its real gate, and scramble did not satisfy the full hold criterion despite exceeding the 80% episode success threshold. Latest candidate checkpoints are under `sim/runs/production/candidates/`; existing production balance and locomotion weights were left unchanged.

The final HTML report contains reward, episode-length, clean-bounce, and scramble-regain charts with plain-language explanations: [extended_training_report.html](./extended_training_report.html).
