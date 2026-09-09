"""The shipped APRS gateway service directory.

See `directory.py` for what this is and why it ships as data rather than
being asked for over the air. Import from here, not from `.directory`, so
the data layout stays an implementation detail.
"""

from __future__ import annotations

from .directory import (
    CONFIDENCE_ORDER,
    DATA_DIR,
    Service,
    ServiceCommand,
    find,
    load_all,
    lookup,
    lookup_callsign,
)

__all__ = [
    "CONFIDENCE_ORDER",
    "DATA_DIR",
    "Service",
    "ServiceCommand",
    "find",
    "load_all",
    "lookup",
    "lookup_callsign",
]
