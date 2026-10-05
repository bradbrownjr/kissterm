"""Connecting: the transmit gate's arming, the radio reminder, the dial,
the hop chain and the auto-login, for every front end (ROADMAP P7a M2).

**Arming lives here.** The gate stops transmissions the operator did not
initiate -- beacons, auto-answer, anything on a timer. It was never meant to
veto one they just asked for by name: naming a station and confirming it
IS the request to key the radio, and answering it with "transmit is
disabled" is a dead end. So a confirmed, targeted request arms the gate
(`Connector.arm_for`), and arming is never silent: a notice, a line in the
session's transcript, and a `GateChanged` event for every client's status
display. A single keystroke with no confirmation and no target (the manual
text beacon) still does not arm. An unattended resend never arms.

**The radio reminder comes before arming.** A frequency on file is worth
nothing if the operator sees it after the SABMs went out
(`questions.RadioReminder`); cancelling it transmits nothing.

**Two failures, two wordings.** A DM means the node heard us and refused
(configuration); silence after N2 tries means the path did not carry
(antenna, power, propagation); a TNC link that is down means nothing
reached the air at all. Each is said differently (AGENTS.md "A failure the
operator cannot diagnose is a bug").

**Sessions are the core's** (`sessions.py`): binding a link, the record
and the echo of each line sent. What stays with a client is presentation
-- which session is on screen, whether there is room for another, putting
one in front of the operator -- through `SessionView`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from ..ax25 import parse_path
from ..ax25.address import AX25Address
from ..config import credential_username, find_credential, find_script
from ..config import login_text as saved_login_text
from ..transport.base import TransportError, TransportState
from . import hops
from .hops import HopConfirmation
from .links import SessionLinkAdapter
from .events import ConnectingChanged
from .operator import Notice, Severity
from .questions import ChooseSessionTransport, RadioReminder, TrustHostKey
from .service import MAX_LINKS

log = logging.getLogger(__name__)

#: `AX25Link.last_error` set by `Connector.disconnect` when it cancels a
#: connect still in the SABM/retry phase. Checked back in `connect` so a
#: cancelled attempt is reported as cancelled, not run through the "no
#: answer" / "check the Monitor tab" wording meant for a genuine timeout.
CANCELLED_REASON = "cancelled by operator"

#: Pause between auto-login lines (`Connector.run_connect_script`). A
#: login sequence is normally two or three short commands, not a burst --
#: pacing them gives a BBS's own line handling a moment to catch up rather
#: than racing several commands in before it has processed the first.
CONNECT_SCRIPT_LINE_DELAY = 0.75


@dataclass(frozen=True)
class ConnectRequest:
    """Where to connect, and what to do once there.

    `hops` is a comma-separated chain of intermediate nodes to reach
    `target` node-to-node, for when no digipeater path does the job --
    almost always empty. `script`/`credential`/`script_name` are the three
    mutually exclusive ways to say what to send once the FULL chain (or the
    plain direct connect, if `hops` is empty) comes up, checked in that
    order by `Connector.resolve_login`: the name of a saved credential,
    the name of a saved script, or literal text -- see `Config.credentials`
    for why a login and a script are two separate saved lists rather than
    one, and `run_connect_script` for how the winning text gets sent.

    `transport_name`, when non-empty and different from the currently
    active transport, asks the caller to switch to it (via
    `Core.switch_frame_transport`) BEFORE dialing -- only ever a same-tier
    alternative, since the connect dialog itself only appears on the frame
    tier; see `transport.FRAME_TIER_KINDS`'s docstring for why a live tier
    switch is not offered anywhere.
    """

    target: str
    script: str = ""
    hops: str = ""
    credential: str = ""
    script_name: str = ""
    transport_name: str = ""
    #: KISS/AGW radio port selected for this attempt.  This is deliberately
    #: per-attempt rather than an Address Book property: the same node may be
    #: reachable on different channels as the operator changes the station.
    port: int = 0


def session_key(peer, port: int = 0) -> str:
    """The identity a session is keyed on. Plain callsign for the
    overwhelmingly common `port=0` case, so tab labels stay exactly what an
    operator expects; the port is only appended when it would otherwise
    collide (two different ports genuinely can reach two different
    stations sharing a displayed callsign+SSID)."""
    return str(peer) if port == 0 else f"{peer}:{port}"


def entry_link_override(text: str) -> int | None:
    """Turn an `addressbook.Entry.paclen`/`window` string into an override
    for `AX25Station.connect`, or `None` to mean "use the global default".

    The entry dialog already refuses to save anything but blank or a
    positive whole number, but the address book is a JSON file an operator
    could still hand-edit into something invalid -- treating that the same
    as blank (fall back to the global default) is a data-format mismatch,
    not a reason to refuse a connect.
    """
    try:
        value = int(text.strip())
    except ValueError:
        return None
    return value if value >= 1 else None


class SessionView(Protocol):
    """What the connect flow asks of the client showing the sessions: the
    presentation half that stays in a client. The terminal UI implements
    it; a remote client's version arrives with the WebSocket server."""

    def active_key(self) -> str:
        """The session the operator is looking at."""
    def has_room_for(self, key: str) -> bool: ...
    def open_session(self, key: str, *, kind: str, focus: bool) -> None:
        """Show the session `key` about to be dialed. `kind` is "radio",
        "internet" or "session" (the session-tier transport's one tab)."""
    def is_active(self, key: str) -> bool: ...
    def focus_input(self) -> None: ...


