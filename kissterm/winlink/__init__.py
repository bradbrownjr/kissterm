"""Winlink over a packet route: the B2F exchange a Winlink RMS speaks
(ROADMAP P2, "Winlink account").

No UI and no transport here, like `mail/`: these modules turn bytes into
messages and back, and the app drives them over a link it has already
connected (an Address Book route to the RMS; the exchange starts when the
gateway's `[WL2K-...]` line arrives).

- `secure.py`: the answer to the CMS's `;PQ:` password challenge.
- `lzhuf.py`: the LZHUF compression every B2 message travels in.
- `message.py`: one message in B2 format (headers, body, attachments), MIDs.
- `b2f.py`: the exchange itself, as a client, bytes in and bytes out.
- `gateways.py`: the RMS gateway list, nearest first. The one module here
  that does I/O: an HTTPS request to winlink.org, only when asked, never
  over the air.

**Sources.** The protocol is documented by its implementations, not by a
published specification: wl2k-go (Martin Hebnes Pedersen LA5NTA, MIT
licence, github.com/la5nta/wl2k-go, the library behind Pat) and
paclink-unix, whose secure login wl2k-go ported, and JNOS 2's `lzhuf.c`,
which wl2k-go's LZHUF came from. Each module cites what it follows, and
marks anything not yet seen on air `# UNVERIFIED:`.
"""
