"""
ProxiScan 4.0 - BLE Proximity Scanner & Fox Hunt Tool
Features:
- Real-time BLE device scanning with signal strength
- Arrow-key device selection with scrollable list
- Target tracking with compass and signal visualization
- Competition timer and waypoint system
- 4-point antenna calibration for direction finding
- Dual audio feedback modes (frequency / beep-rate)
- Signal history graph and trend analysis
- Logging to SD card with review
"""

import picocalc
import bluetooth
import math
import utime
import gc
import os
from machine import Pin, PWM

# Audio pins
AUDIO_LEFT = 28
AUDIO_RIGHT = 27

# Arrow key escape sequences
KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_LEFT = b'\x1b[D'
KEY_RIGHT = b'\x1b[C'
KEY_ESC = b'\x1b\x1b'

# Configuration
LOG_FILE = "/sd/logs/proxiscan_log.txt"
RSSI_AT_1M = -59
N_FACTOR = 2.0

# Display colors (4-bit grayscale)
C_BLK = 0
C_DKGR = 3
C_DK = 5
C_GR = 8
C_MD = 10
C_LT = 12
C_WHT = 15

# Modes
MODE_SCAN = 0
MODE_HUNT = 1
MODE_TRACK = 2

# Layout constants
W = 320
H = 320
TOPBAR_H = 18
LIST_Y = 22
LIST_ROW_H = 32
MAX_VIS_DEVS = 8
CTRL_Y = 296


