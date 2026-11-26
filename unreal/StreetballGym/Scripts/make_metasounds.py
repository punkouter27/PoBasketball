"""Items 18/19: procedural MetaSounds for the court, headlessly (MetaSound Builder API).

    run_headless.ps1 -EditorArgs @("-run=pythonscript", "-script=<this file>")

Builds /Game/Project/Core/Audio/MetaSounds/MS_* and rewires DA_CourtAudioBank to them:
  * impact sounds (ball/floor, palm, shoe, rim, board, net) = the placeholder wave from make_audio_assets.py, low-passed
    and gained by the float input "Impact" (0..1, set per event by FCourtAudioPlayer), plus a synthesized body (thump /
    ring) whose level also follows Impact -> soft dribbles sound muffled, hard pounds bright and boomy;
  * CrowdCheer / CrowdGroan (filtered noise swells + falling "aww" voice), Grunt (formant-filtered saw),
  * Ambience (looping): traffic rumble, chirping birds, a distant siren sweep.
Swap any slot for a recorded sample later; the bank accepts any USoundBase.
"""
import unreal

PKG = "/Game/Project/Core/Audio/MetaSounds"
BANK = "/Game/Project/DataAssets/DA_CourtAudioBank"
bs = unreal.get_engine_subsystem(unreal.MetaSoundBuilderSubsystem)
ed = unreal.get_editor_subsystem(unreal.MetaSoundEditorSubsystem)
OK = unreal.MetaSoundBuilderResult.SUCCEEDED

# Biquad filter types (EBiquadFilterType order)
LOWPASS, HIGHPASS, BANDPASS = 0, 1, 2


def first(v):
    """Builder literal factories return (literal, data_type)."""
    return v[0] if isinstance(v, tuple) else v


def cn(ns, name, var=""):
    return unreal.MetasoundFrontendClassName(ns, name, var)


NODES = {
    "wave": (cn("UE", "Wave Player", "Mono"), 1),
    "sine": (cn("UE", "Sine", "Audio"), 1),
    "saw": (cn("UE", "Saw", "Audio"), 1),
    "lfo": (cn("UE", "LFO", "Audio"), 1),
    "noise": (cn("UE", "Noise", "Audio"), 1),
    "biquad": (cn("UE", "Biquad Filter", "Audio"), 2),
    "env_a": (cn("AD Envelope", "AD Envelope", "Audio"), 1),
    "env_f": (cn("AD Envelope", "AD Envelope", "Float"), 1),
    "maprange": (cn("MapRange", "MapRange", "Float"), 1),
    "mul_af": (cn("UE", "Multiply", "Audio by Float"), 1),
    "mul_a": (cn("UE", "Multiply", "Audio"), 1),
    "mul_f": (cn("UE", "Multiply", "Float"), 1),
    "add_a": (cn("UE", "Add", "Audio"), 1),
    "add_f": (cn("UE", "Add", "Float"), 1),
    "delay_t": (cn("UE", "Trigger Delay", ""), 1),
    "repeat": (cn("UE", "TriggerRepeat", ""), 1),
}


