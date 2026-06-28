# picosampler milestone 1 smoke test.
#
# Loads one 8-bit PCM one-shot from /sd/samples/ and triggers it a few times
# through the DMA-PWM audio engine. Proves the C module plays a real sample.
#
# Prereqs:
#   - firmware built with the picosampler C module (Dockerfile.v128)
#   - a sample at /sd/samples/bd.raw (see make_samples.sh)

import time
import picosampler

SAMPLE_PATH = "/sd/samples/bd.raw"


def load(path):
    # Keep a reference to the buffer: picosampler holds a GC root, but loading
    # via a local that we return makes the ownership obvious.
    with open(path, "rb") as f:
        return f.read()


def main():
    sr = picosampler.init(22050)
    print("audio engine running at %.1f Hz" % sr)

    data = load(SAMPLE_PATH)
    sid = picosampler.register(data)
    print("registered %s as id %d (%d bytes)" % (SAMPLE_PATH, sid, len(data)))

    print("playing 4 hits...")
    for _ in range(4):
        picosampler.play(sid, 256)
        time.sleep(0.5)

    time.sleep(0.5)
    picosampler.stop_all()
    print("done")


if __name__ == "__main__":
    main()
