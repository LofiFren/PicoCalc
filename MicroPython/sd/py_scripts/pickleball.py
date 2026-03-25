"""
Pickleball - Simple pickleball paddle game
Features:
- Senior-friendly: wide paddle, slow ball
- Pickleball scoring (first to 11, win by 2)
- Sound effects for hits and points
- LEFT/RIGHT to move, ENTER to serve
- No rush, play at your own pace
"""
import picocalc
import utime
import urandom
import gc
from machine import Pin, PWM

KEY_LEFT = b'\x1b[D'
KEY_RIGHT = b'\x1b[C'
KEY_ESC = b'\x1b\x1b'
KEY_ENTER = b'\r\n'

# Court layout
CL = 10
CR = 310
CT = 24
CB = 306
CW = CR - CL
CH = CB - CT
NET_Y = CT + CH // 2

# Paddles and ball
PAD_W = 70
PAD_H = 6
P_Y = CB - 18
AI_Y = CT + 12
BALL = 8

# Colors
WHITE = 15
BRIGHT = 12
MID = 8
DIM = 5
BLACK = 0

# Score font (5x7 bitmap)
FONT = {
    '0': [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
    '1': [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    '2': [0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F],
    '3': [0x0E, 0x11, 0x01, 0x06, 0x01, 0x11, 0x0E],
    '4': [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
    '5': [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    '6': [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
    '7': [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    '8': [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
    '9': [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
    '-': [0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00],
}


def draw_big(d, text, x, y, color, scale):
    cx = x
    for ch in text:
        if ch == ' ':
            cx += 3 * scale
            continue
        bmp = FONT.get(ch)
        if bmp is None:
            d.text(ch, cx, y, color)
            cx += 8
            continue
        for row in range(7):
            bits = bmp[row]
            for col in range(5):
                if bits & (0x10 >> col):
                    d.fill_rect(cx + col * scale, y + row * scale,
                                scale, scale, color)
        cx += 6 * scale
    return cx - x


def txt_w(text, scale):
    w = 0
    for ch in text:
        w += 3 * scale if ch == ' ' else 6 * scale
    return w


class Sound:
    def __init__(self):
        self.l = PWM(Pin(28))
        self.r = PWM(Pin(27))
        self.on = True

    def _t(self, f, ms, v=0.15):
        if not self.on:
            return
        d = int(32768 * v)
        self.l.freq(f)
        self.r.freq(f)
        self.l.duty_u16(d)
        self.r.duty_u16(d)
        utime.sleep_ms(ms)
        self.l.duty_u16(0)
        self.r.duty_u16(0)

    def hit(self):
        self._t(700, 15)

    def wall(self):
        self._t(400, 10, 0.08)

    def point(self):
        self._t(523, 50)
        self._t(659, 50)
        self._t(784, 80)

    def lose(self):
        self._t(300, 80, 0.10)
        self._t(200, 120, 0.10)

    def win(self):
        for f in [523, 659, 784, 1047]:
            self._t(f, 70)
        utime.sleep_ms(40)
        self._t(1047, 150)

    def serve(self):
        self._t(500, 15)

    def cleanup(self):
        self.l.duty_u16(0)
        self.r.duty_u16(0)


class Pickleball:
    def __init__(self):
        self.d = picocalc.display
        self.kb = bytearray(10)
        self.snd = Sound()

        self.p_score = 0
        self.ai_score = 0
        self.p_x = 160 - PAD_W // 2
        self.ai_x = 160 - PAD_W // 2

        self.bx = 160.0
        self.by = 160.0
        self.bdx = 0.0
        self.bdy = 0.0

        self.state = "TITLE"
        self.serving = True
        self.msg = ""
        self._sc_dirty = True

    def _reset_ball(self):
        if self.serving:
            self.bx = float(self.p_x + PAD_W // 2 - BALL // 2)
            self.by = float(P_Y - BALL - 4)
        else:
            self.bx = float(self.ai_x + PAD_W // 2 - BALL // 2)
            self.by = float(AI_Y + PAD_H + 4)
        self.bdx = 0.0
        self.bdy = 0.0

    def _do_serve(self):
        self.bdy = -2.5 if self.serving else 2.5
        self.bdx = float((urandom.getrandbits(2) % 3) - 1)
        self.snd.serve()

    def _input(self):
        if not picocalc.terminal:
            return None
        c = picocalc.terminal.readinto(self.kb)
        if not c:
            return None
        k = bytes(self.kb[:c])
        if k == KEY_ESC:
            return "X"
        if self.state == "TITLE":
            if k == KEY_ENTER or (c == 1 and self.kb[0] == ord(' ')):
                return "GO"
        elif self.state == "SERVE":
            if k == KEY_LEFT:
                return "L"
            if k == KEY_RIGHT:
                return "R"
            if k == KEY_ENTER or (c == 1 and self.kb[0] == ord(' ')):
                return "HIT"
        elif self.state == "PLAY":
            if k == KEY_LEFT:
                return "L"
            if k == KEY_RIGHT:
                return "R"
            if c == 1 and self.kb[0] in (ord('s'), ord('S')):
                self.snd.on = not self.snd.on
        elif self.state == "POINT":
            return "NXT"
        elif self.state == "OVER":
            if k == KEY_ENTER or (c == 1 and self.kb[0] == ord(' ')):
                return "AGAIN"
        return None

    def _move_p(self, lr):
        spd = 10
        if lr == "L":
            self.p_x = max(CL + 2, self.p_x - spd)
        else:
            self.p_x = min(CR - PAD_W - 2, self.p_x + spd)

    def _update_ball(self):
        self.bx += self.bdx
        self.by += self.bdy

        # Wall bounces
        if self.bx <= CL + 1:
            self.bx = float(CL + 1)
            self.bdx = abs(self.bdx)
            self.snd.wall()
        elif self.bx + BALL >= CR - 1:
            self.bx = float(CR - BALL - 1)
            self.bdx = -abs(self.bdx)
            self.snd.wall()

        bxi = int(self.bx)
        byi = int(self.by)

        # Player paddle hit
        if self.bdy > 0 and byi + BALL >= P_Y and byi + BALL <= P_Y + PAD_H + 5:
            if bxi + BALL > self.p_x and bxi < self.p_x + PAD_W:
                self.by = float(P_Y - BALL)
                self.bdy = -abs(self.bdy)
                hit = (self.bx + BALL / 2 - self.p_x) / PAD_W
                self.bdx = (hit - 0.5) * 5.0
                if abs(self.bdy) < 4.0:
                    self.bdy = -(abs(self.bdy) + 0.12)
                self.snd.hit()
                return

        # AI paddle hit
        if self.bdy < 0 and byi <= AI_Y + PAD_H and byi >= AI_Y - 5:
            if bxi + BALL > self.ai_x and bxi < self.ai_x + PAD_W:
                self.by = float(AI_Y + PAD_H)
                self.bdy = abs(self.bdy)
                hit = (self.bx + BALL / 2 - self.ai_x) / PAD_W
                self.bdx = (hit - 0.5) * 5.0
                if abs(self.bdy) < 4.0:
                    self.bdy = abs(self.bdy) + 0.12
                self.snd.hit()
                return

        # Score check
        if byi < CT - 15:
            self.p_score += 1
            self._sc_dirty = True
            self.serving = True
            self.snd.point()
            self.state = "POINT"
            self.msg = "Your point!"
        elif byi > CB + 15:
            self.ai_score += 1
            self._sc_dirty = True
            self.serving = False
            self.snd.lose()
            self.state = "POINT"
            self.msg = "Opponent scores"

    def _update_ai(self):
        target = self.bx + BALL / 2 - PAD_W / 2
        diff = target - self.ai_x
        spd = 2.5 if self.by < NET_Y else 1.5
        if abs(diff) > 6:
            if diff > 0:
                self.ai_x = min(CR - PAD_W - 2, int(self.ai_x + spd))
            else:
                self.ai_x = max(CL + 2, int(self.ai_x - spd))

    def _game_over(self):
        if self.p_score >= 11 and self.p_score - self.ai_score >= 2:
            return "WIN"
        if self.ai_score >= 11 and self.ai_score - self.p_score >= 2:
            return "LOSE"
        return None

    # -- Drawing --

    def _draw_title(self):
        d = self.d
        d.fill(0)
        d.text("P I C K L E B A L L", 56, 25, WHITE)

        # Mini court preview
        d.rect(100, 50, 120, 80, MID)
        for x in range(104, 216, 8):
            d.fill_rect(x, 89, 4, 2, BRIGHT)
        d.fill_rect(130, 58, 40, 4, WHITE)
        d.fill_rect(140, 118, 40, 4, BRIGHT)
        d.fill_rect(155, 82, 6, 6, WHITE)

        d.hline(30, 145, 260, DIM)
        d.text("HOW TO PLAY:", 104, 160, WHITE)
        d.text("LEFT / RIGHT = move paddle", 28, 182, BRIGHT)
        d.text("ENTER = serve the ball", 44, 200, BRIGHT)
        d.text("Hit ball past your opponent!", 28, 218, BRIGHT)
        d.text("First to 11 wins (by 2)", 44, 236, BRIGHT)
        d.hline(30, 258, 260, DIM)
        d.text("S = toggle sound  ESC = quit", 28, 272, MID)
        d.text("Press ENTER to play!", 76, 302, WHITE)
        d.show()

    def _draw_score_bar(self):
        if not self._sc_dirty:
            return
        d = self.d
        d.fill_rect(0, 0, 320, 20, BLACK)
        d.text("YOU: " + str(self.p_score), 20, 6, WHITE)
        d.text("OPP: " + str(self.ai_score), 220, 6, BRIGHT)
        d.text("-", 156, 6, MID)
        self._sc_dirty = False

    def _draw_court_bg(self):
        d = self.d
        d.fill(0)
        self._sc_dirty = True
        self._draw_score_bar()
        d.rect(CL - 1, CT - 1, CW + 2, CH + 2, DIM)
        for x in range(CL + 2, CR - 2, 8):
            d.fill_rect(x, NET_Y, 4, 2, MID)
        d.text("LEFT/RIGHT move  ENTER serve", 24, 312, DIM)
        d.show()

    def _draw_frame(self):
        d = self.d
        # Clear court interior
        d.fill_rect(CL, CT, CW, CH, BLACK)
        # Net
        for x in range(CL + 2, CR - 2, 8):
            d.fill_rect(x, NET_Y, 4, 2, MID)
        # Paddles
        d.fill_rect(self.p_x, P_Y, PAD_W, PAD_H, WHITE)
        d.fill_rect(self.ai_x, AI_Y, PAD_W, PAD_H, BRIGHT)
        # Ball
        bxi, byi = int(self.bx), int(self.by)
        if CT - BALL <= byi <= CB + BALL:
            d.fill_rect(bxi, byi, BALL, BALL, WHITE)
        # Score
        self._draw_score_bar()
        # Serve prompt
        if self.state == "SERVE":
            if self.serving:
                d.text("ENTER to serve", 100, NET_Y + 20, MID)
            else:
                d.text("ENTER to receive", 92, NET_Y - 28, MID)
        d.show()

    def _draw_point_msg(self):
        d = self.d
        w = len(self.msg) * 8 + 24
        x = (320 - w) // 2
        d.fill_rect(x, NET_Y - 14, w, 28, BLACK)
        d.rect(x, NET_Y - 14, w, 28, BRIGHT)
        d.text(self.msg, x + 12, NET_Y - 6, WHITE)
        d.show()

    def _draw_over(self):
        d = self.d
        d.fill(0)
        if self.p_score > self.ai_score:
            d.text("YOU WIN!", 116, 40, WHITE)
        else:
            d.text("GAME OVER", 112, 40, BRIGHT)
        sc = str(self.p_score) + " - " + str(self.ai_score)
        tw = txt_w(sc, 7)
        draw_big(d, sc, (320 - tw) // 2, 80, WHITE, 7)
        d.text("YOU", 80, 145, WHITE)
        d.text("OPP", 200, 145, BRIGHT)
        if self.p_score > self.ai_score:
            d.text("Great game!", 112, 185, WHITE)
        else:
            d.text("Good effort! Try again!", 52, 185, BRIGHT)
        d.hline(40, 220, 240, DIM)
        d.text("ENTER = play again", 80, 250, WHITE)
        d.text("ESC = quit", 112, 275, MID)
        d.show()

    # -- Main loop --

    def run(self):
        try:
            self._draw_title()

            while True:
                t0 = utime.ticks_ms()
                act = self._input()

                if act == "X":
                    break

                if self.state == "TITLE":
                    if act == "GO":
                        self.state = "SERVE"
                        self.serving = True
                        self._reset_ball()
                        self._draw_court_bg()
                        self._draw_frame()

                elif self.state == "SERVE":
                    if act in ("L", "R"):
                        self._move_p(act)
                        if self.serving:
                            self._reset_ball()
                        self._draw_frame()
                    elif act == "HIT":
                        self._do_serve()
                        self.state = "PLAY"

                elif self.state == "PLAY":
                    if act in ("L", "R"):
                        self._move_p(act)
                    self._update_ball()
                    if self.state == "PLAY":
                        self._update_ai()
                    self._draw_frame()
                    if self.state == "POINT":
                        self._draw_point_msg()
                        result = self._game_over()
                        if result:
                            utime.sleep_ms(800)
                            if result == "WIN":
                                self.snd.win()
                            self.state = "OVER"
                            self._draw_over()

                elif self.state == "POINT":
                    if act == "NXT":
                        self.state = "SERVE"
                        self._reset_ball()
                        self._draw_court_bg()
                        self._draw_frame()

                elif self.state == "OVER":
                    if act == "AGAIN":
                        self.p_score = 0
                        self.ai_score = 0
                        self.p_x = 160 - PAD_W // 2
                        self.ai_x = 160 - PAD_W // 2
                        self.serving = True
                        self._sc_dirty = True
                        self.state = "SERVE"
                        self._reset_ball()
                        self._draw_court_bg()
                        self._draw_frame()

                # Frame timing (~30fps)
                el = utime.ticks_diff(utime.ticks_ms(), t0)
                dl = max(1, 33 - el)
                utime.sleep_ms(dl)

        except KeyboardInterrupt:
            pass

        self.snd.cleanup()


def main():
    gc.collect()
    try:
        print("Free memory:", gc.mem_free(), "bytes")
        game = Pickleball()
        game.run()
    except Exception as e:
        print("Error:", e)
        import sys
        sys.print_exception(e)


if __name__ == "__main__":
    main()
