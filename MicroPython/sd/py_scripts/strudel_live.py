# picocalc-app: Strudel Live | Music | live-code beats, color themes
# strudel_live.py - on-device live-coding UI for the PicoCalc Strudel port.
#
# Milestone 2 of the Strudel-on-PicoCalc port (option C1). Edit a pattern with
# the keyboard and hear it update live, Strudel-style. Each non-empty line is a
# layer; they are stacked together (joined with the mini-notation comma).
#
# Colour: the display runs a 4-bit (16 index) framebuffer through a hardware
# colour LUT. We don't need a colour framebuffer (a 200KB RGB565 buffer won't
# fit / fragments); instead each theme reprograms the 16-entry LUT via
# picocalcdisplay.setLUT, turning the 16 indices into real colours. So themes
# are instant palette swaps and cost no extra RAM. The original LUT is restored
# on exit so the menu/terminal look normal again.
#
# Mini-notation (see strudel.py): bd sd hh ~  [bd sd]  bd*2  bd/2  <bd sd>
#   stack via separate lines,  euclid bd(3,8) / bd(3,8,1).
#
# Keys:
#   type / Backspace / Enter / arrows   edit
#   TAB        evaluate + play (updates at the next cycle, like Ctrl-Enter)
#   Ctrl-K     stop sound
#   Ctrl-T     cycle theme
#   Ctrl-O / Ctrl-P   tempo down / up
#   ESC        exit

import sys
if "/sd/py_scripts" not in sys.path:
    sys.path.append("/sd/py_scripts")

import utime
import gc
import picocalc
import picocalcdisplay
import strudel

# Colour role -> LUT index. The drawing code uses these constants; switching
# theme only changes what colour each index maps to.
BG, FG, OP, NUM, REST, HBG, HFG, BAR, BARBG, PLAY, LINE, LN, CUR, DOT = range(14)

# Each theme: 16 RGB888 values in LUT-index order (roles above, then 2 spares).
THEMES = [
    {"name": "SonicPink", "cols": [
        0x000000, 0xededed, 0xff1493, 0x4c83ff, 0x54636d, 0xff1493, 0x000000,
        0xff1493, 0x1e1e1e, 0xffffff, 0x3a3a3a, 0x54636d, 0xff1493, 0x4c83ff,
        0xffffff, 0xffffff]},
    {"name": "Dracula", "cols": [
        0x282a36, 0xf8f8f2, 0xff79c6, 0xbd93f9, 0x6272a4, 0xbd93f9, 0x282a36,
        0x50fa7b, 0x44475a, 0x8be9fd, 0x44475a, 0x6272a4, 0xf1fa8c, 0xff79c6,
        0xffffff, 0xffffff]},
    {"name": "Monokai", "cols": [
        0x272822, 0xf8f8f2, 0xf92672, 0xae81ff, 0x75715e, 0xf92672, 0x272822,
        0xa6e22e, 0x3e3d32, 0x66d9ef, 0x3e3d32, 0x75715e, 0xe6db74, 0xfd971f,
        0xffffff, 0xffffff]},
    {"name": "Nord", "cols": [
        0x2e3440, 0xd8dee9, 0x88c0d0, 0xb48ead, 0x4c566a, 0x5e81ac, 0xeceff4,
        0xa3be8c, 0x3b4252, 0x88c0d0, 0x434c5e, 0x4c566a, 0xebcb8b, 0x81a1c1,
        0xffffff, 0xffffff]},
    {"name": "Terminal", "cols": [
        0x001100, 0x33ff66, 0x00ffaa, 0x88ff88, 0x117722, 0x003311, 0x66ffaa,
        0x33ff66, 0x002200, 0xaaffcc, 0x115522, 0x229944, 0x66ffaa, 0x00ffaa,
        0xffffff, 0xffffff]},
]

# Original 16 LUT entries (byte-swapped RGB565, as stored in firmware) so we can
# restore the device's default palette on exit.
_ORIG_LUT = [0x0000, 0x0080, 0x0004, 0x0084, 0x1000, 0x1080, 0x1004, 0x18C6,
             0x1084, 0x00F8, 0xE007, 0xE0FF, 0x1F00, 0x1FF8, 0xFF07, 0xFFFF]

OPS = "[]<>(),*/"

