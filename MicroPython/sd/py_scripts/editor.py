"""
Code Editor - On-device file editor for PicoCalc
Features:
- Browse files on flash and SD card
- Edit any .py file with syntax-aware pye editor
- Create new files
- No computer needed
"""
import picocalc
import utime
import os
import gc

# -- VT100 helpers -------------------------------------------------
_E = '\033'
_BLK, _RED, _GRN, _YEL, _BLU, _MAG, _CYN, _WHT = range(8)
_W = 53

def _w(s):
    picocalc.terminal.wr(s)

def _clr():
    _w(f'{_E}[2J{_E}[H')

def _at(r, c):
    _w(f'{_E}[{r};{c}H')

def _style(fg=None, bg=None, bold=False, dim=False):
    codes = []
    if bold: codes.append('1')
    if dim: codes.append('2')
    if fg is not None: codes.append(str(30 + fg))
    if bg is not None: codes.append(str(40 + bg))
    if codes:
        _w(f'{_E}[{";".join(codes)}m')

def _rst():
    _w(f'{_E}[0m')

def _cll():
    _w(f'{_E}[K')

def _cursor(show=True):
    _w(f'{_E}[?25{"h" if show else "l"}')

def _box_h(n):
    _w('\x0e' + 'q' * n + '\x0f')


# -- File utilities ------------------------------------------------

def _list_dir(path):
    """List directory contents, return sorted (dirs first, then files)."""
    dirs = []
    files = []
    try:
        for name in os.listdir(path):
            full = path.rstrip('/') + '/' + name
            try:
                st = os.stat(full)
                if st[0] & 0x4000:
                    dirs.append(name)
                else:
                    files.append((name, st[6]))
            except:
                files.append((name, 0))
    except:
        pass
    return sorted(dirs), sorted(files, key=lambda x: x[0])


def _fmt_size(b):
    if b >= 1024 * 1024:
        return f'{b // (1024*1024)}.{(b % (1024*1024)) * 10 // (1024*1024)}MB'
    elif b >= 1024:
        return f'{b // 1024}.{(b % 1024) * 10 // 1024}KB'
    return f'{b}B'


# -- File Browser --------------------------------------------------

