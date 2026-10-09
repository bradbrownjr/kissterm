"""Settings > Radio, Logins and Scripts, for every front end: the
transports the station can use, the saved logins and scripts a contact
or transport names.

**These are lists of dicts, not schema fields** (`settings_schema`'s
docstring), so each front end used to build its own screens over
`config.transports`, `credentials` and `scripts`. This is the one place
that changes them, so the terminal's Settings and a phone's agree on what
is valid and what is saved.

**An entry is proven before it is saved.** `transport.build_transport` is
the only constructor from config (AGENTS.md), so a transport that would
not construct is refused here, while the operator still has the form
open: a config entry that looks right and fails at `open()` is worse.

**Nothing here transmits.** Scan and Test are what the terminal's buttons
are: a serial listing, a network sweep, and the two bare probes
`discovery` documents. They run only when asked (AGENTS.md "Never scan the
network on a timer").

**Passwords never come back.** A login is described by its name, username
and where its password is kept; an empty password on an edit keeps the
saved one.
"""

from __future__ import annotations

import logging

from ..config import (
    credential_store,
    credential_username,
    find_credential,
    forget_credential,
    set_credential,
)
from ..launch.presets import PRESETS
from ..transport.forms import BANDS, PROGRAM_FORM, RIG_FORM, TRANSPORT_FORMS
from .events import ConfigChanged

log = logging.getLogger(__name__)

#: What a test prints for each `discovery.Identity.verdict`: an operator
#: pressing Test wants OK or FAILED, not the paragraph scan results carry.
TEST_LABEL = {
    "agwpe": "OK",
    "kiss": "OK",
    "not-a-tnc": "FAILED",
    "unreachable": "FAILED",
    # Silence is normal for an idle KISS TNC.
    "unknown": "OPEN",
}


def test_result_line(host: str, port: int, identity) -> str:
    label = TEST_LABEL.get(identity.verdict, "UNKNOWN")
    if identity.is_tnc:
        reason = identity.summary.removeprefix("Confirmed: ").rstrip(".")
    elif identity.verdict in ("not-a-tnc", "unreachable"):
        reason = identity.summary.rstrip(".")
    else:
        reason = "open, identity unconfirmed (silent KISS is normal)"
    return f"{host}:{port}  {label}  --  {reason}"


test_result_line.__test__ = False  # pytest: a function named test_*, not a test


def login_where() -> str:
    """Where a new login's password will be kept: "keyring" or "config"."""
    from .. import keystore

    return "keyring" if keystore.available() else "config"


