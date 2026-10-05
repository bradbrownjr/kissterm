"""Saving and applying settings, for every front end (ROADMAP P7a M6).

A client edits a draft -- `{field path: raw value}` for the fields
`settings_schema.SETTINGS_SCHEMA` describes -- and hands it to
`Settings.save`. Validation is the schema's (`coerce`, plus the rules no
one field can state); **a save is all or nothing**: one bad field and
nothing is written, because a partial save leaves the operator unable to
tell which values took. A "secret" field's text becomes a saved login (the
system keyring when there is one) and is never echoed back.

What changes under a running station is applied here too: the callsign
and link parameters on the station (new links only -- an established
link keeps what it agreed, since changing it underneath corrupts it), and
the beacons, GPS, APRS-IS watch and watched-callsign limits
(`apply_runtime`, also run once at launch). What only a client draws --
its theme, its monitor filter -- the client applies itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..ax25.address import AX25Address
from ..config import SECRET_LOGINS, credential_store, set_credential
from . import settings_schema as schema

log = logging.getLogger(__name__)

#: Two fields whose relationship no one `Field` can express.
_SMART_SLOW = "aprs.smart_slow_speed_knots"
_SMART_FAST = "aprs.smart_fast_speed_knots"


@dataclass
class SaveResult:
    """What `Settings.save` did. `errors` (field path -> message, in schema
    order) non-empty means nothing was written."""

    errors: dict[str, str] = field(default_factory=dict)
    #: Whether the file was written; False with no errors means "applied
    #: for this session only".
    saved: bool = False
    #: Cross-field advice (`settings_schema.cross_check`), worth showing.
    notes: list[str] = field(default_factory=list)
    #: Secret field path -> "keyring" or "config": where its text went.
    secrets: dict[str, str] = field(default_factory=dict)


class Settings:
    """Owned by `Core` as `core.settings`."""

    def __init__(self, core) -> None:
        self.core = core

    def validate(self, draft: dict) -> tuple[dict, list[tuple[str, str]], dict[str, str]]:
        """(coerced values, secrets typed, errors) for `draft`, touching
        nothing."""
        pending: dict = {}
        secrets: list[tuple[str, str]] = []
        errors: dict[str, str] = {}
        for section in schema.SETTINGS_SCHEMA:
            for spec in section.fields:
                if spec.path not in draft:
                    continue
                raw = draft[spec.path]
                if spec.kind == "secret":
                    if raw:
                        secrets.append((spec.path, str(raw)))
                    continue
                try:
                    pending[spec.path] = schema.coerce(spec, raw)
                except schema.ValidationError as exc:
                    errors[spec.path] = str(exc)
        slow, fast = pending.get(_SMART_SLOW), pending.get(_SMART_FAST)
        if isinstance(slow, int) and isinstance(fast, int) and slow >= fast:
            for path in (_SMART_SLOW, _SMART_FAST):
                errors[path] = "Must be below Smart fast speed."
        return pending, secrets, errors

    def save(self, draft: dict, active_transport: str = "", *, apply: bool = True) -> SaveResult:
        """Validate `draft`; if it all holds, set it, save it and (with
        `apply`) apply it to the running station. `active_transport` (""
        leaves it) is the transport chosen; opening it is the caller's next
        step (`Core.switch_frame_transport`). A client with its own apply
        hook (the terminal UI's `apply_runtime_settings`) passes
        `apply=False` and calls `apply_to_station` and `apply_runtime`
        itself, so nothing restarts twice."""
        config = self.core.config
        pending, secrets, errors = self.validate(draft)
        if errors:
            return SaveResult(errors=errors)
        for path, value in pending.items():
            schema.set_value(config, path, value)
        names = dict(SECRET_LOGINS)
        for path, text in secrets:
            set_credential(config, names[path], text)
            schema.set_value(config, path, names[path])
        if active_transport:
            config.active_transport = active_transport
        result = SaveResult(notes=schema.cross_check(config))
        result.saved = self.core.save_config()
        for path, _text in secrets:
            result.secrets[path] = credential_store(config, names[path]) or "config"
        if apply:
            self.apply_to_station()
            self.apply_runtime()
        return result

    def apply_to_station(self) -> None:
        """The callsign and link parameters, on the live station. New links
        pick the parameters up (`Field.apply == "connect"`)."""
        config = self.core.config
        station = self.core.station
        if station is None:
            return
        try:
            station.mycall = AX25Address.parse(config.mycall)
            station.aliases = tuple(AX25Address.parse(a) for a in config.mycall_aliases)
        except Exception:  # noqa: BLE001 - a bad call must not stop the rest
            log.exception("could not apply callsign settings")
        params = station.params
        params.paclen = config.paclen
        params.window = config.window
        params.modulo = config.modulo
        params.retries = config.retries
        params.t1 = config.t1
        params.t2 = config.t2
        params.t3 = config.t3

    def apply_runtime(self) -> None:
        """Reconcile what runs on its own with the configuration: both
        beacons, GPS, the APRS-IS debug watch, the watched-callsign limits.
        Idempotent: Save gets pressed repeatedly, and a second press must
        not leave two beacon timers running."""
        aprs = self.core.aprs
        aprs.spawn(aprs.restart_beacon())
        aprs.spawn(aprs.restart_gps())
        aprs.spawn(aprs.restart_aprs_beacon())
        aprs.reconcile_is_debug_watch()
        self.core.channel.watch_notifier = self.core.channel.make_watch_notifier()
