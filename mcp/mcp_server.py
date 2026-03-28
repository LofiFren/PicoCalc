#!/usr/bin/env python3
"""
PicoCalc MCP Server
Gives AI assistants direct access to a PicoCalc device over USB.

Usage:
  pip install picocalc-mcp && picocalc-mcp
  -- or --
  python3 mcp/mcp_server.py

MCP config:
{
  "mcpServers": {
    "picocalc": {
      "command": "picocalc-mcp"
    }
  }
}

Author: LofiFren (https://github.com/LofiFren/PicoCalc)
"""

import sys
import json
import subprocess
import shutil
import threading
from pathlib import Path

# --- mpremote wrapper (shared with dashboard.py) ---

MPREMOTE = shutil.which("mpremote") or "mpremote"

class DeviceManager:
    def __init__(self):
        self.lock = threading.Lock()

    def _run(self, *args, timeout=30):
        cmd = [MPREMOTE, "resume"] + list(args)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except FileNotFoundError:
            return -1, "", "mpremote not found"
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)

    def is_connected(self):
        with self.lock:
            rc, out, err = self._run("eval", "1", timeout=5)
            return rc == 0

    def exec_code(self, code):
        with self.lock:
            rc, out, err = self._run("exec", code, timeout=30)
            return {"rc": rc, "out": out.strip(), "err": err.strip()}

    def device_info(self):
        code = (
            "import gc, os, sys\n"
            "gc.collect()\n"
            "d = {}\n"
            "d['platform'] = sys.platform\n"
            "d['version'] = '.'.join(str(x) for x in sys.implementation.version)\n"
            "d['ram_free'] = gc.mem_free()\n"
            "d['ram_used'] = gc.mem_alloc()\n"
            "try:\n"
            "    st = os.statvfs('/sd')\n"
            "    d['sd_free'] = st[0] * st[3]\n"
            "except:\n"
            "    d['sd_free'] = 0\n"
            "print(d)\n"
        )
        with self.lock:
            rc, out, err = self._run("exec", code, timeout=10)
            if rc != 0:
                return None
            for line in out.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        return eval(line)
                    except:
                        pass
            return None

    def list_files(self, path="/sd/py_scripts"):
        code = (
            f"import os\n"
            f"for f in sorted(os.listdir('{path}')):\n"
            f"    try:\n"
            f"        s = os.stat('{path}/' + f)\n"
            f"        print(('d' if s[0] & 0x4000 else 'f') + '|' + f + '|' + str(s[6]))\n"
            f"    except:\n"
            f"        print('?|' + f + '|0')\n"
        )
        with self.lock:
            rc, out, err = self._run("exec", code, timeout=10)
            files = []
            for line in out.strip().split("\n"):
                parts = line.strip().split("|", 2)
                if len(parts) == 3:
                    files.append({
                        "type": parts[0],
                        "name": parts[1],
                        "size": int(parts[2]) if parts[2].isdigit() else 0
                    })
            return files

    def push_file(self, local_path, remote_path):
        with self.lock:
            rc, out, err = self._run("fs", "cp", str(local_path), f":{remote_path}", timeout=30)
            if rc == 0:
                self._run("exec", "import os; os.sync()", timeout=5)
            return rc == 0, out + err

    def read_file(self, remote_path):
        with self.lock:
            rc, out, err = self._run("fs", "cat", f":{remote_path}", timeout=15)
            return out if rc == 0 else None

    def soft_reset(self):
        with self.lock:
            rc, out, err = self._run("soft-reset", timeout=10)
            return rc == 0


# --- MCP Protocol ---

dm = DeviceManager()

