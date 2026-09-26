"""Message forms: ICS-213 and the rest, as data files rendered to text.

ROADMAP P2 (forms). A form is a TOML file in `data/forms/`: its fields and
the plain-text body and subject they fill. This module loads those files,
fills in defaults, checks what the operator typed, and renders the text;
`kissterm/ui/form_screen.py` shows a form, and the finished text goes back
into the compose screen for To, @ and Save, so a form is sent like any
other message and **nothing here transmits**.

**Why the layouts are copied, not designed.** A form is only useful if the
station at the other end recognises it. Winlink Express sends a form twice
-- an XML attachment its own viewer shows, and the same data as readable
text in the body -- and that text is what everyone else reads: a BBS
user, a Pat user, a printer. So each body here reproduces the Winlink
standard template's `Msg:` text, field names and limits as published,
with the form's own numbering from the agency that owns it (FEMA for ICS).
The source and template version are recorded in each data file (`source`)
and listed in `docs/PROTOCOL_GUIDE.md`.

**Where it differs from Winlink's text, on purpose:**

- Winlink ends each body with `Express Sending Station`, `Senders Express
  Version` and "[No changes or editing of this message are allowed]".
  kissterm is not Winlink Express and says so by leaving them out; the
  sender is in the message header anyway. The `[Sender: ... Lat: Lon:
  MGRS]` line is left out too: kissterm does not send a position unasked.
- A template line that holds only variables, all empty, is dropped (the
  exercise banner when the box is not ticked, an empty form title),
  rather than sent as a blank line.
- Repeated rows (the 213RR order lines) are written once per filled row,
  not as eight empty blocks. `<each order>` ... `</each>` in the template
  marks the block.

Computed values, as the Winlink forms compute them in the browser: a
field's `derived` values (the Severe WX report's metric figures from the
imperial ones, to two decimals as its `toFixed(2)`), a `rows` column's
`sum_of` (the Damage Assessment's per-category total) and a form's
`totals` (the sum of a column over all lines). They are rendered only;
the operator never types them.

**Information strips** (MARS/SHARES style, and the local GYX WEATHER
SKYWARN strip): `TITLE/prompt/prompt/.../prompt//` asks for one answer
per prompt, and the answer is the same shape, `TITLE/answer/.../answer//`,
one line, so a net can paste the answers into a spreadsheet. A form with
a `strip` template gets one field per prompt; `strip_form()` builds the
same from any strip pasted or found in a received message. The rules are
bpq-apps' (`forms.py` fill_strip_form, same author):

- a `/` inside parentheses belongs to the prompt ("(@0=Local/Regional
  Chain, ...)" in MCF720), not a separator -- forms.py split on it;
- an answer may not contain `/` (it would add a field);
- an empty answer is three spaces. # UNVERIFIED: bpq-apps calls this the
  MARS convention; no published source was found for it.

`<if name>` ... `</if>` keeps a block only when that field is filled
(the PKTNET check-in's agency line and the blank line after it). A form's
`to_field` is the field that becomes the compose screen's To, and its
`subject_var`, if set, lets the body quote the rendered subject (the
Winlink check-in's "0b: Subject:").

**Template syntax** is Winlink's: `<var name>` is replaced by the field's
value (names compared without case, as Winlink's are), so a template's
`Msg:` section can be pasted in. The XML attachment is ROADMAP P2's
Winlink step: the field ids here are Winlink's variable names so that XML
can be built from the same values.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

#: Field kinds a form file may use.
KINDS = ("text", "multiline", "choice", "date", "time", "datetime", "check", "rows", "strip")

_VAR_RE = re.compile(r"<var\s+(\w+)\s*>", re.IGNORECASE)
_EACH_RE = re.compile(r"<each\s+(\w+)\s*>\n?(.*?)</each>\n?", re.IGNORECASE | re.DOTALL)
_IF_RE = re.compile(r"<if\s+(\w+)\s*>\n?(.*?)</if>\n?", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Column:
    """One column of a `rows` field."""

    id: str
    label: str
    max_length: int = 0
    choices: tuple[str, ...] = ()
    #: Rendered as the sum of these columns of the same line.
    sum_of: tuple[str, ...] = ()
    #: "money": rendered `$ 1,234` as Winlink's formatNumber() writes it.
    format: str = ""


@dataclass(frozen=True)
class Derived:
    """A value computed from a number field: `value * factor`."""

    id: str
    factor: float
    decimals: int = 2


@dataclass(frozen=True)
class Total:
    """A value computed as the sum of one column over all lines."""

    id: str
    rows: str
    column: str
    format: str = ""


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    kind: str = "text"
    required: bool = False
    max_length: int = 0
    help: str = ""
    placeholder: str = ""
    choices: tuple[str, ...] = ()
    default: str = ""
    #: "mycall": the operator's call sign without SSID; "grid": the
    #: station's grid square from Settings > APRS, when it has a position.
    auto: str = ""
    #: A `date`, `time` or `datetime` field's strftime pattern, when the
    #: template's own "now" button differs from the default.
    format: str = ""
    #: A date/time default in UTC rather than local time.
    utc: bool = False
    derived: tuple[Derived, ...] = ()
    #: Another field shown on this field's row (a status and its comment).
    beside: str = ""
    #: A `check` field's value when ticked (Winlink's exercise banner).
    on_value: str = ""
    #: Kept between forms: the station half (who you are, your position),
    #: never the message half.
    remember: bool = False
    columns: tuple[Column, ...] = ()
    max_rows: int = 0


@dataclass(frozen=True)
class FormDef:
    id: str
    title: str
    source: str
    subject: str
    body: str
    fields: tuple[Field, ...]
    #: Where the finished message usually goes: `P` or `B`, and a To/@ to
    #: suggest (a check-in's net address).
    send_type: str = "P"
    to: str = ""
    at: str = ""
    to_field: str = ""
    subject_var: str = ""
    totals: tuple[Total, ...] = ()
    #: An information strip's template; the fields are its prompts.
    strip: str = ""

    def field(self, field_id: str) -> Field:
        return next(f for f in self.fields if f.id == field_id)


# -- loading -----------------------------------------------------------------


def _field(raw: dict[str, Any]) -> Field:
    kind = raw.get("kind", "text")
    if kind not in KINDS:
        raise ValueError(f"field {raw.get('id')!r}: unknown kind {kind!r}")
    columns = tuple(
        Column(**{**c, "choices": tuple(c.get("choices", ())), "sum_of": tuple(c.get("sum_of", ()))})
        for c in raw.get("columns", ())
    )
    derived = tuple(Derived(**d) for d in raw.get("derived", ()))
    return Field(**{**raw, "choices": tuple(raw.get("choices", ())), "columns": columns,
                    "derived": derived})


def split_strip(text: str) -> tuple[str, list[str]]:
    """`TITLE/a/b//` -> ("TITLE", ["a", "b"]); a `/` inside parentheses
    stays in its segment, and an unmatched `)` is ignored."""
    text = " ".join(text.split())
    text = text[:-2] if text.endswith("//") else text.rstrip("/")
    segments, current, depth = [], [], 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        if char == "/" and depth == 0:
            segments.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    segments.append("".join(current).strip())
    return segments[0], [s for s in segments[1:] if s]


_CALL_PROMPT_RE = re.compile(r"^(HAM )?CALL ?SIGN\b", re.IGNORECASE)
_GRID_PROMPT_RE = re.compile(r"^(MAIDENHEAD )?GRID\b", re.IGNORECASE)
_LABEL_WIDTH = 16


def _strip_label(prompt: str) -> str:
    """A prompt cut to the label column: before any "(", at a word when
    that keeps at least half of it; the help line shows it whole."""
    short = prompt.split("(")[0].strip(" :),&") or prompt
    if len(short) <= _LABEL_WIDTH:
        return short
    cut = short[:_LABEL_WIDTH + 1].rsplit(" ", 1)[0].rstrip(" ,&:")
    return cut if len(cut) >= _LABEL_WIDTH // 2 else short[:_LABEL_WIDTH - 1] + "."


def _strip_fields(prompts: list[str]) -> tuple[Field, ...]:
    fields = []
    for number, prompt in enumerate(prompts, 1):
        auto = ("mycall" if _CALL_PROMPT_RE.match(prompt)
                else "grid" if _GRID_PROMPT_RE.match(prompt) else "")
        # The placeholder is the prompt's hint, "(MM-DD-YYYY)" -> MM-DD-YYYY.
        hint = prompt.partition("(")[2].rsplit(")", 1)[0].strip()
        fields.append(Field(id=f"s{number}", label=_strip_label(prompt), help=prompt,
                            placeholder=hint, auto=auto))
    return tuple(fields)


def strip_form(text: str, *, form_id: str = "strip", title: str = "", source: str = "") -> FormDef:
    """A form answering one information strip."""
    strip_title, prompts = split_strip(text)
    if not strip_title or not prompts:
        raise ValueError("A strip is TITLE/prompt/.../prompt// with at least one prompt.")
    return FormDef(id=form_id, title=title or f"{strip_title} (strip)", source=source or "pasted strip",
                   subject=strip_title, body="", fields=_strip_fields(prompts), strip=text)


_STRIP_LINE_RE = re.compile(r"^\s*[A-Z0-9][^/\n]*/.*//\s*$", re.IGNORECASE)


def find_strip(body: str) -> str:
    """The first information strip in a message body, "" if none. A strip
    wrapped over several lines by a mail reader is joined back up."""
    lines = body.splitlines()
    for start, line in enumerate(lines):
        if "/" not in line or not re.match(r"^\s*[A-Z0-9][A-Z0-9 ]*/", line, re.IGNORECASE):
            continue
        for end in range(start, min(start + 20, len(lines))):
            joined = " ".join(l.strip() for l in lines[start:end + 1])
            if _STRIP_LINE_RE.match(joined):
                return joined.strip()
    return ""


def parse_form(text: str) -> FormDef:
    raw = tomllib.loads(text)
    if "strip" in raw and "fields" not in raw:
        return strip_form(raw["strip"], form_id=raw["id"], title=raw["title"], source=raw["source"])
    fields = tuple(_field(f) for f in raw.pop("fields"))
    totals = tuple(Total(**t) for t in raw.pop("totals", ()))
    form = FormDef(**raw, fields=fields, totals=totals)
    names = {f.id.lower() for f in fields} | {
        c.id.lower() for f in fields for c in f.columns
    } | {d.id.lower() for f in fields for d in f.derived} | {
        t.id.lower() for t in totals
    } | ({form.subject_var.lower()} if form.subject_var else set())
    conditions = [m.group(1) for m in _IF_RE.finditer(form.body)]
    for name in _VAR_RE.findall(form.body + form.subject) + conditions:
        if name.lower() not in names:
            raise ValueError(f"form {form.id!r}: template uses unknown <var {name}>")
    return form


@lru_cache(maxsize=1)
def load_forms() -> tuple[FormDef, ...]:
    """Every shipped form, in title order."""
    folder = resources.files("kissterm.mail") / "data" / "forms"
    forms = [parse_form(p.read_text(encoding="utf-8"))
             for p in folder.iterdir() if p.name.endswith(".toml")]
    return tuple(sorted(forms, key=lambda f: f.title))


#: The first step of answering any strip: paste it. `strip_form()` of
#: what comes back is the second.
PASTE_STRIP = FormDef(
    id="strip", title="Information strip (paste)", source="bpq-apps strip.frm",
    subject="", body="<var strip>",
    fields=(Field(id="strip", label="Request strip", kind="strip", required=True,
                  help="Paste the request strip: TITLE/question/question/.../question//"),),
)


def get_form(form_id: str) -> FormDef:
    if form_id == PASTE_STRIP.id:
        return PASTE_STRIP
    return next(f for f in load_forms() if f.id == form_id)


# -- values ------------------------------------------------------------------

#: A form's values: field id -> text, or for a `rows` field a list of
#: {column id: text} dicts.
Values = dict[str, Any]


_TIME_FORMATS = {"date": "%Y-%m-%d", "time": "%H:%M", "datetime": "%Y-%m-%d %H:%M"}


def defaults(form: FormDef, *, mycall: str = "", grid: str = "",
             remembered: Values | None = None, now: datetime | None = None) -> Values:
    """The values a new form opens with. Dates and times are local, as the
    Winlink templates' "now" buttons fill them (`2026-09-26`, `14:05`)."""
    local = now or datetime.now()
    utc = now or datetime.now(timezone.utc)
    remembered = remembered or {}
    values: Values = {}
    for f in form.fields:
        if f.kind == "rows":
            values[f.id] = []
        elif f.kind == "check":
            values[f.id] = ""
        elif f.remember and remembered.get(f.id):
            values[f.id] = remembered[f.id]
        elif f.auto == "mycall":
            values[f.id] = mycall.split("-")[0].upper()
        elif f.auto == "grid":
            values[f.id] = grid
        elif f.kind in _TIME_FORMATS:
            values[f.id] = (utc if f.utc else local).strftime(f.format or _TIME_FORMATS[f.kind])
        else:
            values[f.id] = f.default
    return values


