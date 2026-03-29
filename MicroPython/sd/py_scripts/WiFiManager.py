"""
WiFi Manager - Network scanner, connector, and analyzer
Features:
- Arrow-key navigable menus
- Visual signal strength bars
- Auto-connect to saved networks
- Channel congestion analysis
- Real-time signal monitor
"""
import network
import picocalc
import utime
import gc
import json
try:
    import secure_creds as _sc
except:
    _sc = None

# -- VT100 helpers (same pattern as py_run.py) ---------------------
_E = '\033'
_BLK, _RED, _GRN, _YEL, _BLU, _MAG, _CYN, _WHT = range(8)
_W = 53
_H = 40

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

def _signal_bars(rssi):
    """Return signal bar string and color for RSSI value."""
    if rssi >= -50:
        return '\x0eaaaa\x0f', _GRN     # Excellent
    elif rssi >= -60:
        return '\x0eaaa\x0f ', _GRN     # Good
    elif rssi >= -70:
        return '\x0eaa\x0f  ', _YEL     # Fair
    elif rssi >= -80:
        return '\x0ea\x0f   ', _RED     # Weak
    else:
        return '    ', _RED              # Very weak

def _signal_label(rssi):
    if rssi >= -50: return 'Excellent'
    elif rssi >= -60: return 'Good'
    elif rssi >= -70: return 'Fair'
    else: return 'Weak'

def _sec_str(auth):
    return {0: 'Open', 1: 'WEP', 2: 'WPA', 3: 'WPA2', 4: 'WPA/2', 5: 'WPA3'}.get(auth, '?')


# -- WiFi helpers --------------------------------------------------

_wifi_pin = [None]

def _load_creds():
    try:
        with open('/sd/wifi.json', 'r') as f:
            c = json.load(f)
        ssid = c.get('ssid', '')
        pwd = c.get('password', '')
        if _sc and _sc.is_encrypted(pwd):
            if _wifi_pin[0]:
                try:
                    pwd = _sc.decrypt_password(_wifi_pin[0], pwd)
                except:
                    return ssid, ''
            else:
                return ssid, ''
        return ssid, pwd
    except:
        return '', ''

def _ensure_pin(ui):
    if not _sc:
        return False
    if _wifi_pin[0]:
        return True
    _clr()
    ui.drain_keys()
    if _sc.has_pin():
        _at(3, 2); _style(fg=_CYN, bold=True); _w('ENTER PIN'); _rst()
        for attempt in range(3):
            pin = ui.prompt_password(5 + attempt, 'PIN: ')
            if pin and _sc.verify_pin(pin):
                _wifi_pin[0] = pin
                return True
            _at(5 + attempt, 20); _style(fg=_RED); _w(' Wrong'); _rst()
        return False
    else:
        _at(3, 2); _style(fg=_CYN, bold=True); _w('SET PIN'); _rst()
        _at(4, 2); _style(dim=True); _w('Protects saved passwords (4-8 digits)'); _rst()
        pin = ui.prompt_password(6, 'New PIN: ')
        if not pin or len(pin) < 4:
            return False
        confirm = ui.prompt_password(7, 'Confirm: ')
        if pin != confirm:
            _at(9, 2); _style(fg=_RED); _w("PINs don't match"); _rst()
            return False
        _sc.set_pin(pin)
        _wifi_pin[0] = pin
        return True


def _save_creds(ssid, pwd):
    enc_pwd = pwd
    if _sc and pwd and _wifi_pin[0]:
        enc_pwd = _sc.encrypt_password(_wifi_pin[0], pwd)
    with open('/sd/wifi.json', 'w') as f:
        json.dump({'ssid': ssid, 'password': enc_pwd}, f)

def _get_wlan():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    return wlan

def _scan(wlan):
    """Scan with retry, return sorted by RSSI."""
    for attempt in range(3):
        try:
            results = wlan.scan()
            if results:
                return sorted(results, key=lambda x: x[3], reverse=True)
        except OSError:
            wlan.active(False)
            utime.sleep_ms(500)
            wlan.active(True)
            utime.sleep_ms(500)
    return []

def _connect(wlan, ssid, password):
    """Connect with timeout. Returns True on success."""
    wlan.disconnect()
    utime.sleep_ms(500)
    wlan.connect(ssid, password)
    for _ in range(20):
        if wlan.isconnected():
            return True
        utime.sleep_ms(500)
    return False


