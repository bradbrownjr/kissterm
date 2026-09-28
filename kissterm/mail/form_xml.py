"""Winlink form XML: the `RMS_Express_Form_*.xml` attachment (ROADMAP P2,
"Winlink forms").

Winlink Express sends a form twice: the readable text body, which every
client shows and `form_parse.py` reads, and an XML attachment holding
each field by its variable name, which a Winlink client opens in the
form's own viewer. This module reads that XML into a form's fields, so a
received form is shown from exactly what was filled in rather than from
kissterm's reading of the text.

**The format** is from Pat (github.com/la5nta/pat, MIT, commit 2e6a8d1),
`internal/forms/builder.go` `buildXML` (writing) and `forms.go`
`RenderForm` (reading), and Winlink Standard Forms 1.1.20.0, whose
viewers take `{var name}` from it::

    <?xml version="1.0" encoding="UTF-8"?>
    <RMS_Express_Form>
      <form_parameters>
        <xml_file_version>1.0</xml_file_version>
        <rms_express_version>...</rms_express_version>
        <submission_datetime>20260928143000</submission_datetime>  (UTC)
        <senders_callsign>KC1JMH</senders_callsign>
        <grid_square>FN43</grid_square>
        <display_form>ICS213_Initial_Viewer.html</display_form>
        <reply_template>ICS213_SendReply.0</reply_template>
      </form_parameters>
      <variables>
        <inc_name>...</inc_name> ...
      </variables>
    </RMS_Express_Form>

The attachment is named `RMS_Express_Form_<display form without .html>
.xml` (Pat's `xmlName`). **A form is matched by its `display_form`**,
the viewer file name, against each shipped form's `[winlink] viewer`;
the variable names are compared without case, as Winlink's viewers and
Pat do. # UNVERIFIED: the case Winlink Express itself writes names in;
Pat writes them all lowercase and Winlink Express reads Pat's forms.

A `rows` field (the 213RR's order lines) is numbered in the XML, one
variable per cell: `Qty1` ... `Qty8`, the column id and the line number,
as the viewers name them.

**A Winlink form kissterm does not ship** (there are hundreds) is still
shown: its variables as a plain list under the viewer's name, empty
ones and Winlink's own bookkeeping left out.

**The XML is remote input.** It is parsed only when it is small, and one
holding a DOCTYPE (where entity expansion lives) is refused outright;
every value is still sanitized by the reader (`ui/form_view.py`).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ..winlink.message import B2Error
from ..winlink.message import parse as parse_b2
from .form_parse import Parsed
from .forms import Field, FormDef, Values, load_forms

#: The attachment's name: `RMS_Express_Form_<viewer>.xml`.
_NAME_RE = re.compile(r"^RMS_Express_Form_.*\.xml$", re.IGNORECASE)
#: Larger than any form: the ICS-309's thirty lines are a few kilobytes.
MAX_XML = 256 * 1024
#: Variables Winlink and Pat add to every form, never the operator's.
BOOKKEEPING = frozenset({
    "msgto", "msgcc", "msgsender", "msgsubject", "msgbody", "msgp2p", "msgisreply",
    "msgisforward", "msgisacknowledgement", "msgseqnum", "msgoriginalbody", "txtstr",
    "parseme", "templateversion", "timestamp", "timestamp2", "submit", "formdata",
    "addformat", "attached_file", "attached_text", "nospaces", "withspaces",
})


@dataclass(frozen=True)
class FormXml:
    """One form attachment: its parameters and its variables, in order."""

    parameters: dict[str, str]
    variables: dict[str, str]

    @property
    def display_form(self) -> str:
        return self.parameters.get("display_form", "")

    def get(self, name: str) -> str:
        wanted = name.lower()
        return next((v for k, v in self.variables.items() if k.lower() == wanted), "")


def is_form_attachment(name: str) -> bool:
    return bool(_NAME_RE.match(name.strip()))


def parse(data: bytes) -> FormXml:
    """Read a form attachment. Raises `ValueError` if it is not one."""
    if len(data) > MAX_XML:
        raise ValueError("larger than any form")
    if b"<!doctype" in data.lower() or b"<!entity" in data.lower():
        raise ValueError("a form never has a DOCTYPE")
    try:
        root = ET.fromstring(data.removeprefix(b"\xef\xbb\xbf"))
    except ET.ParseError as exc:
        raise ValueError(f"not XML ({exc})") from None
    if root.tag != "RMS_Express_Form":
        raise ValueError("no RMS_Express_Form element")
    sections = {"form_parameters": {}, "variables": {}}
    for section in root:
        if section.tag in sections:
            for element in section:
                sections[section.tag][element.tag] = "".join(element.itertext())
    return FormXml(sections["form_parameters"], sections["variables"])


def from_files(files: list[tuple[str, bytes]]) -> FormXml | None:
    """The form attachment among a message's files, or None."""
    for name, data in files:
        if is_form_attachment(name):
            try:
                return parse(data)
            except ValueError:
                return None
    return None