class ProxiScan:
    def __init__(self):
        self.display = picocalc.display
        self.key_buf = bytearray(10)

        # Audio (both channels)
        try:
            self.audio_l = PWM(Pin(AUDIO_LEFT))
            self.audio_r = PWM(Pin(AUDIO_RIGHT))
            self.has_audio = True
        except:
            self.audio_l = None
            self.audio_r = None
            self.has_audio = False
        self.audio_on = True
        self.audio_mode = 0  # 0=frequency, 1=beep-rate
        self.last_beep = 0

        # BLE
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self.ble_irq)
        self.scanning = False

        # State
        self.mode = MODE_SCAN
        self.devices = {}
        self.dev_list = []  # sorted snapshot for display
        self.sel = 0
        self.scroll = 0

        # Target tracking
        self.target_mac = None
        self.target_name = ""
        self.target_history = []
        self.bearing = 0
        self.avg_rssi = -100
        self.peak_rssi = -100
        self.trend = 0  # +1 stronger, -1 weaker, 0 stable

        # Calibration
        self.bearing_cal = {}
        self.confidence = 0

        # Competition
        self.timer_start = None
        self.waypoints = []

        # Animation
        self.anim = 0
        self.last_draw = 0
        self.last_dev_count = 0

    # -- BLE ------------------------------------------------

    def ble_irq(self, event, data):
        if event == 5 and self.scanning:
            try:
                addr_type, addr, adv_type, rssi, adv_data = data
                mac = ':'.join(['%02X' % b for b in bytes(addr)])
                name = self._decode_name(adv_data)
                self.devices[mac] = {
                    'rssi': rssi, 'name': name,
                    'ts': utime.ticks_ms(),
                    'dist': self._rssi_to_ft(rssi)
                }
                if self.mode == MODE_HUNT and mac == self.target_mac:
                    self._process_signal(rssi)
            except:
                pass

    def _decode_name(self, adv):
        try:
            if isinstance(adv, memoryview):
                adv = bytes(adv)
            i = 0
            while i < len(adv):
                ln = adv[i]
                if ln == 0 or i + ln >= len(adv):
                    break
                if adv[i + 1] in (0x08, 0x09):
                    try:
                        return adv[i + 2:i + 1 + ln].decode("utf-8")
                    except:
                        return ""
                i += 1 + ln
            return ""
        except:
            return ""

    def _rssi_to_ft(self, rssi):
        try:
            if rssi >= 0:
                return 0.1
            d = 10 ** ((RSSI_AT_1M - rssi) / (10 * N_FACTOR))
            return round(d * 3.28084, 1)
        except:
            return 999.9

    def start_scan(self):
        try:
            self.scanning = True
            self.ble.gap_scan(0, 30000, 30000)
        except:
            self.scanning = False

    def stop_scan(self):
        try:
            self.scanning = False
            self.ble.gap_scan(None)
            self.ble.active(False)
            utime.sleep_ms(50)
            self.ble.active(True)
            self.ble.irq(self.ble_irq)
            utime.sleep_ms(50)
        except:
            self.scanning = False

    # -- Signal Processing ----------------------------------

    def _process_signal(self, rssi):
        self.target_history.append({
            'ts': utime.ticks_ms(), 'rssi': rssi,
            'dist': self._rssi_to_ft(rssi), 'bearing': self.bearing
        })
        if len(self.target_history) > 30:
            self.target_history.pop(0)

        if rssi > self.peak_rssi:
            self.peak_rssi = rssi

        # Rolling average (last 5)
        recent = self.target_history[-5:]
        self.avg_rssi = sum(h['rssi'] for h in recent) / len(recent)

        # Trend (last 3)
        if len(self.target_history) >= 3:
            r = [h['rssi'] for h in self.target_history[-3:]]
            diff = r[-1] - r[0]
            self.trend = 1 if diff > 2 else (-1 if diff < -2 else 0)

        # Bearing drift from RSSI change
        if len(self.target_history) >= 2:
            rd = rssi - self.target_history[-2]['rssi']
            self.bearing = (self.bearing + rd * 2) % 360

        # Audio
        if self.audio_on and self.has_audio:
            if self.audio_mode == 0:
                self._play_tone(rssi)
            else:
                self._play_beep(rssi)

    def _play_tone(self, rssi):
        try:
            freq = int(max(200, min(2000, (rssi + 100) * 20)))
            self.audio_l.freq(freq)
            self.audio_r.freq(freq)
            self.audio_l.duty_u16(16384)
            self.audio_r.duty_u16(16384)
            utime.sleep_ms(40)
            self.audio_l.duty_u16(0)
            self.audio_r.duty_u16(0)
        except:
            pass

    def _play_beep(self, rssi):
        try:
            if rssi > -50:
                delay = 100
            elif rssi > -60:
                delay = 200
            elif rssi > -70:
                delay = 400
            elif rssi > -80:
                delay = 800
            else:
                delay = 1600
            now = utime.ticks_ms()
            if utime.ticks_diff(now, self.last_beep) > delay:
                self.audio_l.freq(1000)
                self.audio_r.freq(1000)
                self.audio_l.duty_u16(32768)
                self.audio_r.duty_u16(32768)
                utime.sleep_ms(40)
                self.audio_l.duty_u16(0)
                self.audio_r.duty_u16(0)
                self.last_beep = now
        except:
            pass

    # -- Drawing --------------------------------------------

    def _refresh_dev_list(self):
        self.dev_list = sorted(self.devices.items(),
                               key=lambda x: x[1]['rssi'], reverse=True)

    def draw(self):
        d = self.display
        d.beginDraw()
        d.fill(C_BLK)
        self._draw_topbar(d)
        if self.mode == MODE_SCAN:
            self._draw_scan(d)
        elif self.mode == MODE_HUNT:
            self._draw_hunt(d)
        elif self.mode == MODE_TRACK:
            self._draw_track(d)
        d.show()

    def _draw_topbar(self, d):
        # Dark background
        d.fill_rect(0, 0, W, TOPBAR_H, C_DKGR)
        d.text("PROXISCAN", 4, 5, C_WHT)

        # Mode tabs
        modes = ["SCAN", "HUNT", "TRACK"]
        tx = 110
        for i, m in enumerate(modes):
            c = C_WHT if i == self.mode else C_DK
            d.text(m, tx, 5, c)
            tx += len(m) * 6 + 10

        # Device count + scan indicator
        n = len(self.devices)
        dots = "." * ((self.anim % 3) + 1) if self.scanning else ""
        d.text(f"{n}dev{dots}", W - 54, 5, C_MD if self.scanning else C_DK)

        # Separator line
        d.hline(0, TOPBAR_H, W, C_LT)

    def _draw_scan(self, d):
        self._refresh_dev_list()
        n = len(self.dev_list)

        if not self.scanning and n == 0:
            d.text("Press P to start scanning", 30, 100, C_MD)
            d.text("ESC to exit", 100, 130, C_GR)
            self._draw_ctrl(d, "P:Scan  ESC:Exit")
            return

        # Ensure selection in bounds
        if self.sel >= n:
            self.sel = max(0, n - 1)
        if self.sel < self.scroll:
            self.scroll = self.sel
        elif self.sel >= self.scroll + MAX_VIS_DEVS:
            self.scroll = self.sel - MAX_VIS_DEVS + 1

        # Scroll indicators
        if self.scroll > 0:
            d.text("^", W - 12, LIST_Y, C_MD)
        if self.scroll + MAX_VIS_DEVS < n:
            d.text("v", W - 12, LIST_Y + MAX_VIS_DEVS * LIST_ROW_H - 10, C_MD)

        # Device rows
        for i in range(min(MAX_VIS_DEVS, n - self.scroll)):
            idx = self.scroll + i
            mac, data = self.dev_list[idx]
            y = LIST_Y + i * LIST_ROW_H
            selected = (idx == self.sel)
            self._draw_dev_row(d, y, mac, data, selected, idx == 0)

        # Controls
        self._draw_ctrl(d, "\x18\x19:Sel ENTER:Hunt P:Scan ESC:Exit")

    def _draw_dev_row(self, d, y, mac, data, selected, is_strongest):
        rssi = data['rssi']
        name = data['name'][:14] if data['name'] else "[unknown]"
        short_mac = mac[-8:]
        dist_str = f"{data['dist']:.0f}ft" if data['dist'] < 100 else f"{int(data['dist'])}ft"

        if selected:
            d.fill_rect(1, y, W - 14, LIST_ROW_H - 2, C_DK)
            d.rect(1, y, W - 14, LIST_ROW_H - 2, C_WHT)
            tc = C_WHT
        else:
            d.rect(1, y, W - 14, LIST_ROW_H - 2, C_DKGR)
            tc = C_LT

        # Signal bar
        bar_w = int(max(2, min(130, (rssi + 100) * 2.6)))
        bar_c = C_WHT if rssi > -55 else (C_LT if rssi > -70 else C_GR)
        d.fill_rect(4, y + 3, bar_w, 5, bar_c)

        # Star for strongest
        if is_strongest:
            d.text("*", 4, y + 11, C_WHT)

        # Name + RSSI
        d.text(name, 14, y + 11, tc)
        d.text(f"{rssi}dBm", W - 74, y + 11, bar_c)

        # MAC + distance
        d.text(short_mac, 14, y + 21, C_GR)
        d.text(dist_str, W - 50, y + 21, C_GR)

    def _draw_hunt(self, d):
        if not self.target_mac:
            d.text("No target selected", 60, 100, C_MD)
            self._draw_ctrl(d, "S:Scan  ESC:Exit")
            return

        data = self.devices.get(self.target_mac)
        rssi = data['rssi'] if data else self.avg_rssi
        dist = data['dist'] if data else 0

        # Target info bar
        y0 = LIST_Y
        d.fill_rect(0, y0, W, 22, C_DKGR)
        nm = self.target_name[:12] if self.target_name else self.target_mac[-8:]
        d.text(nm, 4, y0 + 3, C_WHT)

        rssi_c = C_WHT if rssi > -55 else (C_LT if rssi > -70 else C_GR)
        d.text(f"{int(self.avg_rssi)}dBm", 110, y0 + 3, rssi_c)
        d.text(f"{dist:.0f}ft", 170, y0 + 3, C_MD)

        # Trend
        trend_s = "\x1e STRONGER" if self.trend > 0 else ("\x1f WEAKER" if self.trend < 0 else "= STABLE")
        trend_c = C_WHT if self.trend > 0 else (C_GR if self.trend < 0 else C_MD)
        d.text(trend_s, 215, y0 + 3, trend_c)

        # Compass (left half)
        self._draw_compass(d, 90, 140, 65)

        # Signal panel (right half)
        self._draw_signal_panel(d, 195, 50)

        # Signal history graph
        self._draw_graph(d, 10, 215, 250, 52)

        # Timer + waypoints
        if self.timer_start is not None:
            elapsed = utime.ticks_diff(utime.ticks_ms(), self.timer_start) // 1000
            m, s = elapsed // 60, elapsed % 60
            d.text(f"Time:{m}:{s:02d}", 270, 215, C_MD)
            d.text(f"WP:{len(self.waypoints)}", 270, 227, C_MD)

        # Audio indicator
        am = "FREQ" if self.audio_mode == 0 else "BEEP"
        ac = C_MD if self.audio_on else C_DK
        d.text(f"AU:{am}", 270, 250, ac)

        # Controls
        self._draw_ctrl(d, "S:Scan T:Track W:Mark A:Aud C:Cal L:Log ESC")

    def _draw_compass(self, d, cx, cy, r):
        # Octagon
        for a in range(0, 360, 45):
            x1 = cx + int(r * math.cos(math.radians(a)))
            y1 = cy + int(r * math.sin(math.radians(a)))
            x2 = cx + int(r * math.cos(math.radians(a + 45)))
            y2 = cy + int(r * math.sin(math.radians(a + 45)))
            d.line(x1, y1, x2, y2, C_GR)

        # Tick marks at 30-degree intervals
        for a in range(0, 360, 30):
            ix = cx + int((r - 6) * math.cos(math.radians(a)))
            iy = cy + int((r - 6) * math.sin(math.radians(a)))
            ox = cx + int(r * math.cos(math.radians(a)))
            oy = cy + int(r * math.sin(math.radians(a)))
            d.line(ix, iy, ox, oy, C_DK)

        # Cardinals
        d.text("N", cx - 3, cy - r - 12, C_WHT)
        d.text("S", cx - 3, cy + r + 4, C_GR)
        d.text("E", cx + r + 4, cy - 4, C_GR)
        d.text("W", cx - r - 10, cy - 4, C_GR)

        # Bearing arrow
        br = math.radians(self.bearing)
        al = r - 8
        ex = cx + int(al * math.sin(br))
        ey = cy - int(al * math.cos(br))
        d.line(cx, cy, ex, ey, C_WHT)
        # Arrowhead
        hl = 10
        ha = 0.5
        d.line(ex, ey,
               ex - int(hl * math.sin(br - ha)),
               ey + int(hl * math.cos(br - ha)), C_WHT)
        d.line(ex, ey,
               ex - int(hl * math.sin(br + ha)),
               ey + int(hl * math.cos(br + ha)), C_WHT)

        # Center dot
        d.fill_rect(cx - 2, cy - 2, 4, 4, C_LT)

        # Bearing text
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        di = int((self.bearing + 22.5) % 360 / 45)
        d.text(f"{dirs[di]} {int(self.bearing)}", cx - 20, cy + r + 16, C_MD)

        # Confidence
        if self.confidence > 0:
            d.text(f"{self.confidence}%", cx - 10, cy + r + 28, C_GR)

    def _draw_signal_panel(self, d, x, y):
        # Vertical meter
        mx, my, mw, mh = x, y, 25, 130
        d.rect(mx, my, mw, mh, C_GR)

        # Fill level
        level = int(max(0, min(mh - 4, (self.avg_rssi + 100) * 2.5)))
        if level > 0:
            fc = C_WHT if self.avg_rssi > -55 else (C_LT if self.avg_rssi > -70 else C_GR)
            d.fill_rect(mx + 2, my + mh - 2 - level, mw - 4, level, fc)

        # Scale marks
        for i in range(0, mh, 26):
            d.hline(mx - 3, my + i, 3, C_DK)

        # Labels right of meter
        lx = x + 32
        d.text("RSSI", lx, y, C_GR)
        rc = C_WHT if self.avg_rssi > -55 else C_LT
        d.text(f"{int(self.avg_rssi)}", lx, y + 14, rc)
        d.text("dBm", lx + 24, y + 14, C_GR)

        d.text("Dist", lx, y + 34, C_GR)
        if self.target_mac in self.devices:
            dst = self.devices[self.target_mac]['dist']
            d.text(f"{dst:.0f}ft", lx, y + 48, C_MD)

        d.text("Peak", lx, y + 68, C_GR)
        d.text(f"{self.peak_rssi}", lx, y + 82, C_MD)

        d.text("Avg", lx, y + 100, C_GR)
        d.text(f"{self.avg_rssi:.0f}", lx, y + 114, C_MD)

    def _draw_graph(self, d, gx, gy, gw, gh):
        hist = self.target_history
        if len(hist) < 2:
            d.rect(gx, gy, gw, gh, C_DKGR)
            d.text("Waiting for data...", gx + 50, gy + 20, C_DK)
            return

        d.rect(gx, gy, gw, gh, C_DK)

        # Grid lines
        for i in range(1, 4):
            ly = gy + i * gh // 4
            d.hline(gx + 1, ly, gw - 2, C_DKGR)

        # Scale
        mx = max(h['rssi'] for h in hist)
        mn = min(h['rssi'] for h in hist)
        rng = mx - mn if mx != mn else 1
        d.text(f"{mx}", gx + 1, gy + 2, C_DK)
        d.text(f"{mn}", gx + 1, gy + gh - 10, C_DK)

        # Plot
        n = len(hist)
        for i in range(1, n):
            x1 = gx + (i - 1) * gw // n
            x2 = gx + i * gw // n
            y1 = gy + gh - 4 - int((hist[i - 1]['rssi'] - mn) / rng * (gh - 8))
            y2 = gy + gh - 4 - int((hist[i]['rssi'] - mn) / rng * (gh - 8))
            d.line(x1, y1, x2, y2, C_WHT)

    def _draw_track(self, d):
        if not self.target_mac:
            d.text("No target selected", 60, 100, C_MD)
            self._draw_ctrl(d, "S:Scan  ESC:Exit")
            return

        data = self.devices.get(self.target_mac)
        y = LIST_Y

        # Stats panel background
        d.fill_rect(0, y, W, 78, C_DKGR)

        nm = self.target_name[:18] if self.target_name else self.target_mac[-8:]
        d.text(f"Target: {nm}", 4, y + 3, C_WHT)
        d.text(f"MAC: {self.target_mac}", 4, y + 15, C_GR)

        rc = C_WHT if self.avg_rssi > -55 else C_LT
        d.text(f"RSSI:{int(self.avg_rssi)}", 4, y + 29, rc)
        d.text(f"Avg:{self.avg_rssi:.1f}", 80, y + 29, C_MD)
        d.text(f"Peak:{self.peak_rssi}", 175, y + 29, C_MD)

        dist_s = f"{data['dist']:.0f}ft" if data else "--"
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        di = int((self.bearing + 22.5) % 360 / 45)
        d.text(f"Dist:{dist_s}", 4, y + 43, C_MD)
        d.text(f"Bearing:{dirs[di]}({int(self.bearing)})", 100, y + 43, C_MD)
        if self.confidence > 0:
            d.text(f"Conf:{self.confidence}%", 250, y + 43, C_GR)

        # Trend
        trend_s = "\x1e STRONGER" if self.trend > 0 else ("\x1f WEAKER" if self.trend < 0 else "= STABLE")
        trend_c = C_WHT if self.trend > 0 else (C_GR if self.trend < 0 else C_MD)
        d.text(f"Trend:{trend_s}", 4, y + 57, trend_c)
        d.text(f"Samples:{len(self.target_history)}", 200, y + 57, C_GR)

        # Timer
        if self.timer_start is not None:
            elapsed = utime.ticks_diff(utime.ticks_ms(), self.timer_start) // 1000
            d.text(f"Timer:{elapsed // 60}:{elapsed % 60:02d}", 4, y + 69, C_LT)

        # Signal graph (larger)
        self._draw_graph(d, 4, 106, 310, 70)

        # Waypoints
        wy = 182
        d.text(f"Waypoints ({len(self.waypoints)}):", 4, wy, C_LT)
        wy += 14
        for i, wp in enumerate(self.waypoints[-6:]):
            ws = wp['elapsed'] // 1000
            dirs_i = int((wp['bearing'] + 22.5) % 360 / 45)
            d.text(f"#{i+1} {ws//60}:{ws%60:02d} {wp['rssi']}dBm {dirs[dirs_i]}", 8, wy, C_GR)
            wy += 12

        # Controls
        self._draw_ctrl(d, "H:Hunt W:Mark C:Cal L:Log V:View ESC")

    def _draw_ctrl(self, d, text):
        d.fill_rect(0, CTRL_Y, W, H - CTRL_Y, C_DKGR)
        d.hline(0, CTRL_Y, W, C_GR)
        # Split into 2 lines if long
        if len(text) > 45:
            mid = text.rfind(' ', 0, 45)
            if mid > 0:
                d.text(text[:mid], 4, CTRL_Y + 5, C_MD)
                d.text(text[mid + 1:], 4, CTRL_Y + 16, C_MD)
                return
        d.text(text, 4, CTRL_Y + 8, C_MD)

    # -- Input ----------------------------------------------

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

    def handle_input(self):
        key = self.check_key()
        if not key:
            return True

        # Robust ESC: match double-ESC or single-ESC (not arrow sequences)
        if key == KEY_ESC or (len(key) == 1 and key[0] == 0x1b):
            return False

        if self.mode == MODE_SCAN:
            return self._input_scan(key)
        elif self.mode == MODE_HUNT:
            return self._input_hunt(key)
        elif self.mode == MODE_TRACK:
            return self._input_track(key)
        return True

    def _input_scan(self, key):
        n = len(self.dev_list)
        if key == KEY_UP and self.sel > 0:
            self.sel -= 1
        elif key == KEY_DOWN and self.sel < n - 1:
            self.sel += 1
        elif key in (b'\r\n', b'\r', b'\n'):
            if n > 0:
                mac, data = self.dev_list[self.sel]
                self.target_mac = mac
                self.target_name = data['name']
                self.target_history.clear()
                self.peak_rssi = -100
                self.avg_rssi = -100
                self.trend = 0
                self.waypoints.clear()
                self.timer_start = utime.ticks_ms()
                self.mode = MODE_HUNT
                if not self.scanning:
                    self.start_scan()
        elif len(key) == 1:
            ch = key[0]
            if ch in (ord('p'), ord('P'), 32):
                if self.scanning:
                    self.stop_scan()
                else:
                    self.devices.clear()
                    self.dev_list.clear()
                    self.sel = 0
                    self.scroll = 0
                    self.start_scan()
        return True

    def _input_hunt(self, key):
        if key == KEY_UP:
            self.bearing = (self.bearing - 10) % 360
        elif key == KEY_DOWN:
            self.bearing = (self.bearing + 10) % 360
        elif key == KEY_LEFT:
            self.bearing = (self.bearing - 30) % 360
        elif key == KEY_RIGHT:
            self.bearing = (self.bearing + 30) % 360
        elif len(key) == 1:
            ch = key[0]
            if ch in (ord('s'), ord('S')):
                self.mode = MODE_SCAN
                self.stop_scan()
            elif ch in (ord('t'), ord('T')):
                self.mode = MODE_TRACK
            elif ch in (ord('w'), ord('W')):
                self._mark_waypoint()
            elif ch in (ord('a'), ord('A')):
                self._toggle_audio()
            elif ch in (ord('c'), ord('C')):
                self._calibrate()
            elif ch in (ord('l'), ord('L')):
                self._log_data()
        return True

    def _input_track(self, key):
        if len(key) == 1:
            ch = key[0]
            if ch in (ord('h'), ord('H')):
                self.mode = MODE_HUNT
                if not self.scanning:
                    self.start_scan()
            elif ch in (ord('s'), ord('S')):
                self.mode = MODE_SCAN
                self.stop_scan()
            elif ch in (ord('w'), ord('W')):
                self._mark_waypoint()
            elif ch in (ord('c'), ord('C')):
                self._calibrate()
            elif ch in (ord('l'), ord('L')):
                self._log_data()
            elif ch in (ord('v'), ord('V')):
                self._view_log()
        return True

    # -- Competition ----------------------------------------

    def _mark_waypoint(self):
        if not self.timer_start:
            return
        elapsed = utime.ticks_diff(utime.ticks_ms(), self.timer_start)
        self.waypoints.append({
            'elapsed': elapsed,
            'rssi': int(self.avg_rssi),
            'bearing': int(self.bearing),
            'confidence': self.confidence
        })
        if len(self.waypoints) > 10:
            self.waypoints.pop(0)

    def _calibrate(self):
        """4-point antenna calibration. Enters text mode temporarily."""
        was_scanning = self.scanning
        if was_scanning:
            # Keep scanning for RSSI samples during calibration
            pass

        self.display.fill(C_BLK)
        self.display.text("ANTENNA CALIBRATION", 50, 10, C_WHT)
        self.display.text("Point antenna in each", 30, 35, C_MD)
        self.display.text("direction, press ENTER", 30, 50, C_MD)
        self.display.text("to sample. Q to finish.", 30, 65, C_MD)
        self.display.show()

        directions = [("North", 0), ("East", 90), ("South", 180), ("West", 270)]
        self.bearing_cal = {}

        for name, bearing in directions:
            print(f"\nPoint antenna {name} ({bearing})")
            cmd = input("ENTER=sample, Q=done: ").strip().lower()
            if cmd == 'q':
                break

            print(f"Sampling {name}...")
            samples = []
            start = utime.ticks_ms()
            while utime.ticks_diff(utime.ticks_ms(), start) < 3000:
                if self.target_history:
                    samples.append(self.target_history[-1]['rssi'])
                utime.sleep_ms(200)

            if samples:
                avg = sum(samples) / len(samples)
                self.bearing_cal[bearing] = avg
                print(f"{name}: {avg:.1f} dBm ({len(samples)} samples)")

        # Calculate confidence
        if len(self.bearing_cal) >= 2:
            vals = list(self.bearing_cal.values())
            rng = max(vals) - min(vals)
            if rng > 20:
                self.confidence = 95
            elif rng > 15:
                self.confidence = 80
            elif rng > 10:
                self.confidence = 60
            elif rng > 5:
                self.confidence = 40
            else:
                self.confidence = 20
            strongest = max(self.bearing_cal.items(), key=lambda x: x[1])
            self.bearing = strongest[0]
            print(f"\nBearing: {self.bearing} Confidence: {self.confidence}%")
        else:
            print("\nNot enough samples")

        input("\nPress Enter to return...")

    def _toggle_audio(self):
        if not self.has_audio:
            return
        # Cycle: freq -> beep -> off -> freq
        if self.audio_on and self.audio_mode == 0:
            self.audio_mode = 1
        elif self.audio_on and self.audio_mode == 1:
            self.audio_on = False
            self.audio_l.duty_u16(0)
            self.audio_r.duty_u16(0)
        else:
            self.audio_on = True
            self.audio_mode = 0

    # -- Logging --------------------------------------------

    def _log_data(self):
        if not self.target_mac or not self.target_history:
            return
        try:
            try:
                os.listdir("/sd/logs")
            except:
                os.mkdir("/sd/logs")
            with open(LOG_FILE, "a") as f:
                h = self.target_history[-1]
                elapsed = ""
                if self.timer_start:
                    es = utime.ticks_diff(utime.ticks_ms(), self.timer_start) // 1000
                    elapsed = f" | Time:{es // 60}:{es % 60:02d}"
                f.write(f"PS4: {utime.ticks_ms()} | {self.target_name} | "
                       f"MAC:{self.target_mac} | RSSI:{h['rssi']} | "
                       f"Avg:{self.avg_rssi:.0f} | Peak:{self.peak_rssi} | "
                       f"Dist:{h['dist']:.1f}ft | "
                       f"Bearing:{int(self.bearing)}{elapsed}\n")
            # Flash feedback
            self.display.fill_rect(80, 140, 160, 30, C_DK)
            self.display.text("Logged!", 130, 150, C_WHT)
            self.display.show()
            utime.sleep_ms(300)
        except:
            pass

    def _view_log(self):
        """View recent log entries."""
        self.display.fill(C_BLK)
        self.display.text("LOG REVIEW", 110, 5, C_WHT)
        try:
            lines = []
            with open(LOG_FILE, "r") as f:
                for line in f:
                    lines.append(line.rstrip())
                    if len(lines) > 15:
                        lines.pop(0)
            y = 22
            for line in lines:
                self.display.text(line[:53], 2, y, C_GR)
                y += 10
                if y > 290:
                    break
        except:
            self.display.text("No log data found", 70, 100, C_DK)
        self.display.text("Press any key...", 90, 305, C_MD)
        self.display.show()
        # Wait for key
        while not self.check_key():
            utime.sleep_ms(100)

    # -- Lifecycle ------------------------------------------

    def cleanup(self):
        self.stop_scan()
        if self.has_audio:
            self.audio_l.duty_u16(0)
            self.audio_r.duty_u16(0)
        try:
            self.ble.active(False)
        except:
            pass
        self.display.fill(C_BLK)
        self.display.text("ProxiScan offline", 80, 155, C_DK)
        self.display.show()

    def run(self):
        if not picocalc.terminal:
            print("ProxiScan requires PicoCalc hardware.")
            print("Use the terminal interface, not serial REPL.")
            return

        self.draw()

        try:
            while True:
                if not self.handle_input():
                    break

                now = utime.ticks_ms()
                should_draw = False

                # 1 FPS animation tick
                if utime.ticks_diff(now, self.last_draw) > 1000:
                    self.anim += 1
                    self.last_draw = now
                    should_draw = True

                    # Bearing drift in hunt mode
                    if self.mode == MODE_HUNT and self.target_history:
                        drift = math.sin(self.anim * 0.05) * 0.5
                        self.bearing = (self.bearing + drift) % 360

                # Redraw on device count change
                if self.scanning and len(self.devices) != self.last_dev_count:
                    self.last_dev_count = len(self.devices)
                    should_draw = True

                if should_draw:
                    self.draw()

                utime.sleep_ms(50)

        except KeyboardInterrupt:
            pass

        self.cleanup()


def main():
    gc.collect()
    try:
        print(f"Free memory: {gc.mem_free()} bytes")
        app = ProxiScan()
        app.run()
        print("ProxiScan exited")
    except Exception as e:
        print(f"Error: {e}")
        import sys
        sys.print_exception(e)


if __name__ == "__main__":
    main()
