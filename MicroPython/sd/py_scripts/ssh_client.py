"""
SSH Client - Secure Shell for PicoCalc
Features:
- SSH2 protocol (AES-128-CTR + HMAC-SHA2-256)
- Diffie-Hellman group14 key exchange
- RSA host key verification with TOFU
- Password authentication
- Interactive VT100 terminal (53x40)
- Saved connection profiles
"""
import usocket
import network
import picocalc
import utime
import struct
import gc
import json
import uhashlib
import ucryptolib
import urandom
import select
import secure_creds

# SSH message types
MSG_DISCONNECT = 1
MSG_IGNORE = 2
MSG_DEBUG = 4
MSG_SERVICE_REQUEST = 5
MSG_SERVICE_ACCEPT = 6
MSG_EXT_INFO = 7
MSG_KEXINIT = 20
MSG_NEWKEYS = 21
MSG_KEXDH_INIT = 30
MSG_KEXDH_REPLY = 31
MSG_USERAUTH_REQUEST = 50
MSG_USERAUTH_FAILURE = 51
MSG_USERAUTH_SUCCESS = 52
MSG_USERAUTH_BANNER = 53
MSG_GLOBAL_REQUEST = 80
MSG_REQUEST_FAILURE = 82
MSG_CHANNEL_OPEN = 90
MSG_CHANNEL_OPEN_CONFIRM = 91
MSG_CHANNEL_OPEN_FAILURE = 92
MSG_CHANNEL_WINDOW_ADJUST = 93
MSG_CHANNEL_DATA = 94
MSG_CHANNEL_EXTENDED_DATA = 95
MSG_CHANNEL_EOF = 96
MSG_CHANNEL_CLOSE = 97
MSG_CHANNEL_REQUEST = 98
MSG_CHANNEL_SUCCESS = 99
MSG_CHANNEL_FAILURE = 100

# DH group 14 prime (RFC 3526, 2048-bit)
_DH14_P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16)
_DH14_G = 2

# PKCS#1 DigestInfo for RSA signature verification
_DI_SHA256 = b'\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20'
_DI_SHA1 = b'\x30\x21\x30\x09\x06\x05\x2b\x0e\x03\x02\x1a\x05\x00\x04\x14'

# P-256 (secp256r1) for ECDH key exchange
_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = _P256_P - 3
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_P256_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


def _ec_dbl(X, Y, Z, p):
    if Z == 0:
        return 0, 1, 0
    Y2 = Y * Y % p
    S = 4 * X * Y2 % p
    Z2 = Z * Z % p
    M = 3 * (X - Z2) * (X + Z2) % p
    X3 = (M * M - 2 * S) % p
    Y3 = (M * (S - X3) - 8 * Y2 * Y2) % p
    Z3 = 2 * Y * Z % p
    return X3, Y3, Z3


def _ec_add_mix(X1, Y1, Z1, X2, Y2, p):
    if Z1 == 0:
        return X2, Y2, 1
    Z1s = Z1 * Z1 % p
    U2 = X2 * Z1s % p
    S2 = Y2 * Z1s % p * Z1 % p
    H = (U2 - X1) % p
    R = (S2 - Y1) % p
    if H == 0:
        return _ec_dbl(X1, Y1, Z1, p) if R == 0 else (0, 1, 0)
    H2 = H * H % p
    H3 = H * H2 % p
    U1H2 = X1 * H2 % p
    X3 = (R * R - H3 - 2 * U1H2) % p
    Y3 = (R * (U1H2 - X3) - Y1 * H3) % p
    Z3 = H * Z1 % p
    return X3, Y3, Z3


def _ec_mul(k, Gx, Gy, p):
    Rx, Ry, Rz = 0, 1, 0
    bl = _byte_len(k) * 8
    while bl > 0 and not (k >> (bl - 1) & 1):
        bl -= 1
    for i in range(bl - 1, -1, -1):
        Rx, Ry, Rz = _ec_dbl(Rx, Ry, Rz, p)
        if k >> i & 1:
            Rx, Ry, Rz = _ec_add_mix(Rx, Ry, Rz, Gx, Gy, p)
    Zi = pow(Rz, p - 2, p)
    Zi2 = Zi * Zi % p
    return Rx * Zi2 % p, Ry * Zi * Zi2 % p


# --- Crypto ---

def _randbytes(n):
    buf = bytearray(n)
    for i in range(0, n, 4):
        v = urandom.getrandbits(32)
        e = min(i + 4, n)
        buf[i:e] = struct.pack('>I', v)[:e - i]
    return bytes(buf)


def _hmac(hash_cls, bs, key, msg):
    if len(key) > bs:
        h = hash_cls()
        h.update(key)
        key = h.digest()
    if len(key) < bs:
        key = key + b'\x00' * (bs - len(key))
    o_pad = bytearray(bs)
    i_pad = bytearray(bs)
    for i in range(bs):
        o_pad[i] = key[i] ^ 0x5c
        i_pad[i] = key[i] ^ 0x36
    inner = hash_cls()
    inner.update(bytes(i_pad))
    inner.update(msg)
    outer = hash_cls()
    outer.update(bytes(o_pad))
    outer.update(inner.digest())
    return outer.digest()


def _hmac_sha256(key, msg):
    return _hmac(uhashlib.sha256, 64, key, msg)


