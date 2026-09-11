"""The APRS pane: a contact list and a chat-style conversation view.

Requested directly: replicate, in a terminal, what KM6LYW's APRS WebChat does
in a browser -- a contact list separate from the station Address Book (an
APRS messaging contact is a person or gateway you message, not a node you
connect to -- see `kissterm/aprs_contacts.py`) and a conversation view per
contact.

APRS decoding itself does not live here -- it is wired into the shared frame
fan-out in `ui/app.py`'s `_on_aprs_frame`, the same way the monitor pane and
heard list are (AGENTS.md sec. 2b: never a second decode path). This module
only ever reads `self.app.config.aprs_contacts` and
`self.app.aprs_conversations`; the actual encode-and-transmit step is
`KissTermApp._send_aprs_message` -- the shared primitive a fresh send and a
retry both call, so "what does it mean to send an APRS message" has exactly
one answer, gated by the same transmit switch as everything else in this app.

**Sending, ack, and retry.** `self._pending` (`aprs_conversations.
PendingAcks`) tracks outgoing messages awaiting an ack, in memory only --
see that module's docstring for why. A periodic timer
(`_check_retries`) reconciles it against `self.app.aprs_conversations`
(an ack arriving is `_on_aprs_frame`'s job, over on the frame fan-out; this
pane only notices the flag it leaves behind) and resends anything still due.
The "To:" field is independent of the contacts table on purpose: typing a
bare callsign there sends to someone not in the contact list at all, the
same way the Connect dialog and the Address Book coexist -- a contact is a
convenience, not a requirement, for messaging someone.

**The contacts table is a Ctrl+G slide-out, docked on the right, not a
permanent column.** The conversation view is what an operator is actually
looking at while messaging someone; the contact list is a lookup, summoned
with `KissTermApp.action_toggle_contacts` (dispatched here to
`toggle_contacts`) the same way the Terminal pane's Address Book is -- see
`DESIGN.md`'s "slide-out panels" section for the shared recipe. On a
terminal wide enough for both it opens itself (`kissterm/ui/slideouts.py`);
picking a row closes it again only if the operator summoned it.

**One conversation per tab, plus "All".** There is still exactly one
`RichLog`, repainted on `Tabs.TabActivated`, rather than a `TabPane` each --
that reuses `_show_conversation_for` unchanged instead of keeping twelve
render states alive, and for a chat log the useful scroll position is the
bottom, which a repaint gives for free. Before this the pane had a single
viewer showing whoever was last picked, so a message from anyone else left
no mark at all and "who has written to me?" was answerable only from a toast
that had already gone. A tab appears when the operator picks a contact,
sends to a callsign, or receives a message **addressed to this station**
(`note_incoming`); an unread one is marked `*` both on its tab and beside
the callsign in the contacts table. Every conversation already on disk also
gets its tab back at launch (`_restore_tabs`), unread markers aside -- the
history in "All" outlives the process and the tabs above it should too. The
"All" tab is always left-most and active at launch, and deliberately shows
third-party traffic too -- see `_show_all`.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Input, RichLog, Static, Tab, Tabs

from .. import aprs_services
from ..aprs_contacts import Contact, build_message_body, canned_messages_for
from ..aprs_conversations import PendingAcks
from . import slideouts
from .wraplog import WrapLog

#: How often the retry timer checks for a due, un-acked message. Independent
#: of `PendingAcks.retry_seconds` (how long a single message waits before
#: its own first/next retry) -- this is just the polling granularity.
_RETRY_CHECK_INTERVAL = 10.0


#: Cells of padding a `DataTable` adds around every column's content: one
#: either side of each of the four columns.
_TABLE_PADDING = 8

#: How wide the conversation column has to be before the compose row can
#: afford the Templates button as well as To, the message box and Send.
#: Measured, not guessed: To(12) + Templates(13) + Send(11) + the margins
#: between them is 39 cells, and a message box narrower than about 20 is not
#: a message box.
_COMPOSE_ROOM_FOR_TEMPLATES = 60

#: The merged view's tab id. Every other tab is `convo-<CALLSIGN>`.
_ALL_TAB = "convo-ALL"

#: The merged view's title. Empty on purpose -- the "All" tab already says
#: "All", so the title line stays reserved for what it is for everywhere
#: else, naming who a conversation is with (see `_show_conversation_for`),
#: and is hidden rather than filled with a sentence explaining the view for
#: this one tab (requested directly: no descriptive text on any tab).
_ALL_TITLE = ""

#: Conversation tabs kept open at once, not counting "All". Twelve is already
#: more than fits across a normal terminal before the strip starts scrolling,
#: and an unbounded strip would turn a busy channel into a ribbon of
#: callsigns nobody is talking to. See `_make_room_for_a_tab`.
_MAX_CONVO_TABS = 12

#: Lines the merged view renders. It is a merge of up to two hundred
#: conversations, and a repaint runs on every arriving frame, so it is capped
#: at roughly a few screens of scrollback rather than everything ever heard.
_ALL_TAB_LINES = 500


def _tab_id(callsign: str) -> str:
    """The `Tabs` id for one correspondent's tab.

    The `convo-` prefix is load-bearing, not decoration: a Textual widget id
    may not begin with a digit, and `2E0ABC` is an ordinary UK callsign --
    unprefixed it raises `BadIdentifier` and takes the pane down on the first
    message from half of Europe. The substitution is the same defensiveness:
    a callsign off the air is already validated by `AX25Address`, but the
    "To:" field accepts whatever the operator types.
    """
    return "convo-" + re.sub(r"[^A-Za-z0-9_-]", "_", callsign.strip().upper())


@dataclass(frozen=True, slots=True)
class _ColumnWidths:
    callsign: int
    name: int
    detail: int
    service: int
    gateway_label: str


def _column_widths(available: int) -> _ColumnWidths:
    """Split `available` cells across the contacts table's four columns.

    Pure arithmetic, and separated from the pane so it can be tested at every
    terminal size without mounting anything.

    The priorities, in order, are what an operator needs off a glance at this
    list: the **callsign**, because it is what goes in the "To:" field and it
    is the one field that must never be cut; then **what the row is**, which
    for a gateway service is its description and for a person is their name;
    then the kind marker.

    So `callsign` is fixed at the width of the longest real callsign-with-SSID
    and everything else flexes. `service` gives up its full "Gateway Service"
    wording below a threshold and says "Gateway" instead -- a shorter *label*,
    chosen deliberately, rather than the mid-word "Gateway Servi" that letting
    the column clip produced on a narrow screen.
    """
    # 35 is the sum of the four minimums below -- the width at which every
    # column is still showing something. Narrower than that the table scrolls
    # whatever we do, and squeezing further only hides more.
    budget = max(available - _TABLE_PADDING, 35)
    # Ten, not nine: the longest real callsign-with-SSID is nine cells
    # ("KA1ABC-15") and an unread row prefixes it with `*`. A column sized to
    # the callsign alone would clip the SSID off exactly the rows the marker
    # exists to draw attention to.
    callsign = 10
    remaining = budget - callsign
    # "Gateway Service" is 15 wide. Only spend that when the two prose columns
    # can still carry something worth reading without it.
    if remaining >= 46:
        service, gateway_label = 15, "Gateway Service"
    else:
        service, gateway_label = 7, "Gateway"
    remaining -= service
    # Name gets a third, capped: past about twenty cells it is just padding a
    # person's name, and every cell beyond that is worth more to the
    # description next to it.
    name = max(8, min(20, remaining // 3))
    detail = max(10, remaining - name)
    return _ColumnWidths(callsign, name, detail, service, gateway_label)


def _detail_cell(detail: str, notes: str) -> str:
    """One column for a saved contact's `detail` and `notes`.

    They were separate columns until the gateway directory landed, and a
    five-column table does not fit the slide-out -- the description column a
    directory of services exists to show was the one that fell off the edge.
    These two are the pair worth merging: `detail` is the addressing extra
    (a phone number, an email address) and `notes` is free text about the
    same person, so reading them side by side loses nothing. Both fields are
    still stored and still edited separately in `AprsContactScreen`; this is
    a display join, not a data change.
    """
    parts = [part.strip() for part in (detail, notes) if part.strip()]
    return " -- ".join(parts)


class _AprsContactTable(DataTable):
    """Insert/F2/Delete/Enter on the contacts table, same convention as
    `_AddressBookTable` -- bound on the table itself so Delete does not also
    fire while the operator is typing somewhere else in this pane.

    **`show=True`, so these appear in the Footer while this table has
    focus**, rather than as a line of hint text printed under the buttons.
    Textual's Footer already shows the focused widget's bindings and updates
    as focus moves, which is exactly the context-aware shortcut bar this app
    wants -- a second copy of the same information, in a different place and
    a different style, is the duplication DESIGN.md's "one place for each
    fact" rule exists to prevent. It also lets the buttons sit at the same
    height as every other pane's, since nothing is pushed down by a hint
    line only this pane had.
    """

    BINDINGS = [
        Binding("enter", "message_contact", "Message"),
        Binding("insert", "new_contact", "New"),
        Binding("f2", "edit_contact", "Edit"),
        Binding("delete", "forget_contact", "Forget"),
    ]

    def on_resize(self) -> None:
        # `events.Resize` carries no `control`, so it cannot be routed with
        # `@on(...)` from the pane -- the table has to hand it over itself.
        self.app.query_one(AprsPane).contacts_table_resized()

    def action_message_contact(self) -> None:
        self.app.query_one(AprsPane)._message_selected()  # type: ignore[attr-defined]

    def action_new_contact(self) -> None:
        self.app.query_one(AprsPane)._new_contact()  # type: ignore[attr-defined]

    def action_edit_contact(self) -> None:
        self.app.query_one(AprsPane)._edit_selected()  # type: ignore[attr-defined]

    def action_forget_contact(self) -> None:
        self.app.query_one(AprsPane)._forget_selected()  # type: ignore[attr-defined]


class _ConvoTabs(Tabs):
    """The conversation strip, with `Delete` to close the tab you are on.

    `show=True`, so the key appears in the Footer while the strip has focus
    -- the same rule `_AprsContactTable`'s bindings follow, and the reason
    there is no hint line printed under the tabs.

    Deliberately **not** `Ctrl+W`: `Input` already claims that for
    delete-word, and the compose box next to this strip is exactly where an
    operator's hands are. `Delete` is only reachable while the strip itself
    has focus, so it cannot fire while they are typing a message.
    """

    BINDINGS = [Binding("delete", "close_tab", "Close tab")]

    def action_close_tab(self) -> None:
        self.app.query_one(AprsPane).close_active_tab()


class AprsPane(Horizontal):
    """The conversation view, plus a Ctrl+G contacts slide-out on the right."""

    BINDINGS = [
        Binding("escape", "close_contacts", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pending = PendingAcks()
        #: Wraps well inside the spec's 1-5 alphanumeric characters; a
        #: fresh number each send, reused by nothing until it wraps.
        self._next_msg_number = 1
        #: Whose conversation is currently rendered, so an ack arriving or a
        #: retry going out can repaint it in place. Empty while the merged
        #: "All" view is the one on screen.
        self._shown_callsign = ""
        self._shown_title = ""
        #: Callsigns with a message we have not looked at yet. **In memory
        #: only**, the same reasoning `PendingAcks` gives for itself: nothing
        #: arrives while kissterm is closed, so a persisted unread flag could
        #: only ever be stale.
        self._unread: set[str] = set()
        #: Tab id -> callsign, for turning a `TabActivated` back into whose
        #: conversation it is. A reverse `_tab_id()` would have to guess at
        #: the substitution it makes, so the mapping is kept instead.
        self._tab_callsigns: dict[str, str] = {}
        #: Callsign -> the title line to print above their log.
        self._tab_titles: dict[str, str] = {}
        #: Open conversation tabs, least recently looked at FIRST. This is
        #: what `_make_room_for_a_tab` evicts from, and the reason a tab is
        #: moved to the end every time it is activated.
        self._recent: list[str] = []
        #: Non-message APRS traffic (position, weather, status, telemetry,
        #: object/item, third-party) formatted for display -- **in memory
        #: only**, unlike `ConversationStore`. None of it is correspondence
        #: with anyone, so there is no conversation to file it under and
        #: nothing worth persisting across a restart; it exists purely to
        #: merge into the "All" tab, capped the same as that view
        #: (`_ALL_TAB_LINES`) so a busy channel cannot grow it forever.
        #: Fed by `note_packet`, called from `KissTermApp._note_aprs_packet`.
        self._packet_lines: deque[tuple[float, str]] = deque(maxlen=_ALL_TAB_LINES)

    def compose(self) -> ComposeResult:
        # Conversation first -- this is the main, always-visible column.
        # Contacts is the slide-out, hidden by default; see `toggle_contacts`.
        with Vertical(id="aprs-conversation-column"):
            yield Static(_ALL_TITLE, id="aprs-conversation-title")
            # "All" is composed in rather than added at mount, so it is the
            # active tab from the first frame -- `Tabs._on_mount` activates
            # the first tab it finds. It is also why `add_tab` is never
            # called on an empty strip: an add to an empty `Tabs` activates
            # what it just added, which would yank the view to whichever
            # stranger transmitted first.
            yield _ConvoTabs(Tab("All", id=_ALL_TAB), id="aprs-convo-tabs")
            # `WrapLog`, not a plain `RichLog`: with the contact list open
            # this column is narrower than `RichLog`'s 78-cell `min_width`,
            # and the tail a plain one would hide is the `[ack]` status.
            # See `kissterm/ui/wraplog.py`.
            yield WrapLog(id="aprs-conversation-log", wrap=True, markup=False)
            with Horizontal(id="aprs-compose-row"):
                yield Input(placeholder="To (callsign)", id="aprs-to-input")
                yield Input(placeholder="Message", id="aprs-compose-input")
                # Ctrl+R does the same thing. The button exists because the
                # whole point of the directory is discoverability, and a
                # feature reachable only by a key nobody has been told about
                # is not discoverable.
                yield Button("Templates", id="aprs-templates-button")
                yield Button("Send", variant="primary", id="aprs-send-button")
        with Vertical(id="aprs-contacts-column"):
            yield _AprsContactTable(id="aprs-contact-table", cursor_type="row", zebra_stripes=True)
            # No hint line under these. The keys live in the Footer, which
            # already tracks focus -- see `_AprsContactTable`'s docstring.
            with Horizontal(classes="addressbook-actions"):
                yield Button("Message", variant="primary", id="aprs-contact-message")
                yield Button("New", id="aprs-contact-new")
                yield Button("Edit selected", id="aprs-contact-edit")
                yield Button("Forget selected", id="aprs-contact-forget")

    def on_mount(self) -> None:
        self.refresh_from(self.app.config.aprs_contacts)  # type: ignore[attr-defined]
        self._slideout = slideouts.SlideOut(
            self.query_one("#aprs-contacts-column"),
            self.query_one("#aprs-conversation-column"),
        )
        self.query_one("#aprs-contacts-column").display = False
        self.set_interval(_RETRY_CHECK_INTERVAL, self._check_retries)
        self._restore_tabs()

    def _restore_tabs(self) -> None:
        """Reopen a tab for every conversation already on disk, oldest last
        message first.

        `self.app.aprs_conversations` is loaded from disk before the app
        ever mounts a widget, but the tabs above it are pure session state --
        so a station closing and reopening kissterm mid-conversation landed
        back on a bare "All" with the history reachable only by re-picking
        the contact, even though "the conversation remains in All" the whole
        time. Restored via `_open_tab`, never `select_conversation`, so
        nothing is activated and "All" stays the tab on screen at launch
        (`compose`'s note on why that matters); oldest-last-activity first so
        `_touch`'s ordering inside `_open_tab` leaves the most recently
        active conversation as the most-recently-viewed one, exactly as if
        the operator had just been looking at it. Capped by the same
        `_make_room_for_a_tab` a live session already uses, so a station
        with a long history does not restore more tabs than the strip is
        meant to hold.
        """
        store = self.app.aprs_conversations  # type: ignore[attr-defined]
        convos = sorted(
            (c for c in store.conversations.values() if c.messages),
            key=lambda c: c.last_activity,
        )
        for convo in convos:
            callsign = convo.callsign
            contact = self._contact_for(callsign)
            if contact is not None:
                title = f"{contact.name} ({contact.callsign})"
            else:
                service = aprs_services.lookup_callsign(callsign)
                title = f"{service.name} ({service.callsign})" if service is not None else callsign
            self._tab_titles[callsign] = title
            self._open_tab(callsign)

    def on_resize(self) -> None:
        """Re-decide whether the contacts column is showing, and how wide.

        On `Resize` rather than in `on_mount` because a pane has no width
        until it has been laid out -- `KissTermFooter._on_resize` (`ui/app.py`)
        already fits its keys the same way. `SlideOut` ignores this once the
        operator has used `Ctrl+G`, so a resize can never overrule them.
        """
        was_open = self._slideout.open
        self._slideout.resized(
            self.size.width,
            allowed=getattr(self.app.config, "slideouts_auto_open", True),  # type: ignore[attr-defined]
        )
        if self._slideout.open and not was_open:
            # Opened by the width rule, NOT by the operator -- so it must not
            # take focus. DESIGN.md's "opening moves focus into the panel" is
            # about a panel someone summoned to do something in; stealing the
            # cursor out of the message box because a window got wider is a
            # different thing entirely.
            self.refresh_from(self.app.config.aprs_contacts)  # type: ignore[attr-defined]
        self._fit_compose_row()

    def _fit_compose_row(self) -> None:
        """Drop the Templates button when the compose row runs out of room.

        With the contact list open the conversation column can be as narrow as
        40 cells, and `To` + Templates + Send are about 36 of them before the
        message box gets anything at all -- which left a two-character box as
        the DEFAULT view the moment the slide-out started opening itself.

        Templates is the one that goes, because it is the only control here
        that is purely a shortcut: `Ctrl+R` does exactly the same thing and
        shows in the Footer as "Commands". Nothing becomes unreachable, which
        is the bar for hiding anything.
        """
        # From the arithmetic, NOT from the rendered width: this runs inside
        # the same `on_resize` that just set the panel's width, so the
        # conversation column has not been laid out at its new size yet and
        # reading `outer_size` here returns the width it had a moment ago.
        # That is exactly how the first version of this silently did nothing.
        total = self.size.width
        room = slideouts.split(total).main if self._slideout.open else total
        wide = room >= _COMPOSE_ROOM_FOR_TEMPLATES
        self.query_one("#aprs-templates-button", Button).display = wide
        self.query_one("#aprs-to-input", Input).styles.width = 12 if wide else 10

    # -- contacts slide-out ---------------------------------------------------
    def toggle_contacts(self) -> None:
        """Show or hide the contacts column. `Ctrl+G`'s target on this pane,
        dispatched from `KissTermApp.action_toggle_contacts`. Opening
        repaints from `Config.aprs_contacts` (same "correct the instant it
        becomes visible" reasoning as `TerminalPane.toggle_addressbook` --
        this column stays composed-but-hidden rather than being torn down
        and rebuilt, so nothing else repaints it once the pane has mounted)
        and focuses the table; closing (here or via Escape) returns focus to
        the compose field.
        """
        if self._slideout.toggle():
            self.refresh_from(self.app.config.aprs_contacts)  # type: ignore[attr-defined]
            self.query_one("#aprs-contact-table", DataTable).focus()
        else:
            self.query_one("#aprs-compose-input", Input).focus()
        # The conversation column just changed width, so the compose row has
        # either gained room for the Templates button or lost it.
        self._fit_compose_row()

    def action_close_contacts(self) -> None:
        """Escape. A no-op if the column is already hidden, so binding it at
        the pane level never disturbs a plain Escape typed for some other
        reason (e.g. inside a modal opened over this pane)."""
        if self._slideout.close_by_hand():
            self.query_one("#aprs-compose-input", Input).focus()
            self._fit_compose_row()

    def _close_contacts_after_pick(self) -> None:
        """Close the panel because a row was chosen -- but only if the
        operator summoned it. A panel that opened itself on a wide terminal is
        part of the layout, and taking it away when they pick a contact would
        be removing something they never asked for."""
        if self._slideout.closes_on_pick():
            self.action_close_contacts()

    # -- conversation tabs ---------------------------------------------------
    def _tabs(self) -> _ConvoTabs:
        return self.query_one("#aprs-convo-tabs", _ConvoTabs)

    def _label(self, callsign: str) -> str:
        """A tab's label: `*` in front while it has something unread.

        An asterisk rather than a colour alone, because the tab strip is
        already carrying colour to mean "this is the active tab" and a second
        meaning on the same channel is not readable -- and because a marker
        made only of colour is invisible to anyone who cannot see it.
        """
        return f"*{callsign}" if callsign in self._unread else callsign

    def _active_callsign(self) -> str | None:
        """Whose conversation the strip is on, or None for the "All" tab."""
        return self._tab_callsigns.get(self._tabs().active)

    def clear_active(self) -> None:
        """`Ctrl+L` -- clear whichever view is on screen right now, the same
        key `TerminalPane.clear_active` and `MonitorPane.clear` already use
        for their own on-screen log.

        "All" merges EVERY open conversation by timestamp (`_show_all`), so
        clearing it must never delete a correspondent's persisted history --
        that would wipe chat history for every contact from one keystroke on
        the one tab that happens to show them all at once. Only the
        in-memory, non-message packet buffer (`_packet_lines`) is dropped
        there, the same ephemeral-buffer-wipe `MonitorPane.clear` already
        does for its own decoded-frame log.

        A conversation tab instead deletes ITS OWN persisted history
        (`ConversationStore.forget`) and any of its still-pending retries
        (`PendingAcks.discard_for`) -- the log on screen is redrawn straight
        from that store on every repaint (`_show_conversation_for`),
        including the retry timer's own periodic one, so anything less than
        actually deleting the underlying messages would silently reappear
        within `_RETRY_CHECK_INTERVAL` seconds and look like Ctrl+L did
        nothing at all.
        """
        callsign = self._active_callsign()
        if callsign is None:
            self._packet_lines.clear()
            self._show_all()
            return
        self.app.aprs_conversations.forget(callsign)  # type: ignore[attr-defined]
        self._pending.discard_for(callsign)
        self._show_conversation_for(callsign, self._tab_titles.get(callsign, callsign))

    def _touch(self, callsign: str) -> None:
        if callsign in self._recent:
            self._recent.remove(callsign)
        self._recent.append(callsign)

    def _open_tab(self, callsign: str) -> None:
        """Make sure `callsign` has a tab, without activating it.

        Adding without activating is the whole point: a message arriving from
        someone else must not move the view out from under an operator
        part-way through typing a reply to a third station.
        """
        tabs = self._tabs()
        tab_id = _tab_id(callsign)
        if tabs.get_tab(tab_id) is not None:
            return
        self._make_room_for_a_tab()
        self._tab_callsigns[tab_id] = callsign
        self._recent.append(callsign)
        tabs.add_tab(Tab(self._label(callsign), id=tab_id))
        # The tab is queryable the moment `add_tab` returns (the mount is
        # registered synchronously; only `on_mount` is deferred), so the
        # unread class can be put on straight away rather than on a callback.
        self._relabel(callsign)

    def _make_room_for_a_tab(self) -> None:
        """Close the least recently viewed tab if the strip is full.

        Never "All", never the tab on screen, and **never one still holding
        something unread** -- evicting that would throw away the only record
        that somebody called, which is the exact failure this whole feature
        exists to fix. If every open tab is unread or active there is nothing
        safe to close and the strip is simply allowed to run one over; the
        cap is a tidiness rule, not an invariant worth losing a message for.
        """
        active = self._active_callsign()
        while len(self._recent) >= _MAX_CONVO_TABS:
            victim = next(
                (c for c in self._recent if c not in self._unread and c != active),
                None,
            )
            if victim is None:
                return
            self._close_tab(victim)

    def _close_tab(self, callsign: str) -> None:
        tab_id = _tab_id(callsign)
        self._tabs().remove_tab(tab_id)
        self._tab_callsigns.pop(tab_id, None)
        self._tab_titles.pop(callsign, None)
        self._unread.discard(callsign)
        if callsign in self._recent:
            self._recent.remove(callsign)

    def close_active_tab(self) -> None:
        """`Delete` on the strip. "All" cannot be closed.

        It is the one view that is always there and the thing `remove_tab`
        falls back to when the last conversation goes, so closing it would
        leave the pane with no tab at all and nothing to repaint.
        """
        callsign = self._active_callsign()
        if callsign is None:
            self.app.notify("The All tab stays open.", severity="warning")  # type: ignore[attr-defined]
            return
        self._close_tab(callsign)

    def select_conversation(self, callsign: str, title: str) -> None:
        """Put `callsign`'s conversation on screen, opening a tab if needed.

        The single entry point for "show me this conversation" -- a contact
        row, the Message button, a bare "To:" callsign nobody has saved, and
        a message just sent all land here, so a conversation can never be
        showing without a tab to get back to it.
        """
        callsign = callsign.strip().upper()
        if not callsign:
            return
        self._tab_titles[callsign] = title
        self._open_tab(callsign)
        tabs = self._tabs()
        tab_id = _tab_id(callsign)
        if tabs.active != tab_id:
            # Posts `TabActivated`, which repaints -- but the message is
            # handled on a later pass of the event loop, and a caller that
            # sent a message wants the log correct now, so `_activate` runs
            # here too. It is idempotent; the worst case is one extra repaint.
            tabs.active = tab_id
        self._activate(callsign)

    def _activate(self, callsign: str) -> None:
        """Everything that happens when a conversation becomes the one on
        screen: it stops being unread, it becomes the most recently viewed,
        and its log is repainted."""
        if callsign in self._unread:
            self._unread.discard(callsign)
            self._relabel(callsign)
            # The `*` beside the callsign in the contact list has to go at
            # the same moment as the one on the tab, or the two disagree
            # about whether there is anything left to read.
            self.refresh_from(self._contacts())
        self._touch(callsign)
        self._show_conversation_for(callsign, self._tab_titles.get(callsign, callsign))

    def _relabel(self, callsign: str) -> None:
        """Put the tab's label and its unread class back in step with
        `self._unread`. Both, together, every time -- the `*` is what makes
        the marker readable without colour and the class is what makes it
        catch the eye across a strip of a dozen tabs; either one alone is
        half a notification."""
        tab = self._tabs().get_tab(_tab_id(callsign))
        if tab is not None:
            tab.label = self._label(callsign)
            tab.set_class(callsign in self._unread, "-unread")

    @on(Tabs.TabActivated, "#aprs-convo-tabs")
    def _convo_tab_activated(self, event: Tabs.TabActivated) -> None:
        # Stopped because it has done its job. `TabbedContent` ignores a
        # strip that is not its own (`_is_associated_tabs`) and
        # `Tabs.TabActivated` is a different class from
        # `TabbedContent.TabActivated` anyway, so this is not load-bearing --
        # but a message with nothing left to tell anyone should not keep
        # climbing past the widget that handled it.
        event.stop()
        tab_id = event.tab.id or ""
        if tab_id == _ALL_TAB:
            self._show_all()
            return
        callsign = self._tab_callsigns.get(tab_id)
        if callsign is None:
            return
        # Switching to a conversation addresses it too -- otherwise the
        # operator reads a message, types a reply, and sends it to whoever
        # was in the "To:" field before.
        self.query_one("#aprs-to-input", Input).value = callsign
        self._activate(callsign)

    def _show_all(self) -> None:
        """The merged view: every conversation, plus every other decoded
        packet kind, in one log, oldest line first.

        **It includes traffic between other stations, deliberately.**
        `KissTermApp._on_aprs_frame` records every message packet it decodes
        into `ConversationStore` *before* it checks whether the addressee is
        us, so the store has always held third-party messages -- this is
        simply the first view that shows them, and it doubles as a channel
        message monitor. The per-callsign tabs are the ones that stay quiet
        unless something was addressed to this station; if the recording rule
        ever needs to change, it changes in `_on_aprs_frame`, not here.

        Messages are one source; `self._packet_lines` (positions, weather,
        status, telemetry, object/item, third-party -- everything
        `note_packet` has been fed) is the other. Both are merged into plain
        `(timestamp, text)` pairs before sorting, on purpose: sorting the raw
        message tuples would fall through to comparing two `MessageEntry`
        objects whenever two share a timestamp, which raises, and packets
        decoded from the same burst share one readily.
        """
        self._shown_callsign = ""
        self._shown_title = _ALL_TITLE
        title_widget = self.query_one("#aprs-conversation-title", Static)
        title_widget.update(_ALL_TITLE)
        title_widget.display = False
        log = self.query_one("#aprs-conversation-log", RichLog)
        log.clear()
        store = self.app.aprs_conversations  # type: ignore[attr-defined]
        lines: list[tuple[float, str]] = list(self._packet_lines)
        for callsign, convo in store.conversations.items():
            for entry in convo.messages:
                if entry.direction == "in":
                    lines.append((entry.timestamp, f"< {callsign}: {entry.text}"))
                else:
                    status = self._outgoing_status(callsign, entry)
                    lines.append((entry.timestamp, f"> {callsign}: {entry.text}  [{status}]"))
        if not lines:
            log.write("(no messages yet)")
            return
        lines.sort(key=lambda item: item[0])
        for _, text in lines[-_ALL_TAB_LINES:]:
            log.write(text)

    def note_packet(self, line: str, timestamp: float) -> None:
        """A non-message APRS packet was decoded into one human-readable
        `line` (a position, weather report, status, telemetry reading, or
        object/item -- see `format_packet`). Kept in `self._packet_lines`
        only; repaints the "All" tab immediately if it is the one on screen,
        the same way an incoming message does.
        """
        self._packet_lines.append((timestamp, line))
        try:
            if self._tabs().active == _ALL_TAB:
                self._show_all()
        except NoMatches:
            # Off the frame fan-out, which outlives the widget tree -- same
            # tolerance `note_incoming` applies.
            return

    def note_incoming(self, callsign: str, *, to_me: bool) -> None:
        """A message was decoded. Open a tab for it and mark it unread.

        Called from `KissTermApp._on_aprs_frame`, which computes `to_me` with
        the same `callsign_matches` check the auto-ack uses. **The gate is the
        point**: every message packet on the channel is recorded, third-party
        traffic included, so without it two strangers chatting on the
        frequency would open tabs here and put asterisks beside their
        callsigns -- marking as unanswered mail something nobody has to
        answer. That traffic is still visible, in "All".

        A message from whoever is already on screen is not unread; it is just
        the next line of the conversation being read.
        """
        try:
            self._tabs()
        except NoMatches:
            # Off the frame fan-out, which outlives the widget tree -- same
            # tolerance `refresh_conversation` applies.
            return
        callsign = callsign.strip().upper()
        if not to_me or not callsign:
            self.refresh_conversation()
            return
        if self._active_callsign() == callsign:
            self.refresh_conversation()
            return
        self._unread.add(callsign)
        self._tab_titles.setdefault(callsign, callsign)
        self._open_tab(callsign)
        self._relabel(callsign)
        self.refresh_from(self._contacts())
        self.refresh_conversation()

    def _unread_style(self) -> str:
        """The Rich style for an unread row in the contacts table.

        Resolved from the running theme rather than hard-coded, so it follows
        a theme change like everything else -- a `DataTable` cell is a Rich
        renderable, and Textual's `$warning` is a CSS variable Rich knows
        nothing about, so it has to be looked up and handed over as a colour.
        """
        try:
            colour = self.app.get_css_variables().get("warning", "")
        except Exception:  # pragma: no cover - a theme with no warning colour
            colour = ""
        return f"bold {colour}" if colour else "bold"

    def _callsign_cell(self, callsign: str) -> str | Text:
        """The callsign column for one row, marked if it has unread traffic.

        **The first styled `DataTable` cell in this app** -- every other table
        in it passes plain strings. The plain path is still what a read row
        takes, so a contact list with nothing unread in it renders exactly as
        it did before.
        """
        if callsign.strip().upper() not in self._unread:
            return callsign
        return Text(f"*{callsign}", style=self._unread_style())

    # ------------------------------------------------------------------
    def refresh_from(self, raw_contacts: list[dict]) -> None:
        """Repaint the table from `Config.aprs_contacts`, then append the
        shipped gateway services.

        Safe to call repeatedly -- same rule as
        `AddressBookPane.refresh_from`: correct the instant this pane becomes
        visible, not on the next tab switch.

        **The built-in rows are rendered from `kissterm/aprs_services/` and
        are never written into `Config.aprs_contacts`.** Copying them into
        the operator's config would freeze them at whatever this version
        shipped and make a corrected callsign or a new command permanent
        until they noticed and re-added it by hand. Keeping them out means
        they improve when kissterm updates and can never masquerade as
        something the operator typed.

        They sort after the saved contacts because seventeen services would
        otherwise bury the two or three people an operator actually messages.
        Anything in `Config.aprs_hidden_services` is skipped entirely; that
        is what Delete on a built-in row does.
        """
        table = self.query_one("#aprs-contact-table", DataTable)
        table.clear(columns=True)
        # Callsign first: it is what the operator is looking up and what the
        # "To:" field wants, so it is the column the eye should land on.
        #
        # Widths are COMPUTED, and there are four columns rather than five,
        # both for the same reason: a `DataTable` sizes its columns to their
        # content and then SCROLLS when the total overflows -- it does not
        # shrink. Auto-sized, the longest service summary pushed Detail off
        # the right-hand edge of the slide-out entirely, so the descriptions
        # this directory exists to show were invisible until the operator
        # scrolled sideways. Hard-coded widths only move the problem to
        # whichever terminal size they were not picked for; this pane has to
        # look right in an 80-column ssh window and in a full-screen one.
        widths = _column_widths(self._contacts_table_width())
        table.add_column("Callsign", width=widths.callsign)
        table.add_column("Name", width=widths.name)
        table.add_column("Detail", width=widths.detail)
        table.add_column("Service", width=widths.service)

        # Alphabetical by callsign, within each group. The two groups stay
        # separate rather than interleaving -- seventeen gateway services
        # would otherwise bury the handful of people an operator actually
        # messages, which is the whole reason the built-ins sort last.
        saved = sorted(
            ((i, Contact.from_dict(raw)) for i, raw in enumerate(raw_contacts)),
            key=lambda pair: pair[1].callsign,
        )
        for index, contact in saved:
            table.add_row(
                self._callsign_cell(contact.callsign),
                contact.name,
                _detail_cell(contact.detail, contact.notes),
                contact.service,
                key=str(index),
            )

        hidden = set(getattr(self.app.config, "aprs_hidden_services", ()))  # type: ignore[attr-defined]
        services = sorted(
            (s for s in aprs_services.load_all() if s.id not in hidden),
            key=lambda s: s.callsign,
        )
        for service in services:
            table.add_row(
                self._callsign_cell(service.callsign),
                service.name,
                # The description goes in Detail, which is otherwise empty for
                # a service (there is no phone number or address to put there)
                # and is where the eye already goes for "what is this?".
                service.summary,
                # "Gateway Service", not "built-in". The column answers "what
                # kind of thing is this?", and the useful answer is what the
                # row IS, not where it came from -- an operator does not care
                # that it shipped with the app, they care that messaging it
                # reaches a service rather than a person.
                widths.gateway_label,
                key=f"service:{service.id}",
            )

    def _contacts_table_width(self) -> int:
        """How many cells the contacts table actually has to draw in.

        Zero before the first layout pass, and while the column is hidden --
        `_column_widths` clamps to a sane minimum rather than dividing up
        nothing, and `Resize` recomputes as soon as a real width exists.
        """
        table = self.query_one("#aprs-contact-table", DataTable)
        # The vertical scrollbar always shows here (seventeen services plus
        # the operator's own contacts overflow any realistic height), so its
        # width is not ours to spend.
        return max(table.size.width - table.scrollbar_size_vertical, 0)

    def contacts_table_resized(self) -> None:
        """Re-split the columns when the table's width changes.

        A `DataTable`'s column widths are set when the column is added, so a
        table laid out for one terminal size keeps those widths forever
        otherwise -- and this pane is a slide-out, so its width changes on
        every toggle as well as on a real terminal resize.
        """
        table = self.query_one("#aprs-contact-table", DataTable)
        if not table.columns:
            return
        widths = _column_widths(self._contacts_table_width())
        wanted = (widths.callsign, widths.name, widths.detail, widths.service)
        columns = list(table.columns.values())
        if len(columns) != len(wanted):
            return
        if all(column.width == width for column, width in zip(columns, wanted)):
            return
        # A changed gateway label is a cell edit, not a width one, so go
        # through the full rebuild rather than poking column widths in place.
        self.refresh_from(self._contacts())

    def _contacts(self) -> list[dict]:
        return self.app.config.aprs_contacts  # type: ignore[attr-defined]

    def _selected_key(self) -> str | None:
        table = self.query_one("#aprs-contact-table", DataTable)
        if table.row_count == 0 or table.cursor_coordinate is None:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        return None if row_key.value is None else str(row_key.value)

    def _selected_index(self) -> int | None:
        """The `Config.aprs_contacts` index under the cursor, or None.

        None also covers a built-in service row, whose key is `service:<id>`
        rather than a number -- built-ins are not stored in that list at all,
        so there is no index to give. Callers that care about the difference
        use `_selected_service_id` as well.
        """
        key = self._selected_key()
        if key is None or key.startswith("service:"):
            return None
        try:
            return int(key)
        except ValueError:
            return None

    def _selected_service_id(self) -> str | None:
        """The shipped-directory id under the cursor, or None for a saved
        contact."""
        key = self._selected_key()
        if key is None or not key.startswith("service:"):
            return None
        return key.split(":", 1)[1]

    @on(DataTable.RowSelected, "#aprs-contact-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        key = None if event.row_key.value is None else str(event.row_key.value)
        if key is None:
            return
        if key.startswith("service:"):
            # A built-in behaves exactly like picking a contact: address it
            # and show whatever history exists. It is a real callsign you can
            # really message; the only thing it is not is editable.
            service = aprs_services.lookup(key.split(":", 1)[1])
            if service is None:
                return
            self.query_one("#aprs-to-input", Input).value = service.callsign
            self.select_conversation(
                service.callsign, f"{service.name} ({service.callsign})"
            )
            self._close_contacts_after_pick()
            return
        try:
            index = int(key)
        except ValueError:
            return
        raw_contacts = self._contacts()
        if index < 0 or index >= len(raw_contacts):
            return
        contact = Contact.from_dict(raw_contacts[index])
        self.query_one("#aprs-to-input", Input).value = contact.callsign
        self._show_conversation(index)
        # Picking a contact closes the panel -- the conversation just loaded
        # is what the operator wants to look at next, not a panel still
        # covering part of the screen. Only if they summoned it; see
        # `_close_contacts_after_pick`.
        self._close_contacts_after_pick()

    def _message_selected(self) -> None:
        """Address the selected row and put the cursor in the message box.

        What "select a contact" is actually for -- Enter on the table and the
        Message button both land here. Works for a gateway service row too:
        a service is a real callsign you really message, and the only thing
        it is not is editable.
        """
        key = self._selected_key()
        if key is None:
            self.app.notify("Select a contact first.", severity="warning")  # type: ignore[attr-defined]
            return
        if key.startswith("service:"):
            service = aprs_services.lookup(key.split(":", 1)[1])
            if service is None:
                return
            callsign, title = service.callsign, f"{service.name} ({service.callsign})"
        else:
            index = self._selected_index()
            raw_contacts = self._contacts()
            if index is None or index < 0 or index >= len(raw_contacts):
                return
            contact = Contact.from_dict(raw_contacts[index])
            callsign, title = contact.callsign, f"{contact.name} ({contact.callsign})"
        self.query_one("#aprs-to-input", Input).value = callsign
        self.select_conversation(callsign, title)
        self._close_contacts_after_pick()
        self.query_one("#aprs-compose-input", Input).focus()

    @on(Button.Pressed, "#aprs-contact-message")
    def _message_pressed(self) -> None:
        self._message_selected()

    def _show_conversation(self, index: int) -> None:
        raw_contacts = self._contacts()
        if index < 0 or index >= len(raw_contacts):
            return
        contact = Contact.from_dict(raw_contacts[index])
        self.select_conversation(contact.callsign, f"{contact.name} ({contact.callsign})")

    def _outgoing_status(self, callsign: str, entry) -> str:
        """The delivery state of one outgoing message, in square brackets.

        APRS messaging is acknowledged end to end, and an operator on a
        marginal path needs to know which of their messages actually landed
        -- "did that get through?" is the question the whole numbered-message
        and ack mechanism exists to answer, and until now the pane threw the
        answer away except for a bare "(acked)".

        The four states are genuinely different actions for the operator:

        * `ack`      -- the far end confirmed it. Done.
        * `sent`     -- gone out, waiting for the ack. Wait.
        * `retry N`  -- no ack yet and we have resent it N times. Still
                        waiting, but the path is not looking good.
        * `no ack`   -- we stopped retrying and never heard one. Nothing else
                        is going to happen on its own; send it again, or try
                        another path. This also covers a message from before
                        a restart, because the retry queue is deliberately
                        in-memory only (see `aprs_conversations`'s docstring
                        -- kissterm must not resume transmitting into an old
                        conversation on launch), so "we have forgotten" and
                        "we gave up" are honestly the same claim here.

        A message we sent with no number at all is unackable by construction
        and says so rather than pretending it is waiting for something.
        """
        if entry.acked:
            return "ack"
        if entry.number is None:
            return "no ack requested"
        attempts = self._pending.attempts_for(callsign, entry.number)
        if attempts is None:
            return "no ack"
        return "sent" if attempts == 0 else f"retry {attempts}"

    def _show_conversation_for(self, callsign: str, title: str) -> None:
        """Repaint the conversation log for `callsign`.

        The render step only -- it does not open or activate a tab. Everything
        that means "show me this conversation" goes through
        `select_conversation`; this is what that and `TabActivated` both call
        once the strip already agrees whose log is on screen.
        """
        callsign = callsign.strip().upper()
        # Remembered so a status change (an ack arriving, a retry going out)
        # can repaint the view the operator is actually looking at, rather
        # than only correcting itself the next time they click a contact.
        self._shown_callsign = callsign
        self._shown_title = title
        title_widget = self.query_one("#aprs-conversation-title", Static)
        title_widget.update(title)
        title_widget.display = True
        log = self.query_one("#aprs-conversation-log", RichLog)
        log.clear()
        store = self.app.aprs_conversations  # type: ignore[attr-defined]
        convo = store.conversations.get(callsign)
        if convo is None or not convo.messages:
            log.write("(no messages yet)")
            return
        for entry in convo.messages:
            if entry.direction == "in":
                log.write(f"< {entry.text}")
            else:
                log.write(f"> {entry.text}  [{self._outgoing_status(callsign, entry)}]")

    def refresh_conversation(self) -> None:
        """Repaint whichever tab is on screen -- a conversation, or "All".

        Called when a status may have changed underneath the view: an ack
        arriving on the frame fan-out, a new message, or the retry timer
        resending. Cheap (a `RichLog` rewrite) and idempotent.
        """
        try:
            active = self._tabs().active
        except NoMatches:
            # The pane is mounted but its children are not composed yet. This
            # runs off the frame fan-out, which outlives the widget tree in
            # both directions -- same tolerance `_repaint_aprs_conversation`
            # applies to the pane itself.
            return
        if active == _ALL_TAB:
            self._show_all()
        elif self._shown_callsign:
            self._show_conversation_for(self._shown_callsign, self._shown_title)

    # -- new / edit / forget -------------------------------------------------
    def _new_contact(self) -> None:
        self._edit_contact(None)

    @on(Button.Pressed, "#aprs-contact-new")
    def _new_pressed(self) -> None:
        self._new_contact()

    def _edit_selected(self) -> None:
        service_id = self._selected_service_id()
        if service_id is not None:
            # A built-in cannot be edited in place -- it is shipped data, not
            # the operator's. Offering to save a copy is the useful move
            # instead of an error: the reason to "edit" SMSGTE is to attach
            # your own phone number to it, which is a new contact.
            self._copy_service_to_contact(service_id)
            return
        index = self._selected_index()
        if index is None:
            self.app.notify("Select a contact first.", severity="warning")  # type: ignore[attr-defined]
            return
        self._edit_contact(index)

    @work
    async def _copy_service_to_contact(self, service_id: str) -> None:
        """Open the contact editor prefilled from a shipped service, as a NEW
        contact. Never touches the built-in row itself."""
        from .dialogs import AprsContactScreen

        service = aprs_services.lookup(service_id)
        if service is None:
            return
        self.app.notify(  # type: ignore[attr-defined]
            f"{service.callsign} is built in and cannot be edited. "
            "Saving your own copy instead."
        )
        result = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            AprsContactScreen(
                name=service.name,
                callsign=service.callsign,
                gateway=service.id,
                sms_gateway=getattr(self.app.config, "aprs_sms_gateway", ""),  # type: ignore[attr-defined]
                email_gateway=getattr(self.app.config, "aprs_email_gateway", ""),  # type: ignore[attr-defined]
            )
        )
        if result is None:
            return
        raw_contacts = self._contacts()
        raw_contacts.append(result.to_dict())
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(raw_contacts)
        self.app.notify(f"Saved {result.name!r}.")  # type: ignore[attr-defined]

    @on(Button.Pressed, "#aprs-contact-edit")
    def _edit_pressed(self) -> None:
        self._edit_selected()

    def _forget_selected(self) -> None:
        service_id = self._selected_service_id()
        if service_id is not None:
            self._hide_service(service_id)
            return
        index = self._selected_index()
        if index is None:
            return
        raw_contacts = self._contacts()
        if index < 0 or index >= len(raw_contacts):
            return
        removed = raw_contacts.pop(index)
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(raw_contacts)
        self.app.notify(f"Forgot {removed.get('name', '(unnamed)')!r}.")  # type: ignore[attr-defined]

    def _hide_service(self, service_id: str) -> None:
        """Delete on a built-in row hides it (`Config.aprs_hidden_services`).

        A built-in is not stored in `Config.aprs_contacts`, so there is
        nothing to delete; refusing outright would make the key look broken,
        and most operators will never use most of seventeen services. Hiding
        is the honest middle -- reversible by hand in `config.toml`, and the
        notification says so rather than leaving the row's disappearance
        looking permanent.
        """
        service = aprs_services.lookup(service_id)
        hidden = self.app.config.aprs_hidden_services  # type: ignore[attr-defined]
        if service_id not in hidden:
            hidden.append(service_id)
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(self._contacts())
        name = service.name if service is not None else service_id
        self.app.notify(  # type: ignore[attr-defined]
            f"Hid {name}. Remove it from aprs_hidden_services in config.toml "
            "to get it back."
        )

    @on(Button.Pressed, "#aprs-contact-forget")
    def _forget_pressed(self) -> None:
        self._forget_selected()

    @work
    async def _edit_contact(self, index: int | None) -> None:
        from .dialogs import AprsContactScreen

        raw_contacts = self._contacts()
        existing = Contact.from_dict(raw_contacts[index]) if index is not None else None
        result = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            AprsContactScreen(
                name=existing.name if existing else "",
                callsign=existing.callsign if existing else "",
                service=existing.service if existing else "station",
                detail=existing.detail if existing else "",
                notes=existing.notes if existing else "",
                gateway=existing.gateway if existing else "",
                sms_gateway=getattr(self.app.config, "aprs_sms_gateway", ""),  # type: ignore[attr-defined]
                email_gateway=getattr(self.app.config, "aprs_email_gateway", ""),  # type: ignore[attr-defined]
            )
        )
        if result is None:
            return
        if index is not None:
            raw_contacts[index] = result.to_dict()
        else:
            raw_contacts.append(result.to_dict())
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(raw_contacts)
        self.app.notify(f"Saved {result.name!r}.")  # type: ignore[attr-defined]

    # -- templates -----------------------------------------------------------
    @on(Button.Pressed, "#aprs-templates-button")
    def _templates_pressed(self) -> None:
        self.show_templates()

    @work
    async def show_templates(self) -> None:
        """What to say to whoever is in "To:". `Ctrl+R`'s target on this pane.

        Scoped to the current addressee rather than showing all seventeen
        services at once: an operator composing to `WLNK-1` wants Winlink's
        commands, and making them pick the service again -- having already
        picked the contact -- is a step that exists only because the code
        found it convenient.

        **The result fills the compose box and is never sent.** See
        `AprsServiceScreen`'s docstring and AGENTS.md's completion rule. The
        text lands in the input exactly as `CommandReferenceScreen`'s pick
        lands in the terminal's send line, and goes out only when the
        operator commits it.
        """
        from .dialogs import AprsServiceScreen

        addressee = self.query_one("#aprs-to-input", Input).value.strip()
        contact = self._contact_for(addressee)
        # The contact's own `gateway` wins over a callsign match: an operator
        # who deliberately saved "this contact is WXBOT" is more
        # authoritative than the directory, and it also covers a gateway
        # reachable at a callsign the shipped table does not know.
        service = None
        if contact is not None and contact.gateway:
            service = aprs_services.lookup(contact.gateway)
        if service is None:
            service = aprs_services.lookup_callsign(addressee)
        saved = canned_messages_for(
            self.app.config.aprs_templates,  # type: ignore[attr-defined]
            service.id if service is not None else "",
        )
        chosen = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            AprsServiceScreen(service, saved, addressee=addressee)
        )
        if not chosen:
            return
        field = self.query_one("#aprs-compose-input", Input)
        field.value = chosen
        field.focus()
        field.action_end()

    # -- sending, ack, retry -------------------------------------------------
    def _next_number(self) -> str:
        number = str(self._next_msg_number)
        self._next_msg_number = self._next_msg_number % 99999 + 1
        return number

    def _contact_for(self, callsign: str) -> Contact | None:
        """The saved contact whose `callsign` matches, or `None` for a bare
        "To:" target that matches no saved contact at all -- messaging
        someone not in the contact list always behaves like "station"
        service (plain text, no template), the only thing that makes sense
        for a contact this pane knows nothing else about."""
        callsign = callsign.strip().upper()
        for raw in self._contacts():
            if str(raw.get("callsign", "")).strip().upper() == callsign:
                return Contact.from_dict(raw)
        return None

    @on(Button.Pressed, "#aprs-send-button")
    @on(Input.Submitted, "#aprs-compose-input")
    def _send_pressed(self) -> None:
        self._send_compose()

    @work
    async def _send_compose(self) -> None:
        addressee = self.query_one("#aprs-to-input", Input).value.strip()
        text_field = self.query_one("#aprs-compose-input", Input)
        text = text_field.value.strip()
        if not addressee:
            self.app.notify("Type a callsign to send to.", severity="warning")  # type: ignore[attr-defined]
            return
        if not text:
            return
        contact = self._contact_for(addressee)
        service = contact.service if contact else "station"
        detail = contact.detail if contact else ""
        config = self.app.config  # type: ignore[attr-defined]
        wire_text = build_message_body(
            service,
            detail,
            text,
            sms_template=getattr(config, "aprs_sms_template", ""),
            email_template=getattr(config, "aprs_email_template", ""),
        )
        number = self._next_number()
        # A confirmed connect arms the gate rather than being refused by it
        # (`KissTermApp._arm_for`); typing a message, naming a "To:", and
        # pressing Enter or Send is the same shape of request -- refusing it
        # with "transmit is disabled" would be the identical dead end.
        # **Never called from `_retry_worker`**: an automatic retry is
        # unattended, exactly what the gate exists to hold back, so it goes
        # straight to `_send_aprs_message` and stays silently dropped while
        # the gate is closed. Guarded on `self.app.station` the same way
        # `TerminalPane.send_line` guards on `link.connected` -- arming for a
        # send that has nothing to go out on would open the gate for nothing.
        if self.app.station is not None:  # type: ignore[attr-defined]
            self.app._arm_for(f"sending to {addressee}")  # type: ignore[attr-defined]
        ok = await self.app._send_aprs_message(addressee, wire_text, number)  # type: ignore[attr-defined]
        if not ok:
            self.app.notify(  # type: ignore[attr-defined]
                "Message not sent -- transmit is disabled (Ctrl+T).", severity="warning"
            )
            return
        # The conversation log keeps what the operator actually typed, not
        # the templated wire body -- readable history, not a wire dump.
        # A retry, though, must resend the exact bytes that went out the
        # first time, so `_pending` tracks `wire_text`, not `text`.
        self.app.aprs_conversations.record_outgoing(  # type: ignore[attr-defined]
            addressee, text, number=number, service=service
        )
        self._pending.add(addressee, number, wire_text)
        text_field.value = ""
        # Sending to someone opens their tab if they did not have one -- the
        # conversation you just started is one you are in.
        key = addressee.strip().upper()
        self.select_conversation(addressee, self._tab_titles.get(key, key))

    def _check_retries(self) -> None:
        self._retry_worker()

    @work
    async def _retry_worker(self) -> None:
        store = self.app.aprs_conversations  # type: ignore[attr-defined]
        self._pending.discard_acked(store)
        for callsign, number, text in self._pending.due():
            await self.app._send_aprs_message(  # type: ignore[attr-defined]
                callsign, text, number, retry=True
            )
        # An ack may have landed and a retry may have gone out since the last
        # paint; both change what the status column should say. Repainting
        # here is what makes "sent" become "ack" on screen without the
        # operator having to click away and back.
        self.refresh_conversation()