class Radio:
    """Owned by `Core` as `core.radio`."""

    def __init__(self, core) -> None:
        self.core = core

    def _saved(self) -> bool:
        ok = self.core.save_config()
        self.core.events.publish(ConfigChanged())
        return ok

    # -- transports --------------------------------------------------------
    def kinds(self) -> list[dict]:
        """What each kind of transport asks for, for a client's form."""
        from ..transport import EXPERIMENTAL_KINDS, KIND_LABELS

        return [{
            "kind": kind, "label": KIND_LABELS.get(kind, kind),
            "experimental": kind in EXPERIMENTAL_KINDS,
            "session_tier": session_tier,
            "fields": [{"key": f.key, "label": f.label, "placeholder": f.placeholder,
                        "default": f.default, "numeric": f.numeric, "password": f.password,
                        "optional": f.optional} for f in fields],
        } for kind, (session_tier, fields) in TRANSPORT_FORMS.items()]

    def info(self) -> dict:
        """Everything Settings > Radio shows: the transports and which is in
        use, the kinds a new one can be, and the logins and scripts an
        auto-login can name."""
        config = self.core.config
        return {
            "active": config.active_transport or (
                config.transports[0].get("name", "") if config.transports else ""),
            "transports": [{k: v for k, v in t.items() if k not in ("script", "text")}
                           for t in config.transports],
            "kinds": self.kinds(),
            "programs": [dict(p) for p in config.programs],
            "rigs": [dict(r) for r in config.rigs],
            "logins": [c["name"] for c in config.credentials if c.get("name")],
            "scripts": [s["name"] for s in config.scripts if s.get("name")],
        }

    def save_transport(self, entry: dict, original: str = "") -> str:
        """Add or replace a transport; "" when it was saved, else why not.

        Only the kind's own fields are taken from `entry`; the entry being
        edited keeps what this form does not show (serial's `kiss_params`,
        vara's `bandwidth`), as the terminal's form does."""
        config = self.core.config
        name = str(entry.get("name", "")).strip()
        kind = str(entry.get("kind", ""))
        if not name:
            return "Name this transport something: it is how Settings and the Address Book find it."
        if kind not in TRANSPORT_FORMS:
            return f"Not a kind of transport: {kind!r}."
        if name != original and any(t.get("name") == name for t in config.transports):
            return f"{name!r} is already in use. Pick another name."
        session_tier, fields = TRANSPORT_FORMS[kind]
        values: dict[str, object] = {}
        for field in fields:
            raw = str(entry.get(field.key, "")).strip()
            if field.numeric:
                if not raw:
                    return f"{field.label} is required."
                try:
                    values[field.key] = int(raw)
                except ValueError:
                    return f"{field.label} must be a number."
            elif not raw and not (field.password or field.optional):
                return f"{field.label} is required."
            else:
                values[field.key] = raw
        before = next((t for t in config.transports if t.get("name") == original), None)
        result = dict(before) if before and before.get("kind") == kind else {}
        result.update(values)
        for key, entries, what in (("program", config.programs, "program"),
                                   ("rig", config.rigs, "rig")):
            wanted = str(entry.get(key, result.get(key, "")) or "")
            if wanted and not any(e.get("name") == wanted for e in entries):
                return f"There is no {what} named {wanted!r}. Add it first, or choose none."
            if wanted:
                result[key] = wanted
            else:
                result.pop(key, None)
        result["name"], result["kind"] = name, kind
        if session_tier:
            credential = str(entry.get("credential", ""))
            script_name = "" if credential else str(entry.get("script_name", ""))
            result["script"] = "" if (credential or script_name) else str(
                (before or {}).get("script", ""))
            result["credential"], result["script_name"] = credential, script_name
        else:
            for key in ("script", "credential", "script_name"):
                result.pop(key, None)
        from .. import transport as transport_mod

        try:
            transport_mod.build_transport(result)
        except Exception as exc:  # noqa: BLE001 - whatever it is, it is why not
            return f"Could not save {name!r}: {exc}"
        config.transports = [t for t in config.transports if t.get("name") not in (original, name)]
        config.transports.append(result)
        if config.active_transport == original or not config.active_transport:
            config.active_transport = name
        self._saved()
        return ""

    def forget_transport(self, name: str) -> bool:
        config = self.core.config
        if not any(t.get("name") == name for t in config.transports):
            return False
        config.transports = [t for t in config.transports if t.get("name") != name]
        if config.active_transport == name:
            config.active_transport = config.transports[0].get("name", "") if config.transports else ""
        self._saved()
        return True

    async def scan(self) -> dict:
        """Look for TNCs (serial, the local network, paired Bluetooth) and
        add what is found that is not already there. Nothing is
        transmitted. `coverage` says whether the sweep reached the whole
        subnet: "nothing found" and "gave up before looking" differ."""
        from .. import discovery

        config = self.core.config
        coverage = discovery.ScanCoverage()
        try:
            found = await discovery.discover_all(coverage=coverage)
        except Exception:  # noqa: BLE001
            log.exception("discovery failed")
            return {"found": 0, "added": 0, "summary": "Scan failed. 'kissterm --doctor' may say why."}
        reach = coverage.summary if coverage.hosts_planned else ""
        if not found:
            return {"found": 0, "added": 0, "summary": (
                "Nothing found. That is not proof there is no TNC: a silent KISS TNC looks "
                "like a wrong serial port until a frame arrives." + (f" {reach}" if reach else ""))}
        added = 0
        for dev in found:
            entry = dict(dev.config)
            entry.setdefault("name", dev.label)
            if any(t.get("name") == entry["name"] for t in config.transports):
                continue
            config.transports.append(entry)
            added += 1
        if added and not config.active_transport:
            config.active_transport = config.transports[0].get("name", "")
        if added:
            self._saved()
        summary = f"Found {len(found)}; added {added} new."
        if coverage.truncated:
            summary = f"{summary}  {coverage.summary}"
        return {"found": len(found), "added": added, "summary": summary}

    async def test(self, name: str) -> dict:
        """Ask a transport whether anything real is on its far end, which is
        not a connect to another station (`discovery.identify_tcp` says
        exactly what goes out on the socket). `ok` is True only for a
        confirmed TNC; a serial or Bluetooth port is not opened from here
        (it would take the port from the station)."""
        entry = next((t for t in self.core.config.transports if t.get("name") == name), None)
        if entry is None:
            return {"ok": False, "line": "Select a transport first."}
        kind = entry.get("kind", "")
        if kind in ("serial", "bluetooth", "ble", "kernel"):
            return {"ok": False, "line": (
                f"Testing {kind} transports from here is not wired up yet: "
                "'kissterm --doctor' checks the device, permissions and dependencies for those.")}
        host, port = entry.get("host", ""), entry.get("port", 0)
        if not host or not port:
            return {"ok": False, "line": f"{name} has no host and port to test."}
        from .. import discovery

        try:
            identity = await discovery.identify_tcp(host, int(port), kind=kind)
        except Exception:  # noqa: BLE001
            log.exception("transport test failed")
            return {"ok": False, "line": "The test itself failed. 'kissterm --doctor' may say why."}
        return {"ok": bool(identity.is_tnc), "line": test_result_line(host, port, identity)}

    # -- logins ---------------------------------------------------------------
    def logins(self) -> list[dict]:
        config = self.core.config
        out = []
        for entry in config.credentials:
            name = entry.get("name")
            if not name:
                continue
            out.append({"name": name, "username": credential_username(config, name),
                        "has_password": bool(find_credential(config, name)),
                        "where": credential_store(config, name) or login_where()})
        return out

    def save_login(self, name: str, username: str = "", password: str = "",
                   original: str = "") -> str:
        """"" when saved, else why not. An empty password keeps the saved
        one of the login being edited."""
        config = self.core.config
        name, username = name.strip(), username.strip()
        if not name:
            return "Name this login: it is how a contact or setting finds it."
        keep = find_credential(config, original) if original else ""
        if not password and not keep and not username:
            return "Type the password, or a username for a passwordless sign-in."
        set_credential(config, name, password or keep, old_name=original, username=username)
        self._saved()
        return ""

    def forget_login(self, name: str) -> bool:
        config = self.core.config
        if not any(c.get("name") == name for c in config.credentials):
            return False
        forget_credential(config, name)
        self._saved()
        return True

    # -- programs and rigs ----------------------------------------------------
    def programs_form(self) -> dict:
        """What a Programs entry asks for, and the presets it starts from."""
        return {"fields": [_field_dict(f) for f in PROGRAM_FORM],
                "presets": [{"key": p.key, "label": p.label, "transport_kind": p.transport_kind,
                             "source": p.source, "note": p.note, "runs_under_wine": p.runs_under_wine}
                            for p in PRESETS.values()]}

    def rigs_form(self) -> dict:
        return {"fields": [_field_dict(f) for f in RIG_FORM], "bands": list(BANDS)}

    def save_program(self, entry: dict, original: str = "") -> str:
        """Add or replace a Programs entry; "" when saved, else why not."""
        config = self.core.config
        name = str(entry.get("name", "")).strip()
        if not name:
            return "Name this program something: transports find it by that name."
        if name != original and any(p.get("name") == name for p in config.programs):
            return f"{name!r} is already in use. Pick another name."
        preset = str(entry.get("preset", "custom") or "custom")
        if preset not in PRESETS:
            return f"Not a known program: {preset!r}."
        path = str(entry.get("path", "")).strip()
        if not path:
            return "Program file is required."
        values = _coerce(entry, PROGRAM_FORM)
        if isinstance(values, str):
            return values
        if values["start_timeout"] < 1:
            return "Seconds to wait for it must be at least 1."
        values.update(name=name, preset=preset, path=path)
        config.programs = [p for p in config.programs if p.get("name") not in (original, name)]
        config.programs.append(values)
        if original and original != name:
            for transport in config.transports:
                if transport.get("program") == original:
                    transport["program"] = name
        self._saved()
        return ""

    def forget_program(self, name: str) -> str:
        """Remove a Programs entry; "" when removed, else why not."""
        config = self.core.config
        if not any(p.get("name") == name for p in config.programs):
            return f"There is no program named {name!r}."
        using = [t.get("name", "") for t in config.transports if t.get("program") == name]
        if using:
            return f"{name!r} is still used by {', '.join(using)}. Change that transport first."
        config.programs = [p for p in config.programs if p.get("name") != name]
        self._saved()
        return ""

    def save_rig(self, entry: dict, original: str = "") -> str:
        """Add or replace a Rigs entry; "" when saved, else why not."""
        config = self.core.config
        name = str(entry.get("name", "")).strip()
        if not name:
            return "Name this radio something: transports find it by that name."
        if name != original and any(r.get("name") == name for r in config.rigs):
            return f"{name!r} is already in use. Pick another name."
        values = _coerce(entry, RIG_FORM)
        if isinstance(values, str):
            return values
        if values["swr_trip"] <= 1.0:
            return "Stop transmitting above SWR must be more than 1.0."
        values.update(name=name)
        config.rigs = [r for r in config.rigs if r.get("name") not in (original, name)]
        config.rigs.append(values)
        if original and original != name:
            for transport in config.transports:
                if transport.get("rig") == original:
                    transport["rig"] = name
        self._saved()
        return ""

    def forget_rig(self, name: str) -> str:
        """Remove a Rigs entry; "" when removed, else why not."""
        config = self.core.config
        if not any(r.get("name") == name for r in config.rigs):
            return f"There is no radio named {name!r}."
        using = [t.get("name", "") for t in config.transports if t.get("rig") == name]
        if using:
            return f"{name!r} is still used by {', '.join(using)}. Change that transport first."
        config.rigs = [r for r in config.rigs if r.get("name") != name]
        self._saved()
        return ""

    # -- scripts --------------------------------------------------------------
    def scripts(self) -> list[dict]:
        """Each script by name and line count: its text may hold a password
        and never leaves the station (as an Address Book login script does)."""
        return [{"name": s["name"],
                 "lines": str(s.get("text", "")).count("\n") + 1 if s.get("text") else 0}
                for s in self.core.config.scripts if s.get("name")]

    def save_script(self, name: str, text: str, original: str = "") -> str:
        """"" when saved. Empty text on an edit keeps the saved text, since
        a client was never shown it."""
        config = self.core.config
        name = name.strip()
        if not name:
            return "Name this script: it is how a contact or setting finds it."
        if not text and original:
            text = next((str(s.get("text", "")) for s in config.scripts
                         if s.get("name") == original), "")
        config.scripts = [s for s in config.scripts if s.get("name") not in (original, name)]
        config.scripts.append({"name": name, "text": text})
        self._saved()
        return ""

    def forget_script(self, name: str) -> bool:
        config = self.core.config
        if not any(s.get("name") == name for s in config.scripts):
            return False
        config.scripts = [s for s in config.scripts if s.get("name") != name]
        self._saved()
        return True


