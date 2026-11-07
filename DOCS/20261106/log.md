# 2026-11-06 — daily log

## Where things stand (for the next agent)

| Area | State | Pointer |
|---|---|---|
| Step 1–3 documents | approved | `DOCS/01_…`, `02_…`, `03_…` |
| Phase A assets | complete, hashes frozen | `DOCS/phase_reports/PhaseA_summary.md` |
| Phase B Unreal | complete, 14 headless tests green | `DOCS/phase_reports/PhaseB_B1_B7.md`, `PhaseB_B8_B10.md` |
| Phase C training stack | complete | `DOCS/phase_reports/PhaseC_setup.md` |
| L0 Stand policy | **training**, run `sim/runs/l0_v3` (detached python, pid in `sim/runs_l0_v3.log`) | TensorBoard http://localhost:6006 |
| Step 4 gate | tooling ready, waiting on L0 | `sim/tools/run_gate.py` |
| Git | initialised on `master` today, first commit `305e498` | |

## L0 training history

| Run | Start | Settings | Outcome |
|---|---|---|---|
| `smoke_l0` | 3 M steps, 2048 envs | defaults | loop works; return 29 → 95 |
| `l0_v1` | 0 → 30.6 M | std 0.5, foot-drift termination 0.20 m, 150 N push curriculum | episodes 4 s; most ended by foot drift, not falls |
| `l0_v2` | from `l0_v1` @30 M, +56.7 M | std 0.3, drift penalty ×2, termination 0.35 m | episodes 26 s plateau once pushes reached 150 N; mean sway 12 cm |
| `l0_v3` | from `l0_v2` @55 M, 100 M budget | pushes capped at 100 N (user approved) | in progress |

Interpretation: with full 150 N shoves the policy survives by shuffling (sway 12 cm, drift 17 cm) and
cannot satisfy both "60 s" and "feet within 20 cm". Capped pushes target the PRD's stance rule.

## Visual run of the Unreal scene (first ever)

`UnrealEditor.exe <uproject> /Game/Maps/Court -game -windowed` with the 44 M-step L0 snapshot:
- HUD, state machine and policy ran (Tier 1 completed at 60 s, Tier 2 fell with the dummy policy).
- Viewport was black: the level's sun was built with `unreal.Rotator(-55, 35, 0)`, which is (roll, pitch, yaw)
  → sun pointing up. Fixed to `Rotator(0, -55, 35)`, lights made Movable, auto exposure re-enabled,
  sideline FOV margin widened. Screenshots in `SCREENSHOTS/`.

## UU_AGENT standard adopted today

See `AGENTS.md` and `DOCS/20261106/uu_agent_audit.md` for the compliance audit and the policy-impact list
of the proposed physics/architecture changes (awaiting the user's answers).

## Open issues (priority order)

1. L0 pass target not yet reached (gate: 95 % of 200 episodes survive 60 s, sway < 3 cm, feet within 20 cm).
2. Self-collision is off in the humanoid model (violates UU_AGENT §2); enabling it changes physics → L0 retrain from checkpoint.
3. Policy roster is 8 per-level policies; UU_AGENT §3 wants one per skill family with command inputs, plus a get-up policy.
4. Cosmetic: fence/ball colours not applied (dark), character framed right of centre in the sideline shot, placeholder audio.
