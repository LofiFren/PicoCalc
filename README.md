# PicoCalc MicroPython

A MicroPython firmware and script collection for the Clockwork Pi PicoCalc handheld device, powered by the **Raspberry Pi Pico 2W**. Features:

- 320x320 LCD display with flicker-free rendering
- Membrane keyboard with VT100 terminal
- Arrow-key navigable menu system
- Games (Tetris, Snake), 4-instrument Synthesizer, BLE Keyboard, WiFi Manager, LLM client
- Development dashboard with file manager, editor, diff, REPL, eject
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

The easiest way -- a local web UI that handles everything:

```bash
python3 MicroPython/tools/dashboard.py
```

This opens a browser dashboard where you can:
- **Deploy All** -- pushes boot files, modules, and scripts in one click
- **Browse** device files, view diffs, push individual files
- **Drag-and-drop** `.py` files to upload
- **Side-by-side diff** -- click a modified file to see device vs local changes color-coded
- **New script** -- create scripts from a starter template with one click
- **REPL** -- run Python on the device from the browser (30s timeout per command)
- **Eject** -- safely disconnect with on-device countdown, then unplug USB
> First run will prompt to install `mpremote` if needed. Requires Python 3.7+.
>
> **Adding new files:** Scripts in `modules/` and `sd/py_scripts/` are auto-discovered by the dashboard. Root-level files (like `boot.py`) must be added to `FILE_MAP` in `dashboard.py` to appear.

#### Option B: AI-Assisted Development (Vibe Coding)

Let your AI coding assistant talk directly to the PicoCalc -- write code, push it, test on device, iterate, all from the AI conversation.

**MCP Server (Recommended)**

