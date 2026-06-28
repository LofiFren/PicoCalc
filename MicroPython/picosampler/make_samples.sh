#!/usr/bin/env bash
# Convert audio files into raw 8-bit unsigned mono PCM for picosampler.
#
# picosampler plays headerless pcm_u8 data: one byte per sample, 0..255,
# centered at 128. Keep one-shots short (drum hits are ideal) so they fit in
# RAM as MicroPython bytes objects.
#
# Usage:
#   ./make_samples.sh [SAMPLE_RATE] IN_DIR OUT_DIR
#   ./make_samples.sh 22050 ~/Dirt-Samples/bd ./samples
#
# Then push OUT_DIR to the device, e.g. /sd/samples/.
#
# Note on pitch: picosampler.init() returns the ACTUAL hardware sample rate,
# which is quantised by the DMA timer and may differ slightly from the request
# (e.g. ~22888 instead of 22050 at 150MHz sys_clk). For pitch-accurate playback,
# re-run this with that reported rate.

set -euo pipefail

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "error: ffmpeg not found on PATH" >&2
    exit 1
fi

if [ "$#" -eq 3 ]; then
    SR="$1"; IN_DIR="$2"; OUT_DIR="$3"
elif [ "$#" -eq 2 ]; then
    SR="22050"; IN_DIR="$1"; OUT_DIR="$2"
else
    echo "usage: $0 [SAMPLE_RATE] IN_DIR OUT_DIR" >&2
    exit 2
fi

mkdir -p "$OUT_DIR"

shopt -s nullglob nocaseglob
count=0
for f in "$IN_DIR"/*.{wav,aif,aiff,flac,mp3,ogg}; do
    base="$(basename "${f%.*}")"
    out="$OUT_DIR/$base.raw"
    ffmpeg -loglevel error -y -i "$f" -ar "$SR" -ac 1 -acodec pcm_u8 -f u8 "$out"
    bytes=$(wc -c < "$out")
    printf '  %-16s %8d bytes  (%.2fs @ %sHz)\n' "$base.raw" "$bytes" \
        "$(echo "scale=2; $bytes / $SR" | bc)" "$SR"
    count=$((count + 1))
done

echo "converted $count file(s) at ${SR}Hz into $OUT_DIR"
