"""The UI-free core every front end drives (ROADMAP P7a). See `service.py`
and this package's `AGENTS.md`."""

from .events import Event, EventBus, GateChanged, RigStateChanged, TransportChanged
from .operator import Notice, NullOperator, Operator, Question, Severity
from .service import MAX_LINKS, TRANSPORT_SKIPPED, Core, build_station

__all__ = [
    "MAX_LINKS",
    "Core",
    "Event",
    "EventBus",
    "GateChanged",
    "Notice",
    "NullOperator",
    "Operator",
    "Question",
    "RigStateChanged",
    "Severity",
    "TRANSPORT_SKIPPED",
    "TransportChanged",
    "build_station",
]
