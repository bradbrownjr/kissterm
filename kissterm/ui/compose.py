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
    SEND_BULLETIN,
    SEND_PRIVATE,
    can_reply_by_number,
    check,
    outbox_message,
    quote,
    reply_title,
)

_TYPES = [("Private message (SP)", SEND_PRIVATE), ("Bulletin (SB)", SEND_BULLETIN)]


class ComposeScreen(ModalScreen[Message | None]):
    """Write one message. Returns the Outbox message, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, sender: str, reply_to: Message | None = None, quoted: bool = False) -> None:
        super().__init__()
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
                    yield Select(_TYPES, value=SEND_PRIVATE, allow_blank=False,
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
            with Horizontal(classes="compose-row"):
                yield Label("Title", classes="compose-label")
                yield Input(id="compose-title", compact=True)
            yield TextArea(id="compose-body", tab_behavior="focus", soft_wrap=True)
            with Horizontal(id="compose-foot"):
                yield Label("", id="compose-error")
                yield Button("Save to Outbox", variant="primary", compact=True, id="compose-save")
                yield Button("Cancel", compact=True, id="compose-cancel")
        yield Footer()

    def on_mount(self) -> None:
        original = self._reply_to
        if original is None:
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
        if self._quoted:
            # Two blank lines above the quote for the reply itself.
            body.text = "\n\n" + quote(original)
        self._start_body = body.text
        body.move_cursor((0, 0))
        body.focus()

    @on(Select.Changed, "#compose-type")
    def _type_changed(self, event: Select.Changed) -> None:
        bulletin = event.value == SEND_BULLETIN
        self.query_one("#compose-to", Input).placeholder = (
            "Category, e.g. WX" if bulletin else "Callsign, e.g. W1BKW"
        )
        self.query_one("#compose-at", Input).placeholder = (
            "Distribution, e.g. ALLUS" if bulletin else "optional: the BBS adds it"
        )

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
            )
        )
