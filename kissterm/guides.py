"""Built-in guides: short how-tos shown on the Help tab (F1 > Guides).

Written for the operator the rest of this app writes for -- licensed, knows
radio, new to packet. The commonest first-night failures are not faults in
anything: the soundmodem was never started, transmit is off, or a connect
failed and nobody told them which end to look at. A guide that answers that
inside the program is read; one on a website is not.

A hardcoded tuple, not files under a `data/` directory, for the same reason
`kissterm/glossary.py` is: one fixed list that changes when the program
does, with no reason to be hand-edited by an operator. Each body is Markdown,
rendered by Textual's `Markdown` widget in `kissterm/ui/help_pane.py`.

**A guide names a key only through `{key:action}`**, which `render()`
replaces with the key the command registry actually binds. Typing "Ctrl+N"
into prose is how README's key table went stale; a placeholder cannot. An
unknown action raises, and `tests/unit/test_guides.py` renders every guide,
so a renamed command fails a test instead of printing a stale key.

No I/O. Every claim in here is about behaviour this codebase has; when that
behaviour changes, the guide changes in the same commit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Guide:
    title: str
    #: One line for the guide list: what question this answers.
    summary: str
    #: Markdown, with `{key:action}` placeholders for keys.
    body: str


#: Ordered by when a new operator needs each one, first night first.
GUIDES: tuple[Guide, ...] = (
    Guide(
        "Getting on the air",
        "From a fresh install to your first connection.",
        """\
kissterm is a terminal. It does not make packets itself: a **TNC** does,
either a hardware box or a **soundmodem** program such as Direwolf or the
UZ7HO soundmodem that turns your computer's sound card into one. kissterm
talks to the TNC, and the TNC talks to the radio.

1. **Start the modem first.** If you use a soundmodem, start that program
   and leave it running. If you use a hardware TNC, plug it in and power it
   on. kissterm cannot start either for you.
2. **Tell kissterm where the TNC is.** Open {key:show_tab('settings')}
   Settings, then Transports. *Scan for hardware* looks for TNCs on serial
   ports and your local network; *New* lets you type one in. A soundmodem is
   usually KISS over TCP on port 8001, or AGWPE on port 8000.
3. **Set your callsign** in Settings if you have not already, and press
   Save.
4. **Turn transmit on when you mean to.** kissterm starts with transmit
   OFF. Connecting or sending a message turns it on for you; see the
   *Transmit switch* guide.
5. **Connect.** Press {key:connect} and type a node or BBS callsign, such as
   `W1AW-7`. See *Your first connection*.

If kissterm could not reach the TNC at startup, it offers to open anyway on
the Transports page. Start the modem, then press Save there to try again.
""",
    ),
    Guide(
        "Your first connection",
        "Connecting to a node or BBS, and leaving politely.",
        """\
Press {key:connect}, type the station's callsign **including its SSID**, and
press Enter. `W1AW-7` and `W1AW-1` are different services on the same
machine, often a node and a BBS; the wrong SSID fails exactly like a bad
radio path.

To reach a station you cannot hear directly, go through a digipeater:
`W1AW-7 via K1ABC-1`.

Once connected, the node usually sends a banner and a prompt. Type a command
in the line at the bottom and press Enter to send it. **Nothing is sent
until you press Enter or click Send.**

- **Do not ask a node for its help list just to learn it.** On a 1200-baud
  channel a long help text can take a minute of airtime, during which nobody
  else on the frequency can transmit. Press {key:command_reference} instead:
  kissterm ships the command lists of the common node types, and picking one
  fills in the send line without sending.
- **As you type,** matching commands appear under the send line. Up and Down
  choose, Tab fills in, and Enter still decides what is sent.
- **To leave,** type the node's own bye command (often `B` or `BYE`), or
  press {key:disconnect}. A clean disconnect frees the node straight away;
  just closing the program leaves it waiting for its own timers.
""",
    ),
    Guide(
        "The transmit switch",
        "Why transmit starts off, and what turns it on.",
        """\
The status bar shows whether transmit is on. It starts **off** every time
kissterm opens, and nothing keys your radio while it is off: not a beacon,
not answering an incoming call, not a message.

