"""
PicoCalc Synthesizer 4.0
Full-featured synthesizer with piano keyboard, ADSR envelope,
arpeggiator, step sequencer, LFO effects, and preset system.

Controls (all pages):
  Tab     - Cycle pages (PLAY/SEQ/ARP/SET)
  Up/Down - Octave shift
  ESC     - Exit

PLAY page piano keys:
  Z X C V B N M       - White keys C D E F G A B
  S D   G H J         - Black keys C# D# F# G# A#
  Q W E R T Y U       - Upper octave white keys
  1-0 number row      - Upper octave (sharps + fills)
  Space               - Toggle sustain hold
  Left/Right           - Volume
"""
import picocalc
import math
import utime
import gc
import json
import os
from machine import Pin, PWM

gc.collect()

# -- Constants -------------------------------------------------------

# Audio pins
AUDIO_L = 28
AUDIO_R = 27

# Note names
NOTE_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

# Pre-compute frequency table: MIDI 24 (C1) through 108 (C8)
FREQ_TABLE = [int(440.0 * (2.0 ** ((m - 69) / 12.0)) + 0.5) for m in range(24, 109)]

# Quarter-period sine lookup (17 entries, values 0-1000)
SINE_Q = [int(math.sin(math.pi / 2 * i / 16) * 1000) for i in range(17)]

def _lfo_sine(phase_64):
    q = phase_64 & 15
    if phase_64 & 16:
        q = 15 - q
    val = SINE_Q[q]
    if phase_64 & 32:
        val = -val
    return val

# Waveform definitions: (name, base_duty, is_sweep)
WAVEFORMS = [
    ("Square",  32768, False),
    ("Pulse25", 16384, False),
    ("Pulse12",  8192, False),
    ("Wide",    49152, False),
    ("PWM Swp",     0, True),
]

# Chord intervals (semitones from root)
CHORDS = {
    'Maj':   (0, 4, 7),
    'Min':   (0, 3, 7),
    '7th':   (0, 4, 7, 10),
    'Min7':  (0, 3, 7, 10),
    'Dim':   (0, 3, 6),
    'Aug':   (0, 4, 8),
    'Oct':   (0, 12),
    'Pwr':   (0, 7, 12),
}
CHORD_NAMES = list(CHORDS.keys())

# Arp pattern types
ARP_PATTERNS = ('Up', 'Down', 'UpDn', 'Rand')

# Grayscale palette (avoid shades 1-2 which look olive on ILI9488)
BG     = 0
PNL    = 3
HDR    = 4
BRD    = 6
LBL    = 8
BAR    = 12
TXT    = 15

# ADSR states
_IDLE      = 0
_ATTACK    = 1
_DECAY     = 2
_SUSTAIN   = 3
_RELEASE   = 4
_RETRIGGER = 5  # brief silence before new note to prevent click

# Audio quality
_DUTY_CEILING = 58000  # soft cap to avoid harshest square edges
_MIN_RELEASE  = 10     # ms, floor to prevent click on note-off
_RETRIGGER_MS = 3      # ms of silence between notes

# Instruments
INST_PIANO  = 0
INST_ORGAN  = 1
INST_STRING = 2
INST_SYNTH  = 3
INST_NAMES = ("Piano", "Organ", "Strings", "Synth")

# Output modes
_OUT_HP   = 0
_OUT_SPK  = 1
_OUT_BOTH = 2
_OUT_NAMES = ("HP", "SPK", "BOTH")
_OUT_VOLS  = (7000, 10000, 8000)  # x10000 scaling

# Pages
PG_PLAY = 0
PG_SEQ  = 1
PG_ARP  = 2
PG_SET  = 3
PAGE_NAMES = ("PLAY", "SEQ", "ARP", "SET")

# Key escape sequences
_K_UP    = b'\x1b[A'
_K_DOWN  = b'\x1b[B'
_K_LEFT  = b'\x1b[D'
_K_RIGHT = b'\x1b[C'
_K_ESC   = b'\x1b\x1b'

# Piano key mapping: byte -> (note_index 0-11, octave_offset 0 or 1)
PIANO_MAP = {
    ord('z'): (0, 0), ord('x'): (2, 0), ord('c'): (4, 0),
    ord('v'): (5, 0), ord('b'): (7, 0), ord('n'): (9, 0), ord('m'): (11, 0),
    ord('s'): (1, 0), ord('d'): (3, 0),
    ord('g'): (6, 0), ord('h'): (8, 0), ord('j'): (10, 0),
    ord('q'): (0, 1), ord('w'): (2, 1), ord('e'): (4, 1),
    ord('r'): (5, 1), ord('t'): (7, 1), ord('y'): (9, 1), ord('u'): (11, 1),
    ord('1'): (0, 1),  ord('2'): (1, 1), ord('3'): (3, 1),
    ord('4'): (4, 1),  ord('5'): (6, 1), ord('6'): (8, 1),
    ord('7'): (10, 1), ord('8'): (0, 2), ord('9'): (2, 2), ord('0'): (4, 2),
}

# Preset directory
PRESET_DIR = "/sd/synth_presets"

# Built-in presets
BUILTIN_PRESETS = {
    'Lead':  {'wf': 0, 'adsr': [10, 50, 70, 100],  'lr': 60, 'ld': 10, 'lv': 1, 'lt': 0, 'det': 3, 'vol': 80, 'ar': 400},
    'Pad':   {'wf': 3, 'adsr': [200, 300, 90, 500], 'lr': 30, 'ld': 20, 'lv': 1, 'lt': 0, 'det': 5, 'vol': 70, 'ar': 1500},
    'Bass':  {'wf': 1, 'adsr': [5, 80, 60, 150],    'lr': 0,  'ld': 0,  'lv': 0, 'lt': 0, 'det': 2, 'vol': 90, 'ar': 300},
    'Pluck': {'wf': 0, 'adsr': [5, 30, 0, 50],      'lr': 0,  'ld': 0,  'lv': 0, 'lt': 0, 'det': 0, 'vol': 85, 'ar': 200},
    'Wobble':{'wf': 4, 'adsr': [10, 100, 80, 200],   'lr': 80, 'ld': 80, 'lv': 0, 'lt': 1, 'det': 4, 'vol': 75, 'ar': 600},
}


# -- SynthEngine -----------------------------------------------------

