#!/usr/bin/env python3
"""PicoCalc Development Dashboard -- local web UI for device management.

Usage:
    python3 dashboard.py              Launch dashboard (opens browser)
    python3 dashboard.py --port 9000  Use a different port
    python3 dashboard.py --no-open    Don't auto-open browser

Requirements: Python 3.7+, mpremote (auto-installed if missing)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
import difflib
from pathlib import Path


def ensure_mpremote():
    """Check for mpremote and offer to install it if missing."""
    if shutil.which("mpremote"):
        return True
    print("\n  mpremote is not installed (needed to talk to the PicoCalc).\n")
    try:
        answer = input("  Install it now? (pip install mpremote) [Y/n] ").strip().lower()
    except EOFError:
        answer = "y"
    if answer in ("", "y", "yes"):
        print("  Installing mpremote...")
        rc = subprocess.call([sys.executable, "-m", "pip", "install", "mpremote"])
        if rc == 0:
            print("  mpremote installed successfully.\n")
            return True
        else:
            print("  Installation failed. Try manually: pip install mpremote\n")
            return False
    else:
        print("  Skipped. Dashboard will start but device features won't work.\n")
        return False


ensure_mpremote()

# Vendored bottle.py (single file, zero deps)
sys.path.insert(0, os.path.dirname(__file__))
from bottle import Bottle, request, response, static_file, abort

# --- Configuration ---

PORT = 8265
HOST = "127.0.0.1"
MPREMOTE = "mpremote"

def find_project_root():
    """Walk up from this script to find MicroPython/ directory."""
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "boot.py").exists() and (d / "modules").is_dir():
            return d
        if (d / "MicroPython" / "boot.py").exists():
            return d / "MicroPython"
        d = d.parent
    # Fallback: assume script is in MicroPython/tools/
    return Path(__file__).resolve().parent.parent

MP_DIR = find_project_root()

# --- File mapping ---
#
# ROOT FILES: Files in the MicroPython/ root must be listed here
# explicitly so the dashboard knows where to put them on the device.
# Add new root-level .py files here as "filename.py": "/filename.py".
#
# MODULES & SCRIPTS: Files in modules/ and sd/py_scripts/ are
# auto-discovered by glob -- no need to add them here.
#
FILE_MAP = {
    "boot.py": "/boot.py",
    "main.py": "/main.py",
    "boot_thonny.py": "/boot_thonny.py",
    "boot_dev.py": "/boot_dev.py",
}

# --- Device Manager ---

class DeviceManager:
    """Thread-safe wrapper around mpremote subprocess calls."""

    def __init__(self):
        self.lock = threading.Lock()
        self.port = None  # auto-detect

    def _run(self, *args, timeout=30):
        """Run mpremote command, return (returncode, stdout, stderr)."""
        cmd = [MPREMOTE]
        if self.port:
            cmd += ["connect", self.port]
        cmd += ["resume"] + list(args)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except FileNotFoundError:
            return -1, "", "mpremote not found. Install: pip install mpremote"

    def is_connected(self):
        with self.lock:
            rc, out, err = self._run("eval", "1", timeout=5)
            return rc == 0

    def device_info(self):
        with self.lock:
            code = """
import gc, os, sys
gc.collect()
d = {}
d['platform'] = sys.platform
d['version'] = '.'.join(str(x) for x in sys.implementation.version)
d['impl'] = sys.implementation.name
d['ram_free'] = gc.mem_free()
d['ram_used'] = gc.mem_alloc()
try:
    st = os.statvfs('/sd')
    d['sd_total'] = st[0] * st[2]
    d['sd_free'] = st[0] * st[3]
except:
    d['sd_total'] = 0
    d['sd_free'] = 0
try:
    st = os.statvfs('/')
    d['flash_total'] = st[0] * st[2]
    d['flash_free'] = st[0] * st[3]
except:
    d['flash_total'] = 0
    d['flash_free'] = 0
print(d)
"""
            rc, out, err = self._run("exec", code, timeout=10)
            if rc != 0:
                return None
            # Parse the dict from stdout
            try:
                # Find the dict in output (skip any debug prints)
                for line in out.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        return eval(line)
            except Exception:
                pass
            return None

    def list_files(self, path="/"):
        """Return list of {name, type, size} dicts."""
        with self.lock:
            code = f"""
