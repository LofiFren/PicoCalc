"""
Math Kids - Fun math game for 5 year olds
Features:
- Addition and subtraction with numbers 0-10
- Big friendly numbers easy to read
- Three answer choices (arrow keys to pick)
- Happy sounds for correct, gentle sound for wrong
- Star rewards and streak tracking
- Difficulty adapts: starts easy, grows with streaks
"""
import picocalc
import utime
import urandom
import gc
from machine import Pin, PWM

KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_LEFT = b'\x1b[D'
KEY_RIGHT = b'\x1b[C'
KEY_ESC = b'\x1b\x1b'
KEY_ENTER = b'\r\n'

AUDIO_LEFT = 28
AUDIO_RIGHT = 27

COLOR_BLACK = 0
COLOR_DARK = 4
COLOR_GRAY = 8
COLOR_LIGHT = 12
COLOR_WHITE = 15


def draw_big_char(display, ch, x, y, color, size=4):
    """Draw a character scaled up by size factor."""
    # Render at 1x into a tiny area, then read pixels back
    # Instead, use a simple bitmap font for digits and operators
    pass


# 5x7 bitmap font for digits 0-9 and + - =
# Each digit is 5 columns wide, 7 rows tall, stored as 7 bytes (each byte = 1 row, 5 bits)
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
    '+': [0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00],
    '-': [0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00],
    '=': [0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00],
    '?': [0x0E, 0x11, 0x01, 0x06, 0x04, 0x00, 0x04],
}


def draw_big_text(display, text, x, y, color, scale=4):
    """Draw text using scaled bitmap font. Returns total width drawn."""
    cx = x
    for ch in text:
        if ch == ' ':
            cx += 3 * scale
            continue
        bitmap = FONT.get(ch)
        if bitmap is None:
            # Fall back to built-in tiny font for unknown chars
            display.text(ch, cx, y, color)
            cx += 8
            continue
        for row_idx in range(7):
            row_bits = bitmap[row_idx]
            for col in range(5):
                if row_bits & (0x10 >> col):
                    px = cx + col * scale
                    py = y + row_idx * scale
                    display.fill_rect(px, py, scale, scale, color)
        cx += 6 * scale
    return cx - x


