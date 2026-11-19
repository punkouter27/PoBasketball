"""Rebuild an actor-only training checkpoint from an exported production ONNX policy.

sim/runs/ is gitignored, so a fresh clone has the production ONNX files in shared/policies/ but no
.pt checkpoints to warm-start from. export_onnx folds the observation normaliser into constants;
this tool reads them back (Sub = mean, Div = sqrt(var + 1e-8)), loads the four Linear layers in
graph order, and refuses to write unless PyTorch matches onnxruntime to < 1e-5 on 1000 random
observations. The result only supports `--init ... --init-actor-only` (no critic/optimiser state).

    uv run python tools/onnx_to_ckpt.py ../shared/policies/locomotion.onnx --out runs/production/locomotion.pt
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
import onnx
import onnxruntime as ort
import torch
from onnx import numpy_helper

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from streetball import obs as obs_spec  # noqa: E402
from streetball.ppo import Actor  # noqa: E402


def constant_inputs(model: onnx.ModelProto) -> dict[str, np.ndarray]:
    consts = {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}
    for n in model.graph.node:
        if n.op_type == "Constant":
            consts[n.output[0]] = numpy_helper.to_array(n.attribute[0].t)
    return consts


def rebuild(onnx_path: pathlib.Path, hidden=(512, 256, 128), n_obs: int | None = None,
            n_act: int | None = None) -> tuple[Actor, float]:
    n_obs = obs_spec.N_OBS if n_obs is None else n_obs
    n_act = obs_spec.N_JOINTS if n_act is None else n_act
    model = onnx.load(str(onnx_path))
    c = constant_inputs(model)
    mean = std = None
    linears: list[tuple[np.ndarray, np.ndarray]] = []
    for n in model.graph.node:
        k = [x for x in n.input if x in c]
        if n.op_type == "Sub" and mean is None and k:
            mean = c[k[0]].astype(np.float64)
        elif n.op_type == "Div" and std is None and k:
            std = c[k[0]].astype(np.float64)
        elif n.op_type == "Gemm":
            w, b = c[n.input[1]], c[n.input[2]]
            trans_b = next((a.i for a in n.attribute if a.name == "transB"), 0)
            linears.append((w if trans_b else w.T, b))
        elif n.op_type == "MatMul" and k:
            linears.append((c[k[0]].T, None))
        elif n.op_type == "Add" and k and linears and linears[-1][1] is None:
            linears[-1] = (linears[-1][0], c[k[0]])
    if mean is None or std is None or len(linears) != len(hidden) + 1:
        raise SystemExit(f"unexpected graph: mean={mean is not None} std={std is not None} linears={len(linears)}")

    actor = Actor(n_obs, n_act, hidden)
    with torch.no_grad():
        actor.norm.mean.copy_(torch.from_numpy(np.broadcast_to(mean, (n_obs,)).copy()).float())
        actor.norm.var.copy_(torch.from_numpy(np.broadcast_to(std ** 2 - 1e-8, (n_obs,)).copy()).float())
        actor.norm.count.fill_(1e6)  # treat the normaliser as converged so fine-tuning does not jerk it
        layers = [m for m in actor.net if isinstance(m, torch.nn.Linear)]
        for lin, (w, b) in zip(layers, linears):
            lin.weight.copy_(torch.from_numpy(np.ascontiguousarray(w)).float())
            lin.bias.copy_(torch.from_numpy(b).float())
    actor.eval()

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    x = np.random.default_rng(0).normal(0, 2, (1000, n_obs)).astype(np.float32)
    with torch.no_grad():
        ref = actor(torch.from_numpy(x)).numpy()
    got = np.concatenate([sess.run(["action"], {"obs": x[i:i + 1]})[0] for i in range(len(x))], 0)
    return actor, float(np.abs(got - ref).max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("onnx")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    src = pathlib.Path(args.onnx)
    actor, diff = rebuild(src)
    print(f"onnxruntime vs rebuilt torch actor max abs diff {diff:.2e}")
    if diff >= 1e-5:
        raise SystemExit("FAIL: parity above 1e-5, checkpoint not written")
    side = src.with_suffix(".json")
    meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    sd = {"ac": {f"actor.{k}": v for k, v in actor.state_dict().items()},
          "actor_only": True, "rebuilt_from_onnx": str(src),
          "level": meta.get("level"), "interface_sha": meta.get("interface_sha"),
          "physics_sha": meta.get("physics_sha"), "steps": meta.get("train_steps"), "nan_grads": meta.get("nan_grads", 0)}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(sd, out)
    print(f"wrote {out} (actor only, parity PASS)")


if __name__ == "__main__":
    main()
