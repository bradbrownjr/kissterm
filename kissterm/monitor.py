"""Turning frames into monitor lines -- kissterm's equivalent of `listen -a`.

The monitor pane is the single most useful diagnostic a packet operator has. It
answers "is my TNC actually hearing anything", "is that node responding to me",
and "why is this link retrying" faster than any status indicator, which is why
it is a first-class pane here rather than a debug option.

Two rules shape this module:

**Remote payload text is untrusted.** Every byte in an information field was
put there by somebody else's transmitter. Rendered raw into a terminal it can
carry ANSI escape sequences that move the cursor, recolour the screen, alter
the window title, or -- with some terminal emulators -- inject a response the
shell will later read. `sanitize` strips C0/C1 control bytes and escape
sequences before anything reaches a widget. This is not paranoia about
malicious hams; a corrupt frame off a noisy channel produces the same bytes by
accident, and losing the display in the middle of an emergency net is the
failure that matters.

**Formatting is separate from filtering.** `MonitorFilter` decides what is
worth showing; `format_frame` decides how it reads. Keeping them apart is what
lets the same decode feed the monitor pane, a session log file, and the APRS
pane without three divergent renderers.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .ax25.frame import PID_NO_LAYER3, AX25Frame, UType

#: ESC-introduced sequences: CSI, OSC, and the single-character escapes.
_ANSI_RE = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
#: C0 controls except tab, LF and CR, plus DEL and the C1 range.
_CONTROL_RE = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def sanitize(data: bytes, keep_newlines: bool = True) -> str:
    """Make remote-supplied bytes safe to put in a widget.

    Strips escape sequences first, then remaining control bytes, then decodes
    as latin-1 -- not UTF-8. Packet is a byte-oriented, mostly-ASCII medium and
    a decoder that raises or inserts replacement characters on the high bytes
    of a corrupt frame loses the readable part of the line along with the noise.
    latin-1 is total: every byte maps to something, nothing is lost, and the
    printable ASCII that makes up real traffic comes through untouched.
    """
    cleaned = _ANSI_RE.sub(b"", data)
    cleaned = _CONTROL_RE.sub(b"", cleaned)
    text = cleaned.decode("latin-1")
    if not keep_newlines:
        text = text.replace("\r", " ").replace("\n", " ")
    else:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


@dataclass(slots=True)
class MonitorFilter:
    """What the monitor pane shows.

    Defaults are chosen for "I want to see what is happening on the channel":
    everything except the supervisory chatter, which on a busy link is most of
    the frames and almost none of the information.
    """

    show_supervisory: bool = False
    show_unnumbered: bool = True
    show_information: bool = True
    show_ui: bool = True
    #: Only these callsigns (source or destination), if non-empty.
    calls: tuple[str, ...] = ()
    #: Substring that must appear in the payload text, if set.
    contains: str = ""
    ports: tuple[int, ...] = ()

    def allows(self, frame: AX25Frame, port: int = 0) -> bool:
        if self.ports and port not in self.ports:
            return False
        if frame.kind == "S" and not self.show_supervisory:
            return False
        if frame.kind == "I" and not self.show_information:
            return False
        if frame.kind == "U":
            is_ui = frame.utype is UType.UI
            if is_ui and not self.show_ui:
                return False
            if not is_ui and not self.show_unnumbered:
                return False
        if self.calls:
            wanted = {c.upper() for c in self.calls}
            seen = {str(frame.path.source).upper(), str(frame.path.destination).upper()}
            seen |= {str(r).upper() for r in frame.path.repeaters}
            if not (wanted & seen):
                return False
        if self.contains:
            if self.contains.lower() not in sanitize(frame.info, False).lower():
                return False
        return True


@dataclass(slots=True)
class MonitorLine:
    """One rendered monitor entry, split so the UI can style the parts."""

    timestamp: float
    port: int
    header: str
    payload: str
    kind: str

    def as_text(self, show_time: bool = True) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(self.timestamp)) if show_time else ""
        head = f"{stamp} [{self.port}] {self.header}".strip()
        return f"{head}\n{self.payload}" if self.payload else head


def format_frame(frame: AX25Frame, port: int = 0, when: float | None = None) -> MonitorLine:
    """Render one frame the way a packet operator expects to read it.

    The header follows the long-standing `listen`/BPQ convention -- source to
    destination, then the digipeater path, then the frame type and sequence
    numbers -- because operators already know how to read that and inventing a
    prettier format would only make their experience non-transferable.
    """
    header = frame.summary()
    payload = ""
    if frame.info and frame.pid in (PID_NO_LAYER3, None):
        payload = sanitize(frame.info).rstrip("\n")
    elif frame.info:
        payload = f"<{len(frame.info)} bytes, PID 0x{frame.pid:02X}>"
    return MonitorLine(
        timestamp=when if when is not None else time.time(),
        port=port,
        header=header,
        payload=payload,
        kind=frame.control_name,
    )
