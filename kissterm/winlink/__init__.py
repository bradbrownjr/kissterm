"""Winlink over a packet route: the B2F exchange a Winlink RMS speaks
(ROADMAP P2, "Winlink account").

No UI and no transport here, like `mail/`: these modules turn bytes into
messages and back, and the app drives them over a link it has already
connected (an Address Book route to the RMS; the exchange starts when the
gateway's `[WL2K-...]` line arrives).

- `secure.py`: the answer to the CMS's `;PQ:` password challenge.
- `lzhuf.py`: the LZHUF compression every B2 message travels in.

**Sources.** The protocol is documented by its implementations, not by a
published specification: wl2k-go (Martin Hebnes Pedersen LA5NTA, MIT
licence, github.com/la5nta/wl2k-go, the library behind Pat) and
paclink-unix, whose secure login wl2k-go ported, and JNOS 2's `lzhuf.c`,
which wl2k-go's LZHUF came from. Each module cites what it follows, and
marks anything not yet seen on air `# UNVERIFIED:`.
"""
