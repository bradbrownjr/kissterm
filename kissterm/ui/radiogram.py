"""The radiogram form: an ARRL radiogram for NTS, saved to the Outbox.

Opened by choosing "NTS radiogram (ST)" as the Type in the compose screen
(Mail tab, Insert). The formatting rules are `kissterm/mail/nts.py`'s,
from ARRL's Methods and Practices Guidelines; this screen only collects the
fields and shows the result. **Saving never transmits**: the radiogram
waits in the Outbox and goes out as `ST <zip> @ NTS<state>` on the next
Send/Receive (G).

**What makes it self-explanatory** is that the text converts as it is
typed: each word is converted to its radiogram form when it is finished
(space or Enter), so a period becomes X, `?` QUERY and `ARL 46` ARL FORTY
SIX in front of the operator, and leaving the text drops a final X (MPG
1.3.1: X is never the last group). The Check field counts the groups; the
meaning of each ARL text used is shown under the text, and the status
line shows the BBS routing and subject. A new operator sees what the
rules did to their text before anything is saved, instead of learning it
from a relay station's service message. Only a word typed at the end of
the text converts live; an edit in the middle converts when the operator
leaves the text, so the cursor never jumps under them.

Laid out like the compose screen and Settings: one row per field, compact
controls, no field taller than it needs (DESIGN.md section 3).
"""

from __future__ import annotations

from datetime import datetime, timezone

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Input, Label, Select, Static, TextArea

from ..mail import Message
from ..mail.compose import ends_text_early, radiogram_message
from ..mail.nts import PRECEDENCES, Radiogram, arl_texts, arl_used, date_filed, encode_text

#: The Input fields, by id suffix, and the `Radiogram` attribute each fills.
_INPUTS = {
    "number": "number", "hx": "handling", "origin": "origin", "place": "place",
    "time": "time_filed", "name": "to_name", "call": "to_call", "street": "to_street",
    "city": "to_city", "state": "to_state", "zip": "to_zip", "phone": "to_phone",
    "email": "to_email", "opnote": "to_op_note", "signature": "signature",
    "sigopnote": "sig_op_note",
}


