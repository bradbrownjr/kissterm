"""Walking a hop chain: "C <node>" over a link that is already up, and
deciding from the node's own reply whether the hop came up.

THE one definition of "the hop worked": the scripted hop chain
(`connect.Connector.hop_to`) and a hop the operator types by hand (the
terminal UI's `log_sent`) both go through `HopConfirmation`, so the two
cannot drift apart. Modelled on the send/wait-for-CONNECTED-or-BUSY/FAILED
loop the sibling `bpq-apps` project's node-map crawler uses against real
BPQ nodes.
"""

from __future__ import annotations

import asyncio
import contextlib

#: How long to wait for one intermediate node's own CONNECTED reply
#: (`Connector.hop_to`) before giving up on that hop. Fixed rather than
#: scaled to the remaining chain length (unlike the bpq-apps node-map
#: crawler this is modelled on) -- that crawler walks up to ten
#: auto-discovered hops, this walks a short chain the operator typed by
#: hand, so a flat, generous timeout is simpler and does the job.
HOP_TIMEOUT = 20.0

#: A hop that answers with any of these has explicitly refused or dropped,
#: which is a different diagnosis from silence and must be reported
#: differently -- see `AX25Station.connect`'s DM-vs-timeout distinction for
#: the same reasoning one layer down. Matched case-insensitively as a
#: substring against everything received since the "C <node>" command went
#: out, the same heuristic bpq-apps' crawler uses against real BPQ nodes.
HOP_FAIL_WORDS = ("BUSY", "FAILED", "DISCONNECTED", "TIMEOUT")

#: The first word of an outgoing line that means "connect onward to a
#: different node" across every shipped family's own command set -- bpq32/
#: NET-ROM's "C"/"CONNECT" and JNOS's "connect" (its own alias table also
#: has "c"). `log_sent` starts a confirmation watch when it sees one of
#: these followed by a target, so an operator typing the command by hand
#: mid-session gets the same confirm-then-reset treatment the scripted hop
#: chain already gets from `_hop_to` -- see `log_sent`'s hop paragraph for
#: why detection otherwise never notices the switch, and `_commit_hop` for
#: why the reset must wait for the hop to actually come up.
HOP_COMMAND_WORDS = frozenset({"C", "CONNECT"})


class HopConfirmation:
    """Watches one link for a node's own reply to a "C <node>" that has just
    gone out, and decides whether the hop came up.

    THE one definition of "the hop worked" in this app -- both the scripted
    hop chain (`Connector.hop_to`) and a hand-typed hop
    (the terminal UI's `log_sent` background watch) go through it, so the two
    cannot drift apart on, say, whether DISCONNECTED counts as a refusal.

    A small class rather than a plain coroutine for one reason that is not
    cosmetic: it subscribes to `link.on_data` in `__init__`, SYNCHRONOUSLY.
    A coroutine can only subscribe once the event loop first runs it, and
    `log_sent` is a synchronous method that cannot await anything before
    returning -- so a reply arriving in that window would be fanned out to
    every other subscriber and missed by this one, and the hop would never
    be confirmed at all.

    Subscribing is non-destructive: the terminal pane has its own separate
    subscriber from `_bind_link` and goes on displaying the same bytes, the
    same one-fan-out-many-subscribers shape as the frame transport's own
    `subscribe()`. `stop()` must always be called -- a watcher left
    subscribed goes on matching a later, unrelated hop's traffic.
    """

    def __init__(self, link, node: str) -> None:
        self._link = link
        self._node = node
        self._seen = bytearray()
        self.result: asyncio.Future[tuple[bool, str]] = (
            asyncio.get_event_loop().create_future()
        )
        link.on_data.append(self._on_data)

    def _on_data(self, data: bytes) -> None:
        self._seen.extend(data)
        # latin-1 for the same reason every other payload decode in this app
        # uses it: a corrupt frame off a noisy channel must lose the noise,
        # not the readable part around it.
        text = self._seen.decode("latin-1", "replace").upper()
        if "CONNECTED" in text:
            if not self.result.done():
                self.result.set_result((True, ""))
            return
        for word in HOP_FAIL_WORDS:
            if word in text:
                if not self.result.done():
                    self.result.set_result((False, f"{self._node} answered {word}"))
                return

    def stop(self) -> None:
        """Unsubscribe. Idempotent -- it is called from both the awaiting
        coroutine's `finally` and the watching task's done callback, and
        either one may get there first."""
        with contextlib.suppress(ValueError):
            self._link.on_data.remove(self._on_data)
