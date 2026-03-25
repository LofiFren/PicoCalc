"""
Color Count for PicoCalc
Counts 1-100, cycling through all 15 grayscale shades.
"""
import picocalc
import utime
import gc

gc.collect()


def main():
    d = picocalc.display
    d.beginDraw()
    d.fill(0)

    for i in range(1, 101):
        color = (i % 15) + 1
        row = (i - 1) // 10
        col = (i - 1) % 10
        tx = 10 + col * 30
        ty = 20 + row * 28
        d.text(str(i), tx, ty, color)
        d.show()
        utime.sleep_ms(100)

    # Wait for keypress to exit
    kb = picocalc.keyboard
    while True:
        key = kb.read_key()
        if key:
            break
        utime.sleep_ms(50)


if __name__ == "__main__":
    main()
