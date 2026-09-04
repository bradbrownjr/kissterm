"""Tests for the APRS decoder/encoder and the MHEARD table.

Most sample packets below are literal APRS payloads of the kind seen on RF
(the weather report is the sample from the APRS 1.0.1 spec appendix). The
compressed-position and Mic-E samples are generated from this module's own
inverse formulas rather than copied from a public capture -- transcribing a
13-byte base-91 string or a binary Mic-E destination callsign by hand from
memory is exactly the kind of transcription error this suite exists to catch,
so those two fixtures are computed once (see the comment above each) and
then pinned as literals, with the expected decoded values checked against
the same physical formulas the APRS spec defines (base-91 lat/lon, and the
byte-28 longitude/speed/course scheme), not merely against whatever the
encoder happened to produce.
"""

from __future__ import annotations

from kissterm.ax25.address import AX25Address, AX25Path
from kissterm.ax25.frame import AX25Frame, PID_NO_LAYER3, UType
from kissterm.aprs.parse import (
    Message,
    ObjectReport,
    Position,
    Status,
    Telemetry,
    ThirdParty,
    WeatherReport,
    format_packet,
    parse_packet,
)
from kissterm.heard import HeardTable


def _ui_frame(dest: str, src: str, info: bytes, via: tuple[str, ...] = ()) -> AX25Frame:
    path = AX25Path(
        destination=AX25Address.parse(dest),
        source=AX25Address.parse(src),
        repeaters=tuple(AX25Address.parse(v) for v in via),
    )
    return AX25Frame.u_frame(path, UType.UI, pid=PID_NO_LAYER3, command=True, info=info)


# -- position: uncompressed ----------------------------------------------


def test_uncompressed_position_no_ambiguity():
    frame = _ui_frame("APRS", "N1ABC-9", b"!4903.50N/07201.75W>045/030/A=001234Mobile")
    pkt = parse_packet(frame)
    assert pkt is not None
    assert pkt.kind == "position"
    pos = pkt.data
    assert isinstance(pos, Position)
    assert round(pos.latitude, 5) == round(49 + 3.50 / 60, 5)
    assert round(pos.longitude, 5) == round(-(72 + 1.75 / 60), 5)
    assert pos.symbol_table == "/"
    assert pos.symbol_code == ">"
    assert pos.course == 45
    assert pos.speed_knots == 30.0
    assert pos.altitude_ft == 1234
    assert pos.ambiguity == 0
    assert pos.comment == "Mobile"
    assert format_packet(pkt) == 'N1ABC-9 pos 49.0583,-72.0292 car 45deg 30kt 1234ft "Mobile"'


def test_uncompressed_position_with_ambiguity():
    # Ambiguity level 1: the hundredths-of-a-minute digit is blanked in both
    # latitude and longitude, per the APRS spec's position-ambiguity table.
    frame = _ui_frame("APRS", "N1ABC-9", b"!4903.5 N/07201.7 W-blank last digit")
    pkt = parse_packet(frame)
    assert pkt.kind == "position"
    pos = pkt.data
    assert pos.ambiguity == 1
    # Blanked digits are treated as zero, so 4903.50 -> 4903.5(0).
    assert round(pos.latitude, 4) == round(49 + 3.50 / 60, 4)
    assert round(pos.longitude, 4) == round(-(72 + 1.70 / 60), 4)
    assert pos.symbol_code == "-"


def test_uncompressed_position_messaging_flag():
    # '=' means messaging-capable, '!' does not; both are position-no-timestamp.
    live = parse_packet(_ui_frame("APRS", "N1ABC", b"=4903.50N/07201.75W>Messaging capable"))
    plain = parse_packet(_ui_frame("APRS", "N1ABC", b"!4903.50N/07201.75W>No messaging"))
    assert live.kind == plain.kind == "position"
    assert live.data.comment == "Messaging capable"
    assert plain.data.comment == "No messaging"


def test_position_with_timestamp():
    frame = _ui_frame("APRS", "N1ABC-9", b"/092345z4903.50N/07201.75W>Timestamped")
    pkt = parse_packet(frame)
    assert pkt.kind == "position"
    assert pkt.data.timestamp == "092345z"
    assert pkt.data.comment == "Timestamped"


# -- position: compressed -------------------------------------------------


