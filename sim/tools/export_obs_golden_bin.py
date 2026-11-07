"""Convert shared/golden/obs_golden.npz to a flat little-endian binary for the UE golden test.

Layout (all int32 header, then float64 arrays, row-major):
    int32 magic = 0x0B5601D ("OBSGOLD"), int32 n, nq, nv, n_action, n_task, n_obs
    float64 qpos[n][nq], qvel[n][nv], prev_action[n][n_action], task[n][n_task],
            in_control[n], countdown_frac[n], obs[n][n_obs]

Usage: uv run python tools/export_obs_golden_bin.py
"""
import pathlib
import struct

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT.parent / "shared" / "golden" / "obs_golden.npz"
DST = ROOT.parent / "shared" / "golden" / "obs_golden.bin"


def main() -> None:
    z = np.load(SRC)
    n, nq = z["qpos"].shape
    nv = z["qvel"].shape[1]
    na = z["prev_action"].shape[1]
    nt = z["task"].shape[1]
    no = z["obs"].shape[1]
    with open(DST, "wb") as f:
        f.write(struct.pack("<7i", 0x0B5601D, n, nq, nv, na, nt, no))
        for key in ["qpos", "qvel", "prev_action", "task", "in_control", "countdown_frac", "obs"]:
            f.write(np.ascontiguousarray(z[key], dtype="<f8").tobytes())
    print(f"wrote {DST} ({DST.stat().st_size} bytes; n={n} nq={nq} nv={nv} na={na} nt={nt} nobs={no})")


if __name__ == "__main__":
    main()
