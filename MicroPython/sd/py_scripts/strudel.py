# strudel.py - a tiny Strudel/TidalCycles mini-notation sequencer for PicoCalc.
#
# Milestone 2 of the "Strudel on PicoCalc" port (option C1). Parses a subset of
# the Strudel mini-notation and drives the native picosampler audio engine, so
# you can type patterns like:
#
#   import strudel
#   strudel.jam("bd*4 , ~ sd ~ sd , hh*8", cps=0.5, cycles=8)
#
# Supported mini-notation:
#   bd sd hh        sequence (events share the cycle equally)
#   ~               rest
#   [bd sd]         sub-sequence in one slot (subdivides that slot)
#   bd*2            repeat/speed up within the slot
#   bd/2            play once every 2 cycles
#   <bd sd>         alternate between children, one per cycle
#   bd , hh*4       stack (comma) -> layers played together
#   bd(3,8)         euclidean rhythm (3 onsets over 8 steps)
#   bd(3,8,1)       euclidean with rotation
#
# Samples are loaded on demand from /sd/samples/<name>.raw (8-bit unsigned PCM,
# see picosampler/make_samples.sh or generate_drums.py).

import time
import picosampler

SAMPLE_DIR = "/sd/samples"

_inited = False
_ids = {}      # name -> picosampler sample id
_bufs = {}     # name -> bytes (kept so the data stays alive)


def init(sr=22050):
    global _inited
    # picosampler.init is idempotent (returns early if already running), so
    # always call it -- this also recovers after a shutdown()/deinit().
    rate = picosampler.init(sr)
    _inited = True
    return rate


def shutdown():
    """Release the audio engine (stop DMA, free the PWM pins). Call on app exit
    so a later app's machine.PWM audio isn't fought by a left-running engine."""
    global _inited
    try:
        picosampler.deinit()
    except Exception:
        pass
    _inited = False


def _sample(name):
    if name not in _ids:
        try:
            data = open("%s/%s.raw" % (SAMPLE_DIR, name), "rb").read()
        except OSError:
            print("strudel: missing sample '%s'" % name)
            _ids[name] = None
            return None
        _bufs[name] = data
        _ids[name] = picosampler.register(data)
    return _ids[name]


# ----- mini-notation parser -------------------------------------------------
# Node tuples:
#   ('atom', name) ('rest',) ('seq', [..]) ('stack', [..]) ('alt', [..])
#   ('fast', node, n) ('slow', node, n) ('euclid', node, k, n, rot)

_SPECIAL = "[]<>(),*/"


def _tokenize(s):
    toks = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
        elif c in _SPECIAL or c == "~":
            toks.append(c)
            i += 1
        else:
            j = i
            while j < n and not s[j].isspace() and s[j] not in _SPECIAL and s[j] != "~":
                j += 1
            toks.append(s[i:j])
            i = j
    return toks


class _Cur:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        x = self.peek()
        self.i += 1
        return x


def _parse(s):
    return _p_stack(_Cur(_tokenize(s)), None)


def _p_stack(c, end):
    seqs = [_p_seq(c, end)]
    while c.peek() == ",":
        c.take()
        seqs.append(_p_seq(c, end))
    return seqs[0] if len(seqs) == 1 else ("stack", seqs)


def _p_seq(c, end):
    terms = []
    while True:
        tk = c.peek()
        if tk is None or tk == end or tk == ",":
            break
        terms.append(_p_term(c))
    return ("seq", terms)


def _num(c):
    return int(float(c.take()))


def _p_term(c):
    node = _p_atom(c)
    while True:
        tk = c.peek()
        if tk == "*":
            c.take()
            node = ("fast", node, _num(c))
        elif tk == "/":
            c.take()
            node = ("slow", node, _num(c))
        elif tk == "(":
            c.take()
            k = _num(c)
            c.take()              # ','
            n = _num(c)
            rot = 0
            if c.peek() == ",":
                c.take()
                rot = _num(c)
            c.take()              # ')'
            node = ("euclid", node, k, n, rot)
        else:
            return node


def _p_atom(c):
    tk = c.peek()
    if tk == "[":
        c.take()
        node = _p_stack(c, "]")
        c.take()                  # ']'
        return node
    if tk == "<":
        c.take()
        seq = _p_seq(c, ">")
        c.take()                  # '>'
        return ("alt", seq[1])
    if tk == "~":
        c.take()
        return ("rest",)
    return ("atom", c.take())


# ----- Bjorklund euclidean rhythm -------------------------------------------

def _euclid(k, n):
    if k <= 0:
        return [False] * n
    if k >= n:
        return [True] * n
    a = [[True] for _ in range(k)]
    b = [[False] for _ in range(n - k)]
    while len(b) > 1:
        m = min(len(a), len(b))
        a2 = [a[i] + b[i] for i in range(m)]
        rest_a = a[m:]
        rest_b = b[m:]
        a, b = a2, (rest_a if rest_a else rest_b)
    flat = []
    for grp in a + b:
        flat += grp
    i = flat.index(True)
    return flat[i:] + flat[:i]


# ----- renderer: node -> onset events within [lo, hi) of one cycle ----------