# -- Shared UI components ------------------------------------------

class _UI:
    """Shared drawing methods for all screens."""

    def __init__(self):
        self.key_buf = bytearray(32)
        self._pending = bytearray()

    def check_key(self):
        if not self._pending:
            try:
                count = picocalc.terminal.readinto(self.key_buf)
            except OSError:
                count = None
            if not count:
                return None
            self._pending = bytearray(self.key_buf[:count])
        b = self._pending
        if b[0] == 0x1b:
            if len(b) >= 2 and b[1] == 0x1b:
                self._pending = b[2:]
                return b'\x1b\x1b'
            if len(b) >= 3 and b[1] == 0x5b:
                self._pending = b[3:]
                return bytes(b[:3])
            if len(b) == 2 and b[1] == 0x5b:
                return None
            self._pending = b[1:]
            return b'\x1b'
        if b[0] == 0x0d:
            if len(b) >= 2 and b[1] == 0x0a:
                self._pending = b[2:]
            else:
                self._pending = b[1:]
            return b'\r'
        ch = bytes(b[:1])
        self._pending = b[1:]
        return ch

    def drain_keys(self):
        self._pending = bytearray()
        picocalc.terminal.dryBuffer()
        for _ in range(10):
            try:
                if not picocalc.terminal.readinto(self.key_buf):
                    break
            except:
                break

    def header(self, title, wlan):
        _at(1, 1)
        _style(fg=_WHT, bg=_BLU, bold=True)
        _w(' ' * _W)
        _at(1, 2)
        _w(title)
        # Connection status right-aligned
        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            try:
                ssid = wlan.config('essid')
            except:
                ssid = '?'
            info = f'{ssid} {ip}'
        else:
            info = 'Not connected'
        _at(1, _W - len(info))
        _style(fg=_CYN, bg=_BLU)
        _w(info)
        _rst()
        _at(2, 1); _style(fg=_CYN); _box_h(_W); _rst()

    def footer(self, *items):
        """Draw footer with key hints. items = [(key, label), ...]"""
        row = _H - 1
        _at(row, 1); _style(fg=_BLU); _box_h(_W); _rst()
        _at(row + 1, 2)
        for key, label in items:
            _style(fg=_GRN, bold=True); _w(key)
            _rst(); _style(dim=True); _w(f' {label}  ')
        _rst()



    def status_line(self, row, msg, color=_CYN):
        _at(row, 2); _cll()
        _style(fg=color); _w(msg); _rst()

    def wait_key(self, prompt='Press any key...'):
        _at(_H - 2, 2); _cll(); _style(dim=True); _w(prompt); _rst()
        self.drain_keys()
        while not self.check_key():
            utime.sleep_ms(50)
        self.drain_keys()

    def prompt_text(self, row, label):
        """Simple single-line text input. Returns string or None on ESC."""
        _at(row, 2); _cll()
        _style(fg=_CYN); _w(label); _rst()
        _cursor(True)
        result = []
        col = 2 + len(label)
        _at(row, col)
        while True:
            key = self.check_key()
            if not key:
                utime.sleep_ms(30)
                continue
            if key == b'\x1b\x1b':
                _cursor(False)
                return None
            if key in (b'\r\n', b'\r', b'\n'):
                _cursor(False)
                return ''.join(result)
            if key[0] == 0x7F or key[0] == 0x08:  # Backspace/Delete
                if result:
                    result.pop()
                    col -= 1
                    _at(row, col); _w(' '); _at(row, col)
            elif len(key) == 1 and 32 <= key[0] < 127:
                ch = chr(key[0])
                result.append(ch)
                _w(ch)
                col += 1

    def prompt_password(self, row, label):
        """Password input showing asterisks."""
        _at(row, 2); _cll()
        _style(fg=_CYN); _w(label); _rst()
        _cursor(True)
        result = []
        col = 2 + len(label)
        _at(row, col)
        while True:
            key = self.check_key()
            if not key:
                utime.sleep_ms(30)
                continue
            if key == b'\x1b\x1b':
                _cursor(False)
                return None
            if key in (b'\r\n', b'\r', b'\n'):
                _cursor(False)
                return ''.join(result)
            if key[0] == 0x7F or key[0] == 0x08:
                if result:
                    result.pop()
                    col -= 1
                    _at(row, col); _w(' '); _at(row, col)
            elif len(key) == 1 and 32 <= key[0] < 127:
                result.append(chr(key[0]))
                _w('*')
                col += 1


