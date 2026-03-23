import os
import sys
import gc
import picocalc
import utime

# ── VT100 helpers ──────────────────────────────────────────────
_E = '\033'
# Colors
_BLK, _RED, _GRN, _YEL, _BLU, _MAG, _CYN, _WHT = range(8)
# Screen dimensions
_W = 53
_H = 40
# Max visible script rows (leave room for header + footer)
_MAX_VIS = 28

def _w(s):
    """Write string to VT100 terminal."""
    picocalc.terminal.wr(s)

def _clr():
    _w(f'{_E}[2J{_E}[H')

def _at(r, c):
    _w(f'{_E}[{r};{c}H')

def _fg(c):
    _w(f'{_E}[{30+c}m')

def _bg(c):
    _w(f'{_E}[{40+c}m')

def _style(fg=None, bg=None, bold=False, dim=False, rev=False):
    codes = []
    if bold: codes.append('1')
    if dim: codes.append('2')
    if rev: codes.append('7')
    if fg is not None: codes.append(str(30 + fg))
    if bg is not None: codes.append(str(40 + bg))
    if codes:
        _w(f'{_E}[{";".join(codes)}m')

def _rst():
    _w(f'{_E}[0m')

def _cll():
    """Clear to end of line."""
    _w(f'{_E}[K')

def _cursor(show=True):
    _w(f'{_E}[?25{"h" if show else "l"}')

def _box_line(ch, n):
    """Draw n copies of a G1 line-drawing char. Switch G1 on/off."""
    _w('\x0e' + ch * n + '\x0f')

def _box_h(n):
    """Horizontal line using G1 line-drawing."""
    _box_line('q', n)

def _box_v():
    """Single vertical line char using G1."""
    _w('\x0ex\x0f')


# ── File utilities ─────────────────────────────────────────────

def find_py_files(base_path="/sd"):
    py_files = []
    try:
        for entry in os.listdir(base_path):
            full_path = f"{base_path}/{entry}"
            try:
                mode = os.stat(full_path)[0]
                if mode & 0x4000:  # Directory
                    sub_files = find_py_files(full_path)
                    py_files.extend(sub_files)
                elif entry.endswith(".py"):
                    relative_path = full_path[len("/sd/"):-3]
                    py_files.append(relative_path)
            except Exception as e:
                print(f"Error reading {full_path}: {e}")
    except Exception as e:
        print(f"Error listing {base_path}: {e}")
    return py_files

def delete_file(script_path, base_path="/sd"):
    try:
        full_path = f"{base_path}/{script_path}.py"
        try:
            os.stat(full_path)
        except OSError:
            print(f"File not found: {script_path}.py")
            return False

        try:
            stat = os.stat(full_path)
            size = stat[6]
            print(f"\nFile: {script_path}.py")
            print(f"Size: {size} bytes")
            print(f"Path: {full_path}")
        except:
            pass

        print(f"\nAre you sure you want to delete '{script_path}.py'?")
        print("This action cannot be undone!")
        confirm = input("Delete file? (y/N): ").strip().lower()

        if confirm == "y":
            os.remove(full_path)
            print(f"File '{script_path}.py' has been deleted.")
            return True
        else:
            print("Deletion cancelled.")
            return False

    except Exception as e:
        print(f"Error deleting {script_path}: {e}")
        return False

def run_script(script_path, base_path="/sd"):
    try:
        full_path = f"{base_path}/{script_path}.py"
        with open(full_path) as f:
            script_content = f.read()

        script_globals = {
            '__name__': '__main__',
            '__file__': full_path,
        }
        for module_name in ['os', 'sys', 'gc']:
            if module_name in globals():
                script_globals[module_name] = globals()[module_name]

        exec(script_content, script_globals)

        if 'main_menu' in script_globals and callable(script_globals['main_menu']):
            if 'main_executed' not in script_globals or not script_globals['main_executed']:
                script_globals['main_menu']()
                script_globals['main_executed'] = True

    except Exception as e:
        print(f"Failed running {script_path}: {e}")

def flush_modules(exclude=("os", "sys", "gc")):
    flushed = []
    for name in list(sys.modules):
        if name not in exclude and not name.startswith("micropython"):
            sys.modules.pop(name, None)
            flushed.append(name)
    print(f"Flushed: {', '.join(flushed)}")

def show_memory():
    gc.collect()
    print(f"RAM Free: {gc.mem_free()} bytes")
    print(f"RAM Used: {gc.mem_alloc()} bytes")
    try:
        stat = os.statvfs('/sd')
        block_size = stat[0]
        total_blocks = stat[2]
        free_blocks = stat[3]
        total_space = block_size * total_blocks
        free_space = block_size * free_blocks
        used_space = total_space - free_space

        def fmt(b):
            if b >= 1024 * 1024:
                return f"{b / (1024 * 1024):.2f} MB"
            elif b >= 1024:
                return f"{b / 1024:.2f} KB"
            return f"{b} bytes"

        print(f"\nStorage on /sd:")
        print(f"Total: {fmt(total_space)}")
        print(f"Used:  {fmt(used_space)}")
        print(f"Free:  {fmt(free_space)}")
        print(f"Usage: {int(used_space * 100 // total_space)}%")
    except Exception as e:
        print(f"Error getting storage info: {e}")


