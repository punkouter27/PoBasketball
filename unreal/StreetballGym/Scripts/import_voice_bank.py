"""Item 20: import the offline-baked grandma voice (tools/voice_bake/bake.py -> Content/Art/Exports/Voice) as sound
waves + /Game/Audio/Voice/DA_GrandmaVoiceBank (UGrandmaVoiceBank: per-line audio and per-frame CC morph weights).

    run_headless.ps1 -EditorArgs @("-run=pythonscript", "-script=<this file>")

Re-bake with real NVIDIA Audio2Face curves: uv run tools/voice_bake/bake.py --a2f-csv <dir>, then re-run this script.
"""
import json
import os

import unreal

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "Content", "Art", "Exports", "Voice")
DEST = "/Game/Audio/Voice"
EAL = unreal.EditorAssetLibrary


def main():
    with open(os.path.join(SRC, "voice_bank.json"), encoding="utf-8") as f:
        bank_json = json.load(f)
    EAL.make_directory(DEST)
    tasks = []
    for line in bank_json["lines"]:
        t = unreal.AssetImportTask()
        t.set_editor_property("filename", os.path.join(SRC, line["wav"]))
        t.set_editor_property("destination_path", DEST)
        t.set_editor_property("destination_name", "SW_Voice_" + line["id"])
        t.set_editor_property("automated", True)
        t.set_editor_property("replace_existing", True)
        t.set_editor_property("save", True)
        tasks.append(t)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

    path = f"{DEST}/DA_GrandmaVoiceBank"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.GrandmaVoiceBank)
    bank = unreal.AssetToolsHelpers.get_asset_tools().create_asset("DA_GrandmaVoiceBank", DEST, unreal.GrandmaVoiceBank, factory)
    morphs = bank_json["morphs"]
    bank.set_editor_property("fps", float(bank_json.get("fps", 30)))
    bank.set_editor_property("morphs", [unreal.Name(m) for m in morphs])
    lines = []
    missing = 0
    for line in bank_json["lines"]:
        snd = unreal.load_asset(f"{DEST}/SW_Voice_{line['id']}")
        if snd is None:
            missing += 1
        frames = line["frames"]
        flat = [float(w) for row in frames for w in row]
        if any(len(row) != len(morphs) for row in frames):
            raise SystemExit(f"VOICE_IMPORT FAILED: {line['id']} frame width != {len(morphs)} morphs")
        v = unreal.GrandmaVoiceLine()
        v.set_editor_property("id", unreal.Name(line["id"]))
        v.set_editor_property("event", unreal.Name(line["event"]))
        v.set_editor_property("text", line["text"])
        v.set_editor_property("mood", unreal.Name(line.get("mood", "")))
        v.set_editor_property("sound", snd)
        v.set_editor_property("duration", float(line["duration_s"]))
        v.set_editor_property("num_frames", len(frames))
        v.set_editor_property("frames", flat)
        lines.append(v)
    bank.set_editor_property("lines", lines)
    EAL.save_loaded_asset(bank)
    events = sorted({l["event"] for l in bank_json["lines"]})
    unreal.log(f"VOICE_IMPORT OK {len(lines)} lines, {len(morphs)} morphs, events {events}, missing sounds {missing}")


main()
