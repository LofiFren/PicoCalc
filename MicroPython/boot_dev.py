import sys
# Ensure /modules is in path before any picocalc imports
for _p in ["/modules", "/sd/py_scripts"]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import picocalc
from picocalc import PicoDisplay, PicoKeyboard
import os
import gc

# -- Splash screen helpers (direct framebuffer, before terminal) --

_C_BLK = 0
_C_DK = 3
_C_GR = 8
_C_LT = 12
_C_WHT = 15
_C_WARN = 10

def _splash_init(d):
    """Draw initial splash screen -- DEV variant."""
    d.fill(_C_BLK)
    # Header bar
    d.fill_rect(0, 0, 320, 22, _C_DK)
    d.text("PICOCALC", 100, 7, _C_WHT)
    d.text("DEV", 168, 7, _C_WARN)
    d.hline(0, 22, 320, _C_WARN)
    d.text("Developer Boot", 110, 34, _C_WARN)
    d.show()

def _splash_step(d, row, label, status, color=_C_LT):
    """Draw one boot progress line."""
    y = 60 + row * 18
    d.text(label, 40, y, _C_GR)
    lx = 40 + len(label) * 6 + 4
    while lx < 210:
        d.fill_rect(lx, y + 4, 2, 2, _C_DK)
        lx += 6
    d.text(status, 214, y, color)
    d.show()

# -- Boot sequence (DEV -- verbose SD, drops to REPL) -------------

try:
    # 1. Display
    pc_display = PicoDisplay(320, 320)
    _splash_init(pc_display)
    _splash_step(pc_display, 0, "Display", "OK", _C_WHT)

    # 2. Keyboard
    pc_keyboard = PicoKeyboard()
    _splash_step(pc_display, 1, "Keyboard", "OK", _C_WHT)

    # 3. USB debug
    _usb = sys.stdout
    def usb_debug(msg):
        _usb.write(str(msg))
        _usb.write('\r\n')
    picocalc.usb_debug = usb_debug

    # 4. SD card (verbose debug in dev mode)
    gc.collect()
    _splash_step(pc_display, 2, "SD Card", "...", _C_GR)
    usb_debug("Starting SD card initialization (debug=True)...")

    import utime
    utime.sleep_ms(500)

    from enhanced_sd import initsd
    sd = initsd(debug=True)  # DEV: verbose SD output to USB

    if sd:
        try:
            st = os.statvfs('/sd')
            total_mb = (st[0] * st[2]) // (1024 * 1024)
            free_mb = (st[0] * st[3]) // (1024 * 1024)
            if free_mb >= 1024:
                sd_str = f"{free_mb // 1024}.{(free_mb % 1024) * 10 // 1024}GB free"
            else:
                sd_str = f"{free_mb}MB free"
            _splash_step(pc_display, 2, "SD Card", sd_str, _C_WHT)
            usb_debug(f"SD: {total_mb}MB total, {free_mb}MB free")
        except:
            _splash_step(pc_display, 2, "SD Card", "OK", _C_WHT)
        usb_debug("SD card initialized successfully")
    else:
        _splash_step(pc_display, 2, "SD Card", "FAIL", _C_WARN)
        usb_debug("SD card initialization failed!")

    # 6. Terminal
    _splash_step(pc_display, 3, "Terminal", "...", _C_GR)
    import vt
    pc_terminal = vt.vt(pc_display, pc_keyboard, sd=sd)
    _splash_step(pc_display, 3, "Terminal", "OK", _C_WHT)

    # 7. Register globals
    picocalc.display = pc_display
    picocalc.keyboard = pc_keyboard
    picocalc.terminal = pc_terminal
    picocalc.sd = sd

    # 8. Editor
    from pye import pye_edit
    def edit(*args, tab_size=2, undo=50):
        pc_terminal.dryBuffer()
        return pye_edit(args, tab_size=tab_size, undo=undo, io_device=pc_terminal)
    picocalc.edit = edit

    # 9. Connect terminal to REPL
    os.dupterm(pc_terminal)

    # 10. Memory report
    gc.collect()
    free = gc.mem_free()
    _splash_step(pc_display, 5, "Memory", f"{free // 1024}KB free", _C_WHT)
    usb_debug(f"Boot complete. Free: {free} bytes")

    # 11. DEV: Drop to REPL (no main_menu)
    _splash_step(pc_display, 6, "Mode", "REPL", _C_WARN)
    utime.sleep_ms(600)

except Exception as e:
    sys.print_exception(e)
    try:
        os.dupterm(None).write(b"[boot_dev.py error]\n")
    except:
        pass