def to_remember(form: FormDef, values: Values) -> Values:
    return {f.id: values.get(f.id, "") for f in form.fields if f.remember}


def load_remembered(path: Path, form_id: str) -> Values:
    """The remembered fields of one form, from `forms.json`; {} when the
    file is missing or unreadable (it is a convenience, never needed)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entry = data.get(form_id) if isinstance(data, dict) else None
    return {k: v for k, v in entry.items() if isinstance(v, str)} if isinstance(entry, dict) else {}


def save_remembered(path: Path, form_id: str, values: Values) -> None:
    """Store one form's remembered fields; a failed write is ignored."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[form_id] = values
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def filled_rows(field_def: Field, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if any(str(r.get(c.id, "")).strip() for c in field_def.columns)]


def problems(form: FormDef, values: Values) -> list[str]:
    """What stops the form being finished, one line per field."""
    found = []
    for f in form.fields:
        value = values.get(f.id, "")
        if form.strip and "/" in str(value):
            found.append(f"{f.label}: an answer cannot contain / (it separates the answers).")
            continue
        if f.kind == "rows":
            rows = filled_rows(f, value or [])
            if f.required and not rows:
                found.append(f"{f.label}: add at least one line.")
            for number, row in enumerate(rows, 1):
                for c in f.columns:
                    if c.max_length and len(row.get(c.id, "")) > c.max_length:
                        found.append(f"{f.label} line {number}: {c.label} is at most "
                                     f"{c.max_length} characters.")
            continue
        text = str(value).strip()
        if f.required and not text:
            found.append(f"{f.label} is needed.")
        elif f.max_length and len(text) > f.max_length:
            found.append(f"{f.label} is at most {f.max_length} characters.")
        elif f.kind == "choice" and text and text not in f.choices:
            found.append(f"{f.label}: choose one of {', '.join(f.choices)}.")
        elif f.kind == "strip" and text and not find_strip(text):
            found.append("That is not a strip: TITLE/question/.../question// on one line.")
        elif f.derived and text and _number(text) is None:
            found.append(f"{f.label} is a number.")
    return found


