"""Mail, bulletins and files Send/Receive, for every front end (ROADMAP
P7a M5; the flows themselves are ROADMAP P2).

What G and I do, from whichever folder the client says is in front
(`send_receive_kind`, operator 2026-09-26): the Home BBS
(`mail/collect.py` drives it), Winlink (`mail/winlink_collect.py`), or on
All Inboxes each one in use, the Home BBS first. Bulletins and files are
Home BBS runs with `CollectOptions.bulletins`/`files`.

**Everything that has to be asked is asked before the first dial**
(`_prepare_runs`), so a missing login never costs a connect's airtime and
a run of both services never stops in between. Each question is a typed
`Question` (`questions.py`); on All Inboxes it says why it is asked and
can skip its service (operator, 2026-09-27). "Go there" cancels the run
and publishes `SetupRequested`; the client knows where "there" is.

**A radio run dials through `Connector.dial_entry`**, so the reminder,
the transmit gate, the hop chain and the route's own login all apply and
nothing here arms anything. An Internet run (I) never touches the gate:
nothing in it can key a radio. Every line sent is echoed to the session
(`LineSent`) and its transcript; when a radio run finishes, the link is
disconnected. Progress goes to `core.set_activity`; the outcome is one
notice (DESIGN.md section 6: one event, one notice).

**A run can be cancelled** (`cancel`; operator, 2026-10-06, from a phone:
"tap it again to cancel and disconnect"). A run on a session (radio, or
an Internet contact) is ended the way a disconnect ends any session: its
SABMs stop, or the link gets its DISC, and the collector stops as the
link goes, reporting "cancelled". A run over the Internet with no session
of its own (the Winlink CMS, the Home BBS by I) is a task cancelled; its
`finally` closes the connection. `MailRunChanged` tells every client a
run started and ended, so a phone can offer the cancel.

**Writing, deleting and restoring are here too** (`reply_start`, `write`,
`file_outbox`, `delete`, `restore`), so the terminal and the phone do them
the same way (AGENTS.md: the front ends have parity). None of them
transmits: a written message waits in its Outbox for Send/Receive, and a
deleted one waits in Deleted for Restore (the phone's Undo).

**So are radiograms** (`radiogram_start`, `radiogram_check`,
`write_radiogram`, `radiogram_problems`): the terminal's radiogram form
and the phone's check and save the same way (operator, 2026-10-06, on
the phone: "New Message lacks NTS"). The rules are `mail/nts.py`'s.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..ax25 import parse_path
from ..ax25.address import AX25Address
from ..config import (
    credential_store,
    credential_username,
    find_credential,
    mail_path,
    set_credential,
    winlink_account,
)
from ..config import login_text as saved_login_text
from ..mail import MessageStore
from ..mail.bulletins import SubscriptionBook
from ..mail.store import ALL_INBOXES, FILES, INBOX, MAIL, SENT
from ..mail.winlink_collect import WINLINK_FOLDER
from ..monitor import sanitize
from ..session_log import SessionLog
from ..transport.base import TransportError
from .events import (
    AddressBookChanged,
    ConfigChanged,
    LineSent,
    MailChanged,
    MailRunChanged,
    SessionData,
    SetupRequested,
)
from .links import SessionLinkAdapter
from .operator import Notice, Severity
from .questions import (
    SETUP_GO,
    SETUP_SKIP,
    ChooseCategories,
    Credential,
    GatewayChoice,
    HomeBbsRoute,
    HowManyBulletins,
    InternetLogin,
    InternetLoginAsk,
    LoginAsk,
    PickFiles,
    WinlinkGateway,
)

log = logging.getLogger(__name__)

#: The CMS's own words when its production servers turn away a client
#: program they do not know (operator's first session, 2026-09-28; ROADMAP,
#: Blockers). Not the password, network or radio.
UNKNOWN_CLIENT = (
    "Winlink refused kissterm itself, not your login: its production servers "
    "accept only client programs they know, and kissterm is not one of them yet. "
    "Nothing was sent. Settings > Mail > Internet server can use Winlink's test "
    "server instead."
)


@dataclass(frozen=True, slots=True)
class ReplyStart:
    """A reply as it starts (`Mail.reply_start`). `by_number`: it goes as
    `SR <number>`, which the BBS addresses and titles, so To and Title are
    not the operator's to change."""

    to: str
    title: str
    body: str
    send_type: str
    by_number: bool
    heading: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class BulletinChoice:
    """`Mail.bulletin_categories`: the Home BBS, each category it listed
    last with its count, the ones collected, and whether all are."""

    bbs: str
    seen: dict
    chosen: list
    all: bool


#: Said when categories are asked for before any collection listed them.
NO_CATEGORIES = ("No categories yet: Get bulletins asks the BBS for its list on the "
                 "first collection.")


class SkipService(Exception):
    """The operator pressed Skip on an All Inboxes setup question."""


def login_where() -> str:
    """Where a new login's password will be kept: "keyring" or "config"."""
    from .. import keystore

    return "keyring" if keystore.available() else "config"


