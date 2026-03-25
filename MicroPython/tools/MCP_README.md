# PicoCalc MCP Server

Give your AI coding assistant direct access to the PicoCalc device over USB.

[MCP (Model Context Protocol)](https://modelcontextprotocol.io/) is an open standard that lets AI tools call external functions. This server exposes your PicoCalc as a set of tools -- the AI can check device status, run MicroPython code, read and push files, and reset the device, all without you copy-pasting anything.

---

## Prerequisites

- **PicoCalc** connected via USB (serial port visible)
- **Python 3.7+**
- **mpremote** -- install with `pip install mpremote` (or `pip3 install mpremote`)

Verify your device is connected:

```bash
# macOS
ls /dev/tty.usbmodem*

# Linux
ls /dev/ttyACM*
```

---

## Setup

### Claude Code (CLI)

Add to your project's `.mcp.json` (or create it in the repo root):

```json
{
  "mcpServers": {
    "picocalc": {
      "command": "python3",
      "args": ["/full/path/to/PicoCalc/MicroPython/tools/mcp_server.py"]
    }
  }
}
```

Then restart Claude Code. You'll see the PicoCalc tools available automatically.

### Claude Desktop

Open **Settings > Developer > Edit Config** and add under `mcpServers`:

```json
{
  "mcpServers": {
    "picocalc": {
      "command": "python3",
      "args": ["/full/path/to/PicoCalc/MicroPython/tools/mcp_server.py"]
    }
  }
}
```

Restart Claude Desktop. The PicoCalc tools appear in the tool list.

### Cursor / Other MCP Clients

Any tool that supports MCP's stdio transport works. Point it at:

```
python3 MicroPython/tools/mcp_server.py
```

---

## Available Tools

| Tool | What it does |
|------|-------------|
| `picocalc_status` | Check connection, firmware version, free RAM, SD card space |
| `picocalc_exec` | Run MicroPython code on the device (30s timeout) |
| `picocalc_list_files` | List files at a device path (default: `/sd/py_scripts`) |
| `picocalc_read_file` | Read a file from the device |
| `picocalc_push` | Push a local file to the device |
| `picocalc_reset` | Soft reset (re-runs boot.py and main.py) |

---

## Try It

Once configured, just ask your AI assistant:

> "Check if the PicoCalc is connected"

It will call `picocalc_status` and show you something like:

```
Connected
  Firmware: MicroPython 1.25.0
  Platform: rp2
  RAM free: 326 KB
  SD free:  2 MB
```

Then try:

> "Run `print('Hello from PicoCalc!')` on the device"

> "List the scripts on the SD card"

> "Read the synth.py file from the device"

The AI can also write code, push it to the device, and test it -- all in one conversation.

---

## How It Works

```
AI Assistant <--stdio--> mcp_server.py <--mpremote--> PicoCalc (USB)
```

The server uses `mpremote` (MicroPython's official tool) to communicate with the device over USB serial. Each tool call acquires a lock, runs the mpremote command, and returns the result. No background processes, no daemons -- it starts when the AI client launches it and stops when the client exits.

---

## Troubleshooting

**"mpremote not found"**
- Install it: `pip3 install mpremote`
- Make sure it's on your PATH: `which mpremote`

**"Device not connected"**
- Check USB cable (some are charge-only, no data)
- Verify serial port exists: `ls /dev/tty.usbmodem*` (macOS) or `ls /dev/ttyACM*` (Linux)
- Close other programs using the serial port (Thonny, screen, etc.) -- only one connection at a time

**"timeout"**
- The device may be running an app with a main loop. Press ESC on the PicoCalc to return to the menu, then try again
- `picocalc_exec` has a 30-second timeout -- don't use it to launch apps with infinite loops

**Tools not appearing in Claude**
- Check the path in your MCP config is correct and absolute
- Restart your AI client after editing the config
- Check stderr output: `python3 MicroPython/tools/mcp_server.py` should print "PicoCalc MCP Server starting..."

**Dashboard vs MCP**
- The [Dashboard](../../README.md) (`dashboard.py`) is a web UI you use in your browser
- The MCP server is for AI assistants -- they call it directly, no browser needed
- Both use `mpremote` under the hood, so don't run them at the same time
