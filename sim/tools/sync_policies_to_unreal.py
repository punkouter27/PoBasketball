"""Copy the shared contracts and exported policies into the Unreal project (Content/Project/RL_Policies).

Policy roster (shared/transition_table.json v1): five families, one ONNX each:
    balance, locomotion, dribble, scramble, shot  ->  Content/Project/RL_Policies/policies/<family>.onnx
The Unreal director (UStreetballDirector) loads the table at BeginPlay and resolves each state
to its family file; a family without a file falls back to policies/dummy_policy.onnx.

Sources, in order of preference, for each family:
  1. shared/policies/<family>.onnx
  2. shared/policies/<trained_by_stage>.onnx (e.g. l0_stand.onnx -> balance.onnx), as recorded in the table
Sidecar <name>.json files are copied alongside; a sidecar whose obs_spec hash differs from the
current shared/obs_spec.json raises a warning (the policy was exported against another interface).

Also refreshes Content/Project/RL_Policies/{obs_spec,humanoid_spec,transition_table}.json and copies the MuJoCo
scene sim/assets/{scene,humanoid,court}.xml.

Usage: uv run python tools/sync_policies_to_unreal.py
"""

import hashlib
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"
DST = ROOT.parent / "unreal" / "StreetballGym" / "Content" / "Project" / "RL_Policies"
FAMILIES = ("balance", "locomotion", "dribble", "scramble", "shot")


def main() -> None:
    (DST / "policies").mkdir(parents=True, exist_ok=True)
    for name in ("obs_spec.json", "humanoid_spec.json", "transition_table.json"):
        src = SHARED / name
        if src.exists():
            shutil.copy2(src, DST / name)
        else:
            print(f"WARNING missing {src}")
    # the MuJoCo scene Unreal simulates must be the training one (its court.xml went stale once, 11-17 vs 11-19)
    for name in ("scene.xml", "humanoid.xml", "court.xml"):
        shutil.copy2(ROOT / "assets" / name, DST / name)
    # the fallback every family without a trained file uses (a fresh clone has none: Content/Project/RL_Policies/policies is ignored)
    for name in ("dummy_policy.onnx", "dummy_policy.json"):
        if (SHARED / name).exists():
            shutil.copy2(SHARED / name, DST / "policies" / name)
    spec_hash = hashlib.sha256((SHARED / "obs_spec.json").read_bytes()).hexdigest()
    table = json.loads((SHARED / "transition_table.json").read_text(encoding="utf-8"))
    policies = table.get("policies", {})
    src_dir = SHARED / "policies"
    copied, missing = [], []
    for fam in FAMILIES:
        cands = [src_dir / f"{fam}.onnx"]
        stage = policies.get(fam, {}).get("trained_by_stage")
        if stage:
            cands.append(src_dir / f"{stage}.onnx")
        src = next((c for c in cands if c.exists()), None)
        if src is None:
            missing.append(fam)
            continue
        shutil.copy2(src, DST / "policies" / f"{fam}.onnx")
        side = src.with_suffix(".json")
        if side.exists():
            h = json.loads(side.read_text(encoding="utf-8")).get("obs_spec_sha256")
            if h and h != spec_hash:
                print(f"WARNING {src.name}: obs_spec hash {h[:12]} != current {spec_hash[:12]}")
            shutil.copy2(side, DST / "policies" / f"{fam}.json")
        copied.append(f"{fam} <- {src.name}")
    print(f"copied {len(copied)} family policies to {DST / 'policies'}: {copied}; missing (dummy fallback): {missing}")


if __name__ == "__main__":
    main()