class Mail:
    """Send/Receive and the message store. Owned by `Core` as `core.mail`."""

    def __init__(self, core) -> None:
        self.core = core
        #: The message store behind Mail, Bulletins and Files. Under the
        #: platformdirs data directory, so `_isolate` redirects it in tests.
        self.store = MessageStore(mail_path())
        try:
            self.store.ensure_default_tree()
        except OSError:
            # An unwritable data directory must not stop the station from
            # starting; the Mail tab just shows nothing.
            pass
        #: Bulletin categories chosen per BBS (`mail/bulletins.py`).
        self.subscriptions = SubscriptionBook()
        self.subscriptions.load()
        #: True while a run is under way; one at a time.
        self.collecting = False
        #: The run's task, its session's key once it dials one, and whether
        #: `cancel` was asked for (module docstring).
        self._task: asyncio.Task | None = None
        self.session_key = ""
        self.cancel_requested = False
        #: While G or I on All Inboxes prepares its runs: (key, service
        #: being asked about), so each question says why it is asked and
        #: offers to skip that service (`_all_inboxes_ask`).
        self._all_inboxes: tuple[str, str] | None = None

    # ------------------------------------------------------------------
    @property
    def config(self):
        return self.core.config

    def _notice(self, text: str, severity: Severity = Severity.INFORMATION,
                timeout: float | None = None) -> None:
        self.core.operator.notice(Notice(text, severity, timeout=timeout))

    def _publish(self, event) -> None:
        self.core.events.publish(event)

    def _config_saved(self) -> None:
        self.core.save_config()
        self._publish(ConfigChanged())

    async def _ask(self, question):
        return await self.core.operator.ask(question)

    def downloads_dir(self) -> Path:
        """Files > Downloads in the message store, where a YAPP or AutoBIN
        download is saved, so the Files tab shows it."""
        folder = self.store.root / FILES / "Downloads"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def gateway_cache(self) -> Path:
        from ..config import state_path
        from ..winlink import gateways

        return gateways.cache_path(state_path())

    # ------------------------------------------------------------------
    # RMS gateways (F10 > Session > RMS gateways): Internet on request only
    # ------------------------------------------------------------------
    def rms_gateways(self, mode: str = "packet", limit: int = 200) -> dict:
        """The saved Winlink gateway list in `mode`, nearest first (the
        terminal's `RmsGatewaysScreen`): `channels`, a `note` saying how old
        the list is or why there is none, `modes` to choose from, and
        whether `can_refresh` (a Winlink API key is set). Reads the saved
        file only; nothing goes on the air and nothing is fetched."""
        from ..geo import compass_point
        from ..winlink import gateways

        position = self.core.aprs.own_position()
        lat, lon = position if position else (None, None)
        channels, fetched = [], None
        cached = gateways.load_cached(self.gateway_cache())
        if cached is not None:
            try:
                channels = gateways.parse(cached[0], lat=lat, lon=lon)
                fetched = cached[1]
            except ValueError:
                channels = []
        shown = gateways.nearest(channels, mode, limit=limit)
        key = bool(gateways.ACCESS_KEY)
        if fetched is not None:
            note = f"From winlink.org, {gateways.age_text(fetched)}; {len(shown)} shown."
        elif not key:
            note = ("No gateway list yet, and this version of kissterm cannot fetch one: "
                    "it is waiting for its Winlink API key.")
        else:
            note = ("No gateway list yet. Refresh fetches it from winlink.org over the "
                    "Internet; nothing goes on the air.")
        if channels and position is None:
            note += " Set your position in Settings > APRS to sort by distance."
        return {
            "channels": [{
                "callsign": sanitize(c.callsign.encode()), "frequency": c.frequency,
                "frequency_hz": c.frequency_hz, "modes": sanitize(c.modes.encode()),
                "grid": sanitize(c.grid.encode()), "hours": sanitize(c.hours.encode()),
                "distance": "" if c.distance_mi is None
                else f"{c.distance_mi:.0f} mi {compass_point(c.bearing or 0.0)}"}
                for c in shown],
            "note": note, "can_refresh": key,
            "modes": [list(m) for m in gateways.MODES],
        }

    async def rms_refresh(self) -> str:
        """Fetch the list from winlink.org (an HTTPS request, only when
        asked) and keep it; returns "" or why it was not refreshed."""
        from ..winlink import gateways

        try:
            data = await asyncio.to_thread(gateways.fetch, gateways.ACCESS_KEY)
            await asyncio.to_thread(gateways.save_cached, self.gateway_cache(), data)
        except (gateways.NoAccessKey, gateways.FetchError, OSError) as exc:
            return f"Not refreshed: {exc}."
        return ""

    def use_gateway(self, callsign: str, frequency: str = "", modes: str = "",
                    grid: str = "") -> str:
        """Make a gateway the Winlink Dial: into the Address Book (an
        entry already there keeps its hops, login and note) and as the
        Winlink route. Nothing is dialed or sent. Returns the notice."""
        if self.core.addressbook.find(callsign) is None:
            note = f"Winlink RMS, {modes}" + (f", {grid}" if grid else "")
            self.core.addressbook.upsert(callsign, frequency=frequency, note=note)
            self._publish(AddressBookChanged())
        self.config.winlink.route = callsign
        self._config_saved()
        message = (f"{callsign} ({frequency}) is in the Address Book and is now the "
                   "Winlink Dial.")
        self.core.operator.notice(Notice(message))
        return message

    # ------------------------------------------------------------------
    # The runs
    # ------------------------------------------------------------------
    def send_receive_kind(self, folder: str, internet: bool = False) -> str:
        """What G does from `folder` (operator, 2026-09-26): "winlink" on a
        Winlink folder; "bbs" anywhere else. On All Inboxes, "all" (the
        Home BBS, then Winlink) when both are in use, else whichever is,
        and "bbs" when neither is yet (the Home BBS's first-run question).

        In use = set up for G or for I, whichever key was pressed: what the
        key still needs is then asked for, with its Skip button (operator,
        2026-09-28). A service set up for neither is not asked about, so a
        BBS-only station is not asked about Winlink at every G."""
        if folder == WINLINK_FOLDER or folder.startswith(f"{WINLINK_FOLDER}/"):
            return "winlink"
        if folder == ALL_INBOXES:
            home, winlink_config = self.config.home_bbs, self.config.winlink
            bbs = bool(home.route.strip() or home.internet.strip())
            winlink = bool(winlink_config.route.strip() or winlink_config.credential.strip())
            if bbs and winlink:
                return "all"
            if winlink:
                return "winlink"
        return "bbs"

    def _busy(self) -> bool:
        if self.collecting:
            self._notice("Already sending and receiving.", Severity.WARNING)
            return True
        self.collecting = True
        self._task = asyncio.current_task()
        self.session_key = ""
        self.cancel_requested = False
        self._publish(MailRunChanged(True))
        return False

    def _done(self) -> None:
        self.collecting = False
        self._task = None
        self.session_key = ""
        self.core.set_activity("")
        self._publish(MailRunChanged(False))

    def _cancelled(self) -> bool:
        """Whether a CancelledError reaching a run is `cancel`'s, which
        ends the run quietly rather than the task it runs in."""
        if not self.cancel_requested:
            return False
        task = asyncio.current_task()
        if task is not None:
            task.uncancel()
        self._notice("Send/Receive cancelled.")
        return True

    async def cancel(self) -> bool:
        """Stop the run under way (module docstring). False if none is."""
        if not self.collecting:
            return False
        self.cancel_requested = True
        key = self.session_key
        connector = self.core.connector
        if key and connector is not None and connector.session_is_live(key):
            await connector.disconnect(key)
        elif self._task is not None and self._task is not asyncio.current_task():
            self._task.cancel()
        return True

    async def send_receive(self, folder: str, *, internet: bool = False) -> None:
        """Send/Receive (G; I with `internet`) for the folder in front."""
        if self._busy():
            return
        try:
            kind = self.send_receive_kind(folder, internet=internet)
            if internet:
                runs = await self._prepare_runs(kind, "I", (
                    ("Home BBS", self._bbs_internet_prepare, self._bbs_internet_run),
                    ("Winlink", self.winlink_login, self._winlink_cms_run),
                ))
                for run, args in runs or ():
                    if self.cancel_requested:
                        break
                    await run(*args)
            else:
                runs = await self._prepare_runs(kind, "G", (
                    ("Home BBS", self._bbs_prepare, self._bbs_run),
                    ("Winlink", self._winlink_prepare, self._winlink_run),
                ))
                for run, (entry, options) in runs or ():
                    if self.cancel_requested:
                        break
                    await run(entry, options)
        except asyncio.CancelledError:
            if not self._cancelled():
                raise
        finally:
            self._done()

    async def get_bulletins(self, *, internet: bool = False) -> None:
        """Get bulletins: the Home BBS run with `CollectOptions.bulletins`,
        the categories chosen (`mail/bulletins.py`) offered on the first run
        and when a check finds a new one (`choose_categories`)."""
        if self._busy():
            return
        try:
            prepared = await (self._bbs_internet_prepare() if internet
                              else self._bbs_prepare())
            if prepared is None:
                return
            entry, options = prepared
            home = self.config.home_bbs
            options.bulletins = True
            options.check_days = home.bulletin_check_days
            options.first_days = home.bulletin_days
            run = self._bbs_internet_run if internet else self._bbs_run
            await run(entry, options)
        except SkipService:
            pass
        except asyncio.CancelledError:
            if not self._cancelled():
                raise
        finally:
            self._done()

    async def get_files(self) -> None:
        """Get files from the Home BBS, by radio only: `FILES`, the
        operator's pick (`pick_files`) and a YAPP download of each. No
        Internet twin: YAPP does not survive a server's telnet."""
        if self._busy():
            return
        try:
            prepared = await self._bbs_prepare()
            if prepared is None:
                return
            entry, options = prepared
            options.files = True
            await self._bbs_run(entry, options)
        except SkipService:
            pass
        except asyncio.CancelledError:
            if not self._cancelled():
                raise
        finally:
            self._done()

    async def _prepare_runs(self, kind: str, key: str, services) -> list | None:
        """Ask everything each service in `kind` needs, in order; the runs
        to make, or None if the operator cancelled. On All Inboxes each
        question says why it is asked and can skip its service (operator,
        2026-09-27: make it "clear why they're being prompted")."""
        wanted = [s for s in services
                  if kind == "all" or s[0] == ("Winlink" if kind == "winlink" else "Home BBS")]
        runs = []
        try:
            for name, prepare, run in wanted:
                self._all_inboxes = (key, name) if kind == "all" else None
                try:
                    prepared = await prepare()
                except SkipService:
                    self._notice(f"Skipping {name} this time.")
                    continue
                if prepared is None:
                    return None
                runs.append((run, prepared))
        finally:
            self._all_inboxes = None
        if not runs:
            self._notice("Nothing to send or receive: every service was skipped.")
        return runs

    def _all_inboxes_ask(self) -> tuple[str, str]:
        """(note, skip label) for a question asked on All Inboxes, else ("", "")."""
        if self._all_inboxes is None:
            return "", ""
        key, name = self._all_inboxes
        how = " over the Internet" if key == "I" else ""
        # The operator's wording, 2026-09-27.
        return (
            f"You have All Inboxes selected, therefore kissterm will check mail "
            f"for both BBS and Winlink{how}.",
            f"Skip {name}",
        )

    def _setup_answer(self, answer, place: str):
        """A setup question's answer: SETUP_SKIP raises `SkipService`,
        SETUP_GO asks the client to show `place` and returns None (the run
        is cancelled), anything else is returned."""
        if answer == SETUP_SKIP:
            raise SkipService
        if answer == SETUP_GO:
            self._publish(SetupRequested(place))
            return None
        return answer

    # ------------------------------------------------------------------
    # Asking for what is missing
    # ------------------------------------------------------------------
    async def _winlink_gateway(self):
        """The Address Book contact to reach Winlink through: the favourite
        gateway (Settings > Mail > Gateway contact) when it is in the book,
        else the one chosen now, added to the book and remembered as the
        favourite if asked. None if cancelled."""
        from ..winlink import gateways

        addressbook = self.core.addressbook
        favourite = self.config.winlink.route.strip()
        entry = addressbook.find(favourite) if favourite else None
        if entry is not None:
            return entry
        note, skip = self._all_inboxes_ask()
        has_list = bool(gateways.ACCESS_KEY) or gateways.load_cached(self.gateway_cache()) is not None
        answer = self._setup_answer(await self._ask(WinlinkGateway(
            tuple(e.target for e in addressbook.entries if not e.is_internet), favourite,
            gateway_list=has_list, all_note=note, skip=skip)), "winlink")
        if not isinstance(answer, GatewayChoice):
            return None
        entry = addressbook.find(answer.target)
        if entry is None:
            channel = answer.channel
            details = {} if channel is None else {
                "frequency": channel.frequency,
                "note": f"Winlink RMS, {channel.modes}" + (f", {channel.grid}" if channel.grid else ""),
            }
            entry = addressbook.upsert(answer.target, **details)
            self._publish(AddressBookChanged())
        if answer.remember and self.config.winlink.route != entry.target:
            self.config.winlink.route = entry.target
            self._config_saved()
        return entry

    async def _mail_route(self, route: str):
        """The Address Book entry `route` names, asking for one (and saving
        the answer) on first use or when the entry is gone; None if the
        operator cancelled."""
        addressbook = self.core.addressbook
        entry = addressbook.find(route.strip()) if route.strip() else None
        if entry is not None:
            return entry
        note, skip = self._all_inboxes_ask()
        targets = tuple(e.target for e in addressbook.entries)
        chosen = self._setup_answer(await self._ask(
            HomeBbsRoute(targets, missing=route.strip(), all_note=note, skip=skip)
        ), "connect" if not targets else "bbs")
        entry = addressbook.find(chosen) if chosen else None
        if entry is None:
            return None
        self.config.home_bbs.route = entry.target
        self._config_saved()
        return entry

    async def _ask_login(self, current: str, default_name: str, title: str, detail: str,
                         *, secret: bool = True,
                         username: bool = False) -> tuple[str, str] | None:
        """The saved login `current` names, as (name, password); if there
        is none or it cannot be read, ask for it before dialing and save it
        (with `username`, its username too). None if cancelled."""
        text = find_credential(self.config, current) if current else ""
        if text:
            return current, text
        # A name that is no saved login may be a password typed in its place:
        # never show it, save under the fixed name instead.
        name = current if current and credential_store(self.config, current) else default_name
        note, skip = self._all_inboxes_ask()
        answer = self._setup_answer(await self._ask(LoginAsk(
            title, detail, name, secret=secret, all_note=note, skip=skip,
            username=credential_username(self.config, name) if username else None,
            where=login_where() if username else "")), "")
        if not answer:
            return None
        text = answer.text if isinstance(answer, Credential) else answer
        where = set_credential(self.config, name, text, username=(
            answer.username if isinstance(answer, Credential) else None))
        self.core.save_config()
        self._notice(
            f"Saved the login \"{name}\" in "
            + ("the system keyring." if where == "keyring" else "config.toml (no system keyring here)."),
        )
        return name, text

    # ------------------------------------------------------------------
    # Dialing
    # ------------------------------------------------------------------
    def connected_to(self, peer: AX25Address) -> bool:
        """Whether a session is already connected to `peer` over AX.25.
        Only an AX.25 link has an address to compare: a session-tier link's
        peer is a host or a modem's name (operator, 2026-10-03: G on Mail
        with WS1EC's SSH login open crashed here)."""
        return any(
            s.link is not None and s.link.connected
            and isinstance(s.link.peer, AX25Address)
            and (s.link.peer.callsign, s.link.peer.ssid) == (peer.callsign, peer.ssid)
            for s in self.core.sessions.by_key.values()
        )

    async def _dial(self, entry, build, doing: str, label: str = "Send/Receive"):
        """Dial `entry` for a Home BBS or Winlink run. `build(link, key)`
        makes the runner the moment the link is up, before anything awaits,
        so the far end's first bytes are not missed; it starts once the
        chain has reached the target. Returns (runner, key), or None having
        said why. `doing` ("get files") goes in the connect notice and
        `label` ("Get files") leads a failure's, so each says what was
        asked for (operator, 2026-10-04)."""
        first = [h.strip() for h in entry.hops.split(",") if h.strip()] or [entry.target]
        peer = parse_path(first[0]).destination
        if self.connected_to(peer):
            self._notice(f"Already connected to {peer}. Disconnect first, then press {{key:get_mail}}.",
                         Severity.WARNING)
            return None
        state: dict = {"runner": None, "key": "", "reached": False}

        def on_link(link, key: str) -> None:
            state["key"] = key
            state["runner"] = build(link, key)

        def on_reached(reached: bool) -> None:
            state["reached"] = reached

        # One notice says a connect is under way (and that transmit was
        # enabled, if it was); a failure is one notice too: the connect
        # hands its reason here (`report`) rather than raising its own
        # beside this one (operator, 2026-10-02: two toasts per event).
        reasons: list[str] = []
        announce = f"Connecting to {entry.target} to {doing}..."
        if entry.is_internet:
            # No transmit gate on the Internet, so nothing to fold in.
            self._notice(announce)
            announce = ""
        self.core.set_activity(f"Connecting to {entry.target}")
        # The key `Connector` gives the session, so `cancel` can end it.
        self.session_key = entry.target if entry.is_internet else str(peer)
        await self.core.connector.dial_entry(
            entry, on_link=on_link, on_reached=on_reached, focus=False,
            announce=announce, report=reasons.append,
        )
        runner = state["runner"]
        why = reasons[-1].rstrip(".") if reasons else f"did not reach {entry.target}"
        if runner is None:
            # No reason means the operator cancelled (the reminder, a
            # disconnect): nothing to tell them, unless it was `cancel`,
            # which a remote tap asked for and wants to see done.
            if reasons:
                self._notice(f"{label}: {why}.", Severity.ERROR)
            elif self.cancel_requested:
                self._notice(f"{label} cancelled.")
            return None
        if not state["reached"]:
            runner.close()
            self._notice(f"{label}: {why}.", Severity.ERROR)
            return None
        return runner, state["key"]

    def _note(self, key: str, text: str) -> None:
        """A Send/Receive progress sentence, for the transcript only."""
        self.core.sessions.record(key, f"Mail: {text}")

    def _sent(self, key: str, text: str) -> None:
        """Echo a line Send/Receive sent, as a typed line is echoed."""
        self._publish(LineSent(key, self.core.connector.masked(text)))
        self.core.sessions.log_sent(key, text, watch_hop=False)

    def _received(self, key: str, text: str) -> None:
        """A line from the Winlink gateway, shown and kept in the
        transcript as received text (the raw bytes are suppressed)."""
        data = (text + "\r").encode("latin-1", errors="replace")
        self._publish(SessionData(key, data))
        session = self.core.sessions.get(key)
        if session is not None and session.transcript is not None:
            session.transcript.received_stream(data, sanitize)

    def _transferring(self, key: str, on: bool) -> None:
        """A files run's download starting or ending on session `key`: the
        session's bytes are the transfer's meanwhile."""
        if on:
            self.core.transfers.active.add(key)
        else:
            self.core.transfers.active.discard(key)

    def _gate_open(self) -> bool:
        return self.core.gate.enabled

    # ------------------------------------------------------------------
    # The Home BBS by radio
    # ------------------------------------------------------------------
    async def _bbs_prepare(self):
        """Everything the Home BBS run needs before dialing, asking for
        what is missing: (entry, options), or None if cancelled."""
        from ..mail.collect import CollectOptions

        home = self.config.home_bbs
        entry = await self._mail_route(home.route)
        if entry is None:
            return None
        login_text = ""
        if home.login_prompt:
            # Settings says the BBS asks for a login: have it before dialing.
            login = await self._ask_login(
                home.credential, "Home BBS", "Home BBS login", "", username=True)
            if login is None:
                return None
            if home.credential != login[0]:
                home.credential = login[0]
                self._config_saved()
            # The username line, then the password (a saved login's shape).
            login_text = saved_login_text(self.config, login[0]) or login[1]
        options = CollectOptions(
            bbs_call=home.call,
            software=home.software,
            ready_text=home.ready_text,
            login_prompt=home.login_prompt,
            login_text=login_text,
            sign_off=True,
        )
        return entry, options

    async def _bbs_run(self, entry, options) -> None:
        """The Home BBS: `kissterm/mail/collect.py` drives it."""
        from ..mail.collect import BbsCollector

        def build(link, key: str):
            return BbsCollector(
                link,
                self.store,
                options,
                note=lambda text: self._note(key, text),
                sent=lambda text: self._sent(key, text),
                gate_open=self._gate_open,
                progress=self.core.set_activity,
                subscriptions=self.subscriptions,
                choose=self.choose_categories,
                how_many=lambda count, categories: self.how_many_bulletins(
                    count, categories, radio=True),
                pick_files=self.pick_files,
                files_dir=self.downloads_dir() if options.files else None,
                transferring=lambda on: self._transferring(key, on),
            )

        if options.files:
            doing, label = "get files", "Get files"
        elif options.bulletins:
            doing, label = "get bulletins", "Get bulletins"
        else:
            doing, label = "send and receive mail", "Send/Receive"
        dialed = await self._dial(entry, build, doing, label)
        if dialed is None:
            return
        collector, key = dialed
        result = await collector.run()
        self.bbs_report(result, bulletins=options.bulletins, files=options.files)
        if not result.stopped and not self.cancel_requested:
            await collector.sign_off()
        if collector.link.connected:
            # The BBS did not hang up after `B` (or the run stopped first).
            await self.core.connector.disconnect(key)

    def bbs_report(self, result, bulletins: bool = False, files: bool = False) -> None:
        """The outcome notice of a Home BBS run, over radio or the Internet."""
        if self.cancel_requested and result.stopped:
            result.stopped = "cancelled"
        sent = f"{len(result.sent)} sent, " if result.sent else ""
        if not files and not bulletins:
            self.answer_receipts(list(result.filed))
        if files:
            got = len(result.downloaded)
            if result.stopped:
                self._notice(f"Getting files stopped: {result.stopped}. {got} downloaded.",
                             Severity.WARNING)
            elif got:
                self._notice(f"{got} file(s) downloaded into Files > Downloads.")
            elif not result.listed:
                self._notice("The Home BBS lists no files.")
            self._publish(MailChanged())
            return
        if bulletins:
            if result.stopped:
                self._notice(f"Getting bulletins stopped: {result.stopped}. "
                             f"{len(result.filed)} received.", Severity.WARNING)
            elif result.filed:
                self._notice(f"{len(result.filed)} new bulletin(s) from the Home BBS.")
            else:
                self._notice("No new bulletins on the Home BBS.")
            self._publish(MailChanged())
            return
        if "unknown client type" in result.stopped.lower():
            self._notice(UNKNOWN_CLIENT, Severity.WARNING, timeout=15)
        elif result.stopped:
            self._notice(f"Send/Receive stopped: {result.stopped}. "
                         f"{sent}{len(result.filed)} received.", Severity.WARNING)
        elif result.filed:
            self._notice(f"{sent}{len(result.filed)} new message(s) from the Home BBS.")
        elif result.sent:
            self._notice(f"{len(result.sent)} sent. No new mail on the Home BBS.")
        else:
            self._notice("No new mail on the Home BBS.")
        self._publish(MailChanged())

    def routing(self, ref: str) -> list[str]:
        """The `R:` lines of a message from a BBS (`bpqmail.routes_of`)."""
        from ..mail.bpqmail import routes_of

        return routes_of(self.store, ref)

    # -- writing, deleting, restoring (every front end) ----------------
    def reply_start(self, ref: str, *, quoted: bool | None = None,
                    everyone: bool = False) -> ReplyStart:
        """How a reply to `ref` starts: addressed, titled, quoted when asked
        (`quoted` None: as Settings > Mail says; R, and the phone's Reply).
        `everyone` is Reply all: a Winlink message's other recipients too."""
        from ..mail.compose import (
            MAX_TITLE, MAX_WINLINK_TITLE, SEND_PRIVATE, SEND_WINLINK, can_reply_by_number,
            is_winlink, quote, reply_all_to, reply_title,
        )

        original = self.store.read(ref)
        winlink = is_winlink(original)
        by_number = not winlink and can_reply_by_number(original)
        if quoted is None:
            quoted = self.config.reply_quote
        number = original.extra.get("Bbs-Number", "")
        heading = f"Reply to #{number}" if number else "Reply"
        heading += f" from {original.sender}" + (" by Winlink" if winlink else "")
        return ReplyStart(
            to=reply_all_to(original, str(self.config.mycall or "")) if everyone
            else original.sender,
            title=reply_title(original.subject, MAX_WINLINK_TITLE if winlink else MAX_TITLE),
            body="\n\n" + quote(original) if quoted else "",
            send_type=SEND_WINLINK if winlink else SEND_PRIVATE,
            by_number=by_number,
            heading=heading,
            note=(f"Sent as SR {number}: {original.source.removeprefix('BBS ')} "
                  "addresses and titles it.") if by_number else "",
        )

    def _prepare(self, to: str, at: str, title: str, body: str, send_type: str,
                 reply_to: str, form_id: str = ""):
        """The checks and the message for `write` and `write_form`:
        (problems, message); no message while there is a problem."""
        from ..mail.compose import (
            SEND_BULLETIN, SEND_PRIVATE, SEND_WINLINK, can_reply_by_number, check,
            check_winlink, is_winlink, outbox_message,
        )

        original = self.store.read(reply_to) if reply_to else None
        if original is not None:
            # A reply goes as its original's kind, whatever was asked.
            send_type = SEND_WINLINK if is_winlink(original) else SEND_PRIVATE
        if send_type not in (SEND_PRIVATE, SEND_BULLETIN, SEND_WINLINK):
            return [f"Unknown message type {send_type!r}."], None
        if send_type == SEND_WINLINK:
            problems = check_winlink(to, title, body)
        else:
            by_number = original is not None and can_reply_by_number(original)
            problems = check(to, at, title, body, reply_by_number=by_number)
        if problems:
            return problems, None
        return [], outbox_message(sender=str(self.config.mycall or ""), to=to, at=at,
                                  title=title, body=body, send_type=send_type,
                                  reply_to=original, form_id=form_id)

    def write(self, *, to: str, at: str = "", title: str, body: str,
              send_type: str = "P", reply_to: str = "") -> tuple[list[str], str]:
        """Check a message and file it in its Outbox: (problems, folder).
        Nothing is filed while there is a problem, and nothing transmits:
        the message waits for Send/Receive. The checks are the terminal's
        compose screen's (`mail/compose.py`), BPQMail's and Winlink's own."""
        problems, message = self._prepare(to, at, title, body, send_type, reply_to)
        if problems:
            return problems, ""
        return [], self.file_outbox(message)

    #: The largest file a client may add to Files/Uploads: a file this size
    #: is already hours of packet, and the station holds it in memory.
    MAX_UPLOAD = 1 << 20

    def save_upload(self, name: str, data: bytes) -> str:
        """A file from a client's own storage, kept in Files/Uploads so it
        can be sent (Transfers) from there. The name is cleaned and never
        replaces a file (`attachments.save_attachment`). Returns its ref;
        ValueError when empty or over `MAX_UPLOAD`. Nothing transmits."""
        from ..mail.attachments import save_attachment
        from ..mail.store import FILES

        if not data:
            raise ValueError("That file is empty.")
        if len(data) > self.MAX_UPLOAD:
            raise ValueError(f"That file is over {self.MAX_UPLOAD // 1024} KiB, "
                             "more than is worth sending by packet.")
        root = self.store.root.resolve()
        try:
            path = save_attachment(root / FILES / "Uploads", name, data)
        except OSError as exc:
            raise ValueError(f"Cannot save it: {exc}") from None
        self._publish(MailChanged())
        return path.relative_to(root).as_posix()

    # -- forms (the terminal's Type > a form, the phone's) -----------------
    def forms_list(self) -> list[dict]:
        """The forms a new message can be written on (`mail/forms.py`)."""
        from ..mail import forms

        # A pasted strip comes first, as in the terminal's Type list.
        return [{"id": forms.PASTE_STRIP.id, "title": forms.PASTE_STRIP.title}] + [
            {"id": f.id, "title": f.title} for f in forms.load_forms() if not f.hidden]

    STRIP_KEY = "strip:"

    def _form(self, key: str):
        """A form from its key: a shipped form's id, or `strip:` and the
        text of an information strip (a strip's questions are the form)."""
        from ..mail import forms

        if key.startswith(self.STRIP_KEY):
            return forms.strip_form(key.removeprefix(self.STRIP_KEY))
        return forms.get_form(key)

    def reply_choices(self, ref: str) -> dict:
        """What a received message can be answered on, besides a plain
        reply: `form` (it is a form with a reply form, the ICS-213) and
        `strip` (it carries an information strip), the key to open."""
        from ..mail import form_parse, forms

        original = self.store.read(ref)
        strip = forms.find_strip(original.body)
        return {"form": form_parse.reply_form_for(original) is not None,
                "strip": self.STRIP_KEY + strip if strip else ""}

    def _form_ctx(self) -> tuple[Path, str]:
        from ..config import state_path
        from ..locator import to_grid

        aprs = self.config.aprs
        grid = to_grid(aprs.latitude, aprs.longitude) if aprs.latitude or aprs.longitude else ""
        return state_path() / "forms.json", grid

    def form_start(self, form_id: str, reply_to: str = "") -> dict:
        """A form and the values it opens with: dates now, this station's
        call and grid, and what was kept from the last time (the station
        half, never the message half). `form_id` may be `strip:<text>`.
        With `reply_to`, the form is that message's reply form with the
        original's own blocks filled in (read-only). `key` is what to pass
        back to `form_check` and `write_form`. ValueError for an unknown
        form."""
        from ..mail import form_parse, forms

        seed: dict = {}
        if reply_to:
            found = form_parse.reply_form_for(self.store.read(reply_to))
            if found is None:
                raise ValueError("That message has no reply form.")
            form, seed = found
            form_id = form.id
        else:
            form = self._form(form_id)
        remembered, grid = self._form_ctx()
        values = forms.defaults(
            form, mycall=str(self.config.mycall or ""), grid=grid,
            remembered=forms.load_remembered(remembered, form.id))
        values.update(seed)
        return {"form": form, "values": values, "key": form_id}

    def form_check(self, form_id: str, values: dict) -> dict:
        """What stops the form being finished (`problems`), and when none,
        the message it makes: `to`, `at`, `title`, `body`, `send_type`, to
        go in the writer for addressing. Files nothing."""
        from ..mail import forms
        from ..mail.compose import MAX_TITLE

        form = self._form(form_id)
        found = forms.problems(form, values)
        if found:
            return {"problems": found}
        if form is forms.PASTE_STRIP:
            # Pasting is the first of two steps: the strip's questions are next.
            return {"problems": [], "next_form": self.STRIP_KEY + forms.find_strip(values["strip"])}
        subject, body = forms.render(form, values)
        # BPQMail cuts a title at 60; cut it at a word so no half-number is left.
        if len(subject) > MAX_TITLE:
            subject = subject[:MAX_TITLE + 1].rsplit(" ", 1)[0]
        to = values.get(form.to_field, "") if form.to_field else form.to
        return {"problems": [], "to": to, "at": form.at, "title": subject, "body": body,
                "send_type": form.send_type}

    def mail_log_entries(self) -> list:
        """Every dated message in a Mail Inbox or Sent folder (BBS,
        Winlink, and their subfolders): what an ICS-309 logs."""
        from ..mail import forms

        entries = []
        for folder in self.store.folders():
            parts = folder.split("/")
            if parts[0] != MAIL or not {INBOX, SENT} & set(parts):
                continue
            for summary in self.store.list(folder):
                if summary.date is not None:
                    entries.append(forms.MailEntry(summary.date, summary.sender, summary.to,
                                                   summary.subject))
        return entries

    def form_mail_log(self, form_id: str, field_id: str, since: str) -> dict:
        """The lines a form's mail log would take (the ICS-309) for the
        mail since `since` (`2026-09-26 14:00` or a date): `rows`, or
        `problem` when the time is not one."""
        from ..mail import forms

        when = forms.parse_since(since)
        if when is None:
            return {"rows": [], "problem": "Time as 2026-09-26 14:00 or 2026-09-26."}
        field = forms.get_form(form_id).field(field_id)
        return {"rows": forms.mail_log_rows(field, self.mail_log_entries(), when), "problem": ""}

    def write_form(self, *, form_id: str, values: dict, to: str, at: str = "", title: str,
                   body: str, send_type: str = "P",
                   reply_to: str = "") -> tuple[list[str], str, str]:
        """File a message written on a form: (problems, folder, note). The
        form's id is kept as the `Form:` header, what the station half
        remembers is kept for next time, and a Winlink message on a form
        with a Winlink viewer carries its XML, unless the text was changed
        after the form (the XML would show a viewer something other than
        what was sent). Nothing transmits."""
        from ..mail import form_xml, forms
        from ..mail.compose import SEND_WINLINK

        form = self._form(form_id)
        problems, message = self._prepare(to, at, title, body, send_type, reply_to,
                                          form_id=form.id)
        if problems:
            return problems, "", ""
        remembered, grid = self._form_ctx()
        forms.save_remembered(remembered, form.id, forms.to_remember(form, values))
        xml, note = None, ""
        if message.extra.get("Send-Type") == SEND_WINLINK and form.winlink_viewer:
            if body.rstrip() == forms.render(form, values)[1].rstrip():
                try:
                    xml = form_xml.build(form, values, callsign=str(self.config.mycall or ""),
                                         grid=grid)
                except form_xml.TooManyRows as exc:
                    note = f"{exc}, so it goes as text only."
            else:
                note = "The text was changed after the form, so it goes as text only."
        return [], self.file_outbox(message, raw=xml, raw_suffix=".xml"), note

    # -- radiograms (the terminal's radiogram form, the phone's) ----------
    def radiogram_start(self, ics213: bool = False) -> dict:
        """A new radiogram's defaults: the next number and the last place
        of origin (from the Outbox and Sent), this station as origin, HXI
        on a radiogram-ICS213, and the choices the form offers."""
        from ..mail.compose import radiogram_defaults
        from ..mail.nts import PRECEDENCES, arl_texts, date_filed

        number, place = radiogram_defaults(self.store)
        return {
            "number": number, "place": place,
            "origin": str(self.config.mycall or "").split("-")[0].upper(),
            "precedence": "R", "handling": "HXI" if ics213 else "",
            "date": date_filed(datetime.now(timezone.utc)),
            "precedences": [list(p) for p in PRECEDENCES],
            "arl": [{"number": t.number, "groups": t.groups, "text": t.text}
                    for t in arl_texts()],
        }

    def radiogram_check(self, fields: dict, ics213: bool = False) -> dict:
        """What the form shows as it is filled: the check, the BBS routing
        and title, the ARL texts used, the text as it will go (`text`, a
        final X dropped) and as it converts while typed (`live`, the
        terminal form's as-you-type conversion, ending in a space),
        warnings, and what stops it being saved (`problems`)."""
        from ..mail.nts import arl_used, encode_text

        gram = radiogram_from(fields, ics213)
        to, at = gram.routing()
        live = encode_text(gram.text, final=False)
        return {
            "live": f"{live} " if live else "",
            "check": gram.check,
            "route": f"ST {to or '<zip>'} @ {at if len(at) == 5 else 'NTS<state>'}",
            "subject": gram.subject(),
            "text": encode_text(gram.text),
            "arl_used": [f"{t.groups} = {t.text}" for t in arl_used(gram.encoded_text)],
            "warnings": gram.warnings(),
            "problems": radiogram_problems(gram),
        }

    def write_radiogram(self, fields: dict, ics213: bool = False) -> tuple[list[str], str]:
        """Check a radiogram and file it in the BBS Outbox as `ST <zip> @
        NTS<state>`: (problems, folder). Nothing transmits."""
        from ..mail.compose import radiogram_message

        gram = radiogram_from(fields, ics213)
        problems = radiogram_problems(gram)
        if problems:
            return problems, ""
        return [], self.file_outbox(radiogram_message(gram, str(self.config.mycall or "")))

    def _request_receipts(self, message) -> None:
        """Mark a private BBS message the operator wrote as asking for a
        Delivery and/or Read Receipt, as Settings > Mail says; the flags
        are put on the first line when it is sent (`mail/collect.py`).
        Not a form, a reply by number, or a receipt itself."""
        from ..mail import receipts

        cfg = self.config
        if message.extra.get("Send-Type") != "P" or message.extra.get("Form") \
                or message.extra.get(receipts.HEADER_RECEIPT):
            return
        if cfg.receipt_request_delivery:
            message.extra[receipts.HEADER_DR] = "Y"
        if cfg.receipt_request_read:
            message.extra[receipts.HEADER_RR] = "Y"

    def _queue_receipt(self, original, ref: str, kind: str) -> bool:
        """File the Delivery (`kind` "DR") or Read ("RR") Receipt for
        `original` in the BBS Outbox, and note on the original that it was
        answered so it never is again. False when there is no one to answer."""
        from ..mail import numbering, receipts
        from ..mail.compose import outbox_message

        sender = original.sender.strip().upper()
        mycall = str(self.config.mycall or "")
        if not sender or not re.fullmatch(r"[A-Z0-9]{3,}(-\d{1,2})?", sender) or not mycall:
            return False
        now = datetime.now()
        if kind == "DR":
            prefix = numbering.clean_prefix(self.config.message_prefix, mycall)
            number = original.extra.get("Bbs-Number", "") or original.message_id.replace("!", "")
            title, body = receipts.delivery_receipt(
                local_id=f"{prefix}-{number or 'x'}P", to=original.to, subject=original.subject,
                when=now)
        else:
            title, body = receipts.read_receipt(to=original.to, subject=original.subject, when=now)
        message = outbox_message(sender=mycall, to=sender, at="", title=title, body=body)
        message.extra[receipts.HEADER_RECEIPT] = "delivered" if kind == "DR" else "read"
        self.file_outbox(message)
        answered = set(original.extra.get(receipts.HEADER_ANSWERED, "").split()) | {kind}
        original.extra[receipts.HEADER_ANSWERED] = " ".join(sorted(answered))
        self.store.update(ref, original)
        return True

    def answer_receipts(self, refs: list[str]) -> int:
        """After a Send/Receive: queue a Delivery Receipt for each newly
        downloaded private message that asked for one (Settings > Mail >
        Answer delivery requests). Waits in the Outbox; nothing transmits
        here (`mail/receipts.py`). Returns how many were queued."""
        from ..mail import receipts

        if not self.config.receipt_answer_delivery:
            return 0
        queued = 0
        for ref in refs:
            try:
                original = self.store.read(ref)
            except (OSError, ValueError):
                continue
            if original.extra.get(receipts.HEADER_DR) and not original.extra.get(
                    receipts.HEADER_RECEIPT) and "DR" not in original.extra.get(
                    receipts.HEADER_ANSWERED, "").split():
                queued += self._queue_receipt(original, ref, "DR")
        if queued:
            self._notice(f"{queued} delivery receipt(s) waiting in the Outbox.")
        return queued

    def opened(self, ref: str) -> None:
        """A message was opened in a front end: mark it read, and when it
        asked for a Read Receipt and Settings > Mail > Answer read requests
        is on, queue one (once). Nothing transmits."""
        from ..mail import receipts

        try:
            message = self.store.read(ref)
        except (OSError, ValueError):
            return
        if not message.is_read:
            self.store.set_read(ref)
            self._publish(MailChanged())
        if (self.config.receipt_answer_read and message.extra.get(receipts.HEADER_RR)
                and not message.extra.get(receipts.HEADER_RECEIPT)
                and "RR" not in message.extra.get(receipts.HEADER_ANSWERED, "").split()
                and ref.split("/")[:2] == ["Mail", "BBS"] and "/Inbox/" in ref):
            message = self.store.read(ref)
            if self._queue_receipt(message, ref, "RR"):
                self._notice("A read receipt is waiting in the Outbox.")

    def _number(self, message) -> None:
        """Title a BBS message the operator wrote as `ABC-12P: title` when
        Settings > Mail > Number my BBS messages is on (`mail/numbering.py`):
        the one place every front end files from."""
        from ..config import state_path
        from ..mail import numbering

        if not self.config.message_numbering or not numbering.applies(
                message.extra, message.subject):
            return
        prefix = numbering.clean_prefix(self.config.message_prefix, str(self.config.mycall or ""))
        if not prefix:
            return
        number = numbering.Counter(state_path() / "numbering.json").take()
        message.subject = numbering.numbered_title(
            prefix, number, message.extra["Send-Type"], message.subject)

    def file_outbox(self, message, *, raw: bytes | None = None, raw_suffix: str = ".xml") -> str:
        """File a written message in Mail/BBS/Outbox, or Mail/Winlink/Outbox
        for a Winlink one; returns the folder. One place for every front end."""
        from ..mail.compose import BBS_OUTBOX, SEND_WINLINK
        from ..mail.winlink_collect import WINLINK_OUTBOX

        folder = WINLINK_OUTBOX if message.extra.get("Send-Type") == SEND_WINLINK else BBS_OUTBOX
        self._number(message)
        self._request_receipts(message)
        self.store.add(folder, message, raw=raw, raw_suffix=raw_suffix)
        self._publish(MailChanged())
        return folder

    def delete(self, ref: str) -> str:
        """Move a message, or a file under Files, to the Deleted folder
        beside it; returns its new ref, which `restore` puts back (Undo)."""
        new_ref = (self.store.delete_file(ref) if ref.split("/", 1)[0] == FILES
                   else self.store.delete(ref))
        self._publish(MailChanged())
        return new_ref

    def restore(self, ref: str) -> str:
        """Put a deleted message or file back where it was deleted from."""
        new_ref = (self.store.restore_file(ref) if ref.split("/", 1)[0] == FILES
                   else self.store.restore(ref))
        self._publish(MailChanged())
        return new_ref

    def bulletin_categories(self) -> BulletinChoice | None:
        """What S on Bulletins (and the phone's Categories) offers: the
        categories the Home BBS listed last, and which are collected.
        None before any collection has asked the BBS: nothing is asked of
        the air to fill this in."""
        bbs = self.bulletin_bbs()
        subs = self.subscriptions.for_bbs(bbs) if bbs else None
        if subs is None or not subs.seen:
            return None
        return BulletinChoice(bbs, dict(sorted(subs.seen.items())), sorted(subs.chosen), subs.all)

    def choose_bulletin_categories(self, picked: list[str], *, all_: bool) -> None:
        """Replace the choice of categories collected, offline."""
        bbs = self.bulletin_bbs()
        subs = self.subscriptions.for_bbs(bbs) if bbs else None
        if subs is None or not subs.seen:
            self._notice(NO_CATEGORIES)
            return
        subs.choose(list(subs.seen), list(picked), all_=all_)
        self.subscriptions.save()
        self._notice("Collecting " + ("every category." if subs.all
                                      else (", ".join(subs.chosen) or "no categories") + "."))

    def bulletin_bbs(self) -> str:
        """The Home BBS's callsign as its choices are kept, or ""."""
        home = self.config.home_bbs
        if home.call:
            return home.call
        route = home.route or home.internet
        return str(parse_path(route).destination.callsign) if route else ""

    async def choose_categories(self, offer: list[str], counts: dict[str, int], first: bool):
        """The collector's question (`collect.Choose`), asked mid-run."""
        return await self._ask(ChooseCategories(
            self.bulletin_bbs() or "the BBS", {c: counts.get(c, 0) for c in offer},
            new_only=not first))

    async def how_many_bulletins(self, count: int, categories: list[str], *,
                                 radio: bool = False) -> int | None:
        """The collector's question (`collect.HowMany`): more than
        `bulletins.ASK_OVER` new, so all, the newest, or none."""
        from ..mail.bulletins import ASK_OVER

        return await self._ask(HowManyBulletins(
            self.bulletin_bbs() or "the BBS", count, tuple(categories), ASK_OVER, radio=radio))

    async def pick_files(self, files):
        """The collector's question (`collect.PickFiles`), asked mid-run."""
        folder = self.downloads_dir()
        have = {p.name: p.stat().st_size for p in folder.iterdir() if p.is_file()}
        return await self._ask(PickFiles(self.bulletin_bbs() or "the BBS", tuple(files), have))

    # ------------------------------------------------------------------
    # Winlink by radio
    # ------------------------------------------------------------------
    async def _winlink_prepare(self):
        """Everything the Winlink run needs before dialing, asking for what
        is missing: (entry, options), or None if cancelled."""
        from ..mail.winlink_collect import WinlinkOptions

        winlink = self.config.winlink
        entry = await self._winlink_gateway() if await self._winlink_account() else None
        if entry is None:
            return None
        login = await self.winlink_login()
        if login is None:
            return None
        account, password = login
        return entry, WinlinkOptions(
            account,
            password=password,
            target=str(parse_path(entry.target).destination),
            locator=winlink.locator or self.config.aprs.grid_square,
        )

    async def _winlink_account(self) -> str:
        """The Winlink account, asking for the callsign it defaults to when
        neither is set; "" if the operator cancelled."""
        if not winlink_account(self.config):
            await self.core.ask_callsign()
        return winlink_account(self.config)

    async def winlink_login(self) -> tuple[str, str] | None:
        """(account, password), asking for the password if no saved login
        holds it; None if cancelled."""
        winlink = self.config.winlink
        account = await self._winlink_account()
        if not account:
            return None
        # Have the password before dialing, so a missing one never costs a
        # connect. UNVERIFIED: that every gateway challenges (Winlink
        # accounts have passwords; wl2k-go answers ;PQ whenever it comes).
        login = await self._ask_login(
            winlink.credential, "Winlink", f"Winlink password for {account}", "")
        if login is None:
            return None
        if winlink.credential != login[0]:
            winlink.credential = login[0]
            self._config_saved()
        return account, login[1]

    async def _winlink_run(self, entry, options) -> None:
        """Winlink over the route Settings > Mail names:
        `mail/winlink_collect.py` drives the B2F exchange.

        While it runs, the session shows the protocol lines as text, not
        the link's raw bytes: a message travels compressed, and its binary
        would only fill a terminal with noise (the same suppression a file
        transfer uses). What arrived before the exchange started (the
        node's banner, the hop chain) was shown as usual."""
        from ..mail.winlink_collect import WinlinkCollector

        def build(link, key: str):
            return WinlinkCollector(
                link,
                self.store,
                options,
                note=lambda text: self._note(key, text),
                sent=lambda text: self._sent(key, text),
                received=lambda text: self._received(key, text),
                gate_open=self._gate_open,
                progress=self.core.set_activity,
            )

        dialed = await self._dial(entry, build, "send and receive Winlink mail")
        if dialed is None:
            return
        collector, key = dialed
        active = self.core.transfers.active
        active.add(key)
        try:
            result = await collector.run()
        finally:
            active.discard(key)
        self.winlink_report(result)
        await self.core.connector.disconnect(key)
        await self._winlink_password_refused(result)

    async def _winlink_password_refused(self, result) -> None:
        """The gateway refused the password: ask for it again here, rather
        than say where to set it (operator, 2026-09-27: go there, don't
        point). Saved for the next run; nothing is dialed now, so a retry
        costs airtime only when the operator presses G again."""
        if "password" not in (result.stopped or "").lower():
            return
        text = await self._ask(LoginAsk(
            "Winlink password refused",
            f"The gateway said: {result.stopped}. Type the password for "
            f"{winlink_account(self.config)} again.",
            "Winlink", go_label="Save"))
        if not text or text == SETUP_SKIP:
            return
        where = set_credential(self.config, "Winlink", text)
        self.config.winlink.credential = "Winlink"
        self._config_saved()
        self._notice("Saved in " + ("the system keyring" if where == "keyring" else "config.toml")
                     + ". Send/Receive again to use it.")

    def winlink_report(self, result) -> None:
        """The outcome notice of a Winlink run, over radio or the Internet."""
        if self.cancel_requested and result.stopped:
            result.stopped = "cancelled"
        sent = f"{len(result.sent)} sent, " if result.sent else ""
        if "unknown client type" in result.stopped.lower():
            self._notice(UNKNOWN_CLIENT, Severity.WARNING, timeout=15)
        elif result.stopped:
            self._notice(f"Winlink stopped: {result.stopped}. {sent}{len(result.filed)} received.",
                         Severity.WARNING)
        elif result.filed:
            self._notice(f"{sent}{len(result.filed)} new Winlink message(s).")
        elif result.sent:
            self._notice(f"{len(result.sent)} sent. No new Winlink mail.")
        else:
            self._notice("No new Winlink mail.")
        self._publish(MailChanged())

    # ------------------------------------------------------------------
    # Over the Internet (I)
    # ------------------------------------------------------------------
    async def _internet_run(self, transport, peer: str, what: str, build,
                            label: str = "Send/Receive"):
        """Connect a session `transport` and run the collector
        `build(link, note, sent, received)` makes over it, with a
        transcript. Returns its result, or None having said why, led by
        `label`."""
        self._notice(f"Connecting to {what} over the Internet...")
        self.core.set_activity(f"Connecting to {what}")
        link = transcript = None
        try:
            await transport.open()
            try:
                session = await self.core.connector.session_connect(transport)
            except TransportError as exc:
                self._notice(f"{label} by Internet: {exc}", Severity.ERROR)
                return None
            link = SessionLinkAdapter(session)
            mycall = str(self.config.mycall or "").upper()
            transcript = SessionLog(self.core.sessions.transcript_directory(), mycall, peer)
            if not transcript.open():
                transcript = None
            record = transcript
            masked = self.core.connector.masked

            def note(text: str) -> None:
                if record is not None:
                    record.note(f"*** Mail: {text}")

            collector = build(
                link, note,
                lambda text: record.sent(masked(text)) if record is not None else None,
                lambda text: record.received(text) if record is not None else None,
            )
            result = await collector.run()
            if not result.stopped and hasattr(collector, "sign_off"):
                # Before the outcome notice here, but over the Internet
                # the BBS hangs up at once (`sign_off_wait`).
                await collector.sign_off()
            return result
        finally:
            if link is not None:
                with contextlib.suppress(Exception):
                    await link.disconnect()
            with contextlib.suppress(Exception):
                await transport.close()
            if transcript is not None:
                transcript.close()
            self.core.set_activity("")

    async def _winlink_cms_run(self, account: str, password: str) -> None:
        """Winlink through the CMS by Telnet (`winlink_collect.CMS_*`,
        from wl2k-go): its login, then the same exchange as over radio."""
        from ..mail.winlink_collect import (
            CMS_PORT, CMS_TARGET, WinlinkCollector, WinlinkOptions, cms_host,
        )
        from ..transport import build_transport

        options = WinlinkOptions(
            account, password=password, target=CMS_TARGET,
            locator=self.config.winlink.locator or self.config.aprs.grid_square,
            telnet_login=True,
        )

        def build(link, note, sent, received):
            return WinlinkCollector(link, self.store, options, note=note, sent=sent,
                                    received=received, progress=self.core.set_activity,
                                    early_lines_shown=False)

        server = self.config.winlink.server
        transport = build_transport({"kind": "telnet", "host": cms_host(server), "port": CMS_PORT})
        what = "Winlink's test server" if server == "test" else "the Winlink CMS"
        result = await self._internet_run(transport, CMS_TARGET, what, build)
        if result is not None:
            self.winlink_report(result)
            await self._winlink_password_refused(result)

    def internet_contacts(self) -> list:
        """The Address Book's Telnet and SSH contacts: what I reaches the
        Home BBS through."""
        return [e for e in self.core.addressbook.entries if e.is_internet]

    async def _bbs_internet_prepare(self):
        """Everything the Home BBS needs over the Internet, asking for what
        is missing: (connection, options), or None if cancelled."""
        from ..mail.collect import CollectOptions

        home = self.config.home_bbs
        contacts = self.internet_contacts()
        wanted = home.internet.strip().upper()
        entry = next((e for e in contacts if e.target.upper() == wanted), None)
        # A name that is no saved login may be a password typed in its
        # place: never shown, replaced by a login made here.
        name = (home.internet_credential
                if credential_store(self.config, home.internet_credential) else "")
        password = find_credential(self.config, name) if name else ""
        if not password and entry is not None and entry.credential:
            # The contact's own Node login is the node's sign-in already;
            # asking for it again here was a second copy (operator,
            # 2026-10-02).
            node_password = find_credential(self.config, entry.credential)
            if node_password:
                name, password = entry.credential, node_password
        user = (credential_username(self.config, name) or home.internet_user
                or str(self.config.mycall or "").split("-")[0].upper())
        if entry is None or not password:
            # One question for all of it: the contact, the username and the
            # password, saved as one login (operator, 2026-09-28).
            note, skip = self._all_inboxes_ask()
            answer = self._setup_answer(await self._ask(InternetLoginAsk(
                tuple(e.target for e in contacts), entry.target if entry else "",
                missing=home.internet.strip() if entry is None else "",
                username=user, saved=bool(password), where=login_where(),
                all_note=note, skip=skip)), "")
            if not isinstance(answer, InternetLogin):
                return None
            entry = self.core.addressbook.find(answer.target)
            if entry is None or not entry.is_internet:
                return None
            name = name or f"{entry.target} login"
            password = answer.password or password
            user = answer.username
            where = set_credential(self.config, name, password, username=user)
            home.internet, home.internet_credential, home.internet_user = entry.target, name, ""
            self._config_saved()
            self._notice(
                f"Saved the login \"{name}\" for {entry.target}, its password in "
                + ("the system keyring." if where == "keyring"
                   else "config.toml (no system keyring here)."),
            )
        return entry, CollectOptions(
            bbs_call=home.call,
            software=home.software,
            ready_text=home.ready_text,
            telnet_user=user,
            telnet_password=password,
            after_login=home.internet_command.strip(),
            sign_off=True,
            # A Telnet session hangs up at once; no radio path to wait on.
            sign_off_wait=10.0,
        )

    async def _bbs_internet_run(self, entry, options) -> None:
        """The Home BBS over its Telnet or SSH contact, built the one way
        every connection is (`build_transport`)."""
        from ..mail.collect import BbsCollector
        from ..transport import build_transport

        label = "Get bulletins" if options.bulletins else "Send/Receive"
        try:
            transport = build_transport(entry.transport_config(
                lambda name: find_credential(self.config, name),
                lambda name: credential_username(self.config, name)))
        except (TransportError, TypeError, ValueError) as exc:
            self._notice(f"{label} by Internet: {entry.target}: {exc}", Severity.ERROR)
            return

        def build(link, note, sent, received):
            return BbsCollector(link, self.store, options, note=note, sent=sent,
                                progress=self.core.set_activity,
                                subscriptions=self.subscriptions,
                                choose=self.choose_categories,
                                how_many=self.how_many_bulletins)

        result = await self._internet_run(transport, entry.target, entry.target, build, label)
        if result is not None:
            self.bbs_report(result, bulletins=options.bulletins)