{key:toggle_transmit} turns it on or off by hand. You rarely need to, because
**anything you ask for by name turns it on for you**: connecting to a
station, sending a line in the terminal, sending an APRS message,
disconnecting, or APRS > Send position. Each time that happens, kissterm
says so in the terminal and in a notification.

What never turns it on: a beacon timer, an automatic retry of an unanswered
APRS message, or a station calling you. Those happen with nobody at the
keyboard, so they wait until you have turned transmit on yourself.

If an APRS message arrives while transmit is off, kissterm cannot send the
acknowledgement, and it tells you so. The sender will keep retrying until
you turn transmit on.
""",
    ),
    Guide(
        "When a connection fails",
        "Reading the failure, so you check the right end.",
        """\
Open {key:show_tab('monitor')} Monitor: it shows every frame in both
directions. What you see there tells you where the problem is.

- **The status bar says DOWN or RECONNECTING.** kissterm cannot reach the
  TNC itself. This is not a radio problem. Check that the modem program is
  running and that the address in Settings > Transports is right.
- **Your connect requests go out, and nothing comes back.** The far station
  did not hear you, or you did not hear it. Check the frequency, antenna,
  power and audio levels, or try a digipeater.
- **A DM comes back.** The far station heard you and refused. Check the
  callsign and SSID; the service may be down or busy.
- **Connected, but the node never answers what you type.** If the monitor
  shows your line acknowledged, the radio side worked; the node's own
  software is slow or stuck. Wait, or disconnect and try again later.

Monitor shows frames that went out, not only frames that came in. If a
frame is missing there, it never left your station.
""",
    ),
    Guide(
        "APRS messaging",
        "Sending messages, and using gateways for SMS, email and weather.",
        """\
Open {key:show_tab('aprs')} APRS. Put a callsign in **To**, type the
message, and press Enter. Each person you exchange messages with gets their
own tab; **All** shows every APRS packet heard.

A message is retried until the other station acknowledges it. Its line
shows whether it was acknowledged, is still being retried, or gave up.

**Gateways** are services with an APRS callsign that relay to the outside
world: text messages, email, weather reports and more. Press
{key:command_reference} on the APRS tab to pick one. It fills in the address
and the message format for you, and sends nothing until you press Enter.
Some gateways act as soon as a message arrives, sending a real text message
or posting a public spot, so read what you are sending.

Messages are answered only when they are addressed to your exact callsign
and SSID. APRS > SSID filter in the {key:menu} menu turns that off, if you
want this station to answer for every SSID of your call.
""",
    ),
    Guide(
        "Sharing the channel",
        "Habits that keep a packet frequency usable for everyone.",
        """\
Packet radio is a shared, half-duplex channel: while anyone transmits,
everyone else waits. At 1200 baud, 2 KB of text is about 19 seconds of
airtime.

- **Do not download long lists just to look at them.** Use
  {key:command_reference} for command lists; kissterm ships them so you do
  not have to ask the node.
- **Beacon rarely.** kissterm will not beacon more often than every ten
  minutes, and it never beacons an empty message.
- **Disconnect when you are done** rather than leaving a node holding your
  session open.
- **Answering calls is off by default.** Turning it on (Settings) means your
  station transmits under your callsign when someone calls it, even if you
  are away. The status bar shows ANSWERING for as long as it is on.
""",
    ),
)

_KEY_PLACEHOLDER = re.compile(r"\{key:([^}]+)\}")


def render(guide: Guide) -> str:
    """The guide's Markdown with every `{key:action}` replaced by the key the
    registry binds to that action, in bold. Raises `KeyError` for an action
    the registry does not know or does not bind, so a stale guide fails."""
    from .ui import commands

    def key_for(match: re.Match[str]) -> str:
        action = match.group(1)
        found = [c for c in commands.COMMANDS if c.action == action and c.key]
        if not found:
            raise KeyError(f"guide {guide.title!r} names unbound action {action!r}")
        return f"**{commands.key_label(found[0].key, short=False)}**"

    return _KEY_PLACEHOLDER.sub(key_for, guide.body)
