"""ARRL radiograms for the National Traffic System, sent as BPQMail `ST`.

ROADMAP P2 step 4. Nothing here does I/O or transmits: it turns what an
operator typed into a correctly formatted radiogram, its check, the BBS
subject and the `ST` routing, and says what is wrong before anything is
saved.

**Sources, researched before building (AGENTS.md section 7)**, with links
and their order of precedence in `docs/PROTOCOL_GUIDE.md` ("NTS
radiograms"):

- ARRL NTS Methods and Practices Guidelines, chapter 1, "The ARRL Message
  Format" (MPG v1.04, 5/02): the preamble (1.1), the address (1.2), text
  punctuation (1.3.1), ARL numbered radiograms (1.3.3) and the check
  (1.3.4). Section numbers are cited in the code below.
- The same MPG, chapter 6, "NTS Digital", 6.2.1: the packet upload -- the
  `ST 99999 @ NTSCA` line, the `QTC <town> / <area code> <exchange>`
  subject (30 characters at most), a preamble starting `NR`, no blank line
  between preamble and address, a blank line before and after the text,
  and five words per text line.
- RRI / ARRL NTS 2.0, "Guidelines for Origination, Relay and Delivery of
  Radiogram-ICS213 Messages", final-approved 27 Feb 2026
  (nts2.arrl.org). The current word where it and the 2002 MPG differ:
  BT separates the address from the text and the text from the signature
  (the MPG's packet example used blank lines); an email address is
  `... ATSIGN ...`; a question mark is QUERY and other punctuation is
  spelled out (COMMA), confirming MPG 1.3.1; five groups to a text line.
- Jim Kutsch KY2D's review of the bpq-apps radiogram form (bpq-apps
  commit ef6612c, forms v1.28, 2026-05-25): two BTs and no AR, no `TO:`,
  call sign after the name with no comma, `#` in an address as NR, and
  the BBS title `CITY CALLSIGN` / `CITY NXX NXX` / `CITY - -`. Sources
  for the title disagree -- MPG 6.2.1 has `QTC TOWN / NXX NXX`, the
  Outpost "NTS for Packet" guide (rev 1.4, 2006) `QTC 1 R CITY ST
  (NXX-NXX)` -- and none is from RRI, so the one a working traffic
  handler checked is used. TPRFN's radiogram generator, which the PKTNET
  net's May 2026 instructions name and which was set up with KY2D
  (tprfn.net/radiogram-form, read 2026-09-26), titles traffic `CITY
  CALL` too. It and RRI's 2026 sample also leave `NR` off the preamble,
  which MPG 6.2.1 has; kissterm keeps `NR` until the operator decides.
  # UNVERIFIED: the title against a live NTS listing (`LT` on a BBS
  # carrying NTS traffic); nothing in the captures shows one yet.
- ARL Numbered Radiogram Texts, final-approved version 3.0, 2025-10-07
  (ARRL/RRI, nts2.arrl.org/numbered-texts), shipped as
  `data/arl_numbered.json`. Its instruction 1: the check counts the groups
  "as originated, NOT as translated".

**Where this differs from bpq-apps' `forms.py`**, which it was ported from
(same author, CC0). `forms.py` copied Winlink's `fixpunct()` for the text;
these are the points where the MPG and the 2026 RRI guidelines say
otherwise, none of them part of KY2D's review:

- The check is the number of groups, whatever their length (1.3.4: "each
  ... group of connected digits ... constitutes one group"). `forms.py`
  counted a long digit string as one group per five digits.
- A question mark is QUERY (1.3.1), not INT; other punctuation is spelled
  out (COMMA, DASH, COLON) rather than turned into X, which is the period
  only (1.3.1). "/" stays inside a group (1.3.1); a decimal point between
  digits is R (1.3.1), a colon or slash between digits is not.
- EMERGENCY is always spelled out in the preamble (1.1.2); the day has no
  leading zero (1.1.9); a time filed carries its zone, "1830Z" (1.1.7).
- The telephone line is the digit groups alone, no TEL prefix (1.2.4).

The preview in the form shows the encoded text as it will be sent, so an
encoding the operator does not want is seen and rewritten before saving.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from typing import Iterable

#: (value, label). EMERGENCY is always spelled out (MPG 1.1.2).
PRECEDENCES = (
    ("R", "Routine"),
    ("W", "Welfare"),
    ("P", "Priority"),
    ("EMERGENCY", "Emergency"),
)

#: Handling instructions, ARRL FSD-218 (MPG 1.1.3).
HX_CODES = (
    ("HXA", "Collect landline delivery authorized within n miles (HXA50)"),
    ("HXB", "Cancel if not delivered within n hours of filing (HXB12)"),
    ("HXC", "Report date and time of delivery to the originating station"),
    ("HXD", "Report the relay chain and delivery to the originating station"),
    ("HXE", "Delivering station get a reply from the addressee"),
    ("HXF", "Hold delivery until date n (HXF25)"),
    ("HXG", "No toll call or mail delivery; cancel and service if needed"),
)

#: USPS state and territory codes: the NTS routing is `NTS` + one of these.
# UNVERIFIED: Canadian traffic. NTS serves Canada too, but no source
# consulted here gives its `@ NTSxx` routing, so provinces are refused
# rather than guessed.
STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
    "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA "
    "WV WI WY PR VI GU AS MP".split()
)

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

#: The most text groups a message should carry (MPG 1.3: "usually limited
#: to 25 words or less"). More is allowed, with a warning.
USUAL_MAX_GROUPS = 25

#: The BBS subject limit for NTS traffic (MPG 6.2.1).
MAX_SUBJECT = 30

#: Spelled-out punctuation (MPG 1.3.1: X for a period; "other punctuation
#: is spelled out ... QUERY ... DASH ... EXCLAMATION, COMMA"). `&` and `@`
#: become AND and AT (1.3.2 allows AT for ATSIGN).
_SPELLED = {
    ".": "X",
    "?": "QUERY",
    "!": "EXCLAMATION",
    ",": "COMMA",
    ":": "COLON",
    ";": "SEMICOLON",
    "-": "DASH",
    "&": "AND",
    "@": "AT",
}

_ONES = ("", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
         "TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN",
         "SEVENTEEN", "EIGHTEEN", "NINETEEN")
_TENS = ("", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HX_RE = re.compile(r"^HX[A-G]+\d*$")
_CALL_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}[A-Z]$")


def number_words(n: int) -> str:
    """1-99 as ARL numbers are written: `46` -> `FORTY SIX` (MPG 1.3.3)."""
    if not 1 <= n <= 99:
        raise ValueError(n)
    if n < 20:
        return _ONES[n]
    return f"{_TENS[n // 10]} {_ONES[n % 10]}".strip()


def encode_email(address: str) -> str:
    """`w3xxx@aol.com` -> `W3XXX ATSIGN AOL DOT COM` (RRI 2026 guidelines'
    example; MPG 1.3.2 allows AT, which is also an ordinary word)."""
    text = address.strip().upper()
    for char, word in (("@", "ATSIGN"), (".", "DOT"), ("-", "DASH"), ("_", "UNDERSCORE")):
        text = text.replace(char, f" {word} ")
    return " ".join(text.split())


def encode_text(raw: str, *, final: bool = True) -> str:
    """The text as groups, punctuation spelled out (MPG 1.3.1-1.3.3).

    Every rule works one word at a time (a quote mark opening a word is
    QUOTE, one closing it UNQUOTE), so the form can convert each word as
    it is finished and the result is the same as converting the whole text
    at once. `final=False` is that live conversion: a trailing X stays,
    since the operator is still typing; the finished text never ends in X.
    """
    text = raw.upper().replace("’", "'")
    text = _EMAIL_RE.sub(lambda m: f" {encode_email(m.group(0))} ", text)
    text = re.sub(r"(\d)\.(\d)", r"\1R\2", text)  # 7013.5 -> 7013R5
    # Hyphens are not used in telephone number groups (1.3.1).
    text = re.sub(r"\b(\d{3})-(\d{3})-(\d{4})\b", r"\1 \2 \3", text)
    text = re.sub(r"\b(\d{3})-(\d{4})\b", r"\1 \2", text)
    # Handling convention, not in MPG chapter 1: QUOTE/UNQUOTE and
    # PAREN/UNPAREN around a quoted or bracketed passage; an apostrophe is
    # dropped (DONT); `#5` is NR 5.
    text = re.sub(r'(^|\s)"', r"\1 QUOTE ", text).replace('"', " UNQUOTE ")
    text = text.replace("(", " PAREN ").replace(")", " UNPAREN ")
    text = text.replace("'", "")
    text = re.sub(r"#\s*(?=\d)", " NR ", text)
    for char, word in _SPELLED.items():
        text = text.replace(char, f" {word} ")
    text = re.sub(r"[^A-Z0-9/\s]", " ", text)
    groups = _spell_arl_numbers(text.split())
    # X is never the last group (1.3.1), and one period is one X.
    groups = [g for i, g in enumerate(groups) if not (g == "X" and i and groups[i - 1] == "X")]
    while final and groups and groups[-1] == "X":
        groups.pop()
    return " ".join(groups)


def _spell_arl_numbers(groups: list[str]) -> list[str]:
    """`ARL 46` typed as digits -> `ARL FORTY SIX` (always spelled, 1.3.3)."""
    out: list[str] = []
    for index, group in enumerate(groups):
        if index and groups[index - 1] == "ARL" and group.isdigit() and 1 <= int(group) <= 99:
            out.extend(number_words(int(group)).split())
        else:
            out.append(group)
    return out


def check(encoded_text: str) -> str:
    """The check: the number of groups, `ARL` ahead of it when the text
    holds an ARL numbered radiogram (MPG 1.1.5, 1.3.4)."""
    groups = encoded_text.split()
    return f"ARL {len(groups)}" if "ARL" in groups else str(len(groups))


def encode_address(line: str) -> str:
    """An address line without punctuation (MPG 1.2.6): a needed dash is
    spelled DASH, `#` is NR (KY2D), "/" may stay, anything else becomes a
    space."""
    text = re.sub(r"#\s*", " NR ", line.upper())
    text = re.sub(r"(\w)\s*-\s*(\w)", r"\1 DASH \2", text)
    text = re.sub(r"[^A-Z0-9/\s]", " ", text)
    return " ".join(text.split())


def format_phone(phone: str) -> str:
    """`(207) 555-1212` -> `207 555 1212` (MPG 1.2.4); other shapes lose
    their punctuation and keep their grouping."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
    if len(digits) == 7:
        return f"{digits[:3]} {digits[3:]}"
    return " ".join(re.sub(r"[^0-9\s]", " ", phone).split())


