"""
Remote Claude for PicoCalc -- chat with Claude over WiFi.

Talks directly to the Anthropic Messages API (api.anthropic.com) over HTTPS and
streams the reply token-by-token. Two ways to authenticate:

  api    -- an Anthropic API key (x-api-key). Pay-as-you-go, static credential,
            recommended for a handheld. Get one at console.anthropic.com.
  oauth  -- a Claude.ai (Max/Pro subscription) OAuth bearer token. No per-token
            cost, but the token is short-lived: generate it on your computer and
            re-paste when it expires. Experimental.

Default model is claude-opus-4-8 (Anthropic's most capable Opus-tier model).
The credential is stored PIN-encrypted on the SD card (/sd/claude.json) via the
same secure_creds module the WiFi/SSH apps use.

Requires WiFi (run WiFiManager first) and firmware with ssl/mbedtls.
"""
import sys
import json
import gc

try:
    import usocket as socket
except ImportError:
    import socket
try:
    import ussl as ssl
except ImportError:
    import ssl

import network
import utime

try:
    import secure_creds as _sc
except Exception:
    _sc = None

HOST = "api.anthropic.com"
PATH = "/v1/messages"
API_VERSION = "2023-06-01"
OAUTH_BETA = "oauth-2025-04-20"
CFG_PATH = "/sd/claude.json"
WIFI_PATH = "/sd/wifi.json"
DEFAULT_MODEL = "claude-opus-4-8"
# (id, short label) -- offered in the first-run picker. Default is opus 4.8.
MODELS = [
    ("claude-opus-4-8", "Opus 4.8   most capable (default)"),
    ("claude-sonnet-4-6", "Sonnet 4.6 balanced speed/intelligence"),
    ("claude-haiku-4-5", "Haiku 4.5  fastest & cheapest"),
]
DEFAULT_MAX_TOKENS = 1024
MAX_HISTORY_TURNS = 12          # cap context sent each request (memory bound)

SYSTEM_PROMPT = (
    "You are Claude, a helpful AI assistant accessed from a PicoCalc handheld "
    "with a tiny 40-column screen. Keep answers concise and avoid long code "
    "blocks unless asked."
)

_pin = [None]                   # cached PIN for this session


# --- Claude-branded splash (orange on black) --------------------------------

# Default 16-entry display palette (byte-swapped RGB565) -- to restore after.
_DEFAULT_LUT = (0x0000, 0x0080, 0x0004, 0x0084, 0x1000, 0x1080, 0x1004, 0x18C6,
                0x1084, 0x00F8, 0xE007, 0xE0FF, 0x1F00, 0x1FF8, 0xFF07, 0xFFFF)


def _rgb565_sw(r, g, b):
    """Pack r,g,b into the display's byte-swapped RGB565 LUT format."""
    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return ((v & 0xFF) << 8) | (v >> 8)