# Layout
HDR_H = 18
TR_Y, TR_H = 20, 34
ED_Y = 60
LINE_H = 11
GUTTER = 22
FOOT_Y = 306


def _char_color(ch):
    if ch == "~":
        return REST
    if ch in OPS:
        return OP
    if "0" <= ch <= "9":
        return NUM
    return FG


def _apply_lut(cols, swapped=False):
    # Build the 16-entry LUT and install it. setLUT copies len*2 bytes, so we
    # pass a 32-byte memoryview into a 64-byte buffer to keep the read in-bounds.
    buf = bytearray(64)
    for i in range(16):
        c = cols[i]
        if swapped:
            v = c                      # already a stored LUT value
            buf[i * 2] = v & 0xff
            buf[i * 2 + 1] = v >> 8
        else:
            r, g, b = (c >> 16) & 0xff, (c >> 8) & 0xff, c & 0xff
            v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)   # RGB565
            buf[i * 2] = v >> 8        # big-endian -> byte-swapped on push
            buf[i * 2 + 1] = v & 0xff
    picocalcdisplay.setLUT(memoryview(buf)[0:32])


class LiveCoder:
    def __init__(self):
        self.d = picocalc.display
        self.W = self.d.width
        self.key_buf = bytearray(16)
        self.seq = strudel.Sequencer(cps=0.5)
        self.theme = 0
        self.lines = ["bd*4", "~ sd ~ sd", "hh*8", "~ ~ ~ cp"]
        self.cr = 0
        self.cc = 0
        self.dirty = True
        self.running = True

    # ----- input ----------------------------------------------------------
    def _read_keys(self):
        try:
            count = picocalc.terminal.readinto(self.key_buf)
        except OSError:
            return []
        if not count:
            return []
        b = self.key_buf
        out = []
        i = 0
        while i < count:
            c = b[i]
            if c == 0x1b:
                if i + 1 < count and b[i + 1] == 0x1b:
                    out.append("ESC")
                    i += 2
                    continue
                if i + 2 < count and b[i + 1] == ord("["):
                    m = {65: "UP", 66: "DOWN", 67: "RIGHT", 68: "LEFT"}.get(b[i + 2])
                    if m:
                        out.append(m)
                        i += 3
                        continue
                out.append("ESC")
                i += 1
                continue
            out.append(c)
            i += 1
        return out

    def _handle(self, k):
        if k == "ESC":
            self.running = False
        elif k == "UP":
            self.cr = max(0, self.cr - 1)
            self.cc = min(self.cc, len(self.lines[self.cr]))
            self.dirty = True
        elif k == "DOWN":
            self.cr = min(len(self.lines) - 1, self.cr + 1)
            self.cc = min(self.cc, len(self.lines[self.cr]))
            self.dirty = True
        elif k == "LEFT":
            self.cc = max(0, self.cc - 1)
            self.dirty = True
        elif k == "RIGHT":
            self.cc = min(len(self.lines[self.cr]), self.cc + 1)
            self.dirty = True
        elif k == 0x09:                       # TAB -> evaluate + play
            self._evaluate()
            self.dirty = True
        elif k == 0x0b:                       # Ctrl-K -> stop
            self.seq.stop()
            self.dirty = True
        elif k == 0x14:                       # Ctrl-T -> theme
            self.theme = (self.theme + 1) % len(THEMES)
            _apply_lut(THEMES[self.theme]["cols"])
            self.dirty = True
        elif k == 0x0f:                       # Ctrl-O -> slower
            self.seq.set_cps(self.seq.cps - 0.05)
            self.dirty = True
        elif k == 0x10:                       # Ctrl-P -> faster
            self.seq.set_cps(self.seq.cps + 0.05)
            self.dirty = True
        elif k in (0x08, 0x7f):               # Backspace
            if self.cc > 0:
                ln = self.lines[self.cr]
                self.lines[self.cr] = ln[:self.cc - 1] + ln[self.cc:]
                self.cc -= 1
            elif self.cr > 0:
                self.cc = len(self.lines[self.cr - 1])
                self.lines[self.cr - 1] += self.lines[self.cr]
                del self.lines[self.cr]
                self.cr -= 1
            self.dirty = True
        elif k in (0x0d, 0x0a):               # Enter -> split line
            ln = self.lines[self.cr]
            self.lines[self.cr] = ln[:self.cc]
            self.lines.insert(self.cr + 1, ln[self.cc:])
            self.cr += 1
            self.cc = 0
            self.dirty = True
        elif 0x20 <= k <= 0x7e:               # printable
            ln = self.lines[self.cr]
            self.lines[self.cr] = ln[:self.cc] + chr(k) + ln[self.cc:]
            self.cc += 1
            self.dirty = True

    def _evaluate(self):
        parts = []
        for ln in self.lines:
            s = ln[:strudel._comment_cut(ln)].strip()   # drop // or # comment
            if s:
                parts.append(s)
        code = " , ".join(parts)
        if not code:
            return
        if self.seq.set_code(code) and not self.seq.playing:
            self.seq.start()

    # ----- drawing --------------------------------------------------------
    def _draw_code_line(self, x, y, text):
        cut = strudel._comment_cut(text)
        code, comment = text[:cut], text[cut:]
        i, n, cx = 0, len(code), x
        while i < n:
            col = _char_color(code[i])
            j = i
            while j < n and _char_color(code[j]) == col:
                j += 1
            self.d.text(code[i:j], cx, y, col)
            cx += (j - i) * 6
            i = j
        if comment:                       # render the // or # comment dim
            self.d.text(comment, cx, y, REST)

    def _draw_transport(self):
        d = self.d
        d.fill_rect(0, TR_Y, self.W, TR_H, BG)
        x0, w = 4, self.W - 8
        ph = self.seq.phase()
        for bt in range(4):
            d.vline(x0 + bt * w // 4, TR_Y + 2, 12, LINE)
        for o in self.seq.offsets:
            d.fill_rect(x0 + int(o * w), TR_Y + 2, 2, 12, DOT)
        px = x0 + int(ph * w)
        d.vline(px, TR_Y, 16, PLAY)
        by = TR_Y + 22
        fill = int(ph * w)
        d.fill_rect(x0, by, fill, 5, BAR)
        d.fill_rect(x0 + fill, by, w - fill, 5, BARBG)

    def _draw_static(self):
        d = self.d
        d.beginDraw()
        d.fill(BG)

        d.fill_rect(0, 0, self.W, HDR_H, HBG)
        d.text("strudel", 6, 5, HFG)
        status = "ERR" if self.seq.error else ("PLAY" if self.seq.playing else "STOP")
        right = "%s  cps %.2f  [%s]" % (status, self.seq.cps, THEMES[self.theme]["name"])
        d.text(right, self.W - len(right) * 6 - 6, 5, HFG)

        self._draw_transport()

        for r, ln in enumerate(self.lines):
            y = ED_Y + r * LINE_H
            if y > 278:
                break
            d.text("%2d" % (r + 1), 4, y, LN)
            self._draw_code_line(GUTTER, y, ln)
        cy = ED_Y + self.cr * LINE_H
        cx = GUTTER + self.cc * 6
        d.hline(cx, cy + 9, 6, CUR)

        # footer: two lines, controls spelled out (no cryptic "^K")
        if self.seq.error:
            d.text("parse error: " + self.seq.error[:38], 4, 282, REST)
        d.hline(0, 293, self.W, LINE)
        d.text("Tab=Play   Ctrl-K=Stop   Ctrl-T=Theme", 4, 297, REST)
        d.text("Ctrl-O=Slower   Ctrl-P=Faster   Esc=Exit", 4, 308, REST)
        d.show()

    # ----- loop -----------------------------------------------------------
    def run(self):
        _apply_lut(THEMES[self.theme]["cols"])
        try:
            while self.running:
                for _ in range(3):
                    for k in self._read_keys():
                        self._handle(k)
                        if not self.running:
                            break
                    self.seq.tick()
                if self.dirty:
                    self._draw_static()
                    self.dirty = False
                else:
                    self._draw_transport()
                    self.d.show()
                self.seq.tick()
                utime.sleep_ms(10)
        finally:
            self.seq.stop()
            strudel.shutdown()                    # release audio engine + pins
            _apply_lut(_ORIG_LUT, swapped=True)   # restore default palette
            self.d.beginDraw()
            self.d.fill(0)
            self.d.show()


def main():
    gc.collect()
    try:
        LiveCoder().run()
    except Exception as e:
        sys.print_exception(e)
        try:
            _apply_lut(_ORIG_LUT, swapped=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
