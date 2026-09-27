"""The RMS gateway list (`kissterm/winlink/gateways.py`), against a small
reply in the shape Pat's shipped sample has. The live API needs a key
kissterm does not have yet, so the fetch is tested against a local HTTP
server only."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import json  # noqa: E402
import threading  # noqa: E402
import urllib.parse  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from kissterm.winlink import gateways  # noqa: E402

SAMPLE = (Path(__file__).parent / "data" / "winlink" / "gateway_status.json").read_bytes()
#: Waterboro, Maine (FN43).
HOME = (43.54, -70.72)


def test_every_well_formed_channel_is_read_and_the_rest_skipped():
    channels = gateways.parse(SAMPLE)
    assert [(c.callsign, c.frequency_hz) for c in channels] == [
        ("W1AW-10", 145050000), ("W1AW-10", 145070000),
        ("N1ABC-10", 145010000), ("N1ABC-10", 7101200),
        ("K1XYZ-10", 144990000),
        ("W9BAD-10", 145090000),
    ]
    first = channels[0]
    assert first.modes == "Packet 1200" and first.grid == "FN31PR" and first.baud == "1200"
    assert first.frequency == "145.050 MHz"


def test_text_from_the_reply_is_printable_only():
    """Right-to-left overrides and bells never reach a widget."""
    bad = [c for c in gateways.parse(SAMPLE) if c.callsign.startswith("W9BAD")][0]
    assert bad.callsign == "W9BAD-10"


def test_not_a_gateway_list_is_an_error_not_an_empty_list():
    for data in (b"<html>", b"[]", b'{"Gateways": 3}'):
        with pytest.raises(ValueError):
            gateways.parse(data)


def test_nearest_first_and_unknown_distance_last():
    channels = gateways.parse(SAMPLE, lat=HOME[0], lon=HOME[1])
    packet = gateways.nearest(channels, "packet")
    assert [c.callsign for c in packet] == ["N1ABC-10", "W1AW-10", "K1XYZ-10", "W9BAD-10"]
    assert packet[0].distance_mi is not None and packet[0].distance_mi < 30
    assert 150 < packet[1].distance_mi < 200
    assert packet[2].distance_mi is None and packet[3].distance_mi is None  # no grid; a bad grid
    assert len(gateways.nearest(channels, "packet", limit=2)) == 2


def test_modes_are_filtered_as_pat_does():
    channels = gateways.parse(SAMPLE)
    calls = lambda mode: [(c.callsign, c.modes) for c in gateways.nearest(channels, mode)]  # noqa: E731
    assert calls("vara fm") == [("W1AW-10", "VARA FM")]
    assert calls("vara hf") == [("N1ABC-10", "VARA 2750")]
    assert calls("") and len(calls("")) == 6


def test_the_cache_is_replaced_whole(tmp_path):
    path = gateways.cache_path(tmp_path)
    assert gateways.load_cached(path) is None
    gateways.save_cached(path, SAMPLE)
    data, when = gateways.load_cached(path)
    assert data == SAMPLE and when > 0
    assert not path.with_suffix(".partial").exists()


def test_no_key_means_no_request():
    with pytest.raises(gateways.NoAccessKey):
        gateways.fetch("", url="http://127.0.0.1:9/never")
    assert gateways.ACCESS_KEY == "", "kissterm's own key only, once issued"


def test_parameters_are_checked_before_any_request():
    with pytest.raises(ValueError):
        gateways.fetch("k", mode="Packet&key=x", url="http://127.0.0.1:9/never")
    with pytest.raises(ValueError):
        gateways.fetch("k", service_codes=("PUBLIC&x",), url="http://127.0.0.1:9/never")


class _Server:
    """A local stand-in for api.winlink.org that records the request."""

    def __init__(self, status: int, body: bytes) -> None:
        seen: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers["Content-Length"])
                seen["form"] = urllib.parse.parse_qs(self.rfile.read(length).decode())
                seen["agent"] = self.headers["User-Agent"]
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.seen = seen
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/gateway/status.json"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_the_request_is_the_documented_form():
    server = _Server(200, SAMPLE)
    try:
        data = gateways.fetch("TESTKEY", history_hours=99, url=server.url)
    finally:
        server.close()
    assert data == SAMPLE
    form = server.seen["form"]
    assert form == {"Mode": ["AnyAll"], "HistoryHours": ["48"], "key": ["TESTKEY"],
                    "ServiceCodes": ["PUBLIC"]}
    assert server.seen["agent"].startswith("kissterm/")


def test_a_refused_or_wrong_reply_says_so():
    server = _Server(403, b"Forbidden")
    try:
        with pytest.raises(gateways.FetchError, match="403"):
            gateways.fetch("BADKEY", url=server.url)
    finally:
        server.close()
    server = _Server(200, json.dumps({"ResponseStatus": {"ErrorCode": "x"}}).encode())
    try:
        with pytest.raises(gateways.FetchError, match="not a gateway list"):
            gateways.fetch("KEY", url=server.url)
    finally:
        server.close()


def test_age_text():
    assert gateways.age_text(0, now=30) == "fetched just now"
    assert gateways.age_text(0, now=3 * 86400 + 5) == "fetched 3 days ago"
    assert gateways.age_text(0, now=3600) == "fetched 1 hour ago"