class Connector:
    """The connect flow. Owned by `Core` as `core.connector`."""

    def __init__(self, core, view: SessionView) -> None:
        self.core = core
        self.view = view
        #: Targets of connect attempts still in the SABM/retry phase,
        #: session key -> (peer address, port). A session does not exist
        #: until the attempt SUCCEEDS, so without this a disconnect during
        #: a stuck connect has nothing to act on and the operator waits out
        #: N2 retries with no way to stop them.
        self.connecting: dict[str, tuple[AX25Address, int]] = {}
        #: Internet contacts still connecting, by session key, so a
        #: disconnect can cancel one (`dial_internet`).
        self.internet_connecting: dict[str, asyncio.Task] = {}
        #: The one in-flight `SessionTransport.connect()`, if any. Session
        #: transports have no AX.25 link to close during setup, so the task
        #: itself is the cancellation handle.
        self.session_connect_task: asyncio.Task | None = None
        #: What each session last dialed, for Reconnect: the whole request
        #: (hops, login, port), not just the callsign, so a reconnect to a
        #: station reached through two nodes goes back the same way.
        self.last_connect: dict[str, ConnectRequest] = {}
        self.last_connect_key = ""
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    @property
    def config(self):
        return self.core.config

    @property
    def gate(self):
        return self.core.gate

    def _problem(self, report, text: str, severity: Severity = Severity.ERROR) -> None:
        """Why a connect did not happen: a notice, or handed to `report`
        when the caller (Send/Receive) raises its own, so one failure is
        one notice, not two (DESIGN.md section 6)."""
        if report is not None:
            report(text)
        else:
            self.core.operator.notice(Notice(text, severity))

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("connect task failed", exc_info=task.exception())

    def cancel_tasks(self) -> None:
        """Stop every background task (auto-login scripts) at shutdown."""
        for task in list(self._tasks):
            task.cancel()

    # ------------------------------------------------------------------
    # The transmit gate
    # ------------------------------------------------------------------
    def arm_for(self, what: str, key: str | None = None, toast: bool = True) -> bool:
        """Open the transmit gate because the operator just asked for
        something that cannot happen without transmitting. See the module
        docstring. `toast=False` is only for a caller that says it in its
        own notice (`connect`'s `announce`), so the operator gets one
        notice, not two. True if it armed now."""
        if self.gate.enabled:
            return False
        self.gate.set(True)
        self.core.sessions.record(self.view.active_key() if key is None else key,
                         f"Transmit enabled automatically for: {what}")
        if toast:
            self.core.operator.notice(
                Notice(f"Transmit ENABLED for {what}. Ctrl+T turns it back off."))
        return True

    # ------------------------------------------------------------------
    # Frame tier: kissterm's own AX.25
    # ------------------------------------------------------------------
    async def dial_entry(self, entry, *, on_link: Callable | None = None,
                         on_reached: Callable[[bool], None] | None = None,
                         focus: bool = True, announce: str = "",
                         report: Callable[[str], None] | None = None) -> None:
        """Dial Address Book contact `entry`: an Internet contact in its own
        session (`dial_internet`), the session tier's far end, or the
        station through `connect` -- the same flow as any connect (reminder,
        gate, hops, login), never a lighter path. Recorded as an attempt
        (`AddressBook.record_attempt`: on the attempt, not on success)."""
        core = self.core
        if entry.is_internet:
            await self.dial_internet(entry, on_link=on_link, on_reached=on_reached,
                                     focus=focus, report=report)
            return
        if core.station is None:
            if core.session_transport is None:
                self._problem(report, "No transport is open.")
                return
            candidates = core.session_tier_transports()
            if len(candidates) > 1:
                chosen = await core.operator.ask(
                    ChooseSessionTransport(tuple(candidates), self.config.active_transport))
                if chosen is None:
                    return
                if chosen != self.config.active_transport:
                    self.config.active_transport = chosen
                    core.save_config()
                    if not await core.switch_session_transport(chosen):
                        return
            await self.connect_session_transport()
            return
        request = ConnectRequest(
            entry.target, entry.script, entry.hops, entry.credential, entry.script_name)
        if core.addressbook is not None:
            core.addressbook.record_attempt(
                entry.target, entry.script, entry.hops, entry.credential, entry.script_name)
        await self.connect(request, entry=entry, on_link=on_link, on_reached=on_reached,
                           focus=focus, announce=announce, report=report)

    async def connect(
        self,
        request: ConnectRequest,
        *,
        entry=None,
        on_link: Callable | None = None,
        on_reached: Callable[[bool], None] | None = None,
        focus: bool = True,
        announce: str = "",
        report: Callable[[str], None] | None = None,
    ) -> None:
        """Dial `request` on the station: reminder, gate, SABMs, hop chain,
        login. `entry` is the Address Book contact being dialed, if any
        (else it is looked up by target) -- its reminder and link overrides
        apply. `on_link(link, key)` is called the moment the link is up,
        before anything awaits, and `on_reached(bool)` once the hop chain
        has (or has not) reached the target. `announce` is the caller's
        "Connecting..." notice, raised when the SABMs are about to go (with
        the gate's arming in the same notice), and `report(text)` receives
        a failure's reason instead of a notice here.
        """
        station = self.core.station
        addressbook = self.core.addressbook
        reminder = entry or (addressbook.find(request.target) if addressbook else None)
        if reminder is not None and (
            reminder.frequency or reminder.connection_type or reminder.note
        ):
            proceed = await self.core.operator.ask(
                RadioReminder(reminder.frequency, reminder.connection_type, reminder.note))
            if not proceed:
                return
        target = request.target
        # Node hops replace the "via DIGI" path entirely rather than
        # combining with it (the connect dialog refuses that combination),
        # so `parse_path(chain[0])` is either a plain callsign (hops in use)
        # or a full digipeater path (hops empty). Either way the SABM goes to
        # `path.destination`: the chain's first hop, or the final target.
        hop_names = [h.strip() for h in request.hops.split(",") if h.strip()]
        chain = hop_names + [target] if hop_names else [target]
        path = parse_path(chain[0])
        port = request.port
        if port < 0 or port >= station.transport.ports:
            self._problem(report, f"Radio port {port} is not available on this transport.")
            return
        key = session_key(path.destination, port)
        if key in self.connecting:
            # A second request while the first is still calling (a double
            # click on the dial and on the reminder's Connect, 2026-09-24).
            # Two SABM streams key the radio over the peer's UA, and a join
            # would run the login script twice; say so and drop this one.
            self._problem(report, f"Already connecting to {path.destination}.", Severity.WARNING)
            return
        self.last_connect[key] = request
        self.last_connect_key = key
        if not self.view.has_room_for(key):
            self._problem(
                report,
                f"Close a session first -- {MAX_LINKS} connections are already open.",
                Severity.WARNING,
            )
            return
        # After every validation and the reminder: a cancelled dialog must
        # not change what the operator is looking at.
        self.view.open_session(key, kind="radio", focus=focus)
        # The TNC link, before the RF link. Sending six SABMs into a socket
        # that is down produces "no answer from WS1EC-15" -- a diagnosis
        # pointing at the antenna when the fault is in the room. Unlike a
        # closed transmit gate this is not something a keystroke can fix, so
        # it is worth saying before spending the attempt.
        state = station.transport.state
        if state is not TransportState.OPEN:
            where = station.transport.info.detail
            self._problem(
                report, f"Not connecting: the link to the TNC at {where} is {state.value}, "
                "so nothing would reach the air. This is not an RF problem -- check the "
                "TNC, then Settings (F9) > Radio > Test.")
            return
        armed = self.arm_for(f"connect to {path.destination}", key, toast=not announce)
        if announce:
            self.core.operator.notice(Notice(
                announce + (" Transmit ENABLED; Ctrl+T turns it back off." if armed else "")))
        self.core.sessions.record(key, f"Connecting to {path.destination} on port {port}")
        # Set before the await: `AX25Station.connect` registers the link
        # synchronously before it awaits anything, so a disconnect can find
        # and cancel it mid-attempt.
        self.connecting[key] = (path.destination, port)
        self.core.events.publish(ConnectingChanged())
        try:
            link = await station.connect(
                path,
                port=port,
                paclen=entry_link_override(reminder.paclen) if reminder else None,
                window=entry_link_override(reminder.window) if reminder else None,
            )
        except TransportError as exc:
            self._problem(report, str(exc))
            return
        finally:
            self.connecting.pop(key, None)
            self.core.events.publish(ConnectingChanged())
        if link is None:
            failed = station.link_to(path.destination, port)
            reason = getattr(failed, "last_error", "") if failed else ""
            if reason == CANCELLED_REASON:
                self.core.sessions.record(key, f"Connect to {path.destination} cancelled")
                return
            # Say WHY: a DM is a refusal (configuration), silence after N2
            # is the path (antenna, power, propagation).
            attempts = getattr(failed, "rc", 0) if failed else 0
            detail = f" -- {reason}" if reason else ""
            why = f"Could not connect to {path.destination}{detail}."
            if attempts:
                why += (f" {attempts} attempt(s) sent; the Monitor tab (F8) shows "
                        "what went out and what came back.")
            # It was up when we started, so a transport that is down NOW
            # dropped during the attempt and some SABMs never left the
            # process. Say so, or the operator spends the evening on an
            # antenna that is fine.
            if station.transport.state is not TransportState.OPEN:
                why += (" The link to the TNC dropped during this attempt, so some "
                        "of those frames never reached the radio. Fix that first -- "
                        "this is not an RF failure.")
            self.core.sessions.record(key, why)
            self._problem(report, why.rstrip("."), Severity.WARNING)
            return
        self.core.sessions.bind(link, key)
        if on_link is not None:
            on_link(link, key)
        # Explicit: `AX25Station.connect` ran the SABM/UA exchange before
        # returning this link, so the transition INTO connected fired to
        # nobody. It is the one an operator most needs to see, and the
        # transcript needs it at the time it happened, not at the next
        # transition.
        self.core.sessions.note(key, f"Connected to {link.peer}")
        if focus and self.view.is_active(key):
            # Only if the operator is still looking at this session -- a
            # long SABM retry or hop chain can outlast several tab switches.
            self.view.focus_input()
        if len(chain) > 1:
            # The AX.25 link is only to the FIRST node; the rest is that
            # node's own onward routing, driven by watching its replies.
            if not await self.hop_through(link, key, chain[1:], report):
                # Left connected to whichever node was last reached. Neither
                # the address book nor a login should treat a chain that
                # stalled partway as having reached `target`.
                if on_reached is not None:
                    on_reached(False)
                return
        # Separate from the attempt already recorded: "tried ten times, never
        # got in" is a different fact from "this one works".
        if addressbook is not None:
            addressbook.record_connect(target)
        login = self.resolve_login(request.credential, request.script_name, request.script)
        if login.strip():
            self.run_connect_script(link, key, login)
        if on_reached is not None:
            on_reached(True)

    # ------------------------------------------------------------------
    # The Internet and the session tier
    # ------------------------------------------------------------------
    async def session_connect(self, transport):
        """`transport.connect()`, asking the operator to trust an SSH server
        seen for the first time (kissterm/transport/ssh.py). Not trusting
        it is a `TransportError` like any other failed connect."""
        from ..transport.ssh import UnknownHostKey, trust_host_key

        try:
            return await transport.connect()
        except UnknownHostKey as unknown:
            trusted = await self.core.operator.ask(TrustHostKey(
                unknown.host, unknown.port, unknown.key_type, unknown.fingerprint,
                str(unknown.path)))
            if not trusted:
                raise TransportError(
                    f"{unknown.host}:{unknown.port}: host key not trusted; "
                    "nothing was sent.") from None
            try:
                trust_host_key(unknown.path, unknown.line)
            except OSError as exc:
                raise TransportError(
                    f"could not save the host key to {unknown.path}: {exc}") from exc
            return await transport.connect()

    async def dial_internet(self, entry, *, on_link=None, on_reached=None,
                            focus: bool = True, report=None) -> None:
        """Dial an Internet contact (`Entry.connect_by` "telnet" or "ssh")
        into its own session, beside any radio session (operator,
        2026-09-26). Its own transport, built the one way every transport is
        (`build_transport`), opened now and closed with the session.

        The transmit gate is neither checked nor armed: nothing here can
        key a radio, and arming would open RF for everything else too.
        """
        from ..transport import build_transport

        key = entry.target

        def reached(ok: bool) -> None:
            if on_reached is not None:
                on_reached(ok)

        if self.session_is_live(key):
            self._problem(report, f"Already connected to {key}.", Severity.INFORMATION)
            reached(False)
            return
        try:
            transport = build_transport(entry.transport_config(
                lambda name: find_credential(self.config, name),
                lambda name: credential_username(self.config, name)))
        except (TransportError, TypeError, ValueError) as exc:
            self._problem(report, f"{key}: {exc}")
            reached(False)
            return
        if self.core.addressbook is not None:
            self.core.addressbook.record_attempt(
                entry.target, entry.script, "", entry.credential, entry.script_name)
        self.last_connect[key] = ConnectRequest(entry.target)
        self.last_connect_key = key
        self.view.open_session(key, kind="internet", focus=focus)
        where = entry.host + (f":{entry.port}" if entry.port else "")
        self.core.sessions.record(key, f"Connecting to {key} by {entry.connect_by.upper()} ({where}), "
                              "over the Internet")
        task = asyncio.current_task()
        assert task is not None
        self.internet_connecting[key] = task
        self.core.events.publish(ConnectingChanged())
        try:
            await transport.open()
            session = await self.session_connect(transport)
        except asyncio.CancelledError:
            self.core.sessions.record(key, "Connect cancelled by operator")
            with contextlib.suppress(Exception):
                await transport.close()
            reached(False)
            return
        except (TransportError, OSError) as exc:
            self.core.sessions.record(key, f"Could not connect: {exc}")
            self._problem(report, f"{key}: {exc}")
            with contextlib.suppress(Exception):
                await transport.close()
            reached(False)
            return
        finally:
            self.internet_connecting.pop(key, None)
            self.core.events.publish(ConnectingChanged())
        link = SessionLinkAdapter(session, transport)
        if on_link is not None:
            on_link(link, key)
        self.core.sessions.bind(link, key, activate=focus)
        self.core.sessions.note(key, f"Connected to {key}")
        if self.core.addressbook is not None:
            self.core.addressbook.record_connect(entry.target)
        if focus:
            self.view.focus_input()
        login = self.resolve_login(entry.credential, entry.script_name, entry.script)
        if login.strip():
            self.run_connect_script(link, key, login)
        reached(True)

    async def connect_session_transport(self) -> None:
        """Connect through the session-tier transport (Telnet, SSH, VARA,
        Mercury, kernel AX.25): one destination, the one it was configured
        with, so no target, hop chain or Address Book. The auto-login comes
        from the transport's own config entry (`Transport.script`); its last
        line can be "C <node>" like a hand-typed hop. Always the permanent
        `""` session: this tier never has more than one.
        """
        transport = self.core.session_transport
        current = self.core.sessions.link(self.view.active_key())
        if current is not None and current.connected:
            self.core.operator.notice(Notice("Already connected.", Severity.WARNING))
            return
        key_before = self.view.active_key()
        self.view.open_session("", kind="session", focus=True)
        self.arm_for(f"connect via {transport.info.detail}", key_before)
        self.core.sessions.record("", f"Connecting to {transport.info.detail}")
        connect_task = asyncio.current_task()
        assert connect_task is not None
        self.session_connect_task = connect_task
        self.core.events.publish(ConnectingChanged())
        try:
            session = await self.session_connect(transport)
        except asyncio.CancelledError:
            # A disconnect is an operator decision, not a failed connection.
            # SessionTransport implementations clean up their partly-open
            # connection before propagating this cancellation.
            self.core.sessions.record("", "Connect cancelled by operator")
            return
        except TransportError as exc:
            self.core.sessions.record("", f"Could not connect: {exc}")
            self.core.operator.notice(Notice(str(exc), Severity.ERROR))
            return
        finally:
            if self.session_connect_task is connect_task:
                self.session_connect_task = None
                self.core.events.publish(ConnectingChanged())
        link = SessionLinkAdapter(session)
        self.core.sessions.bind(link, "")
        self.core.sessions.note("", f"Connected to {link.peer}")
        self.view.focus_input()
        login = self.resolve_login(transport.credential, transport.script_name, transport.script)
        if login.strip():
            self.run_connect_script(link, "", login)

    # ------------------------------------------------------------------
    # Hops and the auto-login
    # ------------------------------------------------------------------
    async def hop_through(self, link, key: str, nodes: list[str], report=None) -> bool:
        """Walk a chain of node-to-node hops over an already-open link:
        "C <node>", wait for that node's own CONNECTED, then the next.

        `key` is explicit, not derived from what is on screen: this can run
        for minutes and the operator may switch sessions meanwhile. Stops on
        the first hop that does not come up, leaving the link connected to
        the node last reached, and never sends the next hop's command after
        a failure -- that would transmit into a link nothing has confirmed
        is ready for it.
        """
        for node in nodes:
            if not link.connected:
                self.core.sessions.record(key, "Hop chain stopped: no longer connected")
                self._problem(report, "The hop chain stopped: no longer connected",
                              Severity.WARNING)
                return False
            if not self.gate.enabled:
                self.core.sessions.record(key, "Hop chain stopped: transmit is off")
                self._problem(report, "The hop chain stopped: transmit is off",
                              Severity.WARNING)
                return False
            ok, detail = await self.hop_to(link, key, node)
            if not ok:
                extra = f" -- {detail}" if detail else ""
                self.core.sessions.record(key, f"No connection to {node}{extra}")
                self._problem(report, f"Hop to {node} did not connect{extra}", Severity.WARNING)
                return False
        return True

    async def await_hop_confirmation(
        self, link, node: str, timeout: float | None = None,
        watch: HopConfirmation | None = None,
    ) -> tuple[bool, str]:
        """Wait for `node`'s own CONNECTED reply after a "C <node>" has
        just gone out on `link`. ``(True, "")`` on CONNECTED; ``(False,
        detail)`` on an explicit refusal (`detail` names the word) or on
        silence past `timeout` -- two diagnoses, two wordings.

        `watch` lets a caller that already subscribed hand its listener over
        (`HopConfirmation` explains why subscribing first matters); either
        way this method stops it. `timeout=None` means `hops.HOP_TIMEOUT`,
        read here rather than bound as a default, so a test can turn it down.
        """
        if timeout is None:
            timeout = hops.HOP_TIMEOUT
        if watch is None:
            watch = HopConfirmation(link, node)
        try:
            return await asyncio.wait_for(watch.result, timeout=timeout)
        except asyncio.TimeoutError:
            return False, f"no response within {timeout:.0f}s"
        finally:
            watch.stop()

    async def hop_to(self, link, key: str, node: str) -> tuple[bool, str]:
        """Send ``C <node>`` and commit the hop only if it comes up. A
        failure leaves the session's node identification untouched: the
        operator is still talking to the node they were connected to."""
        # Subscribed before the command goes out: `link.send` is an await,
        # and the node's answer could arrive during it.
        watch = HopConfirmation(link, node)
        try:
            cmd = f"C {node}"
            await link.send(cmd.encode("latin-1", "replace") + b"\r")
            # This flow confirms its own hop; a second watcher on the same
            # bytes could also reach `commit_hop`.
            self.core.sessions.echo_sent(key, cmd, cmd, watch_hop=False)
            ok, detail = await self.await_hop_confirmation(link, node, watch=watch)
        finally:
            # A send that raises never reaches the wait, and a watcher left
            # on the fan-out would match a later hop's traffic.
            watch.stop()
        if ok:
            self.core.sessions.commit_hop(key, node)
        return ok, detail

    def resolve_login(self, credential: str, script_name: str, script: str) -> str:
        """The text an auto-login sends: a saved login by name, a saved
        script by name, or literal text, checked in that order."""
        if credential:
            return saved_login_text(self.config, credential)
        if script_name:
            return find_script(self.config, script_name)
        return script

    def masked(self, text: str) -> str:
        """`text`, or `********` when it is a saved login's password. By the
        time a script runs it no longer knows which line was the secret, so
        a sent line is masked when it equals any saved password (operator's
        WS1EC SSH session, 2026-10-02)."""
        if not text.strip():
            return text
        for item in getattr(self.config, "credentials", ()):
            name = item.get("name", "")
            if name and find_credential(self.config, name) == text:
                return "********"
        return text

    def run_connect_script(self, link, key: str, script: str) -> asyncio.Task:
        """Send an auto-login in the background, one line at a time."""
        return self._spawn(self._connect_script(link, key, script))

    async def _connect_script(self, link, key: str, script: str) -> None:
        """Runs only right after a connect the operator named and confirmed,
        and rides that confirmation; it arms nothing itself. Every line is
        echoed as a typed line is -- automation the operator cannot see is
        what the gate rules exist to prevent. A closed gate or a dropped
        link stops it rather than losing lines silently."""
        lines = [ln for ln in script.splitlines() if ln.strip()]
        if not lines:
            return
        self.core.sessions.record(key, f"Auto-login: sending {len(lines)} line(s)")
        for line in lines:
            if not link.connected:
                self.core.sessions.record(key, "Auto-login stopped: no longer connected")
                return
            if not self.gate.enabled and not getattr(link, "internet", False):
                self.core.sessions.record(key, "Auto-login stopped: transmit is off")
                self.core.operator.notice(
                    Notice("Auto-login stopped: transmit is off.", Severity.WARNING))
                return
            await link.send(line.encode("latin-1", "replace") + b"\r")
            self.core.sessions.echo_sent(key, self.masked(line), line)
            await asyncio.sleep(CONNECT_SCRIPT_LINE_DELAY)

    # ------------------------------------------------------------------
    # Disconnect and reconnect
    # ------------------------------------------------------------------
    def session_is_live(self, key: str) -> bool:
        """Connected or still connecting: closing it would disconnect first."""
        link = self.core.sessions.link(key)
        connected = link is not None and link.connected
        return connected or key in self.connecting or key in self.internet_connecting

    async def disconnect(self, key: str) -> None:
        """End session `key`, or cancel its connect still in progress."""
        link = self.core.sessions.link(key)
        if link is not None and link.connected:
            # A DISC is how a link is ended politely; refusing to send it
            # leaves the far station holding a session open until ITS timers
            # give up, worse for the channel than the transmission avoided.
            if not getattr(link, "internet", False):
                self.arm_for(f"disconnect from {link.peer}")
            self.core.sessions.record(key, "Disconnecting")
            await link.disconnect()
            return
        # No established link -- but a connect may still be working through
        # its SABM retries. Without this the only way off a stuck attempt was
        # to wait out N2 while the radio kept keying up on its own.
        pending = self.connecting.get(key)
        station = self.core.station
        if pending is not None and station is not None:
            target, port = pending
            attempt = station.link_to(target, port)
            if attempt is not None and not attempt.connected:
                self.core.sessions.record(key, f"Cancelling connect to {attempt.peer} -- no "
                                      "further SABMs will be sent")
                attempt.close(reason=CANCELLED_REASON)
                return
        internet = self.internet_connecting.get(key)
        if internet is not None and not internet.done():
            self.core.sessions.record(key, "Cancelling connect")
            internet.cancel()
            return
        task = self.session_connect_task
        if key == "" and task is not None and not task.done():
            self.core.sessions.record(key, "Cancelling session transport connect")
            task.cancel()
            return
        self.core.operator.notice(Notice("Not connected.", Severity.WARNING))

    def reconnect_request(self, key: str) -> ConnectRequest | None:
        """What Reconnect would dial for session `key`: its own last
        request; for a session that answered an incoming call, its peer;
        with no session, the last thing dialed at all."""
        request = self.last_connect.get(key)
        if request is None and key:
            call, _, port = key.partition(":")
            request = ConnectRequest(call, port=int(port) if port.isdigit() else 0)
        if request is None:
            request = self.last_connect.get(self.last_connect_key)
        return request