def _claude_splash():
    """Show a Claude-style orange-on-black intro, then restore the palette."""
    try:
        import picocalc
        import picocalcdisplay
        import utime
        import math
        from array import array

        d = picocalc.display
        orange = _rgb565_sw(0xD9, 0x77, 0x57)   # Claude clay orange #D97757
        light = _rgb565_sw(0xF0, 0xA8, 0x80)    # lighter tint for the center
        pal = list(_DEFAULT_LUT)
        pal[1] = orange
        pal[2] = light
        picocalcdisplay.setLUT(array('H', pal))

        d.beginDraw()
        d.fill(0)
        cx, cy = 160, 116
        # Anthropic-style sunburst: 12 tapered rays in orange (index 1)
        for k in range(12):
            a = k * math.pi / 6
            ca, sa = math.cos(a), math.sin(a)
            px, py = -sa, ca          # perpendicular, for thickness
            for off in (-1, 0, 1):
                x1 = int(cx + 18 * ca + off * px)
                y1 = int(cy + 18 * sa + off * py)
                x2 = int(cx + 54 * ca + off * px)
                y2 = int(cy + 54 * sa + off * py)
                d.line(x1, y1, x2, y2, 1)
        d.fill_rect(cx - 5, cy - 5, 10, 10, 2)   # glowing center
        # Wordmark + subtitle, centered (6px per glyph)
        wm = "CLAUDE"
        d.text(wm, cx - (len(wm) * 6) // 2, cy + 60, 1)
        sub = "Remote Claude"
        d.text(sub, cx - (len(sub) * 6) // 2, cy + 76, 2)
        tag = "for PicoCalc"
        d.text(tag, cx - (len(tag) * 6) // 2, cy + 90, 15)
        d.show()
        utime.sleep_ms(1500)
    except Exception:
        pass
    finally:
        # Always restore the default palette + hand the screen to the terminal
        try:
            import picocalcdisplay
            from array import array
            picocalcdisplay.setLUT(array('H', list(_DEFAULT_LUT)))
        except Exception:
            pass
        try:
            import picocalc
            picocalc.terminal.wr("\033[2J\033[H")
        except Exception:
            pass


# --- config ----------------------------------------------------------------

def _load_cfg():
    try:
        with open(CFG_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cfg(cfg):
    with open(CFG_PATH, "w") as f:
        json.dump(cfg, f)


def _decrypt(val):
    """Decrypt a stored credential, prompting for a PIN if needed."""
    if not _sc or not _sc.is_encrypted(val):
        return val
    for _ in range(3):
        if _pin[0] and _sc.verify_pin(_pin[0]):
            break
        entered = input("PIN to unlock credential: ").strip()
        if _sc.verify_pin(entered):
            _pin[0] = entered
            break
        print("Wrong PIN.")
    else:
        return None
    try:
        return _sc.decrypt_password(_pin[0], val)
    except Exception:
        return None


def _maybe_encrypt(secret):
    """PIN-encrypt a secret if secure_creds + a PIN are available."""
    if not _sc:
        return secret
    if not _sc.has_pin():
        ans = input("Set a PIN to encrypt the credential? (y/n) ").strip().lower()
        if ans == "y":
            for _ in range(3):
                p = input("New PIN (4-8 digits): ").strip()
                if len(p) < 4:
                    print("Too short.")
                    continue
                c = input("Confirm PIN: ").strip()
                if p != c:
                    print("PINs don't match.")
                    continue
                _sc.set_pin(p)
                _pin[0] = p
                break
    if _sc.has_pin():
        if not _pin[0]:
            for _ in range(3):
                p = input("Enter your PIN: ").strip()
                if _sc.verify_pin(p):
                    _pin[0] = p
                    break
                print("Wrong PIN.")
        if _pin[0]:
            return _sc.encrypt_password(_pin[0], secret)
    return secret


def _pick_model():
    print("\nModel:")
    for i, (mid, label) in enumerate(MODELS, 1):
        print("  %d. %s" % (i, label))
    print("  (or type a model id)")
    choice = input("Choose 1-%d [1]: " % len(MODELS)).strip()
    if not choice:
        return MODELS[0][0]
    if choice.isdigit():
        n = int(choice)
        if 1 <= n <= len(MODELS):
            return MODELS[n - 1][0]
        print("Out of range; using default.")
        return MODELS[0][0]
    return choice  # custom model id


def first_run_setup():
    print("\n=== Remote Claude setup ===")
    print("Auth mode:")
    print("  1. API key        (recommended -- console.anthropic.com)")
    print("  2. Max/Pro OAuth  (experimental -- bearer token from your computer)")
    choice = input("Choose 1 or 2 [1]: ").strip()
    mode = "oauth" if choice == "2" else "api"
    if mode == "api":
        secret = input("Paste your Anthropic API key (sk-ant-...): ").strip()
    else:
        print("\nMax/Pro OAuth token -- how to get one (on your computer):")
        print("  1. brew install anthropics/tap/ant   (or use Claude Code)")
        print("  2. ant auth login                    (log in w/ subscription)")
        print("  3. ant auth print-credentials --access-token")
        print("  4. copy the sk-ant-oat... value and paste it below")
        print("These tokens expire -- re-run /auth to refresh when it stops.")
        secret = input("OAuth token: ").strip()
    if not secret:
        print("No credential entered. Aborting.")
        return None
    model = _pick_model()
    stored = _maybe_encrypt(secret)
    cfg = {"auth_mode": mode, "credential": stored, "model": model}
    _save_cfg(cfg)
    print("Saved to", CFG_PATH)
    return cfg


# --- WiFi -------------------------------------------------------------------

def _ensure_wifi():
    w = network.WLAN(network.STA_IF)
    w.active(True)
    if w.isconnected():
        return True
    try:
        with open(WIFI_PATH) as f:
            c = json.load(f)
        ssid = c.get("ssid", "")
        pwd = c.get("password", "")
        if _sc and _sc.is_encrypted(pwd):
            pwd = _decrypt(pwd) or ""
    except Exception:
        print("No WiFi config. Run WiFiManager first.")
        return False
    print("Connecting to WiFi:", ssid)
    w.connect(ssid, pwd)
    for _ in range(20):
        if w.isconnected():
            print("WiFi OK:", w.ifconfig()[0])
            return True
        utime.sleep_ms(500)
    print("WiFi connection failed.")
    return False


# --- HTTPS streaming request ------------------------------------------------

def _readline(s):
    line = b""
    while True:
        c = s.read(1)
        if not c:
            break
        line += c
        if c == b"\n":
            break
    return line


def _body_chunks(s, chunked):
    """Yield body bytes, de-chunking transfer-encoding: chunked if needed."""
    if not chunked:
        while True:
            d = s.read(512)
            if not d:
                break
            yield d
        return
    while True:
        size_line = _readline(s).strip()
        if not size_line:
            continue
        try:
            n = int(size_line, 16)
        except Exception:
            break
        if n == 0:
            break
        got = b""
        while len(got) < n:
            d = s.read(n - len(got))
            if not d:
                break
            got += d
        yield got
        _readline(s)  # trailing CRLF


def send_message(cfg, secret, messages, on_delta):
    """Stream a Claude response. Calls on_delta(text) for each chunk.

    Returns (ok, info) where info is the full text on success or an error
    string on failure.
    """
    payload = json.dumps({
        "model": cfg.get("model", DEFAULT_MODEL),
        "max_tokens": DEFAULT_MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "stream": True,
        "messages": messages,
    })

    # Auth headers differ by mode
    if cfg.get("auth_mode") == "oauth":
        auth_lines = (
            "authorization: Bearer %s\r\n" % secret +
            "anthropic-beta: %s\r\n" % OAUTH_BETA
        )
    else:
        auth_lines = "x-api-key: %s\r\n" % secret

    req = (
        "POST %s HTTP/1.1\r\n" % PATH +
        "host: %s\r\n" % HOST +
        auth_lines +
        "anthropic-version: %s\r\n" % API_VERSION +
        "content-type: application/json\r\n" +
        "content-length: %d\r\n" % len(payload) +
        "connection: close\r\n\r\n"
    )

    s = None
    try:
        ai = socket.getaddrinfo(HOST, 443)[0][-1]
        raw = socket.socket()
        raw.connect(ai)
        try:
            s = ssl.wrap_socket(raw, server_hostname=HOST)
        except TypeError:
            # Older ssl without SNI -- Cloudflare will likely reject, but try
            s = ssl.wrap_socket(raw)
        s.write(req.encode())
        s.write(payload.encode())

        # Status line
        status_line = _readline(s)
        parts = status_line.split(b" ")
        status = int(parts[1]) if len(parts) > 1 else 0

        # Headers
        chunked = False
        while True:
            h = _readline(s)
            if h in (b"\r\n", b"\n", b""):
                break
            if b"chunked" in h.lower():
                chunked = True

        if status != 200:
            body = b""
            for d in _body_chunks(s, chunked):
                body += d
                if len(body) > 2048:
                    break
            return False, _explain_error(status, body)

        # Stream SSE from the (de-chunked) body
        full = []
        stop_reason = [None]
        buf = b""
        for data in _body_chunks(s, chunked):
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                t = ev.get("type")
                if t == "content_block_delta":
                    d = ev.get("delta", {})
                    if d.get("type") == "text_delta":
                        txt = d.get("text", "")
                        if txt:
                            full.append(txt)
                            on_delta(txt)
                elif t == "message_delta":
                    sr = ev.get("delta", {}).get("stop_reason")
                    if sr:
                        stop_reason[0] = sr
                elif t == "error":
                    err = ev.get("error", {})
                    return False, "API error: " + err.get("message", "?")
        if stop_reason[0] == "refusal":
            on_delta("\n[Claude declined this request.]")
        return True, "".join(full)
    except Exception as e:
        return False, "Request failed: %s" % e
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass
        gc.collect()


def _explain_error(status, body):
    try:
        msg = json.loads(body).get("error", {}).get("message", "")
    except Exception:
        msg = body[:160].decode() if body else ""
    hints = {
        400: "Bad request",
        401: "Invalid credential -- check your API key / token",
        403: "Permission denied",
        404: "Not found (model id?)",
        429: "Rate limited -- wait and retry",
        529: "Anthropic overloaded -- retry shortly",
    }
    return "HTTP %d: %s%s" % (status, hints.get(status, "error"),
                             (" -- " + msg) if msg else "")


# --- chat loop --------------------------------------------------------------

def main():
    _claude_splash()
    print("=== Remote Claude (PicoCalc) ===")
    cfg = _load_cfg()
    if not cfg or not cfg.get("credential"):
        cfg = first_run_setup()
        if not cfg:
            return

    if not _ensure_wifi():
        return

    secret = _decrypt(cfg["credential"])
    if not secret:
        print("Could not unlock credential.")
        return

    print("Model:", cfg.get("model", DEFAULT_MODEL),
          "| Auth:", cfg.get("auth_mode", "api"))
    print("Commands: /model <id>  /reset  /auth  /help  /quit")
    print("-" * 40)

    history = []
    while True:
        try:
            print("\nYou: ")
            prompt = input().strip()
        except KeyboardInterrupt:
            print("\nBye!")
            break

        if not prompt:
            continue
        if prompt in ("/quit", "/q", "/exit"):
            print("Bye!")
            break
        if prompt == "/help":
            print("/models      pick a model from a menu")
            print("/model <id>  switch model (default %s)" % DEFAULT_MODEL)
            print("/reset       clear conversation history")
            print("/auth        re-run credential setup")
            print("/quit        exit")
            continue
        if prompt == "/reset":
            history = []
            print("History cleared.")
            continue
        if prompt == "/models":
            cfg["model"] = _pick_model()
            _save_cfg(cfg)
            print("Model set to", cfg["model"])
            continue
        if prompt.startswith("/model"):
            parts = prompt.split(None, 1)
            if len(parts) == 2:
                cfg["model"] = parts[1].strip()
                _save_cfg(cfg)
                print("Model set to", cfg["model"])
            else:
                print("Current model:", cfg.get("model", DEFAULT_MODEL))
            continue
        if prompt == "/auth":
            new = first_run_setup()
            if new:
                cfg = new
                secret = _decrypt(cfg["credential"])
            continue

        history.append({"role": "user", "content": prompt})
        # Cap context to bound request size / memory
        if len(history) > MAX_HISTORY_TURNS * 2:
            history = history[-MAX_HISTORY_TURNS * 2:]

        print("\nClaude: ", end="")
        ok, info = send_message(cfg, secret, history, lambda t: sys.stdout.write(t))
        print()
        if ok:
            history.append({"role": "assistant", "content": info})
        else:
            print("[" + info + "]")
            history.pop()  # drop the user turn that errored


if __name__ == "__main__":
    main()
