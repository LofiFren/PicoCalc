import picocalc
from picocalc import PicoDisplay, PicoKeyboard
import os
import vt
import sys
import time
import gc
import sd_chk

paths_to_add = ["/sd/py_scripts", "/modules"]
for path in paths_to_add:
    if path not in sys.path:
        sys.path.insert(0, path)

from picocalc_system import run, files
from picocalc_system import memory, disk
# from picocalc_system import clear as clear
# from picocalc_system import initsd, killsd
from enhanced_sd import initsd, killsd, check_real_sd, show_sd_info
from checksd import checksd
from mkdir import mkdir
from flush import flush
from pye import pye_edit
import builtins

try:
    # Initialize basic hardware first
    pc_display = PicoDisplay(320, 320)
    pc_keyboard = PicoKeyboard()
    
    # Setup debugging
    _usb = sys.stdout
    def usb_debug(msg):
        if isinstance(msg, str):
            _usb.write(msg)
        else:
            _usb.write(str(msg))
        _usb.write('\r\n')
    picocalc.usb_debug = usb_debug
    
    # Run garbage collection before SD card init
    gc.collect()
    usb_debug("Starting SD card initialization...")
    
    # Mount SD card to /sd with extra delay for stability
    time.sleep_ms(900)  # Add delay before SD init
    sd = initsd(debug=False)  # Enable debug output
    
    # Check if SD was initialized properly
    if sd:
        usb_debug("SD card initialized successfully")
        # Verify it's the real SD card with full capacity
        if check_real_sd():
            usb_debug("Full capacity SD card detected")
        else:
            usb_debug("WARNING: SD card capacity seems wrong")
    else:
        usb_debug("SD card initialization failed!")
    
    # Give a moment for SD card to stabilize
    time.sleep_ms(900)
    
    # Continue with terminal and rest of setup
    pc_terminal = vt.vt(pc_display, pc_keyboard, sd=sd)
    
    picocalc.display = pc_display
    picocalc.keyboard = pc_keyboard
    picocalc.terminal = pc_terminal
    picocalc.sd = sd
    
    def edit(*args, tab_size=2, undo=50):
        # Dry the key buffer before editing
        pc_terminal.dryBuffer()
        return pye_edit(args, tab_size=tab_size, undo=undo, io_device=pc_terminal)
    picocalc.edit = edit
    
    os.dupterm(pc_terminal)
    
    # Run the standard SD check function
    sd_status, sd_msg = checksd()
    usb_debug(f"SD check: {sd_msg}")
    
    # Start main menu
    from py_run import main_menu
    main_menu()

except Exception as e:
    import sys
    sys.print_exception(e)
    try:
        os.dupterm(None).write(b"[boot.py error]\n")
    except:
        pass