def draw_star(display, cx, cy, size, color):
    """Draw a simple star shape."""
    s = size
    # Diamond + crossbar = star-ish
    half = s // 2
    # Vertical diamond
    for i in range(s):
        w = i if i <= half else s - i
        display.hline(cx - w, cy - half + i, w * 2 + 1, color)
    # Horizontal bar
    display.fill_rect(cx - s, cy - half // 2, s * 2 + 1, half + 1, color)


class MathSound:
    def __init__(self):
        self.audio_left = PWM(Pin(AUDIO_LEFT))
        self.audio_right = PWM(Pin(AUDIO_RIGHT))
        self.enabled = True
        self.volume = 0.25

    def _tone(self, freq, ms, vol=None):
        if not self.enabled:
            return
        v = vol if vol else self.volume
        duty = int(32768 * v)
        self.audio_left.freq(freq)
        self.audio_right.freq(freq)
        self.audio_left.duty_u16(duty)
        self.audio_right.duty_u16(duty)
        utime.sleep_ms(ms)
        self.audio_left.duty_u16(0)
        self.audio_right.duty_u16(0)

    def correct(self):
        """Happy ascending arpeggio."""
        self._tone(523, 60)
        self._tone(659, 60)
        self._tone(784, 60)
        self._tone(1047, 120)

    def wrong(self):
        """Gentle low boop."""
        self._tone(220, 150, 0.15)

    def select(self):
        """Short click when moving selection."""
        self._tone(300, 15, 0.15)

    def level_up(self):
        """Celebration fanfare."""
        self._tone(523, 80)
        self._tone(659, 80)
        self._tone(784, 80)
        self._tone(1047, 80)
        utime.sleep_ms(40)
        self._tone(1047, 200)

    def cleanup(self):
        self.audio_left.duty_u16(0)
        self.audio_right.duty_u16(0)


class MathKids:
    def __init__(self):
        self.display = picocalc.display
        self.W = self.display.width
        self.H = self.display.height
        self.key_buffer = bytearray(10)
        self.sound = MathSound()

        # Game state
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.total_correct = 0
        self.total_asked = 0
        self.level = 1           # 1=easy(+, 0-5), 2=medium(+, 0-10), 3=hard(+-, 0-10)
        self.stars = 0

        # Current problem
        self.num_a = 0
        self.num_b = 0
        self.op = '+'
        self.answer = 0
        self.choices = [0, 0, 0]
        self.selected = 0        # 0, 1, or 2
        self.state = "TITLE"     # TITLE, PLAY, CORRECT, WRONG, LEVELUP
        self.state_timer = 0
        self.feedback_msg = ""

        self._new_problem()

    def _new_problem(self):
        """Generate a new math problem based on level."""
        if self.level == 1:
            # Easy: addition 0-5
            self.num_a = urandom.getrandbits(3) % 6  # 0-5
            self.num_b = urandom.getrandbits(3) % 6
            self.op = '+'
            self.answer = self.num_a + self.num_b
        elif self.level == 2:
            # Medium: addition 0-10
            self.num_a = urandom.getrandbits(4) % 11  # 0-10
            self.num_b = urandom.getrandbits(4) % 11
            self.op = '+'
            self.answer = self.num_a + self.num_b
        else:
            # Hard: addition and subtraction 0-10
            if urandom.getrandbits(1):
                self.op = '+'
                self.num_a = urandom.getrandbits(4) % 11
                self.num_b = urandom.getrandbits(4) % 11
                self.answer = self.num_a + self.num_b
            else:
                self.op = '-'
                # Ensure non-negative result
                self.num_a = urandom.getrandbits(4) % 11
                self.num_b = urandom.getrandbits(4) % (self.num_a + 1)
                self.answer = self.num_a - self.num_b

        # Generate 3 choices: one correct + two wrong
        slot = urandom.getrandbits(2) % 3
        self.choices = [0, 0, 0]
        self.choices[slot] = self.answer

        for i in range(3):
            if i == slot:
                continue
            # Generate a wrong answer that's close but different
            attempts = 0
            while attempts < 20:
                offset = (urandom.getrandbits(3) % 5) + 1  # 1-5
                if urandom.getrandbits(1):
                    offset = -offset
                wrong = self.answer + offset
                if wrong < 0:
                    wrong = self.answer + abs(offset)
                if wrong != self.answer and wrong not in self.choices and wrong >= 0:
                    self.choices[i] = wrong
                    break
                attempts += 1
            else:
                # Fallback
                self.choices[i] = self.answer + (i + 1) * 2

        self.selected = 1  # Start in middle

    def handle_input(self):
        if not picocalc.terminal:
            return None
        count = picocalc.terminal.readinto(self.key_buffer)
        if not count:
            return None
        key = bytes(self.key_buffer[:count])

        if key == KEY_ESC:
            return "EXIT"

        if self.state == "TITLE":
            if key == KEY_ENTER or (count == 1 and self.key_buffer[0] == ord(' ')):
                self.state = "PLAY"
                self._static_drawn = False
                return "REDRAW"
            return None

        if self.state == "PLAY":
            if key == KEY_LEFT:
                if self.selected > 0:
                    self.selected -= 1
                    self.sound.select()
                return "UPDATE_SEL"
            elif key == KEY_RIGHT:
                if self.selected < 2:
                    self.selected += 1
                    self.sound.select()
                return "UPDATE_SEL"
            elif key == KEY_ENTER or (count == 1 and self.key_buffer[0] == ord(' ')):
                return "SUBMIT"

        if self.state in ("CORRECT", "WRONG"):
            # Any key advances after feedback
            return "NEXT"

        if self.state == "LEVELUP":
            return "NEXT"

        return None

    def _check_answer(self):
        self.total_asked += 1
        if self.choices[self.selected] == self.answer:
            self.score += 10
            self.streak += 1
            self.total_correct += 1
            if self.streak > self.best_streak:
                self.best_streak = self.streak
            # Every 5 correct in a row = a star
            if self.streak % 5 == 0:
                self.stars += 1
            # Level up every 10 correct answers if streak >= 3
            if self.total_correct % 10 == 0 and self.level < 3 and self.streak >= 3:
                self.level += 1
                self.state = "LEVELUP"
                self.state_timer = utime.ticks_ms()
                self.sound.level_up()
                return
            self.state = "CORRECT"
            self.state_timer = utime.ticks_ms()
            msgs = ["Great job!", "Awesome!", "You got it!", "Super!", "Yay!", "Nice!"]
            self.feedback_msg = msgs[urandom.getrandbits(3) % len(msgs)]
            self.sound.correct()
        else:
            self.streak = 0
            self.state = "WRONG"
            self.state_timer = utime.ticks_ms()
            self.feedback_msg = str(self.answer)
            self.sound.wrong()

    def _draw_title(self):
        d = self.display
        d.fill(0)

        # Title
        draw_big_text(d, "1+2=3", 52, 30, COLOR_WHITE, 5)

        # Subtitle
        d.text("MATH KIDS", 124, 80, COLOR_WHITE)

        # Stars decoration
        for i in range(5):
            draw_star(d, 60 + i * 50, 120, 8, COLOR_LIGHT)

        # Instructions
        d.text("Learn math the fun way!", 68, 160, COLOR_LIGHT)
        d.text("LEFT/RIGHT = pick answer", 60, 190, COLOR_GRAY)
        d.text("ENTER = check answer", 76, 206, COLOR_GRAY)
        d.text("ESC = quit", 112, 222, COLOR_GRAY)

        # Level info
        lvl_names = ["Easy (0-5 add)", "Medium (0-10 add)", "Hard (add & subtract)"]
        d.text("Level: " + lvl_names[self.level - 1], 60, 255, COLOR_LIGHT)

        # Start prompt
        d.text("Press ENTER to start!", 76, 290, COLOR_WHITE)

        d.show()

    def _draw_problem(self):
        """Draw the full play screen (called once per problem)."""
        d = self.display
        self._static_drawn = True
        d.fill(0)

        # Top bar: score and stars
        d.text("Score:" + str(self.score), 4, 4, COLOR_WHITE)
        streak_txt = "Streak:" + str(self.streak)
        d.text(streak_txt, 180, 4, COLOR_LIGHT)
        # Draw earned stars in top-right
        for i in range(min(self.stars, 5)):
            draw_star(d, 280 + i * 10, 6, 3, COLOR_WHITE)

        # Level indicator
        lvl_txt = ["EASY", "MEDIUM", "HARD"]
        d.text(lvl_txt[self.level - 1], 4, 16, COLOR_GRAY)

        # Separator
        d.hline(0, 28, 320, COLOR_DARK)

        # Problem text - big and centered
        prob = str(self.num_a) + " " + self.op + " " + str(self.num_b) + " = ?"
        # Calculate width: each char is 6*scale pixels, space is 3*scale
        scale = 5
        tw = 0
        for ch in prob:
            tw += 3 * scale if ch == ' ' else 6 * scale
        px = (320 - tw) // 2
        draw_big_text(d, prob, px, 55, COLOR_WHITE, scale)

        # Divider
        d.hline(20, 105, 280, COLOR_DARK)

        # Instruction
        d.text("Pick the answer:", 100, 115, COLOR_GRAY)

        # Draw the three choice boxes
        self._draw_choices(d)

        d.show()

    def _draw_choices(self, d):
        """Draw the three answer choice boxes."""
        box_w = 80
        box_h = 60
        gap = 12
        total_w = box_w * 3 + gap * 2
        start_x = (320 - total_w) // 2
        box_y = 140

        for i in range(3):
            bx = start_x + i * (box_w + gap)
            color = COLOR_WHITE if i == self.selected else COLOR_GRAY
            border = COLOR_WHITE if i == self.selected else COLOR_DARK

            # Box background
            if i == self.selected:
                d.fill_rect(bx, box_y, box_w, box_h, COLOR_DARK)
            else:
                d.fill_rect(bx, box_y, box_w, box_h, 0)

            # Border (thicker for selected)
            d.rect(bx, box_y, box_w, box_h, border)
            if i == self.selected:
                d.rect(bx + 1, box_y + 1, box_w - 2, box_h - 2, border)

            # Number centered in box
            num_str = str(self.choices[i])
            nw = 0
            for ch in num_str:
                nw += 3 * 4 if ch == ' ' else 6 * 4
            nx = bx + (box_w - nw) // 2
            ny = box_y + (box_h - 28) // 2
            draw_big_text(d, num_str, nx, ny, color, 4)

        # Arrow indicators
        arr_y = box_y + box_h + 8
        d.text("<-- LEFT      RIGHT -->", 64, arr_y, COLOR_GRAY)

    def _update_choices_only(self):
        """Redraw just the choice area (avoids full redraw)."""
        d = self.display
        # Clear the choice region
        d.fill_rect(0, 135, 320, 90, 0)
        self._draw_choices(d)
        d.show()

    def _draw_feedback(self):
        """Draw correct/wrong feedback overlay."""
        d = self.display
        # Clear bottom portion for feedback
        d.fill_rect(0, 230, 320, 90, 0)

        if self.state == "CORRECT":
            # Happy message
            d.text(self.feedback_msg, (320 - len(self.feedback_msg) * 8) // 2, 245, COLOR_WHITE)

            # Draw some stars as celebration
            for i in range(3):
                sx = 100 + i * 60
                draw_star(d, sx, 275, 6, COLOR_LIGHT)

            d.text("Press any key...", 96, 300, COLOR_GRAY)
        elif self.state == "WRONG":
            d.text("Not quite!", 120, 240, COLOR_LIGHT)
            # Show the right answer
            ans_str = str(self.num_a) + " " + self.op + " " + str(self.num_b) + " = " + self.feedback_msg
            d.text(ans_str, (320 - len(ans_str) * 8) // 2, 260, COLOR_WHITE)
            d.text("Press any key...", 96, 300, COLOR_GRAY)

        d.show()

    def _draw_levelup(self):
        """Draw level up celebration screen."""
        d = self.display
        d.fill(0)

        draw_big_text(d, "LEVEL UP", 28, 40, COLOR_WHITE, 5)

        lvl_names = ["Easy", "Medium", "Hard"]
        msg = "Level " + str(self.level) + ": " + lvl_names[self.level - 1]
        d.text(msg, (320 - len(msg) * 8) // 2, 100, COLOR_LIGHT)

        # Stars
        for i in range(7):
            draw_star(d, 30 + i * 42, 150, 8, COLOR_WHITE if i % 2 == 0 else COLOR_LIGHT)

        d.text("Score: " + str(self.score), 112, 200, COLOR_WHITE)
        d.text("Stars: " + str(self.stars), 120, 218, COLOR_LIGHT)

        d.text("Press any key!", 104, 280, COLOR_GRAY)
        d.show()

    def run(self):
        self._static_drawn = False
        try:
            self._draw_title()

            while True:
                action = self.handle_input()

                if action == "EXIT":
                    break

                if self.state == "TITLE":
                    if action == "REDRAW":
                        self._draw_problem()
                    continue

                if self.state == "PLAY":
                    if not self._static_drawn:
                        self._draw_problem()
                    if action == "UPDATE_SEL":
                        self._update_choices_only()
                    elif action == "SUBMIT":
                        self._check_answer()
                        if self.state == "CORRECT" or self.state == "WRONG":
                            self._draw_feedback()
                        elif self.state == "LEVELUP":
                            self._draw_levelup()
                    continue

                if self.state in ("CORRECT", "WRONG"):
                    if action == "NEXT":
                        self._new_problem()
                        self.state = "PLAY"
                        self._static_drawn = False
                        self._draw_problem()
                    continue

                if self.state == "LEVELUP":
                    if action == "NEXT":
                        self._new_problem()
                        self.state = "PLAY"
                        self._static_drawn = False
                        self._draw_problem()
                    continue

                utime.sleep_ms(30)

        except KeyboardInterrupt:
            pass

        self.sound.cleanup()


def main():
    gc.collect()
    try:
        print("Free memory:", gc.mem_free(), "bytes")
        app = MathKids()
        app.run()
    except Exception as e:
        print("Error:", e)
        import sys
        sys.print_exception(e)


if __name__ == "__main__":
    main()