# ── File management sub-menu (text mode) ──────────────────────

def file_management_menu():
    while True:
        scripts = find_py_files()
        if not scripts:
            print("No Python files found.")
            input("Press Enter to return to main menu...")
            return

        print("\n=== File Management ===")
        for i, name in enumerate(scripts):
            print(f"{i + 1}: {name}.py")

        print("\nD: Delete  E: Edit  B: Back")
        choice = input("\nEnter choice: ").strip().lower()

        if choice == "b":
            return
        elif choice == "d":
            print("\nSelect file to delete:")
            for i, name in enumerate(scripts):
                print(f"{i + 1}: {name}.py")
            delete_choice = input("\nFile number: ").strip()
            try:
                index = int(delete_choice) - 1
                if 0 <= index < len(scripts):
                    delete_file(scripts[index])
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Invalid input.")
            input("Press Enter to continue...")
        elif choice == "e":
            print("\nSelect file to edit:")
            for i, name in enumerate(scripts):
                print(f"{i + 1}: {name}.py")
            edit_choice = input("\nFile number: ").strip()
            try:
                index = int(edit_choice) - 1
                if 0 <= index < len(scripts):
                    picocalc.edit(f"/sd/{scripts[index]}.py")
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Invalid input.")
            input("Press Enter to continue...")
        else:
            print("Invalid choice.")
            input("Press Enter to continue...")


# ── Main menu with arrow-key navigation ───────────────────────

