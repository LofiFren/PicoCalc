"""
Demo - Visual display showcase for PicoCalc v2.0
Features:
- Grayscale palette viewer
- Bouncing boxes (flicker-free demo)
- Scrolling gradient bars
- Device info screen
"""
import picocalc
import utime
import gc

KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_LEFT = b'\x1b[D'
KEY_RIGHT = b'\x1b[C'
KEY_ESC = b'\x1b\x1b'

_MODES = ['Palette', 'Bouncing', 'Gradient', 'About']


class Demo:
    def __init__(self):
        self.d = picocalc.display
        self.key_buf = bytearray(10)
        self.mode = 0
        self.frame = 0
        self._drawn_static = -1  # Which mode has its static content drawn
        # Bouncing boxes -- use simple predetermined values (no RNG needed)
        self.boxes = [
            [20,  40,  30, 24,  3,  2, 4],
            [80,  100, 36, 28, -2,  3, 7],
            [160, 60,  42, 32,  2, -2, 10],
            [60,  200, 28, 20, -3,  2, 13],
            [240, 150, 34, 26,  2, -3, 15],
        ]

    def check_key(self):
        try:
            count = picocalc.terminal.readinto(self.key_buf)
        except OSError:
            count = None
        if not count:
            return None
        return bytes(self.key_buf[:count])

    # -- Mode: Palette ---------------------------------------------
    def _draw_palette_static(self):
        """Draw the static palette grid once -- no flicker."""
        self.d.beginDraw()
        self.d.fill(0)

        self.d.text("GRAYSCALE PALETTE", 88, 10, 15)
        self.d.text("16 shades (4-bit)", 88, 24, 8)

        sw, sh, gap = 60, 50, 10
        ox = (320 - 4 * sw - 3 * gap) // 2
        oy = 48

        for i in range(16):
            x = ox + (i % 4) * (sw + gap)
            y = oy + (i // 4) * (sh + gap)
            self.d.fill_rect(x, y, sw, sh, i)
            if i < 3:
                self.d.rect(x, y, sw, sh, 5)
            label_col = 15 if i < 8 else 0
            self.d.text(str(i), x + sw // 2 - 3, y + sh // 2 - 4, label_col)

        self.d.text("< > mode   ESC exit", 82, 282, 5)
        self.d.show()
        self._drawn_static = 0

    def draw_palette(self):
        if self._drawn_static != 0:
            self._draw_palette_static()
        # Only update the animated bar -- no beginDraw/fill needed
        pulse = (self.frame // 3) % 16
        for x in range(32):
            shade = (pulse + x) % 16
            self.d.fill_rect(x * 10, 300, 10, 12, shade)
        self.d.show()

    # -- Mode: Bouncing --------------------------------------------
    def _draw_bouncing_static(self):
        """Draw static header once."""
        self.d.beginDraw()
        self.d.fill(0)
        self.d.text("BOUNCING BOXES", 100, 4, 15)
        self.d.text("no-fill erase technique", 70, 16, 8)
        self.d.show()
        self._drawn_static = 1

    def draw_bouncing(self):
        if self._drawn_static != 1:
            self._draw_bouncing_static()

        for b in self.boxes:
            x, y, w, h, dx, dy, c = b
            # Erase at current position (black)
            self.d.fill_rect(x, y, w, h, 0)
            # Move
            x += dx; y += dy
            if x <= 0 or x + w >= 320: dx = -dx; x += dx * 2
            if y <= 28 or y + h >= 312: dy = -dy; y += dy * 2
            b[0], b[1], b[4], b[5] = x, y, dx, dy
            # Draw at new position
            self.d.fill_rect(x, y, w, h, c)
            self.d.rect(x, y, w, h, min(15, c + 3))

        # Erase and redraw frame counter
        self.d.fill_rect(4, 310, 100, 10, 0)
        self.d.text(f"Frame {self.frame}", 4, 312, 5)
        self.d.show()

    # -- Mode: Gradient --------------------------------------------
    def _draw_gradient_static(self):
        """Draw header once."""
        self.d.beginDraw()
        self.d.fill(0)
        self.d.text("SCROLLING GRADIENT", 88, 4, 15)
        self.d.show()
        self._drawn_static = 2

    def draw_gradient(self):
        if self._drawn_static != 2:
            self._draw_gradient_static()

        # Bands fully overwrite each other -- no fill(0) needed
        offset = (self.frame // 2) % 16
        band_h = 18
        for row in range(16):
            y = 20 + row * band_h
            shade = (row + offset) % 16
            self.d.fill_rect(0, y, 320, band_h, shade)
            label_col = 15 if shade < 8 else 0
            self.d.text(f"Shade {shade:>2}", 130, y + 5, label_col)

        self.d.show()

    # -- Mode: About -----------------------------------------------
    def _draw_about_static(self):
        """Draw the static about screen once."""
        self.d.beginDraw()
        self.d.fill(0)

        self.d.fill_rect(0, 0, 320, 24, 3)
        self.d.text("PICOCALC v2.0", 106, 8, 15)
        self.d.hline(0, 24, 320, 8)

        lines = [
            ("Platform", "Raspberry Pi Pico 2W"),
            ("Chip", "RP2350"),
            ("Display", "320x320 ILI9488"),
            ("Colors", "4-bit grayscale (16)"),
            ("Keyboard", "Membrane I2C"),
            ("Audio", "Stereo PWM"),
            ("WiFi", "CYW43 802.11n"),
            ("BLE", "Bluetooth 5.2"),
        ]

        for i, (label, value) in enumerate(lines):
            y = 40 + i * 22
            self.d.text(label, 20, y, 8)
            lx = 20 + len(label) * 6 + 4
            while lx < 160:
                self.d.pixel(lx, y + 4, 3)
                lx += 4
            self.d.text(value, 164, y, 15)

        gc.collect()
        y = 40 + len(lines) * 22 + 10
        self.d.text(f"RAM Free: {gc.mem_free() // 1024}KB", 20, y, 10)

        self.d.hline(0, 272, 320, 3)
        self.d.text("github.com/LofiFren/PicoCalc", 40, 282, 8)
        self.d.text("@lofifren", 124, 298, 5)

        self.d.show()
        self._drawn_static = 3

    def draw_about(self):
        if self._drawn_static != 3:
            self._draw_about_static()
        # Only animate the border -- no full redraw
        pulse = (self.frame // 3) % 16
        self.d.rect(2, 2, 316, 316, pulse)
        self.d.show()

    # -- Main loop -------------------------------------------------
    def draw(self):
        m = self.mode
        if m == 0: self.draw_palette()
        elif m == 1: self.draw_bouncing()
        elif m == 2: self.draw_gradient()
        elif m == 3: self.draw_about()

    def run(self):
        try:
            while True:
                # Check keys multiple times per frame for responsiveness
                for _ in range(3):
                    key = self.check_key()
                    if key:
                        if key == KEY_ESC or key == b'\x1b' or (len(key) >= 1 and key[0] == 0x1b and key not in (KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT)):
                            return  # Exit immediately
                        elif key == KEY_RIGHT or key == KEY_DOWN:
                            self.mode = (self.mode + 1) % len(_MODES)
                            self.frame = 0
                            self._drawn_static = -1
                        elif key == KEY_LEFT or key == KEY_UP:
                            self.mode = (self.mode - 1) % len(_MODES)
                            self.frame = 0
                            self._drawn_static = -1

                self.draw()
                self.frame += 1
                utime.sleep_ms(30)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Demo error: {e}")


def main():
    gc.collect()
    try:
        app = Demo()
        app.run()
    except Exception as e:
        print(f"Demo error: {e}")
        import sys
        sys.print_exception(e)

if __name__ == "__main__":
    main()