class FileBrowser:
    MAX_VIS = 30

    def __init__(self):
        self.key_buf = bytearray(10)
        self.path = '/'
        self.entries = []  # list of (display_name, full_path, is_dir, size)
        self.sel = 0
        self.scroll = 0

    def load(self):
        """Load current directory."""
        dirs, files = _list_dir(self.path)
        self.entries = []

        # Parent directory (if not root)
        if self.path != '/':
            parent = self.path.rstrip('/')
            parent = parent[:parent.rfind('/')] or '/'
            self.entries.append(('..', parent, True, 0))

        for d in dirs:
            full = self.path.rstrip('/') + '/' + d
            self.entries.append((d + '/', full, True, 0))

        for name, size in files:
            full = self.path.rstrip('/') + '/' + name
            self.entries.append((name, full, False, size))

        if self.sel >= len(self.entries):
            self.sel = max(0, len(self.entries) - 1)
        self.scroll = 0

    def draw(self):
        _clr()
        _cursor(False)
        n = len(self.entries)

        # Header
        _at(1, 1)
        _style(fg=_WHT, bg=_BLU, bold=True)
        _w(' ' * _W)
        _at(1, 2)
        _w('Code Editor')

        # Show free RAM right-aligned
        gc.collect()
        ram = f'{gc.mem_free() // 1024}K'
        _at(1, _W - len(ram))
        _style(fg=_CYN, bg=_BLU)
        _w(ram)
        _rst()

        # Path bar
        _at(2, 1)
        _style(fg=_CYN)
        _box_h(_W)
        _rst()
        _at(3, 2)
        _style(fg=_CYN, bold=True)
        _w(self.path)
        _rst()
        _style(dim=True)
        _w(f'  ({n} items)')
        _rst()

        # File list
        if n == 0:
            _at(5, 4)
            _style(dim=True)
            _w('Empty directory')
            _rst()
        else:
            if self.sel < self.scroll:
                self.scroll = self.sel
            elif self.sel >= self.scroll + self.MAX_VIS:
                self.scroll = self.sel - self.MAX_VIS + 1

            vis = min(self.MAX_VIS, n - self.scroll)

            # Scroll up indicator
            if self.scroll > 0:
                _at(4, _W - 1)
                _style(fg=_YEL, bold=True)
                _w('^')
                _rst()

            for i in range(vis):
                idx = self.scroll + i
                name, full, is_dir, size = self.entries[idx]
                row = 5 + i
                _at(row, 1)

                if idx == self.sel:
                    _style(fg=_BLK, bg=_GRN, bold=True)
                    if is_dir:
                        _w(f' \x10 {name:<{_W - 4}}')
                    else:
                        size_str = _fmt_size(size)
                        name_w = _W - 4 - len(size_str) - 1
                        _w(f' \x10 {name:<{name_w}} {size_str}')
                else:
                    _w('   ')
                    if is_dir:
                        _style(fg=_CYN, bold=True)
                        _w(name)
                    elif name.endswith('.py'):
                        _style(fg=_GRN)
                        _w(name)
                        _rst()
                        _style(dim=True)
                        _w(f'  {_fmt_size(size)}')
                    else:
                        _style(dim=True)
                        _w(f'{name}  {_fmt_size(size)}')
                _rst()

            # Scroll down indicator
            if self.scroll + self.MAX_VIS < n:
                _at(5 + vis, _W - 1)
                _style(fg=_YEL, bold=True)
                _w('v')
                _rst()

        # Footer
        foot = 37
        _at(foot, 1)
        _style(fg=_BLU)
        _box_h(_W)
        _rst()

        _at(foot + 1, 2)
        _style(fg=_GRN, bold=True); _w('ENTER')
        _rst(); _style(dim=True); _w(' Open  ')
        _style(fg=_YEL, bold=True); _w('E')
        _rst(); _style(dim=True); _w('dit  ')
        _style(fg=_MAG, bold=True); _w('N')
        _rst(); _style(dim=True); _w('ew  ')
        _style(fg=_RED, bold=True); _w('D')
        _rst(); _style(dim=True); _w('el  ')
        _style(fg=_WHT, bold=True); _w('ESC')
        _rst(); _style(dim=True); _w(' Exit')
        _rst()

    def check_key(self):
        try:
            count = picocalc.terminal.readinto(self.key_buf)
        except OSError:
            count = None
        if not count:
            return None
        return bytes(self.key_buf[:count])

    def _prompt_text(self, row, label):
        """Simple text input on the device."""
        _at(row, 2)
        _cll()
        _style(fg=_CYN)
        _w(label)
        _rst()
        _cursor(True)
        result = []
        col = 2 + len(label)
        _at(row, col)
        while True:
            key = self.check_key()
            if not key:
                utime.sleep_ms(30)
                continue
            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                _cursor(False)
                return None
            if key in (b'\r\n', b'\r', b'\n'):
                _cursor(False)
                return ''.join(result)
            if key[0] == 0x7F or key[0] == 0x08:
                if result:
                    result.pop()
                    col -= 1
                    _at(row, col)
                    _w(' ')
                    _at(row, col)
            elif len(key) == 1 and 32 <= key[0] < 127:
                result.append(chr(key[0]))
                _w(chr(key[0]))
                col += 1

    def _confirm(self, row, msg):
        """Yes/no confirm. Returns True for yes."""
        _at(row, 2)
        _cll()
        _style(fg=_YEL)
        _w(f'{msg} (y/N)')
        _rst()
        while True:
            key = self.check_key()
            if not key:
                utime.sleep_ms(30)
                continue
            if len(key) == 1:
                if key[0] == ord('y') or key[0] == ord('Y'):
                    return True
                return False

    def edit_file(self, filepath):
        """Open file in pye editor."""
        if not picocalc.edit:
            _at(36, 2)
            _style(fg=_RED)
            _w('Editor not available')
            _rst()
            utime.sleep_ms(1500)
            return

        _cursor(True)
        _clr()
        _rst()
        try:
            picocalc.edit(filepath)
        except Exception as e:
            _at(36, 2)
            _style(fg=_RED)
            _w(f'Edit error: {e}')
            _rst()
            utime.sleep_ms(2000)

    def create_file(self):
        """Create a new .py file."""
        name = self._prompt_text(36, 'New filename: ')
        if not name:
            return
        if not name.endswith('.py'):
            name += '.py'
        filepath = self.path.rstrip('/') + '/' + name

        try:
            f = open(filepath, 'w')
            f.write('# ' + name + '\n')
            f.write('import picocalc\n')
            f.write('import utime\n')
            f.write('import gc\n\n\n')
            f.write('def main():\n')
            f.write('    gc.collect()\n')
            f.write('    pass\n\n\n')
            f.write('if __name__ == "__main__":\n')
            f.write('    main()\n')
            f.close()
            _at(36, 2); _cll()
            _style(fg=_GRN)
            _w(f'Created: {name} - press E to edit')
            _rst()
            utime.sleep_ms(1500)
            self.load()
        except Exception as e:
            _at(36, 2); _cll()
            _style(fg=_RED)
            _w(f'Error: {e}')
            _rst()
            utime.sleep_ms(2000)

    def delete_entry(self):
        """Delete selected file."""
        if not self.entries:
            return
        name, full, is_dir, size = self.entries[self.sel]
        if name == '..':
            return
        if is_dir:
            return  # Don't delete directories from this UI

        if self._confirm(36, f'Delete {name}?'):
            try:
                os.remove(full)
                _at(36, 2)
                _style(fg=_GRN)
                _w(f'Deleted: {name}')
                _rst()
                utime.sleep_ms(800)
                self.load()
            except Exception as e:
                _at(36, 2)
                _style(fg=_RED)
                _w(f'Error: {e}')
                _rst()
                utime.sleep_ms(2000)

    def run(self):
        self.load()
        self.draw()

        while True:
            key = self.check_key()
            if not key:
                utime.sleep_ms(50)
                continue

            redraw = False
            n = len(self.entries)

            # ESC: exit
            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                return

            # Arrow Up
            elif key == b'\x1b[A' and self.sel > 0:
                self.sel -= 1
                redraw = True

            # Arrow Down
            elif key == b'\x1b[B' and self.sel < n - 1:
                self.sel += 1
                redraw = True

            # Home
            elif key == b'\x1b[H':
                self.sel = 0
                self.scroll = 0
                redraw = True

            # End
            elif key == b'\x1b[F':
                self.sel = max(0, n - 1)
                redraw = True

            # Enter: open dir or edit file
            elif key in (b'\r\n', b'\r', b'\n') and n > 0:
                name, full, is_dir, size = self.entries[self.sel]
                if is_dir:
                    if name == '..':
                        self.path = full if full else '/'
                    else:
                        self.path = full
                    self.sel = 0
                    self.load()
                elif name.endswith('.py'):
                    self.edit_file(full)
                    self.load()
                redraw = True

            # E: edit selected file
            elif len(key) == 1 and key[0] in (ord('e'), ord('E')):
                if n > 0:
                    name, full, is_dir, size = self.entries[self.sel]
                    if not is_dir:
                        self.edit_file(full)
                        self.load()
                        redraw = True

            # N: new file
            elif len(key) == 1 and key[0] in (ord('n'), ord('N')):
                self.create_file()
                self.load()
                redraw = True

            # D: delete
            elif len(key) == 1 and key[0] in (ord('d'), ord('D')):
                self.delete_entry()
                redraw = True

            if redraw:
                self.draw()


def main():
    gc.collect()
    try:
        browser = FileBrowser()
        browser.path = '/sd/py_scripts'
        # Fall back to root if SD not available
        try:
            os.listdir('/sd/py_scripts')
        except:
            browser.path = '/'
        browser.run()
    except Exception as e:
        _cursor(True)
        _rst()
        print(f'Editor error: {e}')
        import sys
        sys.print_exception(e)

if __name__ == '__main__':
    main()