class G:
    """Small wrapper: nodes by kind, pins by name, literals by Python type."""

    def __init__(self, name, one_shot=True):
        self.name = name
        self.b, self.on_play, self.on_finished, self.outs, r = bs.create_source_builder(name, unreal.MetaSoundOutputAudioFormat.MONO, one_shot)
        assert r == OK, f"{name}: builder"
        self.audio_out = self.outs[0]
        self.count = 0

    def node(self, kind, **defaults):
        klass, ver = NODES[kind]
        r = None
        for v in (ver, 1, 2, 3, 0):
            h, r = self.b.add_node_by_class_name(klass, v)
            if r == OK:
                break
        if r != OK:
            raise RuntimeError(f"{self.name}: cannot add {kind}")
        for pin, v in defaults.items():
            self.set(h, pin.replace("_", " "), v)
        self.count += 1
        return h

    def inp(self, h, pin):
        x, r = self.b.find_node_input_by_name(h, pin)
        if r != OK:
            ins, _ = self.b.find_node_inputs(h)
            raise RuntimeError(f"{self.name}: no input '{pin}', have {[str(self.b.get_node_input_data(i)[0]) for i in ins]}")
        return x

    def out(self, h, pin):
        x, r = self.b.find_node_output_by_name(h, pin)
        if r != OK:
            outs, _ = self.b.find_node_outputs(h)
            raise RuntimeError(f"{self.name}: no output '{pin}', have {[str(self.b.get_node_output_data(o)[0]) for o in outs]}")
        return x

    def lit(self, v):
        if isinstance(v, bool):
            return first(bs.create_bool_meta_sound_literal(v))
        if isinstance(v, int):
            return first(bs.create_int_meta_sound_literal(v))
        if isinstance(v, float):
            return first(bs.create_float_meta_sound_literal(v))
        return first(bs.create_object_meta_sound_literal(v))

    def set(self, h, pin, v):
        r = self.b.set_node_input_default(self.inp(h, pin), self.lit(v))
        if r != OK:
            raise RuntimeError(f"{self.name}: cannot set {pin}")

    def link(self, src_h, src_pin, dst_h, dst_pin):
        o = src_h if not isinstance(src_pin, str) else self.out(src_h, src_pin)
        r = self.b.connect_nodes(o, self.inp(dst_h, dst_pin))
        if r != OK:
            raise RuntimeError(f"{self.name}: link {src_pin} -> {dst_pin}")

    def link_handle(self, out_handle, dst_h, dst_pin):
        r = self.b.connect_nodes(out_handle, self.inp(dst_h, dst_pin))
        if r != OK:
            raise RuntimeError(f"{self.name}: link handle -> {dst_pin}")

    def graph_float(self, name, default):
        h, r = self.b.add_graph_input_node(name, "Float", first(bs.create_float_meta_sound_literal(default)), False)
        assert r == OK, f"{self.name}: input {name}"
        return h

    def to_output(self, h, pin):
        r = self.b.connect_nodes(self.out(h, pin), self.audio_out)
        assert r == OK, f"{self.name}: output"

    def finish_after(self, h, pin):
        r = self.b.connect_nodes(self.out(h, pin), self.on_finished)
        assert r == OK, f"{self.name}: finished"

    def finish_after_seconds(self, seconds):
        d = self.node("delay_t")
        self.set(d, "Delay Time", float(seconds))
        self.link_handle(self.on_play, d, "In")
        self.finish_after(d, "Out")

    def save(self):
        asset, r = ed.build_to_asset(self.b, "Streetball", self.name, PKG)
        if r != OK or asset is None:
            raise RuntimeError(f"{self.name}: build_to_asset failed")
        unreal.log(f"METASOUND built {PKG}/{self.name} ({self.count} nodes)")
        return unreal.load_asset(f"{PKG}/{self.name}")


def maprange(g, src_handle, in_lo, in_hi, out_lo, out_hi):
    m = g.node("maprange")
    g.set(m, "In Range A", float(in_lo)); g.set(m, "In Range B", float(in_hi))
    g.set(m, "Out Range A", float(out_lo)); g.set(m, "Out Range B", float(out_hi))
    g.set(m, "Clamped", True)
    g.link_handle(src_handle, m, "In")
    return m


