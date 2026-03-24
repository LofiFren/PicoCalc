# PicoCalc MicroPython

A MicroPython firmware and script collection for the Clockwork Pi PicoCalc handheld device, powered by the **Raspberry Pi Pico 2W**. Features:

- 320x320 LCD display with flicker-free rendering
- Membrane keyboard with VT100 terminal
- Arrow-key navigable menu system
- Games (Tetris, Snake), Synthesizer, BLE Scanner, WiFi Manager, LLM client
- SD card script auto-discovery

---

## Quick Start

- YouTube PicoCalc 2.0 Demo: [https://youtu.be/gf3ittEwFJ8](https://youtu.be/gf3ittEwFJ8)

### 1. Flash the Firmware

1. **Power off** the PicoCalc and unplug USB.
2. **Hold BOOTSEL** on the Pico 2W, then connect USB.
3. A drive named **RP2350** appears.
4. Copy `MicroPython/firmware/picocalc_micropython_pico2w.uf2` to that drive.
5. The device reboots automatically.

### 2. Deploy Files to the Device

#### Option A: Dashboard (Recommended)

The easiest way — a local web UI that handles everything:

```bash
python3 MicroPython/tools/dashboard.py
```

This opens a browser dashboard where you can:
- **Deploy All** — pushes boot files, modules, and scripts in one click
- **Browse** device files, view diffs, push individual files
- **Drag-and-drop** `.py` files to upload
- **REPL** — run Python on the device from the browser

> First run will prompt to install `mpremote` if needed. Requires Python 3.7+.
>
> **Adding new files:** Scripts in `modules/` and `sd/py_scripts/` are auto-discovered by the dashboard. Root-level files (like `boot.py`) must be added to `FILE_MAP` in `dashboard.py` to appear.

#### Option B: Manual

Use [Thonny](https://thonny.org/), `mpremote`, or `rshell` to copy files to the Pico's internal flash.

**Copy these to the Pico root (`/`):**
```
MicroPython/boot.py       --> /boot.py
MicroPython/main.py       --> /main.py
MicroPython/modules/      --> /modules/     (entire directory)
```

**Copy SD card scripts:**
```
MicroPython/sd/py_scripts/*.py  --> SD card /py_scripts/
```

**Do NOT copy these to the device** (they run on your computer, not the PicoCalc):
```
tools/             <-- Dashboard web UI (runs on your computer)
picocalcdisplay/   <-- C source, compiled into firmware
vtterminal/        <-- C source, compiled into firmware
firmware/          <-- UF2 images and Dockerfile
Client_Code/       <-- Desktop BLE client
```

### 3. Prepare the SD Card

1. Format an SD card as **FAT32** (4GB-32GB recommended).
2. Create a `py_scripts` folder on the SD card.
3. Copy all `.py` files from `MicroPython/sd/py_scripts/` into that folder.
4. Insert the SD card into the PicoCalc.

> Or use the Dashboard — click **Deploy Scripts** to push all scripts to the SD card over USB.

### 4. Boot

Power cycle the PicoCalc. The boot splash shows initialization progress, then the main menu appears with arrow-key navigation.

---

## Repository Structure

```
MicroPython/
├── boot.py                  --> Copy to device /
├── main.py                  --> Copy to device / (launches menu)
├── boot_thonny.py           --> Deploy as /boot.py for Thonny users
├── boot_dev.py              --> Deploy as /boot.py for dev mode (REPL only)
├── cleanup.py               --> (Optional) one-time cleanup, or use dashboard Cleanup button
├── modules/                 --> Copy to device /modules/
│   ├── picocalc.py              Hardware abstraction (display + keyboard)
│   ├── vt.py                    VT100 terminal emulator
│   ├── py_run.py                Menu system with arrow-key navigation
│   ├── enhanced_sd.py           SD card initialization
│   ├── picocalc_system.py       System utilities
│   ├── sdcard.py                SD card driver
│   ├── checksd.py               SD card verification
│   ├── pye.py                   Built-in text editor
│   ├── colorer.py               Terminal color support
│   ├── default_style.py         Syntax highlighting styles
│   ├── highlighter.py           Code syntax highlighting
│   ├── flush.py                 Module cache flushing
│   └── mkdir.py                 Directory creation utility
├── sd/py_scripts/           --> Copy contents to SD card /py_scripts/
│   ├── tetris.py                Tetris with sound effects
│   ├── snake.py                 Snake with high scores
│   ├── synth.py                 Multi-waveform synthesizer
│   ├── ProxiScan.py             BLE proximity scanner & fox hunt tool
│   ├── WiFiManager.py           WiFi scanning & connection manager
│   ├── PicoBLE.py               BLE GATT server & file transfer
│   ├── picocalc_ollama.py       Local LLM client (Ollama)
│   ├── brad.py                  WiFi utility library
│   ├── demo.py                  Visual display showcase (grayscale, animation)
│   └── editor.py                On-device file browser + code editor
├── firmware/                    Prebuilt UF2 firmware images
│   ├── picocalc_micropython_pico2w.uf2
│   └── Dockerfile               Build environment for firmware
├── micropython.cmake            Top-level build config for C modules
├── picocalcdisplay/             C display driver (compiled into firmware)
│   ├── picocalcdisplay.c
│   ├── picocalcdisplay.h
│   ├── font6x8e500.h
│   └── micropython.cmake
├── vtterminal/                  C terminal emulator (compiled into firmware)
│   ├── vtterminal.c
│   ├── vtterminal.h
│   ├── font6x8.h
│   └── micropython.cmake
├── tools/                       Development dashboard
│   ├── dashboard.py                 Web UI server (run this!)
│   ├── bottle.py                    Vendored web framework (zero install)
│   └── static/
│       ├── index.html               Dashboard frontend
│       └── vendor/                  CodeMirror editor (vendored, offline)
└── Client_Code/                 Desktop BLE client (runs on PC, not device)
    ├── PicoCalc_Client_BLE.py
    └── picocalc_client_config.json
```

---

## Applications

| App | Description |
|-----|-------------|
| **Tetris** | Classic Tetris with 7 pieces, ghost piece, sound effects, level progression |
| **Snake** | Snake with high score tracking, speed levels, sound |
| **Synth** | Multi-waveform synthesizer with headphone/speaker output |
| **ProxiScan** | BLE proximity scanner, fox hunt tool with compass, signal tracking, competition timer, waypoints, antenna calibration |
| **WiFiManager** | WiFi scanner with VT100 UI, signal bars, channel analysis, signal monitor |
| **PicoBLE** | BLE GATT server with Nordic UART Service, file transfer |
| **Ollama Client** | Chat with local LLMs over WiFi via Ollama |
| **Demo** | Visual display showcase: grayscale palette, bouncing boxes, scrolling gradient, device info |
| **Editor** | On-device file browser and code editor — browse, create, edit, delete scripts without a computer |

---

## Menu Controls

The main menu uses arrow-key navigation:

| Key | Action |
|-----|--------|
| Up/Down | Navigate script list |
| Enter | Run selected script |
| ESC | Exit to REPL |
| R | Reload script list |
| F | Flush module cache |
| M | Show memory/storage info |
| T | File management tools |

---

## Building Firmware from Source

The prebuilt UF2 in `firmware/` is ready to flash. To build from source:

```bash
# Build Docker image (one-time setup)
docker build -t picocalc-build MicroPython/firmware/

# Compile firmware with custom C modules
docker run --rm \
  -v $(pwd)/MicroPython:/picocalc \
  -v $(pwd)/MicroPython/firmware:/out \
  picocalc-build \
  bash -c "make BOARD=RPI_PICO2_W USER_C_MODULES=/picocalc/micropython.cmake -j\$(nproc) && \
           cp build-RPI_PICO2_W/firmware.uf2 /out/picocalc_micropython_pico2w.uf2"
```

Requires: Docker Desktop. The Dockerfile pins MicroPython to a known-good version for USB stability.

---

## Hardware

| Component | Details |
|-----------|---------|
| Display | 320x320 ILI9488 LCD, SPI1, 4-bit grayscale |
| Keyboard | Membrane keypad, I2C MCU at 0x1F |
| SD Card | SPI0, FAT32, mounted at /sd |
| Audio | PWM stereo, GPIO 27 (right) + GPIO 28 (left) |
| WiFi/BLE | CYW43 via Pico 2W |
| MCU | RP2350 (Raspberry Pi Pico 2W) |

---

## Troubleshooting

**"no module named 'picocalc'"** after flashing new firmware:
- The C source directories (`picocalcdisplay/`, `vtterminal/`) may be on the device filesystem, shadowing the C modules compiled into firmware. Delete them from the device — they should only exist in the repo, not on the Pico.
- Ensure `/modules/` directory with `picocalc.py` is on the device.

**Boot doesn't auto-run:**
- Verify `boot.py` is at the root of the Pico filesystem (`/boot.py`).
- Check that `/modules/` contains all `.py` files.

**SD card not mounting:**
- Format as FAT32. Ensure card is seated firmly.
- The boot sequence includes a stabilization delay for cold starts.

**Display blank but REPL responds:**
- The display runs on Core 1. If the firmware is old, update to the latest UF2.

**USB REPL not connecting (no serial port appears):**
- Firmware must be built with `BOARD=RPI_PICO2_W`. Default `RPI_PICO` is the wrong chip.
- MicroPython must be pinned to v1.25.0-preview. Later versions (v1.28+) have a USB regression on RP2350.
- Check with `ls /dev/tty.usbmodem*` (macOS) or `ls /dev/ttyACM*` (Linux).

**Thonny shows `KeyboardInterrupt` traceback on connect:**
- This is normal! Thonny sends Ctrl+C to interrupt `main.py`'s menu loop. You'll see a traceback followed by `>>>`. This means Thonny connected successfully.

**Thonny shows "Unexpected read during raw paste":**
- Deploy `boot_thonny.py` as `/boot.py` on the device (meaning rename boot_thonny.py as boot.py). This skips `os.dupterm()` which conflicts with Thonny's raw paste protocol. The PicoCalc screen and keyboard still work for apps and the menu — only REPL output moves to Thonny's shell panel instead of the device screen.
- To switch back to standard boot: deploy `boot.py` as `/boot.py`.
- The dashboard and mpremote work with the standard `boot.py` and don't need the Thonny variant.

---

## What's New in v2.0

- **Development Dashboard** — local web UI (`python3 MicroPython/tools/dashboard.py`) with FTP-style dual-pane file manager, in-browser editor, REPL, drag-and-drop deploy, file diff, and macOS junk cleanup
- **Flicker-free display** — `beginDraw()` blocks Core 1 during screen clear to prevent white flash artifacts
- **Firmware build pipeline** — Dockerfile pinned to known-good MicroPython v1.25.0 for USB stability on RP2350
- **Boot/main split** — USB REPL available immediately after boot; Thonny and mpremote can connect without issues
- **WiFiManager rewrite** — full VT100 terminal UI with arrow-key navigation, color-coded signal bars, channel congestion analysis, real-time signal monitor
- **On-device code editor** — browse, create, edit, and delete scripts directly on the PicoCalc, no computer needed
- **Demo app** — visual display showcase with grayscale palette, animated boxes, scrolling gradient
- **Thonny support** — `boot_thonny.py` variant for Thonny users (skips dupterm)
- **Dashboard code editor** — Python syntax highlighting and PicoCalc-aware linting (vendored CodeMirror, works offline)
- **Codebase cleanup** — consolidated ProxiScan variants, removed legacy scripts and archive directory

---

## Credits

Built on [PicoCalc-micropython-driver](https://github.com/zenodante/PicoCalc-micropython-driver) by **zenodante** (LCD driver, keyboard logic, original 1.0 UF2 image).

## License

[MIT License](LICENSE)

## Contact

- Issues: [GitHub Issues](https://github.com/LofiFren/PicoCalc/issues)
- IG: [@lofifren](https://www.instagram.com/lofifren/)
- YT: [@lofifren](https://www.youtube.com/@lofifren)
- YouTube PicoCalc 2.0 Demo: [https://youtu.be/gf3ittEwFJ8](https://youtu.be/gf3ittEwFJ8)
- Playlist: [PicoCalc Playlist](https://www.youtube.com/playlist?list=PL9WsMKb7awj9qmWcUHpMxpqV1nPUyIeuq)