# -- Main Menu -----------------------------------------------------

_MENU_ITEMS = [
    ('Scan & Connect', 'scan'),
    ('Saved Network', 'saved'),
    ('Signal Monitor', 'monitor'),
    ('Channel Analysis', 'channels'),
    ('Network Analysis', 'analyze'),
    ('Disconnect', 'disconnect'),
]

class WiFiManager:
    def __init__(self):
        self.ui = _UI()
        self.wlan = _get_wlan()
        self.sel = 0
        if _sc and _sc.has_pin():
            _clr()
            self.ui.drain_keys()
            _at(2, 2)
            _style(fg=_CYN, bold=True)
            _w('ENTER PIN')
            _rst()
            for attempt in range(3):
                pin = self.ui.prompt_password(4 + attempt, 'PIN: ')
                if pin and _sc.verify_pin(pin):
                    _wifi_pin[0] = pin
                    break
                _at(4 + attempt, 20)
                _style(fg=_RED)
                _w(' Wrong')
                _rst()

    def draw_menu(self):
        _clr()
        _cursor(False)
        self.ui.header('WiFi Manager', self.wlan)

        # Connection detail
        _at(3, 2)
        if self.wlan.isconnected():
            _style(fg=_GRN, bold=True); _w('Connected')
            _rst()
            try:
                rssi = self.wlan.status('rssi')
                bars, col = _signal_bars(rssi)
                _w('  '); _style(fg=col); _w(f'{bars} {rssi}dBm')
            except:
                pass
        else:
            _style(fg=_RED); _w('Disconnected')
        _rst()

        # Menu items
        _at(5, 2)
        _style(fg=_CYN, bold=True); _w('MENU'); _rst()

        for i, (label, _) in enumerate(_MENU_ITEMS):
            row = 7 + i
            _at(row, 1)
            if i == self.sel:
                _style(fg=_BLK, bg=_GRN, bold=True)
                _w(f' \x10 {label:<{_W - 4}}')
            else:
                _w(f'   ')
                _style(fg=_WHT)
                _w(label)
            _rst()

        self.ui.footer(
            ('\x18\x19', 'Navigate'),
            ('ENTER', 'Select'),
            ('ESC', 'Exit'),
        )

    def run(self):
        self.draw_menu()
        while True:
            key = self.ui.check_key()
            if not key:
                utime.sleep_ms(50)
                continue

            redraw = False

            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                _cursor(True); _clr(); _rst()
                return

            elif key == b'\x1b[A':  # Up
                if self.sel > 0:
                    self.sel -= 1; redraw = True

            elif key == b'\x1b[B':  # Down
                if self.sel < len(_MENU_ITEMS) - 1:
                    self.sel += 1; redraw = True

            elif key in (b'\r\n', b'\r', b'\n'):
                action = _MENU_ITEMS[self.sel][1]
                if action == 'scan':
                    ScanScreen(self.ui, self.wlan).run()
                elif action == 'saved':
                    self._connect_saved()
                elif action == 'monitor':
                    SignalMonitor(self.ui, self.wlan).run()
                elif action == 'channels':
                    ChannelAnalysis(self.ui, self.wlan).run()
                elif action == 'analyze':
                    NetworkAnalysis(self.ui, self.wlan).run()
                elif action == 'disconnect':
                    self._disconnect()
                redraw = True

            if redraw:
                self.draw_menu()

    def _connect_saved(self):
        _clr()
        self.ui.header('Saved Network', self.wlan)
        ssid, pwd = _load_creds()
        if not ssid:
            self.ui.status_line(4, 'No saved credentials found.', _YEL)
            self.ui.wait_key()
            return
        if not pwd:
            if _sc and not _wifi_pin[0]:
                _ensure_pin(self.ui)
                ssid, pwd = _load_creds()
            if not pwd:
                _clr()
                self.ui.header('Saved Network', self.wlan)
                self.ui.status_line(4, 'PIN required to decrypt password.', _YEL)
                self.ui.wait_key()
                return

        _clr()
        self.ui.header('Saved Network', self.wlan)
        self.ui.status_line(4, f'Connecting to: {ssid}...', _CYN)
        if _connect(self.wlan, ssid, pwd):
            self.ui.status_line(5, f'Connected! IP: {self.wlan.ifconfig()[0]}', _GRN)
        else:
            self.ui.status_line(5, 'Connection failed.', _RED)
        self.ui.wait_key()

    def _disconnect(self):
        if self.wlan.isconnected():
            self.wlan.disconnect()


