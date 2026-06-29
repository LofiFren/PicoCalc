# picocalc-app: Strudel Basics | Music | learn to make beats (interactive)
# strudel_demo.py - an interactive, color tutorial for the PicoCalc Strudel port.
#
# Walks through the mini-notation basics one lesson at a time: shows the pattern
# (syntax-colored), plays it on a loop, and animates a rhythm timeline so you can
# SEE where each hit lands while you HEAR it. Reuses the color themes and the
# non-blocking sequencer, so it looks and sounds like Strudel Live.
#
# Keys:  < / >  (or up/down) change lesson    Space  play / pause
#        Ctrl-T  theme    Esc  exit

import sys
if "/sd/py_scripts" not in sys.path:
    sys.path.append("/sd/py_scripts")

import utime
import gc
import picocalc
import strudel
from strudel_live import (
    THEMES, _apply_lut, _ORIG_LUT, _char_color,
    BG, FG, OP, NUM, REST, HBG, HFG, BAR, BARBG, PLAY, LINE, LN, CUR, DOT,
)

# Each lesson: a title, a pattern (uses the bd/sd/hh/cp kit), 2-4 explanation
# lines (kept short to fit), and an optional cps (cycles per second).
LESSONS = [
    {"t": "1. A Sequence", "c": "bd sd hh cp", "cps": 0.5, "x": [
        "Type drum sounds in a row.",
        "One bar splits evenly:",
        "bd sd hh cp = 4 even beats.",
        "bd=kick sd=snare hh=hat cp=clap"]},
    {"t": "2. Rests  ~", "c": "bd ~ sd ~", "cps": 0.5, "x": [
        "The ~ symbol means silence.",
        "Use it to leave gaps:",
        "kick, rest, snare, rest."]},
    {"t": "3. Repeat  *", "c": "bd*4 , hh*8", "cps": 0.5, "x": [
        "* repeats a sound, faster.",
        "bd*4 = four kicks.",
        "hh*8 = eight hi-hats.",
        "The comma , stacks layers."]},
    {"t": "4. Groups  [ ]", "c": "bd [sd sd] hh ~", "cps": 0.5, "x": [
        "[ ] squeezes sounds into one",
        "slot, so they play twice as",
        "fast, together."]},
    {"t": "5. Alternate  < >", "c": "<bd cp> sd hh", "cps": 0.5, "x": [
        "< > plays a different one each",
        "bar: bd, then cp, then bd...",
        "Watch the first hit change."]},
    {"t": "6. Euclid  (k,n)", "c": "bd(3,8) , hh*8", "cps": 0.5, "x": [
        "Spread k hits over n steps,",
        "evenly. bd(3,8) is the",
        "classic 'tresillo' groove."]},
    {"t": "7. Slow  /", "c": "hh*8 , bd/2 , ~ sd", "cps": 0.5, "x": [
        "/ makes a sound play less",
        "often. bd/2 = every 2nd bar.",
        "Good for big, slow kicks."]},
    {"t": "8. Build a Beat", "c": "bd*4 , ~ sd ~ sd , hh*8 , ~ ~ ~ cp", "cps": 0.52, "x": [
        "Stack layers with commas:",
        "kicks + backbeat snare +",
        "hats + a clap = a groove!"]},
    {"t": "9. Your Turn!", "c": "bd*4 , ~ sd ~ sd , hh(5,8) , ~ cp", "cps": 0.55, "x": [
        "Mix these tricks together.",
        "Then open STRUDEL LIVE and",
        "make your own. Have fun!"]},
]

HDR_H = 18
TITLE_Y = HDR_H + 4
CODE_Y = 44
TL_Y = 80
BEAT_Y = TL_Y + 22
EXP_Y = 122


