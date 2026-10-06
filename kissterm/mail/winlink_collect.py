"""Winlink Send/Receive over a link that is already up.

ROADMAP P2 "Winlink". The connect is `KissTermApp`'s normal flow over the
Address Book route Settings > Mail names -- a direct RMS SSID, a NET/ROM
alias, a node plus its `RMS` command, or a hop chain to a gateway whose
Internet is up -- and this runs once the link exists, like `collect.py`
for a BBS. `kissterm/winlink/b2f.py` is the protocol; this is the glue:

- **Outbox**: every message in Mail/Winlink/Outbox is offered. One without
  a MID gets one first, saved back, so a retry after a dropped link offers
  the same MID and the CMS can refuse a duplicate. A form saved with
  its Winlink XML (`<stem>.xml`) sends it as the attachment Winlink
  clients open in the form's viewer (`form_xml.py`).
- **Sent**: a message moves to Mail/Winlink/Sent only when the gateway has
  taken it (`b2f.Sent`), or said it already had it.
- **Inbox**: each message that arrives whole goes to Mail/Winlink/Inbox,
  with its B2 bytes beside it as `.b2f` (attachments included), and one
  already in the store is answered "have it" so it is not sent again. Its
  attachments are saved into Files/Attachments (`mail/attachments.py`),
  and its Attachments line says where.

**Visible.** Every protocol line, both ways, goes to the session log
(`sent` for ours, `received` for the gateway's), with a message's
compressed bytes summarised rather than dumped; progress goes to `note`
and `progress` as for a BBS (DESIGN.md section 6).

**Over the Internet** (`telnet_login`): the Winlink CMS's Telnet port
asks `Callsign :` and `Password :` before the B2F exchange; the answers
are the account and the fixed Telnet password every client sends,
`CMSTelnet` (wl2k-go `transport/telnet/dial.go`, which also gives the
host, port and the `wl2k` target). The account's own password is never
that: it answers the `;PQ:` challenge afterwards, as over radio.
# UNVERIFIED: wl2k-go's constants, not yet a session of our own.

**It stops rather than guesses**, with the reason in the operator's
words: the gateway's own error line (a wrong password), a damaged
message, silence past `idle_timeout`, a dropped link, or the transmit
gate closing. Nothing half-received is filed.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..winlink import b2f
from ..winlink.message import SOURCE, B2Error, B2Message, build, generate_mid, to_mail
from .message import Message
from . import form_xml
from .attachments import safe_filename, save_attachment
from .store import FILES, INBOX, MAIL, OUTBOX, SENT, MessageStore

#: G on a folder under this runs Winlink, not the Home BBS.
WINLINK_FOLDER = f"{MAIL}/Winlink"
WINLINK_INBOX = f"{WINLINK_FOLDER}/{INBOX}"
WINLINK_OUTBOX = f"{WINLINK_FOLDER}/{OUTBOX}"
WINLINK_SENT = f"{WINLINK_FOLDER}/{SENT}"
RAW_SUFFIX = ".b2f"
#: Where a received message's attachments are saved.
ATTACHMENTS = f"{FILES}/Attachments"
#: As for a BBS: a slow packet path has long gaps (`collect.py`).
DEFAULT_IDLE_TIMEOUT = 300.0

_ADDRESS_SPLIT = re.compile(r"[,;\s]+")

#: The Winlink CMS's Telnet service (wl2k-go `CMSAddress`, `CMSTargetCall`).
CMS_HOST = "server.winlink.org"
#: Winlink's test CMS, named by the production CMS when it refused kissterm:
#: "Unknown client types are not allowed on production servers -- use
#: cms-z.winlink.org" (operator's session, 2026-09-28).
#: # UNVERIFIED: its port (taken to be production's) and where mail sent
#: through it goes.
CMS_TEST_HOST = "cms-z.winlink.org"
CMS_PORT = 8772


def cms_host(server: str) -> str:
    """The CMS for `WinlinkConfig.server`."""
    return CMS_TEST_HOST if server == "test" else CMS_HOST
CMS_TARGET = "WL2K"
#: The Telnet-layer password every client sends (wl2k-go `CMSPassword`).
CMS_TELNET_PASSWORD = "CMSTelnet"


@dataclass
class WinlinkOptions:
    #: The Winlink account (callsign, no SSID).
    account: str
    #: The account's password, for a `;PQ:` challenge; "" if none is set.
    password: str = field(default="", repr=False)
    #: Who we say we are talking to (`; TARGET DE ACCOUNT`).
    target: str = "WL2K"
    #: Maidenhead locator for the handshake; may be "".
    locator: str = ""
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT
    #: Answer the CMS Telnet port's `Callsign :` / `Password :` first.
    telnet_login: bool = False


@dataclass
class WinlinkResult:
    #: Refs in Mail/Winlink/Inbox of the messages received.
    filed: list[str] = field(default_factory=list)
    #: Refs in Mail/Winlink/Sent of the messages the gateway took.
    sent: list[str] = field(default_factory=list)
    deferred: int = 0
    skipped: list[str] = field(default_factory=list)
    stopped: str = ""


def addresses(text: str) -> list[str]:
    """`W1AW, foo@bar.com` -> ["W1AW", "foo@bar.com"]."""
    return [a for a in _ADDRESS_SPLIT.split(text.strip()) if a]


def outbound_message(message: Message, account: str,
                     files: list[tuple[str, bytes]] | None = None) -> B2Message:
    """An Outbox message as B2. Raises `B2Error` if it cannot be sent."""
    return build(
        sender=account,
        to=addresses(message.to),
        cc=addresses(message.extra.get("Cc", "")),
        subject=message.subject,
        body=message.body,
        files=files,
        mid=message.message_id,
        date=message.date,
    )


def form_attachments(raw_files: list[Path]) -> list[tuple[str, bytes]]:
    """A form message's XML (`<stem>.xml`, saved with it by the compose
    flow), named as Winlink names it (`form_xml.attachment_name`). A file
    that is not a form's XML is left behind, never sent."""
    for path in raw_files:
        if path.suffix.lower() != ".xml":
            continue
        try:
            data = path.read_bytes()
            found = form_xml.parse(data)
        except (OSError, ValueError):
            continue
        if found.display_form:
            return [(form_xml.attachment_name(found.display_form), data)]
    return []


