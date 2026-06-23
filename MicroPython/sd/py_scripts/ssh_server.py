"""
SSH Server for PicoCalc -- lets you SSH INTO the device and get a MicroPython REPL.

Pairs with ssh_client.py (ssh out). Reuses that module's SSH2 transport, P-256
curve math, AES-128-CTR cipher, and HMAC-SHA2-256 primitives, and adds the
server side: an ECDSA-nistp256 host key, key-exchange signing, password +
public-key authentication, and a channel bridged to an interactive REPL.

  Key exchange : ecdh-sha2-nistp256
  Host key     : ecdsa-sha2-nistp256 (generated once, stored on SD)
  Cipher / MAC : aes128-ctr / hmac-sha2-256
  Auth         : password (salted-hash) and/or public key (authorized_keys)

Files (on the SD card):
  /sd/ssh_host_ecdsa.json  -- host private key (auto-generated on first run)
  /sd/ssh_server.json      -- username + salted password hash (set on first run)
  /sd/authorized_keys      -- optional OpenSSH-format public keys, one per line

Default listen port is 2222. Connect with:
  ssh -p 2222 <user>@<pico-ip>
"""
import usocket
import network
import picocalc
import utime
import struct
import gc
import os
import json
import uhashlib

# Reuse the client's protocol + crypto primitives
from ssh_client import (
    _ec_mul, _ec_add_mix, _randbytes,
    _hmac_sha256, _AES_CTR,
    _ssh_str, _ssh_mpint, _byte_len, _verify_rsa,
    _p_str, _p_mpint, _p_u32, _p_nl,
    _Transport,
    _P256_P, _P256_A, _P256_B, _P256_N, _P256_GX, _P256_GY,
    MSG_DISCONNECT, MSG_IGNORE, MSG_DEBUG,
    MSG_SERVICE_REQUEST, MSG_SERVICE_ACCEPT,
    MSG_KEXINIT, MSG_NEWKEYS, MSG_KEXDH_INIT, MSG_KEXDH_REPLY,
    MSG_USERAUTH_REQUEST, MSG_USERAUTH_FAILURE, MSG_USERAUTH_SUCCESS,
    MSG_USERAUTH_BANNER, MSG_GLOBAL_REQUEST, MSG_REQUEST_FAILURE,
    MSG_CHANNEL_OPEN, MSG_CHANNEL_OPEN_CONFIRM, MSG_CHANNEL_OPEN_FAILURE,
    MSG_CHANNEL_WINDOW_ADJUST, MSG_CHANNEL_DATA, MSG_CHANNEL_EOF,
    MSG_CHANNEL_CLOSE, MSG_CHANNEL_REQUEST, MSG_CHANNEL_SUCCESS,
    MSG_CHANNEL_FAILURE,
    # VT100 UI helpers
    _w, _clr, _at, _fg, _rst, _cur,
    _BLK, _RED, _GRN, _YEL, _BLU, _CYN, _WHT, _W, _H,
)

MSG_USERAUTH_PK_OK = 60

BANNER = "SSH-2.0-PicoCalc_SSH_1.0"
HOST_KEY_PATH = '/sd/ssh_host_ecdsa.json'
SERVER_CFG_PATH = '/sd/ssh_server.json'
AUTH_KEYS_PATH = '/sd/authorized_keys'
DEFAULT_PORT = 2222

_HK_TYPE = b'ecdsa-sha2-nistp256'
_HK_CURVE = b'nistp256'


# --- ECDSA over nistp256 ----------------------------------------------------

def _ecdsa_sign(d, z):
    """Sign integer digest z with private scalar d. Returns (r, s)."""
    n = _P256_N
    while True:
        k = int.from_bytes(_randbytes(32), 'big') % (n - 1) + 1
        x1, _ = _ec_mul(k, _P256_GX, _P256_GY, _P256_P)
        r = x1 % n
        if r == 0:
            continue
        s = pow(k, n - 2, n) * (z + r * d) % n
        if s == 0:
            continue
        return r, s


def _ecdsa_verify(Qx, Qy, r, s, z):
    """Verify (r, s) over digest z against public point (Qx, Qy)."""
    n = _P256_N
    p = _P256_P
    if not (1 <= r < n and 1 <= s < n):
        return False
    w = pow(s, n - 2, n)
    u1 = z * w % n
    u2 = r * w % n
    X1, Y1 = _ec_mul(u1, _P256_GX, _P256_GY, p)
    X2, Y2 = _ec_mul(u2, Qx, Qy, p)
    X3, Y3, Z3 = _ec_add_mix(X1, Y1, 1, X2, Y2, p)
    if Z3 == 0:
        return False
    zi = pow(Z3, p - 2, p)
    x = X3 * zi % p * zi % p
    return (x % n) == r


