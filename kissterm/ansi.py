"""Remote-supplied escape sequences: an allowlist, not a denylist.

`monitor.sanitize` removes every escape sequence a remote station sends. That
is the right default and it stays the default everywhere text is *matched*,
*filtered* or *logged*. It is the wrong answer in exactly one place: the
terminal pane, where a BBS's colour is the point. A packet BBS that has been
painting menus in ANSI colour since 1988 renders as flat grey under a total
strip, and the operator loses information the sysop deliberately encoded.

This module is the narrow exception, and it is written the only way an
exception like this is safe to write.

**Allowlist, never denylist.** The set of escape sequences a terminal
understands is large, undocumented in practice, and different on every
emulator; the set that can only change how a glyph is painted is small and
enumerable. So: SGR (`CSI ... m`) with recognised parameters survives.
Everything else -- cursor movement, erase, scroll regions, OSC (window title,
clipboard, hyperlinks), DCS, APC, PM, SOS, charset selection, the terminal
*query* sequences whose replies a shell later reads as keystrokes -- is
removed. Anything unrecognised is removed by construction rather than by
having been thought of, which is the property a denylist cannot have. This is
the class of bug that has produced real terminal-emulator CVEs, and a corrupt
frame off a noisy channel produces the same bytes as a hostile one.

**A dropped sequence is consumed whole.** Removing the ESC and leaving `[2J`
behind as literal text is the classic version of this bug -- it looks like it
worked, and it fails the moment anything downstream re-interprets the string.
`_consume_escape` always advances past the entire sequence, including a
sequence truncated by the end of the buffer, which is discarded rather than
held over.

**Not allowed, deliberately:**

- *Blink* (5, 6). Photosensitivity is a real accessibility hazard and no
  remote station gets to impose it on an operator's screen.
- *Conceal* (8). Text that renders invisible is a spoofing primitive, not a
  formatting choice.
- *Underline colour* (58, 59) and the framed/encircled/overlined group. No
  loss worth the parser surface.

Colour pairs remain a residual annoyance: a station can set a foreground
matching the background and make text hard to read. That is cosmetic, it is
undone by scrolling or copying the text out, and it is not the boundary this
module defends -- which is that remote bytes must never move the cursor,
address the screen outside this widget, or provoke a reply.

**Styles do not persist across calls.** Each chunk is decoded independently,
so an unterminated `CSI 1 m` at the end of one frame cannot bold everything
that arrives after it. A real terminal would carry that state; carrying it
would mean one malformed frame permanently colouring the session.
"""

from __future__ import annotations

import re

from rich.text import Text

_ESC = 0x1B

#: C0 controls except tab, LF and CR, plus DEL and the whole C1 range. C1 is
#: stripped because on a terminal in 8-bit mode 0x9B *is* CSI -- an escape
#: sequence with no ESC byte in front of it, which a parser looking only for
#: 0x1B would sail straight past.
_CONTROL_RE = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

#: SGR parameters that can only change how a glyph is painted.
SAFE_SGR: frozenset[int] = frozenset(
    {
        0,  # reset
        1,  # bold
        2,  # dim
        3,  # italic
        4,  # underline
        7,  # reverse
        9,  # strikethrough
        21,  # double underline (bold-off on some terminals; harmless either way)
        22,  # normal intensity
        23,  # italic off
        24,  # underline off
        27,  # reverse off
        29,  # strikethrough off
        39,  # default foreground
        49,  # default background
        *range(30, 38),  # foreground
        *range(40, 48),  # background
        *range(90, 98),  # bright foreground
        *range(100, 108),  # bright background
    }
)

#: Extended-colour introducers, which carry their own parameters.
_EXTENDED = (38, 48)

#: A sequence longer than this is not formatting, it is an attempt to find a
#: parser bug. Dropped whole.
_MAX_PARAMS = 32


def filter_ansi(data: bytes) -> bytes:
    """Strip every escape sequence except allowlisted SGR, and every control byte.

    Newlines and tabs survive; `\\r\\n` and a lone `\\r` are normalised to
    `\\n`, matching `monitor.sanitize` so the two paths cannot disagree about
    where a line ends.
    """
    out = bytearray()
    index = 0
    length = len(data)
    while index < length:
        if data[index] != _ESC:
            stop = data.find(_ESC, index)
            if stop == -1:
                stop = length
            out += _CONTROL_RE.sub(b"", data[index:stop])
            index = stop
            continue
        kept, index = _consume_escape(data, index)
        if kept is not None:
            out += kept
    return bytes(out).replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def to_text(data: bytes) -> Text:
    """Decode remote bytes into a Rich `Text` with allowlisted styles applied.

    latin-1, not UTF-8, for the reason `monitor.sanitize` uses it: packet is a
    byte-oriented, mostly-ASCII medium, and a decoder that raises or inserts
    replacement characters on the high bytes of a corrupt frame loses the
    readable part of the line along with the noise.
    """
    filtered = filter_ansi(data).decode("latin-1")
    if "\x1b" not in filtered:
        # Nothing to parse. Skipping Rich's decoder here is not just speed:
        # it keeps the overwhelmingly common case on a path with no parser in
        # it at all.
        return Text(filtered)
    return Text.from_ansi(filtered)


