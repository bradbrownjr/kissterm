"""End-to-end tests of the connected-mode state machine over a loopback pair.

These are the tests that matter most in this project: they exercise the code
that has no spec-conformance safety net short of putting it on the air. Each
one drives two real `AX25Station`s against each other and asserts on observable
link behaviour, not on internal calls.
"""

from __future__ import annotations

import asyncio

import pytest

from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams
from kissterm.ax25.frame import MODULO128
from kissterm.transport.base import SessionState
from tests.loopback import loopback_pair

CALL_A = AX25Address.parse("N1ABC-1")
CALL_B = AX25Address.parse("WS1EC-7")


def _params(**kw) -> LinkParams:
    # Short timers so a test that exercises recovery finishes in milliseconds
    # rather than in the eight seconds a real VHF link would want.
    base = dict(t1=0.25, t2=0.05, t3=0.6, paclen=16, window=4, retries=10)
    base.update(kw)
    return LinkParams(**base)


async def _pair(params_a=None, params_b=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    a = AX25Station(CALL_A, ta, params_a or _params())
    b = AX25Station(CALL_B, tb, params_b or _params())
    return a, b, ta, tb


async def _drain(link, timeout=1.0, expect: int | None = None) -> bytes:
    """Collect delivered bytes until ``expect`` bytes arrive or time runs out.

    Waiting for the stream to "go quiet" instead is wrong and produced a
    false failure once already: on a lossy link the gap between chunks is a
    whole T1 recovery cycle, so a quiet-period heuristic returns a partial
    read and blames the state machine for a harness bug.
    """
    loop = asyncio.get_event_loop()
    out = b""
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(0.02)
        out += link.read_nowait()
        if expect is not None and len(out) >= expect:
            break
    return out


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    a, b, *_ = await _pair()
    incoming = []
    b.on_incoming.append(incoming.append)

    link = await a.connect(AX25Path(CALL_B, CALL_A))
    assert link is not None
    assert link.state is SessionState.CONNECTED
    await asyncio.sleep(0.05)
    assert len(incoming) == 1
    assert incoming[0].state is SessionState.CONNECTED

    await link.disconnect()
    await asyncio.sleep(0.1)
    assert link.state is SessionState.DISCONNECTED
    assert incoming[0].state is SessionState.DISCONNECTED
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_refused_connection_reports_failure():
    a, b, *_ = await _pair()
    b.accept_incoming = False
    link = await a.connect(AX25Path(CALL_B, CALL_A))
    assert link is None
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_no_answer_gives_up_after_n2():
    ta, tb = loopback_pair()
    await ta.open()
    ta.peer = None  # nothing on the far end at all
    a = AX25Station(CALL_A, ta, _params(retries=2))  # N2=2: give up fast
    errors: list[str] = []
    link = None

    path = AX25Path(CALL_B, CALL_A)
    link = await a.connect(path)
    assert link is None
    # SABM plus one retransmission per retry, and no more.
    assert 2 <= len(ta.sent) <= 4
    a.close()


@pytest.mark.asyncio
async def test_data_transfer_both_directions():
    a, b, *_ = await _pair()
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    await asyncio.sleep(0.05)
    link_b = incoming[0]

    payload = b"The quick brown fox jumps over the lazy dog. " * 4
    await link_a.send(payload)
    got = await _drain(link_b, expect=len(payload))
    assert got == payload

    reply = b"73 de WS1EC\r"
    await link_b.send(reply)
    assert await _drain(link_a, expect=len(reply)) == reply
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_fragmentation_respects_paclen():
    a, b, ta, tb = await _pair(_params(paclen=8))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    await asyncio.sleep(0.05)
    link_b = incoming[0]

    payload = bytes(range(65, 65 + 26))  # 26 bytes -> at least 4 frames of 8
    await link_a.send(payload)
    assert await _drain(link_b, expect=len(payload)) == payload
    i_frames = [f for f in ta.sent if f.kind == "I"]
    assert i_frames, "no I frames were sent"
    assert all(len(f.info) <= 8 for f in i_frames)
    assert len(i_frames) >= 4
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_recovers_from_a_lossy_channel():
    """Drop a quarter of all frames and require the data through intact.

    This is the test that actually exercises REJ, T1 expiry, timer recovery and
    go-back-N retransmission together. If the state machine has an off-by-one
    in its modular sequence arithmetic, this hangs instead of failing cleanly --
    hence the outer timeout.
    """
    a, b, ta, tb = await _pair(_params(t1=0.2, window=4, paclen=16))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    await asyncio.sleep(0.05)
    link_b = incoming[0]

    ta.loss = tb.loss = 0.25
    payload = bytes(range(32)) * 6  # 192 bytes -> 12 frames, well past one window
    await link_a.send(payload)

    got = await asyncio.wait_for(_drain(link_b, timeout=8.0, expect=len(payload)), timeout=20)
    assert got == payload, f"got {len(got)} of {len(payload)} bytes"
    assert link_a.stats.retransmits > 0, "lossy channel produced no retransmissions"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_window_never_exceeds_k():
    a, b, ta, tb = await _pair(_params(window=2, paclen=4))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    await asyncio.sleep(0.05)

    tb.loss = 1.0  # nothing is ever acknowledged
    await link_a.send(b"A" * 64)
    await asyncio.sleep(0.05)
    unacked = (link_a.vs - link_a.va) % link_a.params.modulo
    assert unacked <= 2, f"{unacked} frames outstanding with k=2"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_sequence_numbers_wrap_past_modulo():
    """More than 8 frames must keep flowing once N(S) wraps through zero."""
    a, b, *_ = await _pair(_params(paclen=4, window=4, t1=0.3))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    await asyncio.sleep(0.05)
    link_b = incoming[0]

    payload = bytes(range(48))  # 12 frames of 4 bytes -> wraps modulo 8
    await link_a.send(payload)
    assert await asyncio.wait_for(_drain(link_b, 4.0, expect=len(payload)), timeout=10) == payload
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_t3_probes_an_idle_link():
    a, b, ta, tb = await _pair(_params(t3=0.2, t1=0.5))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    await asyncio.sleep(0.05)
    before = len(ta.sent)
    await asyncio.sleep(0.5)
    assert len(ta.sent) > before, "T3 never probed the idle link"
    assert link_a.connected, "an answered T3 probe must not disturb the link"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_peer_reconnect_resets_the_link():
    """A node that restarts sends SABM mid-session; the link must resynchronise."""
    a, b, *_ = await _pair()
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    await asyncio.sleep(0.05)
    link_b = incoming[0]
    await link_a.send(b"some traffic first")
    await _drain(link_b, 0.4)
    assert link_a.vs != 0

    await link_b._reestablish()
    await asyncio.sleep(0.2)
    assert link_a.vs == 0 and link_a.vr == 0 and link_a.connected
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_modulo_128_link():
    params = _params(modulo=MODULO128, window=8, paclen=16)
    a, b, *_ = await _pair(params, params)
    incoming: list = []
    b.on_incoming.append(incoming.append)
    link_a = await a.connect(AX25Path(CALL_B, CALL_A))
    assert link_a is not None and link_a.params.modulo == MODULO128
    await asyncio.sleep(0.05)
    link_b = incoming[0]
    payload = b"extended sequence numbers " * 8
    await link_a.send(payload)
    assert await asyncio.wait_for(_drain(link_b, 3.0, expect=len(payload)), timeout=10) == payload
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_refused_connect_and_an_unanswered_one_do_not_look_alike():
    """The whole diagnosis of a failed connection is which of these it was.

    A DM means the far end heard us and said no -- a configuration problem at
    one end or the other. Silence after N2 tries means the path did not carry
    -- an antenna, power or propagation problem. Reporting both as "no
    connection" sends the operator to check the wrong end of the station, so
    the reason is kept on the link for the UI to read back.
    """
    a, b, ta, tb = await _pair(params_a=_params(retries=2))

    b.accept_incoming = False
    refused = await a.connect(AX25Path(CALL_B, CALL_A))
    assert refused is None
    link = a.link_to(CALL_B)
    assert link is not None
    assert "refused" in link.last_error.lower(), link.last_error

    # Now the same connect with nothing at the far end at all.
    a2 = AX25Station(AX25Address.parse("N1ABC-2"), ta, _params(retries=2))
    tb.loss = 1.0  # nothing we transmit is ever heard
    silent = await a2.connect(AX25Path(AX25Address.parse("W1XYZ-9"), CALL_A))
    assert silent is None
    dead = a2.link_to(AX25Address.parse("W1XYZ-9"))
    assert dead is not None
    assert "no answer" in dead.last_error.lower(), dead.last_error
    assert dead.rc > 1, "gave up without using the retry budget"


@pytest.mark.asyncio
async def test_a_healthy_link_reports_no_error():
    a, b, *_ = await _pair()
    link = await a.connect(AX25Path(CALL_B, CALL_A))
    assert link is not None
    assert link.last_error == ""
    await link.disconnect()