[MCP](https://modelcontextprotocol.io/) gives AI tools native access to the device with no dashboard running. Add to your `.mcp.json` or Claude Desktop config:

```json
{
  "mcpServers": {
    "picocalc": {
      "command": "python3",
      "args": ["/path/to/PicoCalc/MicroPython/tools/mcp_server.py"]
    }
  }
}
```

Works with Claude Code, Claude Desktop, Cursor, and any MCP-compatible tool. Full setup guide: **[MCP_README.md](MicroPython/tools/MCP_README.md)**

**Claude Code Skills (Optional)**

For Claude Code users, the [code-skills](https://github.com/LofiFren/code-skills) repo provides PicoCalc-specific skills that teach the AI how to write correct apps, use the hardware APIs, review code, and handle device operations. The MCP server gives the AI hands to interact with the device; the skills give it the knowledge to build for it.

```
# With skill-deployer installed, just paste a URL:
"install this skill https://github.com/LofiFren/code-skills/tree/main/skills/picocalc-app"
```

**Dashboard REST API (Legacy)**

If you already have the dashboard running, AI tools can also use its HTTP endpoints:

```bash
curl -s http://localhost:8265/api/device                          # Device status
curl -s -X POST http://localhost:8265/api/exec -H 'Content-Type: application/json' \
  -d '{"code": "print(1+1)"}'                                     # Run Python on device
curl -s -X POST http://localhost:8265/api/push -H 'Content-Type: application/json' \
  -d '{"file": "sd/py_scripts/my_app.py"}'                        # Push file to device
curl -s "http://localhost:8265/api/diff?file=sd/py_scripts/synth.py"  # Diff local vs device
curl -s -X POST http://localhost:8265/api/eject                   # Safe disconnect
```

All endpoints: `/api/device`, `/api/exec`, `/api/push`, `/api/pull`, `/api/files`, `/api/diff`, `/api/local/tree`, `/api/eject`, `/api/reset`, `/api/cleanup`

#### Option C: Manual

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
```

### 3. Prepare the SD Card

1. Format an SD card as **FAT32** (4GB-32GB recommended).
2. Create a `py_scripts` folder on the SD card.
3. Copy all `.py` files from `MicroPython/sd/py_scripts/` into that folder.
4. Insert the SD card into the PicoCalc.

> Or use the Dashboard -- click **Deploy Scripts** to push all scripts to the SD card over USB.

### 4. Boot

Power cycle the PicoCalc. The boot splash shows initialization progress, then the main menu appears with arrow-key navigation.

---

## Repository Structure

```
MicroPython/
|-- boot.py                  --> Copy to device /
|-- main.py                  --> Copy to device / (launches menu)
|-- boot_thonny.py           --> Deploy as /boot.py for Thonny users
|-- boot_dev.py              --> Deploy as /boot.py for dev mode (REPL only)
|-- cleanup.py               --> (Optional) one-time cleanup, or use dashboard Cleanup button
|-- modules/                 --> Copy to device /modules/
|   |-- picocalc.py              Hardware abstraction (display + keyboard)
|   |-- vt.py                    VT100 terminal emulator
|   |-- py_run.py                Menu system with arrow-key navigation
|   |-- enhanced_sd.py           SD card initialization
|   |-- picocalc_system.py       System utilities
|   |-- sdcard.py                SD card driver
|   |-- checksd.py               SD card verification
|   |-- pye.py                   Built-in text editor
|   |-- colorer.py               Terminal color support
|   |-- default_style.py         Syntax highlighting styles
|   |-- highlighter.py           Code syntax highlighting
|   |-- flush.py                 Module cache flushing
|   \-- mkdir.py                 Directory creation utility
|-- sd/py_scripts/           --> Copy contents to SD card /py_scripts/
|   |-- tetris.py                Tetris with sound effects
|   |-- snake.py                 Snake with high scores
|   |-- synth.py                 4-instrument synthesizer with piano keyboard
|   |-- ProxiScan.py             BLE proximity scanner & fox hunt tool
|   |-- WiFiManager.py           WiFi scanning & connection manager
|   |-- picocalc_ollama.py       Local LLM client (Ollama)
|   |-- brad.py                  WiFi utility library
|   |-- demo.py                  Visual display showcase (grayscale, animation)
|   \-- editor.py                On-device file browser + code editor
|-- firmware/                    Prebuilt UF2 firmware images
|   |-- picocalc_micropython_pico2w.uf2   (v1.25.0, stable)
|   |-- picocalc_v127_pico2w.uf2          (v1.27.0, patched)
|   |-- Dockerfile                         Build for v1.25.0
|   |-- Dockerfile.v127                    Build for v1.27.0 + USB fix
|   \-- USB_REGRESSION_FIX.md              RP2350 USB bug report
|-- micropython.cmake            Top-level build config for C modules
|-- picocalcdisplay/             C display driver (compiled into firmware)
|   |-- picocalcdisplay.c
|   |-- picocalcdisplay.h
|   |-- font6x8e500.h
|   \-- micropython.cmake
|-- vtterminal/                  C terminal emulator (compiled into firmware)
|   |-- vtterminal.c
|   |-- vtterminal.h
|   |-- font6x8.h
|   \-- micropython.cmake
|-- tools/                       Development tools
|   |-- dashboard.py                 Web UI server (run this!)
|   |-- mcp_server.py                MCP server for AI assistants (see tools/MCP_README.md)
|   |-- bottle.py                    Vendored web framework (zero install)
|   \-- static/
|       |-- index.html               Dashboard frontend
|       \-- vendor/                  CodeMirror editor (vendored, offline)
```

---

## Applications

| App | Description |
|-----|-------------|
| **Tetris** | Classic Tetris with 7 pieces, ghost piece, sound effects, level progression |
| **Snake** | Snake with high score tracking, speed levels, sound |
| **[Synth](SYNTH.md)** | 4-instrument synthesizer (Piano, Organ, Strings, Synth) with QWERTY piano keyboard, ADSR envelope, arpeggiator, 16-step sequencer, LFO effects, presets |
| **ProxiScan** | BLE proximity scanner, fox hunt tool with compass, signal tracking, competition timer, waypoints, antenna calibration |
| **WiFiManager** | WiFi scanner with VT100 UI, signal bars, channel analysis, signal monitor |
| **Ollama Client** | Chat with local LLMs over WiFi via Ollama |
| **Demo** | Visual display showcase: grayscale palette, bouncing boxes, scrolling gradient, device info |
| **Editor** | On-device file browser and code editor -- browse, create, edit, delete scripts without a computer |

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

The prebuilt UF2 files in `firmware/` are ready to flash -- **building from source is not required**. Only do this if you want to modify the C display/terminal drivers or experiment with different MicroPython versions.

Requires: [Docker Desktop](https://www.docker.com/products/docker-desktop/).

### Option A: Standard Build (v1.25.0 -- recommended)

Stable, known-good USB. Used by the prebuilt `picocalc_micropython_pico2w.uf2`.

```bash
# 1. Build the Docker image (one-time, ~5 min)
docker build -t picocalc-build MicroPython/firmware/

# 2. Compile firmware with PicoCalc C modules (~3 min)
docker run --rm \
  -v $(pwd)/MicroPython:/picocalc \
  -v $(pwd)/MicroPython/firmware:/out \
  picocalc-build \
  bash -c "make BOARD=RPI_PICO2_W USER_C_MODULES=/picocalc/micropython.cmake -j\$(nproc) && \
           cp build-RPI_PICO2_W/firmware.uf2 /out/picocalc_micropython_pico2w.uf2"
```

### Option B: Patched v1.27.0 Build

Newer MicroPython with BLE pairing APIs enabled. Includes a two-line patch for the RP2350 USB regression (see `firmware/USB_REGRESSION_FIX.md`).

```bash
# 1. Build the Docker image (one-time, ~5 min)
docker build -t picocalc-v127 -f MicroPython/firmware/Dockerfile.v127 MicroPython/firmware/

# 2. Compile firmware (~3 min)
docker run --rm \
  -v $(pwd)/MicroPython:/picocalc \
  -v $(pwd)/MicroPython/firmware:/out \
  picocalc-v127 \
  bash -c "make BOARD=RPI_PICO2_W USER_C_MODULES=/picocalc/micropython.cmake -j\$(nproc) && \
           cp build-RPI_PICO2_W/firmware.uf2 /out/picocalc_v127_pico2w.uf2"
```

### Firmware Files

| File | MicroPython | Notes |
|------|-------------|-------|
| `picocalc_micropython_pico2w.uf2` | v1.25.0-preview | Stable default, all apps work |
| `picocalc_v127_pico2w.uf2` | v1.27.0 (patched) | BLE pairing APIs, USB fix applied |
| `Dockerfile` | v1.25.0-preview | Standard build |
| `Dockerfile.v127` | v1.27.0 + patches | USB fix + BLE security enabled |
| `USB_REGRESSION_FIX.md` | -- | Bug analysis and patch details |

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
- The C source directories (`picocalcdisplay/`, `vtterminal/`) may be on the device filesystem, shadowing the C modules compiled into firmware. Delete them from the device -- they should only exist in the repo, not on the Pico.
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
- MicroPython v1.26.0, v1.27.0, and v1.28.0+ all have a USB regression on RP2350 ([#18990](https://github.com/micropython/micropython/issues/18990)). Use either the v1.25.0-preview firmware or the patched v1.27.0 (`picocalc_v127_pico2w.uf2`).
- Check with `ls /dev/tty.usbmodem*` (macOS) or `ls /dev/ttyACM*` (Linux).

**Thonny shows `KeyboardInterrupt` traceback on connect:**
- This is normal! Thonny sends Ctrl+C to interrupt `main.py`'s menu loop. You'll see a traceback followed by `>>>`. This means Thonny connected successfully.

**Thonny shows "Unexpected read during raw paste":**
- Deploy `boot_thonny.py` as `/boot.py` on the device (meaning rename boot_thonny.py as boot.py). This skips `os.dupterm()` which conflicts with Thonny's raw paste protocol. The PicoCalc screen and keyboard still work for apps and the menu -- only REPL output moves to Thonny's shell panel instead of the device screen.
- To switch back to standard boot: deploy `boot.py` as `/boot.py`.
- The dashboard and mpremote work with the standard `boot.py` and don't need the Thonny variant.

---

## What's New in v3.0

- **[MCP Server](MicroPython/tools/MCP_README.md)** -- AI coding assistants (Claude Code, Claude Desktop, Cursor) can talk directly to the PicoCalc over USB via the Model Context Protocol -- run code, read/push files, check status, no dashboard needed
- **[Synth 4.0](SYNTH.md)** -- ground-up rewrite with 4 instruments (Piano, Organ, Strings, Synth), QWERTY piano keyboard, ADSR envelope, arpeggiator, 16-step sequencer, LFO, presets, stereo harmonic enrichment
- **Dashboard eject button** -- sends 7-second countdown to device screen, then reboots to menu for safe USB unplug
- **Dashboard side-by-side diff** -- click a modified file to see device vs local changes color-coded in a split view
- **Dashboard new script** -- "+" button creates scripts from a starter template, opens in editor
- **Smart file clicks** -- modified files auto-show diff, clean files open in editor
- **Adaptive polling** -- 1.5s when disconnected for fast reconnection, 5s when connected
- **Firmware v1.27.0 option** -- patched build with USB fix and BLE pairing APIs (see `firmware/Dockerfile.v127`)
- **USB regression fix** -- discovered and patched MicroPython RP2350 USB-CDC bug affecting v1.26.0+ ([#18990](https://github.com/micropython/micropython/issues/18990))
- **Audio quality** -- anti-click retrigger, soft duty ceiling, per-instrument stereo overtones, frequency-scaled decay
- **Removed PicoBLE** -- old BLE file transfer removed (dashboard handles file transfer over USB)

## What's New in v2.0

- **Development Dashboard** -- local web UI (`python3 MicroPython/tools/dashboard.py`) with FTP-style dual-pane file manager, in-browser editor, REPL, drag-and-drop deploy, file diff, and macOS junk cleanup
- **Flicker-free display** -- `beginDraw()` blocks Core 1 during screen clear to prevent white flash artifacts
- **Firmware build pipeline** -- Dockerfile pinned to known-good MicroPython v1.25.0 for USB stability on RP2350
- **Boot/main split** -- USB REPL available immediately after boot; Thonny and mpremote can connect without issues
- **WiFiManager rewrite** -- full VT100 terminal UI with arrow-key navigation, color-coded signal bars, channel congestion analysis, real-time signal monitor
- **On-device code editor** -- browse, create, edit, and delete scripts directly on the PicoCalc, no computer needed
- **Demo app** -- visual display showcase with grayscale palette, animated boxes, scrolling gradient
- **Thonny support** -- `boot_thonny.py` variant for Thonny users (skips dupterm)
- **Dashboard code editor** -- Python syntax highlighting and PicoCalc-aware linting (vendored CodeMirror, works offline)
- **Codebase cleanup** -- consolidated ProxiScan variants, removed legacy scripts and archive directory

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
