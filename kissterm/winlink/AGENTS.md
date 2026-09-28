# kissterm/winlink — local contract

Winlink's B2F exchange as pure code: bytes in, messages out. No UI, no
transport, no I/O; the app drives it over a link it already connected.
Tests: `tests/unit/test_winlink_*.py`, against wl2k-go's vectors and test
data in `tests/unit/data/winlink/`.

- **Winlink's own documents come first** (Open B2F and Data Flow, in
  `docs/PROTOCOL_GUIDE.md`, "Winlink B2F", with where they disagree with
  wl2k-go and the wire).
- **Port from wl2k-go (MIT, LA5NTA) and cite it**; the README credits it.
  Behaviour seen only in its code, not yet in a live exchange with an RMS,
  is marked `# UNVERIFIED:`.
- **A message is filed whole or not at all**: `lzhuf.decompress` raises on
  a bad CRC or a short stream, never returns part of one.
- **The password never goes on the air**; only `secure.login_response`'s
  eight digits do. It comes from the keyring (`kissterm/keystore.py`).
- **Tests never talk to winlink.org**; a CMS session is operator-initiated.
