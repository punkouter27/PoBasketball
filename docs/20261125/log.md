# 2026-11-25

## Progress report with inference captures (presentation only)

Report: `SCREENSHOTS/20261125_progress/index.html`. Game run on the gated policies (balance, locomotion, dribble =
dribble_anchor10, scramble; NNE/ONNX inference), scripted switches through every Dribble Lab behaviour and humanoid:
12 annotated stills, 5 GIFs. The overnight checkpoints failed their gates and were not exported (UU_AGENT section 4).
Editor proof (GUI editor, timed Python, screen grabs): StreetballNeighbourhood PCG volume moved +20 m / +8 m and rotated
25 deg (regenerated), Sun rotated; Play-In-Editor afterwards: 57 bounces, 55 clean, 0 resets. Transforms restored, level
not saved (no git change to Court.umap). Physics objects (court, hoops, ball, humanoid) are spawned from the MJCF at
BeginPlay by design and are not hand-placed.