# -- Scan & Connect Screen ----------------------------------------

class ScanScreen:
    MAX_VIS = 26

    def __init__(self, ui, wlan):
        self.ui = ui
        self.wlan = wlan
        self.networks = []
        self.sel = 0
        self.scroll = 0

    def _do_scan(self):
        _clr()
        self.ui.header('WiFi Scan', self.wlan)
        self.ui.status_line(4, 'Scanning...', _CYN)
        gc.collect()
        self.networks = _scan(self.wlan)
        self.sel = 0
        self.scroll = 0

    def draw(self):
        _clr()
        _cursor(False)
        self.ui.header('WiFi Scan', self.wlan)
        n = len(self.networks)

        _at(3, 2)
        _style(fg=_CYN, bold=True); _w('NETWORKS')
        _rst(); _style(dim=True); _w(f'  ({n})'); _rst()

        if n == 0:
            _at(5, 4); _style(dim=True); _w('No networks found'); _rst()
        else:
            # Keep selection visible
            if self.sel < self.scroll:
                self.scroll = self.sel
            elif self.sel >= self.scroll + self.MAX_VIS:
                self.scroll = self.sel - self.MAX_VIS + 1

            vis = min(self.MAX_VIS, n - self.scroll)
            for i in range(vis):
                idx = self.scroll + i
                net = self.networks[idx]
                ssid = net[0].decode() if isinstance(net[0], bytes) else net[0]
                rssi = net[3]
                auth = net[4]
                ch = net[2]
                bars, bar_col = _signal_bars(rssi)

                row = 5 + i
                _at(row, 1)

                if not ssid:
                    ssid = '[Hidden]'
                ssid_disp = ssid[:22] if len(ssid) > 22 else ssid

                if idx == self.sel:
                    _style(fg=_BLK, bg=_GRN, bold=True)
                    lock = ' ' if auth == 0 else '\x0ey\x0f'
                    _w(f' {ssid_disp:<22} {rssi:>4}dBm Ch{ch:<2} {_sec_str(auth):<5}')
                    _cll()
                else:
                    _w(' ')
                    _style(fg=bar_col); _w(bars); _rst()
                    _w(f' {ssid_disp:<22}')
                    _style(dim=True); _w(f'{rssi:>4}dBm Ch{ch:<2}')
                    if auth == 0:
                        _style(fg=_YEL); _w(' Open')
                    else:
                        _style(dim=True); _w(f' {_sec_str(auth)}')
                _rst()

            # Scroll indicators
            if self.scroll > 0:
                _at(4, _W - 1); _style(fg=_YEL, bold=True); _w('^'); _rst()
            if self.scroll + self.MAX_VIS < n:
                _at(5 + vis, _W - 1); _style(fg=_YEL, bold=True); _w('v'); _rst()

        self.ui.footer(
            ('\x18\x19', 'Select'),
            ('ENTER', 'Connect'),
            ('R', 'Rescan'),
            ('ESC', 'Back'),
        )

    def run(self):
        self._do_scan()
        self.draw()
        while True:
            key = self.ui.check_key()
            if not key:
                utime.sleep_ms(50)
                continue

            redraw = False
            n = len(self.networks)

            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                return

            elif key == b'\x1b[A' and self.sel > 0:
                self.sel -= 1; redraw = True

            elif key == b'\x1b[B' and self.sel < n - 1:
                self.sel += 1; redraw = True

            elif key == b'\x1b[H':  # Home
                self.sel = 0; self.scroll = 0; redraw = True

            elif key == b'\x1b[F':  # End
                self.sel = max(0, n - 1); redraw = True

            elif len(key) == 1 and key[0] in (ord('r'), ord('R')):
                self._do_scan(); redraw = True

            elif key in (b'\r\n', b'\r', b'\n') and n > 0:
                self._connect_selected()
                redraw = True

            if redraw:
                self.draw()

    def _connect_selected(self):
        net = self.networks[self.sel]
        ssid = net[0].decode() if isinstance(net[0], bytes) else net[0]
        auth = net[4]
        rssi = net[3]

        _clr()
        self.ui.header('Connect', self.wlan)

        _at(4, 2); _style(fg=_WHT, bold=True); _w(f'Network: '); _rst(); _w(ssid)
        bars, col = _signal_bars(rssi)
        _at(5, 2); _style(fg=col); _w(f'Signal:  {bars} {rssi}dBm ({_signal_label(rssi)})'); _rst()
        _at(6, 2); _style(dim=True); _w(f'Security: {_sec_str(auth)}  Channel: {net[2]}'); _rst()

        password = ''
        if auth != 0:
            password = self.ui.prompt_password(8, 'Password: ')
            if password is None:
                return  # ESC pressed

        _at(10, 2); _style(fg=_CYN); _w('Connecting'); _rst()
        for i in range(3):
            utime.sleep_ms(300)
            _w('.')

        if _connect(self.wlan, ssid, password):
            if _sc and password and not _wifi_pin[0]:
                if _ensure_pin(self.ui):
                    _save_creds(ssid, password)
                else:
                    _save_creds(ssid, password)
            else:
                _save_creds(ssid, password)
            _clr()
            self.ui.header('Connect', self.wlan)
            ip = self.wlan.ifconfig()[0]
            _at(4, 2); _style(fg=_GRN, bold=True); _w(f'Connected to {ssid}'); _rst()
            _at(5, 2); _w(f'IP: {ip}')
            if _wifi_pin[0]:
                _at(6, 2); _style(dim=True); _w('Password encrypted and saved.'); _rst()
            else:
                _at(6, 2); _style(dim=True); _w('Password saved.'); _rst()
        else:
            _at(12, 2); _style(fg=_RED, bold=True); _w('Connection failed'); _rst()

        self.ui.wait_key()