def format_zip(code: str) -> str:
    """`21117-2345` -> `21117 DASH 2345` (MPG 1.2.3)."""
    digits = re.sub(r"\D", "", code)
    return f"{digits[:5]} DASH {digits[5:]}" if len(digits) == 9 else digits


def date_filed(when: datetime) -> str:
    """`SEP 25`: month and day, no leading zero (MPG 1.1.8, 1.1.9)."""
    return f"{_MONTHS[when.month - 1]} {when.day}"


@dataclass
class Radiogram:
    """One radiogram as the operator fills it in; `body()` formats it."""

    number: str = ""
    precedence: str = "R"
    #: An exercise message: `TEST R` (MPG 1.1.2).
    test: bool = False
    handling: str = ""
    origin: str = ""
    place: str = ""
    #: Optional (MPG 1.1.7), with its zone: `1830Z`.
    time_filed: str = ""
    filed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    to_name: str = ""
    to_call: str = ""
    to_street: str = ""
    to_city: str = ""
    to_state: str = ""
    to_zip: str = ""
    to_phone: str = ""
    to_email: str = ""
    to_op_note: str = ""
    text: str = ""
    signature: str = ""
    sig_op_note: str = ""

    # -- the parts --------------------------------------------------------

    @property
    def encoded_text(self) -> str:
        return encode_text(self.text)

    @property
    def check(self) -> str:
        return check(self.encoded_text)

    def preamble(self) -> str:
        precedence = self.precedence.strip().upper()
        if self.test:
            precedence = f"TEST {precedence}"
        parts = [
            "NR", self.number.strip(), precedence, self.handling.strip().upper(),
            self.origin.strip().upper(), self.check, encode_address(self.place),
            self.time_filed.strip().upper(), date_filed(self.filed),
        ]
        return " ".join(part for part in parts if part)

    def address(self) -> list[str]:
        name = encode_address(self.to_name)
        call = self.to_call.strip().upper()
        if call and not name.endswith(call):
            name = f"{name} {call}".strip()  # call signs follow the name (1.2.1)
        lines = [name, encode_address(self.to_street)]
        city = " ".join(
            part for part in (encode_address(self.to_city), self.to_state.strip().upper(),
                              format_zip(self.to_zip)) if part
        )
        lines.append(city)
        if self.to_phone.strip():
            lines.append(format_phone(self.to_phone))
        if self.to_email.strip():
            lines.append(encode_email(self.to_email))
        if self.to_op_note.strip():
            lines.append(f"OP NOTE {encode_address(self.to_op_note)}")
        return [line for line in lines if line]

    def body(self) -> str:
        """The message body for a packet BBS: preamble, address, BT, the
        text five groups to a line, BT, signature; no AR (RRI 2026, KY2D)."""
        groups = self.encoded_text.split()
        text_lines = [" ".join(groups[i:i + 5]) for i in range(0, len(groups), 5)]
        lines = [self.preamble(), *self.address(), "BT", *text_lines, "BT",
                 encode_address(self.signature)]
        if self.sig_op_note.strip():
            lines.append(f"OP NOTE {encode_address(self.sig_op_note)}")
        return "\n".join(lines) + "\n"

    def subject(self) -> str:
        """The BBS title: `AUGUSTA KC1ABC` for a ham addressee, else
        `AUGUSTA 207 555` (area code and exchange), else `AUGUSTA - -`
        (KY2D; see the module docstring). At most 30 characters (MPG 6.2.1)
        -- the town is shortened, never the call or the phone."""
        digits = re.sub(r"\D", "", self.to_phone)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        call = self.to_call.strip().upper()
        if call:
            tail = call
        elif len(digits) == 10:
            tail = f"{digits[:3]} {digits[3:6]}"
        else:
            tail = "- -"
        room = MAX_SUBJECT - len(tail) - 1
        town = encode_address(self.to_city)[:max(room, 1)].rstrip()
        return f"{town} {tail}"[:MAX_SUBJECT]

    def routing(self) -> tuple[str, str]:
        """(`to`, `at`) for `ST <zip> @ NTS<state>` (MPG 6.2.1)."""
        return re.sub(r"\D", "", self.to_zip)[:5], f"NTS{self.to_state.strip().upper()}"

    # -- what stops it being saved ------------------------------------------

    def problems(self) -> list[str]:
        """What is missing or wrong, in the operator's words. Empty = OK."""
        found: list[str] = []
        number = self.number.strip()
        if not number.isdigit() or number.startswith("0"):
            found.append("Number: digits only, no leading zero (1.1.1).")
        if self.precedence.strip().upper() not in {value for value, _label in PRECEDENCES}:
            found.append("Precedence: R, W, P or EMERGENCY.")
        for code in self.handling.upper().split():
            if not _HX_RE.match(code):
                found.append(f"HX: {code!r} is not a handling code (HXA-HXG, e.g. HXG or HXA50).")
        if not _CALL_RE.match(self.origin.strip().upper()):
            found.append("Station of origin: a call sign, e.g. KC1JMH.")
        if len(encode_address(self.place).split()) < 2:
            found.append("Place of origin: the city and state of the sender, e.g. WATERBORO ME.")
        elif encode_address(self.place).split()[-1] not in STATES:
            found.append("Place of origin: end it with the two-letter state, e.g. WATERBORO ME.")
        if self.time_filed.strip() and not re.match(r"^\d{4}(Z|L|[A-Z]{3})$", self.time_filed.strip().upper()):
            found.append("Time filed: 24-hour time and zone, e.g. 1830Z, or leave it empty.")
        if not self.to_name.strip():
            found.append("To: the addressee's name.")
        if not self.to_city.strip():
            found.append("City: the addressee's city.")
        if self.to_state.strip().upper() not in STATES:
            found.append("State: the two-letter US state; NTS routes on it.")
        if not re.fullmatch(r"\d{5}(\d{4})?", re.sub(r"[\s-]", "", self.to_zip)):
            found.append("ZIP: 5 or 9 digits; NTS routes on it.")
        if self.to_call.strip() and not _CALL_RE.match(self.to_call.strip().upper()):
            found.append("Call sign: the addressee's, if they are a ham, or empty.")
        if not self.encoded_text:
            found.append("Text: the message is empty.")
        if not self.signature.strip():
            found.append("Signature: who the message is from.")
        return found

    def warnings(self) -> list[str]:
        """Allowed, but worth a second look."""
        found = []
        count = len(self.encoded_text.split())
        if count > USUAL_MAX_GROUPS:
            found.append(f"{count} groups: radiograms are usually {USUAL_MAX_GROUPS} or fewer (1.3).")
        if not self.to_phone.strip():
            found.append("No phone: delivery is much harder without one (1.2).")
        return found