def _field_dict(f) -> dict:
    return {"key": f.key, "label": f.label, "kind": f.kind, "placeholder": f.placeholder,
            "default": f.default, "optional": f.optional, "advanced": f.advanced,
            "choices": list(f.choices)}


def _coerce(entry: dict, form) -> dict | str:
    """The typed values of `entry` for `form`, or the first reason it will not do.

    A key the form does not show is dropped; a blank optional value is
    omitted so the file stays short."""
    out: dict = {}
    for f in form:
        raw = entry.get(f.key, f.default)
        if f.kind == "bool":
            out[f.key] = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "yes", "on")
            continue
        if f.kind == "bands":
            items = raw if isinstance(raw, (list, tuple)) else [b for b in str(raw).replace(",", " ").split()]
            bad = [b for b in items if b not in BANDS]
            if bad:
                return f"Not a band: {', '.join(map(str, bad))}."
            out[f.key] = list(items)
            continue
        text = str(raw if raw is not None else "").strip()
        if not text:
            if f.optional:
                continue
            if f.kind in ("number", "decimal") and f.default:
                text = f.default
            elif f.kind != "choice":
                return f"{f.label} is required."
        try:
            out[f.key] = int(text) if f.kind == "number" else float(text) if f.kind == "decimal" else text
        except ValueError:
            return f"{f.label} must be a number."
    return out