def impact_sound(name, wave_path, lpf_lo, lpf_hi, gain_lo, body_freq=None, body_decay=0.1, body_gain=0.5, body_freq_span=0.25, wave_len=0.6):
    """Wave layer (Impact + SurfaceHardness -> cutoff + gain) + optional sine body (Impact -> pitch + level)."""
    g = G(name)
    impact = g.graph_float("Impact", 0.5)
    hardness = g.graph_float("SurfaceHardness", 0.5)
    wave = unreal.load_asset(wave_path)
    w = g.node("wave")
    g.set(w, "Wave Asset", wave)
    g.link_handle(g.on_play, w, "Play")
    flt = g.node("biquad")
    g.set(flt, "Type", LOWPASS)
    g.link(w, "Out Mono", flt, "In")
    cutoff_base = maprange(g, impact, 0, 1, lpf_lo, lpf_hi)
    cutoff_hard = maprange(g, hardness, 0, 1, 0.75, 1.35)
    cutoff_mul = g.node("mul_f")
    g.link(cutoff_base, "Out Value", cutoff_mul, "PrimaryOperand")
    g.link(cutoff_hard, "Out Value", cutoff_mul, "AdditionalOperands")
    g.link(cutoff_mul, "Out", flt, "Cutoff Frequency")
    gain = g.node("mul_af")
    g.link(flt, "Out", gain, "PrimaryOperand")
    g.link(maprange(g, impact, 0, 1, gain_lo, 1.0), "Out Value", gain, "AdditionalOperands")
    mix = gain
    mix_pin = "Out"
    if body_freq:
        osc = g.node("sine")
        g.link(maprange(g, impact, 0, 1, body_freq * (1 - body_freq_span), body_freq * (1 + body_freq_span)), "Out Value", osc, "Frequency")
        env = g.node("env_a")
        g.set(env, "Attack Time", 0.002)
        g.set(env, "Decay Time", float(body_decay))
        g.link_handle(g.on_play, env, "Trigger")
        shaped = g.node("mul_a")
        g.link(osc, "Audio", shaped, "PrimaryOperand")
        g.link(env, "Out Envelope", shaped, "AdditionalOperands")
        lvl = g.node("mul_af")
        g.link(shaped, "Out", lvl, "PrimaryOperand")
        g.link(maprange(g, impact, 0, 1, 0.05 * body_gain, body_gain), "Out Value", lvl, "AdditionalOperands")
        add = g.node("add_a")
        g.link(gain, "Out", add, "PrimaryOperand")
        g.link(lvl, "Out", add, "AdditionalOperands")
        mix, mix_pin = add, "Out"
    g.to_output(mix, mix_pin)
    g.finish_after_seconds(wave_len)
    return g.save()


def noise_swell(name, filt_type, cutoff, q, attack, decay, gain, voice=None, wobble_hz=0.0):
    """Crowd: filtered noise with an AD swell, optional amplitude wobble and a falling vowel-ish sine ("aww")."""
    g = G(name)
    n = g.node("noise")
    f = g.node("biquad")
    g.set(f, "Type", filt_type)
    g.set(f, "Cutoff Frequency", float(cutoff))
    g.set(f, "Bandwidth", float(q))
    g.link(n, "Audio", f, "In")
    env = g.node("env_a")
    g.set(env, "Attack Time", float(attack)); g.set(env, "Decay Time", float(decay))
    g.link_handle(g.on_play, env, "Trigger")
    shaped = g.node("mul_a")
    g.link(f, "Out", shaped, "PrimaryOperand")
    g.link(env, "Out Envelope", shaped, "AdditionalOperands")
    out, pin = shaped, "Out"
    if wobble_hz > 0:
        lfo = g.node("lfo")
        g.set(lfo, "Frequency", float(wobble_hz))
        g.set(lfo, "Min Value", 0.55); g.set(lfo, "Max Value", 1.0)
        wob = g.node("mul_af")
        g.link(out, pin, wob, "PrimaryOperand")
        g.link(lfo, "Out", wob, "AdditionalOperands")
        out, pin = wob, "Out"
    lvl = g.node("mul_af")
    g.link(out, pin, lvl, "PrimaryOperand")
    g.set(lvl, "AdditionalOperands", float(gain))
    out, pin = lvl, "Out"
    if voice:
        f_hi, f_lo, vgain = voice
        fenv = g.node("env_f")
        g.set(fenv, "Attack Time", 0.05); g.set(fenv, "Decay Time", float(decay))
        g.link_handle(g.on_play, fenv, "Trigger")
        osc = g.node("saw")
        g.link(maprange(g, g.out(fenv, "Out Envelope"), 0, 1, f_lo, f_hi), "Out Value", osc, "Frequency")
        form = g.node("biquad")
        g.set(form, "Type", BANDPASS); g.set(form, "Cutoff Frequency", 750.0); g.set(form, "Bandwidth", 1.2)
        g.link(osc, "Audio", form, "In")
        venv = g.node("env_a")
        g.set(venv, "Attack Time", float(attack)); g.set(venv, "Decay Time", float(decay) * 0.8)
        g.link_handle(g.on_play, venv, "Trigger")
        vs = g.node("mul_a")
        g.link(form, "Out", vs, "PrimaryOperand")
        g.link(venv, "Out Envelope", vs, "AdditionalOperands")
        vl = g.node("mul_af")
        g.link(vs, "Out", vl, "PrimaryOperand")
        g.set(vl, "AdditionalOperands", float(vgain))
        add = g.node("add_a")
        g.link(out, pin, add, "PrimaryOperand")
        g.link(vl, "Out", add, "AdditionalOperands")
        out, pin = add, "Out"
    g.to_output(out, pin)
    g.finish_after_seconds(attack + decay + 0.2)
    return g.save()


