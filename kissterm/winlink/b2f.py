"""The B2F exchange with a Winlink gateway, as a client, without I/O.

`Client` takes the bytes the link delivers (`feed`) and hands back the
bytes to send (`take_output`) and what happened (`take_events`), so the
same code runs over an AX.25 link, a VARA session or Telnet, and the tests
drive it from a script (`tests/unit/test_winlink_b2f.py`). Nothing here
touches a socket, the store or the UI.

**The exchange** (wl2k-go `fbb/`: `handshake.go`, `b2f.go`, `wl2k.go`):

1. The gateway sends its SID, `[WL2K-5.0-B2FWIHJM$]` (which must include
   B2), maybe `;PQ: <challenge>` and other `;` lines, and a prompt ending
   in `>`.
2. We answer with `;FW: MYCALL`, our SID `[kissterm-<version>-B2FHM$]`,
   `;PR: <eight digits>` if challenged (`secure.py`), and
   `; TARGET DE MYCALL (LOCATOR)`. Every line ends in CR.
3. Turns alternate, ours first. On our turn: `FF` if we have nothing
   (`FQ` if the gateway had nothing either: quit), else up to five
   proposals `FC EM <MID> <size> <compressed size> 0` and `F> <checksum>`;
   the gateway answers `FS` with a character per proposal (`+`/`Y` send,
   `-`/`N`/`R` already have it, `=`/`L`/`H` later, `!<n>`/`A<n>` send from
   offset n), and we send each accepted message as blocks: SOH, length,
   title, NUL, offset, NUL; then STX, length, up to 125 bytes, repeated;
   then EOT and a checksum. A message counts as sent only once the
   gateway's next turn starts (its next byte is `F` or `;`).
4. On the gateway's turn: proposals and `F>`, which we answer `FS` and then
   read each accepted message; or `FF` (nothing for us); or `FQ` (quit).

A line starting `*` is an error from the far end (`*** Secure login
failed - account password does not match`), reported in its words.

**Deliberate deviation:** wl2k-go ends the handshake at the first line
ending in `>`. Over packet, the node's own lines come first and a node
prompt can end in `>` too, so here nothing counts until the SID line
arrives -- which is also the operator's rule for when the exchange
starts (ROADMAP, 2026-09-26).

# UNVERIFIED: the exchange has been checked against wl2k-go's code and its
# recorded CMS sessions only, not yet against an RMS over the air, and
# whether a CMS accepts a client name it has not seen before in the SID is
# unknown. The first on-air session's transcript becomes a fixture
# (docs/ON-AIR-TESTS.md).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from . import lzhuf
from .message import B2Error, B2Message, decode_header, encode_header, parse, serialize
from .secure import login_response

#: Proposals per block (wl2k-go `MaxBlockSize`).
MAX_BLOCK = 5
#: Bytes per STX block when sending (wl2k-go `MaxMsgLength`).
MAX_CHUNK = 125
#: The largest offset the SOH header can carry.
MAX_OFFSET = 999_999
#: Longest title we send in the SOH header ("Max 80 bytes").
MAX_TITLE = 80

ACCEPT, REJECT, DEFER = "+", "-", "="

_SOH, _STX, _EOT = 0x01, 0x02, 0x04
_SID_RE = re.compile(r"\[.*-(.*)\]")
_PRECEDENCE = (("//WL2K Z/", 0), ("//WL2K O/", 1), ("//WL2K P/", 2))


class B2FError(Exception):
    """The exchange cannot go on. The text is for the operator."""


# -- events --


@dataclass
class Line:
    """A protocol line, `>` sent or `<` received, for the session log."""

    direction: str
    text: str


@dataclass
class Received:
    """A message arrived whole and checked; `raw` is its B2 bytes."""

    message: B2Message
    raw: bytes


@dataclass
class Sent:
    """The gateway took a message (`already_had`: it said it had it)."""

    mid: str
    already_had: bool = False


@dataclass
class Deferred:
    """The gateway asked for a message later; it stays in the Outbox."""

    mid: str


@dataclass
class Pending:
    """A `;PM:` line: a message waiting for us, announced by the CMS."""

    to: str
    mid: str
    size: int
    sender: str
    subject: str


@dataclass
class Proposal:
    mid: str
    size: int
    compressed_size: int
    title: str = ""
    code: str = "C"
    kind: str = "EM"
    answer: str = ""
    offset: int = 0
    data: bytes = b""  # the compressed message, B2 container included

    def line(self) -> str:
        return f"F{self.code} {self.kind} {self.mid} {self.size} {self.compressed_size} 0"

    @property
    def precedence(self) -> int:
        return next((rank for marker, rank in _PRECEDENCE if marker in self.title), 3)


def proposal_for(message: B2Message) -> Proposal:
    raw = serialize(message)
    data = lzhuf.compress(raw)
    return Proposal(message.mid, len(raw), len(data), message.subject or "No title", data=data)


def parse_proposal(line: str) -> Proposal:
    """`FC EM <MID> <size> <compressed size> 0`."""
    parts = line[3:].split(" ")
    if len(line) < 4 or len(parts) != 5:
        raise B2FError(f"malformed proposal: {line!r}")
    kind, mid, size, compressed, _ = parts
    if kind not in ("EM", "CM"):
        raise B2FError(f"unexpected message type {kind!r} in proposal")
    try:
        return Proposal(mid, int(size), int(compressed), code=line[1], kind=kind)
    except ValueError:
        raise B2FError(f"malformed proposal: {line!r}") from None


def parse_answers(line: str, count: int) -> list[tuple[str, int]]:
    """`FS +=!3350-+` -> [(answer, offset)] for `count` proposals."""
    text = line[3:] if line.startswith("FS ") else line
    answers: list[tuple[str, int]] = []
    while text:
        c, text = text[0], text[1:]
        if c in "Yy+":
            answers.append((ACCEPT, 0))
        elif c in "NnRr-":
            answers.append((REJECT, 0))
        elif c in "LlHh=":
            answers.append((DEFER, 0))
        elif c in "Aa!":
            digits = re.match(r"\d+", text)
            if not digits:
                raise B2FError("the gateway asked for an offset without giving one")
            text = text[digits.end():]
            offset = int(digits.group())
            answers.append((ACCEPT, offset if offset <= MAX_OFFSET else 0))
        else:
            raise B2FError(f"unexpected character {c!r} in the gateway's answer")
    if len(answers) != count:
        raise B2FError(f"the gateway answered {len(answers)} of {count} proposals")
    return answers


def checksum(lines: list[str]) -> int:
    """The `F>` checksum: minus the sum of every character, CRs included."""
    return -sum(sum(ord(c) for c in line) + 13 for line in lines) & 0xFF


def remote_error(line: str) -> str:
    """The text of a `*** ...` error line, or ""."""
    if not line.startswith("*"):
        return ""
    return line[line.rfind("*") + 1:].strip()


def _clean(line: str) -> str:
    return line.strip().strip("\x00").strip()


def _title_bytes(title: str) -> bytes:
    title = title or "No title"
    while len(encode_header(title)) > MAX_TITLE and len(title) > 1:
        title = title[:-1]
    return encode_header(title).encode("ascii")


class Client:
    """One B2F exchange as the calling station.

    `outbound` is the messages to offer. `have(mid)` says whether a message
    is already in the store (answered `-`, so the gateway marks it
    delivered); `password` answers a `;PQ:` challenge. Call `feed` with
    every byte from the link after it connects; `done` is set when the
    exchange ends, and `error` says why if it did not end well.
    """

    def __init__(
        self,
        mycall: str,
        target: str,
        *,
        locator: str = "",
        password: str | None = None,
        outbound: list[B2Message] | None = None,
        have: Callable[[str], bool] | None = None,
        name: str = "kissterm",
        version: str = "",
    ) -> None:
        if not version:
            from .. import __version__ as version
        self.mycall = mycall.upper()
        self.target = target.upper()
        self.locator = locator
        self.password = password
        self.have = have or (lambda mid: False)
        self.sid = f"[{name}-{version}-B2FHM$]"
        self.remote_sid = ""
        self.done = False
        self.error = ""
        self._queue = [proposal_for(m) for m in outbound or []]
        self._buf = bytearray()
        self._out = bytearray()
        self._events: list = []
        self._remote_no_msgs = False
        self._gen = self._run()
        self._step()

    # -- the outside --

    def feed(self, data: bytes) -> None:
        if self.done:
            return
        self._buf += data
        self._step()

    def connection_lost(self) -> None:
        """The link went down. An exchange cut short is an error."""
        if not self.done:
            self._finish("the link dropped before the exchange finished")

    def take_output(self) -> bytes:
        out, self._out = bytes(self._out), bytearray()
        return out

    def take_events(self) -> list:
        events, self._events = self._events, []
        return events

    def _step(self) -> None:
        try:
            next(self._gen)
        except StopIteration:
            self._finish("")
        except B2FError as exc:
            self._send_line(f"*** {exc}")
            self._finish(str(exc))

    def _finish(self, error: str) -> None:
        self.done = True
        self.error = error
        self._gen.close()

    # -- reading and writing --

    def _send_line(self, text: str, shown: str | None = None) -> None:
        """Queue `text`; its event (what the log and terminal show) is
        `shown` when given."""
        self._out += text.encode("latin-1", errors="replace") + b"\r"
        self._events.append(Line(">", text if shown is None else shown))

    def _read_line(self):
        while True:
            match = re.search(rb"[\r\n]", self._buf)
            if match:
                raw = bytes(self._buf[:match.start()])
                del self._buf[:match.end()]
                line = _clean(raw.decode("latin-1"))
                if line:
                    self._events.append(Line("<", line))
                    return line
                continue
            yield

    def _read_byte(self):
        while not self._buf:
            yield
        byte = self._buf[0]
        del self._buf[:1]
        return byte

    def _read_bytes(self, n: int):
        while len(self._buf) < n:
            yield
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk

    def _read_until_nul(self):
        while True:
            end = self._buf.find(b"\x00")
            if end >= 0:
                chunk = bytes(self._buf[:end])
                del self._buf[:end + 1]
                return chunk
            if len(self._buf) > 300:
                raise B2FError("a message header without its end")
            yield

    def _peek_byte(self):
        """The next byte that is not a line end, left unread."""
        while True:
            while self._buf[:1] in (b"\r", b"\n"):
                del self._buf[:1]
            if self._buf:
                return self._buf[0]
            yield

    def _protocol_line(self):
        """The next line, raising on a `*` error line."""
        line = yield from self._read_line()
        error = remote_error(line)
        if error:
            raise B2FError(f"the gateway said: {error}")
        return line

    # -- the exchange --

    def _run(self):
        yield from self._handshake()
        my_turn = True
        while True:
            if my_turn:
                quit_sent = yield from self._outbound()
                if quit_sent:
                    return
            else:
                quit_received = yield from self._inbound()
                if quit_received:
                    return
            my_turn = not my_turn

    def _handshake(self):
        challenge = ""
        while True:
            line = yield from self._read_line()
            if line.startswith("[") and line.endswith("]"):
                match = _SID_RE.match(line)
                if not match:
                    raise B2FError(f"unreadable gateway SID: {line}")
                self.remote_sid = match.group(1).upper()
                if "B2" not in self.remote_sid:
                    raise B2FError("the gateway does not speak B2F")
            elif not self.remote_sid:
                continue  # the node's own lines, before the gateway's
            elif line.startswith(";PQ"):
                challenge = line[5:].strip()
            elif line.endswith(">"):
                break
        self._send_line(f";FW: {self.mycall}")
        self._send_line(self.sid)
        if challenge:
            if not self.password:
                raise B2FError("the gateway asks for a password, and none is set for this account")
            # Never logged: beside the ;PQ: challenge in a transcript, the
            # answer lets anyone holding the file test guesses at the
            # password offline (operator's session log, 2026-09-28).
            self._send_line(f";PR: {login_response(challenge, self.password)}",
                            shown=";PR: (secure login answer, not logged)")
        self._send_line(f"; {self.target} DE {self.mycall} ({self.locator})")

    def _outbound(self):
        if not self._queue:
            self._send_line("FQ" if self._remote_no_msgs else "FF")
            return self._remote_no_msgs
        block = sorted(self._queue, key=lambda p: (p.compressed_size, p.mid))
        block = sorted(block, key=lambda p: p.precedence)[:MAX_BLOCK]
        lines = [p.line() for p in block]
        for line in lines:
            self._send_line(line)
        self._send_line(f"F> {checksum(lines):02X}")
        while True:
            line = yield from self._protocol_line()
            if line.startswith(";PM"):
                self._pending(line)
            elif line.startswith(";"):
                continue
            elif line.startswith("FS "):
                break
            else:
                raise B2FError(f"expected the gateway's answer to our proposals, got {line!r}")
        answers = parse_answers(line, len(block))
        sent: list[Proposal] = []
        for proposal, (answer, offset) in zip(block, answers):
            self._queue.remove(proposal)
            if answer == DEFER:
                self._events.append(Deferred(proposal.mid))
            elif answer == REJECT:
                self._events.append(Sent(proposal.mid, already_had=True))
            else:
                proposal.offset = offset
                self._write_message(proposal)
                sent.append(proposal)
        if sent:
            first = yield from self._peek_byte()
            if first not in b"F;":
                line = yield from self._read_line()
                raise B2FError(f"unexpected reply after sending: {line!r}")
            for proposal in sent:
                self._events.append(Sent(proposal.mid))
        return False

    def _write_message(self, proposal: Proposal) -> None:
        title = _title_bytes(proposal.title)
        offset = str(proposal.offset).encode("ascii")
        self._out += bytes((_SOH, len(title) + len(offset) + 2)) + title + b"\x00" + offset + b"\x00"
        data = proposal.data[proposal.offset:]
        for start in range(0, len(data), MAX_CHUNK):
            chunk = data[start:start + MAX_CHUNK]
            self._out += bytes((_STX, len(chunk))) + chunk
        self._out += bytes((_EOT, -sum(data) & 0xFF))
        self._events.append(Line(">", f"[message {proposal.mid}, {len(data)} bytes]"))

    def _pending(self, line: str) -> None:
        parts = line[len(";PM:"):].strip().split(" ", 4)
        if len(parts) == 5:
            to, mid, size, sender, subject = parts
            self._events.append(Pending(to, mid, int(size) if size.isdigit() else 0, sender, subject))

    def _inbound(self):
        proposals: list[Proposal] = []
        lines: list[str] = []
        while True:
            line = yield from self._protocol_line()
            if line.startswith(";PM"):
                self._pending(line)
                continue
            if line.startswith(";"):
                continue
            if len(line) < 2 or line[0] != "F":
                raise B2FError(f"unexpected line from the gateway: {line!r}")
            command = line[:2]
            if command in ("FA", "FB", "FC", "FD"):
                lines.append(line)
                proposals.append(parse_proposal(line) if command in ("FC", "FD") else
                                 Proposal("", 0, 0, code=line[1]))
            elif command == "FF":
                self._remote_no_msgs = True
                return False
            elif command == "FQ":
                return True
            elif command == "F>":
                try:
                    theirs = int(line[3:].strip(), 16)
                except ValueError:
                    theirs = -1
                if theirs != checksum(lines):
                    raise B2FError("proposal checksum error")
                if not proposals:
                    self._remote_no_msgs = True
                    return False
                self._remote_no_msgs = False
                break
            else:
                raise B2FError(f"unknown command from the gateway: {line!r}")
        seen: set[str] = set()
        for proposal in proposals:
            if proposal.mid in seen or proposal.code != "C" or not proposal.mid:
                proposal.answer = DEFER
            elif self.have(proposal.mid):
                proposal.answer = REJECT
            else:
                proposal.answer = ACCEPT
            seen.add(proposal.mid)
        self._send_line("FS " + "".join(p.answer for p in proposals))
        for proposal in proposals:
            if proposal.answer == ACCEPT:
                yield from self._read_message(proposal)
        return False

    def _read_message(self, proposal: Proposal):
        first = yield from self._peek_byte()
        if first == ord("*"):
            line = yield from self._read_line()
            raise B2FError(f"the gateway said: {remote_error(line) or line}")
        yield from self._read_byte()
        if first != _SOH:
            raise B2FError(f"expected the start of a message, got byte {first}")
        length = yield from self._read_byte()
        title = yield from self._read_until_nul()
        offset = yield from self._read_until_nul()
        if length != len(title) + len(offset) + 2:
            raise B2FError("message header length does not match")
        if offset.strip() != b"0":
            raise B2FError(f"the gateway sent from offset {offset.decode('latin-1')}, not the start")
        proposal.title = decode_header(title.decode("latin-1"))
        data = bytearray()
        while True:
            kind = yield from self._read_byte()
            if kind == _STX:
                size = yield from self._read_byte()
                data += yield from self._read_bytes(size or 256)
            elif kind == _EOT:
                check = yield from self._read_byte()
                if (sum(data) + check) & 0xFF:
                    raise B2FError(f"message {proposal.mid} arrived damaged (checksum)")
                break
            else:
                raise B2FError(f"unexpected byte {kind} inside message {proposal.mid}")
        if len(data) != proposal.compressed_size:
            raise B2FError(f"message {proposal.mid} is {len(data)} bytes, proposed {proposal.compressed_size}")
        self._events.append(Line("<", f"[message {proposal.mid}, {len(data)} bytes]"))
        try:
            raw = lzhuf.decompress(bytes(data))
            message = parse(raw)
        except (lzhuf.LzhufError, B2Error) as exc:
            raise B2FError(f"message {proposal.mid} could not be read: {exc}") from None
        self._events.append(Received(message, raw))
