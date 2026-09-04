"""Exhaustive tests for the sliding window's modular arithmetic.

These run with no event loop, no transport and no peer, which is the reason
`SlidingWindow` was carved out of the state machine: the arithmetic that causes
the most damage is now the arithmetic that is cheapest to test.
"""

from __future__ import annotations

import pytest

from kissterm.ax25.window import SlidingWindow


def test_window_opens_and_closes_at_k():
    w = SlidingWindow(modulo=8, k=3)
    assert w.is_open
    for i in range(3):
        assert w.record_sent(bytes([i])) == i
    assert not w.is_open, "window must close once k frames are outstanding"
    assert w.outstanding == 3
    w.ack_upto(1)
    assert w.is_open and w.outstanding == 2


def test_ack_reports_whether_it_advanced():
    w = SlidingWindow(modulo=8, k=4)
    w.record_sent(b"a")
    assert w.ack_upto(1) is True
    assert w.ack_upto(1) is False, "a repeated N(R) acknowledges nothing new"


def test_k_is_clamped_below_modulo():
    """k == modulo makes a full window indistinguishable from an empty one."""
    assert SlidingWindow(modulo=8, k=8).k == 7
    assert SlidingWindow(modulo=8, k=99).k == 7
    assert SlidingWindow(modulo=128, k=128).k == 63 or SlidingWindow(modulo=128, k=128).k == 127
    assert SlidingWindow(modulo=8, k=0).k == 1


def test_reset_reclamps_after_a_modulo_change():
    """A SABME refused with DM drops the link to modulo 8; k must follow."""
    w = SlidingWindow(modulo=128, k=32)
    assert w.k == 32
    w.modulo = 8
    w.reset()
    assert w.k == 7, "k left at 32 under modulo 8 corrupts every sequence number"


def test_ack_wraps_past_zero():
    """The bug this whole module exists to prevent: stalling at the wrap."""
    w = SlidingWindow(modulo=8, k=7)
    for i in range(7):
        w.record_sent(bytes([i]))
    assert w.vs == 7 and w.outstanding == 7
    w.ack_upto(7)
    assert w.fully_acked and w.outstanding == 0
    assert not w.sent, "acknowledged frames must be released"
    # Now push V(S) around through zero and acknowledge across the wrap.
    for i in range(4):
        w.record_sent(bytes([i]))
    assert w.vs == 3, "V(S) must wrap past 7 to 3"
    assert w.outstanding == 4
    w.ack_upto(3)
    assert w.fully_acked, "acknowledging across the wrap must clear the window"


def test_full_cycle_never_stalls():
    """Send and acknowledge four full modulo cycles, one frame at a time."""
    w = SlidingWindow(modulo=8, k=1)
    for i in range(32):
        assert w.is_open, f"window jammed shut at frame {i}"
        ns = w.record_sent(bytes([i % 256]))
        w.ack_upto((ns + 1) % 8)
    assert w.fully_acked


def test_pending_from_is_go_back_n_in_order():
    w = SlidingWindow(modulo=8, k=4)
    for i in range(4):
        w.record_sent(bytes([i]))
    w.ack_upto(2)  # frames 0 and 1 are acknowledged
    assert [seq for seq, _ in w.pending_from(2)] == [2, 3]
    assert [info for _, info in w.pending_from(2)] == [b"\x02", b"\x03"]


def test_pending_from_wraps():
    w = SlidingWindow(modulo=8, k=6)
    for i in range(6):
        w.record_sent(bytes([i]))
    w.ack_upto(5)
    for i in range(3):  # push V(S) around past zero
        w.record_sent(bytes([100 + i]))
    seqs = [seq for seq, _ in w.pending_from(w.va)]
    assert seqs == [5, 6, 7, 0], f"go-back-N did not wrap correctly: {seqs}"


def test_pending_from_cannot_spin_on_a_bogus_nr():
    """A peer sending a nonsensical N(R) must not hang the sender."""
    w = SlidingWindow(modulo=8, k=4)
    w.record_sent(b"x")
    assert len(list(w.pending_from(6))) <= 8


def test_ack_upto_cannot_spin_on_a_bogus_nr():
    w = SlidingWindow(modulo=8, k=4)
    w.record_sent(b"x")
    w.ack_upto(99)  # must terminate, whatever it decides
    assert w.outstanding <= 8


def test_accept_only_takes_the_expected_sequence():
    w = SlidingWindow(modulo=8, k=4)
    assert w.accept(0) is True and w.vr == 1
    assert w.accept(3) is False, "out-of-sequence frames must be refused"
    assert w.vr == 1, "a refused frame must not advance V(R)"
    assert w.accept(1) is True and w.vr == 2


def test_accept_wraps():
    w = SlidingWindow(modulo=8, k=4)
    for i in range(8):
        assert w.accept(i) is True
    assert w.vr == 0


def test_modulo_128_window():
    w = SlidingWindow(modulo=128, k=32)
    for i in range(100):
        w.record_sent(bytes([i % 256]))
    assert w.vs == 100 and w.outstanding == 100
    w.ack_upto(100)
    assert w.fully_acked
    for i in range(40):
        w.record_sent(b"z")
    assert w.vs == 140 % 128


def test_reset_returns_to_post_sabm_state():
    w = SlidingWindow(modulo=8, k=4)
    w.record_sent(b"a")
    w.accept(0)
    w.reset()
    assert (w.vs, w.vr, w.va) == (0, 0, 0)
    assert not w.sent