def next_number(used: Iterable[str]) -> str:
    """One more than the highest message number already used."""
    numbers = [int(n) for n in used if str(n).isdigit()]
    return str(max(numbers, default=0) + 1)


@dataclass(frozen=True)
class ArlText:
    number: int
    word: str
    group: str
    text: str
    blanks: int

    @property
    def groups(self) -> str:
        """As it goes in the text: `ARL FORTY SIX`."""
        return f"ARL {self.word}"


@lru_cache(maxsize=1)
def arl_texts() -> tuple[ArlText, ...]:
    """The ARL numbered radiogram texts, v3.0 (see `data/arl_numbered.json`)."""
    raw = resources.files(__package__).joinpath("data/arl_numbered.json").read_text("utf-8")
    return tuple(ArlText(**entry) for entry in json.loads(raw)["texts"])


def arl_used(encoded_text: str) -> list[ArlText]:
    """The ARL numbered texts an encoded text refers to, in order: after
    each `ARL`, the longest number that follows (`ARL SIXTY TWO` is 62,
    not 60)."""
    by_word = {t.word: t for t in arl_texts()}
    groups = encoded_text.split()
    found = []
    for index, group in enumerate(groups):
        if group != "ARL":
            continue
        for size in (2, 1):
            word = " ".join(groups[index + 1:index + 1 + size])
            if word in by_word:
                found.append(by_word[word])
                break
    return found