import os
path = '{path}'
result = []
try:
    for name in sorted(set(os.listdir(path))):
        full = path.rstrip('/') + '/' + name
        try:
            st = os.stat(full)
            is_dir = st[0] & 0x4000
            result.append((name, 'd' if is_dir else 'f', st[6] if not is_dir else 0))
        except:
            result.append((name, '?', 0))
except Exception as e:
    print('ERROR:' + str(e))
for r in result:
    print(r[1] + '|' + r[0] + '|' + str(r[2]))
"""
            rc, out, err = self._run("exec", code, timeout=10)
            files = []
            for line in out.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("ERROR:"):
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    files.append({
                        "type": parts[0],
                        "name": parts[1],
                        "size": int(parts[2]) if parts[2].isdigit() else 0,
                    })
            return files

    def read_file(self, path):
        """Read file content from device."""
        with self.lock:
            rc, out, err = self._run("fs", "cat", f":{path}", timeout=15)
            if rc != 0:
                return None
            return out

    def push_file(self, local_path, remote_path):
        """Copy local file to device."""
        with self.lock:
            rc, out, err = self._run("fs", "cp", str(local_path), f":{remote_path}", timeout=30)
            return rc == 0, (out + err).strip()

    def write_file_content(self, remote_path, content):
        """Write string content to a file on the device."""
        import tempfile
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py")
        try:
            tmp.write(content)
            tmp.close()
            return self.push_file(tmp.name, remote_path)
        finally:
            os.unlink(tmp.name)

    def read_local_file(self, rel_path):
        """Read a local project file."""
        local_path = MP_DIR / rel_path
        if not local_path.exists():
            return None
        return local_path.read_text()

    def delete_file(self, path):
        with self.lock:
            rc, out, err = self._run("fs", "rm", f":{path}", timeout=10)
            return rc == 0

    def delete_dir(self, path):
        """Recursively delete a directory on the device."""
        code = f"""
import os
def rmtree(p):
    for f in os.listdir(p):
        fp = p.rstrip('/') + '/' + f
        try:
            if os.stat(fp)[0] & 0x4000:
                rmtree(fp)
            else:
                os.remove(fp)
        except:
            pass
    os.rmdir(p)
try:
    rmtree('{path}')
    print('OK')
except Exception as e:
    print('ERR:' + str(e))
"""
        with self.lock:
            rc, out, err = self._run("exec", code, timeout=30)
            return "OK" in out

    def exec_code(self, code):
        with self.lock:
            rc, out, err = self._run("exec", code, timeout=30)
            return {"rc": rc, "out": out, "err": err}

    def cleanup_macos_junk(self):
        """Remove macOS Spotlight, fsevents, Trashes, DS_Store, ._ files from device."""
        code = """
import os

removed = []

def rm_tree(path):
    try:
        for f in os.listdir(path):
            fp = path + '/' + f
            try:
                s = os.stat(fp)
                if s[0] & 0x4000:
                    rm_tree(fp)
                else:
                    os.remove(fp)
            except:
                pass
        os.rmdir(path)
        removed.append(path)
    except:
        pass

def rm_file(path):
    try:
        os.remove(path)
        removed.append(path)
    except:
        pass

def clean_dir(base):
    try:
        entries = os.listdir(base)
    except:
        return
    for name in entries:
        full = base.rstrip('/') + '/' + name
        if name in ('.Spotlight-V100', '.fseventsd', '.Trashes'):
            rm_tree(full)
        elif name == '.DS_Store' or name.startswith('._'):
            rm_file(full)
        else:
            try:
                s = os.stat(full)
                if s[0] & 0x4000:
                    clean_dir(full)
            except:
                pass

clean_dir('/')
try:
    clean_dir('/sd')
except:
    pass

# Also remove stale source directories that shadow firmware C modules
# (left over from v1.0 upgrades)
for stale in ['/picocalcdisplay', '/vtterminal', '/Client_Code']:
    try:
        os.listdir(stale)
        rm_tree(stale)
    except:
        pass

# Remove stale root files from v1.0
for stale_f in ['/sd_chk.py', '/cleanup.py']:
    rm_file(stale_f)

if removed:
    for r in removed:
        print('REMOVED:' + r)
else:
    print('CLEAN:No junk found')
