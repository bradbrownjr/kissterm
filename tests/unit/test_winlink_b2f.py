"""The B2F client against a scripted gateway.

The first three tests are wl2k-go's recorded CMS sessions
(`fbb/wl2k_test.go`: TestSessionCMS, TestSessionCMSWithMessage,
TestSessionCMSv4), line for line; the rest send and receive whole messages
and check every refusal the client must make.
"""

from kissterm._isolate import isolate

isolate()

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from kissterm.winlink import b2f, lzhuf  # noqa: E402
from kissterm.winlink import message as b2  # noqa: E402
from kissterm.winlink.secure import login_response  # noqa: E402

REAL = Path(__file__).parent / "data" / "winlink" / "LPE5NXDVLVSQ.b2f"
HANDSHAKE = [";FW: LA5NTA", "[kissterm-1.0-B2FHM$]", "; LA1B-10 DE LA5NTA (JO39EQ)"]


def client(**kwargs):
    return b2f.Client("LA5NTA", "LA1B-10", locator="JO39EQ", version="1.0", **kwargs)


def lines(data: bytes) -> list[str]:
    return [line for line in data.decode("latin-1").split("\r") if line]


def gateway_sends(c, *text_lines):
    c.feed("".join(f"{line}\r" for line in text_lines).encode("latin-1"))


def blocks(raw_message: bytes, title: str = "Test") -> tuple[bytes, int]:
    """A message as the gateway sends it, and its compressed size."""
    data = lzhuf.compress(raw_message)
    out = bytes((1, len(title) + 3)) + title.encode() + b"\x000\x00"
    for start in range(0, len(data), 250):
        chunk = data[start:start + 250]
        out += bytes((2, len(chunk))) + chunk
    return out + bytes((4, -sum(data) & 0xFF)), len(data)


def test_cms_session_with_nothing_to_do():
    c = client()
    gateway_sends(c, "[WL2K-2.8.4.8-B2FWIHJM$]", "Foobar should be ignored", "Test CMS >")
    assert lines(c.take_output()) == [*HANDSHAKE, "FF"]
    gateway_sends(c, "FQ")
    assert c.done and not c.error


def test_cms_session_with_a_proposal_we_cannot_take_defers_it():
    c = client()
    gateway_sends(c, "[WL2K-2.8.4.8-B2FWIHJM$]", "Test CMS >")
    c.take_output()
    # wl2k-go's session has no handler, so it defers everything. Ours
    # defers what it cannot read: FD (gzip), which we never offer.
    gateway_sends(c, "FD EM TJKYEIMMHSRB 527 123 0", f"F> {b2f.checksum(['FD EM TJKYEIMMHSRB 527 123 0']):02x}")
    assert lines(c.take_output()) == ["FS =", "FF"]
    gateway_sends(c, "FQ")
    assert c.done and not c.error


def test_cms_v4_lines_and_the_recorded_checksum():
    c = client(have=lambda mid: mid == "TJKYEIMMHSRB")
    gateway_sends(c, "[WL2K-4.0-B2FWIHJM$]", "Test CMS >")
    assert lines(c.take_output()) == [*HANDSHAKE, "FF"]
    gateway_sends(c, ";PM: LA5NTA TJKYEIMMHSRB 123 martin.h.pedersen@gmail.com",
                  ";WARNING: Foo bar baz", "FC EM TJKYEIMMHSRB 527 123 0", "F> 3b")
    assert lines(c.take_output()) == ["FS -", "FF"]
    gateway_sends(c, ";WARNING: Foo bar baz", "FQ")
    assert c.done and not c.error


def test_secure_login_answers_the_challenge_and_never_sends_the_password():
    c = client(password="FooBar")
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", ";PQ: 23753528", "CMS >")
    out = c.take_output()
    assert lines(out)[:3] == [";FW: LA5NTA", "[kissterm-1.0-B2FHM$]", ";PR: 95074758"]
    assert login_response("23753528", "FooBar") == "95074758"
    assert b"FooBar" not in out


def test_a_challenge_without_a_password_stops_with_a_reason():
    c = client()
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", ";PQ: 23753528", "CMS >")
    assert c.done and "password" in c.error


def test_a_login_failure_is_reported_in_the_gateways_words():
    c = client(password="wrong")
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", ";PQ: 23753528", "CMS >")
    c.take_output()
    gateway_sends(c, "*** [1] Secure login failed - account password does not match. - Disconnecting")
    assert c.done
    assert "Secure login failed - account password does not match" in c.error


