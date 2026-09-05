"""Per-session transcript writer -- one plain-text file per connected link.

An operator who worked a station six months ago and wants to know what was
actually said has nowhere to look once the RichLog scrollback is gone --
Textual does not persist widget content, and the heard table only ever
tracked *that* a station was heard, not what crossed the link. `SessionLog`
exists to make "what did we actually say to each other" answerable after the
fact: everything sent, everything received, and every link-state change
(connected, retry, timeout, disconnected) gets appended to a file named after
the two callsigns and the moment the session started.

**A transcript is a convenience; a live link is not.** Every public method
here catches `OSError` and turns it into "stop writing, remember why, keep
going" rather than letting a full disk, a read-only log directory, or a log
directory that got unmounted mid-session propagate up into the code driving
the actual AX.25 link. Losing the transcript is a shrug. Killing the
connection because the disk that holds the transcript filled up is a
regression a packet operator will not forgive, especially mid-emergency-net.
Once `failed` is set the object stays inert for its remaining lifetime --
every subsequent call is a silent no-op -- rather than retrying and risking a
half-written, re-opened-mid-line file.

**Received text is written exactly as handed to `received()`.** This module
does not import or call `kissterm.monitor.sanitize`. Sanitizing here as well
would be redundant with the monitor pane's own pass and would hide the
one-sanitizer invariant behind two call sites that could drift out of sync.
The caller (the pane/session glue) is responsible for calling `sanitize`
before text reaches `received`, so a transcript file only ever contains
already-cleaned text -- but that also means calling this module directly with
raw wire bytes decoded some other way is a way to reintroduce the exact
escape-sequence problem `sanitize` exists to prevent.

Filenames are *constructed* from `mycall`/`started`/`peer`, never taken
verbatim from the wire. `peer` reaches this module from an incoming AX.25
address or a user-typed connect target -- either way it is attacker-adjacent
by the time it could end up in a path, so `transcript_name` reduces it (and
`mycall`, for symmetry -- a locally misconfigured callsign should not be able
to do anything worse than pick an ugly filename either) to a short, boring
`[A-Za-z0-9-]` token before it ever touches a `Path`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

#: Anything outside this set is stripped, not escaped -- there is no reversible
#: encoding a plain-text filename needs to support, and escaping (e.g. percent
#: encoding) just moves the "does this still shell-glob/path-traverse safely"
#: question instead of closing it.
_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9-]")
_MAX_TOKEN_LEN = 12


def _sanitize_call(value: str) -> str:
    """Reduce a callsign-shaped string to a short, filesystem-safe token.

    Uppercased because AX.25 callsigns are conventionally upper-case and a
    transcript directory mixing `w1aw-1` and `W1AW-1` files for the same
    station is a self-inflicted annoyance. Capped at 12 characters -- longer
    than any real callsign-SSID pair needs, short enough that even a
    pathological input can't produce an unwieldy filename or, combined with
    a long peer, threaten filename length limits on any real filesystem.
    """
    cleaned = _SAFE_CHARS_RE.sub("", value.upper())[:_MAX_TOKEN_LEN]
    return cleaned or "UNKNOWN"


def transcript_name(mycall: str, peer: str, started: float) -> str:
    """Build the transcript filename for one session.

    Timestamp first so a directory listing sorts chronologically without the
    caller needing to parse callsigns out of the name first. Both callsigns
    are sanitized -- see `_sanitize_call` -- so this function's output is
    always a bare filename: no path separator, no leading dot, safe to join
    onto any directory without escaping it.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(started))
    return f"{stamp}_{_sanitize_call(mycall)}_{_sanitize_call(peer)}.log"


class SessionLog:
    """Appends one plain-text transcript for a single connected session.

    Not a general-purpose logger: one instance covers exactly one session,
    from `open()` to `close()`, and writes to exactly one file. A new
    session -- even to the same peer moments later -- gets a new
    `SessionLog`, which is also why the filename embeds `started`: two
    sessions with the same two callsigns in the same second would otherwise
    collide, and appending (see `open`) means a collision silently merges two
    unrelated conversations into one file instead of failing loudly.
    """

    def __init__(
        self,
        directory: Path,
        mycall: str,
        peer: str,
        started: float | None = None,
        timestamps: bool = True,
    ) -> None:
        self._directory = Path(directory)
        self._mycall = mycall
        self._peer = peer
        self._started = started if started is not None else time.time()
        self._timestamps = timestamps
        self._path = self._directory / transcript_name(mycall, peer, self._started)
        self._handle = None
        self._failed = ""
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def failed(self) -> str:
        return self._failed

    def open(self) -> bool:
        """Create the log directory (if needed) and open the transcript file.

        Append mode, not write/truncate: `transcript_name` is second-
        granularity, so two sessions to the same peer inside the same wall
        clock second produce the same name, and append means the second
        session's lines land after the first's instead of destroying them.
        `errors="replace"` on top of UTF-8 matches the append-never-raise
        contract -- a stray byte that doesn't round-trip as UTF-8 must not be
        the thing that takes the transcript down. Line-buffered so a crash or
        `kill -9` mid-session still leaves every line written so far on disk
        instead of sitting in a libc buffer.
        """
        if self._failed or self._closed or self._handle is not None:
            # Already open. Reopening would leak the first handle and write a
            # second header into the middle of a live transcript.
            return False
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            self._handle = open(
                self._path, "a", encoding="utf-8", errors="replace", buffering=1
            )
            header_date = time.strftime("%Y-%m-%d", time.localtime(self._started))
            self._handle.write(
                f"# kissterm session log -- {self._mycall} <-> {self._peer} -- {header_date}\n"
            )
        except OSError as exc:
            self._failed = f"could not open {self._path}: {exc}"
            self._handle = None
            return False
        return True

    def _prefix(self) -> str:
        if not self._timestamps:
            return ""
        return f"[{time.strftime('%H:%M:%S')}] "

    def _write(self, marker: str, text: str) -> None:
        if self._handle is None or self._failed or self._closed:
            return
        prefix = self._prefix()
        # rstrip("\n") first so a trailing newline in the caller's text does
        # not produce a dangling, unprefixed blank line at the end -- every
        # line of the entry gets the same marker or none of it reads as one
        # coherent record years later.
        lines = text.rstrip("\n").split("\n")
        try:
            for line in lines:
                self._handle.write(f"{prefix}{marker} {line}\n")
        except OSError as exc:
            self._failed = f"write to {self._path} failed: {exc}"
            self._handle = None

    def sent(self, text: str) -> None:
        self._write(">", text)

    def received(self, text: str) -> None:
        self._write("<", text)

    def note(self, text: str) -> None:
        self._write("*", text)

    def close(self) -> None:
        """Write a closing marker and release the file handle.

        Idempotent and safe from any state -- never opened, failed mid-open,
        failed mid-write, or already closed -- because callers close from
        session-teardown paths that do not want to first work out which of
        those states they are in.
        """
        if self._closed:
            return
        handle = self._handle
        self._closed = True
        if handle is None:
            return
        try:
            handle.write(f"{self._prefix()}* session closed\n")
            handle.close()
        except OSError as exc:
            self._failed = self._failed or f"close of {self._path} failed: {exc}"
        finally:
            self._handle = None
