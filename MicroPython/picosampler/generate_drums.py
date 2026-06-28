#!/usr/bin/env python3
# Synthesize a tiny drum kit as 8-bit unsigned mono PCM (.raw) for picosampler.
#
# No dependencies (stdlib only). Output is headerless pcm_u8: one byte/sample,
# 0..255, centered at 128 - exactly what picosampler.register() expects.
#
#   python3 generate_drums.py [SAMPLE_RATE] [OUT_DIR]
#   defaults: 22050 Hz, ../sd/samples

import math
import os
import random
import struct
import sys

SR = int(sys.argv[1]) if len(sys.argv) > 1 else 22050
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(__file__), "..", "sd", "samples")

# Keep peaks below full scale so several voices can mix without clipping.
HEADROOM = 0.7


def write_raw(name, samples):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".raw")
    peak = max(1e-9, max(abs(s) for s in samples))
    norm = HEADROOM / peak
    with open(path, "wb") as f:
        for s in samples:
            v = int(round(128 + 127 * s * norm))
            v = 0 if v < 0 else 255 if v > 255 else v
            f.write(struct.pack("B", v))
    dur = len(samples) / SR
    print("  %-10s %6d samples  %.3fs" % (name + ".raw", len(samples), dur))
    return path


def env(i, n, decay):
    # Exponential amplitude decay over the sample, with a tiny fade-out tail
    # to avoid a click at the end.
    t = i / SR
    a = math.exp(-t / decay)
    tail = min(1.0, (n - i) / (0.003 * SR))  # last 3ms ramps to zero
    return a * tail


def kick(dur=0.22, f0=120.0, f1=45.0, decay=0.10):
    n = int(SR * dur)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / SR
        # Pitch sweeps from f0 down to f1 quickly (that classic "boom").
        f = f1 + (f0 - f1) * math.exp(-t / 0.04)
        phase += 2 * math.pi * f / SR
        out.append(math.sin(phase) * env(i, n, decay))
    return out


def snare(dur=0.18, tone=185.0, decay=0.09, noise_decay=0.11):
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        body = math.sin(2 * math.pi * tone * t) * math.exp(-t / decay)
        noise = (random.random() * 2 - 1) * math.exp(-t / noise_decay)
        out.append((0.45 * body + 0.85 * noise) * env(i, n, max(decay, noise_decay)))
    return out


def hihat(dur=0.05, decay=0.018):
    n = int(SR * dur)
    out = []
    prev = 0.0
    for i in range(n):
        white = random.random() * 2 - 1
        # Crude high-pass (first difference) for a bright, metallic noise.
        hp = white - prev
        prev = white
        out.append(hp * env(i, n, decay))
    return out


def clap(dur=0.18, decay=0.10):
    n = int(SR * dur)
    out = [0.0] * n
    # Three quick noise bursts ~10ms apart, then a short tail - the clap "spread".
    offsets = [0.0, 0.010, 0.020, 0.032]
    for off in offsets:
        start = int(off * SR)
        for i in range(start, n):
            t = (i - start) / SR
            out[i] += (random.random() * 2 - 1) * math.exp(-t / 0.012)
    for i in range(n):
        t = i / SR
        out[i] *= math.exp(-t / decay) * env(i, n, decay)
    return out


def main():
    random.seed(1)  # reproducible kit
    print("synthesizing drum kit at %d Hz -> %s" % (SR, os.path.normpath(OUT)))
    write_raw("bd", kick())
    write_raw("sd", snare())
    write_raw("hh", hihat())
    write_raw("cp", clap())
    print("done. push these to /sd/samples/ on the device.")


if __name__ == "__main__":
    main()
