"""Collecting mail from a BBS over a link that is already up.

ROADMAP P2 "BBS send/receive", the receive half. The connect (reminder,
transmit gate, hop chain, the route's own login) is `KissTermApp`'s normal
flow; this runs once the link exists and drives the BBS the way an operator
would at the keyboard:

1. Wait for the BBS to be ready: its prompt (`de WS1EC#>`), or the
   operator's own "ready" text for a BBS whose prompt is not recognised.
   If a login prompt is configured and seen first, send the credential.
2. Check what answered. BPQMail is the only application whose replies are
   captured (`bpqmail.py`), so anything else stops here, by name.
3. `LM`, then `R <n>` for each listed message not already in the store,
   oldest first. A page prompt is answered with Enter.
4. File each complete read in Mail/BBS/Inbox (a bulletin under
   Bulletins/<category>), with the raw reply beside it as `.bbs`.

**It stops rather than guesses.** A reply it does not recognise, a read
without its end marker, silence past `idle_timeout`, a dropped link or a
closed transmit gate each end the run with a note saying which. Nothing
half-read is filed (`bpqmail.py`'s rule).

**Airtime.** Only messages not already stored are read: the listing's
number is checked against the store before the `R` goes out
(`MessageStore.has_bbs_number`), and the BID after it (`find`), so a
message reached by another route or deleted in kissterm is never fetched
again. Messages stay on the BBS: this never sends `K` (decided 2026-09-22).

**Visible.** Every line sent goes through `sent`, which the app echoes to
the terminal pane and the transcript; progress goes through `note` (a
sentence for the session log) and `progress` (a few words for the status
bar, DESIGN.md section 6).

Pure asyncio over a link-shaped object (`send`, `on_data`, `connected`),
so the tests drive it with a scripted BBS built from the real captures.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..ansi import decode_text
from . import bpqmail
from .message import KIND_BULLETIN
from .store import BULLETINS, INBOX, MAIL, MessageStore

#: Where BBS private mail is filed.
BBS_INBOX = f"{MAIL}/BBS/{INBOX}"
#: Suffix of the raw reply kept beside each filed message.
RAW_SUFFIX = ".bbs"
#: Seconds of silence from the BBS before giving up. Long on purpose: on the
#: weak WS1EC-2 path a nine-line listing took almost four minutes, with
#: gaps of two between lines (2026-09-24).
DEFAULT_IDLE_TIMEOUT = 300.0

SOFTWARE_AUTO = "auto"
SOFTWARE_BPQMAIL = "bpqmail"


class CollectStopped(Exception):
    """The run ended early; the message says why, in the operator's words."""


@dataclass
class CollectOptions:
    #: The BBS's callsign for `Source:`; "" takes it from the prompt.
    bbs_call: str = ""
    #: "auto" identifies the BBS from what it sends; "bpqmail" skips that.
    software: str = SOFTWARE_AUTO
    #: Text meaning "ready for the first command"; "" means the BBS prompt.
    ready_text: str = ""
    #: Text after which `login_text` is sent; "" sends no login.
    login_prompt: str = ""
    login_text: str = ""
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT


@dataclass
class CollectResult:
    listed: int = 0
    filed: list[str] = field(default_factory=list)
    already_had: int = 0
    not_found: list[int] = field(default_factory=list)
    stopped: str = ""


