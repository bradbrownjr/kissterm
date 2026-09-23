# kissterm/mail — local contract

The message store for Mail, Bulletins and Files (ROADMAP P2). No UI, no
network, no transport: only files under one root (`config.mail_path()`).
Tests: `tests/unit/test_mail_store.py`, with `_isolate` and `tmp_path`.
`bpqmail.py` parses BPQMail replies; it is written from the real captures in
`tests/unit/data/bpqmail/` -- add a capture before changing a pattern.

- **The files are the truth.** One `.txt` per message (`message.py`);
  `.index.json` is a cache that `refresh()` rebuilds. Never store a fact only
  in the index.
- **Folders separate kinds of mail, never sources.** No folder per BBS or
  per route; a message's origin is its `Source:` header (`BBS WS1EC`), by
  the far end's callsign. Duplicate checks use Message-Id plus source.
- **Deleted is a folder.** `delete()` moves, `restore()` moves back, and only
  `purge()` from a Deleted folder removes a file.
- **Raw copies (`<stem>.b2f`) move with their message.** Never drop them.
- **Every path is checked** (`check_folder`, `MessageStore._path`); folder
  names can come from remote data (bulletin categories). Dotfiles and symlinks are skipped.
- Header values are one line; `format_message` strips CR/LF so a remote
  subject cannot forge a header.
- **A BBS read is filed only when its end marker arrived** (`BbsRead.complete`).
