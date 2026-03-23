FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    git cmake build-essential gcc-arm-none-eabi libnewlib-arm-none-eabi \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone MicroPython at known-good commit (v1.25.0-preview.389)
# Pinned because MicroPython master (v1.28.0-preview) has a USB-CDC
# regression on RP2350 — the device fails to enumerate over USB.
RUN git clone https://github.com/micropython/micropython.git /micropython \
    && cd /micropython && git checkout f187c77da

# Init all submodules (including pico-sdk's nested WiFi/BLE deps)
WORKDIR /micropython
RUN git submodule update --init --depth 1 lib/pico-sdk lib/tinyusb lib/mbedtls lib/micropython-lib
RUN cd lib/pico-sdk && git submodule update --init --depth 1

# Build mpy-cross
RUN make -C mpy-cross -j$(nproc)

# Pre-init board submodules (CYW43 driver, btstack, lwip for Pico 2W)
WORKDIR /micropython/ports/rp2
RUN make BOARD=RPI_PICO2_W submodules

# Default build command — mount C modules at /picocalc and run:
#   docker build -t picocalc-build MicroPython/firmware/
#   docker run --rm -v $(pwd)/MicroPython:/picocalc picocalc-build \
#     make BOARD=RPI_PICO2_W USER_C_MODULES=/picocalc/micropython.cmake -j$(nproc)
#
# The .uf2 will be at: build-RPI_PICO2_W/firmware.uf2
# Copy it out:
#   docker run --rm -v $(pwd)/MicroPython:/picocalc -v $(pwd)/MicroPython/firmware:/out picocalc-build \
#     bash -c "make BOARD=RPI_PICO2_W USER_C_MODULES=/picocalc/micropython.cmake -j\$(nproc) && \
#              cp build-RPI_PICO2_W/firmware.uf2 /out/picocalc_micropython_pico2w.uf2"
