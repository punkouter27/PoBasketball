# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "scipy", "matplotlib"]
# ///
"""Offline voice bake for the trash-talking grandma.

Pipeline per line (all offline, no GPU, no network at runtime):
  1. Windows SAPI TTS (System.Speech via PowerShell, see sapi_tts.ps1) -> raw 48 kHz WAV.
  2. ffmpeg "older voice" post: pitch drop via asetrate, shallow 5 Hz vibrato/tremolo,
     gentle low-pass, loudness normalisation to -16 LUFS -> final 48 kHz mono s16 WAV.
  3. Face curves at 30 Hz for Character Creator morph targets, either from the built-in
     audio-driven lip-sync or from NVIDIA Audio2Face-3D ARKit tracks (--a2f-csv <dir>),
     plus a mood expression layer and natural blinks.
  4. Writes <id>.wav + voice_bank.json into unreal/StreetballGym/Content/Art/Exports/Voice/.

Run:  uv run tools/voice_bake/bake.py [--only make_01,miss_02] [--a2f-csv DIR] [--voice NAME]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, resample_poly, sosfiltfilt

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DEFAULT_OUT = REPO / "unreal" / "StreetballGym" / "Content" / "Art" / "Exports" / "Voice"

SR = 48000
FPS = 30
HOP_HZ = 120  # analysis rate; smoothed then decimated to FPS

# Ordered morph list written into voice_bank.json (column order of every frame row).
MORPHS = [
    "V_Open",
    "V_Explosive",
    "V_Dental_Lip",
    "V_Tight-O",
    "V_Tight",
    "V_Wide",
    "V_Affricate",
    "V_Lip_Open",
    "Jaw_Open",
    "Mouth_Smile_L",
    "Mouth_Smile_R",
    "Mouth_Frown_L",
    "Mouth_Frown_R",
    "Mouth_Pucker",
    "Mouth_Press_L",
    "Mouth_Press_R",
    "Mouth_Stretch_L",
    "Mouth_Stretch_R",
    "Brow_Raise_Inner_L",
    "Brow_Raise_Inner_R",
    "Brow_Raise_Outer_L",
    "Brow_Raise_Outer_R",
    "Brow_Drop_L",
    "Brow_Drop_R",
    "Cheek_Raise_L",
    "Cheek_Raise_R",
    "Eye_Squint_L",
    "Eye_Squint_R",
    "Eye_Blink_L",
    "Eye_Blink_R",
    "Nose_Sneer_L",
    "Nose_Sneer_R",
]
MI = {n: i for i, n in enumerate(MORPHS)}
LIPSYNC_MORPHS = [
    "V_Open",
    "V_Explosive",
    "V_Dental_Lip",
    "V_Tight-O",
    "V_Tight",
    "V_Wide",
    "V_Affricate",
    "V_Lip_Open",
    "Jaw_Open",
    "Mouth_Pucker",
]

# ---------------------------------------------------------------------------------------------
# Voice settings
# ---------------------------------------------------------------------------------------------
DEFAULT_VOICE = "Microsoft Zira Desktop"
SSML_RATE = "-8%"  # SAPI prosody rate (the ffmpeg pitch drop slows a further ~7 %)
SSML_PITCH = "-2st"  # SAPI honours this loosely; the real drop is the asetrate step below
PITCH_FACTOR = 0.93  # asetrate factor: ~-1.25 semitones and ~7 % slower -> older, heavier
VIBRATO_HZ, VIBRATO_CENTS = 5.2, 18.0  # shallow pitch wobble
TREMOLO_HZ, TREMOLO_DEPTH = 5.2, 0.07  # shallow amplitude wobble
HIGHPASS_HZ, LOWPASS_HZ = 90.0, 6800.0  # warmer, slightly duller timbre
# Timbre/pitch are done in numpy/scipy (ffmpeg 9's vibrato -> biquad chain intermittently
# latched to a full-scale DC rail on some lines). ffmpeg is used only for loudness.
FFMPEG_FILTER = f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample={SR}"

MOODS = ("happy", "smug", "annoyed", "determined", "surprised")


# ---------------------------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------------------------
def powershell_exe() -> str:
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell"


def list_voices() -> list[str]:
    out = subprocess.run(
        [powershell_exe(), "-NoProfile", "-File", str(HERE / "sapi_tts.ps1"), "-Jobs", "-", "-ListVoices"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def ssml_for(text: str, voice: str, mood: str) -> str:
    # Small per-mood nudges keep lines from sounding identical.
    rate = {"surprised": "-2%", "determined": "-5%", "annoyed": "-10%"}.get(mood, SSML_RATE)
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
        f'<voice name="{escape(voice)}"><prosody rate="{rate}" pitch="{SSML_PITCH}">'
        f"{escape(text)}</prosody></voice></speak>"
    )


def synthesize(lines: list[dict], voice: str, tmp: Path) -> dict[str, Path]:
    jobs, raw = [], {}
    for ln in lines:
        p = tmp / f"{ln['id']}_raw.wav"
        raw[ln["id"]] = p
        jobs.append({"ssml": ssml_for(ln["text"], voice, ln["mood"]), "out": str(p)})
    jf = tmp / "jobs.json"
    jf.write_text(json.dumps(jobs), encoding="utf-8")
    subprocess.run(
        [powershell_exe(), "-NoProfile", "-File", str(HERE / "sapi_tts.ps1"), "-Jobs", str(jf)],
        check=True,
        capture_output=True,
        text=True,
    )
    return raw


def trim_silence(x: np.ndarray, thresh_db: float = -45.0, pad_s: float = 0.06) -> np.ndarray:
    if x.size == 0:
        return x
    win = int(0.01 * SR)
    n = len(x) // win
    if n == 0:
        return x
    e = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(e / (np.max(e) + 1e-12))
    idx = np.where(db > thresh_db)[0]
    if idx.size == 0:
        return x
    pad = int(pad_s * SR)
    return x[max(0, idx[0] * win - pad) : min(len(x), (idx[-1] + 1) * win + pad)]


def postprocess(raw: Path, out: Path) -> None:
    sr, x = wavfile.read(raw)
    x = x.astype(np.float32) / 32768.0 if x.dtype == np.int16 else x.astype(np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        g = math.gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    x = trim_silence(x)
    x = older_voice(x)
    trimmed = out.with_suffix(".trim.wav")
    wavfile.write(trimmed, SR, (np.clip(x, -1, 1) * 32767).astype(np.int16))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(trimmed),
            "-af",
            FFMPEG_FILTER,
            "-ac",
            "1",
            "-ar",
            str(SR),
            "-c:a",
            "pcm_s16le",
            str(out),
        ],
        check=True,
    )
    trimmed.unlink(missing_ok=True)
    y = read_wav(out)
    rms = float(np.sqrt(np.mean(y**2)))
    if not (0.02 < rms < 0.4) or abs(float(np.mean(y))) > 0.05:
        raise RuntimeError(f"{out.name}: implausible output level rms={rms:.3f} dc={np.mean(y):.3f}")


def older_voice(x: np.ndarray) -> np.ndarray:
    """Pitch drop (tape-style resample), shallow vibrato + tremolo, gentle band-limit and low-mid warmth."""
    # Tape-style pitch drop: play SR*PITCH_FACTOR samples per second -> lower and slower.
    up, down = 100, int(round(100 * PITCH_FACTOR))
    x = resample_poly(x, up, down).astype(np.float64)
    n = len(x)
    t = np.arange(n) / SR
    # Vibrato via a modulated fractional delay; depth in samples for +-VIBRATO_CENTS.
    ratio = 2 ** (VIBRATO_CENTS / 1200) - 1
    depth = ratio * SR / (2 * np.pi * VIBRATO_HZ)
    pos = np.arange(n) - depth * (1 + np.sin(2 * np.pi * VIBRATO_HZ * t))
    x = np.interp(np.clip(pos, 0, n - 1), np.arange(n), x)
    x *= 1 - TREMOLO_DEPTH * (0.5 + 0.5 * np.sin(2 * np.pi * TREMOLO_HZ * t + 1.3))
    sos = np.vstack(
        [butter(2, HIGHPASS_HZ, "highpass", fs=SR, output="sos"), butter(4, LOWPASS_HZ, "lowpass", fs=SR, output="sos")]
    )
    y = sosfiltfilt(sos, x)
    warm = sosfiltfilt(butter(2, [160, 400], "bandpass", fs=SR, output="sos"), y)
    y = y + 0.35 * warm  # ~+2.5 dB around 250 Hz
    y /= max(1e-9, np.max(np.abs(y))) / 0.8
    return y.astype(np.float32)


def read_wav(p: Path) -> np.ndarray:
    sr, x = wavfile.read(p)
    assert sr == SR, f"{p} sr={sr}"
    x = x.astype(np.float32) / 32768.0
    return x if x.ndim == 1 else x.mean(axis=1)


# ---------------------------------------------------------------------------------------------
# Built-in audio-driven lip-sync
# ---------------------------------------------------------------------------------------------
def n_frames(duration_s: float) -> int:
    return max(1, int(round(duration_s * FPS)))


def attack_release(x: np.ndarray, rate_hz: float, attack_s: float = 0.04, release_s: float = 0.08) -> np.ndarray:
    a_up = 1 - math.exp(-1 / (rate_hz * attack_s))
    a_dn = 1 - math.exp(-1 / (rate_hz * release_s))
    y = np.zeros_like(x)
    prev = np.zeros(x.shape[1:], dtype=x.dtype)
    for t in range(len(x)):
        a = np.where(x[t] > prev, a_up, a_dn)
        prev = prev + a * (x[t] - prev)
        y[t] = prev
    return y


def audio_features(x: np.ndarray):
    hop = SR // HOP_HZ
    win = 2 * hop  # ~16.7 ms hop, ~33 ms Hann window
    n = int(math.ceil(len(x) / hop))
    xp = np.pad(x, (win // 2, win + hop))
    w = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1 / SR)
    rms = np.zeros(n)
    cen = np.zeros(n)
    zcr = np.zeros(n)
    hf = np.zeros(n)
    lo = np.zeros(n)
    for i in range(n):
        seg = xp[i * hop : i * hop + win]
        rms[i] = math.sqrt(float(np.mean(seg**2)) + 1e-12)
        zcr[i] = np.mean(np.abs(np.diff(np.signbit(seg).astype(np.int8)))) * SR / 2
        spec = np.abs(np.fft.rfft(seg * w)) ** 2
        tot = spec[(freqs > 80) & (freqs < 10000)].sum() + 1e-12
        cen[i] = float((spec * freqs)[(freqs > 80) & (freqs < 10000)].sum() / tot)
        hf[i] = spec[(freqs >= 3500) & (freqs < 10000)].sum() / tot
        lo[i] = spec[(freqs >= 80) & (freqs < 900)].sum() / tot
    return rms, cen, zcr, hf, lo


def builtin_lipsync(x: np.ndarray, n_out: int) -> dict[str, np.ndarray]:
    rms, cen, zcr, hf, lo = audio_features(x)
    db = 20 * np.log10(rms + 1e-9)
    peak = np.percentile(db, 98)
    floor = max(np.percentile(db, 10), peak - 45)
    loud = np.clip((db - (floor + 6)) / max(peak - floor - 6, 1e-3), 0, 1) ** 0.8
    voiced = loud > 0.12

    # Vowel colour relative to this line's own voiced frames (absolute thresholds drift with
    # voice/timbre). Blend of spectral centroid and low-band share; top third -> spread lips
    # (V_Wide, "ee/eh"), bottom third -> rounded (V_Tight-O + pucker, "oo/oh"), middle -> V_Open.
    vmask = voiced if voiced.sum() >= 5 else np.ones_like(voiced)

    def rel(v):
        lo_p, hi_p = np.percentile(v[vmask], [15, 85])
        return np.clip((v - lo_p) / max(hi_p - lo_p, 1e-6), 0, 1)

    colour = 0.6 * rel(cen) + 0.4 * (1 - rel(lo))
    bright = np.clip((colour - 0.6) / 0.35, 0, 1)
    rounded = np.clip((0.35 - colour) / 0.3, 0, 1)
    noisy = np.clip((hf - 0.18) / 0.30, 0, 1) * np.clip((zcr - 1500) / 3000, 0, 1)
    sibilant = np.clip((hf - 0.45) / 0.3, 0, 1) * noisy

    n = len(rms)
    raw = {k: np.zeros(n) for k in LIPSYNC_MORPHS}
    open_ = loud * (1 - 0.6 * noisy)
    raw["Jaw_Open"] = 0.55 * open_ * (1 - 0.3 * bright)
    raw["V_Open"] = 0.55 * open_ * (1 - rounded) * (1 - 0.5 * bright)
    raw["V_Lip_Open"] = 0.25 * open_
    raw["V_Wide"] = 0.55 * open_ * bright
    raw["V_Tight-O"] = 0.55 * open_ * rounded
    raw["Mouth_Pucker"] = 0.30 * open_ * rounded
    raw["V_Dental_Lip"] = 0.55 * loud.clip(0.3, 1) * noisy * (1 - sibilant) * (loud > 0.05)
    raw["V_Affricate"] = 0.45 * sibilant * (loud > 0.05)

    # Silence between words: gently pressed lips.
    quiet = np.clip((0.12 - loud) / 0.12, 0, 1)
    raw["V_Tight"] = 0.30 * quiet

    # Plosives: sharp onset after >= ~50 ms of silence -> lips closed just before the burst.
    hist = int(0.05 * HOP_HZ)
    for i in range(hist, n):
        if voiced[i] and not voiced[i - hist : i].any() and loud[i] - loud[i - 1] > 0.25:
            for k, wgt in ((i - 4, 0.6), (i - 3, 0.9), (i - 2, 1.0), (i - 1, 0.9), (i, 0.4)):
                if 0 <= k < n:
                    raw["V_Explosive"][k] = max(raw["V_Explosive"][k], wgt)
                    raw["V_Tight"][k] = 0.0

    stack = np.stack([raw[k] for k in LIPSYNC_MORPHS], axis=1)
    sm = attack_release(stack, HOP_HZ)
    # Decimate to 30 Hz by sampling the smoothed track at frame centres.
    t_src = (np.arange(n) + 0.5) / HOP_HZ
    t_dst = (np.arange(n_out) + 0.5) / FPS
    out = {}
    for j, k in enumerate(LIPSYNC_MORPHS):
        out[k] = np.interp(t_dst, t_src, sm[:, j])
    return out


# ---------------------------------------------------------------------------------------------
# NVIDIA Audio2Face-3D adapter (ARKit-52 -> CC morphs)
# ---------------------------------------------------------------------------------------------
# Each ARKit shape contributes (cc_morph, gain); contributions are summed then clipped to 0..1.
# ARKit "Left" is the subject's own left, same convention as CC "_L".
ARKIT_TO_CC: dict[str, list[tuple[str, float]]] = {
    "jawOpen": [("Jaw_Open", 1.0), ("V_Open", 0.35)],
    "mouthClose": [("V_Explosive", 0.8)],
    "mouthFunnel": [("V_Tight-O", 1.0)],
    "mouthPucker": [("Mouth_Pucker", 1.0)],
    "mouthSmileLeft": [("Mouth_Smile_L", 1.0)],
    "mouthSmileRight": [("Mouth_Smile_R", 1.0)],
    "mouthFrownLeft": [("Mouth_Frown_L", 1.0)],
    "mouthFrownRight": [("Mouth_Frown_R", 1.0)],
    "mouthDimpleLeft": [("Mouth_Smile_L", 0.3)],
    "mouthDimpleRight": [("Mouth_Smile_R", 0.3)],
    "mouthStretchLeft": [("Mouth_Stretch_L", 1.0), ("V_Wide", 0.25)],
    "mouthStretchRight": [("Mouth_Stretch_R", 1.0), ("V_Wide", 0.25)],
    "mouthPressLeft": [("Mouth_Press_L", 1.0)],
    "mouthPressRight": [("Mouth_Press_R", 1.0)],
    "mouthRollLower": [("V_Dental_Lip", 0.6), ("V_Tight", 0.3)],
    "mouthRollUpper": [("V_Tight", 0.5)],
    "mouthShrugLower": [("V_Tight", 0.3)],
    "mouthShrugUpper": [("V_Affricate", 0.3)],
    "mouthUpperUpLeft": [("V_Lip_Open", 0.5), ("Nose_Sneer_L", 0.2)],
    "mouthUpperUpRight": [("V_Lip_Open", 0.5), ("Nose_Sneer_R", 0.2)],
    "mouthLowerDownLeft": [("V_Lip_Open", 0.5)],
    "mouthLowerDownRight": [("V_Lip_Open", 0.5)],
    "browInnerUp": [("Brow_Raise_Inner_L", 1.0), ("Brow_Raise_Inner_R", 1.0)],
    "browOuterUpLeft": [("Brow_Raise_Outer_L", 1.0)],
    "browOuterUpRight": [("Brow_Raise_Outer_R", 1.0)],
    "browDownLeft": [("Brow_Drop_L", 1.0)],
    "browDownRight": [("Brow_Drop_R", 1.0)],
    "cheekSquintLeft": [("Cheek_Raise_L", 1.0)],
    "cheekSquintRight": [("Cheek_Raise_R", 1.0)],
    "eyeSquintLeft": [("Eye_Squint_L", 1.0)],
    "eyeSquintRight": [("Eye_Squint_R", 1.0)],
    "eyeBlinkLeft": [("Eye_Blink_L", 1.0)],
    "eyeBlinkRight": [("Eye_Blink_R", 1.0)],
    "noseSneerLeft": [("Nose_Sneer_L", 1.0)],
    "noseSneerRight": [("Nose_Sneer_R", 1.0)],
    # Not mapped (no matching CC morph in our list): cheekPuff, jawForward, jawLeft, jawRight,
    # mouthLeft, mouthRight, eyeLook*, eyeWide*, tongueOut.
}


def map_arkit_frame(arkit: dict[str, float]) -> np.ndarray:
    row = np.zeros(len(MORPHS))
    for name, v in arkit.items():
        key = name.split(".")[-1].strip()
        key = key[0].lower() + key[1:] if key else key  # accept "JawOpen" / "blendShapes.jawOpen"
        for cc, gain in ARKIT_TO_CC.get(key, ()):
            row[MI[cc]] += gain * float(v)
    return np.clip(row, 0, 1)


def load_a2f_track(path: Path) -> tuple[list[dict[str, float]], float]:
    """Return (per-frame ARKit dicts, fps). Supports A2F CSV and A2F JSON blendshape exports."""
    if path.suffix.lower() == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        names = d.get("facsNames") or d.get("names")
        mat = d.get("weightMat") or d.get("weights")
        fps = float(d.get("exportFps") or d.get("fps") or 30)
        return [dict(zip(names, row)) for row in mat], fps
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return [], FPS
    tkey = next((k for k in rows[0] if k.lower().replace(" ", "") in ("timecode", "time", "time_s", "timestamp")), None)
    frames, times = [], []
    for r in rows:
        d = {}
        for k, v in r.items():
            if k == tkey or v in (None, ""):
                continue
            try:
                d[k] = float(v)
            except ValueError:
                pass
        frames.append(d)
        if tkey:
            times.append(float(r[tkey]))
    fps = FPS
    if len(times) > 1 and times[1] > times[0]:
        fps = 1.0 / float(np.median(np.diff(times)))
    return frames, fps


def a2f_curves(path: Path, n_out: int) -> np.ndarray:
    frames, fps = load_a2f_track(path)
    if not frames:
        raise ValueError(f"empty A2F track {path}")
    src = np.stack([map_arkit_frame(f) for f in frames])
    t_src = np.arange(len(src)) / fps
    t_dst = np.arange(n_out) / FPS
    return np.stack([np.interp(t_dst, t_src, src[:, j]) for j in range(len(MORPHS))], axis=1)


# ---------------------------------------------------------------------------------------------
# Mood layer + blinks
# ---------------------------------------------------------------------------------------------
MOOD_SHAPES: dict[str, dict[str, float]] = {
    "happy": {
        "Mouth_Smile_L": 0.55,
        "Mouth_Smile_R": 0.55,
        "Cheek_Raise_L": 0.45,
        "Cheek_Raise_R": 0.45,
        "Eye_Squint_L": 0.15,
        "Eye_Squint_R": 0.15,
        "Brow_Raise_Inner_L": 0.15,
        "Brow_Raise_Inner_R": 0.15,
    },
    "smug": {
        "Mouth_Smile_L": 0.55,
        "Mouth_Smile_R": 0.12,
        "Cheek_Raise_L": 0.3,
        "Brow_Raise_Outer_L": 0.5,
        "Brow_Drop_R": 0.2,
        "Eye_Squint_R": 0.2,
        "Eye_Squint_L": 0.1,
    },
    "annoyed": {
        "Brow_Drop_L": 0.5,
        "Brow_Drop_R": 0.5,
        "Nose_Sneer_L": 0.22,
        "Nose_Sneer_R": 0.22,
        "Mouth_Press_L": 0.3,
        "Mouth_Press_R": 0.3,
        "Mouth_Frown_L": 0.25,
        "Mouth_Frown_R": 0.25,
    },
    "determined": {
        "Brow_Drop_L": 0.45,
        "Brow_Drop_R": 0.45,
        "Eye_Squint_L": 0.4,
        "Eye_Squint_R": 0.4,
        "Mouth_Press_L": 0.15,
        "Mouth_Press_R": 0.15,
        "Mouth_Stretch_L": 0.12,
        "Mouth_Stretch_R": 0.12,
    },
    "surprised": {
        "Brow_Raise_Inner_L": 0.6,
        "Brow_Raise_Inner_R": 0.6,
        "Brow_Raise_Outer_L": 0.55,
        "Brow_Raise_Outer_R": 0.55,
        "V_Open": 0.12,
        "Jaw_Open": 0.08,
    },
}


def seeded_rng(line_id: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha1(line_id.encode()).hexdigest()[:8], 16))


def mood_layer(mood: str, n: int, rng: np.random.Generator) -> np.ndarray:
    out = np.zeros((n, len(MORPHS)))
    t = np.arange(n) / FPS
    dur = n / FPS
    ease_in = np.clip(t / 0.25, 0, 1)
    ease_out = np.clip((dur - t) / 0.35, 0, 1)
    env = (np.sin(np.pi / 2 * np.minimum(ease_in, 1)) ** 2) * (0.35 + 0.65 * ease_out)  # hold a little at end
    phase = rng.uniform(0, 2 * np.pi)
    wobble = 1 + 0.08 * np.sin(2 * np.pi * 0.7 * t + phase)
    for k, v in MOOD_SHAPES[mood].items():
        out[:, MI[k]] = v * env * wobble
    return out


def blink_layer(n: int, rng: np.random.Generator) -> np.ndarray:
    out = np.zeros((n, len(MORPHS)))
    shape = np.array([0.35, 0.9, 1.0, 0.55, 0.15]) * 0.9  # ~165 ms at 30 Hz
    t = rng.uniform(0.4, 1.6)
    while t < n / FPS:
        f0 = int(t * FPS)
        for i, v in enumerate(shape):
            if f0 + i < n:
                out[f0 + i, MI["Eye_Blink_L"]] = max(out[f0 + i, MI["Eye_Blink_L"]], v)
                out[f0 + i, MI["Eye_Blink_R"]] = max(out[f0 + i, MI["Eye_Blink_R"]], v * 0.97)
        t += rng.uniform(2.5, 5.0)
    return out


def build_frames(line: dict, wav: Path, duration: float, a2f_dir: Path | None) -> tuple[np.ndarray, str]:
    n = n_frames(duration)
    rng = seeded_rng(line["id"])
    src = "builtin"
    base = None
    if a2f_dir is not None:
        for ext in (".csv", ".json"):
            p = a2f_dir / f"{line['id']}{ext}"
            if p.exists():
                base, src = a2f_curves(p, n), "a2f"
                break
    if base is None:
        lip = builtin_lipsync(read_wav(wav), n)
        base = np.zeros((n, len(MORPHS)))
        for k, v in lip.items():
            base[:, MI[k]] = v
        base = np.maximum(base, blink_layer(n, rng))
    mood = mood_layer(line["mood"], n, rng)
    if line["mood"] == "smug" and rng.random() < 0.5:  # mirror the lopsided smirk half the time
        swap = {"_L": "_R", "_R": "_L"}
        perm = [MI[m[:-2] + swap[m[-2:]]] if m[-2:] in swap else i for i, m in enumerate(MORPHS)]
        mood = mood[:, perm]
    frames = np.maximum(base, mood) if src == "a2f" else np.clip(base + mood, 0, 1)
    # Lip shapes compete with mouth-press/smile; damp mood mouth while the jaw is open.
    if src == "builtin":
        jaw = frames[:, MI["Jaw_Open"]]
        for k in ("Mouth_Press_L", "Mouth_Press_R"):
            frames[:, MI[k]] *= np.clip(1 - 1.5 * jaw, 0.2, 1)
    return np.clip(np.nan_to_num(frames), 0, 1), src


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------
def plot_preview(bank: dict, ids: list[str], path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib missing; skipping preview")
        return
    lines = [ln for ln in bank["lines"] if ln["id"] in ids]
    fig, axes = plt.subplots(len(lines), 2, figsize=(14, 3.6 * len(lines)), squeeze=False)
    groups = [
        ["Jaw_Open", "V_Open", "V_Wide", "V_Tight-O", "V_Explosive", "V_Dental_Lip", "V_Affricate", "V_Tight"],
        None,
    ]
    for r, ln in enumerate(lines):
        fr = np.array(ln["frames"])
        t = np.arange(len(fr)) / FPS
        sr, x = wavfile.read(DEFAULT_OUT / ln["wav"]) if (DEFAULT_OUT / ln["wav"]).exists() else (SR, np.zeros(1))
        ax = axes[r][0]
        tx = np.arange(len(x)) / SR
        ax.plot(tx, x / 32768.0 * 0.5 - 0.15, color="0.8", lw=0.5, label="audio")
        for m in groups[0]:
            ax.plot(t, fr[:, MI[m]], lw=1.4, label=m)
        ax.set_title(f'{ln["id"]} [{ln["mood"]}] lips: "{ln["text"]}"', fontsize=9)
        ax.set_ylim(-0.3, 1)
        ax.legend(fontsize=7, ncol=3, loc="upper right")
        ax = axes[r][1]
        active = [m for m in MORPHS if m not in groups[0] and fr[:, MI[m]].max() > 0.02]
        for m in active:
            ax.plot(t, fr[:, MI[m]], lw=1.2, label=m)
        ax.set_title(f"{ln['id']} expression + blinks", fontsize=9)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=7, ncol=2, loc="upper right")
    for ax in axes.flat:
        ax.set_xlabel("s")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    print(f"preview -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", type=Path, default=HERE / "lines.json")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="SAPI voice name (see --list-voices)")
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument(
        "--a2f-csv",
        type=Path,
        default=None,
        help="folder of Audio2Face-3D ARKit tracks named <id>.csv or <id>.json; overrides built-in lip-sync",
    )
    ap.add_argument("--curves-only", action="store_true", help="reuse existing WAVs, recompute curves only")
    ap.add_argument("--only", default="", help="comma-separated ids to (re)bake; others kept from existing bank")
    ap.add_argument("--preview", default="swish_01,fall_02", help="ids to plot into curves_preview.png ('' = skip)")
    args = ap.parse_args()

    if args.list_voices:
        print("\n".join(list_voices()))
        return 0
    if not shutil.which("ffmpeg") and not args.curves_only:
        sys.exit("ffmpeg not on PATH")

    spec = json.loads(args.lines.read_text(encoding="utf-8"))
    lines = spec["lines"]
    for ln in lines:
        assert ln["mood"] in MOODS, ln
    only = {s for s in args.only.split(",") if s}
    todo = [ln for ln in lines if not only or ln["id"] in only]
    args.out.mkdir(parents=True, exist_ok=True)
    bank_path = args.out / "voice_bank.json"
    old = {}
    if bank_path.exists() and only:
        old = {ln["id"]: ln for ln in json.loads(bank_path.read_text(encoding="utf-8"))["lines"]}

    if not args.curves_only:
        voices = [v.split("|")[0] for v in list_voices()]
        if args.voice not in voices:
            sys.exit(f"voice '{args.voice}' not installed; have: {voices}")
        with tempfile.TemporaryDirectory() as td:
            raw = synthesize(todo, args.voice, Path(td))
            for ln in todo:
                postprocess(raw[ln["id"]], args.out / f"{ln['id']}.wav")
                print(f"tts  {ln['id']}")

    out_lines, srcs = [], {}
    for ln in lines:
        if ln not in todo and ln["id"] in old:
            out_lines.append(old[ln["id"]])
            continue
        wav = args.out / f"{ln['id']}.wav"
        x = read_wav(wav)
        dur = len(x) / SR
        frames, src = build_frames(ln, wav, dur, args.a2f_csv)
        srcs[src] = srcs.get(src, 0) + 1
        out_lines.append(
            {
                "id": ln["id"],
                "event": ln["event"],
                "text": ln["text"],
                "mood": ln["mood"],
                "wav": wav.name,
                "duration_s": round(dur, 3),
                "curve_source": src,
                "frames": [[round(float(v), 3) for v in row] for row in frames],
            }
        )
    bank = {"version": 1, "fps": FPS, "sample_rate": SR, "voice": args.voice, "morphs": MORPHS, "lines": out_lines}
    bank_path.write_text(json.dumps(bank, separators=(",", ":")), encoding="utf-8")
    print(f"bank -> {bank_path} ({len(out_lines)} lines, curve sources {srcs})")

    ok = verify(bank, args.out)
    if args.preview:
        plot_preview(bank, args.preview.split(","), HERE / "curves_preview.png")
    return 0 if ok else 1


def verify(bank: dict, out: Path) -> bool:
    ok, total = True, 0.0
    for ln in bank["lines"]:
        wav = out / ln["wav"]
        if not wav.exists():
            print(f"FAIL {ln['id']}: missing wav")
            ok = False
            continue
        sr, x = wavfile.read(wav)
        dur = len(x) / sr
        total += dur
        fr = np.array(ln["frames"], dtype=float)
        problems = []
        if sr != SR or x.dtype != np.int16 or x.ndim != 1:
            problems.append(f"format sr={sr} dtype={x.dtype} ndim={x.ndim}")
        xr = x.astype(np.float64) / 32768.0
        rms = float(np.sqrt(np.mean(xr**2)))
        if not (0.02 < rms < 0.4) or abs(float(np.mean(xr))) > 0.05:
            problems.append(f"audio level rms={rms:.3f} dc={np.mean(xr):.3f}")
        if abs(len(fr) - dur * FPS) > 1:
            problems.append(f"frames {len(fr)} vs {dur * FPS:.1f}")
        if fr.shape[1] != len(bank["morphs"]):
            problems.append("width")
        if not np.isfinite(fr).all():
            problems.append("NaN")
        if fr.min() < 0 or fr.max() > 1:
            problems.append("range")
        jaw = fr[:, MI["Jaw_Open"]].max()
        if not (0.2 <= jaw <= 0.85):
            problems.append(f"jaw peak {jaw:.2f}")
        if dur > 4.5:
            problems.append(f"long {dur:.2f}s")
        if problems:
            ok = False
            print(f"WARN {ln['id']}: {'; '.join(problems)}")
    by_event: dict[str, int] = {}
    for ln in bank["lines"]:
        by_event[ln["event"]] = by_event.get(ln["event"], 0) + 1
    allpk = np.concatenate([np.array(ln["frames"]) for ln in bank["lines"]]).max(axis=0)
    print(
        f"verify: {'OK' if ok else 'ISSUES'}  lines={len(bank['lines'])} total_audio={total:.1f}s by_event={by_event}"
    )
    print("peak per morph: " + ", ".join(f"{m}={p:.2f}" for m, p in zip(bank["morphs"], allpk)))
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
