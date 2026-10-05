"""The UI-free core every front end drives (ROADMAP P7a). See `service.py`
and this package's `AGENTS.md`."""

from .events import Event, EventBus, GateChanged, TransportChanged
from .operator import Notice, NullOperator, Operator, Question, Severity
from .service import MAX_LINKS, Core, build_station

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
    "Severity",
    "TransportChanged",
    "build_station",
]