class RadiogramScreen(ModalScreen[Message | None]):
    """Fill in one radiogram. Returns the Outbox message, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, sender: str, *, number: str = "1", place: str = "") -> None:
        super().__init__()
        self._sender = sender
        self._number = number
        self._place = place
        self._confirm_discard = False

    def compose(self) -> ComposeResult:
        with Vertical(id="rg-box"):
            yield Label("NTS radiogram", id="rg-heading")
            with VerticalScroll(id="rg-form"):
                with Horizontal(classes="rg-row"):
                    yield Label("Number", classes="rg-label")
                    yield Input(self._number, id="rg-number", compact=True, classes="rg-short")
                    yield Label("Prec", classes="rg-label2")
                    yield Select([(f"{v} {label}" if v != "EMERGENCY" else label, v) for v, label in PRECEDENCES],
                                 value="R", allow_blank=False, compact=True, id="rg-precedence")
                    yield Label("HX", classes="rg-label2")
                    yield Input(id="rg-hx", placeholder="e.g. HXG", compact=True)
                    yield Checkbox("test", id="rg-test", compact=True)
                with Horizontal(classes="rg-row"):
                    yield Label("From stn", classes="rg-label")
                    yield Input(self._sender.split("-")[0].upper(), id="rg-origin", compact=True, classes="rg-short")
                    yield Label("Place", classes="rg-label2")
                    yield Input(self._place, id="rg-place", placeholder="sender's city ST, e.g. WATERBORO ME",
                                compact=True)
                with Horizontal(classes="rg-row"):
                    yield Label("Filed", classes="rg-label")
                    yield Input(id="rg-time", placeholder="e.g. 1830Z", compact=True,
                                classes="rg-short")
                    yield Label(f"Date  {date_filed(datetime.now(timezone.utc))} (UTC)", id="rg-date")
                    yield Label("Check", classes="rg-label2")
                    yield Static("0", id="rg-check")
                yield Static("To", classes="rg-heading2")
                with Horizontal(classes="rg-row"):
                    yield Label("Name", classes="rg-label")
                    yield Input(id="rg-name", placeholder="as in the phone book", compact=True)
                    yield Label("Call", classes="rg-label2")
                    yield Input(id="rg-call", placeholder="if a ham", compact=True, classes="rg-short")
                with Horizontal(classes="rg-row"):
                    yield Label("Street", classes="rg-label")
                    yield Input(id="rg-street", placeholder="e.g. 164 EAST SIXTH AVE", compact=True)
                with Horizontal(classes="rg-row"):
                    yield Label("City", classes="rg-label")
                    yield Input(id="rg-city", compact=True, placeholder="e.g. RIVER CITY")
                    yield Label("State", classes="rg-label2")
                    yield Input(id="rg-state", placeholder="MD", max_length=2, compact=True, classes="rg-tiny")
                    yield Label("ZIP", classes="rg-label2")
                    yield Input(id="rg-zip", placeholder="00789", compact=True, classes="rg-short")
                with Horizontal(classes="rg-row"):
                    yield Label("Phone", classes="rg-label")
                    yield Input(id="rg-phone", placeholder="e.g. 301 555 3470", compact=True)
                    yield Label("Email", classes="rg-label2")
                    yield Input(id="rg-email", placeholder="optional", compact=True)
                with Horizontal(classes="rg-row"):
                    yield Label("Op note", classes="rg-label")
                    yield Input(id="rg-opnote", placeholder="optional, for the delivering operator",
                                compact=True)
                yield Static("Text", classes="rg-heading2")
                yield Select(
                    [(f"{t.number} {t.word.title()}: {t.text}", t.number) for t in arl_texts()],
                    prompt="Insert an ARL numbered text...", compact=True, id="rg-arl",
                )
                yield TextArea(id="rg-text", tab_behavior="focus", soft_wrap=True)
                yield Static("", id="rg-preview")
                with Horizontal(classes="rg-row"):
                    yield Label("Signature", classes="rg-label")
                    yield Input(id="rg-signature", placeholder="who it is from", compact=True)
                with Horizontal(classes="rg-row"):
                    yield Label("Op note", classes="rg-label")
                    yield Input(id="rg-sigopnote", placeholder="optional, e.g. REPLY VIA KC1JMH AT WS1EC",
                                compact=True)
            yield Static("", id="rg-status")
            with Horizontal(id="rg-foot"):
                yield Label("", id="rg-error")
                yield Button("Save to Outbox", variant="primary", compact=True, id="rg-save")
                yield Button("Cancel", compact=True, id="rg-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#rg-name" if self._place else "#rg-place", Input).focus()
        self._refresh()

    # -- the radiogram as filled in ------------------------------------------

    def radiogram(self) -> Radiogram:
        values = {attr: self.query_one(f"#rg-{wid}", Input).value for wid, attr in _INPUTS.items()}
        precedence = self.query_one("#rg-precedence", Select).value
        return Radiogram(
            **values,
            precedence=precedence if isinstance(precedence, str) else "R",
            test=self.query_one("#rg-test", Checkbox).value,
            text=self.query_one("#rg-text", TextArea).text,
        )

    @on(Input.Changed)
    @on(TextArea.Changed)
    @on(Checkbox.Changed)
    @on(Select.Changed, "#rg-precedence")
    def _refresh(self) -> None:
        if self._confirm_discard:
            self._confirm_discard = False
            self.query_one("#rg-error", Label).update("")
        gram = self.radiogram()
        encoded = gram.encoded_text
        meanings = [f"{t.groups} = {t.text}" for t in arl_used(encoded)]
        preview = self.query_one("#rg-preview", Static)
        preview.update("\n".join(meanings))
        preview.display = bool(meanings)
        self.query_one("#rg-check", Static).update(gram.check)
        to, at = gram.routing()
        route = f"ST {to or '<zip>'} @ {at if len(at) == 5 else 'NTS<state>'}"
        status = f"{route}   {gram.subject()}"
        warnings = gram.warnings()
        if warnings:
            status += "\n" + " ".join(warnings)
        self.query_one("#rg-status", Static).update(status)

    @on(TextArea.Changed, "#rg-text")
    def _convert_as_typed(self) -> None:
        """Convert the text when a word is finished at the end of it."""
        area = self.query_one("#rg-text", TextArea)
        text = area.text
        if not text or not text[-1].isspace() or area.cursor_location != area.document.end:
            return
        converted = encode_text(text, final=False)
        converted = f"{converted} " if converted else ""
        if converted != text:
            self._set_text(area, converted)

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        """Leaving the text converts all of it, final X dropped."""
        if event.widget.id != "rg-text":
            return
        area = self.query_one("#rg-text", TextArea)
        converted = encode_text(area.text)
        if converted != area.text:
            self._set_text(area, converted)

    @staticmethod
    def _set_text(area: TextArea, text: str) -> None:
        area.text = text
        area.move_cursor(area.document.end)

    @on(Select.Changed, "#rg-arl")
    def _insert_arl(self, event: Select.Changed) -> None:
        if not isinstance(event.value, int):
            return
        text = next(t for t in arl_texts() if t.number == event.value)
        area = self.query_one("#rg-text", TextArea)
        area.insert(f"{text.groups} ")
        event.select.clear()
        area.focus()

    # -- save and cancel -----------------------------------------------------

    @on(Button.Pressed, "#rg-save")
    def _save(self) -> None:
        gram = self.radiogram()
        problems = gram.problems()
        if any(ends_text_early(line) for line in gram.body().splitlines()):
            problems.append("A line would end the message on the BBS (/EX); reword it.")
        if problems:
            self.query_one("#rg-error", Label).update("\n".join(problems[:3]) + (
                f"\n...and {len(problems) - 3} more" if len(problems) > 3 else ""))
            return
        self.dismiss(radiogram_message(gram, self._sender))

    def action_cancel(self) -> None:
        typed = self.query_one("#rg-text", TextArea).text.strip() or self.query_one("#rg-name", Input).value
        if typed and not self._confirm_discard:
            self._confirm_discard = True
            self.query_one("#rg-error", Label).update(
                "Discard this radiogram? Esc again to discard, or keep typing."
            )
            return
        self.dismiss(None)

    @on(Button.Pressed, "#rg-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)
