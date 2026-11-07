"""Task B9: generate placeholder court sounds and the UCourtAudioBank data asset, headlessly.

    UnrealEditor-Cmd.exe StreetballGym.uproject -run=pythonscript -script="<this file>" -unattended -nop4

Writes short synthetic WAVs (sine / noise bursts, pure-python `wave` so no numpy is needed) to
Saved/GeneratedAudio/, imports them as USoundWave into /Game/Audio, then creates
/Game/Audio/DA_CourtAudioBank and wires each slot. Replace the slots with real samples later.
"""
import math
import os
import random
import struct
import wave

import unreal

SR = 44100
OUT_DIR = os.path.join(unreal.Paths.project_saved_dir(), "GeneratedAudio")
PKG_DIR = "/Game/Audio"


def write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples))


def env(t, attack, decay):
    return min(1.0, t / attack) * math.exp(-t / decay) if t >= 0 else 0.0


def tone_burst(freq, dur, attack=0.002, decay=0.06, harmonics=(1.0,), noise=0.0, drop=0.0):
    rnd = random.Random(1)
    out = []
    n = int(dur * SR)
    for i in range(n):
        t = i / SR
        f = freq * (1.0 - drop * t / dur)
        s = sum(a * math.sin(2 * math.pi * f * (k + 1) * t) for k, a in enumerate(harmonics))
        s += noise * (rnd.random() * 2 - 1)
        out.append(0.8 * s * env(t, attack, decay))
    return out


def noise_burst(dur, attack=0.001, decay=0.04, lowpass=0.6):
    rnd = random.Random(2)
    out, prev = [], 0.0
    for i in range(int(dur * SR)):
        t = i / SR
        x = rnd.random() * 2 - 1
        prev = lowpass * prev + (1 - lowpass) * x
        out.append(0.9 * prev * env(t, attack, decay))
    return out


def rattle(dur=0.6):
    rnd = random.Random(3)
    out = []
    n = int(dur * SR)
    hits = sorted(rnd.random() * dur * 0.8 for _ in range(14))
    for i in range(n):
        t = i / SR
        s = 0.0
        for h in hits:
            dt = t - h
            if 0 <= dt < 0.05:
                s += 0.35 * math.sin(2 * math.pi * (2400 + 600 * (h * 7 % 1)) * dt) * math.exp(-dt / 0.012)
        out.append(s * (1.0 - t / dur))
    return out


SOUNDS = {
    "SW_BallFloor": tone_burst(95, 0.18, decay=0.045, harmonics=(1.0, 0.4, 0.15), noise=0.15, drop=0.25),
    "SW_BallPalm": noise_burst(0.07, decay=0.018, lowpass=0.3),
    "SW_ShoeFloor": tone_burst(2600, 0.12, attack=0.004, decay=0.03, harmonics=(1.0, 0.3), noise=0.4, drop=0.3),
    "SW_BallRim": tone_burst(640, 0.35, decay=0.09, harmonics=(1.0, 0.5, 0.3, 0.2)),
    "SW_BallBoard": tone_burst(180, 0.22, decay=0.05, harmonics=(1.0, 0.6, 0.2), noise=0.25),
    "SW_NetRattle": rattle(),
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    tasks = []
    for name, samples in SOUNDS.items():
        path = os.path.join(OUT_DIR, name + ".wav")
        write_wav(path, samples)
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", path)
        task.set_editor_property("destination_path", PKG_DIR)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        tasks.append(task)
    tools.import_asset_tasks(tasks)

    waves = {}
    for name in SOUNDS:
        obj = unreal.load_asset(f"{PKG_DIR}/{name}")
        if obj is None:
            raise SystemExit(f"import failed for {name}")
        waves[name] = obj

    bank_cls = unreal.load_class(None, "/Script/StreetballGym.CourtAudioBank")
    bank = unreal.load_asset(f"{PKG_DIR}/DA_CourtAudioBank")
    if bank is None:
        bank = tools.create_asset("DA_CourtAudioBank", PKG_DIR, bank_cls, unreal.DataAssetFactory())
    bank.set_editor_property("ball_floor", waves["SW_BallFloor"])
    bank.set_editor_property("ball_palm", waves["SW_BallPalm"])
    bank.set_editor_property("shoe_floor", waves["SW_ShoeFloor"])
    bank.set_editor_property("ball_rim", waves["SW_BallRim"])
    bank.set_editor_property("ball_board", waves["SW_BallBoard"])
    bank.set_editor_property("net_rattle", waves["SW_NetRattle"])
    unreal.EditorAssetLibrary.save_loaded_asset(bank)
    unreal.log(f"audio bank ready: {PKG_DIR}/DA_CourtAudioBank with {len(waves)} placeholder waves")


main()
