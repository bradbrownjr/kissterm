"""Frequencies as the operator writes them, and as a rig is told them.

Pure functions: no I/O, no rig.

**A contact's frequency is the DIAL** -- what the radio's display should
read -- written the way a person would ("145.090", "145.090 MHz FM",
"7.1015 MHz USB-D", "7101500"). `parse_frequency` reads it into a `Tuning`:
hertz plus, when the text names one, a Hamlib mode token.

**Winlink publishes the CENTRE frequency of a gateway channel**, not the
dial. For an HF digital mode sent as upper sideband (VARA HF, Pactor, ARDOP)
the dial is the centre minus 1500 Hz (`dial_from_centre`). Sources: Winlink
and VARA setup guides (a gateway listed at 14065.400 kHz centre is dialled
at 14063.90 kHz; "All frequencies are USB"; Winlink Express applies the
1500 Hz itself when it tunes a rig from the channel list); cited in
`docs/SOURCES.md`. VHF and UHF packet and VARA FM channels are not offset.

**Mode tokens are Hamlib's** (`rigctl(1)`, `M`/`set_mode`): `USB`, `LSB`,
`FM`, `AM`, `CW`, and the data modes `PKTUSB`, `PKTLSB`, `PKTFM`. Rig menus
call the data modes "USB-D", "DATA-USB", "DIG" and so on; `USB-D` is the
operator's word here and maps to `PKTUSB`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: What an operator may write after a frequency, and the Hamlib token it means.
MODE_WORDS = {
    "USB": "USB", "LSB": "LSB", "FM": "FM", "AM": "AM", "CW": "CW",
    "USB-D": "PKTUSB", "USBD": "PKTUSB", "DATA-USB": "PKTUSB", "PKTUSB": "PKTUSB",
    "LSB-D": "PKTLSB", "LSBD": "PKTLSB", "DATA-LSB": "PKTLSB", "PKTLSB": "PKTLSB",
    "FM-D": "PKTFM", "FMD": "PKTFM", "DATA-FM": "PKTFM", "PKTFM": "PKTFM",
}
#: Hamlib token -> the operator's word, for display.
MODE_LABELS = {"PKTUSB": "USB-D", "PKTLSB": "LSB-D", "PKTFM": "FM-D"}

#: Winlink modes whose published frequency is a centre, dialled 1500 Hz
#: below on upper sideband.
CENTRE_MODES = ("VARA", "PACTOR", "ARDOP", "WINMOR", "ROBUST")
CENTRE_OFFSET_HZ = 1500
HF_LIMIT_HZ = 30_000_000

#: Amateur bands, in hertz (the ones `tune_bands` names). Edges are the
#: widest allocations; this names a band, it does not police privileges.
BANDS_HZ = {
    "160m": (1_800_000, 2_000_000), "80m": (3_500_000, 4_000_000),
    "60m": (5_060_000, 5_450_000), "40m": (7_000_000, 7_300_000),
    "30m": (10_100_000, 10_150_000), "20m": (14_000_000, 14_350_000),
    "17m": (18_068_000, 18_168_000), "15m": (21_000_000, 21_450_000),
    "12m": (24_890_000, 24_990_000), "10m": (28_000_000, 29_700_000),
    "6m": (50_000_000, 54_000_000), "2m": (144_000_000, 148_000_000),
    "70cm": (420_000_000, 450_000_000),
}

_PATTERN = re.compile(
    r"^\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>[kKmMgG]?[hH][zZ])?\s*(?P<rest>.*)$")
_UNITS = {"hz": 1, "khz": 1_000, "mhz": 1_000_000, "ghz": 1_000_000_000}


@dataclass(frozen=True)
class Tuning:
    """Where to put the rig: dial `hz`, and a Hamlib `mode` ("" leaves the
    rig's mode as it is)."""

    hz: int
    mode: str = ""

    def describe(self) -> str:
        """"7.101.500 USB-D": MHz.kHz.Hz, then the mode in the operator's word."""
        mhz, rest = divmod(self.hz, 1_000_000)
        khz, hz = divmod(rest, 1000)
        text = f"{mhz}.{khz:03d}.{hz:03d}"
        return f"{text} {MODE_LABELS.get(self.mode, self.mode)}".strip()

    def as_contact_text(self) -> str:
        """The form an Address Book contact stores: "7.101500 MHz USB-D"."""
        label = MODE_LABELS.get(self.mode, self.mode)
        return f"{self.hz / 1e6:.6f} MHz" + (f" {label}" if label else "")


def parse_frequency(text: str) -> Tuning | None:
    """Read a contact's frequency; None if there is no number to tune to.

    With a unit (`Hz`, `kHz`, `MHz`, `GHz`) the number is that. Without
    one: under 1000 is MHz ("145.090"), 1000 to 999999 is kHz ("7101.5"),
    and a million or more is Hz ("7101500"). A word after it that is a mode
    (`MODE_WORDS`) sets the mode; any other word is ignored (a note), never
    guessed at."""
    match = _PATTERN.match(str(text or ""))
    if not match:
        return None
    value = float(match["num"].replace(",", "."))
    unit = (match["unit"] or "").lower()
    if unit:
        hertz = value * _UNITS[unit]
    elif value < 1000:
        hertz = value * 1_000_000
    elif value < 1_000_000:
        hertz = value * 1_000
    else:
        hertz = value
    hz = int(round(hertz))
    if hz <= 0:
        return None
    mode = ""
    for word in match["rest"].upper().replace("/", " ").split():
        if word in MODE_WORDS:
            mode = MODE_WORDS[word]
            break
    return Tuning(hz, mode)


def dial_from_centre(centre_hz: int, modes: str) -> Tuning:
    """The dial for a Winlink gateway channel published at `centre_hz` in
    `modes` (the channel's `SupportedModes` text): centre minus 1500 Hz in
    USB data for an HF digital mode, else the frequency as listed."""
    upper = (modes or "").upper()
    if centre_hz < HF_LIMIT_HZ and any(word in upper for word in CENTRE_MODES):
        return Tuning(centre_hz - CENTRE_OFFSET_HZ, "PKTUSB")
    return Tuning(centre_hz, "")


def band_of(hz: int) -> str:
    """The amateur band name containing `hz` ("40m"), or ""."""
    for name, (low, high) in BANDS_HZ.items():
        if low <= hz <= high:
            return name
    return ""
