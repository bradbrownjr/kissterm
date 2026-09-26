# Protocol guide: AX.25, KISS, APRS, NTS radiograms and message forms

This is the development baseline for frames that kissterm receives or puts on
the air. It exists because familiar-looking packet-radio terms hide different
layers, and a plausible assumption can create an interoperable-looking test
that fails against an actual TNC or a busy RF channel.

This guide is deliberately not a substitute for the specifications. Follow a
link below before changing a wire-format rule, and record the exact section or
example used in the code comment and test. A captured frame from real hardware
is evidence of interoperability, not evidence that it defines the protocol.

## The boundary between the protocols

```
application text / APRS data-type identifier
              │
       AX.25 UI or connected frame
              │
       HDLC radio frame and FCS
              │
  KISS escaping over serial, TCP, or RFCOMM
```

KISS is only a host-to-TNC framing protocol. It has ports and TNC commands,
but no callsigns, AX.25 state, ACKs, or APRS semantics. In KISS mode the TNC
normally adds/checks the HDLC FCS; kissterm's `AX25Frame.encode()` therefore
handles the address, control, PID, and information fields only. Do not add an
FCS to a KISS payload unless documenting a specific non-KISS backend that
requires it.

AX.25 has two distinct uses in this product:

- Connected mode is a balanced, acknowledged data-link session. `SABM`/`SABME`,
  `UA`, I frames, supervisory frames, sequence variables, and T1/T2/T3 belong
  here. `kissterm.ax25.session.AX25Link` owns it.
- APRS and ordinary beacons are unconnected AX.25 `UI` frames. They have no
  AX.25 connection and no AX.25 delivery guarantee. An APRS message's `ackNN`
  is an APRS application-level convention inside another UI frame, not an
  AX.25 acknowledgement.

Never put an `AX25Link` on a session-tier transport (VARA, kernel AX.25,
Telnet, SSH): that peer already supplies a connected byte stream, or has no
AX.25 on its wire at all. Conversely, a KISS/AGWPE raw-frame transport must
feed the local AX.25 state machine rather than pretend its byte stream is an
established session.

## Canonical sources and their status