def strip_ansi(data: bytes) -> str:
    """The plain text `to_text` would render, with no styles. For logs."""
    return to_text(data).plain


# ---------------------------------------------------------------------------
# Escape-sequence consumption
# ---------------------------------------------------------------------------


def _consume_escape(data: bytes, start: int) -> tuple[bytes | None, int]:
    """Consume one escape sequence at ``start``.

    Returns ``(bytes to keep or None, index just past the sequence)``. The
    index always advances past the whole sequence even when nothing is kept --
    see the module docstring on why leaking a dropped sequence's payload as
    literal text is the bug this shape prevents.
    """
    length = len(data)
    after = start + 1
    if after >= length:
        # A trailing ESC with nothing after it. Discard rather than hold: the
        # next chunk is a separate frame, possibly from a different station,
        # and splicing them would let one station's partial sequence be
        # completed by another's payload.
        return None, length

    introducer = data[after]

    if introducer == 0x5B:  # '[' -- CSI
        return _consume_csi(data, after + 1)

    if introducer in (0x5D, 0x50, 0x58, 0x5E, 0x5F):
        # OSC, DCS, SOS, PM, APC: a string sequence, terminated by ST
        # (ESC \) or, for OSC, BEL. All dropped -- these are the window
        # title, the clipboard, and the hyperlink sequences.
        return None, _consume_string_sequence(data, after + 1)

    # Everything else: an optional run of intermediates then one final byte.
    index = after
    while index < length and 0x20 <= data[index] <= 0x2F:
        index += 1
    if index < length:
        index += 1  # the final byte
    return None, index


def _consume_csi(data: bytes, start: int) -> tuple[bytes | None, int]:
    length = len(data)
    index = start
    while index < length and 0x30 <= data[index] <= 0x3F:  # parameter bytes
        index += 1
    params_end = index
    while index < length and 0x20 <= data[index] <= 0x2F:  # intermediates
        index += 1
    if index >= length:
        return None, length  # truncated; discard
    final = data[index]
    index += 1
    if final != 0x6D:  # not SGR
        return None, index
    kept = _filter_sgr(data[start:params_end])
    return kept, index


def _filter_sgr(params: bytes) -> bytes | None:
    """Rebuild an SGR sequence from only its allowlisted parameters.

    Returns None to drop the sequence entirely. Note that dropping is *not*
    the same as emitting `CSI m`: empty parameters mean reset, so an SGR whose
    every parameter was rejected must vanish, not turn into a reset that the
    sender never asked for.
    """
    if not params:
        return b"\x1b[0m"  # `CSI m` is a legitimate reset; normalise it
    if not all(0x30 <= byte <= 0x39 or byte == 0x3B for byte in params):
        # A private-parameter marker (`?`, `>`, `<`, `=`) or the ITU colon
        # sub-parameter form. Neither is formatting we need, and both change
        # how the parameter list is read.
        return None

    try:
        codes = [int(part or "0") for part in params.decode("ascii").split(";")]
    except ValueError:
        return None
    if len(codes) > _MAX_PARAMS:
        return None

    kept: list[int] = []
    index = 0
    while index < len(codes):
        code = codes[index]
        if code in _EXTENDED:
            chunk = _extended_colour(codes, index)
            if chunk is None:
                # Malformed extended colour. Drop the whole sequence: without
                # knowing where its parameters end there is no safe place to
                # resume, and guessing would let the remainder be reinterpreted.
                return None
            kept.extend(chunk)
            index += len(chunk)
            continue
        if code in SAFE_SGR:
            kept.append(code)
        index += 1

    if not kept:
        return None
    return b"\x1b[" + ";".join(str(c) for c in kept).encode("ascii") + b"m"


def _extended_colour(codes: list[int], index: int) -> list[int] | None:
    """Validate `38;5;n` / `38;2;r;g;b` (and the 48 background forms)."""
    if index + 1 >= len(codes):
        return None
    mode = codes[index + 1]
    if mode == 5:
        span = codes[index : index + 3]
        needed = 3
    elif mode == 2:
        span = codes[index : index + 5]
        needed = 5
    else:
        return None
    if len(span) != needed or any(not 0 <= value <= 255 for value in span[2:]):
        return None
    return span


def _consume_string_sequence(data: bytes, start: int) -> int:
    """Index just past an OSC/DCS/APC/PM/SOS string, terminated by ST or BEL."""
    length = len(data)
    index = start
    while index < length:
        byte = data[index]
        if byte == 0x07:  # BEL
            return index + 1
        if byte == _ESC:
            if index + 1 < length and data[index + 1] == 0x5C:  # ESC \ -- ST
                return index + 2
            # An ESC that is not ST ends the string sequence too: a terminal
            # abandons the unterminated one and starts parsing anew. Stopping
            # here rather than swallowing the rest is what keeps an
            # unterminated OSC from eating an entire session's output.
            return index
        index += 1
    return length