def test_node_lines_before_the_sid_are_ignored_even_a_prompt():
    c = client()
    gateway_sends(c, "WS1EC:WS1EC-2} Connected to RMS", "Node>", "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    assert lines(c.take_output()) == [*HANDSHAKE, "FF"]


def test_a_gateway_without_b2_is_refused():
    c = client()
    gateway_sends(c, "[FBB-7.0-AFHM$]", ">")
    assert c.done and "B2F" in c.error


def test_receive_a_real_message_with_an_attachment():
    raw = REAL.read_bytes()
    data, size = blocks(raw, "73 fra Brekke")
    c = client()
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    c.take_output()
    proposal = f"FC EM LPE5NXDVLVSQ {len(raw)} {size} 0"
    gateway_sends(c, proposal, f"F> {b2f.checksum([proposal]):02X}")
    assert lines(c.take_output()) == ["FS +"]
    c.feed(data[:1000])  # arrives in pieces, as over a link
    assert not c.take_output()
    c.feed(data[1000:])
    assert lines(c.take_output()) == ["FF"]
    received = [e for e in c.take_events() if isinstance(e, b2f.Received)]
    assert len(received) == 1 and received[0].raw == raw
    assert received[0].message.files[0][0] == "1469042410710.jpg"
    gateway_sends(c, "FQ")
    assert c.done and not c.error


def test_a_damaged_message_is_not_filed():
    data, size = blocks(b2.serialize(b2.build(sender="W1AW", to=["LA5NTA"], subject="Hi", body="Hello")))
    damaged = bytearray(data)
    damaged[20] ^= 0xFF
    c = client()
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    proposal = f"FC EM ABCDEFGHIJKL 100 {size} 0"
    gateway_sends(c, proposal, f"F> {b2f.checksum([proposal]):02X}")
    c.feed(bytes(damaged))
    assert c.done and "damaged" in c.error
    assert not [e for e in c.take_events() if isinstance(e, b2f.Received)]
    assert lines(c.take_output())[-1].startswith("*** ")


def test_send_a_message_and_it_counts_only_when_the_gateway_moves_on():
    message = b2.build(sender="LA5NTA", to=["W1AW"], subject="Net report", body="All well\n" * 50)
    c = client(outbound=[message])
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    out = lines(c.take_output())
    proposal = out[len(HANDSHAKE)]
    assert proposal.startswith(f"FC EM {message.mid} {len(b2.serialize(message))} ")
    assert out[-1] == f"F> {b2f.checksum([proposal]):02X}"
    gateway_sends(c, "FS +")
    sent = c.take_output()
    assert sent[0] == 1 and b"Net report\x000\x00" in sent
    # Take the blocks apart the way a gateway would.
    at = 2 + sent[1]
    data = bytearray()
    while sent[at] == 2:
        data += sent[at + 2:at + 2 + sent[at + 1]]
        at += 2 + sent[at + 1]
    assert sent[at] == 4 and (sum(data) + sent[at + 1]) & 0xFF == 0
    assert lzhuf.decompress(bytes(data)) == b2.serialize(message)
    assert not [e for e in c.take_events() if isinstance(e, b2f.Sent)]
    gateway_sends(c, "FF")
    assert [e.mid for e in c.take_events() if isinstance(e, b2f.Sent)] == [message.mid]
    assert lines(c.take_output()) == ["FQ"]
    assert c.done and not c.error


def test_rejected_and_deferred_answers():
    first = b2.build(sender="LA5NTA", to=["W1AW"], subject="One", body="1")
    second = b2.build(sender="LA5NTA", to=["W1AW"], subject="Two", body="2")
    c = client(outbound=[first, second])
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    c.take_output()
    gateway_sends(c, "FS -=")
    events = c.take_events()
    assert [e for e in events if isinstance(e, b2f.Sent)][0].already_had
    assert len([e for e in events if isinstance(e, b2f.Deferred)]) == 1


def test_no_more_than_five_proposals_a_block_and_flash_first():
    messages = [b2.build(sender="LA5NTA", to=["W1AW"], subject=f"Msg {i}", body="x" * (i + 1))
                for i in range(6)]
    messages.append(b2.build(sender="LA5NTA", to=["W1AW"], subject="Urgent //WL2K Z/", body="x" * 500))
    c = client(outbound=messages)
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    proposals = [line for line in lines(c.take_output()) if line.startswith("FC ")]
    assert len(proposals) == 5 and messages[-1].mid in proposals[0]


def test_the_link_dropping_midway_is_an_error():
    c = client()
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    c.connection_lost()
    assert c.done and "dropped" in c.error


def test_every_line_is_an_event_for_the_log():
    c = client()
    gateway_sends(c, "[WL2K-5.0-B2FWIHJM$]", "CMS >")
    logged = [(e.direction, e.text) for e in c.take_events() if isinstance(e, b2f.Line)]
    assert logged[:2] == [("<", "[WL2K-5.0-B2FWIHJM$]"), ("<", "CMS >")]
    assert ("<", "CMS >") in logged and (">", "FF") in logged


@pytest.mark.parametrize(("line", "expect"), [
    ("FS YLA3350RH", [("+", 0), ("=", 0), ("+", 3350), ("-", 0), ("=", 0)]),
    ("FS +=!3350-+", [("+", 0), ("=", 0), ("+", 3350), ("-", 0), ("+", 0)]),
])
def test_proposal_answers(line, expect):
    # wl2k-go's TestParseProposalAnswer.
    assert b2f.parse_answers(line, 5) == expect
