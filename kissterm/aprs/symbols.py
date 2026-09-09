"""The APRS map symbol table -- primary (`/`) and secondary (`\\`) tables.

Sourced from https://github.com/hessu/aprs-symbol-index (the table aprs.fi
itself uses to render map icons; CC BY-SA 4.0, Heikki Hannikainen/aprs.fi),
fetched and verified byte-for-byte against the project's own `symbols.csv`
rather than reconstructed from memory -- accuracy matters here because a
wrong table+code pair is transmitted under the operator's callsign and
rendered as a specific icon by every APRS client that decodes it. A
handful of code points are genuinely unassigned in that source and are
recorded here as ``description=""`` (shown as "Unassigned" by the Settings
picker) rather than guessed at. Overlay characters (a secondary-table
symbol combined with a digit/letter overlay for a variant meaning, e.g. a
numbered storm severity) are not modelled -- kissterm only ever sends the
plain two-character table+code pair, matching `aprs.encode.position_report`.

`emoji` is a separate, best-effort, cosmetic-only annotation this codebase
added on top of the sourced table -- NOT part of the APRS spec and not
transmitted. Where no obvious glyph exists, or where the underlying
concept is abstract (a numbered grid square, a reserved code point), it is
left `None`. Shown in the Settings symbol picker only when
`Config.ascii_safe` is False, reusing that existing manual override
(documented for exactly "no emoji/Unicode glyphs") instead of inventing
terminal-capability detection kissterm has never had.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Symbol", "SYMBOLS", "lookup", "filter_symbols"]


@dataclass(frozen=True, slots=True)
class Symbol:
    table: str  # "/" (primary) or "\\" (secondary)
    code: str  # one printable ASCII character
    description: str  # "" means unassigned in the source table
    emoji: str | None = None

    @property
    def key(self) -> str:
        """The two-character value actually stored in `Config.aprs.symbol`."""
        return f"{self.table}{self.code}"

    @property
    def label(self) -> str:
        """What the Settings picker shows for this entry."""
        name = self.description or "Unassigned"
        glyph = f"{self.emoji}  " if self.emoji else ""
        return f"{glyph}{name} ({self.key})"


# (code, description, emoji) -- table selector is added when building SYMBOLS below.
_PRIMARY: tuple[tuple[str, str, str | None], ...] = (
    ("!", "Police station", "\U0001f693"),
    ('"', "", None),
    ("#", "Digipeater", "\U0001f4e1"),
    ("$", "Telephone", "☎️"),
    ("%", "DX cluster", None),
    ("&", "HF gateway", "\U0001f310"),
    ("'", "Small aircraft", "✈️"),
    ("(", "Mobile satellite station", "\U0001f6f0️"),
    (")", "Wheelchair, handicapped", "♿"),
    ("*", "Snowmobile", "\U0001f6f7"),
    ("+", "Red Cross", "✚"),
    (",", "Boy Scouts", "⛺"),
    ("-", "House", "\U0001f3e0"),
    (".", "Red X", "❌"),
    ("/", "Red dot", "\U0001f534"),
    ("0", "Numbered circle: 0", "0️⃣"),
    ("1", "Numbered circle: 1", "1️⃣"),
    ("2", "Numbered circle: 2", "2️⃣"),
    ("3", "Numbered circle: 3", "3️⃣"),
    ("4", "Numbered circle: 4", "4️⃣"),
    ("5", "Numbered circle: 5", "5️⃣"),
    ("6", "Numbered circle: 6", "6️⃣"),
    ("7", "Numbered circle: 7", "7️⃣"),
    ("8", "Numbered circle: 8", "8️⃣"),
    ("9", "Numbered circle: 9", "9️⃣"),
    (":", "Fire", "\U0001f525"),
    (";", "Campground, tent", "⛺"),
    ("<", "Motorcycle", "\U0001f3cd️"),
    ("=", "Railroad engine", "\U0001f682"),
    (">", "Car", "\U0001f697"),
    ("?", "File server", "\U0001f5a5️"),
    ("@", "Hurricane predicted path", "\U0001f300"),
    ("A", "Aid station", "⛑️"),
    ("B", "BBS", "\U0001f4bb"),
    ("C", "Canoe", "\U0001f6f6"),
    ("D", "", None),
    ("E", "Eyeball", "\U0001f441️"),
    ("F", "Farm vehicle, tractor", "\U0001f69c"),
    ("G", "Grid square, 3 by 3", None),
    ("H", "Hotel", "\U0001f3e8"),
    ("I", "TCP/IP network station", "\U0001f310"),
    ("J", "", None),
    ("K", "School", "\U0001f3eb"),
    ("L", "PC user", "\U0001f4bb"),
    ("M", "Mac apple", "\U0001f34e"),
    ("N", "NTS station", None),
    ("O", "Balloon", "\U0001f388"),
    ("P", "Police car", "\U0001f693"),
    ("Q", "", None),
    ("R", "Recreational vehicle", "\U0001f690"),
    ("S", "Space Shuttle", "\U0001f680"),
    ("T", "SSTV", "\U0001f4f7"),
    ("U", "Bus", "\U0001f68c"),
    ("V", "ATV, Amateur Television", "\U0001f4fa"),
    ("W", "Weather service site", "\U0001f326️"),
    ("X", "Helicopter", "\U0001f681"),
    ("Y", "Sailboat", "⛵"),
    ("Z", "Windows flag", None),
    ("[", "Human", "\U0001f6b6"),
    ("\\", "DF triangle", "\U0001f4e1"),
    ("]", "Mailbox, post office", "\U0001f4ee"),
    ("^", "Large aircraft", "✈️"),
    ("_", "Weather station", "\U0001f321️"),
    ("`", "Satellite dish antenna", "\U0001f4e1"),
    ("a", "Ambulance", "\U0001f691"),
    ("b", "Bicycle", "\U0001f6b2"),
    ("c", "Incident command post", "\U0001f6a8"),
    ("d", "Fire station", "\U0001f692"),
    ("e", "Horse, equestrian", "\U0001f434"),
    ("f", "Fire truck", "\U0001f692"),
    ("g", "Glider", "\U0001f6e9️"),
    ("h", "Hospital", "\U0001f3e5"),
    ("i", "IOTA, islands on the air", "\U0001f3dd️"),
    ("j", "Jeep", "\U0001f699"),
    ("k", "Truck", "\U0001f69a"),
    ("l", "Laptop", "\U0001f4bb"),
    ("m", "Mic-E repeater", "\U0001f4e1"),
    ("n", "Node, black bulls-eye", "\U0001f3af"),
    ("o", "Emergency operations center", "\U0001f198"),
    ("p", "Dog", "\U0001f415"),
    ("q", "Grid square, 2 by 2", None),
    ("r", "Repeater tower", "\U0001f4e1"),
    ("s", "Ship, power boat", "\U0001f6a4"),
    ("t", "Truck stop", "⛽"),
    ("u", "Semi-trailer truck, 18-wheeler", "\U0001f69b"),
    ("v", "Van", "\U0001f690"),
    ("w", "Water station", "\U0001f4a7"),
    ("x", "X / Unix", None),
    ("y", "House, yagi antenna", "\U0001f3e0"),
    ("z", "Shelter", "\U0001f3da️"),
    ("{", "", None),
    ("}", "", None),
)

_SECONDARY: tuple[tuple[str, str, str | None], ...] = (
    ("!", "Emergency", "\U0001f198"),
    ('"', "", None),
    ("#", "Digipeater, green star", "\U0001f4e1"),
    ("$", "Bank or ATM", "\U0001f3e7"),
    ("%", "", None),
    ("&", "Gateway station", "\U0001f310"),
    ("'", "Crash / incident site", "\U0001f4a5"),
    ("(", "Cloudy", "☁️"),
    (")", "Firenet MEO, MODIS Earth Observation", "\U0001f6f0️"),
    ("*", "Snow", "❄️"),
    ("+", "Church", "⛪"),
    (",", "Girl Scouts", "⛺"),
    ("-", "House, HF antenna", "\U0001f3e0"),
    (".", "Ambiguous, question mark inside circle", "❓"),
    ("/", "Waypoint destination", "\U0001f4cd"),
    ("0", "Circle, IRLP / Echolink/WIRES", "\U0001f535"),
    ("1", "", None),
    ("2", "", None),
    ("3", "", None),
    ("4", "", None),
    ("5", "", None),
    ("6", "", None),
    ("7", "", None),
    ("8", "802.11 WiFi or other network node", "\U0001f4f6"),
    ("9", "Gas station", "⛽"),
    (":", "Hail", "\U0001f9ca"),
    (";", "Park, picnic area", "\U0001f3de️"),
    ("<", "Advisory, single red flag", "\U0001f6a9"),
    ("=", "", None),
    (">", "Red car", "\U0001f697"),
    ("?", "Info kiosk", "ℹ️"),
    ("@", "Hurricane, Tropical storm", "\U0001f300"),
    ("A", "White box", "⬜"),
    ("B", "Blowing snow", "\U0001f328️"),
    ("C", "Coast Guard", "⚓"),
    ("D", "Drizzling rain", "\U0001f327️"),
    ("E", "Smoke, Chimney", "\U0001f4a8"),
    ("F", "Freezing rain", "\U0001f328️"),
    ("G", "Snow shower", "❄️"),
    ("H", "Haze", "\U0001f32b️"),
    ("I", "Rain shower", "\U0001f327️"),
    ("J", "Lightning", "⚡"),
    ("K", "Kenwood HT", "\U0001f4fb"),
    ("L", "Lighthouse", "\U0001f5fc"),
    ("M", "", None),
    ("N", "Navigation buoy", "\U0001f6df"),
    ("O", "Rocket", "\U0001f680"),
    ("P", "Parking", "\U0001f17f️"),
    ("Q", "Earthquake", "\U0001f30d"),
    ("R", "Restaurant", "\U0001f37d️"),
    ("S", "Satellite", "\U0001f6f0️"),
    ("T", "Thunderstorm", "⛈️"),
    ("U", "Sunny", "☀️"),
    ("V", "VORTAC, Navigational aid", "\U0001f9ed"),
    ("W", "NWS site", "\U0001f326️"),
    ("X", "Pharmacy", "\U0001f48a"),
    ("Y", "", None),
    ("Z", "", None),
    ("[", "Wall Cloud", "☁️"),
    ("\\", "", None),
    ("]", "", None),
    ("^", "Aircraft", "✈️"),
    ("_", "Weather site", "\U0001f321️"),
    ("`", "Rain", "\U0001f327️"),
    ("a", "Red diamond", "\U0001f536"),
    ("b", "Blowing dust, sand", "\U0001f3dc️"),
    ("c", "CD triangle, RACES, CERTS, SATERN", "⚠️"),
    ("d", "DX spot", "\U0001f4e1"),
    ("e", "Sleet", "\U0001f328️"),
    ("f", "Funnel cloud", "\U0001f32a️"),
    ("g", "Gale, two red flags", "\U0001f6a9"),
    ("h", "Store", "\U0001f3ea"),
    ("i", "Black box, point of interest", "⬛"),
    ("j", "Work zone, excavating machine", "\U0001f6a7"),
    ("k", "SUV, ATV", "\U0001f699"),
    ("l", "", None),
    ("m", "Value sign, 3 digit display", "\U0001f522"),
    ("n", "Red triangle", "\U0001f53a"),
    ("o", "Small circle", "⚪"),
    ("p", "Partly cloudy", "⛅"),
    ("q", "", None),
    ("r", "Restrooms", "\U0001f6bb"),
    ("s", "Ship, boat", "\U0001f6a2"),
    ("t", "Tornado", "\U0001f32a️"),
    ("u", "Truck", "\U0001f69a"),
    ("v", "Van", "\U0001f690"),
    ("w", "Flooding", "\U0001f30a"),
    ("x", "", None),
    ("y", "Skywarn", "⛈️"),
    ("z", "Shelter", "\U0001f3da️"),
    ("{", "Fog", "\U0001f32b️"),
    ("}", "", None),
)

SYMBOLS: tuple[Symbol, ...] = tuple(
    Symbol("/", code, desc, emoji) for code, desc, emoji in _PRIMARY
) + tuple(Symbol("\\", code, desc, emoji) for code, desc, emoji in _SECONDARY)

_BY_KEY: dict[str, Symbol] = {s.key: s for s in SYMBOLS}


def lookup(table: str, code: str) -> Symbol | None:
    """The `Symbol` for a stored `Config.aprs.symbol`-style key, or None."""
    if len(table) != 1 or len(code) != 1:
        return None
    return _BY_KEY.get(f"{table}{code}")


def filter_symbols(needle: str) -> tuple[Symbol, ...]:
    """Symbols whose description (or literal key) contains `needle`.

    Empty `needle` returns every symbol, matching
    `ConnectScreen._render_history`'s "empty filter shows everything"
    convention in `kissterm/ui/dialogs.py`, which this picker's own filter
    input is modelled on.
    """
    needle = needle.strip().lower()
    if not needle:
        return SYMBOLS
    return tuple(
        s
        for s in SYMBOLS
        if needle in s.description.lower() or needle == s.key.lower()
    )