def _hmac_sha1(key, msg):
    return _hmac(uhashlib.sha1, 64, key, msg)


class _AES_CTR:
    """AES-128-CTR built on AES-ECB."""
    def __init__(self, key, iv):
        self._ecb = ucryptolib.aes(key, 1)
        self._ctr = bytearray(iv)

    def _inc(self):
        for i in range(15, -1, -1):
            self._ctr[i] = (self._ctr[i] + 1) & 0xff
            if self._ctr[i]:
                break

    def process(self, data):
        out = bytearray(len(data))
        pos = 0
        while pos < len(data):
            ks = self._ecb.encrypt(bytes(self._ctr))
            n = min(16, len(data) - pos)
            for j in range(n):
                out[pos + j] = data[pos + j] ^ ks[j]
            self._inc()
            pos += n
        return bytes(out)


# --- SSH data encoding ---

def _ssh_str(data):
    if isinstance(data, str):
        data = data.encode()
    return struct.pack('>I', len(data)) + data


def _byte_len(n):
    bl = 0
    while n:
        bl += 1
        n >>= 8
    return bl


def _ssh_mpint(n):
    if n == 0:
        return b'\x00\x00\x00\x00'
    bl = _byte_len(n)
    b = n.to_bytes(bl, 'big')
    if b[0] & 0x80:
        b = b'\x00' + b
    return struct.pack('>I', len(b)) + b


def _p_str(data, off):
    ln = struct.unpack('>I', data[off:off + 4])[0]
    off += 4
    return data[off:off + ln], off + ln


def _p_mpint(data, off):
    ln = struct.unpack('>I', data[off:off + 4])[0]
    off += 4
    if ln == 0:
        return 0, off
    return int.from_bytes(data[off:off + ln], 'big'), off + ln


def _p_u32(data, off):
    return struct.unpack('>I', data[off:off + 4])[0], off + 4


def _p_nl(data, off):
    s, off = _p_str(data, off)
    return s.decode().split(',') if s else [], off


# --- RSA signature verification ---

def _verify_rsa(hk_blob, sig_blob, H):
    off = 0
    _, off = _p_str(hk_blob, off)
    e, off = _p_mpint(hk_blob, off)
    n, off = _p_mpint(hk_blob, off)

    off = 0
    sig_type, off = _p_str(sig_blob, off)
    s_bytes, off = _p_str(sig_blob, off)
    s = int.from_bytes(s_bytes, 'big')

    m = pow(s, e, n)
    n_len = _byte_len(n)
    m_bytes = m.to_bytes(n_len, 'big')

    if sig_type == b'rsa-sha2-256':
        h = uhashlib.sha256()
        h.update(H)
        di, digest = _DI_SHA256, h.digest()
    else:
        h = uhashlib.sha1()
        h.update(H)
        di, digest = _DI_SHA1, h.digest()

    suffix = b'\x00' + di + digest
    pad_len = n_len - 2 - len(suffix)
    if pad_len < 8:
        return False
    expected = b'\x00\x01' + (b'\xff' * pad_len) + suffix
    return m_bytes == expected


# --- SSH Transport ---

class _Transport:
    def __init__(self, sock):
        self.sock = sock
        self.send_seq = 0
        self.recv_seq = 0
        self.send_cipher = None
        self.recv_cipher = None
        self.send_mac_key = None
        self.recv_mac_key = None
        self.send_mac_len = 0
        self.recv_mac_len = 0
        self.send_mac_fn = None
        self.recv_mac_fn = None

    def recv_raw(self, n):
        buf = bytearray(n)
        mv = memoryview(buf)
        pos = 0
        while pos < n:
            chunk = self.sock.recv(min(4096, n - pos))
            if not chunk:
                raise OSError("Connection closed")
            mv[pos:pos + len(chunk)] = chunk
            pos += len(chunk)
        return bytes(buf)

    def recv_packet(self):
        if self.recv_cipher:
            first_enc = self.recv_raw(16)
            first_dec = self.recv_cipher.process(first_enc)
            pkt_len = struct.unpack('>I', first_dec[:4])[0]
            total = 4 + pkt_len
            remain = total - 16
            if remain > 0:
                rest_enc = self.recv_raw(remain)
                rest_dec = self.recv_cipher.process(rest_enc)
                full = first_dec + rest_dec
            else:
                full = first_dec[:total]
            if self.recv_mac_len:
                mac = self.recv_raw(self.recv_mac_len)
                mac_data = struct.pack('>I', self.recv_seq) + full
                expected = self.recv_mac_fn(self.recv_mac_key, mac_data)
                if mac != expected[:self.recv_mac_len]:
                    raise OSError("MAC verify failed")
            pad_len = full[4]
            payload = full[5:5 + pkt_len - pad_len - 1]
        else:
            hdr = self.recv_raw(4)
            pkt_len = struct.unpack('>I', hdr[:4])[0]
            body = self.recv_raw(pkt_len)
            pad_len = body[0]
            payload = body[1:pkt_len - pad_len]
        self.recv_seq += 1
        return payload

    def send_packet(self, payload):
        bs = 16 if self.send_cipher else 8
        pad_len = bs - ((5 + len(payload)) % bs)
        if pad_len < 4:
            pad_len += bs
        pkt_len = 1 + len(payload) + pad_len
        packet = struct.pack('>IB', pkt_len, pad_len) + payload + _randbytes(pad_len)

        if self.send_cipher:
            mac_data = struct.pack('>I', self.send_seq) + packet
            mac = self.send_mac_fn(self.send_mac_key, mac_data)[:self.send_mac_len]
            enc = self.send_cipher.process(packet)
            self.sock.send(enc + mac)
        else:
            self.sock.send(packet)
        self.send_seq += 1