class SynthEngine:
    def __init__(self):
        self.pwm_l = PWM(Pin(AUDIO_L))
        self.pwm_r = PWM(Pin(AUDIO_R))
        self.pwm_l.duty_u16(0)
        self.pwm_r.duty_u16(0)

        # Note state
        self.midi_note = 69  # A4
        self.base_freq = 440
        self.octave = 4

        # Waveform
        self.wf_idx = 0
        self.sweep_phase = 0

        # ADSR
        self.adsr_state = _IDLE
        self.a_ms = 20
        self.d_ms = 100
        self.s_pct = 80
        self.r_ms = 200
        self.phase_start = 0
        self.current_duty = 0
        self.release_duty = 0
        self.max_duty = 32768

        # LFO
        self.lfo_rate = 60   # x10 Hz (6.0 Hz)
        self.lfo_depth = 10  # percent
        self.lfo_vib = True
        self.lfo_trem = False
        self.lfo_phase = 0

        # Volume / output
        self.volume = 80        # 0-100
        self.output = _OUT_HP
        self.detune = 3

        # Auto-release
        self.auto_release_ms = 500
        self.note_start = 0
        self.sustain_hold = False

        # Instrument mode
        self.instrument = INST_PIANO
        self._pitch_bend = 0      # cents of pitch bend (for piano attack)
        self._bend_start = 0

        # Retrigger state (anti-click)
        self._retrigger_midi = 0   # pending note for after retrigger gap

    def _calc_max_duty(self):
        out_vol = _OUT_VOLS[self.output]
        self.max_duty = 32768 * self.volume * out_vol // 1000000

    def _apply_instrument(self, midi):
        """Set engine params based on instrument + note pitch."""
        inst = self.instrument
        if inst == INST_PIANO:
            self.wf_idx = 2          # Pulse12 -- richest harmonics
            self.a_ms = 5
            # Freq-scaled decay: low notes=400ms, high notes=80ms
            self.d_ms = max(80, 400 - (midi - 24) * 4)
            self.s_pct = 12
            self.r_ms = max(60, 150 - midi // 2)
            self.detune = 4
            self.lfo_vib = False
            self.lfo_trem = False
            self.auto_release_ms = max(200, 800 - (midi - 24) * 6)
            # Pitch bend: start 1.5% sharp, drop to target over 25ms
            self._pitch_bend = 15    # x1000 (1.5%)
            self._bend_start = utime.ticks_ms()
        elif inst == INST_ORGAN:
            self.wf_idx = 0          # Square -- classic organ
            self.a_ms = 5
            self.d_ms = 10
            self.s_pct = 100         # Full sustain
            self.r_ms = 30           # Snappy release
            self.detune = 0
            self.lfo_vib = True
            self.lfo_trem = False
            self.lfo_rate = 50       # 5.0 Hz gentle vibrato
            self.lfo_depth = 5
            self.auto_release_ms = 2000
            self._pitch_bend = 0
        elif inst == INST_STRING:
            self.wf_idx = 3          # Wide -- mellow
            self.a_ms = 250          # Slow swell
            self.d_ms = 200
            self.s_pct = 85
            self.r_ms = 400
            self.detune = 6          # Heavy chorus
            self.lfo_vib = False
            self.lfo_trem = True
            self.lfo_rate = 40       # 4.0 Hz tremolo
            self.lfo_depth = 18
            self.auto_release_ms = 1500
            self._pitch_bend = 0
        # INST_SYNTH: user controls all params, no override

    def note_on(self, midi):
        # Anti-click: if already playing, brief silence before new note
        if self.adsr_state not in (_IDLE, _RETRIGGER) and self.current_duty > 500:
            self._retrigger_midi = midi
            self.adsr_state = _RETRIGGER
            self.phase_start = utime.ticks_ms()
            self.pwm_l.duty_u16(0)
            self.pwm_r.duty_u16(0)
            return

        self._start_note(midi)

    def _start_note(self, midi):
        self.midi_note = midi
        idx = midi - 24
        if idx < 0:
            idx = 0
        elif idx >= len(FREQ_TABLE):
            idx = len(FREQ_TABLE) - 1
        self.base_freq = FREQ_TABLE[idx]
        if self.instrument != INST_SYNTH:
            self._apply_instrument(midi)
        self._calc_max_duty()
        self.adsr_state = _ATTACK
        self.phase_start = utime.ticks_ms()
        self.note_start = self.phase_start
        self.current_duty = 0

    def note_off(self):
        if self.adsr_state not in (_IDLE, _RETRIGGER):
            self.release_duty = self.current_duty
            self.adsr_state = _RELEASE
            # Enforce minimum release to prevent click
            if self.r_ms < _MIN_RELEASE:
                self.r_ms = _MIN_RELEASE
            self.phase_start = utime.ticks_ms()

    def silence(self):
        self.adsr_state = _IDLE
        self.current_duty = 0
        self.pwm_l.duty_u16(0)
        self.pwm_r.duty_u16(0)

    def is_playing(self):
        return self.adsr_state not in (_IDLE, _RETRIGGER)

    def update(self, now):
        # Auto-release check
        if self.adsr_state in (_ATTACK, _DECAY, _SUSTAIN) and not self.sustain_hold:
            if utime.ticks_diff(now, self.note_start) > self.auto_release_ms:
                self.note_off()

        # Retrigger: brief silence gap, then start pending note
        if self.adsr_state == _RETRIGGER:
            if utime.ticks_diff(now, self.phase_start) >= _RETRIGGER_MS:
                self._start_note(self._retrigger_midi)
            else:
                return  # stay silent during gap

        # ADSR state machine
        if self.adsr_state == _IDLE:
            if self.current_duty > 0:
                self.current_duty = 0
                self.pwm_l.duty_u16(0)
                self.pwm_r.duty_u16(0)
            return

        elapsed = utime.ticks_diff(now, self.phase_start)

        if self.adsr_state == _ATTACK:
            if self.a_ms <= 0:
                progress = 1000
            else:
                progress = min(1000, elapsed * 1000 // self.a_ms)
            self.current_duty = self.max_duty * progress // 1000
            if progress >= 1000:
                self.adsr_state = _DECAY
                self.phase_start = now

        elif self.adsr_state == _DECAY:
            sustain_duty = self.max_duty * self.s_pct // 100
            if self.d_ms <= 0:
                progress = 1000
            else:
                progress = min(1000, elapsed * 1000 // self.d_ms)
            self.current_duty = self.max_duty - (self.max_duty - sustain_duty) * progress // 1000
            if progress >= 1000:
                self.adsr_state = _SUSTAIN

        elif self.adsr_state == _SUSTAIN:
            self.current_duty = self.max_duty * self.s_pct // 100

        elif self.adsr_state == _RELEASE:
            if self.r_ms <= 0:
                progress = 1000
            else:
                progress = min(1000, elapsed * 1000 // self.r_ms)
            self.current_duty = self.release_duty * (1000 - progress) // 1000
            if progress >= 1000:
                self.adsr_state = _IDLE
                self.current_duty = 0
                self.pwm_l.duty_u16(0)
                self.pwm_r.duty_u16(0)
                return

        # LFO
        if self.lfo_rate > 0 and (self.lfo_vib or self.lfo_trem):
            self.lfo_phase = (self.lfo_phase + self.lfo_rate) % 6400
            p64 = self.lfo_phase // 100
        else:
            p64 = 0

        # Calculate frequency with vibrato
        freq = self.base_freq

        # Piano pitch bend (starts sharp, drops to target over 25ms)
        if self._pitch_bend > 0:
            bend_elapsed = utime.ticks_diff(now, self._bend_start)
            if bend_elapsed < 25:
                bend = self._pitch_bend * (25 - bend_elapsed) // 25
                freq = freq + freq * bend // 1000
            else:
                self._pitch_bend = 0

        if self.lfo_vib and self.lfo_depth > 0 and self.lfo_rate > 0:
            mod = _lfo_sine(p64) * self.lfo_depth // 100
            freq = freq + freq * mod // 1000
        if freq < 20:
            freq = 20

        # Calculate duty with waveform + tremolo
        wf = WAVEFORMS[self.wf_idx]
        if wf[2]:  # PWM sweep
            self.sweep_phase = (self.sweep_phase + 3) % 64
            sweep_val = _lfo_sine(self.sweep_phase)
            base_duty = 32768 + sweep_val * 22
        else:
            base_duty = wf[1]

        # Scale duty by envelope
        duty = base_duty * self.current_duty // 32768

        # Apply tremolo
        if self.lfo_trem and self.lfo_depth > 0 and self.lfo_rate > 0:
            mod = _lfo_sine(p64) * self.lfo_depth // 200
            duty = duty * (1000 + mod) // 1000

        # Soft duty ceiling
        duty = max(0, min(_DUTY_CEILING, duty))

        # High freq attenuation for headphones
        if self.output == _OUT_HP and freq > 2000:
            duty = duty * 85 // 100

        # -- Stereo output with harmonic enrichment --
        self.pwm_l.freq(max(20, freq))
        self.pwm_l.duty_u16(duty)

        inst = self.instrument
        if inst == INST_PIANO:
            # R channel: octave up at 40% duty (upper partial)
            self.pwm_r.freq(max(20, freq * 2))
            self.pwm_r.duty_u16(duty * 40 // 100)
        elif inst == INST_ORGAN:
            # R channel: octave up at 60% duty (4' drawbar)
            self.pwm_r.freq(max(20, freq * 2))
            self.pwm_r.duty_u16(duty * 60 // 100)
        elif inst == INST_STRING:
            # R channel: perfect 5th up at 35% duty (orchestral richness)
            self.pwm_r.freq(max(20, freq * 3 // 2))
            self.pwm_r.duty_u16(duty * 35 // 100)
        else:
            # Synth: classic L/R detune
            self.pwm_r.freq(max(20, freq + self.detune))
            self.pwm_r.duty_u16(duty)

    def get_preset(self):
        return {
            'inst': self.instrument, 'wf': self.wf_idx,
            'adsr': [self.a_ms, self.d_ms, self.s_pct, self.r_ms],
            'lr': self.lfo_rate, 'ld': self.lfo_depth,
            'lv': 1 if self.lfo_vib else 0,
            'lt': 1 if self.lfo_trem else 0,
            'det': self.detune, 'vol': self.volume,
            'ar': self.auto_release_ms,
        }

    def load_preset(self, p):
        self.instrument = p.get('inst', INST_SYNTH)
        self.wf_idx = p.get('wf', 0)
        adsr = p.get('adsr', [20, 100, 80, 200])
        self.a_ms, self.d_ms, self.s_pct, self.r_ms = adsr
        self.lfo_rate = p.get('lr', 60)
        self.lfo_depth = p.get('ld', 10)
        self.lfo_vib = bool(p.get('lv', 1))
        self.lfo_trem = bool(p.get('lt', 0))
        self.detune = p.get('det', 3)
        self.volume = p.get('vol', 80)
        self.auto_release_ms = p.get('ar', 500)


# -- Arpeggiator -----------------------------------------------------

class Arpeggiator:
    def __init__(self, engine):
        self.engine = engine
        self.active = False
        self.bpm = 140
        self.pattern = 0       # index into ARP_PATTERNS
        self.chord_idx = 0     # index into CHORD_NAMES
        self.oct_range = 2
        self.notes = []
        self.step = 0
        self.direction = 1     # 1=up, -1=down (for UpDn)
        self.last_tick = 0
        self.root_note = 60    # C4

    def generate(self):
        chord = CHORDS[CHORD_NAMES[self.chord_idx]]
        self.notes = []
        for octave in range(self.oct_range):
            for interval in chord:
                n = self.root_note + interval + octave * 12
                if 24 <= n <= 108:
                    self.notes.append(n)
        if not self.notes:
            self.notes = [self.root_note]
        pat = ARP_PATTERNS[self.pattern]
        if pat == 'Down':
            self.notes.reverse()
        elif pat == 'Rand':
            pass  # will randomize in tick
        self.step = 0
        self.direction = 1

    def start(self, root_midi=None):
        if root_midi is not None:
            self.root_note = root_midi
        self.generate()
        self.active = True
        self.step = 0
        self.direction = 1
        self.last_tick = utime.ticks_ms()
        if self.notes:
            self.engine.note_on(self.notes[0])
            self.engine.sustain_hold = True

    def stop(self):
        self.active = False
        self.engine.sustain_hold = False
        self.engine.note_off()

    def tick(self, now):
        if not self.active or not self.notes:
            return False
        interval = 60000 // max(1, self.bpm)
        if utime.ticks_diff(now, self.last_tick) < interval:
            return False
        self.last_tick = now

        pat = ARP_PATTERNS[self.pattern]
        if pat == 'Rand':
            import urandom
            self.step = urandom.randint(0, len(self.notes) - 1)
        elif pat == 'UpDn':
            self.step += self.direction
            if self.step >= len(self.notes) - 1:
                self.step = len(self.notes) - 1
                self.direction = -1
            elif self.step <= 0:
                self.step = 0
                self.direction = 1
        else:
            self.step = (self.step + 1) % len(self.notes)

        self.engine.note_on(self.notes[self.step])
        self.engine.sustain_hold = True
        return True


# -- Sequencer --------------------------------------------------------

class Sequencer:
    def __init__(self, engine):
        self.engine = engine
        self.steps = bytearray(32)  # 16 steps x 2 bytes (midi_note, flags)
        self.bpm = 120
        self.playing = False
        self.recording = False
        self.play_step = 0
        self.cursor = 0
        self.last_tick = 0
        self.pattern_name = "default"
        # Init default pattern: all C4, inactive
        for i in range(16):
            self.steps[i * 2] = 60      # C4
            self.steps[i * 2 + 1] = 0   # inactive

    def get_note(self, step):
        return self.steps[step * 2]

    def is_active(self, step):
        return bool(self.steps[step * 2 + 1] & 1)

    def set_note(self, step, midi):
        self.steps[step * 2] = max(24, min(108, midi))

    def toggle_active(self, step):
        self.steps[step * 2 + 1] ^= 1

    def set_active(self, step, active):
        if active:
            self.steps[step * 2 + 1] |= 1
        else:
            self.steps[step * 2 + 1] &= ~1

    def record_note(self, midi):
        if self.recording and self.playing:
            self.set_note(self.play_step, midi)
            self.set_active(self.play_step, True)

    def start_play(self):
        self.playing = True
        self.play_step = 0
        self.last_tick = utime.ticks_ms()
        self._trigger_step()

    def stop_play(self):
        self.playing = False
        self.recording = False
        self.engine.note_off()

    def toggle_record(self):
        self.recording = not self.recording

    def _trigger_step(self):
        if self.is_active(self.play_step):
            midi = self.get_note(self.play_step)
            self.engine.note_on(midi)
            self.engine.sustain_hold = True
        else:
            self.engine.note_off()

    def tick(self, now):
        if not self.playing:
            return False
        interval = 60000 // max(1, self.bpm)
        if utime.ticks_diff(now, self.last_tick) < interval:
            return False
        self.last_tick = now
        self.play_step = (self.play_step + 1) % 16
        self._trigger_step()
        return True

    def save(self, name=None):
        if name:
            self.pattern_name = name
        try:
            os.mkdir(PRESET_DIR)
        except:
            pass
        path = PRESET_DIR + "/" + self.pattern_name + ".seq"
        with open(path, 'w') as f:
            json.dump({'s': list(self.steps), 'b': self.bpm}, f)

    def load(self, name):
        path = PRESET_DIR + "/" + name + ".seq"
        with open(path, 'r') as f:
            data = json.load(f)
        self.steps = bytearray(data['s'])
        self.bpm = data.get('b', 120)
        self.pattern_name = name


# -- SynthUI ----------------------------------------------------------

class SynthUI:
    def __init__(self, display, engine, arp, seq):
        self.d = display
        self.W = display.width
        self.H = display.height
        self.engine = engine
        self.arp = arp
        self.seq = seq
        self.page = PG_PLAY
        self._drawn_page = -1
        self._last_note = -1
        self._last_oct = -1
        self._last_duty = -1
        self._frame = 0
        self._scope_data = []

        # Settings page state
        self.set_cursor = 0
        self.set_params = [
            ("Instrmnt", 'instrument', 'inst', 0, 3, 1),
            ("Attack",   'a_ms',  'ms',  10, 500, 10),
            ("Decay",    'd_ms',  'ms',  10, 500, 10),
            ("Sustain",  's_pct', '%',   0,  100, 5),
            ("Release",  'r_ms',  'ms',  10, 1000, 10),
            ("LFO Rate", 'lfo_rate', '',  0, 200, 5),
            ("LFO Dep",  'lfo_depth', '%', 0, 100, 5),
            ("Vibrato",  'lfo_vib', 'bool', 0, 1, 1),
            ("Tremolo",  'lfo_trem', 'bool', 0, 1, 1),
            ("Waveform", 'wf_idx', 'wf', 0, 4, 1),
            ("Detune",   'detune', 'Hz', 0, 15, 1),
            ("Volume",   'volume', '%',  10, 100, 5),
            ("AutoRel",  'auto_release_ms', 'ms', 100, 2000, 50),
            ("Output",   'output', 'out', 0, 2, 1),
        ]

    def full_redraw(self):
        self.d.beginDraw()
        self.d.fill(BG)
        self._draw_header()
        if self.page == PG_PLAY:
            self._draw_play_static()
        elif self.page == PG_SEQ:
            self._draw_seq_static()
        elif self.page == PG_ARP:
            self._draw_arp_static()
        elif self.page == PG_SET:
            self._draw_set_page()
        self._draw_footer()
        self.d.show()
        self._drawn_page = self.page

    def draw_frame(self):
        self._frame += 1
        need_full = self.page != self._drawn_page
        if need_full:
            self.full_redraw()
            return

        self.d.beginDraw()
        if self.page == PG_PLAY:
            self._update_play()
        elif self.page == PG_SEQ:
            self._update_seq()
        elif self.page == PG_ARP:
            self._update_arp()
        elif self.page == PG_SET:
            self._draw_set_page_content()
        self._update_header_note()
        self.d.show()

    # -- Header / Footer --

    def _draw_header(self):
        self.d.fill_rect(0, 0, self.W, 18, HDR)
        self.d.text("SYNTH 4.0", 4, 5, TXT)
        # Page tabs
        tx = 76
        for i, name in enumerate(PAGE_NAMES):
            if i == self.page:
                self.d.text("[" + name + "]", tx, 5, TXT)
            else:
                self.d.text(" " + name + " ", tx, 5, BRD)
            tx += (len(name) + 2) * 6 + 2
        self._update_header_note()
        self.d.hline(0, 18, self.W, LBL)

    def _update_header_note(self):
        # Note display in header right area
        self.d.fill_rect(240, 1, 78, 16, HDR)
        e = self.engine
        if e.is_playing():
            ni = e.midi_note % 12
            o = e.midi_note // 12 - 1
            note_str = NOTE_NAMES[ni] + str(o)
            freq_str = str(e.base_freq)
        else:
            note_str = "Oct" + str(e.octave)
            freq_str = ""
        self.d.text(note_str, 242, 5, TXT)
        self.d.text(freq_str, 268, 5, BAR)

    def _draw_footer(self):
        self.d.fill_rect(0, 304, self.W, 16, HDR)
        self.d.hline(0, 303, self.W, LBL)
        if self.page == PG_PLAY:
            hints = "Tab:Pg \x18\x19:Oct I:Inst F:Wave Sp:Hold"
        elif self.page == PG_SEQ:
            hints = "Tab:Pg <>:Step \x18\x19:Note P:Play R:Rec"
        elif self.page == PG_ARP:
            hints = "Tab:Pg <>:Pat \x18\x19:Chord P:Play"
        elif self.page == PG_SET:
            hints = "Tab:Pg \x18\x19:Sel <>:Adj L:Load S:Save"
        self.d.text(hints, 4, 308, LBL)
        self.d.text("ESC:Quit", 268, 308, BRD)

    # -- PLAY page --

    def _draw_play_static(self):
        self._draw_wave_box()
        self._draw_adsr_box()
        self._draw_lfo_box()
        self._draw_scope_frame()
        self._draw_vol_bar()
        self._draw_piano()

    def _draw_wave_box(self):
        x, y, w, h = 4, 20, 90, 58
        self.d.rect(x, y, w, h, LBL)
        self.d.fill_rect(x + 1, y + 1, w - 2, h - 2, PNL)
        e = self.engine
        inst_name = INST_NAMES[e.instrument]
        self.d.text("INST", x + 4, y + 4, BRD)
        self.d.text(inst_name, x + 4, y + 16, TXT)
        if e.instrument == INST_SYNTH:
            wf_name = WAVEFORMS[e.wf_idx][0]
            self.d.text(wf_name, x + 4, y + 28, BAR)
        # Mini waveform preview
        self._draw_mini_wave(x + 4, y + 38, 80, 14)

    def _draw_mini_wave(self, x, y, w, h):
        mid = y + h // 2
        self.d.hline(x, mid, w, HDR)
        wf = WAVEFORMS[self.engine.wf_idx]
        duty_pct = wf[1] * 100 // 65536 if not wf[2] else 50
        seg = w // 3
        for cyc in range(3):
            cx = x + cyc * seg
            pw = seg * duty_pct // 100
            if pw < 2:
                pw = 2
            # High portion
            self.d.hline(cx, y + 2, pw, BAR)
            self.d.vline(cx + pw, y + 2, h - 4, BAR)
            # Low portion
            self.d.hline(cx + pw, y + h - 3, seg - pw, BAR)
            if cyc < 2:
                self.d.vline(cx + seg, mid - h // 2 + 2, h - 4, BAR)

    def _draw_adsr_box(self):
        x, y, w, h = 98, 20, 130, 58
        self.d.rect(x, y, w, h, LBL)
        self.d.fill_rect(x + 1, y + 1, w - 2, h - 2, PNL)
        self.d.text("ADSR", x + 4, y + 4, BRD)
        e = self.engine
        vals = [
            ('A', e.a_ms, 500),
            ('D', e.d_ms, 500),
            ('S', e.s_pct, 100),
            ('R', e.r_ms, 1000),
        ]
        bx = x + 8
        for i, (lbl, val, mx) in enumerate(vals):
            bxx = bx + i * 30
            bar_h = val * 34 // max(1, mx)
            bar_h = min(34, bar_h)
            # Bar background
            self.d.rect(bxx, y + 18, 22, 36, HDR)
            # Bar fill from bottom
            if bar_h > 0:
                self.d.fill_rect(bxx + 1, y + 53 - bar_h, 20, bar_h, BAR)
            # Label
            self.d.text(lbl, bxx + 8, y + 48, BRD)

    def _draw_lfo_box(self):
        x, y, w, h = 232, 20, 84, 58
        self.d.rect(x, y, w, h, LBL)
        self.d.fill_rect(x + 1, y + 1, w - 2, h - 2, PNL)
        self.d.text("LFO", x + 4, y + 4, BRD)
        e = self.engine
        # Vibrato LED
        self._draw_led(x + 6, y + 18, e.lfo_vib)
        self.d.text("VIB", x + 16, y + 18, TXT if e.lfo_vib else BRD)
        # Tremolo LED
        self._draw_led(x + 6, y + 30, e.lfo_trem)
        self.d.text("TRM", x + 16, y + 30, TXT if e.lfo_trem else BRD)
        # Rate
        rate_str = str(e.lfo_rate // 10) + "." + str(e.lfo_rate % 10)
        self.d.text("R:" + rate_str, x + 4, y + 44, LBL)
        # Depth
        self.d.text("D:" + str(e.lfo_depth) + "%", x + 44, y + 44, LBL)

    def _draw_led(self, x, y, on):
        if on:
            self.d.fill_rect(x, y, 6, 6, TXT)
            self.d.rect(x - 1, y - 1, 8, 8, LBL)
        else:
            self.d.fill_rect(x, y, 6, 6, HDR)
            self.d.rect(x - 1, y - 1, 8, 8, BRD)

    def _draw_scope_frame(self):
        x, y, w, h = 4, 82, 312, 76
        self.d.rect(x, y, w, h, LBL)
        self.d.rect(x + 1, y + 1, w - 2, h - 2, BRD)
        self.d.fill_rect(x + 2, y + 2, w - 4, h - 4, BG)
        mid = y + h // 2
        self.d.hline(x + 2, mid, w - 4, HDR)
        self.d.text("SCOPE", x + 4, y + 4, BRD)
        self._draw_scope_wave(x + 2, y + 2, w - 4, h - 4)

    def _draw_scope_wave(self, x, y, w, h):
        mid = y + h // 2
        e = self.engine
        if not e.is_playing():
            # Static waveform preview
            wf = WAVEFORMS[e.wf_idx]
            duty_pct = wf[1] * 100 // 65536 if not wf[2] else 50
            seg = w // 4
            amp = h // 2 - 4
            for cyc in range(4):
                cx = x + cyc * seg
                pw = max(2, seg * duty_pct // 100)
                self.d.hline(cx, mid - amp, pw, BAR)
                self.d.vline(cx + pw, mid - amp, amp * 2, BAR)
                self.d.hline(cx + pw, mid + amp, seg - pw, BAR)
                if cyc < 3:
                    self.d.vline(cx + seg, mid - amp, amp * 2, BAR)
            return

        # Animated scope when playing
        wf = WAVEFORMS[e.wf_idx]
        duty_pct = wf[1] * 100 // 65536 if not wf[2] else 50
        amp = (h // 2 - 4) * min(e.current_duty, e.max_duty) // max(1, e.max_duty)
        offset = (self._frame * 3) % 60
        seg = 60
        for cyc in range(-1, w // seg + 2):
            cx = x + cyc * seg - offset
            pw = max(2, seg * duty_pct // 100)
            x1 = max(x, cx)
            x2 = min(x + w, cx + pw)
            if x2 > x1:
                self.d.hline(x1, mid - amp, x2 - x1, TXT)
            vx = cx + pw
            if x <= vx < x + w:
                self.d.vline(vx, mid - amp, amp * 2, TXT)
            x3 = max(x, cx + pw)
            x4 = min(x + w, cx + seg)
            if x4 > x3:
                self.d.hline(x3, mid + amp, x4 - x3, TXT)
            vx2 = cx + seg
            if x <= vx2 < x + w:
                self.d.vline(vx2, mid - amp, amp * 2, TXT)

    def _draw_vol_bar(self):
        y = 162
        self.d.text("VOL", 4, y + 3, LBL)
        self.d.rect(28, y, 200, 14, BRD)
        self.d.fill_rect(29, y + 1, 198, 12, PNL)
        vol_w = self.engine.volume * 196 // 100
        self.d.fill_rect(30, y + 2, vol_w, 10, BAR)
        self.d.text(str(self.engine.volume) + "%", 232, y + 3, TXT)
        self.d.text(_OUT_NAMES[self.engine.output], 280, y + 3, LBL)

    def _draw_piano(self):
        self._draw_piano_at(4, 180, 312, 96, True)

    def _draw_piano_at(self, px, py, pw, ph, show_hints):
        # White keys
        wk_w = pw // 14
        wk_h = ph
        e = self.engine
        active_ni = e.midi_note % 12
        active_oct_off = 0
        if e.is_playing():
            key_oct = e.midi_note // 12 - 1
            base_oct = e.octave if hasattr(self, '_piano_base_oct') else e.octave
            active_oct_off = key_oct - base_oct
        self._piano_base_oct = e.octave

        # White key note indices for 2 octaves
        white_notes = [0, 2, 4, 5, 7, 9, 11, 0, 2, 4, 5, 7, 9, 11]
        white_oct   = [0, 0, 0, 0, 0, 0, 0,  1, 1, 1, 1, 1, 1, 1]

        for i in range(14):
            kx = px + i * wk_w
            ni = white_notes[i]
            oc = white_oct[i]
            pressed = e.is_playing() and ni == active_ni and oc == active_oct_off
            if pressed:
                self.d.fill_rect(kx + 1, py + 1, wk_w - 2, wk_h - 2, 10)
                self.d.rect(kx, py, wk_w, wk_h, TXT)
            else:
                self.d.fill_rect(kx + 1, py + 1, wk_w - 2, wk_h - 2, TXT)
                self.d.rect(kx, py, wk_w, wk_h, BRD)

        # Black keys
        bk_w = wk_w * 2 // 3
        bk_h = ph * 58 // 96
        # Black key positions: after white key index
        # Pattern per octave: 0(C#), 1(D#), skip, 3(F#), 4(G#), 5(A#)
        black_info = [
            (0, 1, 0), (1, 3, 0),
            (3, 6, 0), (4, 8, 0), (5, 10, 0),
            (7, 1, 1), (8, 3, 1),
            (10, 6, 1), (11, 8, 1), (12, 10, 1),
        ]
        for wki, ni, oc in black_info:
            bkx = px + wki * wk_w + wk_w - bk_w // 2
            pressed = e.is_playing() and ni == active_ni and oc == active_oct_off
            if pressed:
                self.d.fill_rect(bkx, py, bk_w, bk_h, LBL)
                self.d.rect(bkx, py, bk_w, bk_h, TXT)
            else:
                self.d.fill_rect(bkx, py, bk_w, bk_h, BG)
                self.d.rect(bkx, py, bk_w, bk_h, BRD)

        # Key hints
        if show_hints:
            hint_y = py + wk_h + 2
            hints_white = ['Z','X','C','V','B','N','M','Q','W','E','R','T','Y','U']
            for i, h in enumerate(hints_white):
                hx = px + i * wk_w + wk_w // 2 - 3
                self.d.text(h, hx, hint_y, BRD)

            hints_black = ['S','D','','G','H','J','S','D','','G','H','J']
            # Map hints to black key positions
            bk_hints = [
                (0, 'S'), (1, 'D'), (3, 'G'), (4, 'H'), (5, 'J'),
                (7, '2'), (8, '3'), (10, '5'), (11, '6'), (12, '7'),
            ]
            for wki, h in bk_hints:
                bkx = px + wki * wk_w + wk_w - bk_w // 2
                self.d.text(h, bkx + bk_w // 2 - 3, py + bk_h - 10, HDR)

    def _update_play(self):
        playing = self.engine.is_playing()

        # Scope: only redraw every 4th frame when playing, less when idle
        scope_interval = 4 if playing else 16
        if self._frame % scope_interval == 0:
            x, y, w, h = 6, 84, 308, 72
            self.d.fill_rect(x, y, w, h, BG)
            mid = y + h // 2
            self.d.hline(x, mid, w, HDR)
            if playing:
                pulse = (self._frame // 4) % 16
                self.d.rect(4, 82, 312, 76, pulse)
            else:
                self.d.rect(4, 82, 312, 76, LBL)
            self._draw_scope_wave(x, y, w, h)
            freq_str = str(self.engine.base_freq) + "Hz"
            self.d.text(freq_str, 250, 86, BRD)

        # Piano: redraw on note change or octave change
        cur_note = self.engine.midi_note if playing else -1
        cur_oct = self.engine.octave
        if cur_note != self._last_note or cur_oct != self._last_oct:
            self._last_note = cur_note
            self._last_oct = cur_oct
            self._draw_piano()

        # Volume bar: only every 16 frames
        if self._frame % 16 == 0:
            self._draw_vol_bar()

        # ADSR/wave/lfo: only every 32 frames (they rarely change)
        if self._frame % 32 == 0:
            self._draw_wave_box()
            self._draw_adsr_box()
            self._draw_lfo_box()

    # -- SEQ page --

    def _draw_seq_static(self):
        self._draw_seq_grid()
        self._draw_seq_transport()
        self._draw_scope_frame_mini(4, 182, 312, 60)
        self._draw_piano_at(4, 248, 312, 50, False)

    def _draw_seq_grid(self):
        cw, ch = 36, 62
        gap = 2
        for step in range(16):
            row = step // 8
            col = step % 8
            cx = 8 + col * (cw + gap)
            cy = 22 + row * (ch + gap + 4)

            is_play = self.seq.playing and step == self.seq.play_step
            is_cursor = step == self.seq.cursor
            active = self.seq.is_active(step)

            if is_play:
                self.d.fill_rect(cx, cy, cw, ch, BRD)
                self.d.rect(cx, cy, cw, ch, TXT)
            elif is_cursor:
                self.d.fill_rect(cx, cy, cw, ch, HDR)
                self.d.rect(cx, cy, cw, ch, BAR)
            else:
                self.d.fill_rect(cx, cy, cw, ch, PNL)
                self.d.rect(cx, cy, cw, ch, BRD)

            # Step number
            self.d.text(str(step + 1), cx + 2, cy + 2, LBL)

            if active:
                midi = self.seq.get_note(step)
                ni = midi % 12
                o = midi // 12 - 1
                nstr = NOTE_NAMES[ni] + str(o)
                self.d.text(nstr, cx + 6, cy + 22, TXT)
                # Activity bar at bottom
                self.d.fill_rect(cx + 2, cy + ch - 8, cw - 4, 4, BAR)
            else:
                self.d.text("---", cx + 8, cy + 22, HDR)

    def _draw_seq_transport(self):
        y = 158
        self.d.fill_rect(0, y, self.W, 20, BG)
        self.d.text("BPM:" + str(self.seq.bpm), 8, y + 4, TXT)

        # Play LED
        self._draw_led(90, y + 5, self.seq.playing)
        self.d.text("PLAY", 100, y + 4, BAR if self.seq.playing else BRD)

        # Rec LED
        self._draw_led(148, y + 5, self.seq.recording)
        self.d.text("REC", 158, y + 4, TXT if self.seq.recording else BRD)

        self.d.text(self.seq.pattern_name, 210, y + 4, LBL)

    def _draw_scope_frame_mini(self, x, y, w, h):
        self.d.rect(x, y, w, h, LBL)
        self.d.fill_rect(x + 1, y + 1, w - 2, h - 2, BG)
        mid = y + h // 2
        self.d.hline(x + 1, mid, w - 2, HDR)
        self._draw_scope_wave(x + 1, y + 1, w - 2, h - 2)

    def _update_seq(self):
        if self._frame % 4 == 0:
            self._draw_seq_grid()
            self._draw_seq_transport()
        if self._frame % 8 == 0:
            self._draw_scope_frame_mini(4, 182, 312, 60)
            self._draw_piano_at(4, 248, 312, 50, False)

    # -- ARP page --

    def _draw_arp_static(self):
        self._draw_arp_config()
        self._draw_arp_chain()
        self._draw_scope_frame_mini(4, 122, 312, 60)
        self._draw_piano_at(4, 188, 312, 96, True)

    def _draw_arp_config(self):
        y = 22
        self.d.text("PATTERN:", 8, y, LBL)
        self.d.text(ARP_PATTERNS[self.arp.pattern], 68, y, TXT)

        self.d.text("CHORD:", 8, y + 14, LBL)
        self.d.text(CHORD_NAMES[self.arp.chord_idx], 52, y + 14, TXT)

        self.d.text("RANGE:", 8, y + 28, LBL)
        self.d.text(str(self.arp.oct_range) + " oct", 52, y + 28, TXT)

        self.d.text("BPM:", 8, y + 42, LBL)
        self.d.text(str(self.arp.bpm), 36, y + 42, TXT)

        # Play status
        self._draw_led(100, y + 42, self.arp.active)
        self.d.text("PLAY" if self.arp.active else "STOP", 112, y + 42, BAR if self.arp.active else BRD)

    def _draw_arp_chain(self):
        y = 82
        x = 8
        self.d.fill_rect(0, y, self.W, 36, BG)
        self.d.text("SEQUENCE:", 8, y, LBL)
        if not self.arp.notes:
            return
        nx = 8
        for i, midi in enumerate(self.arp.notes):
            if nx > 300:
                break
            ni = midi % 12
            o = midi // 12 - 1
            nstr = NOTE_NAMES[ni] + str(o)
            w = len(nstr) * 6 + 4
            is_current = self.arp.active and i == self.arp.step
            if is_current:
                self.d.fill_rect(nx, y + 12, w, 14, BRD)
                self.d.rect(nx, y + 12, w, 14, TXT)
                self.d.text(nstr, nx + 2, y + 15, TXT)
            else:
                self.d.rect(nx, y + 12, w, 14, BRD)
                self.d.text(nstr, nx + 2, y + 15, LBL)
            nx += w + 2

    def _update_arp(self):
        if self._frame % 4 == 0:
            self._draw_arp_config()
            self._draw_arp_chain()
        if self._frame % 8 == 0:
            self._draw_scope_frame_mini(4, 122, 312, 60)
            self._draw_piano_at(4, 188, 312, 96, True)

    # -- SET page --

    def _draw_set_page(self):
        self._draw_set_page_content()

    def _draw_set_page_content(self):
        e = self.engine
        y_start = 22
        row_h = 20

        for i, (name, attr, unit, mn, mx, step) in enumerate(self.set_params):
            y = y_start + i * row_h
            selected = i == self.set_cursor
            self.d.fill_rect(2, y, 316, row_h - 2, HDR if selected else BG)
            if selected:
                self.d.rect(2, y, 316, row_h - 2, BAR)

            self.d.text(name, 8, y + 4, TXT if selected else LBL)

            # Get current value
            val = getattr(e, attr)
            if unit == 'bool':
                val_str = "ON" if val else "OFF"
            elif unit == 'inst':
                val_str = INST_NAMES[val]
            elif unit == 'wf':
                val_str = WAVEFORMS[val][0]
            elif unit == 'out':
                val_str = _OUT_NAMES[val]
            else:
                val_str = str(val) + unit

            self.d.text(val_str, 160, y + 4, TXT if selected else LBL)

            if selected:
                self.d.text("<", 260, y + 4, TXT)
                self.d.text(">", 300, y + 4, TXT)

        # Preset section at bottom
        py = y_start + len(self.set_params) * row_h + 4
        self.d.hline(4, py, 312, BRD)
        self.d.text("PRESETS:", 8, py + 6, LBL)

        # Built-in preset names
        px = 68
        for name in BUILTIN_PRESETS:
            self.d.text(name, px, py + 6, BAR)
            px += (len(name) + 1) * 6


# -- PicoSynth (Main Controller) -------------------------------------

class PicoSynth:
    def __init__(self):
        self.display = picocalc.display
        self.engine = SynthEngine()
        self.arp = Arpeggiator(self.engine)
        self.seq = Sequencer(self.engine)
        self.ui = SynthUI(self.display, self.engine, self.arp, self.seq)
        self.key_buf = bytearray(16)
        self.running = True

        # Preset file listing cache
        self._preset_files = []

        print("Synth 4.0 initialized")
        print("Free mem:", gc.mem_free())

    def handle_input(self):
        if not picocalc.terminal:
            return

        count = picocalc.terminal.readinto(self.key_buf)
        if not count:
            return

        # Parse buffer byte-by-byte, consuming escape sequences
        i = 0
        while i < count:
            b = self.key_buf[i]

            # Escape sequence
            if b == 0x1b:
                remaining = count - i
                # Double ESC = exit
                if remaining >= 2 and self.key_buf[i + 1] == 0x1b:
                    self.running = False
                    return
                # Arrow keys: \x1b [ A/B/C/D
                if remaining >= 3 and self.key_buf[i + 1] == 0x5b:
                    arrow = self.key_buf[i + 2]
                    if arrow == 0x41:    # Up
                        self._dispatch_arrow('U')
                    elif arrow == 0x42:  # Down
                        self._dispatch_arrow('D')
                    elif arrow == 0x43:  # Right
                        self._dispatch_arrow('R')
                    elif arrow == 0x44:  # Left
                        self._dispatch_arrow('L')
                    i += 3
                    continue
                # Lone ESC -- treat as exit
                self.running = False
                return

            # Tab
            if b == 0x09:
                self._stop_all()
                self.ui.page = (self.ui.page + 1) % 4
                i += 1
                continue

            # Regular key -- process it
            self._dispatch_key(b)
            i += 1

    def _dispatch_arrow(self, direction):
        pg = self.ui.page
        if direction == 'U':
            if pg == PG_SET:
                self._handle_set_up()
            elif pg == PG_SEQ:
                self._handle_seq_up()
            elif pg == PG_ARP:
                self._handle_arp_up()
            else:
                self._octave_up()
        elif direction == 'D':
            if pg == PG_SET:
                self._handle_set_down()
            elif pg == PG_SEQ:
                self._handle_seq_down()
            elif pg == PG_ARP:
                self._handle_arp_down()
            else:
                self._octave_down()
        elif direction == 'L':
            if pg == PG_SET:
                self._handle_set_left()
            elif pg == PG_SEQ:
                self._handle_seq_left()
            elif pg == PG_ARP:
                self._handle_arp_left()
            else:
                self._vol_down()
        elif direction == 'R':
            if pg == PG_SET:
                self._handle_set_right()
            elif pg == PG_SEQ:
                self._handle_seq_right()
            elif pg == PG_ARP:
                self._handle_arp_right()
            else:
                self._vol_up()

    def _dispatch_key(self, key):
        lk = key | 0x20  # lowercase for letters, no-op for digits
        if self.ui.page == PG_PLAY:
            self._handle_play_key(key, lk)
        elif self.ui.page == PG_SEQ:
            self._handle_seq_key(key, lk)
        elif self.ui.page == PG_ARP:
            self._handle_arp_key(key, lk)
        elif self.ui.page == PG_SET:
            self._handle_set_key(key, lk)

    def _handle_play_key(self, key, lk):
        # Space - toggle sustain
        if key == 0x20:
            self.engine.sustain_hold = not self.engine.sustain_hold
            if not self.engine.sustain_hold and self.engine.is_playing():
                self.engine.note_off()
            return

        # Piano keys
        if lk in PIANO_MAP:
            ni, oct_off = PIANO_MAP[lk]
            midi = (self.engine.octave + 1 + oct_off) * 12 + ni
            if 24 <= midi <= 108:
                self.engine.note_on(midi)
            return

        # I - cycle instrument
        if lk == ord('i'):
            self.engine.instrument = (self.engine.instrument + 1) % len(INST_NAMES)
            return

        # F - cycle waveform (Synth mode only)
        if lk == ord('f'):
            if self.engine.instrument == INST_SYNTH:
                self.engine.wf_idx = (self.engine.wf_idx + 1) % len(WAVEFORMS)
            return

        # Output toggle
        if lk == ord('o'):
            self.engine.output = (self.engine.output + 1) % 3
            return

    def _handle_seq_key(self, key, lk):
        if lk == ord('p'):
            if self.seq.playing:
                self.seq.stop_play()
            else:
                self.seq.start_play()
            return
        if lk == ord('r'):
            self.seq.toggle_record()
            return
        if key == 0x20:  # Space - toggle step active
            self.seq.toggle_active(self.seq.cursor)
            return
        if lk == ord('c'):  # Clear step
            self.seq.set_active(self.seq.cursor, False)
            return
        if lk == ord('a'):  # Clear all
            for i in range(16):
                self.seq.set_active(i, False)
            return
        if lk == ord('l'):
            self._load_seq_pattern()
            return
        if lk == ord('k'):  # Save (S conflicts with piano)
            self._save_seq_pattern()
            return

        # Piano keys for recording
        if self.seq.recording and lk in PIANO_MAP:
            ni, oct_off = PIANO_MAP[lk]
            midi = (self.engine.octave + 1 + oct_off) * 12 + ni
            if 24 <= midi <= 108:
                self.seq.record_note(midi)
                self.engine.note_on(midi)
            return

    def _handle_seq_up(self):
        midi = self.seq.get_note(self.seq.cursor)
        self.seq.set_note(self.seq.cursor, midi + 1)

    def _handle_seq_down(self):
        midi = self.seq.get_note(self.seq.cursor)
        self.seq.set_note(self.seq.cursor, midi - 1)

    def _handle_seq_left(self):
        self.seq.cursor = (self.seq.cursor - 1) % 16

    def _handle_seq_right(self):
        self.seq.cursor = (self.seq.cursor + 1) % 16

    def _handle_arp_key(self, key, lk):
        if lk == ord('p'):
            if self.arp.active:
                self.arp.stop()
            else:
                midi = (self.engine.octave + 1) * 12  # Root = C of current octave
                self.arp.start(midi)
            return

        # Piano keys set root note
        if lk in PIANO_MAP:
            ni, oct_off = PIANO_MAP[lk]
            midi = (self.engine.octave + 1 + oct_off) * 12 + ni
            if 24 <= midi <= 108:
                self.arp.root_note = midi
                if self.arp.active:
                    self.arp.start(midi)
                else:
                    self.engine.note_on(midi)
            return

    def _handle_arp_up(self):
        self.arp.chord_idx = (self.arp.chord_idx + 1) % len(CHORD_NAMES)
        if self.arp.active:
            self.arp.generate()

    def _handle_arp_down(self):
        self.arp.chord_idx = (self.arp.chord_idx - 1) % len(CHORD_NAMES)
        if self.arp.active:
            self.arp.generate()

    def _handle_arp_left(self):
        self.arp.pattern = (self.arp.pattern - 1) % len(ARP_PATTERNS)
        if self.arp.active:
            self.arp.generate()

    def _handle_arp_right(self):
        self.arp.pattern = (self.arp.pattern + 1) % len(ARP_PATTERNS)
        if self.arp.active:
            self.arp.generate()

    def _handle_set_up(self):
        self.ui.set_cursor = (self.ui.set_cursor - 1) % len(self.ui.set_params)

    def _handle_set_down(self):
        self.ui.set_cursor = (self.ui.set_cursor + 1) % len(self.ui.set_params)

    def _handle_set_left(self):
        self._adjust_setting(-1)

    def _handle_set_right(self):
        self._adjust_setting(1)

    def _adjust_setting(self, direction):
        name, attr, unit, mn, mx, step = self.ui.set_params[self.ui.set_cursor]
        val = getattr(self.engine, attr)
        if unit == 'bool':
            val = not val
        else:
            val = val + direction * step
            val = max(mn, min(mx, val))
        setattr(self.engine, attr, val)

    def _handle_set_key(self, key, lk):
        if lk == ord('l'):
            self._load_preset_menu()
            return
        if lk == ord('s'):
            self._save_preset()
            return
        # Number keys 1-5 for built-in presets
        if ord('1') <= key <= ord('5'):
            idx = key - ord('1')
            names = list(BUILTIN_PRESETS.keys())
            if idx < len(names):
                self.engine.load_preset(BUILTIN_PRESETS[names[idx]])
            return

    def _octave_up(self):
        if self.engine.octave < 7:
            self.engine.octave += 1

    def _octave_down(self):
        if self.engine.octave > 1:
            self.engine.octave -= 1

    def _vol_up(self):
        self.engine.volume = min(100, self.engine.volume + 5)

    def _vol_down(self):
        self.engine.volume = max(10, self.engine.volume - 5)

    def _stop_all(self):
        self.arp.stop()
        self.seq.stop_play()
        self.engine.silence()

    def _save_preset(self):
        try:
            os.mkdir(PRESET_DIR)
        except:
            pass
        p = self.engine.get_preset()
        path = PRESET_DIR + "/USER_preset.json"
        try:
            with open(path, 'w') as f:
                json.dump(p, f)
            print("Preset saved:", path)
        except Exception as ex:
            print("Save error:", ex)

    def _load_preset_menu(self):
        try:
            files = [f for f in os.listdir(PRESET_DIR) if f.endswith('.json')]
            if files:
                path = PRESET_DIR + "/" + files[0]
                with open(path, 'r') as f:
                    p = json.load(f)
                self.engine.load_preset(p)
                print("Loaded:", path)
        except Exception as ex:
            print("Load error:", ex)

    def _save_seq_pattern(self):
        try:
            self.seq.save()
            print("Pattern saved")
        except Exception as ex:
            print("Save error:", ex)

    def _load_seq_pattern(self):
        try:
            files = [f[:-4] for f in os.listdir(PRESET_DIR) if f.endswith('.seq')]
            if files:
                self.seq.load(files[0])
                print("Loaded:", files[0])
        except Exception as ex:
            print("Load error:", ex)

    def run(self):
        print("Starting Synth 4.0...")
        print("Tab: cycle pages | Piano keys: Z-M, S-J, Q-U")

        # Play brief test tone
        self.engine.note_on(69)  # A4
        utime.sleep_ms(300)
        self.engine.silence()

        self.ui.full_redraw()
        gc_counter = 0

        try:
            while self.running:
                now = utime.ticks_ms()

                self.handle_input()
                self.engine.update(now)
                self.arp.tick(now)
                self.seq.tick(now)
                self.ui.draw_frame()

                gc_counter += 1
                if gc_counter >= 200:
                    gc.collect()
                    gc_counter = 0

                utime.sleep_ms(8)

        except KeyboardInterrupt:
            pass

        self.engine.silence()
        self.display.fill(BG)
        self.display.text("Synth 4.0 exited.", 10, 10, TXT)
        self.display.show()
        utime.sleep_ms(500)
        print("Synth 4.0 exited.")


# -- Entry Point ------------------------------------------------------

def main():
    gc.collect()
    try:
        synth = PicoSynth()
        synth.run()
    except Exception as e:
        print("Synth error:", e)
        import sys
        sys.print_exception(e)

if __name__ == "__main__":
    main()