#: The radiogram fields a front end fills (`nts.Radiogram`'s, less the
#: filing date, which is now, and the kind, which is `ics213`).
RADIOGRAM_FIELDS = (
    "number", "precedence", "test", "handling", "origin", "place", "time_filed",
    "to_name", "to_call", "to_street", "to_city", "to_state", "to_zip", "to_phone",
    "to_email", "to_op_note", "text", "signature", "sig_op_note", "ics_subject",
)


def radiogram_from(fields: dict, ics213: bool = False):
    """An `nts.Radiogram` from a front end's fields; unknown keys are
    ignored, and only text (or the `test` flag) is taken from them."""
    from ..mail.nts import Radiogram

    values = {}
    for name in RADIOGRAM_FIELDS:
        if name in fields:
            value = fields[name]
            values[name] = bool(value) if name == "test" else str(value or "")
    values.setdefault("precedence", "R")
    return Radiogram(**values, ics213=bool(ics213))


def radiogram_problems(gram) -> list[str]:
    """What stops a radiogram being saved: its own rules (`nts.py`), and a
    line that would end the message early on the BBS. Both forms' check."""
    from ..mail.compose import ends_text_early

    problems = gram.problems()
    if any(ends_text_early(line) for line in gram.body().splitlines()):
        problems.append("A line would end the message on the BBS (/EX); reword it.")
    return problems
