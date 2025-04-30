import picocalc
from picocalc import PicoDisplay, PicoKeyboard
import os
import vt
import sys


if "/modules" not in sys.path:
    sys.path.insert(0, "/modules")
# Separated imports because Micropython is super finnicky
# Separated imports because Micropython is super finnicky
from picocalc_system import run, files
from picocalc_system import memory, disk
# from picocalc_system import clear as clear
from picocalc_system import initsd, killsd
from checksd import checksd
from mkdir import mkdir
from flush import flush

from pye import pye_edit
import builtins


try:
    pc_display = PicoDisplay(320, 320)
    pc_keyboard = PicoKeyboard()
    # Mount SD card to /sd on boot
    sd = initsd()
    pc_terminal = vt.vt(pc_display, pc_keyboard, sd=sd)
    
    _usb = sys.stdout  # 

    def usb_debug(msg):
        if isinstance(msg, str):
            _usb.write(msg)
        else:
            _usb.write(str(msg))
        _usb.write('\r\n')
    picocalc.usb_debug = usb_debug

    picocalc.display = pc_display
    picocalc.keyboard = pc_keyboard
    picocalc.terminal = pc_terminal
    picocalc.sd = sd

    def edit(*args, tab_size=2, undo=50):
        #dry the key buffer before editing
        pc_terminal.dryBuffer()
        return pye_edit(args, tab_size=tab_size, undo=undo, io_device=pc_terminal)
    picocalc.edit = edit

    os.dupterm(pc_terminal)
    checksd()
    from py_run import main_menu
    main_menu()

except Exception as e:
    import sys
    sys.print_exception(e)
    try:
        os.dupterm(None).write(b"[boot.py error]\n")
    except:
        pass