"""
        with self.lock:
            rc, out, err = self._run("exec", code, timeout=30)
            results = []
            for line in out.strip().split("\n"):
                line = line.strip()
                if line.startswith("REMOVED:"):
                    results.append(line[8:])
                elif line.startswith("CLEAN:"):
                    pass
            return results

    def soft_reset(self):
        with self.lock:
            rc, out, err = self._run("soft-reset", timeout=10)
            return rc == 0

    def eject(self):
        """Show a 7-second countdown on the PicoCalc screen, then hard
        reset.  The exec blocks for ~7s while the countdown runs on the
        device display, so use a generous timeout."""
        code = """\
import machine, utime
# Brief delay lets display settle after Ctrl-C interrupts the menu
utime.sleep_ms(200)
has_display = False
try:
    import picocalc
    d = picocalc.display
    if d:
        d.recoverRefresh()
        utime.sleep_ms(100)
        has_display = True
except:
    pass

for i in range(7, 0, -1):
    if has_display:
        try:
            d.beginDraw()
            d.fill(0)
            d.text('UNPLUG USB CABLE', 76, 50, 15)
            bw, bh = 60, 50
            bx, by = 130, 100
            d.fill_rect(bx, by, bw, bh, 12)
            d.rect(bx, by, bw, bh, 15)
            d.text(str(i), bx + 27, by + 21, 0)
            d.text('seconds until reboot', 60, 170, 6)
            bar_x, bar_w = 40, 240
            d.rect(bar_x, 200, bar_w, 10, 6)
            fill = bar_w * (7 - i) // 7
            if fill > 0:
                d.fill_rect(bar_x + 1, 201, fill, 8, 12)
            d.show()
        except:
            has_display = False
    utime.sleep_ms(1000)

if has_display:
    try:
        d.beginDraw()
        d.fill(0)
        d.text('Rebooting...', 112, 156, 15)
        d.show()
    except:
        pass