class WinlinkCollector:
    """One Winlink exchange. Subscribes to the link on construction (before
    anything awaits, as `BbsCollector` does); `run()` closes it."""

    def __init__(
        self,
        link,
        store: MessageStore,
        options: WinlinkOptions,
        *,
        note: Callable[[str], None],
        sent: Callable[[str], None],
        received: Callable[[str], None],
        gate_open: Callable[[], bool] = lambda: True,
        progress: Callable[[str], None] = lambda _phase: None,
        early_lines_shown: bool = True,
    ) -> None:
        self.link = link
        #: Whether lines heard before `run()` were already shown (a radio
        #: session's Terminal tab shows them); if not, they are logged too.
        self._early_lines_shown = early_lines_shown
        self._login_buffer = ""
        self._login_out: list[str] = []
        self._logged_in = not options.telnet_login
        self.store = store
        self.options = options
        self._note = note
        self._sent = sent
        self._received = received
        self._gate_open = gate_open
        self._progress = progress
        self._arrived = asyncio.Event()
        self._refs: dict[str, str] = {}
        self._skipped: list[str] = []
        outbound = self._outbox()
        self._total_out = len(outbound)
        self.client = b2f.Client(
            options.account,
            options.target,
            locator=options.locator,
            password=options.password or None,
            outbound=outbound,
            have=lambda mid: bool(store.find(mid, SOURCE)),
        )
        link.on_data.append(self._on_data)
        # A link that goes down wakes the wait at once, rather than after
        # the idle timeout (300 s): a disconnect, or a phone's cancel
        # (`core/mail.py`), ends the run as soon as it happens.
        self._on_state_list = getattr(link, "on_state", None)
        if self._on_state_list is not None:
            self._on_state_list.append(self._on_state)

    def _on_state(self, _state) -> None:
        self._arrived.set()

    def close(self) -> None:
        with contextlib.suppress(ValueError):
            self.link.on_data.remove(self._on_data)
        if self._on_state_list is not None:
            with contextlib.suppress(ValueError):
                self._on_state_list.remove(self._on_state)

    def _outbox(self) -> list[B2Message]:
        messages: list[B2Message] = []
        # `list` is newest first; offer them in the order they were written.
        for summary in reversed(self.store.list(WINLINK_OUTBOX)):
            try:
                message = self.store.read(summary.ref)
            except (OSError, ValueError):
                continue
            if not message.message_id:
                message.message_id = generate_mid(self.options.account)
                self.store.update(summary.ref, message)
            try:
                messages.append(outbound_message(
                    message, self.options.account,
                    form_attachments(self.store.raw_files(summary.ref))))
            except B2Error as exc:
                self._skipped.append(f"{message.subject or '(no subject)'}: {exc}")
                continue
            self._refs[message.message_id] = summary.ref
        return messages

    def _on_data(self, data: bytes) -> None:
        if not self._logged_in:
            self._telnet_login(data)
        self.client.feed(data)
        self._arrived.set()

    def _telnet_login(self, data: bytes) -> None:
        """Queue the answers to the CMS Telnet prompts, as wl2k-go does:
        each complete line, lower-cased, starting `callsign` or `password`."""
        self._login_buffer += data.decode("latin-1")
        *lines, self._login_buffer = re.split(r"[\r\n]", self._login_buffer)
        for line in lines:
            line = line.strip().lower()
            if line.startswith("callsign"):
                self._login_out.append(self.options.account)
            elif line.startswith("password"):
                self._login_out.append(CMS_TELNET_PASSWORD)
                self._logged_in = True
                break

    async def _flush(self) -> None:
        while self._login_out:
            line = self._login_out.pop(0)
            if not self._gate_open():
                raise _Stop("transmit is off")
            await self.link.send(line.encode("latin-1") + b"\r")
            self._sent(line)
        out = self.client.take_output()
        if not out:
            return
        if not self.link.connected:
            self.client.connection_lost()
            return
        if not self._gate_open():
            raise _Stop("transmit is off")
        await self.link.send(out)

    def _handle(self, event, result: WinlinkResult) -> None:
        if isinstance(event, b2f.Line):
            (self._sent if event.direction == ">" else self._received)(event.text)
        elif isinstance(event, b2f.Received):
            message = to_mail(event.message)
            saved = self._save_attachments(event.message)
            if saved:
                message.extra["Attachments"] = ", ".join(saved)
            result.filed.append(self.store.add(WINLINK_INBOX, message, raw=event.raw,
                                               raw_suffix=RAW_SUFFIX))
            self._progress(f"Received {len(result.filed)}")
            self._note(f"Received {message.message_id} from {message.sender}: {message.subject}")
        elif isinstance(event, b2f.Sent):
            ref = self._refs.pop(event.mid, "")
            if ref:
                result.sent.append(self.store.move(ref, WINLINK_SENT))
            how = "the gateway already had it" if event.already_had else "sent"
            self._progress(f"Sent {len(result.sent)} of {self._total_out}")
            self._note(f"{event.mid}: {how}.")
        elif isinstance(event, b2f.Deferred):
            result.deferred += 1
            self._note(f"{event.mid}: the gateway asked for it later; it stays in the Outbox.")
        elif isinstance(event, b2f.Pending):
            self._note(f"Waiting for you on Winlink: {event.mid} from {event.sender}, "
                       f"{event.size} bytes: {event.subject}")

    def _save_attachments(self, message: B2Message) -> list[str]:
        """Each attachment into Files/Attachments (`mail/attachments.py`),
        as "where it went (size)" for the message's Attachments line. A
        file that cannot be written is said and skipped: the exchange goes
        on (the raw `.b2f` beside the message still holds it)."""
        saved = []
        directory = self.store.root / ATTACHMENTS
        for name, data in message.files:
            try:
                path = save_attachment(directory, name, data)
            except OSError as exc:
                self._note(f"Could not save the attachment {safe_filename(name)!r}: {exc}")
                saved.append(f"{safe_filename(name)} ({len(data)} bytes, not saved)")
                continue
            where = path.relative_to(self.store.root).as_posix()
            self._note(f"Saved the attachment {path.name} ({len(data)} bytes) in {where}.")
            saved.append(f"{where} ({len(data)} bytes)")
        return saved

    async def run(self) -> WinlinkResult:
        result = WinlinkResult(skipped=list(self._skipped))
        # Lines that arrived before the run (the node's banner, the hop
        # chain) were shown as ordinary session text; only the rest are
        # passed on, so none is logged twice.
        for event in self.client.take_events():
            if not (self._early_lines_shown and isinstance(event, b2f.Line)):
                self._handle(event, result)
        for reason in self._skipped:
            self._note(f"Not sent: {reason}")
        self._note("Waiting for the Winlink gateway...")
        self._progress("Waiting for Winlink")
        try:
            while True:
                self._arrived.clear()
                await self._flush()
                for event in self.client.take_events():
                    self._handle(event, result)
                if self.client.done:
                    break
                if not self.link.connected:
                    self.client.connection_lost()
                    continue
                try:
                    await asyncio.wait_for(self._arrived.wait(), self.options.idle_timeout)
                except asyncio.TimeoutError:
                    raise _Stop(f"nothing from the gateway for {self.options.idle_timeout:.0f} s") from None
            if self.client.error:
                result.stopped = self.client.error
        except _Stop as stop:
            result.stopped = str(stop)
        finally:
            self.close()
        if result.stopped:
            self._note(f"Stopped: {result.stopped}.")
        else:
            self._note(f"Done: {len(result.sent)} sent, {len(result.filed)} received.")
        return result


class _Stop(Exception):
    pass