# -- Signal Monitor ------------------------------------------------

class SignalMonitor:
    GRAPH_W = 45
    GRAPH_H = 20

    def __init__(self, ui, wlan):
        self.ui = ui
        self.wlan = wlan
        self.readings = []

    def run(self):
        if not self.wlan.isconnected():
            _clr()
            self.ui.header('Signal Monitor', self.wlan)
            self.ui.status_line(4, 'Not connected. Connect first.', _YEL)
            self.ui.wait_key()
            return

        _clr()
        _cursor(False)
        self.ui.header('Signal Monitor', self.wlan)

        try:
            ssid = self.wlan.config('essid')
        except:
            ssid = '?'
        _at(3, 2); _style(fg=_WHT, bold=True); _w(f'Monitoring: {ssid}'); _rst()

        # Draw graph frame
        _at(4, 2); _style(dim=True); _w('dBm'); _rst()
        for i in range(self.GRAPH_H):
            row = 5 + i
            val = -40 - i * 2
            _at(row, 1)
            if i % 5 == 0:
                _style(dim=True); _w(f'{val:>4}'); _rst()
            _at(row, 6); _style(dim=True); _w('.'); _rst()

        self.ui.footer(('ESC', 'Stop'))

        # Live loop
        col = 7
        try:
            while True:
                key = self.ui.check_key()
                if key and (key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b)):
                    break

                try:
                    rssi = self.wlan.status('rssi')
                except:
                    rssi = -99

                self.readings.append(rssi)
                bars, bar_col = _signal_bars(rssi)

                # Draw bar in graph area
                bar_height = max(0, min(self.GRAPH_H, (rssi + 100) * self.GRAPH_H // 60))
                for i in range(self.GRAPH_H):
                    row = 5 + self.GRAPH_H - 1 - i
                    _at(row, col)
                    if i < bar_height:
                        _style(fg=bar_col); _w('\x0ea\x0f'); _rst()
                    else:
                        _w(' ')

                # Current reading at bottom
                _at(5 + self.GRAPH_H + 1, 2); _cll()
                _style(fg=bar_col, bold=True)
                _w(f'  {rssi} dBm  {_signal_label(rssi)}  {bars}')
                _rst()

                col += 1
                if col >= 6 + self.GRAPH_W:
                    col = 7
                    # Clear graph columns
                    for i in range(self.GRAPH_H):
                        _at(5 + i, 7)
                        _w(' ' * self.GRAPH_W)

                utime.sleep_ms(500)

        except KeyboardInterrupt:
            pass

        # Show stats
        if self.readings:
            avg = sum(self.readings) // len(self.readings)
            mn = min(self.readings)
            mx = max(self.readings)
            _clr()
            self.ui.header('Signal Summary', self.wlan)
            _at(4, 2); _style(fg=_WHT, bold=True); _w('Statistics'); _rst()
            _at(6, 4); _w(f'Readings:  {len(self.readings)}')
            _at(7, 4); _w(f'Average:   {avg} dBm')
            _at(8, 4); _w(f'Best:      {mx} dBm')
            _at(9, 4); _w(f'Worst:     {mn} dBm')
            self.ui.wait_key()


# -- Channel Analysis ----------------------------------------------

class ChannelAnalysis:
    def __init__(self, ui, wlan):
        self.ui = ui
        self.wlan = wlan

    def run(self):
        _clr()
        _cursor(False)
        self.ui.header('Channel Analysis', self.wlan)
        self.ui.status_line(4, 'Scanning...', _CYN)
        gc.collect()

        networks = _scan(self.wlan)
        if not networks:
            self.ui.status_line(4, 'No networks found.', _YEL)
            self.ui.wait_key()
            return

        # Gather channel data
        ch_data = {}
        for net in networks:
            ch = net[2]
            rssi = net[3]
            if ch not in ch_data:
                ch_data[ch] = {'count': 0, 'total_rssi': 0, 'best': rssi}
            ch_data[ch]['count'] += 1
            ch_data[ch]['total_rssi'] += rssi
            if rssi > ch_data[ch]['best']:
                ch_data[ch]['best'] = rssi

        _clr()
        self.ui.header('Channel Analysis', self.wlan)

        _at(3, 2)
        _style(fg=_CYN, bold=True); _w(f'CHANNELS')
        _rst(); _style(dim=True); _w(f'  ({len(networks)} networks)'); _rst()

        # Table header
        _at(5, 2)
        _style(fg=_WHT, bold=True)
        _w(f'{"Ch":>3}  {"APs":>3}  {"Congestion":<12}  {"Avg dBm":>8}')
        _rst()
        _at(6, 2); _style(dim=True); _box_h(42); _rst()

        row = 7
        best_ch = None
        best_score = -999

        for ch in sorted(ch_data.keys()):
            d = ch_data[ch]
            avg = d['total_rssi'] // d['count']
            count = d['count']

            # Congestion level
            if count <= 2:
                cong = 'Low'; cong_col = _GRN
                bar = '\x0eaa\x0f    '
            elif count <= 5:
                cong = 'Medium'; cong_col = _YEL
                bar = '\x0eaaaa\x0f  '
            elif count <= 8:
                cong = 'High'; cong_col = _RED
                bar = '\x0eaaaaaa\x0f'
            else:
                cong = 'Packed'; cong_col = _RED
                bar = '\x0eaaaaaa\x0f'

            # Score for recommendation (lower count = better, higher RSSI = better)
            score = -count * 10 + avg
            if score > best_score:
                best_score = score
                best_ch = ch

            _at(row, 2)
            _style(fg=_WHT, bold=True); _w(f'{ch:>3}'); _rst()
            _w(f'  {count:>3}  ')
            _style(fg=cong_col); _w(f'{bar} {cong:<6}'); _rst()
            _w(f'  {avg:>4} dBm')

            row += 1
            if row > _H - 5:
                break

        # Recommendation
        if best_ch is not None:
            _at(row + 1, 2)
            _style(fg=_GRN, bold=True); _w('Best channel: '); _rst()
            _style(fg=_WHT, bold=True); _w(f'{best_ch}'); _rst()
            _style(dim=True); _w(f' ({ch_data[best_ch]["count"]} APs, least congested)'); _rst()

        self.ui.footer(('ESC', 'Back'))
        while True:
            key = self.ui.check_key()
            if not key:
                utime.sleep_ms(50)
                continue
            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                return


# -- Network Analysis ----------------------------------------------

class NetworkAnalysis:
    def __init__(self, ui, wlan):
        self.ui = ui
        self.wlan = wlan

    def run(self):
        _clr()
        _cursor(False)
        self.ui.header('Network Analysis', self.wlan)
        self.ui.status_line(4, 'Scanning...', _CYN)
        gc.collect()

        networks = _scan(self.wlan)
        if not networks:
            self.ui.status_line(4, 'No networks found.', _YEL)
            self.ui.wait_key()
            return

        # Analyze
        total = len(networks)
        n_open = sum(1 for n in networks if n[4] == 0)
        n_hidden = sum(1 for n in networks if not n[0])
        sig = {'excellent': 0, 'good': 0, 'fair': 0, 'weak': 0}
        sec_counts = {}

        strongest = networks[0]  # Already sorted
        weakest = networks[-1]

        for net in networks:
            rssi = net[3]
            auth = net[4]
            sec = _sec_str(auth)
            sec_counts[sec] = sec_counts.get(sec, 0) + 1
            if rssi >= -50: sig['excellent'] += 1
            elif rssi >= -60: sig['good'] += 1
            elif rssi >= -70: sig['fair'] += 1
            else: sig['weak'] += 1

        _clr()
        self.ui.header('Network Analysis', self.wlan)

        # Summary
        _at(3, 2); _style(fg=_CYN, bold=True); _w('SUMMARY'); _rst()
        _at(4, 4); _w(f'Total networks:  '); _style(fg=_WHT, bold=True); _w(f'{total}'); _rst()
        _at(5, 4); _w(f'Open networks:   ')
        if n_open > 0:
            _style(fg=_YEL, bold=True)
        _w(f'{n_open}'); _rst()
        _at(6, 4); _w(f'Hidden networks: {n_hidden}')

        # Signal distribution
        _at(8, 2); _style(fg=_CYN, bold=True); _w('SIGNAL QUALITY'); _rst()
        labels = [('Excellent', sig['excellent'], _GRN),
                  ('Good', sig['good'], _GRN),
                  ('Fair', sig['fair'], _YEL),
                  ('Weak', sig['weak'], _RED)]
        for i, (label, count, col) in enumerate(labels):
            _at(9 + i, 4)
            _style(fg=col); _w(f'{label:<10}'); _rst()
            pct = count * 100 // total if total else 0
            bar_len = count * 20 // total if total else 0
            _style(fg=col); _w('\x0e' + 'a' * bar_len + '\x0f'); _rst()
            _w(f' {count} ({pct}%)')

        # Security
        _at(14, 2); _style(fg=_CYN, bold=True); _w('SECURITY'); _rst()
        row = 15
        for sec, count in sorted(sec_counts.items(), key=lambda x: -x[1]):
            pct = count * 100 // total
            _at(row, 4)
            col = _YEL if sec == 'Open' or sec == 'WEP' else _GRN
            _style(fg=col); _w(f'{sec:<8}'); _rst()
            _w(f' {count:>2} ({pct}%)')
            row += 1

        # Highlights
        row += 1
        _at(row, 2); _style(fg=_CYN, bold=True); _w('HIGHLIGHTS'); _rst()
        s_ssid = strongest[0].decode() if isinstance(strongest[0], bytes) else strongest[0]
        w_ssid = weakest[0].decode() if isinstance(weakest[0], bytes) else weakest[0]
        _at(row + 1, 4); _style(fg=_GRN); _w('Strongest: '); _rst()
        _w(f'{s_ssid[:20]} ({strongest[3]}dBm)')
        _at(row + 2, 4); _style(fg=_RED); _w('Weakest:   '); _rst()
        _w(f'{w_ssid[:20]} ({weakest[3]}dBm)')

        # Warnings
        if n_open > 0:
            _at(row + 4, 2)
            _style(fg=_YEL, bold=True); _w(f'! {n_open} open network(s) detected'); _rst()

        self.ui.footer(('ESC', 'Back'))
        while True:
            key = self.ui.check_key()
            if not key:
                utime.sleep_ms(50)
                continue
            if key == b'\x1b\x1b' or (len(key) == 1 and key[0] == 0x1b):
                return


# -- Entry point ---------------------------------------------------

def main():
    gc.collect()
    try:
        app = WiFiManager()
        app.run()
    except Exception as e:
        _cursor(True); _rst(); _clr()
        print(f'WiFiManager error: {e}')
        import sys
        sys.print_exception(e)

if __name__ == '__main__':
    main()
