"""Export a random (untrained) policy MLP to ONNX for the Phase B NNE loader test (B7).

Same contract as the real exporter: input "obs" [1,119] float32, output "action" [1,27]
float32 (tanh), opset 17, no dynamic axes, sidecar <name>.json with the obs_spec hash.

Usage: uv run python tools/make_dummy_policy.py [out.onnx]
"""
import hashlib
import json
import pathlib
import sys

import numpy as np
import onnxruntime as ort
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"
N_OBS, N_ACT = 119, 27


def main() -> None:
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else SHARED / "dummy_policy.onnx"
    torch.manual_seed(0)
    net = torch.nn.Sequential(
        torch.nn.Linear(N_OBS, 512), torch.nn.ELU(),
        torch.nn.Linear(512, 256), torch.nn.ELU(),
        torch.nn.Linear(256, 128), torch.nn.ELU(),
        torch.nn.Linear(128, N_ACT), torch.nn.Tanh(),
    ).eval()
    dummy = torch.zeros(1, N_OBS)
    torch.onnx.export(net, dummy, str(out), input_names=["obs"], output_names=["action"],
                      opset_version=17, dynamo=False)
    # parity check and golden I/O pair for the C++ test
    sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(0)
    x = rng.normal(size=(1, N_OBS)).astype(np.float32)
    y_ort = sess.run(["action"], {"obs": x})[0]
    with torch.no_grad():
        y_t = net(torch.from_numpy(x)).numpy()
    diff = float(np.abs(y_ort - y_t).max())
    spec_hash = hashlib.sha256((SHARED / "obs_spec.json").read_bytes()).hexdigest()
    side = {"n_obs": N_OBS, "n_action": N_ACT, "opset": 17, "obs_spec_sha256": spec_hash,
            "torch_vs_ort_max_abs_diff": diff, "dummy": True,
            "check_input": x[0].tolist(), "check_output": y_ort[0].tolist()}
    out.with_suffix(".json").write_text(json.dumps(side, indent=2), encoding="utf-8")
    print(f"wrote {out} and sidecar; torch vs onnxruntime max abs diff {diff:.2e}")


if __name__ == "__main__":
    main()
