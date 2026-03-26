"""
Tennis Timer - Tennis-themed countdown timer for drills and practice
Features:
- Big scoreboard countdown with tennis court background
- Presets for 30s, 1m, 2m, and 5m
- ENTER/SPACE start or pause, LEFT/RIGHT change preset
- UP/DOWN add or subtract 15 seconds while paused
- Animated tennis ball and finish buzzer
"""

import gc
import picocalc
import utime
from machine import Pin, PWM

KEY_UP = b"\x1b[A"
KEY_DOWN = b"\x1b[B"
KEY_LEFT = b"\x1b[D"
KEY_RIGHT = b"\x1b[C"
KEY_ESC = b"\x1b\x1b"
KEY_ENTER = b"\r\n"

AUDIO_LEFT = 28
AUDIO_RIGHT = 27

BLACK = 0
DARK = 3
MID = 7
LIGHT = 11
WHITE = 15

COURT_X = 20
COURT_Y = 46
COURT_W = 280
COURT_H = 176
NET_Y = COURT_Y + COURT_H // 2

PRESETS = [30, 60, 120, 300]

FONT = {
    "0": [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
    "1": [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "2": [0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F],
    "3": [0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E],
    "4": [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
    "5": [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    "6": [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
    "7": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    "8": [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
    "9": [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
    ":": [0x00, 0x04, 0x04, 0x00, 0x04, 0x04, 0x00],
}


def draw_big(display, text, x, y, color, scale):
    cx = x
    for ch in text:
        bmp = FONT.get(ch)
        if bmp is None:
            cx += 4 * scale
            continue
        for row in range(7):
            bits = bmp[row]
            for col in range(5):
                if bits & (0x10 >> col):
                    display.fill_rect(
                        cx + col * scale,
                        y + row * scale,
                        scale,
                        scale,
                        color,
                    )
        cx += 6 * scale


def text_width(text, scale):
    return len(text) * 6 * scale


class TennisSound:
    def __init__(self):
        self.left = PWM(Pin(AUDIO_LEFT))
        self.right = PWM(Pin(AUDIO_RIGHT))
        self.enabled = True

    def _tone(self, freq, ms, volume=0.12):
        if not self.enabled:
            return
        duty = int(65535 * volume)
        self.left.freq(freq)
        self.right.freq(freq)
        self.left.duty_u16(duty)
        self.right.duty_u16(duty)
        utime.sleep_ms(ms)
        self.left.duty_u16(0)
        self.right.duty_u16(0)

    def start(self):
        self._tone(880, 25)

    def pause(self):
        self._tone(540, 18)

    def warning(self):
        self._tone(720, 16, 0.09)

    def done(self):
        self._tone(988, 55)
        self._tone(1318, 70)
        self._tone(1760, 120)

    def cleanup(self):
        self.left.duty_u16(0)
        self.right.duty_u16(0)


class TennisTimer:
    def __init__(self):
        self.d = picocalc.display
        self.key_buf = bytearray(12)
        self.sound = TennisSound()
        self.preset_index = 1
        self.total_ms = PRESETS[self.preset_index] * 1000
        self.remaining_ms = self.total_ms
        self.state = "READY"
        self.last_tick_ms = utime.ticks_ms()
        self.last_warn_second = -1
        self.ball_x = COURT_X + 30
        self.ball_y = COURT_Y + 36
        self.ball_dx = 3
        self.ball_dy = 2
        self.flash = 0

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

    def _format_time(self):
        total_seconds = (self.remaining_ms + 999) // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return "%02d:%02d" % (minutes, seconds)

    def _sync_preset(self):
        self.total_ms = PRESETS[self.preset_index] * 1000
        self.remaining_ms = self.total_ms
        self.last_warn_second = -1

    def _set_custom(self, seconds):
        if seconds < 15:
            seconds = 15
        if seconds > 599:
            seconds = 599
        self.total_ms = seconds * 1000
        self.remaining_ms = self.total_ms
        self.last_warn_second = -1

    def _change_preset(self, delta):
        self.preset_index = (self.preset_index + delta) % len(PRESETS)
        self._sync_preset()
        self.state = "READY"

    def _adjust_time(self, delta_seconds):
        seconds = (self.remaining_ms + 999) // 1000
        self._set_custom(seconds + delta_seconds)
        self.state = "READY"

    def _toggle_running(self):
        now = utime.ticks_ms()
        if self.state == "RUNNING":
            self.state = "PAUSED"
            self.sound.pause()
            return
        if self.remaining_ms <= 0:
            self.remaining_ms = self.total_ms
            self.last_warn_second = -1
        self.state = "RUNNING"
        self.last_tick_ms = now
        self.sound.start()

    def _reset(self):
        self.remaining_ms = self.total_ms
        self.last_warn_second = -1
        self.state = "READY"

    def _handle_key(self, key):
        if not key:
            return True
        if key == KEY_ESC:
            return False
        if key in (KEY_ENTER,) or key == b" ":
            self._toggle_running()
            return True
        if self.state != "RUNNING":
            if key == KEY_LEFT:
                self._change_preset(-1)
            elif key == KEY_RIGHT:
                self._change_preset(1)
            elif key == KEY_UP:
                self._adjust_time(15)
            elif key == KEY_DOWN:
                self._adjust_time(-15)
        if len(key) == 1:
            if key[0] in (ord("r"), ord("R")):
                self._reset()
            elif key[0] in (ord("s"), ord("S")):
                self.sound.enabled = not self.sound.enabled
        elif len(key) >= 1 and key[0] == 0x1B and key not in (KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT):
            return False
        return True

    def _update_timer(self):
        if self.state != "RUNNING":
            return
        now = utime.ticks_ms()
        delta = utime.ticks_diff(now, self.last_tick_ms)
        self.last_tick_ms = now
        self.remaining_ms -= delta
        if self.remaining_ms <= 0:
            self.remaining_ms = 0
            self.state = "DONE"
            self.flash = 18
            self.sound.done()
            return
        remaining_seconds = (self.remaining_ms + 999) // 1000
        if remaining_seconds <= 3 and remaining_seconds != self.last_warn_second:
            self.last_warn_second = remaining_seconds
            self.sound.warning()

    def _update_ball(self):
        speed = 2 if self.state != "RUNNING" else 3 + ((self.total_ms - self.remaining_ms) // 5000) % 2
        dx = speed if self.ball_dx > 0 else -speed
        dy = max(1, speed - 1) if self.ball_dy > 0 else -max(1, speed - 1)
        self.ball_x += dx
        self.ball_y += dy
        self.ball_dx = dx
        self.ball_dy = dy

        if self.ball_x <= COURT_X + 8:
            self.ball_x = COURT_X + 8
            self.ball_dx = abs(self.ball_dx)
        elif self.ball_x >= COURT_X + COURT_W - 14:
            self.ball_x = COURT_X + COURT_W - 14
            self.ball_dx = -abs(self.ball_dx)

        if self.ball_y <= COURT_Y + 14:
            self.ball_y = COURT_Y + 14
            self.ball_dy = abs(self.ball_dy)
        elif self.ball_y >= COURT_Y + COURT_H - 14:
            self.ball_y = COURT_Y + COURT_H - 14
            self.ball_dy = -abs(self.ball_dy)

        if NET_Y - 3 <= self.ball_y <= NET_Y + 3:
            self.ball_dy = -self.ball_dy

    def _draw_background(self):
        self.d.beginDraw()
        self.d.fill(BLACK)
        self.d.fill_rect(0, 0, 320, 24, 1)
        self.d.hline(0, 24, 320, MID)
        self.d.text("TENNIS TIMER", 115, 8, WHITE)

        for y in range(25, 320, 12):
            shade = 1 + ((y - 25) // 36)
            if shade > 4:
                shade = 4
            self.d.fill_rect(0, y, 320, 12, shade)

        self.d.fill_rect(COURT_X, COURT_Y, COURT_W, COURT_H, 5)
        self.d.rect(COURT_X, COURT_Y, COURT_W, COURT_H, WHITE)
        self.d.rect(COURT_X + 16, COURT_Y + 16, COURT_W - 32, COURT_H - 32, LIGHT)
        self.d.vline(COURT_X + COURT_W // 2, COURT_Y + 16, COURT_H - 32, LIGHT)
        self.d.hline(COURT_X + 16, NET_Y, COURT_W - 32, WHITE)
        self.d.hline(COURT_X + 40, COURT_Y + 52, COURT_W - 80, LIGHT)
        self.d.hline(COURT_X + 40, COURT_Y + COURT_H - 52, COURT_W - 80, LIGHT)

    def _draw_ball(self):
        bx = self.ball_x
        by = self.ball_y
        self.d.fill_rect(bx - 2, by + 8, 12, 4, DARK)
        self.d.fill_rect(bx, by, 8, 8, WHITE)
        self.d.pixel(bx + 1, by + 1, LIGHT)
        self.d.pixel(bx + 6, by + 6, LIGHT)
        self.d.hline(bx + 1, by + 3, 6, MID)
        self.d.vline(bx + 3, by + 1, 6, MID)

    def _draw_timer(self):
        text = self._format_time()
        scale = 6
        width = text_width(text, scale)
        x = (320 - width) // 2
        self.d.fill_rect(24, 234, 272, 58, 1 if self.flash & 1 else 0)
        self.d.rect(24, 234, 272, 58, WHITE if self.flash else LIGHT)
        draw_big(self.d, text, x, 245, WHITE, scale)

    def _draw_status(self):
        label = "READY"
        if self.state == "RUNNING":
            label = "IN PLAY"
        elif self.state == "PAUSED":
            label = "PAUSED"
        elif self.state == "DONE":
            label = "DRILL COMPLETE"

        self.d.fill_rect(74, 28, 172, 14, 0)
        label_x = (320 - len(label) * 6) // 2
        self.d.text(label, label_x, 31, WHITE if self.state != "DONE" else LIGHT)

        preset_text = "PRESET %ds" % PRESETS[self.preset_index]
        custom_seconds = self.total_ms // 1000
        if custom_seconds not in PRESETS:
            preset_text = "CUSTOM %ds" % custom_seconds
        self.d.text(preset_text, 8, 300, LIGHT)
        self.d.text("ENTER start/pause", 116, 300, MID)
        self.d.text("L/R preset U/D +/-15 R reset S sound", 8, 311, MID)

        if self.state == "DONE":
            self.d.fill_rect(54, 120, 212, 22, 1)
            self.d.rect(54, 120, 212, 22, WHITE)
            self.d.text("MATCH POINT. PRESS R TO RESET", 62, 127, WHITE)

    def draw(self):
        self._draw_background()
        self._draw_ball()
        self._draw_timer()
        self._draw_status()
        self.d.show()

    def run(self):
        try:
            while True:
                key = self._read_key()
                if not self._handle_key(key):
                    return
                self._update_timer()
                self._update_ball()
                if self.flash:
                    self.flash -= 1
                self.draw()
                gc.collect()
                utime.sleep_ms(40)
        except KeyboardInterrupt:
            pass
        finally:
            self.sound.cleanup()


def main():
    gc.collect()
    try:
        app = TennisTimer()
        app.run()
    except Exception as e:
        print("Tennis Timer error:", e)
        import sys
        sys.print_exception(e)


if __name__ == "__main__":
    main()
