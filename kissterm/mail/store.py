"""The message store: a directory tree that mirrors the Mail tab's folder tree.

```
<root>/Mail/BBS/{Inbox,Outbox,Sent,Deleted}
<root>/Mail/Winlink/{Inbox,Outbox,Sent,Deleted}
<root>/Mail/Local/{Inbox,Sent,Deleted}
<root>/Bulletins/<category>, plus Bulletins/Deleted
<root>/Files/{Downloads,Attachments,Received}
```

Why it is shaped this way (ROADMAP P2, "The folder tree"):

- **Folders separate kinds of mail, never sources.** One BBS is reachable
  several ways (WS1EC-15 then BBS, the CCEMA NET/ROM alias, WS1EC-2 direct,
  the CCEBBS alias); a folder per route would split one mailbox four ways,
  and Outpost and Winlink Express both file everything in one place. Where
  a message came from is its `Source:` header (`BBS WS1EC`), keyed on the
  BBS's own callsign, never the route. Decided by the operator 2026-09-23.

- **One plain file per message** (`message.py`), named
  `YYYYMMDD-HHMMSS_<sender>.txt` so a directory listing sorts by date and
  any editor opens it. The index (`.index.json`) is only a cache of header
  summaries keyed by path, size and mtime; delete it and `refresh()` rebuilds
  it from the files. Nothing is ever known only to the index.
- **Deleted is a real folder, not destruction.** `delete()` moves a message
  to the `Deleted` folder beside the folder it was in and records where it
  came from; `restore()` puts it back. Only `purge()` removes a file, and
  only from a Deleted folder. A message that came over a marginal HF path
  may not be re-sendable.
- **Raw copies travel with the message.** `add(..., raw=...)` writes
  `<stem>.b2f` (or another suffix) beside `<stem>.txt`, so a Winlink message
  is kept exactly as received and a parser bug loses nothing. Move, delete
  and purge carry every `<stem>.*` sibling along.
- **Files/ holds files, not messages**, so the index covers only Mail/ and
  Bulletins/.

No I/O outside the root, no UI and no network: this is unit-tested the way
`ax25/` is. Folder names can come from remote data (a bulletin category), so every
path is checked to stay inside the root, dotfiles and symlinks are skipped,
and a folder segment is restricted to a conservative character set.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .message import (
    KIND_BULLETIN,
    STATUS_NEW,
    STATUS_READ,
    Message,
    format_message,
    parse_date,
    parse_message,
)

MAIL = "Mail"
BULLETINS = "Bulletins"
FILES = "Files"
DELETED = "Deleted"
INBOX = "Inbox"
OUTBOX = "Outbox"
SENT = "Sent"

MESSAGE_SUFFIX = ".txt"
INDEX_NAME = ".index.json"
_INDEX_VERSION = 2

#: Folders that exist on a fresh install. Bulletin categories are made as
#: bulletins are filed.
DEFAULT_FOLDERS = (
    f"{MAIL}/BBS/{INBOX}",
    f"{MAIL}/BBS/{OUTBOX}",
    f"{MAIL}/BBS/{SENT}",
    f"{MAIL}/BBS/{DELETED}",
    f"{MAIL}/Winlink/{INBOX}",
    f"{MAIL}/Winlink/{OUTBOX}",
    f"{MAIL}/Winlink/{SENT}",
    f"{MAIL}/Winlink/{DELETED}",
    f"{MAIL}/Local/{INBOX}",
    f"{MAIL}/Local/{SENT}",
    f"{MAIL}/Local/{DELETED}",
    f"{BULLETINS}/{DELETED}",
    f"{FILES}/Downloads",
    f"{FILES}/Attachments",
    f"{FILES}/Received",
)

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9-]+")
_RAW_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,8}$")


def check_folder(folder: str) -> str:
    """Return `folder` normalised to `A/B/C`, or raise ValueError.

    Each segment starts with a letter or digit and uses only letters,
    digits, space, `_`, `.` and `-`, so a name can never be `..`, absolute,
    hidden, or carry a separator.
    """
    text = str(folder).replace("\\", "/").rstrip("/")
    if not text:
        raise ValueError("empty folder path")
    if text.startswith("/"):
        raise ValueError(f"absolute folder path: {folder!r}")
    parts = text.split("/")
    for part in parts:
        if not _SEGMENT_RE.fullmatch(part) or part.endswith((".", " ")):
            raise ValueError(f"unsafe folder name: {part!r}")
    return "/".join(parts)


def deleted_folder_for(folder: str) -> str:
    """The Deleted folder beside `folder` (its parent's `Deleted`)."""
    parts = check_folder(folder).split("/")
    return "/".join([*parts[:-1], DELETED])


def is_deleted_folder(folder: str) -> bool:
    return check_folder(folder).split("/")[-1] == DELETED


@dataclass(frozen=True)
class Summary:
    """What a message list shows, without reading the body.

    `ref` is the message's path relative to the store root, POSIX-style;
    it is the handle every other store call takes.
    """

    ref: str
    folder: str
    sender: str
    to: str
    subject: str
    date: datetime | None
    message_id: str
    source: str
    kind: str
    category: str
    expires: datetime | None
    status: str
    size: int

    @property
    def is_read(self) -> bool:
        return self.status == STATUS_READ

    def expired(self, now: datetime | None = None) -> bool:
        if self.expires is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.expires


def _date_text(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _summary_to_json(s: Summary) -> dict:
    return {
        "folder": s.folder,
        "sender": s.sender,
        "to": s.to,
        "subject": s.subject,
        "date": _date_text(s.date),
        "message_id": s.message_id,
        "source": s.source,
        "kind": s.kind,
        "category": s.category,
        "expires": _date_text(s.expires),
        "status": s.status,
        "size": s.size,
    }


def _summary_from_json(ref: str, d: dict) -> Summary:
    return Summary(
        ref=ref,
        folder=str(d.get("folder", "")),
        sender=str(d.get("sender", "")),
        to=str(d.get("to", "")),
        subject=str(d.get("subject", "")),
        date=parse_date(str(d.get("date", ""))),
        message_id=str(d.get("message_id", "")),
        source=str(d.get("source", "")),
        kind=str(d.get("kind", "")),
        category=str(d.get("category", "")),
        expires=parse_date(str(d.get("expires", ""))),
        status=str(d.get("status", STATUS_NEW)),
        size=int(d.get("size", 0)),
    )


class MessageStore:
    """Folders and message files under one root directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        # ref -> (mtime_ns, size, Summary)
        self._index: dict[str, tuple[int, int, Summary]] = {}
        self._loaded = False

    # -- paths -------------------------------------------------------------

    def _dir(self, folder: str) -> Path:
        return self.root.joinpath(*check_folder(folder).split("/"))

    def _path(self, ref: str) -> Path:
        """The file for `ref`, refusing anything that leaves the root."""
        pure = PurePosixPath(str(ref).replace("\\", "/"))
        if pure.is_absolute() or not pure.parts or pure.suffix != MESSAGE_SUFFIX:
            raise ValueError(f"not a message reference: {ref!r}")
        check_folder("/".join(pure.parts[:-1]))
        name = pure.parts[-1]
        if name.startswith(".") or "/" in name:
            raise ValueError(f"not a message reference: {ref!r}")
        return self.root.joinpath(*pure.parts)

    def _ref(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _folder_of(ref: str) -> str:
        return ref.rsplit("/", 1)[0]

    # -- folders -----------------------------------------------------------

    def ensure_default_tree(self) -> None:
        for folder in DEFAULT_FOLDERS:
            self.create_folder(folder)

    def create_folder(self, folder: str) -> str:
        folder = check_folder(folder)
        self._dir(folder).mkdir(parents=True, exist_ok=True)
        return folder

    def folders(self) -> list[str]:
        """Every folder under the root, sorted, as `A/B/C` paths."""
        out: list[str] = []
        if not self.root.is_dir():
            return out
        for dirpath, dirnames, _files in os.walk(self.root):
            here = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and not (here / d).is_symlink()
            )
            if here == self.root:
                continue
            rel = here.relative_to(self.root).as_posix()
            try:
                out.append(check_folder(rel))
            except ValueError:
                dirnames[:] = []
        return sorted(out)

    # -- index -------------------------------------------------------------

    def _index_path(self) -> Path:
        return self.root / INDEX_NAME

    def _load_index(self) -> None:
        self._loaded = True
        self._index = {}
        try:
            data = json.loads(self._index_path().read_text(encoding="utf-8"))
            if data.get("version") != _INDEX_VERSION:
                return
            for ref, entry in data.get("messages", {}).items():
                self._index[ref] = (
                    int(entry["mtime_ns"]),
                    int(entry["size"]),
                    _summary_from_json(ref, entry["summary"]),
                )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # A missing or damaged cache is rebuilt from the files.
            self._index = {}

    def _save_index(self) -> None:
        data = {
            "version": _INDEX_VERSION,
            "messages": {
                ref: {"mtime_ns": m, "size": z, "summary": _summary_to_json(s)}
                for ref, (m, z, s) in sorted(self._index.items())
            },
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / f"{INDEX_NAME}.tmp"
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, self._index_path())
        except OSError:
            # The index is only a cache; failing to write it loses nothing.
            pass

    def _summarise(self, path: Path) -> tuple[int, int, Summary]:
        stat = path.stat()
        message = parse_message(path.read_bytes())
        ref = self._ref(path)
        summary = Summary(
            ref=ref,
            folder=self._folder_of(ref),
            sender=message.sender,
            to=message.to,
            subject=message.subject,
            date=message.date,
            message_id=message.message_id,
            source=message.source,
            kind=message.kind,
            category=message.category,
            expires=message.expires,
            status=message.status,
            size=stat.st_size,
        )
        return stat.st_mtime_ns, stat.st_size, summary

    def _message_files(self):
        for top in (MAIL, BULLETINS):
            base = self.root / top
            if not base.is_dir() or base.is_symlink():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                here = Path(dirpath)
                dirnames[:] = [
                    d for d in dirnames if not d.startswith(".") and not (here / d).is_symlink()
                ]
                for name in filenames:
                    path = here / name
                    if (
                        name.endswith(MESSAGE_SUFFIX)
                        and not name.startswith(".")
                        and not path.is_symlink()
                    ):
                        yield path

    def refresh(self) -> None:
        """Bring the index up to date with the files on disk.

        Unchanged files (same size and mtime) are not re-read, so this is
        cheap enough to call whenever the Mail tab is shown.
        """
        if not self._loaded:
            self._load_index()
        fresh: dict[str, tuple[int, int, Summary]] = {}
        changed = False
        for path in self._message_files():
            ref = self._ref(path)
            try:
                check_folder(self._folder_of(ref))
                stat = path.stat()
            except (ValueError, OSError):
                continue
            cached = self._index.get(ref)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                fresh[ref] = cached
                continue
            try:
                fresh[ref] = self._summarise(path)
            except OSError:
                continue
            changed = True
        if changed or fresh.keys() != self._index.keys():
            self._index = fresh
            self._save_index()
        else:
            self._index = fresh

    def _touch_index(self, *refs: str, removed: tuple[str, ...] = ()) -> None:
        if not self._loaded:
            self._load_index()
        for ref in removed:
            self._index.pop(ref, None)
        for ref in refs:
            self._index[ref] = self._summarise(self._path(ref))
        self._save_index()

    # -- reading -----------------------------------------------------------

    def list(self, folder: str) -> list[Summary]:
        """Messages directly in `folder`, newest first.

        Undated messages sort by filename, which is itself date-stamped.
        """
        folder = check_folder(folder)
        self.refresh()
        items = [s for _m, _z, s in self._index.values() if s.folder == folder]
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        items.sort(key=lambda s: (s.date or epoch, s.ref), reverse=True)
        return items

    def unread_count(self, folder: str) -> int:
        return sum(1 for s in self.list(folder) if not s.is_read)

    def read(self, ref: str) -> Message:
        return parse_message(self._path(ref).read_bytes())

    def raw_files(self, ref: str) -> list[Path]:
        """The `<stem>.*` siblings kept beside a message (raw B2F, etc.)."""
        path = self._path(ref)
        return sorted(
            p
            for p in path.parent.glob(f"{glob.escape(path.stem)}.*")
            if p != path and not p.name.endswith(MESSAGE_SUFFIX) and p.is_file()
        )

    def find(self, message_id: str, source: str = "") -> list[Summary]:
        """Messages with this Message-Id, optionally from one source only.

        This is how a BBS collection avoids filing a message twice, however
        the BBS was reached: a BID/MID is unique network-wide, and a bare
        BBS message number is unique only with its `source` (`BBS WS1EC`).
        Messages in Deleted count, so deleting one does not re-download it.
        """
        if not message_id:
            return []
        self.refresh()
        return [
            s
            for _m, _z, s in self._index.values()
            if s.message_id == message_id and (not source or s.source == source)
        ]

    def expired(self, now: datetime | None = None) -> list[Summary]:
        """Bulletins past their expiry that are not already in a Deleted folder."""
        self.refresh()
        return [
            s
            for _m, _z, s in self._index.values()
            if s.kind == KIND_BULLETIN and s.expired(now) and not is_deleted_folder(s.folder)
        ]

    # -- writing -----------------------------------------------------------

    def _new_name(self, directory: Path, message: Message) -> Path:
        when = message.date or datetime.now(timezone.utc)
        stamp = when.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
        slug = _SLUG_RE.sub("", message.sender.upper())[:16] or "UNKNOWN"
        base = f"{stamp}_{slug}"
        n = 1
        while True:
            stem = base if n == 1 else f"{base}-{n}"
            candidate = directory / f"{stem}{MESSAGE_SUFFIX}"
            # A stem is free only if no sibling of any suffix uses it, so a
            # raw copy can never land on another message's.
            if not any(directory.glob(f"{glob.escape(stem)}.*")):
                return candidate
            n += 1

    @staticmethod
    def _write_new(path: Path, data: bytes) -> None:
        with open(path, "xb") as handle:
            handle.write(data)

    def add(
        self,
        folder: str,
        message: Message,
        raw: bytes | None = None,
        raw_suffix: str = ".b2f",
    ) -> str:
        """File `message` in `folder`, creating the folder. Returns its ref."""
        if raw is not None and not _RAW_SUFFIX_RE.fullmatch(raw_suffix):
            raise ValueError(f"bad raw suffix: {raw_suffix!r}")
        directory = self._dir(folder)
        directory.mkdir(parents=True, exist_ok=True)
        while True:
            path = self._new_name(directory, message)
            try:
                self._write_new(path, format_message(message).encode("utf-8"))
                break
            except FileExistsError:
                continue
        if raw is not None:
            self._write_new(path.with_suffix(raw_suffix), raw)
        ref = self._ref(path)
        self._touch_index(ref)
        return ref

    def _rewrite(self, ref: str, message: Message) -> None:
        path = self._path(ref)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(format_message(message).encode("utf-8"))
        os.replace(tmp, path)
        self._touch_index(ref)

    def set_read(self, ref: str, read: bool = True) -> None:
        message = self.read(ref)
        status = STATUS_READ if read else STATUS_NEW
        if message.status != status:
            message.status = status
            self._rewrite(ref, message)

    def move(self, ref: str, folder: str) -> str:
        """Move a message and its raw siblings into `folder`. Returns the new ref."""
        path = self._path(ref)
        if not path.is_file():
            raise FileNotFoundError(ref)
        target = self._dir(folder)
        if target == path.parent:
            return ref
        target.mkdir(parents=True, exist_ok=True)
        message = parse_message(path.read_bytes())
        new_path = self._new_name(target, message)
        siblings = self.raw_files(ref)
        os.replace(path, new_path)
        for sibling in siblings:
            os.replace(sibling, new_path.with_suffix(sibling.suffix))
        new_ref = self._ref(new_path)
        self._touch_index(new_ref, removed=(ref,))
        return new_ref

    def delete(self, ref: str) -> str:
        """Move a message to the Deleted folder beside it. Returns the new ref."""
        folder = self._folder_of(ref)
        if is_deleted_folder(folder):
            raise ValueError("already in Deleted; purge() removes it for good")
        new_ref = self.move(ref, deleted_folder_for(folder))
        message = self.read(new_ref)
        message.deleted_from = folder
        self._rewrite(new_ref, message)
        return new_ref

    def restore(self, ref: str) -> str:
        """Put a deleted message back where it was deleted from.

        A message with no record of where it came from (an operator moved it
        into Deleted by hand) goes to the Inbox beside the Deleted folder.
        """
        folder = self._folder_of(ref)
        if not is_deleted_folder(folder):
            raise ValueError("only a message in Deleted can be restored")
        message = self.read(ref)
        try:
            target = check_folder(message.deleted_from) if message.deleted_from else ""
        except ValueError:
            target = ""
        if not target:
            target = "/".join([*folder.split("/")[:-1], INBOX])
        new_ref = self.move(ref, target)
        restored = self.read(new_ref)
        restored.deleted_from = ""
        self._rewrite(new_ref, restored)
        return new_ref

    def purge(self, ref: str) -> None:
        """Remove a message and its raw siblings for good. Deleted folders only."""
        if not is_deleted_folder(self._folder_of(ref)):
            raise ValueError("only a message in Deleted can be purged")
        path = self._path(ref)
        for sibling in self.raw_files(ref):
            sibling.unlink()
        path.unlink()
        self._touch_index(removed=(ref,))
