"""`Core`: the station with no user interface -- transports, the transmit
gate, and (as ROADMAP P7a proceeds) every flow the operator drives.

**Why this exists.** Everything kissterm does used to live in the Textual
app (`ui/app.py`), so only the terminal UI could drive it. The core is the
same behaviour with the widgets taken out, so a WebSocket server can expose
it to phone, desktop and browser clients while the terminal UI stays a
client with no visible change. It talks to whichever front end is attached
only through the `Operator` port (`operator.py`) and the event bus
(`events.py`); **nothing in `kissterm/core/` imports Textual**
(`tests/unit/test_core_boundary.py`).

**What it owns so far** (milestone 1): the station and session transport,
the transmit gate, and the transport lifecycle -- opening the first one,
switching live, and wiring every frame subscriber onto whichever transport
is current. A client registers its subscribers in `frame_subscribers`,
`sent_subscribers`, `incoming_subscribers` and `stray_poll_subscribers`
once; the core moves them on a switch, which used to be the app's job
(`_detach_transport`/`_attach_transport`), and was the source of a status
bar that kept naming the old TNC after the operator changed it.

**Single-threaded, one loop.** Everything here runs on the asyncio loop the
station runs on; nothing calls into a link from a thread (AGENTS.md
section 3).

**The gate.** The core installs one `TransmitGate` on every transport it
holds, before anything can send on it -- a freshly built transport's own
gate is OPEN (`kissterm/tx.py`), and left in place would transmit while the
operator's switch reads off.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from collections.abc import Callable

from ..ax25 import AX25Station, LinkParams
from ..ax25.address import AX25Address
from .. import identity
from ..tx import TransmitGate
from .events import ActivityChanged, ConfigChanged, EventBus, GateChanged, TransportChanged
from .operator import NullOperator, Notice, Operator, Severity
from .restart import Restarter

log = logging.getLogger(__name__)

#: Simultaneous AX.25 links. The terminal UI's tab cap
#: (`ui/terminal_pane.MAX_TERMINAL_TABS`) is this number, so the two never
#: disagree about how many connections are usable at once.
MAX_LINKS = 8

#: `Core.transport_problem` when the operator skipped the modem at launch
#: (pressed Enter while kissterm waited on it), not a failed open: nothing
#: is wrong to fix, so a front end does not open Settings over it.
TRANSPORT_SKIPPED = "skipped at startup"


def build_station(config, transport, max_links: int = MAX_LINKS) -> AX25Station:
    """The `AX25Station` for `config` on an opened frame `transport`.

    One constructor for the launch (`__main__.py`) and for a transport
    opened later (`Core.open_initial_transport`), so the link parameters
    cannot drift between the two.
    """
    return AX25Station(
        identity.parse_air_call(config) or AX25Address.parse(config.mycall),
        transport,
        LinkParams(
            paclen=config.paclen,
            window=config.window,
            modulo=config.modulo,
            retries=config.retries,
            connect_retries=config.connect_retries,
            sabm_on_poll=config.sabm_on_poll,
            t1=config.t1,
            t2=config.t2,
            t3=config.t3,
        ),
        aliases=tuple(AX25Address.parse(a) for a in config.mycall_aliases),
        accept_incoming=config.accept_incoming,
        max_links=max_links,
    )


class Core:
    """The UI-free station. See the module docstring."""

    def __init__(
        self,
        config,
        station: AX25Station | None = None,
        session_transport=None,
        transport_problem: str | None = None,
        operator: Operator | None = None,
    ) -> None:
        self.config = config
        self.operator: Operator = operator or NullOperator()
        self.events = EventBus()
        #: Exactly one of `station`/`session_transport` is set while a
        #: transport is open; both None without one.
        self.station = station
        self.session_transport = session_transport
        #: Why the configured transport would not open at launch, when the
        #: operator chose to start anyway; cleared once one opens.
        self.transport_problem = transport_problem
        #: The master transmit switch, closed unless `tx_armed_at_start`.
        self.gate = TransmitGate(enabled=getattr(config, "tx_armed_at_start", False))
        if station is not None:
            station.transport.gate = self.gate
        elif session_transport is not None:
            session_transport.gate = self.gate
        self.gate.on_change.append(lambda enabled: self.events.publish(GateChanged(enabled)))
        #: `(frame, port)` for every frame received, link-owned or not.
        self.frame_subscribers: list[Callable] = []
        #: `(frame)` for every frame the transport accepted for sending.
        self.sent_subscribers: list[Callable] = []
        #: The station's `on_incoming` and `on_stray_poll` callbacks.
        self.incoming_subscribers: list[Callable] = []
        self.stray_poll_subscribers: list[Callable] = []
        from ..addressbook import AddressBook

        #: The Address Book (`kissterm/addressbook.py`): the connect flow
        #: reads reminders from it and records attempts in it; Send/Receive
        #: finds its routes in it. Read once, here, not on every dial.
        self.addressbook = AddressBook()
        self.addressbook.load()
        #: Every session (`sessions.Sessions`) and the connect flow
        #: (`connect.Connector`), built once a client's view is attached
        #: (`attach_view`).
        self.sessions = None
        self.connector = None
        self._unsubscribes: list[Callable[[], None]] = []
        self._attached_sent: list[Callable] = []
        from ..heard import HeardTable
        from .aprs import Aprs

        #: Every station heard, with an APRS position when one was decoded.
        self.heard = HeardTable()
        #: APRS: conversations, sending with ack and retry, both beacons,
        #: GPS (`aprs.py`). Its `on_frame` is a frame subscriber, registered
        #: by whoever orders the fan-out after the heard list's own.
        self.aprs = Aprs(self)
        from .mail import Mail
        from .transfers import Transfers

        #: Mail, bulletins and files Send/Receive and the message store
        #: (`mail.py`); YAPP and AutoBIN file transfers (`transfers.py`),
        #: which read session bytes once the sessions exist (`attach_view`).
        self.mail = Mail(self)
        self.transfers = Transfers(self)
        from .channel import Channel
        from .settings import Settings

        #: Saving and applying settings (`settings.py`).
        self.settings = Settings(self)

        #: The heard list, NET/ROM claims, mail-for beacons and watched
        #: callsigns (`channel.py`). First on the fan-out, so the heard list
        #: has an entry before the APRS decode adds a position to it.
        self.channel = Channel(self)
        self.restarter = Restarter(self)
        from .identifier import Identifier

        #: Identifies the licensed call after a transmission made under a
        #: tactical call (`identifier.py`).
        self.identifier = Identifier(self)
        self.frame_subscribers += [self.channel.on_received, self.aprs.on_frame]
        self.sent_subscribers.append(self.channel.on_sent)

    def attach_view(self, view):
        """Build the sessions and the connect flow, with `view` (a client's
        `connect.SessionView`) showing them. Registers the sessions as the
        station's incoming-call and stray-poll subscribers, so call it
        before `attach_station`."""
        from .connect import Connector
        from .sessions import Sessions

        self.sessions = Sessions(self)
        self.connector = Connector(self, view)
        self.incoming_subscribers.append(self.sessions.on_incoming_link)
        self.stray_poll_subscribers.append(self.sessions.on_stray_poll)
        self.sessions.data_interceptors.append(self.transfers.intercept)
        self.sessions.sent_hooks.append(self.transfers.yapp_requested)
        return self.connector

    # ------------------------------------------------------------------
    @property
    def transport(self):
        """The transport in use, frame or session tier; None without one."""
        if self.station is not None:
            return self.station.transport
        return self.session_transport

    def save_config(self) -> bool:
        """Persist the configuration, reporting failure rather than raising:
        a read-only or full config directory must not take the station off
        the air; the in-memory value keeps working."""
        try:
            from ..config import save_config

            save_config(self.config)
            return True
        except Exception:  # noqa: BLE001 - logged, and the caller says so
            log.exception("could not save config")
            return False

    def set_activity(self, text: str) -> None:
        """What a job the operator started is doing ("Sending 1 of 2"),
        for a client's status line; "" when it is over."""
        self.events.publish(ActivityChanged(text))

    async def ask_callsign(self) -> None:
        """Change the station callsign, live and saved, without a restart.

        Refused while any session is up: the callsign is in the address
        field of every frame of every established link, and changing it
        mid-session would leave every peer answering the old call until
        each link died by N2 timeout -- a failure nobody could diagnose.
        """
        from .questions import CallsignAsk

        sessions = self.sessions.by_key.values() if self.sessions is not None else ()
        if any(s.link is not None and s.link.connected for s in sessions):
            self._notice("Disconnect every session before changing callsign.", Severity.WARNING)
            return
        current = getattr(self.config, "mycall", "") or ""
        new_call = await self.operator.ask(CallsignAsk(current))
        if not new_call or new_call == current:
            return
        self.config.mycall = new_call
        if self.station is not None:
            # The live station too, not just the file: otherwise the change
            # silently waits for the next launch.
            self.station.mycall = identity.parse_air_call(self.config) or AX25Address.parse(new_call)
        saved = self.save_config()
        self.events.publish(ConfigChanged())
        where = "saved" if saved else "applied for this session only (could not write config)"
        self._notice(f"Callsign is now {new_call} -- {where}.")

    def _notice(self, text: str, severity: Severity = Severity.INFORMATION) -> None:
        self.operator.notice(Notice(text, severity))

    def _publish_transport(self, name: str = "") -> None:
        transport = self.transport
        if transport is None:
            self.events.publish(TransportChanged(name, "", ""))
            return
        tier = "frame" if self.station is not None else "session"
        self.events.publish(TransportChanged(name, tier, transport.info.detail))

    # ------------------------------------------------------------------
    # Wiring subscribers onto the transport in use
    # ------------------------------------------------------------------
    def attach_station(self) -> None:
        """Wire every subscriber onto the station and its transport.

        Call once the subscribers are registered, from the loop the station
        runs on: `attach_transport` captures the caller's context for
        frame callbacks (`FrameTransport.callback_context`).
        """
        if self.station is None:
            return
        self.attach_transport(self.station.transport)
        # The station's own hooks survive a transport switch, so they are
        # attached here and not in `attach_transport`.
        self.station.on_incoming.extend(self.incoming_subscribers)
        self.station.on_link_created.append(self.identifier.watch)
        self.station.on_stray_poll.extend(self.stray_poll_subscribers)

    def attach_transport(self, transport) -> None:
        """Wire the gate, the callback context and the fan-out onto `transport`."""
        transport.gate = self.gate
        # Captured on the caller's loop: for the terminal UI that is the
        # app's own message loop, a context in which Textual's `active_app`
        # is set. The transport may have been opened before the app existed;
        # see `FrameTransport.callback_context` for what breaks otherwise.
        transport.callback_context = contextvars.copy_context()
        for subscriber in self.frame_subscribers:
            self._unsubscribes.append(transport.subscribe(subscriber))
        for subscriber in self.sent_subscribers:
            transport.on_sent.append(subscriber)
            self._attached_sent.append(subscriber)

    def detach_transport(self, transport=None) -> None:
        """Undo `attach_transport`, so a replaced transport feeds nothing."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        if transport is not None:
            for subscriber in self._attached_sent:
                with contextlib.suppress(ValueError):
                    transport.on_sent.remove(subscriber)
        self._attached_sent = []

    # ------------------------------------------------------------------
    # The transport lifecycle
    # ------------------------------------------------------------------
    def _entry(self, name: str) -> dict | None:
        return next((t for t in self.config.transports if t.get("name") == name), None)

    def frame_tier_transports(self) -> list[dict]:
        """Configured transports of the frame tier, when that is the tier
        in use; switching tiers live is not offered (see
        `transport.FRAME_TIER_KINDS`). Empty without a station."""
        from ..transport import FRAME_TIER_KINDS

        if self.station is None:
            return []
        return [t for t in self.config.transports if t.get("kind") in FRAME_TIER_KINDS]

    def session_tier_transports(self) -> list[dict]:
        """The session-tier counterpart of `frame_tier_transports`."""
        from ..transport import SESSION_TIER_KINDS

        if self.session_transport is None:
            return []
        return [t for t in self.config.transports if t.get("kind") in SESSION_TIER_KINDS]

    async def open_initial_transport(self, name: str) -> bool:
        """Open the saved transport `name` when none is open yet.

        A first run, or a launch whose transport would not open and the
        operator started anyway. Opening does not transmit; it builds the
        same station and fan-out that a normal launch does, so the operator
        goes straight on without a restart.
        """
        if self.station is not None or self.session_transport is not None:
            return False
        entry = self._entry(name)
        if entry is None:
            return False
        from .. import transport as transport_mod
        from ..transport.base import FrameTransport

        try:
            transport = transport_mod.build_transport(entry)
            await transport.open()
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            log.exception("could not open initial transport %s", name)
            self._notice(f"Saved {name}, but could not open it: {exc}", Severity.ERROR)
            return False

        transport.gate = self.gate
        if isinstance(transport, FrameTransport):
            self.station = build_station(self.config, transport)
            self.attach_station()
            self.aprs.follow_station()
        else:
            self.session_transport = transport
        self._publish_transport(name)
        return True

    async def switch_frame_transport(self, name: str) -> bool:
        """Open `name` and hand it to the station in place of the current
        transport (`AX25Station.rebind_transport`). True if it worked; a
        failure is reported to the operator here, so a caller acts only on
        the result.

        Frame tier only: a session transport hands back connected byte
        streams, not frames this station can run on, so this refuses one
        and says to restart with it selected.
        """
        if self.station is None:
            if self.session_transport is None:
                opened = await self.open_initial_transport(name)
                if opened:
                    self.transport_problem = None
                return opened
            return False
        entry = self._entry(name)
        if entry is None:
            return False

        from .. import transport as transport_mod
        from ..transport.base import FrameTransport

        try:
            new_transport = transport_mod.build_transport(entry)
            new_transport.gate = self.gate
            await new_transport.open()
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            log.exception("could not open %s", name)
            self._notice(f"Could not open {name}: {exc}", Severity.ERROR)
            return False

        if not isinstance(new_transport, FrameTransport):
            self._notice(
                f"{name} is a session transport; switching to it live is not "
                "supported. Restart kissterm with it selected.",
                Severity.WARNING,
            )
            with contextlib.suppress(Exception):
                await new_transport.close()
            return False

        try:
            old_transport = self.station.rebind_transport(new_transport)
        except RuntimeError as exc:
            self._notice(str(exc), Severity.WARNING)
            with contextlib.suppress(Exception):
                await new_transport.close()
            return False

        # `rebind_transport` moved only the station's own subscription; every
        # other subscriber is the core's to move.
        self.detach_transport(old_transport)
        self.attach_transport(new_transport)
        with contextlib.suppress(Exception):
            await old_transport.close()
        self._publish_transport(name)
        return True

    async def switch_session_transport(self, name: str) -> bool:
        """The session-tier counterpart of `switch_frame_transport`.

        Calls `.open()` before handing it over, as the launch does: for
        Telnet and SSH it is a no-op, but VARA's connects to the modem's
        command and data ports, so skipping it would work by accident for
        two backends and fail for the rest.
        """
        entry = self._entry(name)
        if entry is None:
            return False

        from .. import transport as transport_mod

        try:
            new_transport = transport_mod.build_transport(entry)
            new_transport.gate = self.gate
            await new_transport.open()
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            log.exception("could not open %s", name)
            self._notice(f"Could not open {name}: {exc}", Severity.ERROR)
            return False

        old_transport = self.session_transport
        self.session_transport = new_transport
        if old_transport is not None:
            with contextlib.suppress(Exception):
                await old_transport.close()
        self._publish_transport(name)
        return True