# --- SSH Session ---

class _Session:
    BANNER = "SSH-2.0-PicoCalc_SSH_1.0"

    def __init__(self):
        self.transport = None
        self.session_id = None
        self.server_banner = None
        self.host_fp = None
        self._rch = 0
        self._win = 0

    def connect(self, host, port=22):
        addr = usocket.getaddrinfo(host, port)[0][-1]
        sock = usocket.socket()
        sock.settimeout(10)
        sock.connect(addr)
        self.transport = _Transport(sock)

        while True:
            line = b''
            while True:
                b = sock.recv(1)
                if not b:
                    raise OSError("Connection closed")
                line += b
                if b == b'\n':
                    break
            d = line.decode().strip()
            if d.startswith('SSH-'):
                self.server_banner = d
                break

        sock.send((self.BANNER + "\r\n").encode())

    def _neg(self, ours, theirs, name):
        for a in ours:
            if a in theirs:
                return a
        raise OSError(f"No common {name}")

    def _recv_skip(self):
        while True:
            pkt = self.transport.recv_packet()
            t = pkt[0]
            if t in (MSG_IGNORE, MSG_DEBUG, MSG_EXT_INFO):
                continue
            if t == MSG_GLOBAL_REQUEST:
                self.transport.send_packet(bytes([MSG_REQUEST_FAILURE]))
                continue
            if t == MSG_DISCONNECT:
                off = 1
                _, off = _p_u32(pkt, off)
                desc, _ = _p_str(pkt, off)
                raise OSError(f"Disconnected: {desc.decode()}")
            if t == MSG_CHANNEL_WINDOW_ADJUST:
                off = 1
                _, off = _p_u32(pkt, off)
                adj, _ = _p_u32(pkt, off)
                self._win += adj
                continue
            return pkt

    def kex(self, status_cb=None):
        if status_cb:
            status_cb("Key exchange init...")

        our_kex = "ecdh-sha2-nistp256,diffie-hellman-group14-sha256,diffie-hellman-group14-sha1"
        our_hk = "rsa-sha2-256,ssh-rsa"
        our_enc = "aes128-ctr"
        our_mac = "hmac-sha2-256,hmac-sha1"

        cookie = _randbytes(16)
        payload = bytes([MSG_KEXINIT]) + cookie
        for nl in [our_kex, our_hk, our_enc, our_enc,
                    our_mac, our_mac, "none", "none", '', '']:
            payload += _ssh_str(nl)
        payload += b'\x00\x00\x00\x00\x00'
        c_kexinit = payload
        self.transport.send_packet(payload)

        s_kexinit = self._recv_skip()
        if s_kexinit[0] != MSG_KEXINIT:
            raise OSError(f"Expected KEXINIT, got {s_kexinit[0]}")

        off = 17
        srv_kex, off = _p_nl(s_kexinit, off)
        srv_hk, off = _p_nl(s_kexinit, off)
        srv_enc_c, off = _p_nl(s_kexinit, off)
        srv_enc_s, off = _p_nl(s_kexinit, off)
        srv_mac_c, off = _p_nl(s_kexinit, off)
        srv_mac_s, off = _p_nl(s_kexinit, off)

        kex_alg = self._neg(our_kex.split(','), srv_kex, "kex")
        hk_alg = self._neg(our_hk.split(','), srv_hk, "host key")
        self._neg(our_enc.split(','), srv_enc_c, "cipher c2s")
        self._neg(our_enc.split(','), srv_enc_s, "cipher s2c")
        mac_alg = self._neg(our_mac.split(','), srv_mac_c, "MAC")

        kex_hash = uhashlib.sha1 if kex_alg == 'diffie-hellman-group14-sha1' else uhashlib.sha256

        if 'ecdh' in kex_alg:
            if status_cb:
                status_cb("Generating ECDH keys...")
            d = int.from_bytes(_randbytes(32), 'big') % (_P256_N - 1) + 1
            Qx, Qy = _ec_mul(d, _P256_GX, _P256_GY, _P256_P)
            Q_C = b'\x04' + Qx.to_bytes(32, 'big') + Qy.to_bytes(32, 'big')

            self.transport.send_packet(
                bytes([MSG_KEXDH_INIT]) + _ssh_str(Q_C))

            if status_cb:
                status_cb("Waiting for server...")
            reply = self._recv_skip()
            if reply[0] != MSG_KEXDH_REPLY:
                raise OSError(f"Expected KEXDH_REPLY, got {reply[0]}")
            off = 1
            hk_blob, off = _p_str(reply, off)
            Q_S, off = _p_str(reply, off)
            sig_blob, off = _p_str(reply, off)

            if len(Q_S) != 65 or Q_S[0] != 4:
                raise OSError("Bad server EC point")
            Sx = int.from_bytes(Q_S[1:33], 'big')
            Sy = int.from_bytes(Q_S[33:65], 'big')
            if Sy * Sy % _P256_P != (pow(Sx, 3, _P256_P) + _P256_A * Sx + _P256_B) % _P256_P:
                raise OSError("EC point not on curve")

            if status_cb:
                status_cb("Computing shared secret...")
            Kx, _ = _ec_mul(d, Sx, Sy, _P256_P)
            K_mpint = _ssh_mpint(Kx)

            h = kex_hash()
            h.update(_ssh_str(self.BANNER))
            h.update(_ssh_str(self.server_banner))
            h.update(_ssh_str(c_kexinit))
            h.update(_ssh_str(s_kexinit))
            h.update(_ssh_str(hk_blob))
            h.update(_ssh_str(Q_C))
            h.update(_ssh_str(Q_S))
            h.update(K_mpint)
            H = h.digest()
        else:
            if status_cb:
                status_cb("Generating DH keys...")
            x = int.from_bytes(_randbytes(32), 'big')
            e = pow(_DH14_G, x, _DH14_P)

            self.transport.send_packet(
                bytes([MSG_KEXDH_INIT]) + _ssh_mpint(e))

            if status_cb:
                status_cb("Waiting for server...")
            reply = self._recv_skip()
            if reply[0] != MSG_KEXDH_REPLY:
                raise OSError(f"Expected KEXDH_REPLY, got {reply[0]}")
            off = 1
            hk_blob, off = _p_str(reply, off)
            f, off = _p_mpint(reply, off)
            sig_blob, off = _p_str(reply, off)

            if f <= 1 or f >= _DH14_P - 1:
                raise OSError("Invalid server DH value")

            if status_cb:
                status_cb("Computing shared secret...")
            K = pow(f, x, _DH14_P)
            K_mpint = _ssh_mpint(K)

            h = kex_hash()
            h.update(_ssh_str(self.BANNER))
            h.update(_ssh_str(self.server_banner))
            h.update(_ssh_str(c_kexinit))
            h.update(_ssh_str(s_kexinit))
            h.update(_ssh_str(hk_blob))
            h.update(_ssh_mpint(e))
            h.update(_ssh_mpint(f))
            h.update(K_mpint)
            H = h.digest()

        if self.session_id is None:
            self.session_id = H

        fp = uhashlib.sha256()
        fp.update(hk_blob)
        self.host_fp = fp.digest()

        if status_cb:
            status_cb("Verifying host key...")

        if not _verify_rsa(hk_blob, sig_blob, H):
            raise OSError("Host key signature invalid")

        def dk(letter, length):
            h2 = kex_hash()
            h2.update(K_mpint)
            h2.update(H)
            h2.update(letter.encode())
            h2.update(self.session_id)
            k = h2.digest()
            while len(k) < length:
                h3 = kex_hash()
                h3.update(K_mpint)
                h3.update(H)
                h3.update(k)
                k += h3.digest()
            return k[:length]

        iv_c = dk('A', 16)
        iv_s = dk('B', 16)
        key_c = dk('C', 16)
        key_s = dk('D', 16)
        mac_len = 32 if mac_alg == 'hmac-sha2-256' else 20
        mkey_c = dk('E', mac_len)
        mkey_s = dk('F', mac_len)

        gc.collect()

        self.transport.send_packet(bytes([MSG_NEWKEYS]))

        pkt = self._recv_skip()
        if pkt[0] != MSG_NEWKEYS:
            raise OSError(f"Expected NEWKEYS, got {pkt[0]}")

        self.transport.send_cipher = _AES_CTR(key_c, iv_c)
        self.transport.recv_cipher = _AES_CTR(key_s, iv_s)
        self.transport.send_mac_key = mkey_c
        self.transport.recv_mac_key = mkey_s
        mac_fn = _hmac_sha256 if mac_alg == 'hmac-sha2-256' else _hmac_sha1
        self.transport.send_mac_fn = mac_fn
        self.transport.recv_mac_fn = mac_fn
        self.transport.send_mac_len = mac_len
        self.transport.recv_mac_len = mac_len

        if status_cb:
            status_cb("Encryption active")

    def authenticate(self, username, password, status_cb=None):
        if status_cb:
            status_cb("Requesting auth service...")

        self.transport.send_packet(
            bytes([MSG_SERVICE_REQUEST]) + _ssh_str("ssh-userauth"))

        pkt = self._recv_skip()
        if pkt[0] != MSG_SERVICE_ACCEPT:
            raise OSError(f"Service denied: {pkt[0]}")

        if status_cb:
            status_cb(f"Authenticating as {username}...")

        payload = bytes([MSG_USERAUTH_REQUEST])
        payload += _ssh_str(username)
        payload += _ssh_str("ssh-connection")
        payload += _ssh_str("password")
        payload += b'\x00'
        payload += _ssh_str(password)
        self.transport.send_packet(payload)

        while True:
            pkt = self._recv_skip()
            if pkt[0] == MSG_USERAUTH_SUCCESS:
                return True
            elif pkt[0] == MSG_USERAUTH_BANNER:
                continue
            elif pkt[0] == MSG_USERAUTH_FAILURE:
                methods, _ = _p_str(pkt, 1)
                raise OSError(f"Auth failed ({methods.decode()})")
            else:
                raise OSError(f"Auth error: msg {pkt[0]}")

    def open_shell(self, status_cb=None):
        if status_cb:
            status_cb("Opening channel...")

        payload = bytes([MSG_CHANNEL_OPEN])
        payload += _ssh_str("session")
        payload += struct.pack('>III', 0, 1048576, 32768)
        self.transport.send_packet(payload)

        pkt = self._recv_skip()
        if pkt[0] == MSG_CHANNEL_OPEN_FAILURE:
            _, off = _p_u32(pkt, 1)
            reason, _ = _p_u32(pkt, off)
            raise OSError(f"Channel open failed: {reason}")
        if pkt[0] != MSG_CHANNEL_OPEN_CONFIRM:
            raise OSError(f"Expected OPEN_CONFIRM, got {pkt[0]}")

        off = 1
        _, off = _p_u32(pkt, off)
        self._rch, off = _p_u32(pkt, off)
        self._win, off = _p_u32(pkt, off)

        # PTY request
        payload = bytes([MSG_CHANNEL_REQUEST])
        payload += struct.pack('>I', self._rch)
        payload += _ssh_str("pty-req")
        payload += b'\x01'
        payload += _ssh_str("vt100")
        payload += struct.pack('>IIII', 53, 40, 320, 320)
        payload += _ssh_str(b'\x00')
        self.transport.send_packet(payload)

        pkt = self._recv_skip()
        if pkt[0] == MSG_CHANNEL_FAILURE:
            raise OSError("PTY request failed")

        # Shell request
        payload = bytes([MSG_CHANNEL_REQUEST])
        payload += struct.pack('>I', self._rch)
        payload += _ssh_str("shell")
        payload += b'\x01'
        self.transport.send_packet(payload)

        pkt = self._recv_skip()
        if pkt[0] == MSG_CHANNEL_FAILURE:
            raise OSError("Shell request failed")

        if status_cb:
            status_cb("Shell ready!")

    def send_data(self, data):
        payload = bytes([MSG_CHANNEL_DATA])
        payload += struct.pack('>I', self._rch)
        payload += _ssh_str(data)
        self.transport.send_packet(payload)

    def close(self):
        try:
            self.transport.sock.close()
        except:
            pass


