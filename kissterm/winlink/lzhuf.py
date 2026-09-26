"""LZHUF, the compression every B2 message travels in.

A B2F message goes over the air compressed with LZHUF (LZSS with an
adaptive Huffman coder: Okumura, Yoshizaki and Rikitake, 1988), in FBB's
B2 container:

    CRC16 (2 bytes, little-endian) | length (4 bytes, LE) | compressed bits

The length is of the uncompressed data; the CRC is the XMODEM variant of
CRC-CCITT over the length and the compressed bits, with two zero bytes fed
in after them (VE4KLM, JNOS 2: "Airmail and Winlink 2000 are using the
Xmodem variation of CRC-CCITT").

**Sources.** A port of JNOS 2's `lzhuf.c` (github.com/mlangelaar/jnos2),
with the B2 container and bit reader as wl2k-go `lzhuf/` does them (MIT,
LA5NTA). The lzhuf.c authors' terms, as Russell Marks collected them in
2001: "Use, distribute, and modify this program freely". Tested against
wl2k-go's test data, which includes a real message with a JPEG attached
(`tests/unit/data/winlink/`, `tests/unit/test_winlink_lzhuf.py`).

The encoder writes the same bytes as wl2k-go's for both test files, CRC
included, so what it sends is what Pat would send. A bad CRC, a short
stream or a wrong length raises `LzhufError` rather than returning part of
a message: a message is filed whole or not at all.
"""

from __future__ import annotations

import struct

_N = 2048  # ring buffer size
_F = 60  # lookahead size
_THRESHOLD = 2  # a match no longer than this is sent as literals
_NIL = _N  # no tree node
_N_CHAR = 256 - _THRESHOLD + _F  # literals, then match lengths
_T = _N_CHAR * 2 - 1  # Huffman table size
_R = _T - 1  # Huffman root
_MAX_FREQ = 0x8000  # rebuild the tree at this root frequency

# The upper 6 bits of a match position, Huffman-coded by a fixed table:
# (code length, number of codes of that length), codes counting up from 0.
_P_LENGTHS = ((3, 1), (4, 3), (5, 8), (6, 12), (7, 24), (8, 16))


def _position_tables() -> tuple[list[int], list[int], list[int], list[int]]:
    p_code: list[int] = []
    p_len: list[int] = []
    code = 0
    for length, count in _P_LENGTHS:
        for _ in range(count):
            p_code.append(code)
            p_len.append(length)
            code += 1 << (8 - length)
    d_code = [0] * 256
    d_len = [0] * 256
    for index, (code, length) in enumerate(zip(p_code, p_len)):
        for byte in range(code, code + (1 << (8 - length))):
            d_code[byte] = index
            d_len[byte] = length
    return p_code, p_len, d_code, d_len


_P_CODE, _P_LEN, _D_CODE, _D_LEN = _position_tables()


def _crc_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        table.append(crc & 0xFFFF)
    return table


_CRC_TABLE = _crc_table()


def crc16(data: bytes) -> int:
    """The B2 header's CRC of `data` (the length and compressed bits)."""
    crc = 0
    for byte in (*data, 0, 0):
        crc = ((crc << 8) & 0xFF00) ^ _CRC_TABLE[(crc >> 8) & 0xFF] ^ byte
    return crc


class LzhufError(ValueError):
    """Compressed data that is damaged, cut short or fails its CRC."""