class _Menu:
    def __init__(self):
        self.key_buf = bytearray(10)
        self.scripts = []
        self.sel = 0
        self.scroll = 0

    def refresh_scripts(self):
        raw = find_py_files()
        # Filter out archive dirs, sort
        self.scripts = sorted([s for s in raw
                               if '/archive/' not in s
                               and '/temp_archive/' not in s])
        if self.sel >= len(self.scripts):
            self.sel = max(0, len(self.scripts) - 1)

    def _status(self):
        gc.collect()
        ram_kb = gc.mem_free() // 1024
        try:
            st = os.statvfs('/sd')
            sd_mb = (st[0] * st[3]) // (1024 * 1024)
            if sd_mb >= 1024:
                sd = f"{sd_mb // 1024}.{(sd_mb % 1024) * 10 // 1024}GB"
            else:
                sd = f"{sd_mb}MB"
        except:
            sd = "--"
        return ram_kb, sd

    def _display_name(self, path):
        """Clean display name from script path."""
        return path.replace('py_scripts/', '')

    def draw(self):
        ram, sd = self._status()
        n = len(self.scripts)

        _clr()
        _cursor(False)

        # ── Header ─────────────────────────────────────────
        _at(1, 1)
        _style(fg=_WHT, bg=_BLU, bold=True)
        _w(' ' * _W)
        _at(1, 3)
        _w('PicoCalc')
        _rst()

        # Status in header right-aligned
        status_str = f'RAM:{ram}K  SD:{sd}'
        _at(1, _W - len(status_str))
        _style(fg=_CYN, bg=_BLU)
        _w(status_str)
        _rst()

        # Decorative line with box-drawing
        _at(2, 1)
        _fg(_CYN)
        _box_h(_W)
        _rst()

        # ── Section header ─────────────────────────────────
        _at(3, 2)
        _style(fg=_CYN, bold=True)
        _w('SCRIPTS')
        _rst()
        if n > 0:
            _style(dim=True)
            _w(f'  ({n})')
            _rst()

        # ── Script list ────────────────────────────────────
        if n == 0:
            _at(5, 4)
            _style(dim=True)
            _w('No scripts found on SD card')
            _rst()
            list_end = 6
        else:
            # Keep selection in view
            if self.sel < self.scroll:
                self.scroll = self.sel
            elif self.sel >= self.scroll + _MAX_VIS:
                self.scroll = self.sel - _MAX_VIS + 1

            # Scroll-up indicator
            if self.scroll > 0:
                _at(4, _W - 1)
                _style(fg=_YEL, bold=True)
                _w('^')
                _rst()

            vis = min(_MAX_VIS, n - self.scroll)
            for i in range(vis):
                idx = self.scroll + i
                row = 5 + i
                name = self._display_name(self.scripts[idx])

                _at(row, 1)
                if idx == self.sel:
                    # ── Selected item ──
                    _style(fg=_BLK, bg=_GRN, bold=True)
                    _w(f' \x10 {name:<{_W - 4}}')
                    _rst()
                else:
                    _w('   ')
                    _style(fg=_WHT)
                    _w(name)
                    _rst()
                _cll()

            list_end = 5 + vis

            # Scroll-down indicator
            if self.scroll + _MAX_VIS < n:
                _at(list_end, _W - 1)
                _style(fg=_YEL, bold=True)
                _w('v')
                _rst()
                list_end += 1

        # ── Footer ─────────────────────────────────────────
        foot = list_end + 1
        _at(foot, 1)
        _fg(_BLU)
        _box_h(_W)
        _rst()

        # Controls line 1
        _at(foot + 1, 2)
        _style(fg=_GRN, bold=True); _w('ENTER')
        _rst(); _style(dim=True); _w(' Run  ')
        _style(fg=_YEL, bold=True); _w('ESC')
        _rst(); _style(dim=True); _w(' Exit  ')
        _style(fg=_WHT, bold=True); _w('\x18\x19')
        _rst(); _style(dim=True); _w(' Navigate')
        _rst()

        # Controls line 2
        _at(foot + 2, 2)
        _style(fg=_MAG, bold=True); _w('R')
        _rst(); _style(dim=True); _w('eload ')
        _style(fg=_MAG, bold=True); _w('F')
        _rst(); _style(dim=True); _w('lush ')
        _style(fg=_MAG, bold=True); _w('M')
        _rst(); _style(dim=True); _w('emory ')
        _style(fg=_MAG, bold=True); _w('T')
        _rst(); _style(dim=True); _w('ools')
        _rst()

    def check_key(self):
        if not picocalc.terminal:
            return None
        try:
            count = picocalc.terminal.readinto(self.key_buf)
        except OSError:
            count = None
        if not count:
            return None
        return bytes(self.key_buf[:count])

    def _enter_text_mode(self):
        """Prepare terminal for text-mode sub-menus."""
        _cursor(True)
        _clr()

    def _drain_keys(self):
        """Drain any stale key data from terminal buffer."""
        picocalc.terminal.dryBuffer()
        # Also drain any hardware keyboard events
        for _ in range(10):
            try:
                if not picocalc.terminal.readinto(self.key_buf):
                    break
            except:
                break

    def run(self):
        self.refresh_scripts()
        self.draw()

        while True:
            key = self.check_key()
            if not key:
                utime.sleep_ms(50)
                continue

            redraw = False

            # ── ESC: Exit (robust: double or single ESC) ──
            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                _cursor(True)
                _clr()
                _style(fg=_CYN)
                _w('Exiting to REPL...\n')
                _rst()
                return

            # ── Arrow Up ──
            elif key == b'\x1b[A':
                if self.sel > 0:
                    self.sel -= 1
                    redraw = True

            # ── Arrow Down ──
            elif key == b'\x1b[B':
                if self.sel < len(self.scripts) - 1:
                    self.sel += 1
                    redraw = True

            # ── Home ──
            elif key == b'\x1b[H':
                if self.sel != 0:
                    self.sel = 0
                    self.scroll = 0
                    redraw = True

            # ── End ──
            elif key == b'\x1b[F':
                last = len(self.scripts) - 1
                if self.sel != last and last >= 0:
                    self.sel = last
                    redraw = True

            # ── Enter: Run script ──
            elif key in (b'\r\n', b'\r', b'\n'):
                if self.scripts:
                    self._enter_text_mode()
                    name = self._display_name(self.scripts[self.sel])
                    _style(fg=_GRN, bold=True)
                    _w(f'Running {name}...\n')
                    _rst()
                    run_script(self.scripts[self.sel])
                    self._drain_keys()
                    _cursor(True)
                    _rst()
                    _clr()
                    _style(fg=_CYN)
                    _w(f'{name} exited.\n\n')
                    _rst()
                    input("Press Enter for menu...")
                    self._drain_keys()
                    self.refresh_scripts()
                    redraw = True

            # ── Single-key commands ──
            elif len(key) == 1:
                ch = key[0]

                if ch == ord('r') or ch == ord('R'):
                    self.refresh_scripts()
                    redraw = True

                elif ch == ord('f') or ch == ord('F'):
                    self._enter_text_mode()
                    flush_modules()
                    input("\nPress Enter...")
                    self._drain_keys()
                    redraw = True

                elif ch == ord('m') or ch == ord('M'):
                    self._enter_text_mode()
                    show_memory()
                    input("\nPress Enter...")
                    self._drain_keys()
                    redraw = True

                elif ch == ord('t') or ch == ord('T'):
                    self._enter_text_mode()
                    file_management_menu()
                    self._drain_keys()
                    self.refresh_scripts()
                    redraw = True

            if redraw:
                self.draw()


def main_menu():
    menu = _Menu()
    menu.run()


# Keep backward compatibility
main_executed = False

def check_run_main():
    global main_executed
    if __name__ == "__main__" and not main_executed:
        main_menu()
        main_executed = True

if __name__ == "__main__":
    main_menu()
    main_executed = True

check_run_main()