print('EJECT_OK')
machine.reset()
"""
        with self.lock:
            rc, out, err = self._run("exec", code, timeout=12)
            return "EJECT_OK" in out

    def deploy_boot(self):
        """Deploy boot.py and main.py to device root."""
        results = []
        for name in ["boot.py", "main.py"]:
            local = MP_DIR / name
            if local.exists():
                ok, msg = self.push_file(local, f"/{name}")
                results.append({"file": name, "ok": ok, "msg": msg})
            else:
                results.append({"file": name, "ok": False, "msg": "Not found locally"})
        return results

    def deploy_modules(self):
        """Deploy all modules/*.py to /modules/ on device."""
        # Ensure /modules/ exists
        self.exec_code("import os\ntry:\n os.mkdir('/modules')\nexcept:\n pass")
        results = []
        modules_dir = MP_DIR / "modules"
        if not modules_dir.is_dir():
            return [{"file": "modules/", "ok": False, "msg": "Directory not found"}]
        for f in sorted(modules_dir.glob("*.py")):
            ok, msg = self.push_file(f, f"/modules/{f.name}")
            results.append({"file": f"modules/{f.name}", "ok": ok, "msg": msg})
        return results

    def deploy_scripts(self):
        """Deploy all sd/py_scripts/*.py to /sd/py_scripts/ on device."""
        # Ensure dirs exist
        self.exec_code("import os\nfor p in ['/sd','/sd/py_scripts']:\n try:\n  os.mkdir(p)\n except:\n  pass")
        results = []
        scripts_dir = MP_DIR / "sd" / "py_scripts"
        if not scripts_dir.is_dir():
            return [{"file": "sd/py_scripts/", "ok": False, "msg": "Directory not found"}]
        for f in sorted(scripts_dir.glob("*.py")):
            ok, msg = self.push_file(f, f"/sd/py_scripts/{f.name}")
            results.append({"file": f"sd/py_scripts/{f.name}", "ok": ok, "msg": msg})
        return results

    def diff_file(self, local_rel_path):
        """Compare local file vs device file. Returns side-by-side diff data."""
        local_path = MP_DIR / local_rel_path

        # Determine device path
        if local_rel_path.startswith("modules/"):
            remote = f"/modules/{Path(local_rel_path).name}"
        elif local_rel_path.startswith("sd/py_scripts/"):
            remote = f"/sd/py_scripts/{Path(local_rel_path).name}"
        elif local_rel_path in FILE_MAP:
            remote = FILE_MAP[local_rel_path]
        else:
            remote = f"/{local_rel_path}"

        if not local_path.exists():
            return None, "Local file not found"

        local_content = local_path.read_text()
        device_content = self.read_file(remote)
        if device_content is None:
            return None, f"Device file not found: {remote}"

        local_lines = local_content.splitlines()
        device_lines = device_content.splitlines()

        # Build side-by-side diff: local (left) vs device (right)
        sm = difflib.SequenceMatcher(None, local_lines, device_lines)
        rows = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    rows.append({'t': 'eq', 'ln_l': i+1, 'l': local_lines[i],
                                 'ln_r': j+1, 'r': device_lines[j]})
            elif tag == 'replace':
                max_len = max(i2 - i1, j2 - j1)
                for k in range(max_len):
                    left = local_lines[i1+k] if i1+k < i2 else None
                    right = device_lines[j1+k] if j1+k < j2 else None
                    rows.append({'t': 'chg',
                                 'ln_l': i1+k+1 if left is not None else None,
                                 'l': left,
                                 'ln_r': j1+k+1 if right is not None else None,
                                 'r': right})
            elif tag == 'delete':
                for i in range(i1, i2):
                    rows.append({'t': 'del', 'ln_l': i+1, 'l': local_lines[i],
                                 'ln_r': None, 'r': None})
            elif tag == 'insert':
                for j in range(j1, j2):
                    rows.append({'t': 'ins', 'ln_l': None, 'l': None,
                                 'ln_r': j+1, 'r': device_lines[j]})
        return {'rows': rows, 'device': remote, 'local': local_rel_path}, None


# --- Web App ---

app = Bottle()
dm = DeviceManager()


def json_response(data, status=200):
    response.content_type = "application/json"
    response.status = status
    return json.dumps(data)


# --- Static files ---

@app.route("/")
def index():
    resp = static_file("index.html", root=str(Path(__file__).parent / "static"))
    resp.set_header("Cache-Control", "no-cache, no-store, must-revalidate")
    return resp


@app.route("/static/<filepath:path>")
def serve_static(filepath):
    return static_file(filepath, root=str(Path(__file__).parent / "static"))


# --- API: Device ---

@app.route("/api/device")
def api_device():
    try:
        info = dm.device_info()
        if info:
            info["connected"] = True
            return json_response(info)
        # Try simple connectivity check
        if dm.is_connected():
            return json_response({"connected": True, "error": "Could not read device info"})
        return json_response({"connected": False})
    except Exception as e:
        return json_response({"connected": False, "error": str(e)})


# --- API: Files ---

@app.route("/api/files")
def api_files():
    path = request.params.get("path", "/")
    try:
        files = dm.list_files(path)
        return json_response({"path": path, "files": files})
    except Exception as e:
        return json_response({"error": str(e)}, 500)


@app.route("/api/file")
def api_file_read():
    path = request.params.get("path")
    if not path:
        return json_response({"error": "path required"}, 400)
    content = dm.read_file(path)
    if content is None:
        return json_response({"error": "File not found or read error"}, 404)
    return json_response({"path": path, "content": content})


@app.route("/api/file", method="PUT")
def api_file_save():
    """Save edited content to device file."""
    data = request.json
    if not data or "path" not in data or "content" not in data:
        return json_response({"error": "path and content required"}, 400)
    ok, msg = dm.write_file_content(data["path"], data["content"])
    return json_response({"ok": ok, "path": data["path"], "msg": msg})


@app.route("/api/file", method="DELETE")
def api_file_delete():
    path = request.params.get("path")
    if not path:
        return json_response({"error": "path required"}, 400)
    ok = dm.delete_file(path)
    return json_response({"ok": ok, "path": path})


@app.route("/api/dir", method="DELETE")
def api_dir_delete():
    """Recursively delete a directory on device."""
    path = request.params.get("path")
    if not path:
        return json_response({"error": "path required"}, 400)
    ok = dm.delete_dir(path)
    return json_response({"ok": ok, "path": path})


# --- API: Local file reading ---

@app.route("/api/local/file")
def api_local_file():
    """Read a local project file by relative path."""
    rel = request.params.get("path")
    if not rel:
        return json_response({"error": "path required"}, 400)
    content = dm.read_local_file(rel)
    if content is None:
        return json_response({"error": "File not found"}, 404)
    return json_response({"path": rel, "content": content})


@app.route("/api/local/file", method="PUT")
def api_local_file_save():
    """Save edited content to a local project file."""
    data = request.json
    if not data or "path" not in data or "content" not in data:
        return json_response({"error": "path and content required"}, 400)
    rel = data["path"]
    local_path = MP_DIR / rel
    if not local_path.parent.exists():
        return json_response({"error": f"Parent directory not found: {rel}"}, 404)
    try:
        local_path.write_text(data["content"])
        return json_response({"ok": True, "path": rel})
    except Exception as e:
        return json_response({"ok": False, "error": str(e)}, 500)


@app.route("/api/local/file", method="DELETE")
def api_local_file_delete():
    """Delete a local project file."""
    rel = request.params.get("path")
    if not rel:
        return json_response({"error": "path required"}, 400)
    local_path = MP_DIR / rel
    if not local_path.exists():
        return json_response({"error": f"Not found: {rel}"}, 404)
    if not local_path.is_file():
        return json_response({"error": "Not a file"}, 400)
    try:
        local_path.unlink()
        # Remove empty parent dirs up to MP_DIR
        p = local_path.parent
        while p != MP_DIR:
            try:
                p.rmdir()  # only removes if empty
                p = p.parent
            except OSError:
                break
        return json_response({"ok": True, "path": rel})
    except Exception as e:
        return json_response({"ok": False, "error": str(e)}, 500)


@app.route("/api/pull", method="POST")
def api_pull():
    """Pull a file from device to local project directory."""
    data = request.json
    if not data or "device_path" not in data:
        return json_response({"error": "device_path required"}, 400)

    device_path = data["device_path"]

    # Read file content from device
    content = dm.read_file(device_path)
    if content is None:
        return json_response({"error": f"Cannot read device:{device_path}"}, 404)

    # Determine local destination mirroring device path
    if device_path.startswith("/"):
        local_rel = device_path.lstrip("/")
    else:
        local_rel = device_path

    local_path = MP_DIR / local_rel

    # Ensure parent directory exists
    local_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        local_path.write_text(content)
        return json_response({"ok": True, "device": device_path, "local": local_rel})
    except Exception as e:
        return json_response({"ok": False, "error": str(e)}, 500)


# --- API: Lint ---

@app.route("/api/lint", method="POST")
def api_lint():
    """Lint Python code: syntax check + PicoCalc-specific warnings."""
    data = request.json
    if not data or "code" not in data:
        return json_response({"error": "code required"}, 400)

    code = data["code"]
    issues = []

    # 1. Syntax check via ast.parse
    import ast
    try:
        ast.parse(code)
    except SyntaxError as e:
        issues.append({
            "line": e.lineno or 1,
            "ch": (e.offset or 1) - 1,
            "message": f"SyntaxError: {e.msg}",
            "severity": "error",
        })
        # Return early on syntax error -- other checks won't work
        return json_response({"issues": issues})

    # 2. PicoCalc-specific checks (line by line)
    lines = code.split("\n")
    has_gc_collect = "gc.collect()" in code
    has_esc_handler = "KEY_ESC" in code or "\\x1b\\x1b" in code or "0x1b" in code
    has_main_guard = 'if __name__' in code

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Wrong imports for MicroPython
        if stripped == "import time" or stripped.startswith("from time import"):
            if "utime" not in code:
                issues.append({"line": i, "ch": 0, "severity": "warning",
                    "message": "Use 'import utime' instead of 'import time' on MicroPython"})

        if stripped == "import random" or stripped.startswith("from random import"):
            if "urandom" not in code:
                issues.append({"line": i, "ch": 0, "severity": "warning",
                    "message": "Use 'import urandom' instead of 'import random' on MicroPython"})

        # RGB color values (common mistake on 4-bit grayscale display)
        import re
        rgb_match = re.search(r'0x[0-9a-fA-F]{4,6}', stripped)
        if rgb_match and 'color' in stripped.lower():
            issues.append({"line": i, "ch": 0, "severity": "warning",
                "message": "Possible RGB color value -- PicoCalc uses 4-bit grayscale (0-15)"})

        # fill(0); show() on exit (causes black screen flash)
        if 'fill(0)' in stripped and 'show()' in stripped:
            issues.append({"line": i, "ch": 0, "severity": "info",
                "message": "fill(0)+show() on exit causes black flash -- just return instead"})

        # fill(0) in a draw loop without beginDraw
        if stripped.startswith('self.d') and 'fill(0)' in stripped:
            # Check if beginDraw is nearby (within 3 lines above)
            nearby = "\n".join(lines[max(0,i-4):i-1])
            if 'beginDraw' not in nearby and 'static' not in nearby.lower():
                issues.append({"line": i, "ch": 0, "severity": "warning",
                    "message": "fill(0) without beginDraw() may cause flicker -- use erase-move-draw pattern instead"})

    # 3. File-level checks
    if not has_gc_collect and len(lines) > 20:
        issues.append({"line": 1, "ch": 0, "severity": "info",
            "message": "Consider adding gc.collect() at app start -- memory is limited (~190KB)"})

    if not has_esc_handler and len(lines) > 30 and 'picocalc' in code:
        issues.append({"line": 1, "ch": 0, "severity": "warning",
            "message": "No ESC key handler found -- apps should provide an exit path back to menu"})

    if not has_main_guard and 'def main' in code:
        issues.append({"line": 1, "ch": 0, "severity": "info",
            "message": "Missing 'if __name__ == \"__main__\"' guard"})

    return json_response({"issues": issues})


# --- API: Deploy ---

@app.route("/api/deploy/<target>", method="POST")
def api_deploy(target):
    try:
        if target == "all":
            results = dm.deploy_boot() + dm.deploy_modules() + dm.deploy_scripts()
        elif target == "boot":
            results = dm.deploy_boot()
        elif target == "modules":
            results = dm.deploy_modules()
        elif target == "scripts":
            results = dm.deploy_scripts()
        else:
            return json_response({"error": f"Unknown target: {target}"}, 400)
        ok_count = sum(1 for r in results if r["ok"])
        return json_response({
            "target": target,
            "results": results,
            "summary": f"{ok_count}/{len(results)} files deployed",
        })
    except Exception as e:
        return json_response({"error": str(e)}, 500)


# --- API: Push single file ---

@app.route("/api/push", method="POST")
def api_push():
    data = request.json
    if not data or "file" not in data:
        return json_response({"error": "file field required"}, 400)

    local_rel = data["file"]
    local_path = MP_DIR / local_rel

    if not local_path.exists():
        return json_response({"error": f"Local file not found: {local_rel}"}, 404)

    # Auto-detect device path mirroring local structure
    if local_rel in FILE_MAP:
        remote = FILE_MAP[local_rel]
    else:
        remote = "/" + local_rel.replace("\\", "/")

    ok, msg = dm.push_file(local_path, remote)
    return json_response({"ok": ok, "file": local_rel, "remote": remote, "msg": msg})


# --- API: Upload (drag-and-drop) ---

@app.route("/api/upload", method="POST")
def api_upload():
    upload = request.files.get("file")
    dest = request.forms.get("dest", "/sd/py_scripts/")
    if not upload:
        return json_response({"error": "No file uploaded"}, 400)

    # Save to temp, push, cleanup
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".py")
    try:
        upload.save(tmp.name, overwrite=True)
        remote = dest.rstrip("/") + "/" + upload.filename
        ok, msg = dm.push_file(tmp.name, remote)
        return json_response({"ok": ok, "file": upload.filename, "remote": remote, "msg": msg})
    finally:
        os.unlink(tmp.name)


# --- API: Cleanup ---

@app.route("/api/cleanup", method="POST")
def api_cleanup():
    """Remove macOS junk files from device (.Spotlight, .DS_Store, ._ files, etc.)."""
    try:
        removed = dm.cleanup_macos_junk()
        return json_response({
            "removed": removed,
            "count": len(removed),
            "summary": f"Removed {len(removed)} items" if removed else "Device is clean",
        })
    except Exception as e:
        return json_response({"error": str(e)}, 500)


# --- API: Exec ---

@app.route("/api/exec", method="POST")
def api_exec():
    data = request.json
    if not data or "code" not in data:
        return json_response({"error": "code field required"}, 400)
    result = dm.exec_code(data["code"])
    return json_response(result)


# --- API: Reset ---

@app.route("/api/reset", method="POST")
def api_reset():
    ok = dm.soft_reset()
    return json_response({"ok": ok})


@app.route("/api/eject", method="POST")
def api_eject():
    """Restart menu on device and signal dashboard to stop polling."""
    ok = dm.eject()
    return json_response({"ok": ok})


# --- API: Diff ---

@app.route("/api/diff")
def api_diff():
    file_path = request.params.get("file")
    if not file_path:
        return json_response({"error": "file param required"}, 400)
    diff_data, err = dm.diff_file(file_path)
    if err:
        return json_response({"error": err}, 404)
    identical = len(diff_data['rows']) > 0 and all(r['t'] == 'eq' for r in diff_data['rows'])
    return json_response({"file": file_path, "diff": diff_data, "identical": identical})


# --- API: Local file tree (for push UI) ---

@app.route("/api/local/tree")
def api_local_tree():
    """Return local repo files grouped by deploy target, with device size comparison."""
    tree = {"boot": [], "modules": [], "scripts": [], "sd_other": []}

    # Query device file sizes in one shot for comparison
    device_sizes = {}
    try:
        code = """
import os
def walk(d):
    try:
        for f in os.listdir(d):
            full = d.rstrip('/') + '/' + f
            try:
                st = os.stat(full)
                if st[0] & 0x4000:
                    walk(full)
                else:
                    print(full + '|' + str(st[6]))
            except:
                pass
    except:
        pass
walk('/')
walk('/modules')
walk('/sd')
"""
        result = dm.exec_code(code)
        for line in result.get("out", "").strip().split("\n"):
            line = line.strip()
            if "|" in line:
                parts = line.split("|", 1)
                if len(parts) == 2 and parts[1].lstrip('-').isdigit():
                    device_sizes[parts[0]] = int(parts[1])
    except Exception:
        pass

    def file_entry(name, local_path, device_path):
        st = local_path.stat()
        dev_size = device_sizes.get(device_path)
        status = "match"
        if dev_size is None:
            status = "missing"  # not on device
        elif dev_size != st.st_size:
            status = "modified"  # size differs
        return {"name": name, "size": st.st_size, "dev_size": dev_size, "status": status}

    # Root boot files
    for name in ["boot.py", "main.py", "boot_thonny.py", "boot_dev.py"]:
        p = MP_DIR / name
        if p.exists():
            tree["boot"].append(file_entry(name, p, f"/{name}"))

    # Modules
    modules_dir = MP_DIR / "modules"
    if modules_dir.is_dir():
        for f in sorted(modules_dir.glob("*.py")):
            tree["modules"].append(file_entry(f"modules/{f.name}", f, f"/modules/{f.name}"))

    _HIDDEN = {'.DS_Store', '.gitkeep', '.gitignore', 'Thumbs.db', '__pycache__'}

    # Scripts (sd/py_scripts)
    scripts_dir = MP_DIR / "sd" / "py_scripts"
    if scripts_dir.is_dir():
        for f in sorted(scripts_dir.glob("*")):
            if f.is_file() and f.name not in _HIDDEN:
                rel = f"sd/py_scripts/{f.name}"
                tree["scripts"].append(file_entry(rel, f, f"/{rel}"))

    # All other sd/ files (recursive, excluding py_scripts)
    sd_dir = MP_DIR / "sd"
    if sd_dir.is_dir():
        for f in sorted(sd_dir.rglob("*")):
            if f.is_file() and f.name not in _HIDDEN and "py_scripts" not in f.relative_to(sd_dir).parts[:1]:
                rel = str(f.relative_to(MP_DIR)).replace("\\", "/")
                tree["sd_other"].append(file_entry(rel, f, f"/{rel}"))

    return json_response(tree)


# --- Main ---

def main():
    global PORT, HOST

    # Parse args
    auto_open = True
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            PORT = int(args[i + 1])
            i += 2
        elif args[i] == "--host" and i + 1 < len(args):
            HOST = args[i + 1]
            i += 2
        elif args[i] == "--no-open":
            auto_open = False
            i += 1
        elif args[i] in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"Unknown option: {args[i]}")
            print(__doc__)
            sys.exit(1)

    url = f"http://localhost:{PORT}"
    print(f"\n  PicoCalc Dashboard")
    print(f"  --------------------")
    print(f"  Project:   {MP_DIR}")
    print(f"  Dashboard: {url}")
    print(f"  Press Ctrl+C to stop\n")

    # Open browser after a short delay
    if auto_open:
        def open_browser():
            import time
            time.sleep(1)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    # Run server
    app.run(host=HOST, port=PORT, quiet=True)


if __name__ == "__main__":
    main()