TOOLS = [
    {
        "name": "picocalc_status",
        "description": "Check PicoCalc device connection status, RAM, SD card, and firmware version.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "picocalc_exec",
        "description": "Execute MicroPython code on the PicoCalc device. Returns stdout and stderr. Use for testing, debugging, reading sensors, or running one-off commands. 30 second timeout -- do not use for launching apps with main loops.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute on the device"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "picocalc_push",
        "description": "Push a local file to the PicoCalc device. The local_path is relative to the MicroPython/ directory in the project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "local_path": {
                    "type": "string",
                    "description": "Local file path relative to MicroPython/ dir (e.g. sd/py_scripts/my_app.py)"
                },
                "remote_path": {
                    "type": "string",
                    "description": "Device path (e.g. /sd/py_scripts/my_app.py)"
                }
            },
            "required": ["local_path", "remote_path"]
        }
    },
    {
        "name": "picocalc_list_files",
        "description": "List files on the PicoCalc device at a given path. Returns file names, types, and sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Device directory path (default: /sd/py_scripts)",
                    "default": "/sd/py_scripts"
                }
            }
        }
    },
    {
        "name": "picocalc_read_file",
        "description": "Read a file from the PicoCalc device and return its contents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Device file path (e.g. /sd/py_scripts/synth.py)"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "picocalc_reset",
        "description": "Soft reset the PicoCalc device. Re-runs boot.py and main.py.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        }
    },
]


def handle_request(req):
    method = req.get("method")
    params = req.get("params", {})
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "picocalc",
                    "version": "1.0.0"
                }
            }
        }

    elif method == "notifications/initialized":
        return None  # no response needed

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        result = call_tool(tool_name, args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result}]
            }
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    }


def call_tool(name, args):
    try:
        if name == "picocalc_status":
            if not dm.is_connected():
                return "Device not connected. Check USB cable."
            info = dm.device_info()
            if info:
                ram_kb = info.get('ram_free', 0) // 1024
                sd_mb = info.get('sd_free', 0) // (1024 * 1024)
                return (
                    f"Connected\n"
                    f"  Firmware: MicroPython {info.get('version', '?')}\n"
                    f"  Platform: {info.get('platform', '?')}\n"
                    f"  RAM free: {ram_kb} KB\n"
                    f"  SD free:  {sd_mb} MB"
                )
            return "Connected but could not read device info."

        elif name == "picocalc_exec":
            code = args.get("code", "")
            if not code:
                return "Error: no code provided"
            result = dm.exec_code(code)
            out = result["out"]
            err = result["err"]
            if result["rc"] == 0:
                return out if out else "(no output)"
            return f"Error (rc={result['rc']}):\n{err}\n{out}".strip()

        elif name == "picocalc_push":
            local_rel = args.get("local_path", "")
            remote = args.get("remote_path", "")
            if not local_rel or not remote:
                return "Error: local_path and remote_path required"
            mp_dir = Path(__file__).parent.parent / "MicroPython"
            local_full = mp_dir / local_rel
            if not local_full.exists():
                return f"Error: local file not found: {local_full}"
            ok, msg = dm.push_file(local_full, remote)
            return f"OK: {local_rel} -> {remote}" if ok else f"Failed: {msg}"

        elif name == "picocalc_list_files":
            path = args.get("path", "/sd/py_scripts")
            files = dm.list_files(path)
            if not files:
                return f"No files found at {path} (or device not connected)"
            lines = [f"{path}/"]
            for f in files:
                t = "DIR " if f["type"] == "d" else "    "
                sz = f"{f['size'] // 1024}K" if f["size"] >= 1024 else f"{f['size']}B"
                lines.append(f"  {t}{f['name']:30s} {sz}")
            return "\n".join(lines)

        elif name == "picocalc_read_file":
            path = args.get("path", "")
            if not path:
                return "Error: path required"
            content = dm.read_file(path)
            if content is None:
                return f"Error: could not read {path}"
            return content

        elif name == "picocalc_reset":
            ok = dm.soft_reset()
            return "Device reset OK" if ok else "Reset failed"

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        return f"Error: {e}"


def main():
    """MCP stdio transport -- read JSON-RPC from stdin, write to stdout."""
    sys.stderr.write("PicoCalc MCP Server starting...\n")
    sys.stderr.write(f"mpremote: {MPREMOTE}\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
