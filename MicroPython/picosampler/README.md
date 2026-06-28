# picosampler

Native C audio engine for PicoCalc (RP2350 / Pico 2W). Milestone 1 of the
"Strudel on PicoCalc" port (option C1): a DMA-paced PWM mixer that plays 8-bit
PCM one-shots from the SD card, so the device can produce sampled sound
(bd/sd/hh...) rather than pulse-wave chiptune.

## What it does (milestone 1)

- Free-running PWM carrier on GPIO 28 (left audio), duty = audio sample.
- A DMA timer paces two ping-pong DMA channels that stream 8-bit levels into the
  PWM compare register at the audio sample rate; the DMA IRQ mixes the next
  block of all active voices. Gapless, runs off-CPU between blocks.
- Up to 8 simultaneous voices, mono.

Not yet (later milestones): stereo (GPIO 27 is a separate slice), voice
stealing, SD streaming for long loops, off-GC-heap sample pool, the
mini-notation sequencer, and migrating the pattern engine into C (option C2).

## API

```python
import picosampler
sr  = picosampler.init(22050)      # start engine; returns ACTUAL hw rate (Hz)
sid = picosampler.register(buf)    # buf = bytes/bytearray of pcm_u8; -> sample id
picosampler.play(sid, gain=256)    # trigger; gain is 8.8 fixed point (256 = unity)
picosampler.stop_all()
picosampler.sample_rate()          # actual hw rate
```

`register()` keeps a GC root reference to `buf`, so the data stays valid without
the caller having to retain it.

## Sample prep

```bash
./make_samples.sh 22050 ~/Dirt-Samples/bd ./samples
# push ./samples to the device at /sd/samples/
```

`init()` returns the true hardware rate (DMA-timer quantised, e.g. ~22888 Hz at
150 MHz sys_clk). For pitch-accurate playback re-encode at that rate.

## Build

Added to the firmware via `MicroPython/micropython.cmake`. Build with the
existing v1.28 image (from repo root):

```bash
docker build -t picocalc-v128 -f MicroPython/firmware/Dockerfile.v128 MicroPython/firmware/
docker run --rm \
  -v $(pwd)/MicroPython:/picocalc \
  -v $(pwd)/MicroPython/firmware:/out \
  picocalc-v128 \
  bash -c "make BOARD=RPI_PICO2_W USER_C_MODULES=/picocalc/micropython.cmake -j\$(nproc) && \
           cp build-RPI_PICO2_W/firmware.uf2 /out/picocalc_v128_pico2w.uf2"
```

Flash the resulting `.uf2`, push a sample, then run
`sd/py_scripts/picosampler_test.py`.
```
