"""
Cartoon Parade - Three cartoon characters take turns in a rotating show
Features:
- Three grayscale cartoon mascots orbit around center stage
- Each character cycles through simple spin poses while moving
- 30-second countdown timer with automatic return to menu
- ESC exits early
"""

import gc
import math
import picocalc
import utime

KEY_ESC = b"\x1b\x1b"
KEY_UP = b"\x1b[A"
KEY_DOWN = b"\x1b[B"
KEY_LEFT = b"\x1b[D"
KEY_RIGHT = b"\x1b[C"

COLOR_BLACK = 0
COLOR_NEAR_BLACK = 1
COLOR_DARK = 4
COLOR_MID = 7
COLOR_LIGHT = 11
COLOR_WHITE = 15

SCREEN_W = 320
SCREEN_H = 320

SHOW_DURATION_MS = 30000
FRAME_MS = 50


class CartoonParade:
    def __init__(self):
        self.d = picocalc.display
        self.key_buf = bytearray(12)
        self.start_ms = utime.ticks_ms()
        self.frame = 0
        self.cx = SCREEN_W // 2
        self.cy = 184
        self.radius_x = 92
        self.radius_y = 42
        self.characters = (
            {"name": "CAT", "shade": 12, "accent": 15, "kind": 0, "phase": 0},
            {"name": "BOT", "shade": 8, "accent": 13, "kind": 1, "phase": 21},
            {"name": "GHO", "shade": 10, "accent": 15, "kind": 2, "phase": 42},
        )
        self.orbit = []
        self._build_orbit_table()

    def _build_orbit_table(self):
        for i in range(64):
            angle = (i * math.pi * 2.0) / 64.0
            ox = int(math.cos(angle) * self.radius_x)
            oy = int(math.sin(angle) * self.radius_y)
            self.orbit.append((ox, oy))

    def _read_key(self):
        if not picocalc.terminal:
            return None
        try:
            count = picocalc.terminal.readinto(self.key_buf)
        except OSError:
            return None
        if not count:
            return None
        return bytes(self.key_buf[:count])

    def _remaining_ms(self):
        elapsed = utime.ticks_diff(utime.ticks_ms(), self.start_ms)
        remaining = SHOW_DURATION_MS - elapsed
        if remaining < 0:
            remaining = 0
        return remaining

    def _draw_background(self):
        self.d.beginDraw()
        self.d.fill(COLOR_BLACK)

        for band in range(11):
            shade = 1 + band
            y = 44 + band * 12
            self.d.fill_rect(0, y, SCREEN_W, 12, shade if shade < 8 else 7)

        self.d.fill_rect(0, 244, SCREEN_W, 76, 3)
        self.d.hline(0, 243, SCREEN_W, 9)

        for ring in range(3):
            rx = 42 + ring * 24
            ry = 16 + ring * 9
            shade = 4 + ring * 3
            self.d.rect(self.cx - rx, self.cy - 30 - ry, rx * 2, ry * 2, shade)

        self.d.fill_rect(0, 0, SCREEN_W, 26, COLOR_NEAR_BLACK)
        self.d.hline(0, 26, SCREEN_W, COLOR_MID)
        self.d.text("CARTOON PARADE", 92, 8, COLOR_WHITE)
        self.d.text("ESC exit", 8, 300, COLOR_MID)

    def _draw_timer(self, remaining_ms):
        secs = (remaining_ms + 999) // 1000
        self.d.fill_rect(226, 5, 88, 16, COLOR_NEAR_BLACK)
        self.d.text("%2ds LEFT" % secs, 234, 8, COLOR_LIGHT)

    def _draw_shadow(self, x, y, w, h):
        self.d.fill_rect(x + 4, y + h - 2, w - 8, 5, 2)
        self.d.rect(x + 6, y + h - 1, w - 12, 3, 4)

    def _draw_face(self, x, y, facing, eye_y, eye_gap, mouth_y):
        if facing == 0:
            self.d.fill_rect(x + 8, y + eye_y, 4, 4, COLOR_WHITE)
            self.d.fill_rect(x + 18, y + eye_y, 4, 4, COLOR_WHITE)
            self.d.pixel(x + 9, y + eye_y + 1, COLOR_BLACK)
            self.d.pixel(x + 19, y + eye_y + 1, COLOR_BLACK)
            self.d.hline(x + 10, y + mouth_y, 8, COLOR_BLACK)
        elif facing == 1:
            self.d.fill_rect(x + 18, y + eye_y, 4, 4, COLOR_WHITE)
            self.d.pixel(x + 19, y + eye_y + 1, COLOR_BLACK)
            self.d.vline(x + 12, y + mouth_y - 1, 6, COLOR_BLACK)
            self.d.pixel(x + 14, y + mouth_y + 3, COLOR_BLACK)
        elif facing == 2:
            self.d.fill_rect(x + 8, y + eye_y, 4, 4, COLOR_WHITE)
            self.d.fill_rect(x + 18, y + eye_y, 4, 4, COLOR_WHITE)
            self.d.hline(x + 10, y + mouth_y + 1, 8, COLOR_BLACK)
            self.d.pixel(x + 12, y + mouth_y - 1, COLOR_BLACK)
            self.d.pixel(x + 15, y + mouth_y - 1, COLOR_BLACK)
        else:
            self.d.fill_rect(x + 8, y + eye_y, 4, 4, COLOR_WHITE)
            self.d.pixel(x + 9, y + eye_y + 1, COLOR_BLACK)
            self.d.vline(x + 17, y + mouth_y - 1, 6, COLOR_BLACK)
            self.d.pixel(x + 15, y + mouth_y + 3, COLOR_BLACK)

    def _draw_cat(self, x, y, facing, shade, accent, bob):
        y += bob
        self._draw_shadow(x, y, 32, 48)
        self.d.fill_rect(x + 6, y + 8, 20, 22, shade)
        self.d.fill_rect(x + 8, y + 30, 16, 12, shade - 2 if shade > 3 else shade)
        self.d.line(x + 8, y + 8, x + 3, y + 1, shade)
        self.d.line(x + 10, y + 8, x + 7, y + 1, accent)
        self.d.line(x + 24, y + 8, x + 29, y + 1, shade)
        self.d.line(x + 22, y + 8, x + 25, y + 1, accent)
        self.d.rect(x + 6, y + 8, 20, 22, accent)
        self._draw_face(x, y + 2, facing, 14, 10, 24)
        self.d.pixel(x + 15, y + 22, COLOR_BLACK)
        self.d.hline(x + 4, y + 24, 8, COLOR_WHITE)
        self.d.hline(x + 20, y + 24, 8, COLOR_WHITE)
        if facing == 0:
            self.d.line(x + 24, y + 30, x + 31, y + 20, accent)
            self.d.line(x + 23, y + 31, x + 31, y + 25, accent)
        elif facing == 1:
            self.d.line(x + 24, y + 31, x + 31, y + 31, accent)
            self.d.line(x + 24, y + 33, x + 30, y + 36, accent)
        elif facing == 2:
            self.d.line(x + 8, y + 31, x + 1, y + 23, accent)
            self.d.line(x + 9, y + 33, x + 2, y + 29, accent)
        else:
            self.d.line(x + 8, y + 31, x + 1, y + 31, accent)
            self.d.line(x + 8, y + 33, x + 2, y + 36, accent)
        self.d.fill_rect(x + 9, y + 42, 4, 6, 9)
        self.d.fill_rect(x + 19, y + 42, 4, 6, 9)

    def _draw_robot(self, x, y, facing, shade, accent, bob):
        y += bob
        self._draw_shadow(x, y, 32, 48)
        self.d.rect(x + 6, y + 6, 20, 18, accent)
        self.d.fill_rect(x + 7, y + 7, 18, 16, shade)
        self.d.vline(x + 16, y + 2, 6, accent)
        self.d.fill_rect(x + 14, y, 4, 3, COLOR_WHITE)
        if facing == 0:
            self.d.fill_rect(x + 10, y + 12, 4, 4, COLOR_WHITE)
            self.d.fill_rect(x + 18, y + 12, 4, 4, COLOR_WHITE)
            self.d.hline(x + 10, y + 19, 12, COLOR_BLACK)
        elif facing == 1:
            self.d.fill_rect(x + 18, y + 12, 4, 4, COLOR_WHITE)
            self.d.vline(x + 14, y + 11, 7, COLOR_BLACK)
            self.d.pixel(x + 19, y + 13, COLOR_BLACK)
        elif facing == 2:
            self.d.fill_rect(x + 10, y + 12, 4, 4, COLOR_WHITE)
            self.d.fill_rect(x + 18, y + 12, 4, 4, COLOR_WHITE)
            self.d.hline(x + 10, y + 20, 12, COLOR_BLACK)
            self.d.vline(x + 16, y + 18, 3, COLOR_BLACK)
        else:
            self.d.fill_rect(x + 10, y + 12, 4, 4, COLOR_WHITE)
            self.d.vline(x + 18, y + 11, 7, COLOR_BLACK)
            self.d.pixel(x + 11, y + 13, COLOR_BLACK)
        self.d.fill_rect(x + 10, y + 26, 12, 13, shade - 2 if shade > 2 else shade)
        self.d.rect(x + 10, y + 26, 12, 13, accent)
        self.d.line(x + 10, y + 28, x + 4, y + 34, accent)
        self.d.line(x + 22, y + 28, x + 28, y + 34, accent)
        if facing == 1:
            self.d.line(x + 4, y + 34, x + 1, y + 38, COLOR_WHITE)
        elif facing == 3:
            self.d.line(x + 28, y + 34, x + 31, y + 38, COLOR_WHITE)
        self.d.line(x + 12, y + 39, x + 9, y + 47, accent)
        self.d.line(x + 20, y + 39, x + 23, y + 47, accent)

    def _draw_ghost(self, x, y, facing, shade, accent, bob):
        y += bob
        self._draw_shadow(x, y, 32, 48)
        self.d.fill_rect(x + 8, y + 10, 16, 24, shade)
        self.d.fill_rect(x + 10, y + 6, 12, 6, shade)
        self.d.rect(x + 8, y + 10, 16, 24, accent)
        self.d.hline(x + 10, y + 6, 12, accent)
        self._draw_face(x, y + 2, facing, 15, 10, 24)
        self.d.fill_rect(x + 8, y + 34, 4, 8, shade)
        self.d.fill_rect(x + 14, y + 38, 4, 8, shade)
        self.d.fill_rect(x + 20, y + 34, 4, 8, shade)
        self.d.hline(x + 8, y + 42, 16, accent)
        if facing == 0:
            self.d.line(x + 4, y + 16, x + 8, y + 22, accent)
            self.d.line(x + 24, y + 22, x + 28, y + 16, accent)
        elif facing == 1:
            self.d.line(x + 24, y + 18, x + 30, y + 22, accent)
            self.d.line(x + 24, y + 24, x + 29, y + 30, accent)
        elif facing == 2:
            self.d.line(x + 4, y + 18, x + 8, y + 24, accent)
            self.d.line(x + 24, y + 18, x + 28, y + 24, accent)
        else:
            self.d.line(x + 2, y + 22, x + 8, y + 18, accent)
            self.d.line(x + 3, y + 30, x + 8, y + 24, accent)

    def _draw_character(self, char, slot):
        orbit_index = (self.frame + char["phase"]) & 63
        ox, oy = self.orbit[orbit_index]
        x = self.cx - 16 + ox
        y = self.cy - 60 + oy
        bob = ((self.frame + char["phase"]) & 7) - 3
        facing = ((self.frame // 4) + slot) & 3
        scale_hint = 0
        if oy > 0:
            scale_hint = 1
        if oy > 24:
            scale_hint = 2
        x -= scale_hint
        y += scale_hint
        if char["kind"] == 0:
            self._draw_cat(x, y, facing, char["shade"], char["accent"], bob)
        elif char["kind"] == 1:
            self._draw_robot(x, y, facing, char["shade"], char["accent"], bob)
        else:
            self._draw_ghost(x, y, facing, char["shade"], char["accent"], bob)
        self.d.fill_rect(x + 1, y + 54 + bob, 30, 9, COLOR_BLACK)
        self.d.text(char["name"], x + 6, y + 55 + bob, COLOR_LIGHT)

    def draw(self):
        remaining_ms = self._remaining_ms()
        self._draw_background()
        self._draw_timer(remaining_ms)

        self.d.text("3 mascots in a 30s loop", 68, 281, COLOR_LIGHT)
        self.d.text("Auto-return when timer ends", 62, 292, COLOR_MID)

        for slot in range(3):
            index = (slot + (self.frame // 24)) % 3
            self._draw_character(self.characters[index], slot)

        self.d.show()

    def run(self):
        try:
            while True:
                key = self._read_key()
                if key == KEY_ESC:
                    return
                if key and len(key) >= 1 and key[0] == 0x1B and key not in (KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT):
                    return
                if self._remaining_ms() <= 0:
                    return
                self.draw()
                self.frame = (self.frame + 1) & 255
                if (self.frame & 15) == 0:
                    gc.collect()
                utime.sleep_ms(FRAME_MS)
        except KeyboardInterrupt:
            pass


def main():
    gc.collect()
    try:
        app = CartoonParade()
        app.run()
    except Exception as e:
        print("Cartoon Parade error:", e)
        import sys
        sys.print_exception(e)


if __name__ == "__main__":
    main()