# -- rendering ---------------------------------------------------------------


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _format_number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _whole_or_cents(value: float) -> str:
    return _format_number(value, 0 if value == int(value) else 2)


def _money(text: str) -> str:
    number = _number(text.replace("$", "").strip())
    if number is None:
        return text
    whole = f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"
    return f"$ {whole}"


def _row_values(field_def: Field, row: dict[str, str]) -> dict[str, str]:
    values = {c.id: str(row.get(c.id, "")).strip() for c in field_def.columns}
    for c in field_def.columns:
        if c.sum_of:
            numbers = [_number(values.get(i, "")) for i in c.sum_of]
            if any(n is not None for n in numbers):
                values[c.id] = _whole_or_cents(sum(n for n in numbers if n is not None))
        if c.format == "money" and values.get(c.id):
            values[c.id] = _money(values[c.id])
    return values


def _fill(template: str, values: dict[str, str]) -> str:
    lowered = {k.lower(): v for k, v in values.items()}
    lines = []
    for line in template.split("\n"):
        names = _VAR_RE.findall(line)
        filled = _VAR_RE.sub(lambda m: lowered.get(m.group(1).lower(), ""), line)
        if names and not _VAR_RE.sub("", line).strip() and not filled.strip():
            continue  # a line of empty variables only
        lines.append(filled.rstrip())
    return "\n".join(lines)


