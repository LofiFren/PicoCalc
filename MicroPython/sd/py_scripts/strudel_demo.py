# picocalc-app: Strudel Demo | Music | mini-notation pattern showcase
# strudel_demo.py - plays a few Strudel mini-notation patterns through the
# native picosampler engine. Milestone 2 of the Strudel-on-PicoCalc port.

import strudel

PATTERNS = [
    ("four on the floor", "bd*4 , ~ sd ~ sd , hh*8", 0.5),
    ("tresillo",          "bd(3,8) , ~ sd , hh*8", 0.5),
    ("breakbeat-ish",     "bd ~ [bd bd] ~ , ~ sd ~ sd , hh*8", 0.6),
    ("alternating",       "<bd cp> sd , hh*4 , ~ ~ hh ~", 0.55),
]


def main():
    strudel.init()
    print("strudel demo - playing %d patterns" % len(PATTERNS))
    for name, code, cps in PATTERNS:
        print("  %-18s %s" % (name, code))
        strudel.jam(code, cps=cps, cycles=4)
    print("done")


if __name__ == "__main__":
    main()