# --- VT100 UI helpers ---

_E = '\033'
_BLK, _RED, _GRN, _YEL, _BLU, _MAG, _CYN, _WHT = range(8)
_W = 53
_H = 40


def _w(s):
    picocalc.terminal.wr(s)


def _clr():
    _w(f'{_E}[2J{_E}[H')


def _at(r, c):
    _w(f'{_E}[{r};{c}H')


def _fg(c, bold=False, dim=False, bg=None):
    codes = []
    if bold:
        codes.append('1')
    if dim:
        codes.append('2')
    codes.append(str(30 + c))
    if bg is not None:
        codes.append(str(40 + bg))
    _w(f'{_E}[{";".join(codes)}m')


def _rst():
    _w(f'{_E}[0m')


def _cll():
    _w(f'{_E}[K')


def _cur(show):
    _w(f'{_E}[?25{"h" if show else "l"}')


# --- Persistence ---

def _load_profiles():
    try:
        with open('/sd/ssh_profiles.json', 'r') as f:
            return json.load(f)
    except:
        return []


def _save_profiles(p):
    with open('/sd/ssh_profiles.json', 'w') as f:
        json.dump(p, f)


def _load_hosts():
    try:
        with open('/sd/ssh_known_hosts.json', 'r') as f:
            return json.load(f)
    except:
        return {}


