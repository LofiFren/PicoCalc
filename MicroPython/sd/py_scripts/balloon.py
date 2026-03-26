"""
Hot Air Balloon - Countdown timer with liftoff animation
Features:
- Hot air balloon with basket, ropes, flame, clouds
- 10 second countdown
- Liftoff animation
- ESC to exit anytime
"""
import picocalc
import utime
import gc

KEY_ESC = b'\x1b\x1b'


class Balloon:
    def __init__(self):
        self.display = picocalc.display
        self.key_buffer = bytearray(10)
        self.bx = 160
        self.by = 100
        self.clouds = [(50, 40), (250, 60), (80, 150), (270, 130)]

    def handle_input(self):
        if not picocalc.terminal:
            return False
        count = picocalc.terminal.readinto(self.key_buffer)
        if not count:
            return False
        if bytes(self.key_buffer[:count]) == KEY_ESC:
            return "EXIT"
        return True

    def draw_sky(self):
        for y in range(0, 200, 10):
            shade = max(1, 3 - y // 80)
            self.display.fill_rect(0, y, 320, 10, shade)

    def draw_ground(self):
        self.display.fill_rect(0, 260, 320, 60, 4)
        self.display.fill_rect(0, 255, 320, 5, 6)

    def draw_clouds(self):
        for cx, cy in self.clouds:
            self.display.fill_rect(cx - 20, cy - 6, 40, 12, 11)
            self.display.fill_rect(cx - 12, cy - 12, 24, 8, 11)

    def draw_balloon(self, by_offset=0):
        d = self.display
        bx = self.bx
        by = self.by - by_offset

        # Balloon body
        for r in range(45, 0, -1):
            shade = min(15, 8 + (45 - r) // 8)
            yr = int(r * 1.3)
            d.fill_rect(bx - r, by - yr, r * 2, yr * 2, shade)

        # Highlight
        d.fill_rect(bx - 20, by - 40, 12, 25, 15)

        # Stripes
        for i in range(-35, 36, 12):
            d.vline(bx + i, by - 50, 100, 10)

        # Ropes
        d.line(bx - 25, by + 55, bx - 12, by + 85, 8)
        d.line(bx + 25, by + 55, bx + 12, by + 85, 8)
        d.line(bx - 15, by + 55, bx - 8, by + 85, 8)
        d.line(bx + 15, by + 55, bx + 8, by + 85, 8)

        # Basket
        d.fill_rect(bx - 15, by + 85, 30, 20, 7)
        d.rect(bx - 15, by + 85, 30, 20, 12)
        d.hline(bx - 15, by + 91, 30, 10)
        d.hline(bx - 15, by + 97, 30, 10)

        # Flame
        d.fill_rect(bx - 4, by + 50, 8, 10, 15)
        d.fill_rect(bx - 2, by + 46, 4, 6, 12)

    def draw_scene(self, by_offset=0):
        self.draw_sky()
        self.draw_clouds()
        self.draw_balloon(by_offset)
        self.draw_ground()
        self.display.text("HOT AIR BALLOON", 88, 4, 15)

    def run(self):
        try:
            d = self.display
            d.fill(0)

            # Draw initial scene
            self.draw_scene()
            d.text("ESC to exit", 116, 310, 8)
            d.show()

            # Countdown
            for sec in range(10, -1, -1):
                if self.handle_input() == "EXIT":
                    return

                d.fill_rect(80, 270, 160, 40, 4)
                x = 148 if sec >= 10 else 154
                d.text(str(sec), x, 275, 15)
                d.text(f"LIFTOFF IN {sec}s", 100, 295, 15 if sec > 3 else 12)
                d.show()

                if sec > 0:
                    # Check for ESC during countdown
                    for _ in range(10):
                        utime.sleep_ms(100)
                        if self.handle_input() == "EXIT":
                            return

            # Liftoff text
            d.fill_rect(80, 270, 160, 40, 4)
            d.text("LIFTOFF!", 128, 280, 15)
            d.show()

            # Animate balloon rising
            for frame in range(40):
                if self.handle_input() == "EXIT":
                    return

                offset = frame * 5
                self.draw_scene(offset)
                d.fill_rect(80, 270, 160, 40, 4)
                d.text("LIFTOFF!", 128, 280, 15)
                d.show()
                utime.sleep_ms(80)

            # Hold final frame
            while True:
                if self.handle_input() == "EXIT":
                    return
                utime.sleep_ms(100)

        except KeyboardInterrupt:
            pass


def main():
    gc.collect()
    try:
        app = Balloon()
        app.run()
    except Exception as e:
        print(f"Error: {e}")
        import sys
        sys.print_exception(e)


if __name__ == "__main__":
    main()