def _ecdsa_sig_blob(r, s):
    inner = _ssh_mpint(r) + _ssh_mpint(s)
    return _ssh_str(_HK_TYPE) + _ssh_str(inner)


# --- Host key ---------------------------------------------------------------

def _load_or_create_hostkey():
    """Return (d, Qx, Qy) for the ECDSA host key, creating it if absent."""
    try:
        with open(HOST_KEY_PATH) as f:
            d = int(json.load(f)['d'], 16)
    except Exception:
        d = int.from_bytes(_randbytes(32), 'big') % (_P256_N - 1) + 1
        try:
            with open(HOST_KEY_PATH, 'w') as f:
                json.dump({'d': '%x' % d}, f)
        except Exception:
            pass
    Qx, Qy = _ec_mul(d, _P256_GX, _P256_GY, _P256_P)
    return d, Qx, Qy


def _hostkey_blob(Qx, Qy):
    point = b'\x04' + Qx.to_bytes(32, 'big') + Qy.to_bytes(32, 'big')
    return _ssh_str(_HK_TYPE) + _ssh_str(_HK_CURVE) + _ssh_str(point)


def _fingerprint(blob):
    h = uhashlib.sha256()
    h.update(blob)
    return h.digest()


# --- Auth backends ----------------------------------------------------------