def grunt(name):
    """Effort grunt: low saw through two vowel formants, fast AD."""
    g = G(name)
    impact = g.graph_float("Impact", 0.5)
    osc = g.node("saw")
    g.link(maprange(g, impact, 0, 1, 190.0, 240.0), "Out Value", osc, "Frequency")
    f1 = g.node("biquad")
    g.set(f1, "Type", BANDPASS); g.set(f1, "Cutoff Frequency", 650.0); g.set(f1, "Bandwidth", 1.0)
    f2 = g.node("biquad")
    g.set(f2, "Type", BANDPASS); g.set(f2, "Cutoff Frequency", 1100.0); g.set(f2, "Bandwidth", 1.0)
    g.link(osc, "Audio", f1, "In")
    g.link(osc, "Audio", f2, "In")
    both = g.node("add_a")
    g.link(f1, "Out", both, "PrimaryOperand")
    g.link(f2, "Out", both, "AdditionalOperands")
    env = g.node("env_a")
    g.set(env, "Attack Time", 0.015); g.set(env, "Decay Time", 0.22)
    g.link_handle(g.on_play, env, "Trigger")
    s = g.node("mul_a")
    g.link(both, "Out", s, "PrimaryOperand")
    g.link(env, "Out Envelope", s, "AdditionalOperands")
    lvl = g.node("mul_af")
    g.link(s, "Out", lvl, "PrimaryOperand")
    g.set(lvl, "AdditionalOperands", 2.2)
    g.to_output(lvl, "Out")
    g.finish_after_seconds(0.4)
    return g.save()


def ambience(name):
    """Looping city bed: traffic rumble (LPF noise, slow swell) + bird chirps + a faint distant siren."""
    g = G(name, one_shot=False)
    # traffic
    n = g.node("noise")
    lp = g.node("biquad")
    g.set(lp, "Type", LOWPASS); g.set(lp, "Cutoff Frequency", 320.0)
    g.link(n, "Audio", lp, "In")
    swell = g.node("lfo")
    g.set(swell, "Frequency", 0.06); g.set(swell, "Min Value", 0.12); g.set(swell, "Max Value", 0.35)
    traffic = g.node("mul_af")
    g.link(lp, "Out", traffic, "PrimaryOperand")
    g.link(swell, "Out", traffic, "AdditionalOperands")
    # birds: high sine whose pitch follows a fast float envelope, chirped by a repeating AD envelope
    bird = g.node("sine")
    rep = g.node("repeat")
    g.set(rep, "Period", 1.7)
    g.link_handle(g.on_play, rep, "Start")
    benv = g.node("env_a")
    g.set(benv, "Attack Time", 0.01); g.set(benv, "Decay Time", 0.12)
    g.link(rep, "RepeatOut", benv, "Trigger")
    fenv = g.node("env_f")
    g.set(fenv, "Attack Time", 0.005); g.set(fenv, "Decay Time", 0.12)
    g.link(rep, "RepeatOut", fenv, "Trigger")
    g.link(maprange(g, g.out(fenv, "Out Envelope"), 0, 1, 3200.0, 4800.0), "Out Value", bird, "Frequency")
    chirp = g.node("mul_a")
    g.link(bird, "Audio", chirp, "PrimaryOperand")
    g.link(benv, "Out Envelope", chirp, "AdditionalOperands")
    chirp_l = g.node("mul_af")
    g.link(chirp, "Out", chirp_l, "PrimaryOperand")
    g.set(chirp_l, "AdditionalOperands", 0.05)
    # siren: wailing sine (vibrato via the Modulation input), gated by a very slow LFO so it comes and goes
    siren = g.node("sine")
    g.set(siren, "Frequency", 760.0)
    gate = g.node("lfo")
    g.set(gate, "Frequency", 0.021); g.set(gate, "Min Value", 0.0); g.set(gate, "Max Value", 0.018)
    sir = g.node("mul_af")
    g.link(siren, "Audio", sir, "PrimaryOperand")
    g.link(gate, "Out", sir, "AdditionalOperands")
    mix1 = g.node("add_a")
    g.link(traffic, "Out", mix1, "PrimaryOperand")
    g.link(chirp_l, "Out", mix1, "AdditionalOperands")
    mix2 = g.node("add_a")
    g.link(mix1, "Out", mix2, "PrimaryOperand")
    g.link(sir, "Out", mix2, "AdditionalOperands")
    g.to_output(mix2, "Out")
    return g.save()