def _save_hosts(h):
    with open('/sd/ssh_known_hosts.json', 'w') as f:
        json.dump(h, f)


# --- Main App ---

class SSHApp:
    def __init__(self):
        self._kb = bytearray(16)
        self.profiles = _load_profiles()
        self.known = _load_hosts()
        self.session = None
        self._pin = None

    def _key(self):
        try:
            n = picocalc.terminal.readinto(self._kb)
        except OSError:
            n = None
        return bytes(self._kb[:n]) if n else None

    def _drain(self):
        picocalc.terminal.dryBuffer()
        for _ in range(10):
            try:
                if not picocalc.terminal.readinto(self._kb):
                    break
            except:
                break

    def _get_pin(self):
        if self._pin:
            return self._pin
        if not secure_creds.has_pin():
            _at(3, 2)
            _fg(_YEL, bold=True)
            _w('SET CREDENTIAL PIN')
            _rst()
            _at(4, 2)
            _fg(_WHT, dim=True)
            _w('Protects saved passwords (4-8 digits)')
            _rst()
            pin = self._input(6, 'New PIN: ', secret=True)
            if not pin or len(pin) < 4:
                return None
            confirm = self._input(7, 'Confirm: ', secret=True)
            if pin != confirm:
                _at(9, 2)
                _fg(_RED)
                _w("PINs don't match")
                _rst()
                self._wait()
                return None
            secure_creds.set_pin(pin)
            self._pin = pin
            return pin
        else:
            _at(3, 2)
            _fg(_YEL, bold=True)
            _w('ENTER PIN')
            _rst()
            for attempt in range(3):
                pin = self._input(5 + attempt, 'PIN: ', secret=True)
                if pin is None:
                    return None
                if secure_creds.verify_pin(pin):
                    self._pin = pin
                    return pin
                _at(5 + attempt, 20)
                _fg(_RED)
                _w(' Wrong')
                _rst()
            return None

    def _decrypt_pwd(self, stored):
        if not secure_creds.is_encrypted(stored):
            return stored or ''
        if not self._pin:
            return stored
        try:
            return secure_creds.decrypt_password(self._pin, stored)
        except:
            return ''

    def _input(self, row, label, default='', secret=False):
        _at(row, 2)
        _cll()
        _fg(_YEL)
        _w(label)
        _rst()
        result = list(default)
        if not secret:
            _w(default)
        else:
            _w('*' * len(default))
        col = 2 + len(label) + len(result)
        _cur(True)
        while True:
            k = self._key()
            if not k:
                utime.sleep_ms(30)
                continue
            if k == b'\x1b\x1b':
                _cur(False)
                return None
            if k in (b'\r\n', b'\r', b'\n'):
                _cur(False)
                return ''.join(result)
            if k[0] in (0x7f, 0x08) and result:
                result.pop()
                col -= 1
                _at(row, col)
                _w(' ')
                _at(row, col)
            elif len(k) == 1 and 32 <= k[0] < 127:
                result.append(chr(k[0]))
                _w('*' if secret else chr(k[0]))
                col += 1

    def _wifi(self):
        wlan = network.WLAN(network.STA_IF)
        if wlan.isconnected():
            return True
        wlan.active(True)
        try:
            with open('/sd/wifi.json', 'r') as f:
                c = json.load(f)
            ssid = c.get('ssid', '')
            pwd = c.get('password', '')
            if ssid:
                _at(3, 3)
                _fg(_YEL)
                _w(f'WiFi: {ssid}...')
                _rst()
                wlan.connect(ssid, pwd)
                for _ in range(20):
                    if wlan.isconnected():
                        _at(4, 3)
                        _fg(_GRN)
                        _w(f'IP: {wlan.ifconfig()[0]}')
                        _rst()
                        return True
                    utime.sleep_ms(500)
        except:
            pass
        _at(4, 3)
        _fg(_RED)
        _w('No WiFi. Run WiFi Manager first.')
        _rst()
        return False

    def _header(self, title):
        _at(1, 1)
        _fg(_BLK, bg=_BLK)
        _w(' ' * _W)
        _at(1, 2)
        _fg(_YEL, bold=True)
        _w('Lofi Fren')
        _fg(_WHT, dim=True)
        _w(f' / {title}')
        wlan = network.WLAN(network.STA_IF)
        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            _at(1, _W - len(ip))
            _fg(_YEL)
            _w(ip)
        _rst()
        _at(2, 1)
        _fg(_YEL, dim=True)
        _w('\x0e' + 'q' * _W + '\x0f')
        _rst()

    def _footer(self, *items):
        _at(_H - 1, 1)
        _fg(_YEL, dim=True)
        _w('\x0e' + 'q' * _W + '\x0f')
        _rst()
        _at(_H, 2)
        for k, v in items:
            _fg(_YEL, bold=True)
            _w(k)
            _rst()
            _fg(_WHT, dim=True)
            _w(f' {v}  ')
            _rst()

    def _wait(self, msg='Press any key...'):
        _at(_H - 2, 2)
        _fg(_WHT, dim=True)
        _w(msg)
        _rst()
        self._drain()
        while not self._key():
            utime.sleep_ms(50)
        self._drain()

    def draw_menu(self, sel):
        _clr()
        _cur(False)
        self._header('SSH')

        # Big logo with white-to-amber gradient
        _logo_l = [
            '#     ##  #### #',
            '#    #  # #    #',
            '#    #  # ###  #',
            '#    #  # #    #',
            '####  ##  #    #',
        ]
        _logo_r = [
            '  #### ###  #### #   #',
            '  #    #  # #    ##  #',
            '  ###  ###  ###  # # #',
            '  #    # #  #    #  ##',
            '  #    #  # #### #   #',
        ]
        for i in range(5):
            _at(4 + i, 8)
            _fg(_WHT, bold=True)
            _w(_logo_l[i])
            _fg(_YEL, bold=True)
            _w(_logo_r[i])
            _rst()

        _at(10, 8)
        _fg(_WHT, dim=True)
        _w('Secure Shell for PicoCalc')
        _rst()

        items = ['+ New Connection']
        for p in self.profiles:
            items.append(f'{p["user"]}@{p["host"]}:{p.get("port", 22)}')

        _at(12, 2)
        _fg(_YEL, bold=True)
        _w('CONNECTIONS')
        _rst()

        max_vis = min(len(items), _H - 18)
        for i in range(max_vis):
            row = 14 + i
            label = items[i]
            _at(row, 1)
            if i == sel:
                _fg(_BLK, bold=True, bg=_YEL)
                _w(f' > {label:<{_W - 4}}')
            else:
                _w('   ')
                _fg(_WHT)
                _w(label)
            _rst()

        _at(_H - 3, 2)
        _fg(_WHT, dim=True)
        _w('@lofifren')
        _rst()
        self._footer(('\x18\x19', 'Nav'), ('ENTER', 'Go'),
                      ('E', 'Edit'), ('D', 'Del'), ('ESC', 'Exit'))
        return items

    def run(self):
        if secure_creds.has_pin():
            _clr()
            _cur(False)
            self._header('SSH Client')
            pin = self._get_pin()
            if not pin:
                _cur(True)
                _clr()
                _rst()
                return
        sel = 0
        items = self.draw_menu(sel)
        while True:
            k = self._key()
            if not k:
                utime.sleep_ms(50)
                continue
            redraw = False
            if k == b'\x1b\x1b' or (len(k) == 1 and k[0] == 0x1b):
                _cur(True)
                _clr()
                _rst()
                return
            elif k == b'\x1b[A' and sel > 0:
                sel -= 1
                redraw = True
            elif k == b'\x1b[B' and sel < len(items) - 1:
                sel += 1
                redraw = True
            elif k in (b'\r\n', b'\r', b'\n'):
                if sel == 0:
                    self.new_conn()
                else:
                    p = self.profiles[sel - 1]
                    pwd = self._decrypt_pwd(p.get('password', ''))
                    self.do_connect(p['host'], p.get('port', 22),
                                    p['user'], pwd)
                self.profiles = _load_profiles()
                sel = 0
                redraw = True
            elif len(k) == 1 and k[0] in (ord('e'), ord('E')):
                if 0 < sel <= len(self.profiles):
                    self.edit_conn(sel - 1)
                    self.profiles = _load_profiles()
                    redraw = True
            elif len(k) == 1 and k[0] in (ord('d'), ord('D')):
                if 0 < sel <= len(self.profiles):
                    self.profiles.pop(sel - 1)
                    _save_profiles(self.profiles)
                    sel = max(0, sel - 1)
                    redraw = True
            if redraw:
                items = self.draw_menu(sel)

    def edit_conn(self, idx):
        p = self.profiles[idx]
        _clr()
        _cur(False)
        self._header('Edit')
        _at(4, 2)
        _fg(_YEL, bold=True)
        _w('EDIT CONNECTION')
        _rst()
        _at(5, 2)
        _fg(_WHT, dim=True)
        _w('ESC-ESC to cancel, ENTER to keep')
        _rst()

        host = self._input(7, 'Host: ', p['host'])
        if host is None:
            return
        if not host:
            host = p['host']
        port_s = self._input(8, 'Port: ', str(p.get('port', 22)))
        if port_s is None:
            return
        port = int(port_s) if port_s else p.get('port', 22)
        user = self._input(9, 'User: ', p['user'])
        if user is None:
            return
        if not user:
            user = p['user']
        _at(10, 2)
        _fg(_WHT, dim=True)
        _w('Leave blank to keep current password')
        _rst()
        pwd = self._input(11, 'Pass: ', secret=True)
        if pwd is None:
            return

        if pwd:
            if not self._pin:
                _clr()
                self._header('Edit')
                pin = self._get_pin()
                if not pin:
                    return
            enc_pwd = secure_creds.encrypt_password(self._pin, pwd)
        else:
            enc_pwd = p.get('password', '')

        self.profiles[idx] = {
            'host': host, 'port': port,
            'user': user, 'password': enc_pwd
        }
        _save_profiles(self.profiles)
        _at(13, 2)
        _fg(_GRN, bold=True)
        _w('Saved!')
        _rst()
        utime.sleep_ms(600)

    def new_conn(self):
        _clr()
        _cur(False)
        self._header('New')
        _at(4, 2)
        _fg(_YEL, bold=True)
        _w('CONNECTION DETAILS')
        _rst()
        _at(4, 2)
        _fg(_WHT, dim=True)
        _w('ESC-ESC to cancel')
        _rst()

        host = self._input(6, 'Host: ')
        if not host:
            return
        port_s = self._input(7, 'Port: ', '22')
        if port_s is None:
            return
        port = int(port_s) if port_s else 22
        user = self._input(8, 'User: ')
        if not user:
            return
        pwd = self._input(9, 'Pass: ', secret=True)
        if pwd is None:
            return

        _at(11, 2)
        _fg(_YEL)
        _w('Save profile? (y/n) ')
        _rst()
        while True:
            k = self._key()
            if not k:
                utime.sleep_ms(30)
                continue
            if len(k) == 1 and k[0] in (ord('y'), ord('Y')):
                if not self._pin:
                    _clr()
                    self._header('New')
                    pin = self._get_pin()
                    if not pin:
                        _w('Skipped (not saved)')
                        break
                enc_pwd = secure_creds.encrypt_password(self._pin, pwd)
                self.profiles.append({
                    'host': host, 'port': port,
                    'user': user, 'password': enc_pwd
                })
                _save_profiles(self.profiles)
                _w('Saved (encrypted)')
                break
            else:
                break

        self.do_connect(host, port, user, pwd)

    def do_connect(self, host, port, user, pwd):
        _clr()
        _cur(False)
        self._header(f'{user}@{host}')

        row = [4]

        def status(msg):
            _at(row[0], 3)
            _cll()
            _fg(_YEL)
            _w(msg)
            _rst()
            row[0] += 1

        if not self._wifi():
            self._wait()
            return

        gc.collect()
        try:
            self.session = _Session()

            status(f'Connecting {host}:{port}...')
            self.session.connect(host, port)
            sv = self.session.server_banner
            status(f'Server: {sv[:42]}')

            self.session.kex(status)

            # TOFU host key check
            fp = self.session.host_fp
            fp_hex = ':'.join(f'{b:02x}' for b in fp[:16])
            hk = f'{host}:{port}'

            if hk in self.known:
                if self.known[hk] != fp_hex:
                    status('!! HOST KEY CHANGED !!')
                    _at(row[0], 3)
                    _fg(_RED, bold=True)
                    _w('WARNING: possible attack!')
                    _rst()
                    row[0] += 1
                    _at(row[0], 3)
                    _fg(_YEL)
                    _w('Continue? (y/n) ')
                    _rst()
                    while True:
                        k = self._key()
                        if not k:
                            utime.sleep_ms(30)
                            continue
                        if len(k) == 1 and k[0] in (ord('y'), ord('Y')):
                            self.known[hk] = fp_hex
                            _save_hosts(self.known)
                            break
                        else:
                            raise OSError("Rejected host key")
                    row[0] += 1
                else:
                    status('Host key verified (known)')
            else:
                status(f'FP: {fp_hex}')
                _at(row[0], 3)
                _fg(_YEL)
                _w('Trust this host? (y/n) ')
                _rst()
                row[0] += 1
                while True:
                    k = self._key()
                    if not k:
                        utime.sleep_ms(30)
                        continue
                    if len(k) == 1 and k[0] in (ord('y'), ord('Y')):
                        self.known[hk] = fp_hex
                        _save_hosts(self.known)
                        break
                    else:
                        raise OSError("Host not trusted")

            self.session.authenticate(user, pwd, status)
            status('Authenticated!')
            self.session.open_shell(status)

            utime.sleep_ms(300)
            self._terminal()

        except Exception as e:
            _at(row[0] + 1, 3)
            _fg(_RED, bold=True)
            _w(f'Error: {e}')
            _rst()
            import sys
            sys.print_exception(e)
            self._wait()
        finally:
            if self.session:
                self.session.close()
                self.session = None

    def _filter(self, s):
        i = 0
        out = []
        while i < len(s):
            # Bracketed paste mode
            if s[i:i+7] == '\x1b[?2004':
                i += 8
                continue
            # OSC title sequences (ESC ] N ; ... BEL)
            if s[i:i+2] == '\x1b]':
                j = s.find('\x07', i)
                if j < 0:
                    j = s.find('\x1b\\', i)
                i = j + 1 if j >= 0 else len(s)
                continue
            # zsh PROMPT_SP (reverse-video % marker)
            if s[i:i+5] == '\x1b[7m%':
                j = i + 5
                while j < len(s) and s[j] != '\n':
                    j += 1
                i = j
                continue
            out.append(s[i])
            i += 1
        return ''.join(out)

    def _terminal(self):
        session = self.session

        # Init remote shell: disable zsh PROMPT_SP, set TERM, clear
        session.send_data(
            b'unsetopt PROMPT_SP PROMPT_CR 2>/dev/null;'
            b'export TERM=vt100;clear\n'
        )

        _clr()
        _cur(True)
        _at(1, 1)

        poller = select.poll()
        poller.register(session.transport.sock, select.POLLIN)

        kb = bytearray(32)

        # Let Ctrl+C pass through to SSH instead of raising KeyboardInterrupt
        import micropython
        micropython.kbd_intr(-1)

        try:
            while True:
                # Check keyboard first
                try:
                    count = picocalc.terminal.readinto(kb)
                except OSError:
                    count = None
                if count:
                    kd = bytes(kb[:count])
                    if kd == b'\x1b\x1b':
                        _w("\r\n[Disconnected]\r\n")
                        return
                    try:
                        session.send_data(kd)
                    except OSError:
                        _w("\r\n[Send failed]\r\n")
                        return

                # Read SSH data (one packet per cycle)
                evts = poller.poll(10)
                if not evts:
                    continue
                try:
                    pkt = session.transport.recv_packet()
                except OSError:
                    _w("\r\n[Connection lost]\r\n")
                    return
                t = pkt[0]
                if t == MSG_CHANNEL_DATA:
                    off = 1
                    _, off = _p_u32(pkt, off)
                    data, _ = _p_str(pkt, off)
                    if data:
                        text = self._filter(
                            data.decode('utf-8', 'replace'))
                        if text:
                            _w(text)
                        adj = bytes([MSG_CHANNEL_WINDOW_ADJUST])
                        adj += struct.pack('>II', session._rch, len(data))
                        session.transport.send_packet(adj)
                elif t == MSG_CHANNEL_EXTENDED_DATA:
                    off = 1
                    _, off = _p_u32(pkt, off)
                    _, off = _p_u32(pkt, off)
                    data, _ = _p_str(pkt, off)
                    if data:
                        _w(data.decode('utf-8', 'replace'))
                elif t in (MSG_CHANNEL_EOF, MSG_CHANNEL_CLOSE):
                    _w("\r\n[Connection closed]\r\n")
                    return
                elif t == MSG_CHANNEL_WINDOW_ADJUST:
                    off = 1
                    _, off = _p_u32(pkt, off)
                    adj_val, _ = _p_u32(pkt, off)
                    session._win += adj_val
                elif t == MSG_GLOBAL_REQUEST:
                    session.transport.send_packet(
                        bytes([MSG_REQUEST_FAILURE]))

        except Exception as e:
            _w(f"\r\n[Error: {e}]\r\n")
        finally:
            micropython.kbd_intr(3)
            _cur(False)
            self._wait()


def main():
    gc.collect()
    try:
        app = SSHApp()
        app.run()
    except Exception as e:
        _cur(True)
        _rst()
        _clr()
        print(f'SSH error: {e}')
        import sys
        sys.print_exception(e)


if __name__ == '__main__':
    main()