def test_compressed_position():
    # Generated from this module's own inverse of the compressed-position
    # formula for lat=49.5, lon=-72.75, course=88deg, speed~=36.2kt:
    #   lat_val = round((90 - lat) * 380926); lon_val = round((lon+180) * 190463)
    #   base91-encode each to 4 chars, symbol '>' , c = chr(33 + course//4),
    #   s = chr(33 + round(log(speed+1, 1.08))), t = chr(33) (arbitrary valid type byte)
    frame = _ui_frame("APRS", "N1ABC-9", b"=/5L!!<*e8>7P!Compressed")
    pkt = parse_packet(frame)
    assert pkt.kind == "position"
    pos = pkt.data
    assert pos.compressed is True
    assert pos.symbol_table == "/"
    assert pos.symbol_code == ">"
    assert abs(pos.latitude - 49.5) < 0.001
    assert abs(pos.longitude - (-72.75)) < 0.001
    assert pos.course == 88
    assert pos.speed_knots is not None and abs(pos.speed_knots - 36.2) < 1.0
    assert pos.comment == "Compressed"


def test_compressed_position_precalc_range():
    # c1 == '{' flags the cs pair as a pre-calculated range rather than
    # course/speed -- s value 10 -> range = 2 * 1.08**10.
    frame = _ui_frame("APRS", "N1ABC-9", b"=/5L!!<*e8>{+!Range flagged")
    pkt = parse_packet(frame)
    pos = pkt.data
    assert pos.course is None
    assert pos.speed_knots is None
    assert pos.precalc_range_mi is not None
    assert abs(pos.precalc_range_mi - 2 * (1.08**10)) < 0.01


# -- Mic-E ------------------------------------------------------------------


def test_mic_e_northern_western_hemisphere():
    # Destination "42CB3A" and info generated by this module's own Mic-E
    # inverse encoder for: lat=42 21.30' N, lon=071 03.50' W, course=45,
    # speed=30kt, message bits (0,0,1) -> "En Route", symbol '/'+'>'  (car).
    frame = _ui_frame("42CB3A", "N1ABC-9", b"`c\x1fN\x1f\x1cI>/Mobile")
    pkt = parse_packet(frame)
    assert pkt is not None
    assert pkt.kind == "mic-e"
    pos = pkt.data
    assert isinstance(pos, Position)
    assert round(pos.latitude, 4) == round(42 + 21.30 / 60, 4)
    assert round(pos.longitude, 4) == round(-(71 + 3.50 / 60), 4)
    assert pos.course == 45
    assert pos.speed_knots == 30.0
    assert pos.symbol_table == "/"
    assert pos.symbol_code == ">"
    assert pos.mic_e_message == "En Route"
    assert pos.comment == "Mobile"


def test_mic_e_southern_eastern_hemisphere():
    # Destination "DDF100" and info generated the same way for: lat=33 51.00'
    # S, lon=151 12.00' E, course=270, speed=12kt, message bits (1,1,1) ->
    # "Emergency".
    frame = _ui_frame("DDF100", "N1ABC-9", b"`\xb3(\x1c\x1d2b>/Sydney")
    pkt = parse_packet(frame)
    assert pkt.kind == "mic-e"
    pos = pkt.data
    assert round(pos.latitude, 4) == round(-(33 + 51.00 / 60), 4)
    assert round(pos.longitude, 4) == round(151 + 12.00 / 60, 4)
    assert pos.course == 270
    assert pos.speed_knots == 12.0
    assert pos.mic_e_message == "Emergency"


def test_mic_e_old_data_type():
    # The apostrophe data-type identifier ("old" Mic-E, as opposed to the
    # backtick "current") uses the same destination-address decode.
    frame = _ui_frame("42CB3A", "N1ABC-9", b"'c\x1fN\x1f\x1cI>/")
    pkt = parse_packet(frame)
    assert pkt.kind == "mic-e"
    assert pkt.data.mic_e_message == "En Route"


# -- messages ---------------------------------------------------------------


def test_message_and_ack():
    msg_frame = _ui_frame("APRS", "N0CALL-1", b":N1ABC-9  :Hello there{001")
    msg_pkt = parse_packet(msg_frame)
    assert msg_pkt.kind == "message"
    msg = msg_pkt.data
    assert isinstance(msg, Message)
    assert msg.addressee == "N1ABC-9"
    assert msg.text == "Hello there"
    assert msg.number == "001"
    assert not msg.is_ack and not msg.is_rej

    ack_frame = _ui_frame("APRS", "N1ABC-9", b":N0CALL-1 :ack001")
    ack_pkt = parse_packet(ack_frame)
    assert ack_pkt.kind == "message"
    ack_msg = ack_pkt.data
    assert ack_msg.is_ack
    assert ack_msg.number == "001"
    assert ack_msg.addressee == "N0CALL-1"


def test_message_reject():
    frame = _ui_frame("APRS", "N1ABC-9", b":N0CALL   :rej042")
    pkt = parse_packet(frame)
    assert pkt.data.is_rej
    assert pkt.data.number == "042"


# -- status, object, weather, telemetry, third-party ------------------------


