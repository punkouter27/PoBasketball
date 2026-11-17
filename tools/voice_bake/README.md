# Grandma voice bake (offline)

Pre-baked trash talk for the grandma: 45 lines → WAV + 30 Hz face-morph curves. Nothing runs at
game time except "play `<id>.wav` and step its curve rows". No GPU or network is needed at bake time either.
The first `uv run` downloads numpy, scipy and matplotlib from PyPI.

| File | What |
|---|---|
| `lines.json` | Line text grouped by event key (`make`, `miss`, `swish`, `rim_out`, `scramble_start`, `scramble_save`, `fall`, `tier_up`, `idle`, `crossover`) + mood |
| `bake.py` | TTS → post-processing → curves → `voice_bank.json` + checks + preview plot |
| `sapi_tts.ps1` | Batch Windows SAPI (System.Speech) synthesizer that `bake.py` calls |
| `curves_preview.png` | Curves for 2 lines (lips on the left, expression and blinks on the right) |

Output: `unreal/StreetballGym/Content/Art/Exports/Voice/<id>.wav` (48 kHz mono s16, about -16 LUFS) and `voice_bank.json`.

## Re-bake

```
uv run tools/voice_bake/bake.py                      # everything (~2 min)
uv run tools/voice_bake/bake.py --only make_01,fall_02   # just these, other lines kept from the bank
uv run tools/voice_bake/bake.py --curves-only        # keep the WAVs, recompute the curves
```
The run fails (exit code 1) if a WAV is missing, the frame count is off from duration×30 by more than 1, there is a NaN or out-of-range weight,
the audio level is implausible, the jaw peak is outside 0.2–0.85, or a line is longer than 4.5 s.

## Change the voice / lines
- `uv run tools/voice_bake/bake.py --list-voices`, then `--voice "Microsoft Zira Desktop"`. Only SAPI5 "Desktop"
  voices (plus any installed SAPI voice packs) work through System.Speech. OneCore-only voices do not.
- Timbre settings are at the top of `bake.py`: `SSML_RATE`, `PITCH_FACTOR` (tape-style pitch drop, 0.93 ≈ −1.25 st and 7 % slower),
  vibrato and tremolo (5.2 Hz, shallow), high-pass and low-pass, and low-mid warmth. Loudness is set by the ffmpeg `loudnorm` I=-16.
- Edit `lines.json` and keep the ids stable (`<event>_NN`). Mood must be one of happy, smug, annoyed, determined, surprised.

## Curves
`morphs` gives the column order of every frame row. The values are Character Creator morph target weights (0..1) at `fps` = 30.
- Lips (built in): the RMS envelope drives `Jaw_Open`, `V_Open` and `V_Lip_Open`. A per-line relative vowel colour (spectral centroid + low-band share)
  splits between `V_Wide` (bright) and `V_Tight-O` + `Mouth_Pucker` (rounded). Noisy frames (high band + ZCR) drive `V_Dental_Lip`, and strong sibilants drive `V_Affricate`.
  A sharp onset after ≥50 ms of silence drives `V_Explosive` (lips closed before the burst). Silence drives `V_Tight`. Smoothing is a 40 ms attack / 80 ms release
  filter at 120 Hz, then sampled down to 30 Hz.
- Mood layer for the whole line, easing in over 0.25 s and partly out at the end. Smug lines get a one-sided smirk (mirrored at random per line).
- Blinks: about 165 ms, every 2.5–5 s, randomised from a seed built from the line id, so a re-bake gives the same blinks.

## Plugging in NVIDIA Audio2Face-3D later
1. Run A2F-3D on each `<id>.wav`. Use the baked WAVs so the timing matches. Export ARKit blendshape tracks as `<id>.csv`
   (header `timeCode,blendShapes.jawOpen,...`; any fps; the `blendShapes.` prefix and PascalCase names are accepted) or
   `<id>.json` (A2F JSON: `exportFps`, `facsNames`, `weightMat`).
2. `uv run tools/voice_bake/bake.py --curves-only --a2f-csv <dir>`. Lines that have a track use it (`curve_source: "a2f"`).
   Lines without one fall back to the built-in lip-sync. The mood layer is max-blended on top of A2F output, and A2F's own blinks are kept.
3. The mapping is `ARKIT_TO_CC` in `bake.py`: each ARKit shape adds `gain × weight` to one or more CC morphs, and the result is clipped to 0..1.
   These ARKit shapes are not mapped: cheekPuff, jawForward/Left/Right, mouthLeft/Right, eyeLook*, eyeWide*, tongueOut.

## voice_bank.json schema
```
{"version":1,"fps":30,"sample_rate":48000,"voice":"Microsoft Zira Desktop",
 "morphs":["V_Open",...32 names],
 "lines":[{"id":"make_01","event":"make","text":"...","mood":"happy","wav":"make_01.wav",
           "duration_s":2.66,"curve_source":"builtin","frames":[[w0..w31], ...]}]}
```
`len(frames) == round(duration_s*30)`. Row `i` covers time `i/30` s from the start of the WAV.
