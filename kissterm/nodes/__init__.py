"""Command references for node software and TNCs, shipped rather than harvested.

Every node can list its own commands with `?`, and for a while the plan here
was to prefer that over anything kissterm ships. **That was wrong, on airtime
grounds**, and the arithmetic is worth keeping written down:

    at 1200 baud half-duplex, with AX.25 framing, keyup and turnaround --
      512 B of help text  ~  4.7 s of channel time
      2 KB of help text   ~ 18.7 s
      8 KB of help text   ~ 74.9 s

A verbose node's full help is a minute or more during which **nobody else on
the frequency can transmit**. Doing that automatically on every connect, to
populate an autocomplete list, would make kissterm the rudest client on the
band. So:

* **Shipped references are the primary source.** They cost nothing and they are
  available before the first byte is exchanged.
* **Harvesting is opt-in, once per node, and cached forever.** The operator
  asks for it, sees what it will cost, and never pays again for that node.
* Harvested commands *supplement* the shipped list, because local additions are
  real and no shipped table can know them: the WS1EC-15 node in the sibling
  bpq-apps repo adds CALENDAR, FORMS, WALL, GOPHER, PREDICT and a dozen more
  to a stock BPQ32 via `APPLICATION` lines.

References are TOML data in `data/`, one file per family. Adding a family is a
data file, not code -- the same principle as `ui/settings_schema.py`.

Provenance is recorded per family and per command (`confidence`), because a
command reference that quietly mixes documented fact with half-remembered
syntax is worse than none: an operator types what it says, at 1200 baud, and
finds out it was wrong. `"recalled"` entries are explicitly flagged in the UI.

Promoting a harvest into one of these shipped files is a manual step, by
design -- a harvest is one operator's one node on one day, and `confidence =
"verified"` is a claim about the software, not the station. To do it: connect,
harvest (`Ctrl+R` while connected, then confirm), then compare the cached
JSON (`kissterm/harvested.py`'s per-callsign store, in the platformdirs state
directory) against the family's TOML file by hand. A command already listed
there, confirmed present in the harvest, earns `confidence = "verified"`. A
command the harvest found that is not in the shipped file yet is either a
real addition to the family's stock command set (add it at `"documented"`,
and say in a comment which real node confirmed it and when) or a local
`APPLICATION` addition specific to that one node's configuration (leave it
out of the shipped file entirely -- BBS/CHAT/RMS are the stock names common
enough across independently-run nodes to name; CALENDAR, WALL, GOPHER and the
like are one sysop's own menu and do not belong in a file every kissterm user
gets by default). `bpq32.toml`'s own top-of-file comments are a worked
example of this cross-check, including one done against a second, independent
data source (a sibling repo's own node-map crawl) rather than a single
harvest -- more real nodes agreeing is stronger evidence than one, the same
reasoning that keeps `confidence` from being an all-or-nothing flag.
"""

from .reference import (
    Command,
    CommandReference,
    Family,
    airtime_seconds,
    available_families,
    load_family,
    load_all,
    parse_harvested,
)

__all__ = [
    "Command",
    "CommandReference",
    "Family",
    "airtime_seconds",
    "available_families",
    "load_family",
    "load_all",
    "parse_harvested",
]