def test_status():
    frame = _ui_frame("APRS", "N1ABC-9", b">Test status message")
    pkt = parse_packet(frame)
    assert pkt.kind == "status"
    assert isinstance(pkt.data, Status)
    assert pkt.data.text == "Test status message"


def test_object_report():
    frame = _ui_frame("APRS", "N1ABC-9", b";LEADER   *092345z4903.50N/07201.75W>Leading the pack")
    pkt = parse_packet(frame)
    assert pkt.kind == "object"
    obj = pkt.data
    assert isinstance(obj, ObjectReport)
    assert obj.name == "LEADER"
    assert obj.alive is True
    assert obj.timestamp == "092345z"
    assert obj.position is not None
    assert round(obj.position.latitude, 4) == round(49 + 3.50 / 60, 4)


def test_object_report_killed():
    frame = _ui_frame("APRS", "N1ABC-9", b";LEADER   _092345z4903.50N/07201.75W>Gone")
    pkt = parse_packet(frame)
    assert pkt.data.alive is False


def test_item_report():
    frame = _ui_frame("APRS", "N1ABC-9", b")MOBIL!4903.50N/07201.75W>Mobile item")
    pkt = parse_packet(frame)
    assert pkt.kind == "item"
    item = pkt.data
    assert item.name == "MOBIL"
    assert item.alive is True
    assert item.is_item is True


def test_weather_report():
    # Verbatim positionless-weather example from the APRS 1.0.1 spec appendix.
    frame = _ui_frame("APRS", "N1ABC-9", b"_10090556c220s004g005t077r000p000P000h50b09900wRSW")
    pkt = parse_packet(frame)
    assert pkt.kind == "weather"
    wx = pkt.data
    assert isinstance(wx, WeatherReport)
    assert wx.wind_course == 220
    assert wx.wind_speed_mph == 4
    assert wx.wind_gust_mph == 5
    assert wx.temperature_f == 77
    assert wx.humidity_pct == 50
    assert wx.pressure_tenths_mb == 9900
    assert wx.timestamp == "10090556"


def test_telemetry():
    frame = _ui_frame("APRS", "N1ABC-9", b"T#005,123,045,067,000,255,00000000")
    pkt = parse_packet(frame)
    assert pkt.kind == "telemetry"
    tel = pkt.data
    assert isinstance(tel, Telemetry)
    assert tel.sequence == "005"
    assert tel.analog == (123.0, 45.0, 67.0, 0.0, 255.0)
    assert tel.digital == "00000000"


def test_third_party_traffic():
    frame = _ui_frame("APRS", "WIDE1-1", b"}N1ABC>APRS,WIDE2-1:!4903.50N/07201.75W-Relayed")
    pkt = parse_packet(frame)
    assert pkt.kind == "third-party"
    tp = pkt.data
    assert isinstance(tp, ThirdParty)
    assert tp.source == "N1ABC"
    assert tp.destination == "APRS"
    assert tp.path == "WIDE2-1"
    assert tp.inner.kind == "position"
    assert round(tp.inner.data.latitude, 4) == round(49 + 3.50 / 60, 4)
    assert "N1ABC" in format_packet(pkt)


# -- station capabilities / query -------------------------------------------


def test_station_capabilities():
    frame = _ui_frame("APRS", "N1ABC-9", b"<IGATE,MSG_CNT=0,LOC_CNT=0")
    pkt = parse_packet(frame)
    assert pkt.kind == "capabilities"
    assert "IGATE" in pkt.data.text


def test_query():
    frame = _ui_frame("APRS", "N1ABC-9", b"?APRS?")
    pkt = parse_packet(frame)
    assert pkt.kind == "query"


# -- non-APRS and malformed frames -------------------------------------------


def test_non_ui_frame_is_not_aprs():
    path = AX25Path(AX25Address.parse("APRS"), AX25Address.parse("N1ABC"))
    frame = AX25Frame.i_frame(path, 0, 0, b"not APRS at all")
    assert parse_packet(frame) is None


def test_wrong_pid_is_not_aprs():
    path = AX25Path(AX25Address.parse("APRS"), AX25Address.parse("N1ABC"))
    frame = AX25Frame.u_frame(path, UType.UI, pid=0xCF, info=b"!4903.50N/07201.75W>")
    assert parse_packet(frame) is None


def test_malformed_empty_info():
    frame = _ui_frame("APRS", "N1ABC-9", b"")
    pkt = parse_packet(frame)
    assert pkt is not None
    assert pkt.kind == "unparsed"
    assert pkt.info == b""


def test_malformed_truncated_position():
    frame = _ui_frame("APRS", "N1ABC-9", b"!4903.50N/0720")
    pkt = parse_packet(frame)
    assert pkt.kind == "unparsed"
    assert pkt.info == b"!4903.50N/0720"


