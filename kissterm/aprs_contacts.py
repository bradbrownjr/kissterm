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

A contact separately carries `gateway`, an id into the shipped directory in
`kissterm/aprs_services/` -- which service's command set to offer when
composing to it. That is a different question from `service` above and the
two must not be collapsed; see `Contact.gateway`'s own comment.

`CannedMessage` at the bottom is the operator's OWN saved message text
(`Config.aprs_templates`), as opposed to the shipped command templates the
directory provides. Both feed the same picker, which is the point: from the
operator's side "message WXBOT for tomorrow's forecast" and "my standard
net check-in" are the same kind of thing, even though one ships with the
app and the other does not.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = [
    "CannedMessage",
    "Contact",
    "SERVICES",
    "DEFAULT_SMS_TEMPLATE",
    "DEFAULT_EMAIL_TEMPLATE",
    "canned_messages_for",
    "normalize_contact",
    "validate_canned_message",
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
DEFAULT_SMS_TEMPLATE = "@{detail} {text}"
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
    #: Which shipped gateway service this contact IS, as a
    #: `kissterm/aprs_services/data/*.toml` id -- empty for an ordinary
    #: person. Set it and the APRS pane's template picker offers that
    #: service's command set for this contact.
    #:
    #: **`gateway` and `service` above are not the same thing, and the two
    #: names are close enough to confuse.** `service` says how
    #: `build_message_body` wraps what the operator typed (plain text, or a
    #: template pairing `detail` with it); `gateway` says whose command
    #: vocabulary to show. A contact can legitimately be
    #: `service="sms", gateway="smsgte"` -- one decides the bytes, the other
    #: decides the help. A contact can also have a `gateway` and
    #: `service="station"` (WXBOT takes plain text, and has a command set),
    #: or a `service` and no `gateway` (an SMS gateway this directory has
    #: never heard of, typed in by hand).
    #:
    #: An id no longer in the shipped directory degrades to "no templates
    #: offered" rather than erroring -- a service can be retired between
    #: kissterm versions, and that must not make an operator's saved contact
    #: unusable for the plain messaging it could always do.
    gateway: str = ""

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
            gateway=str(data.get("gateway", "")).strip(),
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


@dataclass(frozen=True, slots=True)
class CannedMessage:
    """One message the operator saved to send again (`Config.aprs_templates`).

    `gateway` scopes it: a directory id shows it only when composing to that
    service, and an empty string makes it global. That single field is what
    lets one storage shape answer both halves of the request behind this
    feature -- "attach templates to the contact rather than one long shared
    list", and "let me save canned messages globally". A `WLNK-1`-scoped
    "SP" line and a global "QRV, monitoring 146.520" live in the same list
    and are told apart by where they show up, not by which list they are in.

    Flat `str` fields on purpose: `Config`'s TOML writer (`_dump_toml`) only
    knows arrays of FLAT tables, so anything nested here would need a new
    writer shape for no gain.
    """

    name: str
    text: str
    gateway: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CannedMessage":
        return cls(
            name=str(data.get("name", "")).strip(),
            text=str(data.get("text", "")),
            gateway=str(data.get("gateway", "")).strip(),
        )


def validate_canned_message(name: str, text: str) -> str:
    """The problem with these as a saveable canned message, or `""`.

    Same role as `validate_contact`: catch it while the operator is still
    looking at the form. Empty text is the one that matters -- a saved
    message with nothing in it would insert nothing and look like the
    picker was broken.
    """
    if not name.strip():
        return "Name this message -- it is how you will find it in the list."
    if not text.strip():
        return "A saved message needs some text; an empty one would insert nothing."
    return ""


def canned_messages_for(raw_templates: list[dict], gateway: str) -> list[CannedMessage]:
    """The operator's saved messages applicable to `gateway`, scoped first.

    Ordering is deliberate: messages saved for THIS service come before the
    global ones, because someone composing to `WLNK-1` is far more likely to
    want their saved Winlink line than their generic net check-in, and a
    picker that makes them scroll past the general case to reach the
    specific one has the priority backwards.

    An entry with a name but no text is dropped rather than shown -- see
    `validate_canned_message` for why an empty one is useless, and
    `config.py`'s loader discipline for why a hand-edited file's bad entry
    degrades instead of raising.
    """
    gateway = gateway.strip()
    scoped: list[CannedMessage] = []
    globals_: list[CannedMessage] = []
    for raw in raw_templates:
        message = CannedMessage.from_dict(raw)
        if not message.name or not message.text.strip():
            continue
        if not message.gateway:
            globals_.append(message)
        elif gateway and message.gateway == gateway:
            scoped.append(message)
    return scoped + globals_


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
