"""
PicoCalc Screensaver

Modes:
- Warp Starfield
- Plasma Grid
- Light Trails

Controls:
- Right/Space/M: next mode
- Left: previous mode
- ESC/Q: exit
"""

import gc
import math
import picocalc
import urandom
import utime

KEY_UP = b"\x1b[A"
KEY_DOWN = b"\x1b[B"
KEY_LEFT = b"\x1b[D"
KEY_RIGHT = b"\x1b[C"
KEY_ESC = b"\x1b\x1b"

W = 320
H = 320
CX = W // 2
CY = H // 2

AUTO_SWITCH_MS = 12000

MODE_NAMES = ("WARP STARFIELD", "PLASMA GRID", "LIGHT TRAILS")


def _randi(lo, hi):
    return lo + (urandom.getrandbits(16) % (hi - lo + 1))


class ScreenSaver:
    def __init__(self):
        self.d = picocalc.display
        self.key_buf = bytearray(12)
        self.mode = 0
        self.frame = 0
        self.mode_started = utime.ticks_ms()

        self.sine = [int((math.sin(i * 0.09817477) + 1.0) * 127.0) for i in range(64)]

        self.stars = []
        self._init_stars()

        self.trails = []
        self._init_trails()

        self.d.beginDraw()
        self.d.fill(0)
        self.d.show()

    def _init_stars(self):
        self.stars = []
        for _ in range(95):
            self.stars.append([
                _randi(-160, 160),  # x in world
                _randi(-160, 160),  # y in world
                _randi(12, 180),    # z depth
                _randi(1, 3),       # speed
                -1,                 # previous screen x
                -1,                 # previous screen y
            ])

    def _init_trails(self):
        self.trails = []
        for _ in range(28):
            dx = _randi(-3, 3)
            dy = _randi(-3, 3)
            if dx == 0:
                dx = 1
            if dy == 0:
                dy = -1
            self.trails.append([
                _randi(0, W - 1),
                _randi(0, H - 1),
                dx,
                dy,
                _randi(7, 13),
            ])

    def _read_key(self):
        try:
            n = picocalc.terminal.readinto(self.key_buf)
        except OSError:
            return None
        if not n:
            return None
        return bytes(self.key_buf[:n])

    def _switch_mode(self, delta):
        self.mode = (self.mode + delta) % len(MODE_NAMES)
        self.mode_started = utime.ticks_ms()
        self.frame = 0
        self.d.beginDraw()
        self.d.fill(0)
        self.d.show()
        if self.mode == 0:
            self._init_stars()
        elif self.mode == 2:
            self._init_trails()

    def _handle_key(self, key):
        if not key:
            return True

        if key in (KEY_RIGHT, KEY_DOWN, b" ", b"m", b"M"):
            self._switch_mode(1)
            return True
        if key in (KEY_LEFT, KEY_UP):
            self._switch_mode(-1)
            return True

        # ESC, Q, or unknown escape sequence exits.
        if key in (KEY_ESC, b"\x1b", b"q", b"Q"):
            return False
        if len(key) >= 1 and key[0] == 0x1B and key not in (KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT):
            return False
        return True

    def _draw_hud(self):
        self.d.fill_rect(0, 0, W, 12, 0)
        self.d.text(MODE_NAMES[self.mode], 4, 2, 10)
        self.d.text("M/-> mode  ESC exit", 186, 2, 7)

    def _draw_starfield(self):
        self.d.beginDraw()
        self.d.fill(0)

        # Light tunnel rings for depth cue.
        pulse = (self.frame // 3) & 15
        for r in range(18, 158, 28):
            shade = (r // 14 + pulse) & 15
            self.d.rect(CX - r, CY - r, r * 2, r * 2, shade)

        for s in self.stars:
            s[2] -= s[3]
            if s[2] <= 4:
                s[0] = _randi(-160, 160)
                s[1] = _randi(-160, 160)
                s[2] = 180
                s[3] = _randi(1, 3)
                s[4] = -1
                s[5] = -1

            z = s[2]
            sx = CX + (s[0] * 96) // z
            sy = CY + (s[1] * 96) // z
            if 0 <= sx < W and 12 <= sy < H:
                shade = 2 + ((180 - z) >> 3)
                if shade > 15:
                    shade = 15
                if s[4] >= 0 and 0 <= s[4] < W and 12 <= s[5] < H:
                    self.d.line(s[4], s[5], sx, sy, shade - 1 if shade > 1 else 1)
                self.d.pixel(sx, sy, shade)
                s[4] = sx
                s[5] = sy
            else:
                s[4] = -1
                s[5] = -1

        self._draw_hud()
        self.d.show()

    def _draw_plasma(self):
        t = self.frame
        block = 16
        rows = H // block
        cols = W // block
        for by in range(rows):
            y = by * block
            sy = self.sine[(by * 5 + t) & 63]
            for bx in range(cols):
                x = bx * block
                sx = self.sine[(bx * 7 + t * 2) & 63]
                sz = self.sine[((bx + by) * 4 - t * 3) & 63]
                shade = (sx + sy + sz) >> 5
                if shade > 15:
                    shade = 15
                self.d.fill_rect(x, y, block, block, shade)

        # Moving highlight band.
        sweep = (t * 5) % H
        self.d.hline(0, sweep, W, 15)
        self._draw_hud()
        self.d.show()

    def _draw_trails(self):
        # Random erase acts as a decay to keep trails alive but not saturated.
        for _ in range(350):
            self.d.pixel(urandom.getrandbits(9) % W, urandom.getrandbits(9) % H, 0)

        if (self.frame & 31) == 0:
            # A soft reset every ~1s keeps contrast crisp.
            self.d.fill_rect(0, 12, W, H - 12, 0)

        for p in self.trails:
            x0, y0 = p[0], p[1]
            p[0] += p[2]
            p[1] += p[3]

            if p[0] <= 0 or p[0] >= (W - 1):
                p[2] = -p[2]
                p[0] += p[2]
            if p[1] <= 12 or p[1] >= (H - 1):
                p[3] = -p[3]
                p[1] += p[3]

            if (self.frame & 15) == 0:
                p[2] += _randi(-1, 1)
                p[3] += _randi(-1, 1)
                if p[2] == 0:
                    p[2] = 1
                if p[3] == 0:
                    p[3] = -1
                if p[2] > 4:
                    p[2] = 4
                if p[2] < -4:
                    p[2] = -4
                if p[3] > 4:
                    p[3] = 4
                if p[3] < -4:
                    p[3] = -4
                p[4] = _randi(7, 14)

            self.d.line(x0, y0, p[0], p[1], p[4])
            self.d.pixel(p[0], p[1], 15)

        self._draw_hud()
        self.d.show()

    def _draw_mode(self):
        if self.mode == 0:
            self._draw_starfield()
        elif self.mode == 1:
            self._draw_plasma()
        else:
            self._draw_trails()

    def run(self):
        try:
            while True:
                key = self._read_key()
                if not self._handle_key(key):
                    return

                now = utime.ticks_ms()
                if utime.ticks_diff(now, self.mode_started) > AUTO_SWITCH_MS:
                    self._switch_mode(1)

                self._draw_mode()
                self.frame += 1
                if (self.frame & 63) == 0:
                    gc.collect()
                utime.sleep_ms(33)
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            print("Screensaver error:", exc)
            import sys
            sys.print_exception(exc)


def main():
    gc.collect()
    saver = ScreenSaver()
    saver.run()


if __name__ == "__main__":
    main()
