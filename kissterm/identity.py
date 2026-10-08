"""Which callsign this station operates as.

A **tactical call** (`CCEMA`) is the name of an assignment, so the net
keeps talking to the same address as operators change shifts (ROADMAP P11,
Outpost's "Setups for Tactical Operations"). Every AX.25 frame carries its
source address, so operating as a tactical call puts the tactical name on
the air and nothing else; the licensed callsign has to be identified
separately (`core/identifier.py`).

Pure functions over a `Config`; no I/O. What follows the tactical call: the
AX.25 source of connects and the call the station answers on. What never
does: APRS (`Config.aprs.source_for` takes the real call), Winlink (its
account is the real call), VARA, and the session logs.
"""

from __future__ import annotations

from .ax25.address import AX25Address, AX25AddressError


def tactical_active(config) -> bool:
    """Whether the station is operating as its tactical call now."""
    return bool(config.operate_as_tactical and config.tactical_call)


def air_call(config) -> str:
    """The callsign on the air: the tactical call, else the real one."""
    return config.tactical_call if tactical_active(config) else config.mycall


def parse_air_call(config) -> AX25Address | None:
    """`air_call` as an address, or None when it does not parse."""
    try:
        return AX25Address.parse(air_call(config))
    except (AX25AddressError, ValueError):
        return None