def from_raw(paths: list[Path]) -> FormXml | None:
    """The form attachment kept beside a stored message: inside its raw
    `.b2f` copy (a received Winlink message), or an `.xml` of our own."""
    for path in paths:
        try:
            if path.suffix.lower() == ".xml":
                return parse(path.read_bytes())
            if path.suffix.lower() == ".b2f":
                found = from_files(parse_b2(path.read_bytes()).files)
                if found is not None:
                    return found
        except (OSError, ValueError, B2Error):
            continue
    return None


def _viewer_key(name: str) -> str:
    """"ICS213_Initial_Viewer.html" and "ics213_initial_viewer" alike."""
    name = name.strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    return name.removesuffix(".html")


def form_for(found: FormXml) -> FormDef | None:
    """The shipped form whose Winlink viewer this is, or None."""
    key = _viewer_key(found.display_form)
    if not key:
        return None
    return next((f for f in load_forms() if f.winlink_viewer and _viewer_key(f.winlink_viewer) == key),
                None)


def values(form: FormDef, found: FormXml) -> Values:
    """The form's values from the XML (module docstring)."""
    out: Values = {}
    for f in form.fields:
        if f.kind == "rows":
            rows = []
            for number in range(1, (f.max_rows or 0) + 1):
                row = {c.id: found.get(f"{c.id}{number}").strip() for c in f.columns}
                if any(row.values()):
                    rows.append(row)
            out[f.id] = rows
        elif f.kind == "check":
            out[f.id] = "1" if found.get(f.id).strip() else ""
        else:
            out[f.id] = found.get(f.id).strip("\r\n")
    return out


def _title(found: FormXml) -> str:
    viewer = found.display_form.strip().rsplit("/", 1)[-1]
    viewer = re.sub(r"(?i)\.html?$", "", viewer)
    viewer = re.sub(r"(?i)_?(initial_)?viewer$", "", viewer).replace("_", " ").strip()
    return f"Winlink form: {viewer}" if viewer else "Winlink form"


def generic(found: FormXml) -> FormDef:
    """A form kissterm does not ship, as one field per filled variable."""
    fields = tuple(
        Field(id=name, label=name, kind="multiline" if "\n" in value.strip() else "text")
        for name, value in found.variables.items()
        if value.strip() and name.lower() not in BOOKKEEPING
    )
    return FormDef(id="winlink-xml", title=_title(found), source="received XML", subject="",
                   body="", fields=fields)


def read(found: FormXml) -> Parsed:
    """The attachment as a form to show: the shipped form it belongs to,
    or `generic` when there is none."""
    form = form_for(found)
    if form is None:
        form = generic(found)
        return Parsed(form, {f.id: found.variables[f.id].strip("\r\n") for f in form.fields}, 1.0,
                      dict(found.variables))
    return Parsed(form, values(form, found), 1.0, dict(found.variables))
