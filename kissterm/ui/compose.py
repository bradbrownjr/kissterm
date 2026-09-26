"""The compose screen: a new BBS message, or a reply (ROADMAP P2).

Opened from the Mail tab: Insert for a new message, R to reply, Q to
reply with the original quoted. It returns the message for the Outbox, or
None; **saving never transmits** (DESIGN.md: a click or key that opens or
saves does not send). The checks are `kissterm/mail/compose.py`'s, made
here so a message is never refused halfway through a send on air.

A reply to a message read from a BBS goes out as `SR <number>`: the BBS
addresses and titles it, so To and Title are shown but not editable. It
says so on the screen rather than letting an edit be silently ignored.

Esc on a message with text in it asks first: a long message typed on a
phone keyboard in a shelter is not lost to one stray key.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Select, Static, TextArea

from ..mail import Message
from ..mail.compose import (
    BULLETIN_CATEGORIES,
    BULLETIN_DISTRIBUTIONS,
    Draft,
    SEND_BULLETIN,
    SEND_PRIVATE,
    SEND_TRAFFIC,
    can_reply_by_number,
    check,
    outbox_message,
    quote,
    reply_title,
)
from ..mail import form_parse
from ..mail.forms import PASTE_STRIP, FormDef, Values, find_strip, get_form, load_forms

#: The same for "Radiogram-ICS213": the radiogram form with HXI and a
#: subject line (`nts.py`, RRI 2026).
RADIOGRAM_ICS213 = "radiogram-ics213"

_TYPES = [
    ("Private message (SP)", SEND_PRIVATE),
    ("Bulletin (SB)", SEND_BULLETIN),
    ("NTS radiogram (ST)", SEND_TRAFFIC),
    ("Radiogram-ICS213 (ST)", RADIOGRAM_ICS213),
]

#: What the screen returns when the operator picks "NTS radiogram": a
#: radiogram has its own form (`radiogram.RadiogramScreen`), which the app
#: opens in its place.
RADIOGRAM = "radiogram"

#: A form chosen as the Type comes back as `FORM_PREFIX + form id`; the app
#: opens `form_screen.FormScreen`, which returns a `Draft` to this screen.
FORM_PREFIX = "form:"

#: What a reply returns for "Answer strip": the original carries a request
#: strip, and the app opens it as a form, then this screen again with the
#: answer as the reply's text.
ANSWER_STRIP = "answer-strip"

#: What a reply returns for "Reply on form": the original reads as a form
#: with a `reply_form` (an ICS-213), and the app opens that form with the
#: original's blocks filled in and read-only.
REPLY_FORM = "reply-form"


def reply_form_for(original: Message) -> tuple[FormDef, Values] | None:
    """The reply form for a received form message, and the original's values
    for it (its read-only half), or None if it is no such form."""
    parsed = form_parse.recognize(original.subject, original.body,
                                  form_id=original.extra.get("Form", ""))
    if parsed is None or not parsed.form.reply_form:
        return None
    form = get_form(parsed.form.reply_form)
    ids = {f.id for f in form.fields}
    return form, {k: v for k, v in parsed.values.items() if k in ids}


def _types() -> list[tuple[str, str]]:
    shipped = [(f"{f.title} (form)", FORM_PREFIX + f.id) for f in load_forms() if not f.hidden]
    return _TYPES + [(f"{PASTE_STRIP.title} (form)", FORM_PREFIX + PASTE_STRIP.id)] + shipped


class ComposeScreen(ModalScreen["Message | str | None"]):
    """Write one message. Returns the Outbox message, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, sender: str, reply_to: Message | None = None, quoted: bool = False,
                 draft: Draft | None = None,
                 bulletins: tuple[list[str], list[str]] | None = None) -> None:
        super().__init__()
        #: (categories, distributions) offered for SB (`compose.bulletin_choices`).
        self._bulletins = bulletins or (list(BULLETIN_CATEGORIES),
                                        [d for d, _ in BULLETIN_DISTRIBUTIONS])
        self._draft = draft
        self._sender = sender
        self._reply_to = reply_to
        self._quoted = quoted
        self._by_number = reply_to is not None and can_reply_by_number(reply_to)
        self._confirm_discard = False
        self._start_body = ""

    def compose(self) -> ComposeResult:
        original = self._reply_to
        with Vertical(id="compose-box"):
            with Horizontal(classes="compose-row"):
                if original is None:
                    yield Label("New message", id="compose-heading")
                    if self._draft is not None:
                        # A filled form: its type is set, its text is below.
                        types = [t for t in _TYPES if t[1] in (SEND_PRIVATE, SEND_BULLETIN)]
                        value = self._draft.send_type
                    else:
                        types, value = _types(), SEND_PRIVATE
                    yield Select(types, value=value, allow_blank=False,
                                 compact=True, id="compose-type")
                else:
                    number = original.extra.get("Bbs-Number", "")
                    title = f"Reply to #{number}" if number else "Reply"
                    yield Label(f"{title} from {original.sender}", id="compose-heading")
                    if self._by_number:
                        bbs = original.source.removeprefix("BBS ")
                        yield Static(
                            f"sent as SR {number}: {bbs} addresses and titles it",
                            id="compose-note",
                        )
            with Horizontal(classes="compose-row"):
                yield Label("To", classes="compose-label")
                yield Input(id="compose-to", placeholder="Callsign, e.g. W1BKW", compact=True)
                yield Label("@", classes="compose-label compose-at-label")
                yield Input(id="compose-at", placeholder="optional: the BBS adds it", compact=True)
            if original is None:
                # Shown for a bulletin only: pick-lists that fill To and @
                # (never send), typing anything else still works.
                categories, distributions = self._bulletins
                meaning = dict(BULLETIN_DISTRIBUTIONS)
                with Horizontal(classes="compose-row", id="compose-bulletin-row"):
                    yield Label("", classes="compose-label")
                    yield Select([(c, c) for c in categories], prompt="Category...",
                                 compact=True, id="compose-category")
                    yield Select([("This BBS only (no @)", "-")] + [
                        (f"{d} ({meaning[d]})" if d in meaning else f"{d} (used before)", d)
                        for d in distributions], prompt="Distribution...",
                        compact=True, id="compose-distribution")
            with Horizontal(classes="compose-row"):
                yield Label("Title", classes="compose-label")
                yield Input(id="compose-title", compact=True)
            yield TextArea(id="compose-body", tab_behavior="focus", soft_wrap=True)
            with Horizontal(id="compose-foot"):
                yield Label("", id="compose-error")
                if original is not None and self._draft is None and find_strip(original.body):
                    yield Button("Answer strip", compact=True, id="compose-strip")
                if original is not None and self._draft is None and reply_form_for(original):
                    yield Button("Reply on form", compact=True, id="compose-reply-form")
                yield Button("Save to Outbox", variant="primary", compact=True, id="compose-save")
                yield Button("Cancel", compact=True, id="compose-cancel")
        yield Footer()

    def on_mount(self) -> None:
        original = self._reply_to
        draft = self._draft
        if draft is not None:
            self.query_one("#compose-to", Input).value = draft.to
            self.query_one("#compose-at", Input).value = draft.at
            self.query_one("#compose-title", Input).value = draft.title
            self.query_one("#compose-body", TextArea).text = draft.body
        if original is None:
            bulletin = (draft.send_type if draft else SEND_PRIVATE) == SEND_BULLETIN
            self.query_one("#compose-bulletin-row").display = bulletin
            self.query_one("#compose-to", Input).focus()
            return
        to = self.query_one("#compose-to", Input)
        title = self.query_one("#compose-title", Input)
        to.value = original.sender
        title.value = reply_title(original.subject)
        if self._by_number:
            to.disabled = True
            title.disabled = True
            self.query_one("#compose-at", Input).disabled = True
        body = self.query_one("#compose-body", TextArea)
        if draft is None and self._quoted:
            # Two blank lines above the quote for the reply itself.
            body.text = "\n\n" + quote(original)
        self._start_body = body.text
        body.move_cursor((0, 0))
        body.focus()

    @on(Select.Changed, "#compose-type")
    def _type_changed(self, event: Select.Changed) -> None:
        if event.value == SEND_TRAFFIC:
            self.dismiss(RADIOGRAM)
            return
        if event.value == RADIOGRAM_ICS213:
            self.dismiss(RADIOGRAM_ICS213)
            return
        if isinstance(event.value, str) and event.value.startswith(FORM_PREFIX):
            self.dismiss(event.value)
            return
        bulletin = event.value == SEND_BULLETIN
        self.query_one("#compose-bulletin-row").display = bulletin
        self.query_one("#compose-to", Input).placeholder = (
            "Category, e.g. WX" if bulletin else "Callsign, e.g. W1BKW"
        )
        self.query_one("#compose-at", Input).placeholder = (
            "Distribution, e.g. ALLUS" if bulletin else "optional: the BBS adds it"
        )

    @on(Select.Changed, "#compose-category")
    def _category_picked(self, event: Select.Changed) -> None:
        if isinstance(event.value, str):
            self.query_one("#compose-to", Input).value = event.value

    @on(Select.Changed, "#compose-distribution")
    def _distribution_picked(self, event: Select.Changed) -> None:
        if isinstance(event.value, str):
            self.query_one("#compose-at", Input).value = "" if event.value == "-" else event.value

    @on(TextArea.Changed, "#compose-body")
    @on(Input.Changed)
    def _edited(self) -> None:
        if self._confirm_discard:
            self._confirm_discard = False
            self.query_one("#compose-error", Label).update("")

    def action_cancel(self) -> None:
        body = self.query_one("#compose-body", TextArea).text
        if body.strip() and body != self._start_body and not self._confirm_discard:
            self._confirm_discard = True
            self.query_one("#compose-error", Label).update(
                "Discard this message? Esc again to discard, or keep typing."
            )
            return
        self.dismiss(None)

    @on(Button.Pressed, "#compose-reply-form")
    def _reply_on_form(self) -> None:
        self.dismiss(REPLY_FORM)

    @on(Button.Pressed, "#compose-strip")
    def _answer_strip(self) -> None:
        self.dismiss(ANSWER_STRIP)

    @on(Button.Pressed, "#compose-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#compose-save")
    def _save(self) -> None:
        to = self.query_one("#compose-to", Input).value
        at = self.query_one("#compose-at", Input).value
        title = self.query_one("#compose-title", Input).value
        body = self.query_one("#compose-body", TextArea).text
        problems = check(to, at, title, body, reply_by_number=self._by_number)
        if problems:
            self.query_one("#compose-error", Label).update("\n".join(problems))
            return
        send_type = SEND_PRIVATE
        if self._reply_to is None:
            value = self.query_one("#compose-type", Select).value
            send_type = value if isinstance(value, str) else SEND_PRIVATE
        self.dismiss(
            outbox_message(
                sender=self._sender,
                to=to,
                at=at,
                title=title,
                body=body,
                send_type=send_type,
                reply_to=self._reply_to,
                form_id=self._draft.form_id if self._draft else "",
            )
        )