class Tutorial:
    def __init__(self):
        self.d = picocalc.display
        self.W = self.d.width
        self.key_buf = bytearray(16)
        self.seq = strudel.Sequencer(cps=0.5)
        self.theme = 0
        self.idx = 0
        self.playing = True
        self.dirty = True
        self.running = True

    # ----- lesson / sequencer --------------------------------------------
    def _load_lesson(self):
        L = LESSONS[self.idx]
        self.seq.set_cps(L.get("cps", 0.5))
        self.seq.stop()
        self.seq.node = None        # force immediate (not next-cycle) swap
        self.seq.pending = None
        self.seq.set_code(L["c"])
        if self.playing:
            self.seq.start()
        self.dirty = True

    # ----- input ---------------------------------------------------------
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
        elif k in ("LEFT", "UP", ord(","), ord("<")):
            self.idx = (self.idx - 1) % len(LESSONS)
            self._load_lesson()
        elif k in ("RIGHT", "DOWN", ord("."), ord(">")):
            self.idx = (self.idx + 1) % len(LESSONS)
            self._load_lesson()
        elif k == 0x20:                       # Space -> play / pause
            self.playing = not self.playing
            if self.playing:
                self.seq.start()
            else:
                self.seq.stop()
            self.dirty = True
        elif k == 0x14:                       # Ctrl-T -> theme
            self.theme = (self.theme + 1) % len(THEMES)
            _apply_lut(THEMES[self.theme]["cols"])
            self.dirty = True

    # ----- drawing -------------------------------------------------------
    def _draw_code(self, x, y, text):
        i, n, cx = 0, len(text), x
        while i < n:
            col = _char_color(text[i])
            j = i
            while j < n and _char_color(text[j]) == col:
                j += 1
            self.d.text(text[i:j], cx, y, col)
            cx += (j - i) * 6
            i = j

    def _draw_timeline(self):
        d = self.d
        x0, w = 10, self.W - 20
        d.fill_rect(0, TL_Y - 2, self.W, 23, BG)
        for bt in range(4):                   # beat ticks
            d.vline(x0 + bt * w // 4, TL_Y, 12, LINE)
        for o in self.seq.offsets:            # where the hits land this cycle
            d.fill_rect(x0 + int(o * w), TL_Y, 3, 12, DOT)
        ph = self.seq.phase()                 # sweeping playhead
        d.vline(x0 + int(ph * w), TL_Y - 2, 16, PLAY)
        fill = int(ph * w)
        d.fill_rect(x0, TL_Y + 16, fill, 4, BAR)
        d.fill_rect(x0 + fill, TL_Y + 16, w - fill, 4, BARBG)

    def _draw_static(self):
        d = self.d
        L = LESSONS[self.idx]
        th = THEMES[self.theme]
        d.beginDraw()
        d.fill(BG)

        # header
        d.fill_rect(0, 0, self.W, HDR_H, HBG)
        d.text("Strudel Basics", 6, 5, HFG)
        right = "%d/%d  [%s]" % (self.idx + 1, len(LESSONS), th["name"])
        d.text(right, self.W - len(right) * 6 - 6, 5, HFG)

        # title banner + play state
        d.fill_rect(0, HDR_H + 2, self.W, 12, BARBG)
        d.text(L["t"], 8, TITLE_Y, OP)
        tag = "PLAYING" if self.playing else "PAUSED"
        d.text(tag, self.W - len(tag) * 6 - 6, TITLE_Y, PLAY if self.playing else REST)

        # code panel
        d.fill_rect(8, CODE_Y - 5, self.W - 16, 20, BARBG)
        d.rect(8, CODE_Y - 5, self.W - 16, 20, OP)
        self._draw_code(16, CODE_Y, L["c"])

        # rhythm timeline + beat numbers
        self._draw_timeline()
        x0, w = 10, self.W - 20
        for bt in range(4):
            d.text(str(bt + 1), x0 + bt * w // 4 - 2, BEAT_Y, LN)

        # explanation
        d.text("What it does:", 8, EXP_Y - 16, DOT)
        for i in range(len(L["x"])):
            d.text(L["x"][i], 10, EXP_Y + i * 12, FG)

        # lesson progress dots
        py = 210
        n = len(LESSONS)
        gap = 12
        ox = (self.W - (n - 1) * gap) // 2
        for i in range(n):
            col = PLAY if i == self.idx else LINE
            d.fill_rect(ox + i * gap - 2, py, 4, 4, col)

        # footer
        d.hline(0, 292, self.W, LINE)
        d.text("< >  lesson      Space  play/pause", 6, 296, REST)
        d.text("Ctrl-T  theme         Esc  exit", 6, 307, REST)
        d.show()

    # ----- loop ----------------------------------------------------------
    def run(self):
        _apply_lut(THEMES[self.theme]["cols"])
        self._load_lesson()
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
                    self._draw_timeline()
                    self.d.show()
                self.seq.tick()
                utime.sleep_ms(10)
        finally:
            self.seq.stop()
            strudel.shutdown()
            _apply_lut(_ORIG_LUT, swapped=True)
            self.d.beginDraw()
            self.d.fill(0)
            self.d.show()


def main():
    gc.collect()
    try:
        Tutorial().run()
    except Exception as e:
        sys.print_exception(e)
        try:
            _apply_lut(_ORIG_LUT, swapped=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
