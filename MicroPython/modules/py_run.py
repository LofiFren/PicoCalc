import os
import sys
import gc
import picocalc
import utime

# -- VT100 helpers ----------------------------------------------
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


# -- File utilities ---------------------------------------------

_HIDDEN_LIBS = {'secure_creds.py', '__init__.py'}

# Category display order (unknown categories sort after these, before 'Other').
_CAT_ORDER = ['Music', 'Games', 'Network', 'Graphics', 'Tools', 'Apps', 'Other']


def _parse_meta(full_path, filename):
    """Inspect a .py file and decide if/how it appears in the menu.

    Opt-in metadata header (anywhere in the first lines):
        # picocalc-app: Display Name | Category | one-line description
        # picocalc-hide        (force-hide a file)

    Files without a header still appear (under 'Other') if they look runnable
    (define main()/main_menu() or an __main__ guard); pure libraries are hidden.
    Returns (name, category, desc) or None to hide.
    """
    try:
        with open(full_path) as f:
            content = f.read()
    except Exception:
        return None
    name = None
    category = None
    desc = ''
    for line in content.split('\n')[:40]:
        s = line.strip()
        if s.startswith('# picocalc-hide'):
            return None
        if s.startswith('# picocalc-app:'):
            body = s.split(':', 1)[1].strip()
            parts = [p.strip() for p in body.split('|')]
            if parts and parts[0]:
                name = parts[0]
            if len(parts) > 1 and parts[1]:
                category = parts[1]
            if len(parts) > 2:
                desc = parts[2]
            break
    runnable = ('__main__' in content or '\ndef main(' in content
                or '\ndef main_menu(' in content)
    if name is None and not runnable:
        return None  # pure library: hide
    if name is None:
        name = filename[:-3] if filename.endswith('.py') else filename
    if category is None:
        category = 'Other'
    return (name, category, desc)


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
                elif entry.endswith(".py") and entry not in _HIDDEN_LIBS:
                    relative_path = full_path[len("/sd/"):-3]
                    py_files.append(relative_path)
            except Exception as e:
                print(f"Error reading {full_path}: {e}")
    except Exception as e:
        print(f"Error listing {base_path}: {e}")
    return py_files


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


# -- Main menu with arrow-key navigation -----------------------

