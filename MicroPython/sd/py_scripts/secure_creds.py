"""
Secure credential storage for PicoCalc apps.
PIN-based AES-128-CBC encryption for passwords at rest.
"""
import uhashlib
import ucryptolib
import struct
import urandom
import json

_PIN_FILE = '/sd/cred_pin.json'
_ENC_PREFIX = 'ENC:'


def _randbytes(n):
    buf = bytearray(n)
    for i in range(0, n, 4):
        v = urandom.getrandbits(32)
        e = min(i + 4, n)
        buf[i:e] = struct.pack('>I', v)[:e - i]
    return bytes(buf)


def _derive_key(pin):
    h = uhashlib.sha256()
    h.update(pin.encode())
    return h.digest()[:16]


def _pin_hash(pin):
    h = uhashlib.sha256()
    h.update(b'picocalc_pin:')
    h.update(pin.encode())
    d = h.digest()
    return ''.join(f'{b:02x}' for b in d)


def _pad16(data):
    n = 16 - (len(data) % 16)
    return data + bytes([n] * n)


def _unpad16(data):
    n = data[-1]
    if n < 1 or n > 16:
        raise ValueError("Bad padding")
    return data[:-n]


def _to_hex(b):
    return ''.join(f'{x:02x}' for x in b)


def _from_hex(s):
    out = bytearray(len(s) // 2)
    for i in range(0, len(s), 2):
        out[i // 2] = int(s[i:i + 2], 16)
    return bytes(out)


def has_pin():
    try:
        with open(_PIN_FILE, 'r') as f:
            d = json.load(f)
        return bool(d.get('hash'))
    except:
        return False


def verify_pin(pin):
    try:
        with open(_PIN_FILE, 'r') as f:
            d = json.load(f)
        return d.get('hash') == _pin_hash(pin)
    except:
        return False


def set_pin(pin):
    with open(_PIN_FILE, 'w') as f:
        json.dump({'hash': _pin_hash(pin)}, f)


def encrypt_password(pin, plaintext):
    if not plaintext:
        return plaintext
    key = _derive_key(pin)
    iv = _randbytes(16)
    padded = _pad16(plaintext.encode())
    aes = ucryptolib.aes(key, 2, iv)
    ct = aes.encrypt(padded)
    return _ENC_PREFIX + _to_hex(iv) + ':' + _to_hex(ct)


def decrypt_password(pin, stored):
    if not stored or not isinstance(stored, str):
        return stored or ''
    if not stored.startswith(_ENC_PREFIX):
        return stored
    parts = stored[len(_ENC_PREFIX):].split(':')
    if len(parts) != 2:
        return stored
    iv = _from_hex(parts[0])
    ct = _from_hex(parts[1])
    key = _derive_key(pin)
    aes = ucryptolib.aes(key, 2, iv)
    padded = aes.decrypt(ct)
    return _unpad16(padded).decode()


def is_encrypted(val):
    return isinstance(val, str) and val.startswith(_ENC_PREFIX)