class BbsCollector:
    """One collection run. Subscribes to the link on construction.

    Built synchronously the moment the link is up, before anything awaits,
    so the BBS's first bytes are not fanned out before it listens (the same
    reason `_HopConfirmation` subscribes in `__init__`). `close()` must be
    called; `run()` does it.
    """

    def __init__(
        self,
        link,
        store: MessageStore,
        options: CollectOptions,
        *,
        note: Callable[[str], None],
        sent: Callable[[str], None],
        gate_open: Callable[[], bool] = lambda: True,
        progress: Callable[[str], None] = lambda _phase: None,
    ) -> None:
        self.link = link
        self.store = store
        self.options = options
        self._note = note
        self._sent = sent
        self._gate_open = gate_open
        #: A few words for the status bar ("reading 2/3"); `note` has the
        #: full sentence for the session log.
        self._progress = progress
        self._pending = bytearray()
        self._lines: list[str] = []
        self._transcript: list[str] = []
        self._arrived = asyncio.Event()
        link.on_data.append(self._on_data)

    def close(self) -> None:
        with contextlib.suppress(ValueError):
            self.link.on_data.remove(self._on_data)

    # -- input ---------------------------------------------------------------

    def _on_data(self, data: bytes) -> None:
        self._pending.extend(data)
        # Lines end in CR (BPQMail), LF or CRLF. The tail after the last one
        # stays pending: a prompt or page prompt arrives without an ending.
        text = self._pending.decode("latin-1")
        parts = re.split(r"\r\n|\r|\n", text)
        tail = parts.pop()
        self._pending = bytearray(tail.encode("latin-1"))
        for part in parts:
            line = decode_text(part.encode("latin-1"))
            self._lines.append(line)
            self._transcript.append(line)
        self._arrived.set()

    @property
    def _partial(self) -> str:
        return decode_text(bytes(self._pending))

    def _take_lines(self) -> list[str]:
        lines, self._lines = self._lines, []
        return lines

    async def _wait_for_data(self) -> None:
        # The event is cleared by the loops before they look at the input,
        # never here: data that arrived while a loop was sending has already
        # set it, and clearing now would sleep through it.
        if not self.link.connected:
            raise CollectStopped("the link dropped")
        try:
            await asyncio.wait_for(self._arrived.wait(), self.options.idle_timeout)
        except asyncio.TimeoutError:
            raise CollectStopped(
                f"nothing from the BBS for {self.options.idle_timeout:.0f} s"
            ) from None
        if not self.link.connected and not self._lines and not self._pending:
            raise CollectStopped("the link dropped")

    # -- output --------------------------------------------------------------

    async def _send(self, text: str, shown: str | None = None) -> None:
        if not self.link.connected:
            raise CollectStopped("the link dropped")
        if not self._gate_open():
            raise CollectStopped("transmit is off")
        await self.link.send(text.encode("latin-1", "replace") + b"\r")
        self._sent(text if shown is None else shown)

    # -- the conversation ----------------------------------------------------

    async def _until_prompt(self) -> tuple[list[str], str]:
        """Lines up to the BBS prompt, answering page prompts with Enter.

        Returns the reply's lines (prompt excluded) and the prompt's call.
        """
        reply: list[str] = []
        while True:
            self._arrived.clear()
            for line in self._take_lines():
                if (call := bpqmail.prompt_call(line)):
                    return reply, call
                reply.append(line)
            partial = self._partial
            if (call := bpqmail.prompt_call(partial)):
                self._pending.clear()
                return reply, call
            if bpqmail.PAGE_PROMPT_RE.search(partial):
                self._pending.clear()
                await self._send("", shown="(Enter: continue)")
            await self._wait_for_data()

    async def _until_ready(self) -> str:
        """Wait for the BBS to be ready; returns the prompt's call, or ""."""
        ready = self.options.ready_text
        login_sent = not (self.options.login_prompt and self.options.login_text)
        while True:
            self._arrived.clear()
            lines = self._take_lines()
            text = "\n".join([*lines, self._partial])
            if not login_sent and self.options.login_prompt in text:
                login_sent = True
                self._pending.clear()
                for line in [ln for ln in self.options.login_text.splitlines() if ln.strip()]:
                    await self._send(line, shown="(login sent)")
                continue
            if ready:
                if ready in text:
                    self._pending.clear()
                    return ""
            else:
                for candidate in [*lines, self._partial]:
                    if (call := bpqmail.prompt_call(candidate)):
                        self._pending.clear()
                        return call
            await self._wait_for_data()

    def _check_software(self) -> None:
        if self.options.software == SOFTWARE_BPQMAIL:
            return
        from ..nodes.reference import identify_family

        family = identify_family("\n".join(self._transcript))
        if family is None or family.id != SOFTWARE_BPQMAIL:
            what = family.name if family is not None else "a BBS kissterm could not identify"
            raise CollectStopped(
                f"this is {what}; kissterm can only collect from BPQMail so far. "
                "If it is BPQMail, set Software to BPQMail in Settings > Home BBS."
            )

    async def run(self) -> CollectResult:
        result = CollectResult()
        try:
            await self._collect(result)
        except CollectStopped as stop:
            result.stopped = str(stop)
            self._note(f"Stopped: {stop}.")
        finally:
            self.close()
        return result

    async def _collect(self, result: CollectResult) -> None:
        self._note("Waiting for the BBS prompt...")
        self._progress("waiting for the prompt")
        call = await self._until_ready()
        self._check_software()
        bbs_call = (self.options.bbs_call or call).upper()
        if not bbs_call:
            raise CollectStopped(
                "the BBS's callsign is not known; set it in Settings > Home BBS"
            )
        source = f"BBS {bbs_call}"

        self._progress("listing")
        await self._send("LM")
        listing, _ = await self._until_prompt()
        entries = bpqmail.parse_list(listing)
        result.listed = len(entries)
        new = sorted(
            (e for e in entries if not self.store.has_bbs_number(source, e.number)),
            key=lambda e: e.number,
        )
        result.already_had = len(entries) - len(new)
        if not new:
            self._note(f"No new mail ({len(entries)} listed, all already here).")
            return
        self._note(f"{len(new)} new of {len(entries)} listed.")

        for position, entry in enumerate(new, 1):
            self._progress(f"reading {position}/{len(new)}")
            self._note(
                f"Reading {position} of {len(new)}: #{entry.number} from "
                f"{entry.sender}, {entry.title or '(no title)'}"
            )
            await self._send(f"R {entry.number}")
            reply, _ = await self._until_prompt()
            if bpqmail.not_found(reply) is not None:
                self._note(f"#{entry.number} is no longer on the BBS.")
                result.not_found.append(entry.number)
                continue
            read = bpqmail.parse_read(reply)
            if read is None or not read.complete:
                raise CollectStopped(
                    f"the reply to R {entry.number} was not a complete message; nothing saved"
                )
            message = bpqmail.to_message(read, bbs_call)
            if message.message_id and self.store.find(message.message_id):
                self._note(f"#{entry.number} ({message.message_id}) is already here.")
                result.already_had += 1
                continue
            folder = BBS_INBOX
            if message.kind == KIND_BULLETIN:
                folder = f"{BULLETINS}/{_category_folder(message.category)}"
            raw = ("\r".join(reply) + "\r").encode("utf-8")
            result.filed.append(self.store.add(folder, message, raw=raw, raw_suffix=RAW_SUFFIX))
        self._note(f"Done: {len(result.filed)} received.")


def _category_folder(category: str) -> str:
    """A bulletin category as a folder name: letters, digits, - and _ only."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", category.upper())
    return cleaned or "General"
