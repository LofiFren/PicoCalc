FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    git cmake build-essential gcc-arm-none-eabi libnewlib-arm-none-eabi \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# MicroPython v1.25.0-preview (commit f187c77da) -- stable USB on RP2350.
# Newer versions (v1.26.0+) have a USB-CDC regression on RP2350.
# See USB_REGRESSION_FIX.md for details.
# For v1.27.0 with BLE pairing + USB fix, use Dockerfile.v127 instead.
RUN git clone https://github.com/micropython/micropython.git /micropython \
    && cd /micropython && git checkout f187c77da

WORKDIR /micropython
RUN git submodule update --init --depth 1 lib/pico-sdk lib/tinyusb lib/mbedtls lib/micropython-lib
RUN cd lib/pico-sdk && git submodule update --init --depth 1

RUN make -C mpy-cross -j$(nproc)

WORKDIR /micropython/ports/rp2
RUN make BOARD=RPI_PICO2_W submodules

# Usage (from repo root):
#   docker build -t picocalc-build MicroPython/firmware/
#   docker run --rm \
#     -v $(pwd)/MicroPython:/picocalc \
#     -v $(pwd)/MicroPython/firmware:/out \
#     picocalc-build \
#     bash -c "make BOARD=RPI_PICO2_W USER_C_MODULES=/picocalc/micropython.cmake -j\$(nproc) && \
#              cp build-RPI_PICO2_W/firmware.uf2 /out/picocalc_micropython_pico2w.uf2"