def test_malformed_garbage_latitude_digits():
    frame = _ui_frame("APRS", "N1ABC-9", b"!49AB.50N/07201.75W-broken lat")
    pkt = parse_packet(frame)
    assert pkt.kind == "unparsed"


def test_malformed_message_no_second_colon():
    frame = _ui_frame("APRS", "N1ABC-9", b":BADMESSAGENOCOLON")
    pkt = parse_packet(frame)
    assert pkt.kind == "unparsed"


def test_malformed_mic_e_short_info():
    # Valid Mic-E destination, but the info field is far too short to hold
    # longitude/speed/course -- must not raise.
    frame = _ui_frame("42CB3A", "N1ABC-9", b"`\x01\x02")
    pkt = parse_packet(frame)
    assert pkt.kind == "unparsed"


def test_malformed_never_raises_on_random_bytes():
    # A grab-bag of "RF garbage" -- must never raise regardless of content.
    samples = [
        bytes([0xF0, 0x00, 0x01, 0x02]),
        b"!" * 40,
        b"\x00\x01\x02\x03\x04",
        b"}garbage with no colon at all",
        b"T#notenoughfields",
    ]
    for info in samples:
        frame = _ui_frame("APRS", "N1ABC-9", info)
        pkt = parse_packet(frame)
        assert pkt is not None
        assert pkt.kind in ("unparsed", "message", "position", "telemetry", "third-party")


# -- HeardTable ---------------------------------------------------------


def test_heard_table_records_and_counts():
    table = HeardTable(capacity=10)
    frame = _ui_frame("APRS", "N1ABC-9", b"!4903.50N/07201.75W>hi")
    entry = table.record(frame, port=0)
    assert entry.callsign == "N1ABC-9"
    assert entry.count == 1
    assert entry.direct is True

    table.record(frame, port=0)
    entry2 = table.get("N1ABC-9")
    assert entry2.count == 2
    assert entry2 is entry  # same object, mutated in place


def test_heard_table_direct_detection():
    table = HeardTable()
    direct_frame = _ui_frame("APRS", "N1ABC-9", b"!test", via=("WIDE2-1",))
    entry = table.record(direct_frame)
    assert entry.direct is True  # digipeater listed but has not repeated yet

    path = AX25Path(
        destination=AX25Address.parse("APRS"),
        source=AX25Address.parse("N1ABC-9"),
        repeaters=(AX25Address("WIDE2", 1, ch=True),),
    )
    repeated_frame = AX25Frame.u_frame(path, UType.UI, pid=PID_NO_LAYER3, info=b"!test")
    entry2 = table.record(repeated_frame)
    assert entry2.direct is False
    assert entry2.last_path == "WIDE2-1*"


def test_heard_table_eviction():
    table = HeardTable(capacity=3)
    for i in range(5):
        frame = _ui_frame("APRS", f"N{i}CALL", b"!test")
        table.record(frame)
    assert len(table) == 3
    remaining = {e.callsign for e in table.entries()}
    assert remaining == {"N2CALL", "N3CALL", "N4CALL"}


def test_heard_table_sort_orders():
    table = HeardTable()
    for call in ("AAAA", "ZZZZ", "MMMM"):
        table.record(_ui_frame("APRS", call, b"!test"))
    by_callsign = [e.callsign for e in table.entries(sort="callsign")]
    assert by_callsign == ["AAAA", "MMMM", "ZZZZ"]


def test_heard_table_json_round_trip():
    table = HeardTable(capacity=50)
    table.record(_ui_frame("APRS", "N1ABC-9", b"!test", via=("WIDE1-1",)))
    table.set_position("N1ABC-9", 49.05, -72.03)

    text = table.to_json()
    restored = HeardTable.from_json(text, capacity=50)

    original = table.get("N1ABC-9")
    round_tripped = restored.get("N1ABC-9")
    assert round_tripped is not None
    assert round_tripped.callsign == original.callsign
    assert round_tripped.count == original.count
    assert round_tripped.last_position == (49.05, -72.03)


def test_heard_table_json_round_trip_survives_garbage():
    assert len(HeardTable.from_json("")) == 0
    assert len(HeardTable.from_json("not json")) == 0
    assert len(HeardTable.from_json("[]")) == 0


def test_heard_table_subscribe():
    table = HeardTable()
    seen = []
    unsubscribe = table.subscribe(seen.append)
    table.record(_ui_frame("APRS", "N1ABC-9", b"!test"))
    assert len(seen) == 1
    assert seen[0].callsign == "N1ABC-9"
    unsubscribe()
    table.record(_ui_frame("APRS", "N1ABC-9", b"!test"))
    assert len(seen) == 1