class _Menu:
    def __init__(self):
        self.key_buf = bytearray(10)
        self.scripts = []
        self.meta = {}
        self.sel = 0
        self.scroll = 0

    def refresh_scripts(self):
        raw = [s for s in find_py_files()
               if '/archive/' not in s and '/temp_archive/' not in s]
        self.meta = {}
        apps = []
        for path in raw:
            filename = path.split('/')[-1] + '.py'
            meta = _parse_meta('/sd/' + path + '.py', filename)
            if meta is None:
                continue        # hidden library
            self.meta[path] = meta
            apps.append(path)

        def _key(p):
            name, cat, desc = self.meta[p]
            ci = _CAT_ORDER.index(cat) if cat in _CAT_ORDER else len(_CAT_ORDER) - 1
            return (ci, cat.lower(), name.lower())

        self.scripts = sorted(apps, key=_key)
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
        """Display name from metadata, falling back to the cleaned path."""
        m = self.meta.get(path)
        return m[0] if m else path.replace('py_scripts/', '')

    def draw(self):
        ram, sd = self._status()
        n = len(self.scripts)

        _clr()
        _cursor(False)

        # -- Header -----------------------------------------
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

        # -- App list, grouped by category ------------------
        if n == 0:
            _at(4, 4)
            _style(dim=True)
            _w('No apps found on SD card')
            _rst()
            list_end = 6
        else:
            # Build render rows: (0, category) headers + (1, app_index) entries.
            rows = []
            prev_cat = None
            for i in range(n):
                cat = self.meta[self.scripts[i]][1]
                if cat != prev_cat:
                    rows.append((0, cat))
                    prev_cat = cat
                rows.append((1, i))

            # Locate the selected app's row and keep it visible.
            sel_row = 0
            for ri in range(len(rows)):
                if rows[ri][0] == 1 and rows[ri][1] == self.sel:
                    sel_row = ri
                    break
            if sel_row < self.scroll:
                self.scroll = sel_row
            elif sel_row >= self.scroll + _MAX_VIS:
                self.scroll = sel_row - _MAX_VIS + 1
            max_scroll = max(0, len(rows) - _MAX_VIS)
            if self.scroll > max_scroll:
                self.scroll = max_scroll
            if self.scroll < 0:
                self.scroll = 0

            if self.scroll > 0:
                _at(3, _W - 1)
                _style(fg=_YEL, bold=True)
                _w('^')
                _rst()

            vis = rows[self.scroll:self.scroll + _MAX_VIS]
            for i in range(len(vis)):
                kind, val = vis[i]
                row = 4 + i
                _at(row, 1)
                if kind == 0:
                    label = ' ' + val + ' '
                    _style(fg=_CYN, bold=True)
                    _w(label)
                    _rst()
                    _fg(_CYN)
                    _box_h(max(0, _W - len(label) - 1))
                    _rst()
                else:
                    name, cat, desc = self.meta[self.scripts[val]]
                    if val == self.sel:
                        line = ' \x10 ' + name
                        if desc:
                            line += '  ' + desc
                        _style(fg=_BLK, bg=_GRN, bold=True)
                        _w(line[:_W] + ' ' * max(0, _W - len(line)))
                        _rst()
                    else:
                        _w('   ')
                        _style(fg=_WHT)
                        _w(name[:_W - 4])
                        _rst()
                        rem = _W - 4 - len(name) - 2
                        if desc and rem > 3:
                            _style(dim=True)
                            _w('  ' + desc[:rem])
                            _rst()
                _cll()
            list_end = 4 + len(vis)

            if self.scroll + _MAX_VIS < len(rows):
                _at(list_end, _W - 1)
                _style(fg=_YEL, bold=True)
                _w('v')
                _rst()
                list_end += 1

        # -- Footer -----------------------------------------
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
        for _ in range(10):
            try:
                if not picocalc.terminal.readinto(self.key_buf):
                    break
            except:
                break

    def _wait_key(self):
        """Block until any key pressed. Returns key bytes."""
        while True:
            key = self.check_key()
            if key:
                return key
            utime.sleep_ms(50)

    def _confirm(self, row, msg):
        """Show Y/N prompt at row, poll for answer. No input()."""
        _at(row, 3)
        _style(fg=_YEL, bold=True)
        _w(msg + ' (Y/N) ')
        _rst()
        while True:
            key = self.check_key()
            if key and len(key) == 1:
                ch = key[0]
                if ch in (ord('y'), ord('Y')):
                    return True
                if ch in (ord('n'), ord('N'), 0x1b):
                    return False
            utime.sleep_ms(50)

    def _draw_tool_header(self, title):
        """Draw a tool sub-screen header."""
        _clr()
        _cursor(False)
        _at(1, 1)
        _style(fg=_WHT, bg=_MAG, bold=True)
        t = ' ' + title
        _w(t + ' ' * max(0, _W - len(t)))
        _rst()
        _at(2, 1)
        _fg(_MAG)
        _box_h(_W)
        _rst()

    def _draw_tool_footer(self, row, hints):
        """Draw footer line with key hints."""
        _at(row, 1)
        _fg(_MAG)
        _box_h(_W)
        _rst()
        _at(row + 1, 3)
        _style(dim=True)
        _w(hints)
        _rst()

    # -- Tool: Memory info (M key) --

    def _tool_memory(self):
        gc.collect()
        ram_free = gc.mem_free()
        ram_used = gc.mem_alloc()
        n_mods = len(sys.modules)

        self._draw_tool_header('MEMORY & STORAGE')
        r = 4
        _at(r, 3); _style(fg=_CYN, bold=True); _w('RAM'); _rst()
        r += 1
        _at(r, 5); _w(f'Free: {ram_free // 1024} KB'); r += 1
        _at(r, 5); _w(f'Used: {ram_used // 1024} KB'); r += 1

        r += 1
        try:
            st = os.statvfs('/sd')
            total = st[0] * st[2]
            free = st[0] * st[3]
            used = total - free
            pct = used * 100 // total if total > 0 else 0
            def _fmt(b):
                if b >= 1024 * 1024 * 1024:
                    return f'{b // (1024*1024*1024)}.{(b % (1024*1024*1024)) * 10 // (1024*1024*1024)} GB'
                elif b >= 1024 * 1024:
                    return f'{b // (1024*1024)}.{(b % (1024*1024)) * 100 // (1024*1024):02d} MB'
                elif b >= 1024:
                    return f'{b // 1024} KB'
                return f'{b} B'
            _at(r, 3); _style(fg=_CYN, bold=True); _w('SD CARD'); _rst(); r += 1
            _at(r, 5); _w(f'Total: {_fmt(total)}'); r += 1
            _at(r, 5); _w(f'Used:  {_fmt(used)}'); r += 1
            _at(r, 5); _w(f'Free:  {_fmt(free)}'); r += 1
            _at(r, 5); _w(f'Usage: {pct}%'); r += 1
        except:
            _at(r, 3); _style(dim=True); _w('SD card not available'); _rst(); r += 1

        r += 1
        _at(r, 3); _style(fg=_CYN, bold=True); _w('MODULES'); _rst()
        r += 1
        _at(r, 5); _w(f'Loaded: {n_mods}'); r += 1

        self._draw_tool_footer(r + 1, 'Press any key to return...')
        self._wait_key()
        self._drain_keys()

    # -- Tool: Flush modules (F key) --

    def _tool_flush(self):
        exclude = ("os", "sys", "gc")
        flushed = []
        for name in list(sys.modules):
            if name not in exclude and not name.startswith("micropython"):
                sys.modules.pop(name, None)
                flushed.append(name)
        gc.collect()
        ram_free = gc.mem_free()

        self._draw_tool_header('FLUSH MODULES')
        r = 4
        if flushed:
            _at(r, 3); _w(f'Flushed {len(flushed)} modules:'); r += 1
            # Show names in rows of ~40 chars
            line = ''
            for name in flushed:
                if len(line) + len(name) + 2 > 44:
                    r += 1
                    _at(r, 5); _style(dim=True); _w(line); _rst()
                    line = name
                else:
                    line = line + ', ' + name if line else name
            if line:
                r += 1
                _at(r, 5); _style(dim=True); _w(line); _rst()
        else:
            _at(r, 3); _w('No modules to flush')

        r += 2
        _at(r, 3); _style(fg=_GRN); _w(f'gc.collect() -> {ram_free // 1024} KB free'); _rst()

        self._draw_tool_footer(r + 2, 'Press any key to return...')
        self._wait_key()
        self._drain_keys()

    # -- Tool: File browser (T key) --

    def _tool_files(self):
        sel = 0
        scroll = 0
        max_vis = _MAX_VIS - 2

        while True:
            # Get file list with sizes
            scripts = find_py_files()
            scripts.sort()
            files = []
            for s in scripts:
                if '/archive/' in s or '/temp_archive/' in s:
                    continue
                path = f'/sd/{s}.py'
                try:
                    sz = os.stat(path)[6]
                except:
                    sz = 0
                files.append((s, sz))

            if not files:
                self._draw_tool_header('FILE TOOLS')
                _at(4, 3); _style(dim=True); _w('No scripts found'); _rst()
                self._draw_tool_footer(6, 'Press any key to return...')
                self._wait_key()
                self._drain_keys()
                return

            if sel >= len(files):
                sel = max(0, len(files) - 1)

            # Draw
            self._draw_tool_header('FILE TOOLS')
            n = len(files)
            _at(3, 3)
            _style(fg=_CYN, bold=True); _w('SCRIPTS'); _rst()
            _style(dim=True); _w(f'  ({n})'); _rst()

            # Keep selection in view
            if sel < scroll:
                scroll = sel
            elif sel >= scroll + max_vis:
                scroll = sel - max_vis + 1

            for i in range(min(max_vis, n - scroll)):
                idx = scroll + i
                row = 5 + i
                name, sz = files[idx]
                dname = name.replace('py_scripts/', '')
                # Format size
                if sz >= 1024:
                    sz_str = f'{sz // 1024}.{(sz % 1024) * 10 // 1024}K'
                else:
                    sz_str = f'{sz}B'

                _at(row, 1)
                if idx == sel:
                    _style(fg=_BLK, bg=_GRN, bold=True)
                    _w(f' > {dname}')
                    # Right-align size
                    pad = _W - 4 - len(dname) - len(sz_str)
                    if pad > 0:
                        _w(' ' * pad)
                    _w(sz_str + ' ')
                    _rst()
                else:
                    _w('   ')
                    _style(fg=_WHT); _w(dname); _rst()
                    pad = _W - 3 - len(dname) - len(sz_str)
                    if pad > 0:
                        _w(' ' * pad)
                    _style(dim=True); _w(sz_str); _rst()
                _cll()

            list_end = 5 + min(max_vis, n - scroll)
            self._draw_tool_footer(list_end + 1,
                'D:Delete  E:Edit  \x18\x19:Nav  ESC:Back')

            # Input loop
            key = self._wait_key()

            # ESC or B = back
            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                self._drain_keys()
                return
            if len(key) == 1 and key[0] in (ord('b'), ord('B')):
                self._drain_keys()
                return

            # Arrow up
            if key == b'\x1b[A':
                if sel > 0:
                    sel -= 1

            # Arrow down
            elif key == b'\x1b[B':
                if sel < len(files) - 1:
                    sel += 1

            # Delete
            elif len(key) == 1 and key[0] in (ord('d'), ord('D')):
                name, sz = files[sel]
                dname = name.replace('py_scripts/', '')
                if self._confirm(list_end + 3, f'Delete {dname}.py?'):
                    try:
                        os.remove(f'/sd/{name}.py')
                        _at(list_end + 4, 3)
                        _style(fg=_GRN); _w(f'Deleted {dname}.py'); _rst()
                        utime.sleep_ms(800)
                    except Exception as e:
                        _at(list_end + 4, 3)
                        _style(fg=_RED); _w(f'Error: {e}'); _rst()
                        utime.sleep_ms(1500)

            # Edit
            elif len(key) == 1 and key[0] in (ord('e'), ord('E')):
                name, _ = files[sel]
                _cursor(True)
                _clr()
                try:
                    picocalc.edit(f'/sd/{name}.py')
                except Exception as e:
                    _at(2, 3); _style(fg=_RED); _w(f'Edit error: {e}'); _rst()
                    utime.sleep_ms(1500)
                self._drain_keys()

    def run(self):
        self.refresh_scripts()
        self.draw()

        while True:
            key = self.check_key()
            if not key:
                utime.sleep_ms(50)
                continue

            redraw = False

            # -- ESC: Exit (robust: double or single ESC) --
            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                _cursor(True)
                _clr()
                _style(fg=_CYN)
                _w('Exiting to REPL...\n')
                _rst()
                return

            # -- Arrow Up --
            elif key == b'\x1b[A':
                if self.sel > 0:
                    self.sel -= 1
                    redraw = True

            # -- Arrow Down --
            elif key == b'\x1b[B':
                if self.sel < len(self.scripts) - 1:
                    self.sel += 1
                    redraw = True

            # -- Home --
            elif key == b'\x1b[H':
                if self.sel != 0:
                    self.sel = 0
                    self.scroll = 0
                    redraw = True

            # -- End --
            elif key == b'\x1b[F':
                last = len(self.scripts) - 1
                if self.sel != last and last >= 0:
                    self.sel = last
                    redraw = True

            # -- Enter: Run script --
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

            # -- Single-key commands --
            elif len(key) == 1:
                ch = key[0]

                if ch == ord('r') or ch == ord('R'):
                    self.refresh_scripts()
                    redraw = True

                elif ch == ord('f') or ch == ord('F'):
                    self._tool_flush()
                    redraw = True

                elif ch == ord('m') or ch == ord('M'):
                    self._tool_memory()
                    redraw = True

                elif ch == ord('t') or ch == ord('T'):
                    self._tool_files()
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
