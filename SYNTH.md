# PicoCalc Synth 4.0

A full-featured synthesizer for the PicoCalc with piano keyboard, 4 instruments, ADSR envelope, arpeggiator, step sequencer, and preset system.

Drop `synth.py` onto your SD card's `py_scripts/` folder and launch from the menu.

---

## Instruments

Press **I** on the PLAY page to cycle instruments.

| Instrument | Sound | How it works |
|------------|-------|--------------|
| **Piano** | Percussive, natural decay | Pitch starts 1.5% sharp and drops over 25ms (hammer strike). Decay scales with pitch: low notes ring ~400ms, high notes ~80ms. Pulse12 waveform for rich harmonics. |
| **Organ** | Sustained, warm | Instant attack, 100% sustain, snappy 30ms release. Gentle 5Hz vibrato. Classic drawbar organ feel. Holds as long as the key is down. |
| **Strings** | Slow swell, lush pad | 250ms attack, heavy stereo detune (6Hz chorus), 4Hz tremolo. Wide pulse waveform. Swells in gradually. |
| **Synth** | Fully configurable | All parameters (ADSR, LFO, waveform, detune) controlled from the SET page. Press F to cycle waveforms. |

Piano, Organ, and Strings override engine params per-note for consistent sound. Synth mode gives full manual control.

---

## Pages

Navigate with **Tab** to cycle: PLAY > SEQ > ARP > SET

### PLAY -- Piano Performance

The main page. Play notes on the QWERTY keyboard, see the piano visualization, oscilloscope, and instrument status.

### SEQ -- Step Sequencer

16-step pattern grid (2 rows of 8). Edit notes, toggle steps, record live, play loops. Patterns save to SD card.

### ARP -- Arpeggiator

Auto-cycles through chord tones. Choose chord type, pattern direction, BPM, and octave range. Set root note with piano keys.

### SET -- Settings & Presets

Scrollable parameter list. Adjust ADSR, LFO, waveform, detune, volume, and more. Load built-in presets with keys 1-5. Save/load user presets to SD card.

---

## Controls

### Global (all pages)

| Key | Function |
|-----|----------|
| Tab | Cycle pages: PLAY > SEQ > ARP > SET |
| Up/Down | Octave shift (PLAY/ARP), navigate (SEQ/SET) |
| ESC | Exit synth |

### PLAY Page

**Piano Keyboard:**

```
Number row:  1  2  3     4  5  6  7     8  9  0
             C  C# D#    E  F# G# A#    C  D  E
                         (octave +1)        (+2)

Top row:     Q  W  E  R  T  Y  U
             C  D  E  F  G  A  B  (octave +1)

Home row:       S  D     G  H  J
                C# D#    F# G# A# (black keys)

Bottom row:  Z  X  C  V  B  N  M
             C  D  E  F  G  A  B  (base octave)
```

**PLAY Controls:**

| Key | Function |
|-----|----------|
| I | Cycle instrument: Piano > Organ > Strings > Synth |
| F | Cycle waveform (Synth mode only) |
| Space | Toggle sustain hold |
| Left/Right | Volume down/up |
| O | Cycle output: HP > SPK > BOTH |

### SEQ Page

| Key | Function |
|-----|----------|
| Left/Right | Move cursor between steps |
| Up/Down | Change note at cursor (semitone) |
| Space | Toggle step on/off |
| P | Start/stop playback |
| R | Toggle record mode |
| C | Clear current step |
| A | Clear all steps |
| K | Save pattern to SD card |
| L | Load pattern from SD card |
| Piano keys | Record note into current step (when recording) |

### ARP Page

| Key | Function |
|-----|----------|
| Left/Right | Change pattern (Up, Down, UpDn, Rand) |
| Up/Down | Change chord type |
| P | Start/stop arpeggiator |
| Piano keys | Set root note |

**Chord Types:** Maj, Min, 7th, Min7, Dim, Aug, Oct, Pwr

### SET Page

| Key | Function |
|-----|----------|
| Up/Down | Select parameter |
| Left/Right | Adjust value |
| 1-5 | Load built-in preset (Lead, Pad, Bass, Pluck, Wobble) |
| S | Save user preset to SD |
| L | Load user preset from SD |

---

## Parameters (SET Page)

| Parameter | Range | Description |
|-----------|-------|-------------|
| Instrument | Piano/Organ/Strings/Synth | Active instrument (also changeable with I key) |
| Attack | 10-500ms | Ramp from silence to peak |
| Decay | 10-500ms | Drop from peak to sustain level |
| Sustain | 0-100% | Level held during sustain |
| Release | 10-1000ms | Fade from sustain to silence |
| LFO Rate | 0-20.0Hz | Vibrato/tremolo speed |
| LFO Depth | 0-100% | Vibrato/tremolo intensity |
| Vibrato | ON/OFF | Pitch modulation |
| Tremolo | ON/OFF | Volume modulation |
| Waveform | Square/Pulse25/Pulse12/Wide/PWM Swp | Duty cycle profile (Synth mode) |
| Detune | 0-15Hz | Stereo detune between L/R |
| Volume | 10-100% | Master volume |
| AutoRel | 100-2000ms | Auto-release timer |
| Output | HP/SPK/BOTH | Audio routing |

> Parameters only affect **Synth** mode. Piano, Organ, and Strings override these per-note.

---

## Waveforms (Synth Mode)

| Waveform | Duty Cycle | Character |
|----------|-----------|-----------|
| Square | 50% | Classic hollow tone, strong odd harmonics |
| Pulse25 | 25% | Nasal, reedy, clarinet-like |
| Pulse12 | 12.5% | Thin, buzzy, aggressive |
| Wide | 75% | Mellow, warm |
| PWM Swp | 15-85% sweep | Lush chorus, duty oscillates |

---

## Built-in Presets

| # | Preset | Character |
|---|--------|-----------|
| 1 | Lead | Bright, punchy, fast response |
| 2 | Pad | Slow, lush, atmospheric |
| 3 | Bass | Deep, nasal, tight |
| 4 | Pluck | Sharp attack, instant decay |
| 5 | Wobble | Thick, modulated, heavy tremolo |

---

## Saving & Loading

**Presets** save to `/sd/synth_presets/USER_preset.json` -- includes instrument, ADSR, LFO, waveform, detune, volume settings.

**Sequencer patterns** save to `/sd/synth_presets/<name>.seq` -- includes all 16 steps and BPM.

The `synth_presets` directory is created automatically on first save.

---

## Audio Notes

The PicoCalc uses PWM audio (GPIO 28 left, GPIO 27 right). PWM can only produce pulse waves -- it cannot generate true sine, sawtooth, or triangle waves. The five waveforms are different pulse width profiles that each produce a genuinely different tone.

The Piano instrument gets its character from:
- A downward pitch bend on attack (mimicking hammer mechanics)
- Frequency-scaled decay (low notes sustain longer, like real strings)
- Narrow pulse width (12.5%) for richer harmonics
- Stereo detune for warmth

Headphone output automatically attenuates high frequencies above 2kHz for ear safety.