def _load_server_cfg():
    try:
        with open(SERVER_CFG_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _save_server_cfg(cfg):
    with open(SERVER_CFG_PATH, 'w') as f:
        json.dump(cfg, f)


def _hash_pw(salt_hex, password):
    h = uhashlib.sha256()
    h.update(bytes.fromhex(salt_hex))
    h.update(password.encode())
    return h.digest().hex()


def _check_password(cfg, username, password):
    if not cfg:
        return False
    if username != cfg.get('user'):
        return False
    return _hash_pw(cfg.get('salt', ''), password) == cfg.get('pwhash')


def _load_authorized_keys():
    """Return a list of raw key blobs (bytes) from the authorized_keys file."""
    import binascii
    keys = []
    try:
        with open(AUTH_KEYS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    keys.append(binascii.a2b_base64(parts[1]))
                except Exception:
                    pass
    except Exception:
        pass
    return keys


def _verify_client_sig(keyblob, sig_blob, signed):
    """Verify a public-key auth signature over `signed` bytes."""
    off = 0
    algo, off = _p_str(keyblob, off)
    if algo == _HK_TYPE:
        # ecdsa-sha2-nistp256: keyblob = type, curve, point
        _, off = _p_str(keyblob, off)            # curve
        point, off = _p_str(keyblob, off)
        if len(point) != 65 or point[0] != 4:
            return False
        Qx = int.from_bytes(point[1:33], 'big')
        Qy = int.from_bytes(point[33:65], 'big')
        # sig_blob = type, blob(mpint r, mpint s)
        o2 = 0
        _, o2 = _p_str(sig_blob, o2)
        inner, o2 = _p_str(sig_blob, o2)
        r, i2 = _p_mpint(inner, 0)
        s, i2 = _p_mpint(inner, i2)
        h = uhashlib.sha256()
        h.update(signed)
        z = int.from_bytes(h.digest(), 'big')
        return _ecdsa_verify(Qx, Qy, r, s, z)
    if algo in (b'ssh-rsa', b'rsa-sha2-256', b'rsa-sha2-512'):
        # _verify_rsa hashes `signed` itself (sha256 for rsa-sha2-256, else sha1)
        return _verify_rsa(keyblob, sig_blob, signed)
    return False


# --- Server session ---------------------------------------------------------

class _ServerSession:
    def __init__(self, sock, hostkey, cfg, log):
        self.t = _Transport(sock)
        self.sock = sock
        self.d, self.Qx, self.Qy = hostkey
        self.cfg = cfg
        self.log = log
        self.session_id = None
        self.v_c = None
        self._lch = 0           # our channel id
        self._rch = 0           # client's channel id
        self._rwin = 0          # remaining window for data we send
        self._authed_user = None

    # ---- low-level helpers ----

    def _recv(self):
        """Receive a packet, transparently skipping IGNORE/DEBUG."""
        while True:
            p = self.t.recv_packet()
            if not p:
                continue
            t = p[0]
            if t in (MSG_IGNORE, MSG_DEBUG):
                continue
            if t == MSG_GLOBAL_REQUEST:
                # name, want_reply
                name, off = _p_str(p, 1)
                want = p[off] if off < len(p) else 0
                if want:
                    self.t.send_packet(bytes([MSG_REQUEST_FAILURE]))
                continue
            return p

    def _exchange_banners(self):
        self.sock.send((BANNER + "\r\n").encode())
        # Read the client's identification line (skip any pre-banner lines)
        buf = b''
        while b'\n' not in buf or not buf.lstrip().startswith(b'SSH-'):
            chunk = self.sock.recv(1)
            if not chunk:
                raise OSError("closed during banner")
            buf += chunk
            if len(buf) > 512:
                # consume until newline for non-SSH preamble
                if b'\n' in buf and not buf.lstrip().startswith(b'SSH-'):
                    buf = b''
        self.v_c = buf.strip().decode()

    # ---- key exchange ----

    def do_kex(self):
        our_kex = "ecdh-sha2-nistp256"
        our_hk = "ecdsa-sha2-nistp256"
        our_enc = "aes128-ctr"
        our_mac = "hmac-sha2-256"

        cookie = _randbytes(16)
        payload = bytes([MSG_KEXINIT]) + cookie
        for nl in [our_kex, our_hk, our_enc, our_enc,
                   our_mac, our_mac, "none", "none", '', '']:
            payload += _ssh_str(nl)
        payload += b'\x00\x00\x00\x00\x00'
        i_s = payload
        self.t.send_packet(payload)

        i_c = self._recv()
        if i_c[0] != MSG_KEXINIT:
            raise OSError("expected KEXINIT")
        # Confirm the client offers what we require
        off = 17
        c_kex, off = _p_nl(i_c, off)
        c_hk, off = _p_nl(i_c, off)
        c_enc_cs, off = _p_nl(i_c, off)
        c_enc_sc, off = _p_nl(i_c, off)
        c_mac_cs, off = _p_nl(i_c, off)
        c_mac_sc, off = _p_nl(i_c, off)
        for need, have, what in (
            (our_kex, c_kex, "kex"), (our_hk, c_hk, "host key"),
            (our_enc, c_enc_cs, "cipher"), (our_enc, c_enc_sc, "cipher"),
            (our_mac, c_mac_cs, "mac"), (our_mac, c_mac_sc, "mac"),
        ):
            if need not in have:
                raise OSError("no common " + what)

        pkt = self._recv()
        if pkt[0] != MSG_KEXDH_INIT:
            raise OSError("expected KEXDH_INIT")
        q_c, _ = _p_str(pkt, 1)
        if len(q_c) != 65 or q_c[0] != 4:
            raise OSError("bad client EC point")
        Cx = int.from_bytes(q_c[1:33], 'big')
        Cy = int.from_bytes(q_c[33:65], 'big')
        if Cy * Cy % _P256_P != (pow(Cx, 3, _P256_P) + _P256_A * Cx + _P256_B) % _P256_P:
            raise OSError("client point not on curve")

        # Server ephemeral key
        e = int.from_bytes(_randbytes(32), 'big') % (_P256_N - 1) + 1
        Ex, Ey = _ec_mul(e, _P256_GX, _P256_GY, _P256_P)
        q_s = b'\x04' + Ex.to_bytes(32, 'big') + Ey.to_bytes(32, 'big')

        # Shared secret
        Kx, _ = _ec_mul(e, Cx, Cy, _P256_P)
        k_mpint = _ssh_mpint(Kx)

        k_s = _hostkey_blob(self.Qx, self.Qy)

        h = uhashlib.sha256()
        h.update(_ssh_str(self.v_c))
        h.update(_ssh_str(BANNER))
        h.update(_ssh_str(i_c))
        h.update(_ssh_str(i_s))
        h.update(_ssh_str(k_s))
        h.update(_ssh_str(q_c))
        h.update(_ssh_str(q_s))
        h.update(k_mpint)
        H = h.digest()

        if self.session_id is None:
            self.session_id = H

        r, s = _ecdsa_sign(self.d, int.from_bytes(H, 'big'))
        sig = _ecdsa_sig_blob(r, s)

        reply = bytes([MSG_KEXDH_REPLY]) + _ssh_str(k_s) + _ssh_str(q_s) + _ssh_str(sig)
        self.t.send_packet(reply)

        # Derive keys (RFC 4253). Server send = s2c (D/B/F), recv = c2s (C/A/E).
        def dk(letter, length):
            h2 = uhashlib.sha256()
            h2.update(k_mpint)
            h2.update(H)
            h2.update(letter)
            h2.update(self.session_id)
            out = h2.digest()
            while len(out) < length:
                h3 = uhashlib.sha256()
                h3.update(k_mpint)
                h3.update(H)
                h3.update(out)
                out += h3.digest()
            return out[:length]

        iv_c = dk(b'A', 16)
        iv_s = dk(b'B', 16)
        key_c = dk(b'C', 16)
        key_s = dk(b'D', 16)
        mkey_c = dk(b'E', 32)
        mkey_s = dk(b'F', 32)
        gc.collect()

        self.t.send_packet(bytes([MSG_NEWKEYS]))
        pkt = self._recv()
        if pkt[0] != MSG_NEWKEYS:
            raise OSError("expected NEWKEYS")

        self.t.send_cipher = _AES_CTR(key_s, iv_s)
        self.t.recv_cipher = _AES_CTR(key_c, iv_c)
        self.t.send_mac_key = mkey_s
        self.t.recv_mac_key = mkey_c
        self.t.send_mac_fn = _hmac_sha256
        self.t.recv_mac_fn = _hmac_sha256
        self.t.send_mac_len = 32
        self.t.recv_mac_len = 32

    # ---- authentication ----

    def do_auth(self):
        pkt = self._recv()
        if pkt[0] != MSG_SERVICE_REQUEST:
            raise OSError("expected SERVICE_REQUEST")
        name, _ = _p_str(pkt, 1)
        if name != b'ssh-userauth':
            raise OSError("unexpected service")
        self.t.send_packet(bytes([MSG_SERVICE_ACCEPT]) + _ssh_str("ssh-userauth"))

        authkeys = _load_authorized_keys()
        for _attempt in range(20):
            pkt = self._recv()
            if pkt[0] != MSG_USERAUTH_REQUEST:
                raise OSError("expected USERAUTH_REQUEST")
            off = 1
            user, off = _p_str(pkt, off)
            _svc, off = _p_str(pkt, off)
            method, off = _p_str(pkt, off)
            user = user.decode()

            if method == b'password':
                off += 1  # bool (change-password), always 0
                pw, off = _p_str(pkt, off)
                if _check_password(self.cfg, user, pw.decode()):
                    self._authed_user = user
                    self.t.send_packet(bytes([MSG_USERAUTH_SUCCESS]))
                    self.log("auth ok (password): " + user)
                    return True
                self.log("auth fail (password): " + user)
                self._fail()

            elif method == b'publickey':
                has_sig = pkt[off]; off += 1
                algo, off = _p_str(pkt, off)
                keyblob, off = _p_str(pkt, off)
                authorized = any(keyblob == k for k in authkeys)
                if not authorized:
                    self._fail()
                    continue
                if not has_sig:
                    # probe: tell client this key is acceptable
                    resp = bytes([MSG_USERAUTH_PK_OK]) + _ssh_str(algo) + _ssh_str(keyblob)
                    self.t.send_packet(resp)
                    continue
                sig, off = _p_str(pkt, off)
                # Signed data = string(session_id) + the request up to (and
                # including) the public key blob, with has_sig forced to 1.
                signed = _ssh_str(self.session_id) + pkt[:off - (4 + len(sig))]
                if _verify_client_sig(keyblob, sig, signed):
                    self._authed_user = user
                    self.t.send_packet(bytes([MSG_USERAUTH_SUCCESS]))
                    self.log("auth ok (pubkey): " + user)
                    return True
                self.log("auth fail (pubkey sig): " + user)
                self._fail()

            else:
                self._fail()
        return False

    def _fail(self):
        methods = "publickey,password"
        self.t.send_packet(bytes([MSG_USERAUTH_FAILURE]) + _ssh_str(methods) + b'\x00')

    # ---- channel + REPL ----

    def serve(self):
        # Wait for the client to open a session channel
        while True:
            pkt = self._recv()
            if pkt[0] == MSG_CHANNEL_OPEN:
                ctype, off = _p_str(pkt, 1)
                self._rch, off = _p_u32(pkt, off)
                rwin, off = _p_u32(pkt, off)
                rmax, off = _p_u32(pkt, off)
                self._rwin = rwin
                if ctype != b'session':
                    fail = (bytes([MSG_CHANNEL_OPEN_FAILURE]) +
                            struct.pack('>II', self._rch, 3) +
                            _ssh_str("only session") + _ssh_str(""))
                    self.t.send_packet(fail)
                    continue
                conf = (bytes([MSG_CHANNEL_OPEN_CONFIRM]) +
                        struct.pack('>IIII', self._rch, self._lch, 1048576, 32768))
                self.t.send_packet(conf)
                break

        # Handle channel requests (pty-req, shell/exec) then bridge to REPL
        repl = _Repl(self)
        started = False
        while True:
            pkt = self._recv()
            t = pkt[0]
            if t == MSG_CHANNEL_REQUEST:
                off = 1
                _rc, off = _p_u32(pkt, off)
                req, off = _p_str(pkt, off)
                want = pkt[off]; off += 1
                if req in (b'pty-req', b'env', b'shell'):
                    if want:
                        self.t.send_packet(bytes([MSG_CHANNEL_SUCCESS]) +
                                           struct.pack('>I', self._rch))
                    if req == b'shell':
                        started = True
                        repl.start()
                elif req == b'exec':
                    cmd, off = _p_str(pkt, off)
                    if want:
                        self.t.send_packet(bytes([MSG_CHANNEL_SUCCESS]) +
                                           struct.pack('>I', self._rch))
                    repl.exec_once(cmd.decode())
                    self._channel_eof_close()
                    return
                else:
                    if want:
                        self.t.send_packet(bytes([MSG_CHANNEL_FAILURE]) +
                                           struct.pack('>I', self._rch))
            elif t == MSG_CHANNEL_DATA:
                _rc, off = _p_u32(pkt, 1)
                data, off = _p_str(pkt, off)
                if started:
                    repl.feed(data)
            elif t == MSG_CHANNEL_WINDOW_ADJUST:
                _rc, off = _p_u32(pkt, 1)
                add, off = _p_u32(pkt, off)
                self._rwin += add
            elif t in (MSG_CHANNEL_EOF, MSG_CHANNEL_CLOSE):
                break
            elif t == MSG_DISCONNECT:
                break
        self._channel_eof_close()

    def channel_write(self, data):
        if isinstance(data, str):
            data = data.encode()
        # Respect the client's window; chunk if needed
        pos = 0
        while pos < len(data):
            if self._rwin <= 0:
                # Wait for a window adjustment
                pkt = self._recv()
                if pkt[0] == MSG_CHANNEL_WINDOW_ADJUST:
                    _rc, o = _p_u32(pkt, 1)
                    add, o = _p_u32(pkt, o)
                    self._rwin += add
                elif pkt[0] in (MSG_CHANNEL_CLOSE, MSG_CHANNEL_EOF, MSG_DISCONNECT):
                    raise OSError("channel closed")
                continue
            n = min(len(data) - pos, self._rwin, 16384)
            chunk = data[pos:pos + n]
            self.t.send_packet(bytes([MSG_CHANNEL_DATA]) +
                               struct.pack('>I', self._rch) + _ssh_str(chunk))
            self._rwin -= n
            pos += n

    def _channel_eof_close(self):
        try:
            self.t.send_packet(bytes([MSG_CHANNEL_EOF]) + struct.pack('>I', self._rch))
            self.t.send_packet(bytes([MSG_CHANNEL_CLOSE]) + struct.pack('>I', self._rch))
        except Exception:
            pass


class _Repl:
    """Minimal interactive MicroPython REPL bridged over an SSH channel."""

    def __init__(self, session):
        self.s = session
        self.g = {'__name__': '__ssh__'}
        self.line = bytearray()
        self.src = []          # accumulated lines for a compound statement

    def start(self):
        self.s.channel_write(
            "PicoCalc MicroPython REPL over SSH\r\n"
            "Ctrl-D or exit() to disconnect.\r\n\r\n")
        self._prompt()

    def _prompt(self):
        self.s.channel_write("... " if self.src else ">>> ")

    def feed(self, data):
        for b in data:
            if b in (3,):                      # Ctrl-C
                self.src = []
                self.line = bytearray()
                self.s.channel_write("\r\nKeyboardInterrupt\r\n")
                self._prompt()
            elif b == 4:                       # Ctrl-D
                if not self.line and not self.src:
                    self.s.channel_write("\r\n")
                    raise _Bye()
            elif b in (13, 10):                # CR / LF
                self.s.channel_write("\r\n")
                self._submit(bytes(self.line).decode())
                self.line = bytearray()
            elif b in (8, 127):                # backspace
                if self.line:
                    self.line.pop()
                    self.s.channel_write("\x08 \x08")
            elif 32 <= b < 127:
                self.line.append(b)
                self.s.channel_write(bytes([b]))

    def _submit(self, text):
        self.src.append(text)
        source = "\n".join(self.src)
        if self.src and self.src[-1] != "" and self._needs_more(source):
            self._prompt()
            return
        self.src = []
        if source.strip():
            self._run(source)
        self._prompt()

    def _needs_more(self, source):
        # A trailing empty line always forces execution (handled by caller).
        try:
            compile(source, "<ssh>", "exec")
            return False
        except SyntaxError as e:
            msg = str(e).lower()
            return 'eof' in msg or 'indent' in msg or 'expected' in msg
        except Exception:
            return False

    def _run(self, source):
        old = os.dupterm(_DupAdapter(self.s))
        try:
            # Try as an expression first (so values echo like a REPL),
            # then fall back to statement execution.
            try:
                code = compile(source, "<ssh>", "eval")
                val = eval(code, self.g)
                if val is not None:
                    print(repr(val))
            except SyntaxError:
                exec(compile(source, "<ssh>", "exec"), self.g)
        except _Bye:
            raise
        except Exception as e:
            import sys
            sys.print_exception(e)
        finally:
            try:
                os.dupterm(old)
            except Exception:
                pass

    def exec_once(self, cmd):
        self._run(cmd)


class _DupAdapter:
    """Stream adapter: routes REPL/print output to the SSH channel.

    os.dupterm sends bytes here via write(); we translate bare \\n to \\r\\n so
    output renders correctly in the client's terminal.
    """
    def __init__(self, session):
        self.s = session

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        data = data.replace(b'\n', b'\r\n')
        try:
            self.s.channel_write(data)
        except Exception:
            return 0
        return len(data)

    def readinto(self, buf):
        return None


class _Bye(Exception):
    pass


# --- VT100 status UI --------------------------------------------------------

class SSHServerApp:
    def __init__(self):
        self.events = []
        self.port = DEFAULT_PORT

    def _log(self, msg):
        self.events.append(msg)
        if len(self.events) > 8:
            self.events.pop(0)

    def _key(self):
        b = bytearray(8)
        try:
            n = picocalc.terminal.readinto(b)
        except OSError:
            n = None
        return bytes(b[:n]) if n else None

    def _wlan_ip(self):
        try:
            w = network.WLAN(network.STA_IF)
            if w.isconnected():
                return w.ifconfig()[0]
        except Exception:
            pass
        return None

    def _first_run_setup(self):
        """Prompt for a username + password if no server config exists."""
        _clr(); _cur(True)
        _at(2, 2); _fg(_CYN, bold=True); _w('SSH SERVER SETUP'); _rst()
        _at(3, 2); _fg(_WHT, dim=True); _w('Set login for incoming SSH'); _rst()

        def _prompt(row, label, secret=False):
            _at(row, 2); _fg(_CYN); _w(label); _rst()
            buf = []
            col = 2 + len(label)
            _at(row, col)
            while True:
                k = self._key()
                if not k:
                    utime.sleep_ms(30); continue
                if k == b'\x1b\x1b':
                    return None
                if k in (b'\r', b'\n', b'\r\n'):
                    return ''.join(buf)
                if k[0] in (8, 127):
                    if buf:
                        buf.pop(); col -= 1
                        _at(row, col); _w(' '); _at(row, col)
                elif len(k) == 1 and 32 <= k[0] < 127:
                    buf.append(chr(k[0]))
                    _w('*' if secret else chr(k[0])); col += 1

        user = _prompt(5, 'Username: ')
        if not user:
            return None
        pw = _prompt(6, 'Password: ', True)
        if not pw or len(pw) < 4:
            _at(8, 2); _fg(_RED); _w('Password too short (min 4).'); _rst()
            utime.sleep_ms(1200)
            return None
        salt = _randbytes(16).hex()
        cfg = {'user': user, 'salt': salt, 'pwhash': _hash_pw(salt, pw)}
        _save_server_cfg(cfg)
        _cur(False)
        return cfg

    def _draw(self, ip, hostfp, status, status_c=_CYN):
        _clr(); _cur(False)
        _at(1, 1); _fg(_WHT, bg=_BLU); _w(' ' * _W)
        _at(1, 2); _fg(_YEL, bold=True); _w('PicoCalc SSH Server'); _rst()
        _at(3, 2); _fg(_CYN, bold=True); _w('LISTENING'); _rst()
        _at(4, 4)
        if ip:
            _fg(_GRN); _w('ssh -p %d %s@%s' % (self.port, self.cfg['user'], ip)); _rst()
        else:
            _fg(_RED); _w('No WiFi -- run WiFi Manager first'); _rst()
        _at(6, 2); _fg(_WHT, dim=True)
        _w('Host key SHA256:'); _rst()
        _at(7, 4); _fg(_WHT)
        import binascii
        _w(binascii.b2a_base64(hostfp).decode().strip()[:48]); _rst()
        _at(9, 2); _fg(_CYN, bold=True); _w('STATUS'); _rst()
        _at(10, 4); _fg(status_c); _w(status[:48]); _rst()
        # Event log
        _at(12, 2); _fg(_CYN, bold=True); _w('LOG'); _rst()
        row = 13
        for ev in self.events[-8:]:
            _at(row, 4); _fg(_WHT, dim=True); _w(ev[:48]); _rst()
            row += 1
        _at(_H - 1, 1); _fg(_BLU); _w('-' * _W); _rst()
        _at(_H, 2); _fg(_GRN, bold=True); _w('ESC')
        _rst(); _fg(_WHT, dim=True); _w(' Stop server'); _rst()

    def run(self):
        self.cfg = _load_server_cfg()
        if not self.cfg:
            self.cfg = self._first_run_setup()
            if not self.cfg:
                _clr(); _cur(True); _rst()
                return

        hostkey = _load_or_create_hostkey()
        hostfp = _fingerprint(_hostkey_blob(hostkey[1], hostkey[2]))

        ip = self._wlan_ip()
        self._draw(ip, hostfp, 'Starting...' if ip else 'Offline')
        if not ip:
            self._wait_esc()
            return

        srv = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM)
        srv.setsockopt(usocket.SOL_SOCKET, usocket.SO_REUSEADDR, 1)
        srv.bind(('0.0.0.0', self.port))
        srv.listen(1)
        srv.settimeout(0.3)

        self._log('Listening on :%d' % self.port)
        self._draw(ip, hostfp, 'Waiting for connection', _CYN)

        try:
            while True:
                # Check for ESC to stop
                k = self._key()
                if k and (k == b'\x1b\x1b' or (len(k) == 1 and k[0] == 0x1b)):
                    break
                try:
                    conn, addr = srv.accept()
                except OSError:
                    continue  # timeout, loop to check ESC
                self._log('Connect from %s' % addr[0])
                self._draw(ip, hostfp, 'Client connected: %s' % addr[0], _GRN)
                conn.settimeout(None)
                try:
                    sess = _ServerSession(conn, hostkey, self.cfg, self._log)
                    sess._exchange_banners()
                    sess.do_kex()
                    self._draw(ip, hostfp, 'Encrypted; authenticating', _CYN)
                    if sess.do_auth():
                        self._draw(ip, hostfp, 'Session active (REPL)', _GRN)
                        sess.serve()
                        self._log('Session ended')
                    else:
                        self._log('Auth failed')
                except _Bye:
                    self._log('Client logged out')
                except Exception as e:
                    self._log('Err: %s' % e)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    gc.collect()
                self._draw(ip, hostfp, 'Waiting for connection', _CYN)
        finally:
            try:
                srv.close()
            except Exception:
                pass
            _clr(); _cur(True); _rst()

    def _wait_esc(self):
        while True:
            k = self._key()
            if k and (k == b'\x1b\x1b' or (len(k) == 1 and k[0] == 0x1b)):
                break
            utime.sleep_ms(50)
        _clr(); _cur(True); _rst()


def main():
    gc.collect()
    try:
        SSHServerApp().run()
    except Exception as e:
        _cur(True); _rst(); _clr()
        print("SSH server error:", e)
        import sys
        sys.print_exception(e)


if __name__ == '__main__':
    main()