def _render(node, cycle, lo, hi, out):
    typ = node[0]
    span = hi - lo
    if typ == "rest":
        return
    if typ == "atom":
        out.append((lo, node[1]))
        return
    if typ == "seq":
        ch = node[1]
        m = len(ch)
        for i in range(m):
            _render(ch[i], cycle, lo + span * i / m, lo + span * (i + 1) / m, out)
        return
    if typ == "stack":
        for ch in node[1]:
            _render(ch, cycle, lo, hi, out)
        return
    if typ == "alt":
        ch = node[1]
        _render(ch[cycle % len(ch)], cycle, lo, hi, out)
        return
    if typ == "fast":
        sub, k = node[1], node[2]
        for i in range(k):
            _render(sub, cycle, lo + span * i / k, lo + span * (i + 1) / k, out)
        return
    if typ == "slow":
        sub, k = node[1], node[2]
        if cycle % k == 0:
            _render(sub, cycle, lo, hi, out)
        return
    if typ == "euclid":
        sub, k, n, rot = node[1], node[2], node[3], node[4]
        pat = _euclid(k, n)
        if rot:
            rot %= n
            pat = pat[rot:] + pat[:rot]
        for i in range(n):
            if pat[i]:
                _render(sub, cycle, lo + span * i / n, lo + span * (i + 1) / n, out)
        return


def render_cycle(code, cycle):
    """Return sorted [(offset_in_cycle, name), ...] for one cycle of `code`."""
    out = []
    _render(_parse(code), cycle, 0.0, 1.0, out)
    out.sort(key=lambda e: e[0])
    return out


# ----- clock / player -------------------------------------------------------

def jam(code, cps=0.5, cycles=8, gain=220):
    """Play `code` for `cycles` cycles at `cps` cycles/second. Blocks."""
    init()
    node = _parse(code)
    cyc_ms = int(1000.0 / cps)
    try:
        for cy in range(cycles):
            out = []
            _render(node, cy, 0.0, 1.0, out)
            out.sort(key=lambda e: e[0])
            t0 = time.ticks_ms()
            for offset, name in out:
                target = time.ticks_add(t0, int(offset * cyc_ms))
                d = time.ticks_diff(target, time.ticks_ms())
                if d > 0:
                    time.sleep_ms(d)
                sid = _sample(name)
                if sid is not None:
                    picosampler.play(sid, gain)
            end = time.ticks_add(t0, cyc_ms)
            d = time.ticks_diff(end, time.ticks_ms())
            if d > 0:
                time.sleep_ms(d)
    except KeyboardInterrupt:
        pass
    picosampler.stop_all()


def stop():
    picosampler.stop_all()


# ----- non-blocking sequencer (for the live-coding UI) ----------------------
# Tick this every frame from a UI loop; it fires due events without blocking,
# advances cycles, and swaps in newly-evaluated patterns at the next cycle
# boundary (like Strudel's Ctrl-Enter).

class Sequencer:
    def __init__(self, cps=0.5, gain=220):
        self.gain = gain
        self.node = None
        self.pending = None
        self.code = ""
        self.error = None
        self.playing = False
        self.cycle = 0
        self.cps = cps
        self.cyc_ms = int(1000.0 / cps)
        self.cycle_start = 0
        self.events = []      # (target_ms, name)
        self.offsets = []     # event offsets 0..1 for the UI timeline
        self.idx = 0

    def set_code(self, code):
        """Parse and queue `code`. Swaps in at the next cycle boundary if
        already playing. Returns True on success, False on parse error."""
        try:
            node = _parse(code)
        except Exception as e:
            self.error = str(e)
            return False
        self.error = None
        self.code = code
        if self.node is None:
            self.node = node
        else:
            self.pending = node
        return True

    def set_cps(self, cps):
        if cps < 0.1:
            cps = 0.1
        elif cps > 4.0:
            cps = 4.0
        self.cps = cps
        self.cyc_ms = int(1000.0 / cps)

    def start(self):
        init()
        if self.node is None:
            return
        self.playing = True
        self.cycle = 0
        self.cycle_start = time.ticks_ms()
        self._load()

    def stop(self):
        self.playing = False
        picosampler.stop_all()

    def _load(self):
        out = []
        if self.node is not None:
            try:
                _render(self.node, self.cycle, 0.0, 1.0, out)
            except Exception:
                out = []
        out.sort(key=lambda e: e[0])
        self.offsets = [o for o, _ in out]
        self.events = [(time.ticks_add(self.cycle_start, int(o * self.cyc_ms)), n)
                       for o, n in out]
        self.idx = 0

    def tick(self):
        if not self.playing:
            return
        now = time.ticks_ms()
        ev = self.events
        while self.idx < len(ev) and time.ticks_diff(ev[self.idx][0], now) <= 0:
            sid = _sample(ev[self.idx][1])
            if sid is not None:
                picosampler.play(sid, self.gain)
            self.idx += 1
        if time.ticks_diff(time.ticks_add(self.cycle_start, self.cyc_ms), now) <= 0:
            self.cycle += 1
            self.cycle_start = time.ticks_add(self.cycle_start, self.cyc_ms)
            if self.pending is not None:
                self.node = self.pending
                self.pending = None
            self._load()

    def phase(self):
        if not self.playing:
            return 0.0
        d = time.ticks_diff(time.ticks_ms(), self.cycle_start)
        if d < 0:
            d = 0
        elif d > self.cyc_ms:
            d = self.cyc_ms
        return d / self.cyc_ms