def render(form: FormDef, values: Values) -> tuple[str, str]:
    """(subject, body) as they will be sent."""
    if form.strip:
        answers = [" ".join(str(values.get(f.id, "")).split()) or "   " for f in form.fields]
        return form.subject, f"{form.subject}/{'/'.join(answers)}//\n"
    flat = {f.id: str(values.get(f.id, "")).strip() for f in form.fields if f.kind != "rows"}
    for f in form.fields:
        if f.kind == "check":
            flat[f.id] = f.on_value if values.get(f.id) else ""
        elif f.kind == "multiline":
            flat[f.id] = str(values.get(f.id, "")).rstrip()
        number = _number(flat.get(f.id, "")) if f.derived else None
        for d in f.derived:
            flat[d.id] = "" if number is None else _format_number(number * d.factor, d.decimals)
    for t in form.totals:
        rows_field = form.field(t.rows)
        column = [_number(str(r.get(t.column, "")).replace("$", "").strip())
                  for r in filled_rows(rows_field, values.get(t.rows) or [])]
        present = [n for n in column if n is not None]
        total = _whole_or_cents(sum(present)) if present else ""
        flat[t.id] = _money(total) if total and t.format == "money" else total

    def each(match: re.Match) -> str:
        rows_field = form.field(match.group(1))
        rows = filled_rows(rows_field, values.get(rows_field.id) or [])
        chunks = (_fill(match.group(2), _row_values(rows_field, r)) for r in rows)
        return "".join(c if c.endswith("\n") else c + "\n" for c in chunks)

    subject = " ".join(_fill(form.subject, flat).split())
    if form.subject_var:
        flat[form.subject_var] = subject
    lowered = {k.lower(): v for k, v in flat.items()}
    template = _IF_RE.sub(lambda m: m.group(2) if lowered.get(m.group(1).lower()) else "", form.body)
    body = _fill(_EACH_RE.sub(each, template), flat).strip("\n") + "\n"
    return subject, body
