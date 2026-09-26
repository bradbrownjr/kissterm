"""A received form shown as a form in the Mail and Bulletins reader.

`kissterm/mail/form_parse.py` reads the message against its template; this
lays the values out the way the form screen asks for them: the form's
title, then each filled field under its own label, a table's lines one
to a row. Empty fields are left out, as the sender's text left them out.
V on the message list shows the text as received instead, and back
(`MessageList.action_toggle_form`): the text is what was sent, and the
form view is only kissterm's reading of it, so it is always one key away.

Every value is remote text: it goes through `monitor.sanitize` like the
rest of the reader. Labels come from the shipped form file.
"""

from __future__ import annotations

from rich.text import Text

from ..mail.form_parse import Parsed
from ..monitor import sanitize


def _clean(value: str) -> str:
    return sanitize(value.encode("utf-8"))


def form_text(parsed: Parsed) -> Text:
    """The form view: title, a hint, then label and value per field."""
    out = Text()
    out.append(parsed.form.title, style="bold")
    out.append("   V shows the text as received\n\n", style="dim")
    width = max((len(f.label) for f in parsed.form.fields), default=0) + 2
    for f in parsed.form.fields:
        value = parsed.values.get(f.id, "")
        if f.kind == "rows":
            rows = [r for r in value if any(str(v).strip() for v in r.values())]
            if not rows:
                continue
            # One line per filled cell, under the line's number: a table
            # wider than the reader would otherwise wrap into a jumble.
            out.append(f"{f.label}\n", style="bold")
            cell = max(len(c.label) for c in f.columns) + 2
            for number, row in enumerate(rows, 1):
                lead = f"  {number}.".ljust(6)
                for c in f.columns:
                    value = str(row.get(c.id, "")).strip()
                    if value:
                        out.append(lead, style="bold")
                        out.append(f"{c.label}:".ljust(cell), style="bold")
                        out.append(_clean(value) + "\n")
                        lead = " " * 6
            continue
        if f.kind == "check":
            value = "yes" if value else ""
        value = str(value).strip()
        if not value:
            continue
        if "\n" in value:
            out.append(f"{f.label}\n", style="bold")
            out.append("".join(f"  {line}\n" for line in _clean(value).split("\n")))
        else:
            out.append(f"{f.label}:".ljust(width) + " ", style="bold")
            out.append(_clean(value) + "\n")
    return out