| Scope | Source to use | Status in this project |
|---|---|---|
| AX.25 framing and connected mode | [AX.25 Link Access Protocol v2.2 (TAPR PDF)](https://web.tapr.org/tech_docs/AX25/AX25.2.2.pdf) | Normative baseline. Its SDL in Appendix C resolves text/diagram conflicts. |
| KISS escaping, type byte, and commands | [Chepponis/Karn, *The KISS TNC* (1987)](https://wiki.oarc.uk/_media/packet%3Acnc1987-kiss-tnc-k3mc-ka9q.pdf) | Normative baseline for ordinary KISS. Device extensions are backend-specific. |
| Core APRS formats | [APRS Protocol Reference 1.0.1 (2000)](https://www.aprs.org/doc/APRS101.PDF) | Baseline for on-air payload formats. |
| Approved APRS corrections and operating conventions | [APRS 1.1 Addendum](https://www.aprs.org/aprs11.html) | Part of the supported APRS baseline, including corrections to Mic-E and RF path guidance. |
| Later APRS ideas | [APRS 1.2 addendum proposals](https://www.aprs.org/aprs12.html) | Proposals and evolving material, **not** a blanket standard. Implement only a named, documented item with fixtures/captures. |
| Current symbol meanings | [APRS symbols](https://www.aprs.org/symbols.html) | Display-data source; preserve unknown symbols rather than guessing. |
| RF path stewardship | [New-N Paradigm](https://www.aprs.org/fix14439.html) | Operational guidance, not a reason for kissterm to digipeat. Local frequency plans still win. |

The APRS 1.1 page describes the 2004 addendum as approved and describes 1.2
as proposed. Do not label all of 1.2 "the APRS spec," or treat a web example as
permission to transmit a new extension. In particular, UTF-8 is listed as a
proposal; outgoing APRS payloads remain printable ASCII unless a supported
standard and compatibility policy are deliberately adopted.

## AX.25 facts that constrain changes

### Frame ownership

- A raw AX.25 frame begins with an address field, then a control field, then
  (where applicable) PID and information. KISS does not carry the HDLC flags
  or FCS.
- The destination/source C bits indicate command versus response only as a
  pair. A digipeater's same bit means “has been repeated.” Do not interpret a
  single `ch` bit without its address position.
- A path is an observed route, not an instruction for this client to relay.
  kissterm may originate a user-selected path, show used hops with `*`, and
  receive it; it must not digipeat, rewrite another station's path, or infer
  that an unused alias will be honoured locally.
- UI information normally carries PID `0xF0` for no layer 3. The APRS decoder
  must accept only `U/UI` + `0xF0`; a frame that fails that test is not a
  malformed APRS packet, it is simply not APRS.

### Connected-mode expectations

- Modulo 8 is the interoperable default. `SABM` selects it; `SABME` negotiates
  modulo 128. U frames remain one control octet while modulo-128 I/S control
  fields use two. The mode cannot safely be guessed from an arbitrary I frame.
- Sequence values are circular. Window checks and acknowledgement advancement
  must use the helpers in `ax25/window.py`, never integer ordering.
- T1 retransmits unacknowledged work, T2 deliberately delays a standalone
  acknowledgement so data can piggyback it, and T3 probes an idle link. Timer
  recovery is a recovery state, not an operator-visible link failure.
- Poll (`P=1`) needs a final (`F=1`) response. Unknown connected-mode traffic
  to this station needs `DM`, rather than a silent drop that burns the peer's
  retry budget.
- AX.25 2.2 is the source, but deployed stations are not uniform. Keep the
  project’s documented, test-backed interoperability deviation in
  `session.py` (resetting RC on forward acknowledgement progress) explicit;
  do not “make it spec-pure” without loss-loopback and hardware evidence.

## APRS facts that constrain changes

### What counts as APRS

APRS is an application convention inside `UI`/`0xF0`, not every unproto UI
frame. The first information byte is a data-type identifier. In this codebase,
the dispatch boundary is `kissterm.aprs.parse.parse_packet`; `None` means the
frame was not APRS, while `kind="unparsed"` means it claimed the APRS carrier
but its payload was malformed or unsupported. Preserve this distinction in
the monitor, heard list, and future statistics.

The AX.25 addresses also carry APRS meaning. A destination such as `APxxxx`
may identify software, while Mic-E overloads its destination callsign bytes
with position data. Do not normalize, replace, or validate away those six raw
Mic-E characters before `mice.py` sees them.

### Receive permissively; transmit conservatively

- RF is lossy and implementations are old. Parsing must be total: retain raw
  bytes and show an unparsed packet instead of letting a bad frame kill a
  subscriber.
- Transmit only fields that have an encoder, validation, and a source-backed
  test. Outgoing text is ASCII; reject/clean invalid input before it reaches a
  frame.
- Positions have separate uncompressed, compressed/base-91, and Mic-E forms.
  Position ambiguity is intentional information, not malformed coordinates.
  Preserve it instead of silently advertising a more precise location.
- The compressed `csT` fields carry multiple meanings. The `{` range form is
  a pre-calculated radio range, not altitude. Keep unimplemented T-byte
  semantics visible as unsupported rather than inventing a value.
- To verify that rare range form against real traffic without transmitting,
  run the capture-precalc-range CLI command. It uses the configured APRS
  position as a geographic receive filter, logs into APRS-IS with pass -1,
  and emits the first matching raw TNC2 line plus its decoded range. Preserve
  that raw line and capture time before turning it into a regression fixture.
- Mic-E's latitude/status data is split between destination address and
  payload. Any Mic-E edit requires independent fixtures: the official examples
  and a cross-check against a mature independent decoder or a real capture.
  Self-generated encoder/decoder pairs cannot validate each other.
- A third-party (`}`) payload has its own text header. Its inner source/path
  are not necessarily legal AX.25 addresses, so retain their original text
  for display and do not use a synthetic `NOCALL` as the correspondent
  identity.

### Messages, paths, and channel etiquette

- The addressee field is exactly nine characters, space padded on air. Message
  numbers are application-level correlation identifiers; `ack`/`rej` are not
  ordinary chat lines. Keep retries bounded and never let an unattended retry
  reopen the transmit gate.
- A station must transmit under its configured source identity. A received
  addressee is not permission to forge that identity in an ack. Matching an
  incoming message to the active identity is a separate receive-policy choice;
  kissterm defaults to exact callsign+SSID matching.
- `WIDE1-1,WIDE2-1` is not a universal entitlement. New-N guidance deprecated
  `RELAY`, old `WIDE`, and `TRACE`, and generally limits `WIDEn-N` to two hops;
  local coordinators may require direct operation, a shorter path, or another
  path. Keep path selection explicit and configurable, never silently expand
  it or use traffic to discover what works.
- APRS position beacons, ordinary BTEXT beacons, and APRS messages are three
  different transmit intents. Each has its own destination, scheduling, and
  social cost. A UI convenience must not blend them or create a new automatic
  transmitter.

## Change checklist

Before merging a protocol-related change:

1. State the layer and frame type: KISS transport, AX.25 connected, AX.25 UI,
   or APRS payload. If that answer is unclear, stop before changing code.
2. Add a source URL and section/page or a labelled `# RESEARCH:`/`# UNVERIFIED:`
   note. Do not promote an inference to fact because another client accepts it.
3. Add a fixture made from independently sourced bytes, a published example,
   or a consented real capture. Keep the existing generated fixtures too, but
   label them as self-consistency tests.
4. For AX.25 connection changes, run the link/window suites and a lossy
   loopback case. For APRS parser changes, test malformed input returns
   `unparsed` without raising. For outbound APRS, assert the exact UI/PID/path
   bytes and that a UI selection alone cannot send it.
5. Check airtime and unattended behaviour: no polling/probing, no implicit
   digipeating, no automatic transmit-gate arming, no message retry that sends
   after the gate closes.
6. Record an interoperability observation separately from the normative rule:
   peer software/version, transport, mode/path, raw frame (with any sensitive
   content redacted), and whether it was RF or synthetic.

## NTS radiograms: sources and precedence

`kissterm/mail/nts.py` formats ARRL radiograms sent to a BBS as `ST <zip> @
NTS<state>`. The sources disagree in places, so they are ranked: a newer
RRI/NTS document wins over the 2002 ARRL guide, and a point a working
traffic handler reviewed wins over an unreviewed one. Cite the section or
example used in the code comment and test, as for the protocols above.

| Scope | Source to use | Status in this project |
|---|---|---|
| Radiogram layout and punctuation today | [RRI/NTS 2.0, *Guidelines for Origination, Relay and Delivery of Radiogram-ICS213 Messages*, final 27 Feb 2026](https://nts2.arrl.org/wp-content/uploads/2026/04/Guidelines-for-Origination-Relay-and-Delivery-of-Radiogram-ICS213-Messages-F-A.pdf) | First authority. BT separators, five groups a line, QUERY, spelled-out COMMA, `ATSIGN` in email. |
| Sample RRI radiogram | [RRI, *Certified Radiogram Implementation*](https://radiorelay.org/certified-radiogram-implementation/) | Supporting example: BT separators, phone as digit groups with no TEL. |
| Preamble, address, text and check rules | [ARRL NTS MPG chapter 1, *The ARRL Message Format* (v1.04, 2002)](https://www.arrl.org/files/file/Public%20Service/MPG104A.pdf) | Baseline where RRI 2026 is silent. Section numbers are cited in `nts.py`. |
| Packet BBS upload (`ST`, title, body) | [ARRL NTS MPG chapter 6, *NTS Digital*, 6.2.1 (2002)](https://www.arrl.org/files/file/Public%20Service/MPG604A.pdf) | `ST` routing, the 30-character title limit and `NR` before the number. Its blank-line separators and `QTC` title are superseded (see below). |
| ARL numbered texts | [ARL Numbered Radiogram Texts v3.0, 7 Oct 2025](https://nts2.arrl.org/numbered-texts/) ([RRI copy](https://radiorelay.org/files/reference/ARL_Numbered_Radiogram_Texts.pdf)) | Shipped as `kissterm/mail/data/arl_numbered.json`. Check counts groups "as originated". |
| Review by a traffic handler | [Jim Kutsch KY2D's review of the bpq-apps form (commit `ef6612c`, forms v1.28, 25 May 2026)](https://github.com/bradbrownjr/bpq-apps/commit/ef6612c) | Two BTs and no AR, no `TO:`, call after the name, `#` as NR, and the BBS title `CITY CALLSIGN` / `CITY NXX NXX` / `CITY - -`. |
| Packet NTS how-to (2006) | [Outpost, *Introduction to the National Traffic System for Packet*, rev 1.4](https://outpostpm.org/docs/NTS-14.pdf) | Supporting: BT separators and five words a line. Its `QTC 1 R CITY ST (NXX-NXX)` title is one of several conventions. |
| Section packet procedures | [Eastern Massachusetts ARRL, *Packet Procedures*](https://ema.arrl.org/packet-procedures/) | Supporting: `ST <zip> @ NTS<st>`; titles like `CHICAGO 312-267`. |
| TPRFN radiogram generator | [TPRFN / RRI Radiogram Generator](https://www.tprfn.net/radiogram-form) (named in the [PKTNET May 2026 instructions](http://vden.org/docs/PacketBulletinNet-May2026.pdf), coordinated with KY2D) | Supporting the KY2D title: it titles traffic `CITY CALL`. Its preamble has no `NR`, like RRI 2026's sample; kissterm keeps `NR` (MPG 6.2.1) pending the operator's call. |

**Not a source:** the Winlink `fixpunct()` rules that bpq-apps' `forms.py`
copied (INT for a question mark, comma to X, a check counted per five
digits). RRI 2026 contradicts them.

**Open:** the BBS title. The guides above disagree and RRI publishes none;
kissterm uses KY2D's, marked `# UNVERIFIED` in `nts.py` until an `LT`
listing on a BBS carrying NTS traffic shows what stations actually use
(`docs/ON-AIR-TESTS.md`).

## Message forms: sources

`kissterm/mail/forms.py` renders each form in `kissterm/mail/data/forms/`
to the text its readers expect. Each file's `source` names the template
and version it was transcribed from; the reasons for the few deliberate
differences are in `forms.py`'s docstring.

| Scope | Source to use | Status in this project |
|---|---|---|
| Winlink standard form layouts (body text, subject, field names and limits) | Winlink Standard Forms 1.1.20.0, as mirrored for the Pat client: [version](https://api.getpat.io/v1/forms/standard-templates/latest), [archive](https://api.getpat.io/v1/forms/standard-templates/Standard_Forms_1.1.20.0.zip) (winlink.org's own download sits behind a browser check) | First authority for layout. Each form's `.txt` template gives the body and subject; its `_Initial.html` gives field names, limits and required fields. Read by a developer and transcribed; never fetched by kissterm. |
| Winlink template catalogue | [Winlink Templates in Standard Library](https://winlink.org/sites/default/files/download/winlink_templates_in_standard_library_version_1.0.119.pdf) | Which forms exist and are common. |
| ICS 213 General Message | [FEMA ICS 213 v3](https://training.fema.gov/emiweb/is/icsresource/assets/ics%20forms/ics%20form%20213,%20general%20message%20(v3).pdf) | Block numbering and meaning. Blocks 9-10 are the recipient's. |
| ICS 213 RR Resource Request | [FEMA ICS 213 RR v3](https://training.fema.gov/emiweb/is/icsresource/assets/ics%20forms/ics%20form%20213rr,%20resource%20request%20message%20(v3).pdf) | Block numbering. Blocks 10-19 are Logistics' and Finance's. |
| PKTNET forms | vden.org PKTNET forms, local copy in the sibling `pktnet` directory (v1.1, 2023-11); [live](https://vden.org/pktnet/) | The PKTNET check-in body (`check_in.html`). Its ICS-213 uses the paper form's labels; Winlink's layout is used instead. |
| PKTNET addressing | [Packet Bulletin Net announcement, May 2026](http://vden.org/docs/PacketBulletinNet-May2026.pdf) | `SB PKTNET@USA`, subject "Your Name, Your Call, Your Town, Your State". |
| Information strips | bpq-apps `apps/forms/` (same author): `strip.frm`, `gyx-weather.frm` v1.1, `mcf720-price-survey.frm` v1.0 and the README's ROSTER example | The only source found. No published MARS/SHARES strip specification was found; the empty answer as three spaces is bpq-apps' "MARS convention" and is marked `# UNVERIFIED` in `forms.py`. MCF is a JS8Call form family and does not apply. |
| A working ICS-213 over BPQ | [BPQ-Alt-Webmail v1.8.0](https://github.com/jayflanzbaum-svg/BPQ-Alt-Webmail/releases/tag/v1.8.0) | Supporting: another BPQ client sends Winlink's ICS-213 text without the XML, for the same reason (G8BPQ: binary attachments are not readable on the BBS). |

## Current boundaries and known gaps

The supported baseline is deliberately smaller than the full specifications:

- kissterm is a terminal, not a digipeater, node, or igate. Receiving or
  decoding a packet does not authorize forwarding it.
- The APRS decoder supports the common position, Mic-E, message, status,
  object/item, weather, telemetry, capability, query, and third-party forms.
  Unsupported valid formats should remain visible as `unparsed` until sourced
  and tested, not be guessed from a similar format.
- APRS-IS has no single protocol specification in the APRS 1.2 material and
  is outside the current transport scope. Do not reuse its `q` constructs or
  internet relay behavior as an RF rule.
- Modulo-128 fallback and compressed-position range behavior need further
  live verification; they are tracked in `docs/ROADMAP.md`. Treat the current
  implementation as test-covered, not universally field-proven.

When a future observation conflicts with this guide, keep the raw evidence,
consult the primary source, and update this guide plus the relevant test. The
right outcome may be a documented interoperability exception, but it must not
be an undocumented new assumption.
