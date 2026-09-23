"""A glossary of packet-radio terminology, for the operator who knows radio
but not packet -- the audience `README.md` already writes for.

Deliberately a hardcoded Python tuple, not a TOML file under a `data/`
directory the way `kissterm/nodes/` and `kissterm/aprs_services/` are. Those
exist as data because they are genuinely per-thing content an operator or a
future session adds to piecemeal (one file per node family, one per
gateway service) and might want to hand-edit without touching code. A
glossary is neither: it is one fixed list that changes at the same rate as
the terms this protocol uses, which is to say almost never, and inventing a
loader and a schema for that would be solving a problem this module does not
have. `kissterm/ui/themes.py`'s `THEME_CATALOG` is the same call for the
same reason.

No I/O. Read `kissterm/nodes/reference.py`'s module docstring for the
sibling case this is modelled on -- `CommandReferenceScreen` searches both
from the same pane, per `docs/ROADMAP.md`'s own instruction that a glossary
belongs "searchable in the same pane as commands" rather than behind a
second binding.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Term:
    name: str
    definition: str


#: Ordered roughly by how often a new operator hits the term, not
#: alphabetically -- the search box makes alphabetical order pointless
#: anyway, and an operator paging through with no query yet sees the
#: highest-value entries first.
TERMS: tuple[Term, ...] = (
    Term("TNC", "Terminal Node Controller. Turns audio on a radio channel "
         "into packets and back -- the hardware (or software, for a "
         "soundcard modem) kissterm's KISS transports talk to."),
    Term("KISS", "Keep It Simple, Stupid. The framing protocol a TNC uses to "
         "hand raw AX.25 frames to a computer over serial, TCP or "
         "Bluetooth, with no interpretation of what is inside them."),
    Term("AX.25", "The link-layer protocol packet radio runs on: addressing, "
         "framing, and -- in connected mode -- the acknowledgement and "
         "retransmission rules kissterm runs itself, which is why it needs "
         "no special operating-system support."),
    Term("Connected mode", "An AX.25 session with sequence numbers, "
         "acknowledgement and retransmission, the same idea as a TCP "
         "connection. What kissterm's terminal pane holds open with a "
         "node or another station -- as opposed to unproto traffic, which "
         "is fire-and-forget."),
    Term("Unproto", "Unconnected, unacknowledged AX.25 traffic (a UI frame): "
         "sent once, to no one in particular, with no retry if it is "
         "missed. Beacons and APRS both ride on unproto; a keyboard "
         "conversation does not."),
    Term("Callsign-SSID", "A station's identity on the air is its amateur "
         "radio callsign plus a Secondary Station Identifier, 0-15, "
         "written W1AW-7. One callsign can run several independent "
         "AX.25 services -- a BBS on -1, a chat port on -2 -- each its "
         "own SSID, distinguishable only by that suffix."),
    Term("SSID", "See Callsign-SSID -- the -7 half of W1AW-7."),
    Term("Digipeater", "A station that repeats a frame addressed through it, "
         "named in the AX.25 path (W1AW via K1ABC). Extends range without "
         "running a full node; APRS's WIDE1-1/WIDE2-1 paths are the "
         "most common use."),
    Term("Node / NET/ROM", "A packet station that itself offers connections "
         "onward to other stations or services -- typing C W1AW at one "
         "node's prompt to reach another over RF, rather than dialing "
         "W1AW directly. NET/ROM is one such routing protocol; BPQ32, "
         "TheNet and KA-Node are node software families kissterm can talk "
         "to. kissterm connects to nodes; it is not one."),
    Term("BBS / Mailbox", "A store-and-forward message system reached over "
         "packet -- read bulletins, leave and collect personal mail. "
         "kissterm is a terminal to one, not a BBS itself."),
    Term("RMS / Winlink", "Radio Mail Server: a gateway that relays email "
         "over packet or HF to the Winlink network. A specific kind of "
         "mailbox service, reached the same way as any other node."),
    Term("Paclen", "The maximum size, in bytes, of one AX.25 I frame's "
         "payload. Short on a noisy HF path (less to have to retransmit "
         "per lost frame); long on a clean, fast local link (less "
         "per-frame overhead)."),
    Term("Window (k)", "How many I frames a station may send before it must "
         "stop and wait for an acknowledgement. A bigger window uses a marginal "
         "channel's airtime more efficiently when it works, and wastes "
         "more of it retransmitting when it does not."),
    Term("Modulo 8 / 128", "How far AX.25 sequence numbers count before "
         "wrapping back to zero -- 8 is what almost every TNC on the air "
         "speaks (SABM); 128 (SABME) allows a much bigger window but is "
         "rarely implemented on the other end. Set in Settings; leave it "
         "at 8 unless you know the far station speaks 128."),
    Term("T1 / T2 / T3", "AX.25's three link timers. T1: \"I sent something "
         "and have not been acknowledged\" -- drives retransmission. T2: "
         "\"wait briefly before acknowledging\", so a reply can piggyback "
         "the ack instead of spending a separate frame on it. T3: \"this "
         "link has been idle -- is it still there?\""),
    Term("SABM / SABME", "Set Asynchronous Balanced Mode (Extended): the "
         "AX.25 frame that opens a connection, modulo 8 or 128 "
         "respectively. A station that does not understand SABME answers "
         "DM; kissterm falls back to plain SABM automatically."),
    Term("DM", "Disconnected Mode: an AX.25 station's answer when it hears "
         "a connect attempt (or any traffic) addressed to it but has no "
         "session for that peer, or refuses one. A DM is the far end "
         "actively saying no -- silence is a different problem, usually "
         "the RF path itself."),
    Term("PID", "Protocol ID: one byte in an AX.25 I or UI frame naming what "
         "kind of payload follows -- plain text, NET/ROM routing, or (for "
         "APRS) 0xF0, \"no layer 3\"."),
    Term("Half-duplex", "Only one station on a channel can transmit at a "
         "time and hear the other while doing it -- the normal case for a "
         "packet or voice repeater. Everything in kissterm about airtime "
         "cost (T2, paclen, why command references ship instead of being "
         "asked for) exists because of this constraint."),
    Term("AFSK", "Audio Frequency-Shift Keying: how packet data is encoded "
         "as two audio tones fed into an FM transmitter, the usual "
         "modulation for 1200-baud VHF/UHF packet."),
    Term("Baud", "Signalling rate -- how fast the modem's own symbols "
         "change, not quite the same thing as bits per second, though at "
         "1200-baud AFSK packet they are equal in practice."),
    Term("Frame", "One complete AX.25 unit on the air: address field, "
         "control field, optional PID and payload, and a trailing checksum "
         "(FCS), bounded by flag bytes. The unit the Monitor tab shows, "
         "one per line."),
    Term("FCS", "Frame Check Sequence: the CRC at the end of an AX.25 frame "
         "that lets the receiver detect a frame corrupted in transit. A "
         "failed FCS means the frame is silently dropped, not corrected."),
    Term("Path / Via", "The list of digipeaters a frame is repeated "
         "through, written DEST via DIGI1,DIGI2 -- type it that way in the "
         "Connect dialog. Not the same as Node hops in the Address Book: a "
         "digipeater only repeats frames, while a node hop connects to a "
         "node and then asks it to connect onward."),
    Term("IGate", "Internet Gateway: a station that relays APRS traffic "
         "between RF and the internet APRS-IS network. kissterm is not one "
         "and does not relay traffic, though it can watch APRS-IS for "
         "messages to or from you."),
    Term("APRS", "Automatic Packet Reporting System: position, weather and "
         "short-message traffic riding on unproto UI frames, shown on the "
         "APRS tab. Not the same thing as a plain-text beacon (see Beacon)."),
    Term("Mic-E", "A compact, binary-packed APRS position format -- the "
         "most common one on 2 meters, encoded into what looks like a "
         "callsign-shaped destination field. kissterm's Mic-E decoding has "
         "not yet been checked against real off-air traffic, so treat an "
         "odd-looking Mic-E position with suspicion."),
    Term("Beacon (BTEXT)", "An unproto text transmission sent on a timer to "
         "announce a station is on frequency -- free text, not a position. "
         "Not the same as an APRS position beacon: they have separate "
         "settings, and turning on one does not turn on the other."),
)


def search(needle: str) -> tuple[Term, ...]:
    """Free-text search across name and definition. An empty query returns
    every term -- unlike `nodes.reference.CommandReference.complete`, this is
    a browsable reference, not a live autocomplete source, so there is no
    "the whole list is noise" case to guard against."""
    text = needle.strip().lower()
    if not text:
        return TERMS
    return tuple(
        t for t in TERMS if text in t.name.lower() or text in t.definition.lower()
    )
