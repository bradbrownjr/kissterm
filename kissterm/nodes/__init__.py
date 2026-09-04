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
"""

from .reference import (
    Command,
    CommandReference,
    Family,
    airtime_seconds,
    available_families,
    load_family,
    load_all,
)

__all__ = [
    "Command",
    "CommandReference",
    "Family",
    "airtime_seconds",
    "available_families",
    "load_family",
    "load_all",
]
