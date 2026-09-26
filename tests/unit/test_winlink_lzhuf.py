"""LZHUF in the B2 container, against wl2k-go's test data.

`tests/unit/data/winlink/` is wl2k-go's `lzhuf/testdata` (MIT, LA5NTA):
the Gettysburg Address, and a real B2 message with a JPEG attached, each
with its compressed form as wl2k-go writes it.
"""

from kissterm._isolate import isolate

isolate()

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from kissterm.winlink import lzhuf  # noqa: E402

DATA = Path(__file__).parent / "data" / "winlink"
FILES = ["gettysburg.txt", "LPE5NXDVLVSQ.b2f"]


@pytest.mark.parametrize("name", FILES)
def test_decompress_matches_wl2k_go(name):
    raw = (DATA / name).read_bytes()
    assert lzhuf.decompress((DATA / f"{name}.lzh").read_bytes()) == raw


@pytest.mark.parametrize("name", FILES)
def test_compress_writes_the_same_bytes_as_wl2k_go(name):
    raw = (DATA / name).read_bytes()
    assert lzhuf.compress(raw) == (DATA / f"{name}.lzh").read_bytes()


@pytest.mark.parametrize("data", [b"", b"a", b"aaaa" * 500, bytes(range(256)) * 20,
                                  b"x" * 59 + b"y" * 61])
def test_round_trip(data):
    assert lzhuf.decompress(lzhuf.compress(data)) == data


def test_empty_is_a_header_only():
    assert len(lzhuf.compress(b"")) == 6


def test_damaged_data_is_refused_not_half_returned():
    packed = bytearray((DATA / "gettysburg.txt.lzh").read_bytes())
    packed[100] ^= 0x10
    with pytest.raises(lzhuf.LzhufError, match="CRC"):
        lzhuf.decompress(bytes(packed))


def test_a_short_stream_is_refused():
    packed = lzhuf.compress(b"The quick brown fox " * 20)
    cut = packed[:-10]
    # The CRC covers the bits, so fix it up to reach the length check.
    body = cut[2:]
    cut = lzhuf.crc16(body).to_bytes(2, "little") + body
    with pytest.raises(lzhuf.LzhufError):
        lzhuf.decompress(cut)
