"""Reading a received form back into its fields (ROADMAP P2, "Received
forms render as forms").

A form message on a BBS is plain text -- the Winlink template's text body,
which is what `forms.render` sends and what Winlink Express sends as its
readable body -- so the only way to show it as a form is to read that text
against the same template. **The template is the parser**: each template
line becomes a line matcher, so a new form file is recognised with no code,
and the round trip (render, then parse) is the test
(`tests/unit/test_form_parse.py`).

How a template line is read:

- A line with literal text and variables (`4. Subject: <var Subjectline>`)
  is a regular expression: the literal part matches with any spacing, each
  variable captures what lies between. Two variables separated by a tab
  split on a tab or on exactly four spaces, which is what a tab becomes in
  a saved message (`compose.clean_text`).
- A line that is only a variable (`<var Message>`) takes the next body
  line; a multi-line field takes every line up to the next that matches a
  later template line, blank lines included.
- A line of only tab-separated variables inside `<each>` (the ICS-205 and
  ICS-214 tables) is a table row: each body line is one row, split on tabs.
- Inside `<each>`, a line that matches an earlier line of the same block
  starts the next row (the 309's `TIME:`).

A variable found only in the subject (PKTNET's town and state) is read
from the subject, against the form's subject pattern. A line of only
variables separated by single spaces (`<var Declaration> <var
DecDateTime>`) cannot be split: the whole line goes to the first
(`ambiguous()` names the rest), shown under its label as sent.

Lines the template does not have (Winlink Express's footer, its location
line) are skipped, and lines the sender left out are simply not found:
the template's own rule drops a line whose variables are all empty.

**Recognising** a message is conservative, because a wrong form shown
confidently is worse than the plain text (AGENTS.md section 7): our own
messages carry a `Form:` header; anything else must match the form's
subject pattern (when it has distinctive literal text) and most of the
template's labelled lines. An information strip is recognised by its
title (`GYX WEATHER/...//`) against the shipped strip forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .forms import (
    _EACH_RE,
    _IF_RE,
    _VAR_RE,
    FormDef,
    Values,
    find_strip,
    get_form,
    load_forms,
    split_strip,
)

#: A tab as sent, or as `clean_text` saved it.
_TAB_SPLIT = re.compile(r"\t| {4}")
#: Share of the labelled template lines a body must match to be that form.
MIN_SCORE = 0.6


@dataclass
class _Item:
    kind: str  # "line", "free" or "row"
    names: list[str]
    regex: re.Pattern | None = None
    block: str = ""
    #: Literal text worth counting towards recognition.
    labelled: bool = False


@dataclass
class Parsed:
    """A received message read as a form: its values and how sure we are."""

    form: FormDef
    values: Values
    score: float
    #: Every variable found, by template name (derived figures, totals).
    found: dict[str, str] = field(default_factory=dict)


def _line_regex(line: str) -> re.Pattern:
    parts = re.split(r"(<var\s+\w+\s*>)", line, flags=re.IGNORECASE)
    pattern = [r"^\s*"]
    for index, part in enumerate(parts):
        name = _VAR_RE.fullmatch(part)
        if name:
            last = all(not p.strip() for p in parts[index + 1:])
            pattern.append(f"(?P<{name.group(1).lower()}>.*)" if last else
                           f"(?P<{name.group(1).lower()}>.*?)")
            continue
        between_vars = 0 < index < len(parts) - 1 and not part.strip()
        if between_vars and "\t" in part:
            pattern.append(r"(?:\t| {4})")
        elif between_vars:
            pattern.append(re.escape(part))
        else:
            pieces = [re.escape(p) for p in part.split()]
            if pieces:
                lead = r"\s*" if part[:1].isspace() else ""
                trail = r"\s*" if part[-1:].isspace() else ""
                pattern.append(lead + r"\s*".join(pieces) + trail)
            elif part:
                pattern.append(r"\s*")
    pattern.append(r"\s*$")
    return re.compile("".join(pattern), re.IGNORECASE)


def _items(form: FormDef) -> list[_Item]:
    template = _IF_RE.sub(lambda m: m.group(2), form.body)
    items: list[_Item] = []
    position = 0
    chunks: list[tuple[str, str]] = []
    for match in _EACH_RE.finditer(template):
        chunks.append((template[position:match.start()], ""))
        chunks.append((match.group(2), match.group(1)))
        position = match.end()
    chunks.append((template[position:], ""))
    for text, block in chunks:
        for line in text.split("\n"):
            if not line.strip():
                continue
            names = [n.lower() for n in _VAR_RE.findall(line)]
            literal = _VAR_RE.sub("", line)
            if names and not literal.strip():
                kind = "row" if len(names) > 1 and block else "free"
                items.append(_Item(kind, names, block=block))
            else:
                labelled = len(re.sub(r"[\W_]", "", literal)) >= 3
                items.append(_Item("line", names, _line_regex(line), block, labelled))
    return items


def _split_row(line: str, names: list[str]) -> dict[str, str]:
    cells = _TAB_SPLIT.split(line)
    return {name: (cells[i].strip() if i < len(cells) else "") for i, name in enumerate(names)}


def ambiguous(form: FormDef) -> set[str]:
    """Variables that share a line of variables only, outside a table: the
    parser gives that line to the first of them."""
    names: set[str] = set()
    for item in _items(form):
        if item.kind == "free":
            names.update(item.names[1:])
    return names


def parse(form: FormDef, body: str, subject: str = "") -> Parsed:
    """Read `body` (and `subject`) against `form`'s template. Always
    returns a result; its `score` says how much of the template was found."""
    if form.strip:
        return _parse_strip(form, body)
    items = _items(form)
    multiline = {f.id.lower() for f in form.fields if f.kind in ("multiline", "strip")}
    flat: dict[str, str] = {}
    rows: dict[str, list[dict[str, str]]] = {}
    matched: set[int] = set()
    cursor = 0
    free: tuple[str, str] | None = None  # (variable, block) taking free text
    block_start = {b: min(i for i, it in enumerate(items) if it.block == b)
                   for b in {it.block for it in items if it.block}}

    def store(name: str, value: str, block: str, new_row: bool = False) -> None:
        if not block:
            flat[name] = value
            return
        table = rows.setdefault(block, [])
        if new_row or not table:
            table.append({})
        table[-1][name] = value

    for raw in body.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        hit = None
        if line.strip():
            current_block = items[cursor - 1].block if cursor else ""
            order = list(range(cursor, len(items)))
            if current_block:
                order += list(range(block_start[current_block], cursor))
            for i in order:
                item = items[i]
                if item.kind == "line" and item.regex.match(line):
                    hit = i
                    break
        if hit is not None:
            item = items[hit]
            groups = item.regex.match(line).groupdict()
            new_row = bool(item.block) and (
                hit < cursor or item.block != (items[cursor - 1].block if cursor else "")
                or item.block not in rows)
            if item.block and new_row:
                rows.setdefault(item.block, []).append({})
            for name in item.names:
                store(name, groups.get(name, "").strip(), item.block)
            matched.add(hit)
            cursor = hit + 1
            free = None
            if item.names and item.names[-1] in multiline:
                # "12. Additional Comments: <var Message>": the lines after
                # it are the rest of the message.
                free = (item.names[-1], item.block)
            continue
        if free is not None:
            name, block = free
            target = flat if not block else rows[block][-1]
            target[name] = (target.get(name, "") + "\n" + line) if name in target else line
            continue
        if not line.strip():
            continue
        nearby = [i for i in range(cursor, min(cursor + 3, len(items)))
                  if items[i].kind in ("free", "row")]
        if not nearby:
            continue
        i = nearby[0]
        item = items[i]
        if item.kind == "row":
            rows.setdefault(item.block, []).append(_split_row(line, item.names))
            matched.add(i)
            cursor = i  # the next line may be another row
            continue
        store(item.names[0], line.strip(), item.block)
        # Only a multi-line field goes on; a one-line field (the Incident
        # Status's Evac, then its description) takes this line alone.
        free = (item.names[0], item.block) if item.names[0] in multiline else None
        cursor = i + 1

    for target in [flat, *(r for table in rows.values() for r in table)]:
        for name, value in target.items():
            target[name] = value.strip("\n").rstrip()
    in_subject = _line_regex(form.subject).match(" ".join(subject.split())) if subject else None
    if in_subject:
        for name, value in in_subject.groupdict().items():
            if not flat.get(name):
                flat[name] = value.strip()
    labelled = [i for i, it in enumerate(items) if it.labelled]
    score = len(matched & set(labelled)) / len(labelled) if labelled else 0.0
    return Parsed(form, _values(form, flat, rows), score, dict(flat))


def _values(form: FormDef, flat: dict[str, str], rows: dict[str, list[dict[str, str]]]) -> Values:
    values: Values = {}
    for f in form.fields:
        key = f.id.lower()
        if f.kind == "rows":
            table = rows.get(key, [])
            values[f.id] = [{c.id: r.get(c.id.lower(), "") for c in f.columns} for r in table]
        elif f.kind == "check":
            values[f.id] = "1" if flat.get(key) and flat.get(key) == f.on_value else ""
        else:
            values[f.id] = flat.get(key, "")
    return values


def _parse_strip(form: FormDef, body: str) -> Parsed:
    strip = find_strip(body)
    title, answers = split_strip(strip) if strip else ("", [])
    if title.upper() != form.subject.upper():
        return Parsed(form, {}, 0.0)
    # The answers keep empty ones ("   "), so re-split without dropping them.
    parts = strip.rstrip("/").split("/")[1:]
    values = {f.id: (parts[i].strip() if i < len(parts) else "") for i, f in enumerate(form.fields)}
    return Parsed(form, values, 1.0 if len(parts) == len(form.fields) else 0.5)


def _subject_matches(form: FormDef, subject: str) -> bool | None:
    """True/False when the subject pattern has distinctive text, else None."""
    if form.strip or len(re.sub(r"[\W_]", "", _VAR_RE.sub("", form.subject))) < 3:
        return None
    return bool(_line_regex(form.subject).match(" ".join(subject.split())))


def recognize(subject: str, body: str, *, form_id: str = "") -> Parsed | None:
    """The form this message is, read into its fields, or None.

    `form_id` is our own `Form:` header, which decides it outright."""
    if form_id:
        try:
            return parse(get_form(form_id), body, subject)
        except StopIteration:
            pass
    best: Parsed | None = None
    for form in load_forms():
        if _subject_matches(form, subject) is False:
            continue
        parsed = parse(form, body, subject)
        if parsed.score >= MIN_SCORE and (best is None or parsed.score > best.score):
            best = parsed
    return best
