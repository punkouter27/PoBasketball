"""Copy exported policies (shared/policies/*.onnx + sidecar .json) into the Unreal project.

The showcase loads Content/Sim/policies/<level>.onnx per state (see UStreetballDirector::
PolicyForState): l0_stand, l1_traverse, l2c_crossover, l3a_moving_dribble, l3b_scramble,
l4_jump_shot. Missing ones fall back to dummy_policy.onnx. Also refreshes the obs/humanoid
spec copies and warns if a sidecar's obs_spec hash differs from the current shared/obs_spec.json.

Usage: uv run python tools/sync_policies_to_unreal.py
"""
import hashlib
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"
DST = ROOT.parent / "unreal" / "StreetballGym" / "Content" / "Sim"


def main() -> None:
    (DST / "policies").mkdir(parents=True, exist_ok=True)
    for name in ("obs_spec.json", "humanoid_spec.json"):
        shutil.copy2(SHARED / name, DST / name)
    spec_hash = hashlib.sha256((SHARED / "obs_spec.json").read_bytes()).hexdigest()
    src = SHARED / "policies"
    copied = []
    if src.is_dir():
        for onnx in sorted(src.glob("*.onnx")):
            side = onnx.with_suffix(".json")
            if side.exists():
                h = json.loads(side.read_text(encoding="utf-8")).get("obs_spec_sha256")
                if h and h != spec_hash:
                    print(f"WARNING {onnx.name}: obs_spec hash {h[:12]} != current {spec_hash[:12]}")
                shutil.copy2(side, DST / "policies" / side.name)
            shutil.copy2(onnx, DST / "policies" / onnx.name)
            copied.append(onnx.name)
    print(f"copied {len(copied)} policies to {DST / 'policies'}: {copied}")


if __name__ == "__main__":
    main()