def discover():
    """Log every node kind's pins (helps when an engine update renames one)."""
    g = G("MS_Discover")
    for kind in NODES:
        try:
            h = g.node(kind)
            ins, _ = g.b.find_node_inputs(h)
            outs, _ = g.b.find_node_outputs(h)
            unreal.log(f"METASOUND NODE {kind}: in={[str(g.b.get_node_input_data(i)[0]) + ':' + str(g.b.get_node_input_data(i)[1]) for i in ins]} "
                       f"out={[str(g.b.get_node_output_data(o)[0]) + ':' + str(g.b.get_node_output_data(o)[1]) for o in outs]}")
        except Exception as e:
            unreal.log_warning(f"METASOUND NODE {kind}: {e}")


def main():
    unreal.EditorAssetLibrary.make_directory(PKG)
    discover()
    A = "/Game/Project/Core/Audio/"
    built = {
        "BallFloor": impact_sound("MS_BallFloor", A + "SW_BallFloor", 900.0, 9000.0, 0.35, body_freq=85.0, body_decay=0.11, body_gain=0.7, wave_len=0.4),
        "BallPalm": impact_sound("MS_BallPalm", A + "SW_BallPalm", 1500.0, 9000.0, 0.4, wave_len=0.2),
        "ShoeFloor": impact_sound("MS_ShoeFloor", A + "SW_ShoeFloor", 2500.0, 12000.0, 0.5, body_freq=2900.0, body_decay=0.06, body_gain=0.25, body_freq_span=0.15, wave_len=0.25),
        "BallRim": impact_sound("MS_BallRim", A + "SW_BallRim", 2000.0, 14000.0, 0.45, body_freq=640.0, body_decay=0.45, body_gain=0.45, body_freq_span=0.05, wave_len=0.7),
        "BallBoard": impact_sound("MS_BallBoard", A + "SW_BallBoard", 700.0, 7000.0, 0.4, body_freq=160.0, body_decay=0.12, body_gain=0.6, wave_len=0.4),
        "NetRattle": impact_sound("MS_NetRattle", A + "SW_NetRattle", 3000.0, 12000.0, 0.6, wave_len=0.8),
        "CrowdCheer": noise_swell("MS_CrowdCheer", BANDPASS, 1400.0, 1.6, 0.25, 2.2, 0.9, voice=(330.0, 260.0, 0.25), wobble_hz=7.0),
        "CrowdGroan": noise_swell("MS_CrowdGroan", LOWPASS, 700.0, 1.0, 0.15, 1.6, 0.7, voice=(260.0, 150.0, 0.4)),
        "Grunt": grunt("MS_Grunt"),
        "Ambience": ambience("MS_CityAmbience"),
    }
    bank = unreal.load_asset(BANK)
    if bank is None:
        raise SystemExit("METASOUNDS FAILED: run make_audio_assets.py first (no DA_CourtAudioBank)")
    for slot, asset in built.items():
        prop = {"BallFloor": "ball_floor", "BallPalm": "ball_palm", "ShoeFloor": "shoe_floor", "BallRim": "ball_rim", "BallBoard": "ball_board",
                "NetRattle": "net_rattle", "CrowdCheer": "crowd_cheer", "CrowdGroan": "crowd_groan", "Grunt": "grunt", "Ambience": "ambience"}[slot]
        bank.set_editor_property(prop, asset)
    unreal.EditorAssetLibrary.save_loaded_asset(bank)
    unreal.EditorAssetLibrary.save_directory(PKG)
    unreal.log(f"METASOUNDS OK {len(built)} sources, bank rewired")


main()
