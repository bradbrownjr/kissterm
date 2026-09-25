# kissterm/mail — local contract

The message store for Mail, Bulletins and Files (ROADMAP P2). No UI and no
transport: files under one root (`config.mail_path()`), plus `collect.py`,
which drives a BBS over a link the app has already connected.
Tests: `tests/unit/test_mail_store.py`, with `_isolate` and `tmp_path`.
`bpqmail.py` parses BPQMail replies. **Research first, then verify**: read
what LinBPQ's source says (`g8bpq/linbpq`, `BBSUtilities.c`; the
`bpqmail.py` docstring cites it), then confirm against a real capture in
`tests/unit/data/bpqmail/` before a pattern ships. A detail with only one
of the two is marked `# UNVERIFIED:`.

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
- **`collect.py` never sends `K`**, reads only messages the store lacks
  (`has_bbs_number` before the read, `find` by BID after), and stops by
  name on anything it does not recognise. Tests use a scripted BBS built
  from the captures (`tests/unit/test_mail_collect.py`).
