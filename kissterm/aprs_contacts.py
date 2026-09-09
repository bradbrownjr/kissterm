"""The APRS messaging contact list -- shape and validation only, no storage.

Deliberately separate from `kissterm/addressbook.py`'s station list: an
address-book entry is a *node or BBS you connect to*, and an APRS contact is
a *person or gateway service you message over APRS*. The two are different
enough in kind -- one drives the connect flow and AX.25 session state, the
other drives a UI-frame message and has nothing to do with connections at
all -- that folding them into one list would make each entry's fields mean
different things depending on what it was for, the exact trap
`Config.credentials`/`Config.scripts` docstrings warn against for a
different pair of lists in this same file.

Storage is `Config.aprs_contacts` (`kissterm/config.py`), a plain
`list[dict[str, Any]]` loaded/saved by the same generic `_load_dict_list` /
`_dump_toml` machinery `credentials`/`scripts`/`transports` already use --
this module holds no persistence of its own, only the dict shape and the
validation both the config loader and the Contacts editor screen need to
share.

`service` picks which compose mode a contact defaults to in the APRS pane:

- `"station"` -- `callsign` is the contact's own APRS addressee. Sent text
  goes out as-is.
- `"sms"` / `"email"` -- `callsign` is the SMS/email GATEWAY's addressee
  (e.g. a station that relays messages addressed to it onward to a phone
  number or inbox), and `detail` holds the phone number or email address
  that gateway needs to know who to deliver to. **Which gateway callsign and
  message-body format actually work is not something this codebase can
  verify from here** -- gateway conventions vary and change over time. See
  `kissterm/aprs_pane.py`'s docstring and `Config.aprs_sms_template` /
  `Config.aprs_email_template` for where the body gets built and why those
  defaults are marked unverified rather than asserted as fact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = [
    "Contact",
    "SERVICES",
    "DEFAULT_SMS_TEMPLATE",
    "DEFAULT_EMAIL_TEMPLATE",
    "normalize_contact",
    "validate_contact",
    "build_message_body",
]

#: The only service values the UI offers. Anything else in a hand-edited
#: config.toml falls back to "station" -- see `normalize_contact`.
SERVICES = ("station", "sms", "email")

#: Matches `Config.aprs_sms_template`/`aprs_email_template`'s own defaults --
#: kept here too so `build_message_body` has a safe fallback that does not
#: require importing `kissterm.config` (which would invert this package's
#: dependency direction: `config.py` already documents these gateway
#: fields in terms of this module, not the other way around).
DEFAULT_SMS_TEMPLATE = "{detail} {text}"
DEFAULT_EMAIL_TEMPLATE = "{detail} {text}"


@dataclass(frozen=True, slots=True)
class Contact:
    """One APRS messaging contact. `to_dict`/`from_dict` are the only
    translation this needs to and from `Config.aprs_contacts`' loose dicts.
    """

    name: str
    callsign: str
    service: str = "station"
    detail: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Contact":
        return cls(
            name=str(data.get("name", "")),
            callsign=str(data.get("callsign", "")).strip().upper(),
            service=normalize_service(str(data.get("service", "station"))),
            detail=str(data.get("detail", "")),
            notes=str(data.get("notes", "")),
        )


def normalize_service(service: str) -> str:
    """A value from `SERVICES`, or `"station"` for anything unrecognised --
    the same "degrade this one field rather than the whole entry" rule
    `config.py`'s loader applies everywhere else."""
    service = service.strip().lower()
    return service if service in SERVICES else "station"


def validate_contact(name: str, callsign: str, service: str, detail: str) -> str:
    """The problem with these fields as a saveable contact, or `""` if none.

    Called from the Contacts editor screen before it dismisses, the same
    role `AddressBookEntryScreen`'s own inline checks play -- catch a typo
    at the one moment the operator is still looking at the form, rather than
    writing a contact that quietly cannot be messaged.
    """
    if not name.strip():
        return "Name this contact something -- it is how you will find it in the list."
    callsign = callsign.strip().upper()
    if not callsign or len(callsign) > 9:
        return "Callsign (the APRS addressee to send to) must be 1-9 characters."
    service = normalize_service(service)
    if service in ("sms", "email") and not detail.strip():
        kind = "phone number" if service == "sms" else "email address"
        return f"An SMS/email contact needs a {kind} in the detail field."
    return ""


def normalize_contact(data: dict) -> Contact | None:
    """A `Contact` from a raw config dict, or `None` if it is unsalvageable
    (no name and no callsign -- everything else has a safe default)."""
    name = str(data.get("name", "")).strip()
    callsign = str(data.get("callsign", "")).strip().upper()
    if not name and not callsign:
        return None
    return Contact.from_dict(data)


def build_message_body(
    service: str, detail: str, text: str, *, sms_template: str = "", email_template: str = ""
) -> str:
    """The actual on-air message body for `text`.

    `"station"` sends `text` unchanged. `"sms"`/`"email"` run it through a
    template pairing `detail` (the contact's phone number or email address)
    with `text` -- `sms_template`/`email_template` are normally
    `Config.aprs_sms_template`/`aprs_email_template`, falling back to
    `DEFAULT_SMS_TEMPLATE`/`DEFAULT_EMAIL_TEMPLATE` for an empty string
    (never asserted as the one correct gateway format -- see this module's
    docstring).

    A hand-edited template with a typo'd placeholder (anything but
    `{detail}`/`{text}`) falls back to the default rather than raising --
    a malformed template must not be the reason a message never goes out.
    """
    service = normalize_service(service)
    if service == "station":
        return text
    default = DEFAULT_SMS_TEMPLATE if service == "sms" else DEFAULT_EMAIL_TEMPLATE
    template = (sms_template if service == "sms" else email_template) or default
    try:
        return template.format(detail=detail, text=text)
    except (KeyError, IndexError):
        return default.format(detail=detail, text=text)
