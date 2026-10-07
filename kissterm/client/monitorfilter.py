"""The remote client's Monitor filter: the terminal's `monitor.MonitorFilter`
on what the station sends in a `FrameSeen` (`kind`, `ui`, `calls`, `text`,
`port`), because this package never imports `ax25` (AGENTS.md rule 1). The
rules match `MonitorFilter.allows`, so a filter means the same in both front
ends (`tests/unit/test_client_monitorfilter.py` runs the two side by side).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MonitorFilter:
    show_supervisory: bool = True
    show_unnumbered: bool = True
    show_information: bool = True
    show_ui: bool = True
    ports: tuple[int, ...] = ()
    calls: tuple[str, ...] = ()
    contains: str = ""

    def set_query(self, value: str) -> None:
        """One box, as in the terminal: a callsign-looking word filters by
        call, anything else by text in the payload."""
        value = value.strip()
        self.calls = ()
        self.contains = ""
        if not value:
            return
        if any(c.isdigit() for c in value) and " " not in value:
            self.calls = (value,)
        else:
            self.contains = value

    def allows(self, data: dict) -> bool:
        kind = data.get("kind")
        if self.ports and int(data.get("port", 0)) not in self.ports:
            return False
        if kind == "S" and not self.show_supervisory:
            return False
        if kind == "I" and not self.show_information:
            return False
        if kind == "U":
            if data.get("ui"):
                if not self.show_ui:
                    return False
            elif not self.show_unnumbered:
                return False
        if self.calls:
            wanted = {c.upper() for c in self.calls}
            if not wanted & {str(c).upper() for c in data.get("calls", ())}:
                return False
        if self.contains and self.contains.lower() not in str(data.get("text", "")).lower():
            return False
        return True
