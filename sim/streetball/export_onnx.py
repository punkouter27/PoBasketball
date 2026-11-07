"""C6: export a trained actor to ONNX (opset 17) with observation normalisation folded in.

    uv run python -m streetball.export_onnx runs/<run>/model.pt --out ../shared/policies/l0_stand.onnx

Input  "obs"    float32 [1, 119]
Output "action" float32 [1, 27]  in [-1, 1]  (ctrl = clip(nominal + action * half, lo, hi) is applied by the caller)

Also runs an onnxruntime parity check against PyTorch on 1000 random observations
(max abs diff must be < 1e-5) and writes a sidecar JSON with the obs/action spec hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

import numpy as np
import onnx
import onnxruntime as ort
import torch

from streetball import obs as obs_spec
from streetball.ppo import Actor

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"


def export(ckpt: pathlib.Path, out: pathlib.Path, hidden=(512, 256, 128)) -> float:
    sd = torch.load(ckpt, map_location="cpu")
    if int(sd.get("nan_grads", 0)) > 0:
        raise SystemExit(f"refusing to export {ckpt}: {sd['nan_grads']} NaN-gradient batches recorded (UU_AGENT gate)")
    actor = Actor(obs_spec.N_OBS, obs_spec.N_JOINTS, hidden)
    actor.load_state_dict({k[len("actor."):]: v for k, v in sd["ac"].items() if k.startswith("actor.")})
    actor.eval()

    out.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.zeros(1, obs_spec.N_OBS)
    torch.onnx.export(
        actor, dummy, str(out), opset_version=17, input_names=["obs"], output_names=["action"],
        dynamic_axes=None, do_constant_folding=True, dynamo=False,
    )
    onnx.checker.check_model(onnx.load(str(out)))

    sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(0)
    x = rng.normal(0, 2, (1000, obs_spec.N_OBS)).astype(np.float32)
    with torch.no_grad():
        ref = actor(torch.from_numpy(x)).numpy()
    got = np.concatenate([sess.run(["action"], {"obs": x[i:i + 1]})[0] for i in range(len(x))], 0)
    diff = float(np.abs(got - ref).max())

    spec_hash = hashlib.sha256((SHARED / "obs_spec.json").read_bytes()).hexdigest()[:16]
    out.with_suffix(".json").write_text(json.dumps({
        "checkpoint": str(ckpt), "obs_spec_sha256_16": spec_hash, "n_obs": obs_spec.N_OBS,
        "n_action": obs_spec.N_JOINTS, "opset": 17, "ort_vs_torch_max_abs_diff": diff,
        "input": "obs[1,119]", "output": "action[1,27] in [-1,1]",
        "level": sd.get("level"), "interface_sha": sd.get("interface_sha"), "physics_sha": sd.get("physics_sha"),
        "train_steps": sd.get("steps"), "nan_grads": sd.get("nan_grads", 0),
    }, indent=2), encoding="utf-8")
    return diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    diff = export(pathlib.Path(args.ckpt), pathlib.Path(args.out))
    print(f"exported {args.out}; onnxruntime vs torch max abs diff {diff:.2e} ({'PASS' if diff < 1e-5 else 'FAIL'})")
    raise SystemExit(0 if diff < 1e-5 else 1)


if __name__ == "__main__":
    main()
