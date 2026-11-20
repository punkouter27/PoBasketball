# dribble_drift: l2a_push -> gate l2a_dribble_r

Train 245.0 min, extra `--init runs/dribble_resume/ckpt_50M.pt --assist-anneal-steps 20e6`. Every checkpoint evaluated on `l2a_dribble_r` (200 episodes).

| Checkpoint | Success | Holds 100 | Falls | Episode s | apex | bounces | in_control | palm_touch | reach | streak | switches |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ckpt_50M.pt | 0.0% | no | 10.5% | 5.6 | 0.546 | 4.608 | 0.837 | 0.042 | 0.630 | 1.756 | 0.000 |
| ckpt_100M.pt | 0.0% | no | 1.0% | 5.6 | 0.698 | 4.072 | 0.849 | 0.050 | 0.688 | 2.022 | 0.000 |
| ckpt_150M.pt | 0.0% | no | 4.0% | 6.6 | 0.625 | 5.074 | 0.926 | 0.052 | 0.639 | 0.122 | 0.000 |
| ckpt_200M.pt | 0.0% | no | 0.0% | 4.4 | 0.580 | 3.560 | 0.987 | 0.081 | 0.657 | 0.062 | 0.000 |
| ckpt_250M.pt | 0.0% | no | 1.5% | 10.2 | 0.688 | 7.533 | 0.911 | 0.078 | 0.700 | 0.052 | 0.000 |
| best.pt | 0.0% | no | 0.5% | 5.1 | 0.689 | 3.852 | 0.912 | 0.052 | 0.677 | 0.286 | 0.000 |
| model.pt | 0.0% | no | 0.5% | 6.6 | 0.744 | 4.609 | 0.820 | 0.046 | 0.718 | 0.057 | 0.000 |

Failure reasons (share of all episodes, not exclusive):

| Checkpoint | ball_lost_countdown | ball_over_1_5m | failed_without_falling | fell | out_of_time | pelvis_drifted_0_5m |
|---|---|---|---|---|---|---|
| ckpt_50M.pt | 1.5% | 4.0% | 89.5% | 10.5% | 0.0% | 86.0% |
| ckpt_100M.pt | 0.0% | 10.5% | 99.0% | 1.0% | 0.0% | 89.0% |
| ckpt_150M.pt | 0.0% | 0.5% | 96.0% | 4.0% | 0.0% | 96.0% |
| ckpt_200M.pt | 0.0% | 0.5% | 100.0% | 0.0% | 0.0% | 99.5% |
| ckpt_250M.pt | 0.0% | 0.5% | 98.5% | 1.5% | 0.5% | 98.0% |
| best.pt | 0.0% | 0.0% | 99.5% | 0.5% | 0.0% | 99.5% |
| model.pt | 0.0% | 0.0% | 99.5% | 0.5% | 0.0% | 99.5% |

**Passed the gate:** none.
