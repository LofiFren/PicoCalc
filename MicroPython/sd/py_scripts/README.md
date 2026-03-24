# PicoCalc Python Scripts

This directory contains MicroPython scripts for the PicoCalc device, organized by functionality.

## Radio Direction Finding (RDF) / Fox Hunting

**ProxiScan Series** - Bluetooth-based proximity scanning and direction finding:
- `ProxiScan_3.0.py` - Full-featured fox hunt edition with RDF capabilities, compass interface, and audio feedback
- `ProxiScan_compact.py` - Lightweight version for basic proximity scanning

**Fox Hunt Tools** - Amateur radio direction finding competition tools:
- `FoxHunt_competition.py` - ARDF scanner for competitions with timing and waypoint logging
- `FoxHunt_lite.py` - Text-based lightweight fox hunting tool

## Network & Connectivity

- `NetworkTools.py` - Unified launcher for all network tools with memory management
- `WiFiManager.py` - WiFi connection management and utilities

## Audio & Entertainment

- `synth.py` - 4-instrument synthesizer with piano keyboard, ADSR, arpeggiator, sequencer, presets ([full docs](../../../SYNTH.md))
- `tetris.py` - Complete Tetris game implementation with sound effects and progressive difficulty

## AI Integration

- `picocalc_ollama.py` - Local LLM client for interacting with Ollama models over WiFi
- `start_ollama.sh` - Shell script to start Ollama server on host machine

## Utilities

- `brad.py` - Core utility functions and device management
- `sd_chk.py` - SD card health checking and diagnostics
- `sim.py` - Device simulation and testing utilities
- `flush_menu.py` - Menu system management

## Archive Directories

- `archive/` - Previous versions of scripts (ProxiScan v1, v2, WiFiManager classic)

## Quick Start

### For Radio Direction Finding:
```python
# Launch unified network tools menu
exec(open('NetworkTools.py').read())
```

### For Audio Synthesis:
```python
# Start the synthesizer
exec(open('synth.py').read())
```

### For AI Chat:
```python
# Connect to local Ollama instance
exec(open('picocalc_ollama.py').read())
```

### For Gaming:
```python
# Play Tetris
exec(open('tetris.py').read())
```

## Hardware Requirements

- **Audio Output**: GPIO pins 27/28 for stereo audio (headphone jack + speaker)
- **Display**: 4-bit grayscale display support
- **Storage**: SD card for logging and configuration
- **Wireless**: WiFi and Bluetooth capabilities
- **Input**: Arrow keys and standard keyboard input

## Configuration

Most scripts include configuration sections at the top for:
- Audio pin assignments
- Display color themes
- Network settings (IP addresses, ports)
- Logging directories
- Calibration values for RF measurements

## Features by Category

### RDF/Fox Hunting Features:
- Real-time RSSI measurement and direction finding
- Audio tone feedback for signal strength
- Compass-style directional displays
- Competition timing and logging
- Target tracking and waypoint recording

### Audio Features:
- Stereo PWM audio output
- Real-time waveform visualization
- Multiple synthesis methods
- VU meters and audio monitoring
- Headphone/speaker routing control

### Network Features:
- WiFi scanning and connection management
- BLE device discovery and analysis
- MAC address vendor identification
- Signal strength monitoring
- Network diagnostics

## Logging

Scripts create logs in `/sd/logs/` directory:
- `foxhunt_log.txt` - RDF session data
- `competition_log.txt` - Competition timing and results
- Various debug and diagnostic logs

---

*These scripts are designed for educational and amateur use. Ensure compliance with local regulations when using RF-related tools.*