class _Huffman:
    """The adaptive Huffman tree both directions keep in step."""

    def __init__(self) -> None:
        self.freq = [0] * (_T + 1)
        self.prnt = [0] * (_T + _N_CHAR)
        self.son = [0] * _T
        for i in range(_N_CHAR):
            self.freq[i] = 1
            self.son[i] = i + _T
            self.prnt[i + _T] = i
        i, j = 0, _N_CHAR
        while j <= _R:
            self.freq[j] = self.freq[i] + self.freq[i + 1]
            self.son[j] = i
            self.prnt[i] = self.prnt[i + 1] = j
            i += 2
            j += 1
        self.freq[_T] = 0xFFFF
        self.prnt[_R] = 0

    def _reconst(self) -> None:
        freq, son, prnt = self.freq, self.son, self.prnt
        j = 0
        for i in range(_T):
            if son[i] >= _T:
                freq[j] = (freq[i] + 1) // 2
                son[j] = son[i]
                j += 1
        i, j = 0, _N_CHAR
        while j < _T:
            f = freq[j] = freq[i] + freq[i + 1]
            k = j - 1
            while f < freq[k]:
                k -= 1
            k += 1
            freq[k + 1:j + 1] = freq[k:j]
            freq[k] = f
            son[k + 1:j + 1] = son[k:j]
            son[k] = i
            i += 2
            j += 1
        for i in range(_T):
            k = son[i]
            if k >= _T:
                prnt[k] = i
            else:
                prnt[k] = prnt[k + 1] = i

    def update(self, c: int) -> None:
        freq, son, prnt = self.freq, self.son, self.prnt
        if freq[_R] == _MAX_FREQ:
            self._reconst()
        c = prnt[c + _T]
        while True:
            freq[c] += 1
            k = freq[c]
            if k > freq[c + 1]:
                l = c + 1
                while k > freq[l + 1]:
                    l += 1
                freq[c] = freq[l]
                freq[l] = k
                i = son[c]
                prnt[i] = l
                if i < _T:
                    prnt[i + 1] = l
                j = son[l]
                son[l] = i
                prnt[j] = c
                if j < _T:
                    prnt[j + 1] = c
                son[c] = j
                c = l
            c = prnt[c]
            if c == 0:
                break


class _Encoder:
    def __init__(self) -> None:
        self.huff = _Huffman()
        self.text = bytearray(_N + _F - 1)
        self.dad = [_NIL] * (_N + 1)
        self.lson = [_NIL] * (_N + 1)
        self.rson = [_NIL] * (_N + 257)
        self.match_length = 0
        self.match_position = 0
        self.out = bytearray()
        self.putbuf = 0
        self.putlen = 0

    # -- the LZSS dictionary: a binary tree per first byte --

    def insert(self, r: int) -> None:
        text, dad, lson, rson = self.text, self.dad, self.lson, self.rson
        cmp = 1
        p = _N + 1 + text[r]
        rson[r] = lson[r] = _NIL
        self.match_length = 0
        while True:
            if cmp >= 0:
                if rson[p] != _NIL:
                    p = rson[p]
                else:
                    rson[p] = r
                    dad[r] = p
                    return
            else:
                if lson[p] != _NIL:
                    p = lson[p]
                else:
                    lson[p] = r
                    dad[r] = p
                    return
            i = 1
            cmp = 0
            while i < _F:
                cmp = text[r + i] - text[p + i]
                if cmp:
                    break
                i += 1
            if i > _THRESHOLD:
                if i > self.match_length:
                    self.match_position = ((r - p) & (_N - 1)) - 1
                    self.match_length = i
                    if i >= _F:
                        break
                if i == self.match_length:
                    c = ((r - p) & (_N - 1)) - 1
                    if c < self.match_position:
                        self.match_position = c
        dad[r] = dad[p]
        lson[r] = lson[p]
        rson[r] = rson[p]
        dad[lson[p]] = r
        dad[rson[p]] = r
        if rson[dad[p]] == p:
            rson[dad[p]] = r
        else:
            lson[dad[p]] = r
        dad[p] = _NIL

    def delete(self, p: int) -> None:
        dad, lson, rson = self.dad, self.lson, self.rson
        if dad[p] == _NIL:
            return
        if rson[p] == _NIL:
            q = lson[p]
        elif lson[p] == _NIL:
            q = rson[p]
        else:
            q = lson[p]
            if rson[q] != _NIL:
                while rson[q] != _NIL:
                    q = rson[q]
                rson[dad[q]] = lson[q]
                dad[lson[q]] = dad[q]
                lson[q] = lson[p]
                dad[lson[p]] = q
            rson[q] = rson[p]
            dad[rson[p]] = q
        dad[q] = dad[p]
        if rson[dad[p]] == p:
            rson[dad[p]] = q
        else:
            lson[dad[p]] = q
        dad[p] = _NIL

    # -- the bit writer and the two code kinds --

    def put_code(self, length: int, code: int) -> None:
        self.putbuf = (self.putbuf | (code >> self.putlen)) & 0xFFFF
        self.putlen += length
        if self.putlen >= 8:
            self.out.append(self.putbuf >> 8)
            self.putlen -= 8
            if self.putlen >= 8:
                self.out.append(self.putbuf & 0xFF)
                self.putlen -= 8
                self.putbuf = (code << (length - self.putlen)) & 0xFFFF
            else:
                self.putbuf = (self.putbuf << 8) & 0xFFFF

    def encode_char(self, c: int) -> None:
        prnt = self.huff.prnt
        i = j = 0
        k = prnt[c + _T]
        while True:
            i >>= 1
            if k & 1:
                i += 0x8000
            j += 1
            k = prnt[k]
            if k == _R:
                break
        self.put_code(j, i)
        self.huff.update(c)

    def encode_position(self, c: int) -> None:
        i = c >> 6
        self.put_code(_P_LEN[i], _P_CODE[i] << 8)
        self.put_code(6, (c & 0x3F) << 10)

    def run(self, data: bytes) -> bytes:
        text = self.text
        size = len(data)
        s, r = 0, _N - _F
        for i in range(r):
            text[i] = 0x20
        length = min(_F, size)
        text[r:r + length] = data[:length]
        pos = length
        if length == 0:
            return b""
        for i in range(1, _F + 1):
            self.insert(r - i)
        self.insert(r)
        while length > 0:
            if self.match_length > length:
                self.match_length = length
            if self.match_length <= _THRESHOLD:
                self.match_length = 1
                self.encode_char(text[r])
            else:
                self.encode_char(255 - _THRESHOLD + self.match_length)
                self.encode_position(self.match_position)
            last = self.match_length
            i = 0
            while i < last and pos < size:
                self.delete(s)
                c = data[pos]
                pos += 1
                text[s] = c
                if s < _F - 1:
                    text[s + _N] = c
                s = (s + 1) & (_N - 1)
                r = (r + 1) & (_N - 1)
                self.insert(r)
                i += 1
            while i < last:
                i += 1
                self.delete(s)
                s = (s + 1) & (_N - 1)
                r = (r + 1) & (_N - 1)
                length -= 1
                if length:
                    self.insert(r)
        if self.putlen:
            self.out.append(self.putbuf >> 8)
        return bytes(self.out)


