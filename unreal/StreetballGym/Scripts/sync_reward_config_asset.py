"""Write shared/reward_config.json into the DataAsset /Game/Project/DataAssets/DA_RewardConfig and save it.

The editor test Streetball.Showcase.ConfigDataAssets fails when the two differ; run this after changing the JSON:

    pwsh Scripts/run_headless.ps1 -TimeoutSec 600 -- -ExecutePythonScript="<abs path>/Scripts/sync_reward_config_asset.py"
"""

import json
import pathlib
import re

import unreal

ASSET = "/Game/Project/DataAssets/DA_RewardConfig"
JSON = pathlib.Path(__file__).resolve().parents[3] / "shared" / "reward_config.json"
HEADER = pathlib.Path(__file__).resolve().parents[1] / "Source" / "StreetballGym" / "StreetballRewardConfig.h"


def snake(name: str) -> str:
    """The Python name UE gives a UPROPERTY: TorqueSqWeight -> torque_sq_weight, AngVelXYSqWeight -> ang_vel_xy_sq_weight."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def main() -> None:
    cfg = json.loads(JSON.read_text(encoding="utf-8"))
    # json key -> C++ property, matched by name (power_abs -> PowerAbsWeight) from the header's float *Weight fields
    fields = re.findall(r"float (\w+Weight) = ", HEADER.read_text(encoding="utf-8"))
    by_snake = {snake(f)[: -len("_weight")]: f for f in fields}
    asset = unreal.EditorAssetLibrary.load_asset(ASSET)
    if asset is None:
        raise RuntimeError(f"{ASSET} not found")
    for key, w in cfg["penalties"].items():
        prop = by_snake.get(key)
        if prop is None:
            raise RuntimeError(f"penalty {key!r} has no {HEADER.name} property")
        asset.set_editor_property(snake(prop), float(w))
    stages = []
    for row in cfg["curriculum"]:
        st = unreal.StreetballCurriculumStage()
        st.set_editor_property("stage", row["stage"])
        st.set_editor_property("threshold", float(row["threshold"]))
        st.set_editor_property("metric", row["metric"])
        stages.append(st)
    asset.set_editor_property("curriculum_stages", stages)
    unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
    unreal.log(f"sync_reward_config_asset: {len(cfg['penalties'])} weights, {len(stages)} stages -> {ASSET}")


main()
