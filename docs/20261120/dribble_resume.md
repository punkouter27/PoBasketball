# dribble_resume: l2a_push -> gate l2a_dribble_r

Train 430.0 min, extra `--init runs/dribble_overnight/model.pt --assist-anneal-steps 20e6`. Every checkpoint evaluated on `l2a_dribble_r` (200 episodes).

| Checkpoint | Success | Holds 100 | Falls | Episode s | apex | bounces | in_control | palm_touch | reach | streak | switches |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ckpt_50M.pt | 0.0% | no | 0.5% | 4.4 | 0.696 | 3.300 | 0.902 | 0.051 | 0.693 | 0.359 | 0.000 |
| ckpt_100M.pt | 0.0% | no | 3.5% | 4.3 | 0.634 | 3.379 | 0.908 | 0.047 | 0.657 | 1.486 | 0.000 |
| ckpt_150M.pt | 0.0% | no | 0.0% | 3.8 | 0.661 | 2.961 | 0.912 | 0.046 | 0.623 | 0.774 | 0.000 |
| best.pt | 0.0% | no | 0.5% | 4.2 | 0.695 | 3.109 | 0.889 | 0.051 | 0.676 | 0.614 | 0.000 |
| model.pt | 0.0% | no | 1.0% | 3.6 | 0.659 | 2.753 | 0.903 | 0.051 | 0.599 | 0.206 | 0.000 |

Failure reasons (share of all episodes, not exclusive):

| Checkpoint | ball_lost_countdown | ball_over_1_5m | failed_without_falling | fell | out_of_time | pelvis_drifted_0_5m |
|---|---|---|---|---|---|---|
| ckpt_50M.pt | 0.0% | 0.5% | 99.5% | 0.5% | 0.0% | 99.0% |
| ckpt_100M.pt | 0.0% | 3.0% | 96.5% | 3.5% | 0.0% | 94.0% |
| ckpt_150M.pt | 0.0% | 2.0% | 100.0% | 0.0% | 0.0% | 98.0% |
| best.pt | 0.0% | 3.5% | 99.5% | 0.5% | 0.0% | 96.0% |
| model.pt | 0.0% | 3.5% | 99.0% | 1.0% | 0.0% | 96.0% |

**Passed the gate:** none.