def compress(data: bytes) -> bytes:
    """`data` in the B2 container: CRC16, length, LZHUF bits."""
    body = struct.pack("<I", len(data)) + _Encoder().run(bytes(data))
    return struct.pack("<H", crc16(body)) + body


class _Bits:
    """Most significant bit first; reading past the end is an error."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.index = 0
        self.buffer = 0
        self.count = 0

    def read(self, bits: int) -> int:
        while bits > self.count:
            if self.index >= len(self.data):
                raise LzhufError("compressed data ends early")
            self.buffer = ((self.buffer << 8) | self.data[self.index]) & 0xFFFFFFFF
            self.index += 1
            self.count += 8
        self.count -= bits
        return (self.buffer >> self.count) & ((1 << bits) - 1)


def decompress(data: bytes) -> bytes:
    """The original bytes from a B2 container. Raises `LzhufError` on a
    bad CRC, a short stream or a length that does not match."""
    if len(data) < 6:
        raise LzhufError("too short for a B2 header")
    (expect_crc,) = struct.unpack_from("<H", data)
    if crc16(data[2:]) != expect_crc:
        raise LzhufError("CRC does not match")
    (size,) = struct.unpack_from("<I", data, 2)
    bits = _Bits(data[6:])
    huff = _Huffman()
    son = huff.son
    text = bytearray(b" " * (_N - _F)) + bytearray(_F)
    r = _N - _F
    out = bytearray()
    while len(out) < size:
        c = son[_R]
        while c < _T:
            c = son[c + bits.read(1)]
        c -= _T
        huff.update(c)
        if c < 256:
            out.append(c)
            text[r] = c
            r = (r + 1) & (_N - 1)
            continue
        i = bits.read(8)
        high = _D_CODE[i] << 6
        extra = _D_LEN[i] - 2
        i = (i << extra) | bits.read(extra)
        start = (r - (high | (i & 0x3F)) - 1) & (_N - 1)
        for k in range(c - 255 + _THRESHOLD):
            c = text[(start + k) & (_N - 1)]
            out.append(c)
            text[r] = c
            r = (r + 1) & (_N - 1)
    if len(out) != size:
        raise LzhufError(f"length is {len(out)}, header says {size}")
    return bytes(out)
