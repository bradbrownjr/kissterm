"""Modal screens layered on top of the app.

`ConnectScreen` is the only one that exists today, but it is pulled out into
its own module rather than left inline in `app.py` because it will not stay
the only one -- a "confirm disconnect", a transport picker, or a settings
editor (roadmap P6) are all `ModalScreen`s, and each one is a small, mostly
self-contained unit that a future editor should be able to add or change
without touching `app.py`'s bindings or fan-out wiring at all. Add new
modals here.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Select, Static, Tab, Tabs, TextArea

from ..addressbook import AddressBook
from ..aprs_contacts import (
    CannedMessage,
    Contact,
    normalize_service,
    validate_canned_message,
    validate_contact,
)
from ..ax25 import parse_path
from .wraplog import WrapLog


@dataclass(frozen=True)
class ConnectRequest:
    """What the Connect dialog hands back: where to connect, and what to
    do once there.

    `hops` is a comma-separated chain of intermediate nodes to reach
    `target` node-to-node, for when no digipeater path does the job --
    almost always empty. `script`/`credential`/`script_name` are the three
    mutually exclusive ways to say what to send once the FULL chain (or the
    plain direct connect, if `hops` is empty) comes up, checked in that
    order by `KissTermApp._resolve_login`: the name of a saved credential,
    the name of a saved script, or literal text -- see `Config.credentials`
    for why a login and a script are two separate saved lists rather than
    one, and `_run_connect_script` for how the winning text gets sent.

    `transport_name`, when non-empty and different from the currently
    active transport, asks `action_connect` to switch to it (via
    `KissTermApp._switch_frame_transport`) BEFORE dialing -- only ever a
    same-tier alternative to whatever this dialog was shown for, since
    `ConnectScreen` itself only appears on the frame tier; see
    `transport.FRAME_TIER_KINDS`'s docstring for why a live tier switch is
    not offered anywhere.
    """

    target: str
    script: str = ""
    hops: str = ""
    credential: str = ""
    script_name: str = ""
    transport_name: str = ""
    #: Non-empty only when the operator typed a NAME next to the literal
    #: login text under "+ Add new credential..." in `ConnectScreen` -- see
    #: that screen's `_ADD_CREDENTIAL` sentinel. `credential` already holds
    #: the chosen name in that case; `KissTermApp.action_connect` is what
    #: actually writes `{"name": credential, "text": new_credential_text}`
    #: into `Config.credentials` (replacing a same-named entry rather than
    #: duplicating it) before resolving the login, because a dialog has no
    #: business mutating `Config` itself -- see `_resolve_login`.
    new_credential_text: str = ""
    #: KISS/AGW radio port selected for this attempt.  This is deliberately
    #: per-attempt rather than an Address Book property: the same node may be
    #: reachable on different channels as the operator changes the station.
    port: int = 0


def _validate_target_and_hops(text: str, hops: str) -> tuple[object | None, str]:
    """Parse `text` as a connect target, refusing to combine it with node
    hops. Returns `(path, "")` on success or `(None, message)` on failure --
    shared by `ConnectScreen` and `AddressBookEntryScreen`, which both offer
    the same two addressing mechanisms and must refuse the same conflict:
    a digipeater path repeats ONE frame at the link layer, node hops are a
    sequence of independent connects made minutes apart, and the two do not
    compose.
    """
    try:
        path = parse_path(text)
    except Exception as exc:
        return None, str(exc)
    if hops and path.repeaters:
        return None, "Can't combine a digipeater path (via ...) with node hops -- pick one."
    return path, ""


def _validate_link_params(paclen: str, window: str) -> str:
    """Blank means "use `Config.paclen`/`window`" for both -- the common
    case, and every entry until an operator sets one. Only checks that a
    non-blank value is a positive whole number; the actual range clamp
    (paclen to 256, window to 7 or 63 depending on modulo) lives once, in
    `LinkParams.__post_init__`, which runs again at connect time -- this is
    just enough to keep an obviously-wrong value (blank of a different
    kind, "abc", "-1") out of the address book rather than duplicating that
    clamp here and risking the two drifting apart.
    """
    for label, value in (("Paclen", paclen), ("Window", window)):
        if value and not (value.isdigit() and int(value) >= 1):
            return f"{label} must be blank or a whole number of 1 or more."
    return ""


def _select_has_value(select: Select) -> bool:
    return bool(select.value) and select.value is not Select.NULL


def _sync_login_source_controls(
    credential_select: Select, script_select: Select, area: TextArea
) -> None:
    """Keep the three login sources -- a saved credential, a saved script,
    and literal text -- mutually consistent on screen, matching the order
    `KissTermApp._resolve_login` actually picks one in: credential, then
    script, then literal text.

    Shared by `ConnectScreen`, `AddressBookEntryScreen` and
    `TransportEntryScreen`. Deliberately never CLEARS a losing control's
    value, only disables it: clearing on every dropdown change is how a
    credential's password would end up copied into the text box and then
    silently saved as another station's "custom" script the next time the
    dropdown resets to blank, and clearing the script pick the same way
    would lose it the moment a credential is tried and then reconsidered.
    Leaving values alone and merely disabling the ones a higher-precedence
    choice shadows means none of the three can contaminate another -- each
    screen's submit handler reads a control only when nothing above it in
    the precedence order is set.
    """
    has_credential = _select_has_value(credential_select)
    has_script = _select_has_value(script_select)
    script_select.disabled = has_credential
    area.disabled = has_credential or has_script


#: `ConnectScreen`'s Saved-credential dropdown grows a trailing sentinel
#: option that means "define a new one inline" rather than "pick an
#: existing one" -- see that screen's docstring for why this, and the
#: matching `_SHOW_HOPS` sentinel, exist at all.
_ADD_CREDENTIAL = "__add_credential__"
#: `ConnectScreen`'s Saved-script dropdown's equivalent sentinel: not a
#: script at all, just the switch that reveals the Node hops field.
_SHOW_HOPS = "__show_hops__"


class ConnectScreen(ModalScreen[ConnectRequest | None]):
    """Ask for a connect target. Accepts ``CALL-SSID [via DIGI,DIGI]``.

    Carries an address book of stations already tried, because `WS1EC-15` and
    `WS1EC-7` are different services on one machine and a mistyped SSID fails
    in a way that looks exactly like a bad RF path. The book shows as the
    "Address book" dropdown: typing in the target field narrows its options,
    Down focuses and opens it, picking a row fills the target field and
    previews everything saved for that station, and Delete (with the
    dropdown focused) forgets whatever row it last picked. The book is
    loaded here rather than passed in so the dialog works in a test with no
    app around it, and it is optional: pass `book=AddressBook(path)` to
    point it somewhere else.

    Two fields that matter to almost nobody's everyday connect -- node hops
    and a hand-typed, unnamed login -- do not get their own permanent rows.
    A quick connect is "type a callsign, hit Connect", and a field that is
    blank 99% of the time earns its place in that layout only by staying out
    of the way until asked for:

    - Node hops lives under the Saved-script dropdown, revealed by picking
      "+ Node hops (advanced)..." there (`_SHOW_HOPS`) -- or automatically
      when an address-book pick already has some, so a value that exists is
      never hidden from the operator editing it.
    - The free-text login box lives under Saved credential, revealed by
      picking "+ Add new credential..." there (`_ADD_CREDENTIAL`) -- typing
      a Name next to it there defines a new, reusable, named entry in
      `Config.credentials` (via `ConnectRequest.new_credential_text`,
      applied by `KissTermApp.action_connect`); leaving Name blank keeps the
      text a one-off, exactly like today's unnamed literal login. Same
      auto-reveal rule for a preview that already has script text.

    `credentials`/`scripts` are the raw `Config.credentials`/`Config.scripts`
    lists of `{"name", "text"}` dicts, for the two "send once connected"
    dropdowns; both default to none, so the dialog still works in a test or
    a script with no config around it.
    """

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("down", "into_list", "Address book", show=False),
        Binding("delete", "forget", "Forget", show=False),
    ]

    def __init__(
        self,
        book: AddressBook | None = None,
        credentials: list[dict] | None = None,
        scripts: list[dict] | None = None,
        transports: list[dict] | None = None,
        active_transport_name: str = "",
        ports: int = 1,
    ) -> None:
        super().__init__()
        if book is None:
            book = AddressBook()
            book.load()
        self.book = book
        self.credentials = credentials or []
        self.scripts = scripts or []
        # Same-tier alternatives only -- the caller (`KissTermApp.action_
        # connect`) has already filtered to whichever tier this dialog is
        # being shown for. Shown only with a real choice to make: one
        # transport is the overwhelming common case, and a dropdown that
        # can only ever show the transport already in use is not a control,
        # it is decoration.
        self.transports = transports or []
        self.active_transport_name = active_transport_name
        self.ports = max(1, ports)
        # NOT read from `#connect-address-book`'s own `.value` at forget
        # time -- `Select.set_options` unconditionally resets `.value` to
        # blank, and picking a row does exactly that a moment later by
        # filling the target field, which re-filters this same dropdown
        # (see `_render_history`). By the time a Delete keypress could ever
        # land, `.value` is already back to blank again; this is what
        # `_pick_from_address_book` actually remembers was picked, and what
        # `action_forget` acts on.
        self._last_picked = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Connect to station", id="connect-title")
            if len(self.transports) > 1:
                from ..transport import KIND_LABELS

                options = [
                    (f"{name} ({KIND_LABELS.get(t.get('kind', ''), '?')})", name)
                    for t in self.transports
                    if (name := t.get("name"))
                ]
                known = {value for _, value in options}
                yield Select(
                    options,
                    value=(
                        self.active_transport_name
                        if self.active_transport_name in known
                        else options[0][1]
                    ),
                    id="connect-transport",
                    allow_blank=False,
                )
            if self.ports > 1:
                yield Select(
                    [(f"Radio port {port}", port) for port in range(self.ports)],
                    value=0,
                    id="connect-port",
                    allow_blank=False,
                )
            yield Input(
                placeholder="WS1EC-7  or  WS1EC-7 via W1AW-1",
                id="connect-target",
            )
            yield Select([], id="connect-address-book", prompt="Address book")
            yield Label(
                "Enter to connect - Delete forgets the picked entry",
                id="connect-hint",
            )
            yield Label("", id="connect-error")
            yield Label("Auto-login (optional)", id="connect-script-title")
            yield Static(
                "Pick a saved credential or script -- both have an option to"
                " add a new one.",
                id="connect-script-hint",
            )
            yield Select(
                [],
                id="connect-credential",
                allow_blank=True,
                prompt="Saved credential",
            )
            yield Input(
                placeholder="Name to save this login as (optional)",
                id="connect-credential-name",
            )
            yield TextArea(
                id="connect-script",
                tab_behavior="focus",
                placeholder="One line per prompt, e.g. your callsign then password",
            )
            yield Select(
                [],
                id="connect-script-name",
                allow_blank=True,
                prompt="Saved script",
            )
            yield Input(
                placeholder="Node hops, e.g. N1QFY, AB1KI-15",
                id="connect-hops",
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Connect", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        self._render_history()
        self._render_credentials()
        self._render_scripts()
        self._sync_login_controls()
        self.query_one("#connect-target", Input).focus()

    def _render_credentials(self) -> None:
        select = self.query_one("#connect-credential", Select)
        options = [(name, name) for c in self.credentials if (name := c.get("name"))]
        options.append(("+ Add new credential...", _ADD_CREDENTIAL))
        select.set_options(options)

    def _render_scripts(self) -> None:
        select = self.query_one("#connect-script-name", Select)
        options = [(name, name) for s in self.scripts if (name := s.get("name"))]
        options.append(("+ Node hops (advanced)...", _SHOW_HOPS))
        select.set_options(options)

    # -- the address book -------------------------------------------------
    def _render_history(self, filter_text: str = "") -> None:
        """Repaint the dropdown, narrowed to entries matching `filter_text`.

        The filter is a plain case-insensitive substring on the whole typed
        target, so "ws1" narrows to one machine's services and "via" finds
        the paths that need a digipeater. `Select.set_options` always resets
        the control's own value to blank, which is exactly what is wanted
        here -- every keystroke re-filtering is not the operator picking
        blank on purpose, so `_pick_from_address_book` ignores that reset
        rather than treating it as "clear the preview".
        """
        needle = filter_text.strip().upper()
        matches = [e for e in self.book.entries if needle in e.target.upper()]
        options = [
            (
                f"{e.target}"
                f"{'  --  ' + e.summary if e.summary else ''}"
                f"{'  [via nodes]' if e.hops else ''}",
                e.target,
            )
            for e in matches
        ]
        select = self.query_one("#connect-address-book", Select)
        select.set_options(options)
        select.display = bool(options)
        self.query_one("#connect-hint", Label).display = bool(options)

    def action_into_list(self) -> None:
        select = self.query_one("#connect-address-book", Select)
        if not select.display:
            return
        select.focus()
        select.expanded = True

    def action_forget(self) -> None:
        """Forget whatever address-book row the dropdown last picked (see
        `_last_picked`'s docstring for why that is not simply `select.
        value`). Only meaningful with the dropdown focused, so a Delete
        keypress while editing the target text still edits text."""
        select = self.query_one("#connect-address-book", Select)
        if not select.has_focus or not self._last_picked:
            return
        if self.book.forget(self._last_picked):
            self._last_picked = ""
            # The target field held the just-forgotten entry's name (that is
            # what picking it wrote there) -- clearing it, not just
            # re-filtering on it, is what brings the rest of the address
            # book back into view instead of leaving a needle that now
            # matches nothing.
            self.query_one("#connect-target", Input).value = ""
            self._render_history("")
            self.query_one("#connect-hops", Input).value = ""
            self.query_one("#connect-script", TextArea).text = ""
            self.query_one("#connect-credential-name", Input).value = ""
            self.query_one("#connect-credential", Select).value = Select.NULL
            self.query_one("#connect-script-name", Select).value = Select.NULL
            self._sync_login_controls()
            if not self.book.entries:
                self.query_one("#connect-target", Input).focus()

    @on(Select.Changed, "#connect-address-book")
    def _pick_from_address_book(self, event: Select.Changed) -> None:
        """Picking a station fills the target field and previews everything
        saved for it -- its node-hop chain and its login, script or
        credential -- in one step. Still editable before Connect.

        Fires with a blank value on every keystroke in the target field too
        (see `_render_history`'s docstring), which must be a no-op: acting
        on it would wipe out hops/credential/script the operator is mid-way
        through editing by hand.
        """
        value = event.value
        if value is Select.NULL or not value:
            return
        entry = next((e for e in self.book.entries if e.target == value), None)
        if entry is None:
            return
        self._last_picked = entry.target
        self.query_one("#connect-target", Input).value = entry.target
        self.query_one("#connect-hops", Input).value = entry.hops
        self.query_one("#connect-script", TextArea).text = entry.script
        valid_credentials = {c.get("name") for c in self.credentials}
        credential = entry.credential if entry.credential in valid_credentials else ""
        self.query_one("#connect-credential", Select).value = credential or Select.NULL
        valid_scripts = {s.get("name") for s in self.scripts}
        script_name = entry.script_name if entry.script_name in valid_scripts else ""
        self.query_one("#connect-script-name", Select).value = script_name or Select.NULL
        self._sync_login_controls()

    @on(Select.Changed, "#connect-credential")
    @on(Select.Changed, "#connect-script-name")
    def _login_source_changed(self) -> None:
        self._sync_login_controls()

    def _sync_login_controls(self) -> None:
        """Keep the advanced fields' enabled-ness AND visibility consistent
        with the two dropdowns, without ever clearing a value the operator
        typed -- same "disable, never clear" rule as the shared
        `_sync_login_source_controls` this replaces for this screen only
        (`AddressBookEntryScreen`/`TransportEntryScreen` keep that function
        and their own always-visible layout; they were not part of this
        request).

        Visibility follows two independent rules, checked every time this
        runs so a preview that already has a value is never left hidden:
        the credential Name/textarea pair shows for the `_ADD_CREDENTIAL`
        sentinel OR non-blank content; Node hops shows for the `_SHOW_HOPS`
        sentinel OR a non-blank value. Precedence disabling (credential
        beats script beats literal text, per `ConnectRequest`'s docstring)
        only ever considers a REAL pick -- a sentinel is not itself a
        credential or a script, so it must never disable the very field it
        exists to reveal.
        """
        credential_select = self.query_one("#connect-credential", Select)
        script_select = self.query_one("#connect-script-name", Select)
        area = self.query_one("#connect-script", TextArea)
        name_input = self.query_one("#connect-credential-name", Input)
        hops_input = self.query_one("#connect-hops", Input)

        has_credential_pick = _select_has_value(credential_select)
        has_real_script = (
            _select_has_value(script_select) and script_select.value != _SHOW_HOPS
        )

        script_select.disabled = has_credential_pick
        disable_literal = (
            has_credential_pick and credential_select.value != _ADD_CREDENTIAL
        ) or has_real_script
        area.disabled = disable_literal
        name_input.disabled = disable_literal

        show_literal = credential_select.value == _ADD_CREDENTIAL or bool(area.text)
        area.display = show_literal
        name_input.display = show_literal
        hops_input.display = script_select.value == _SHOW_HOPS or bool(hops_input.value)

    @on(Input.Changed, "#connect-target")
    def _filter(self, event: Input.Changed) -> None:
        self._render_history(event.value)

    # -- connect / cancel -------------------------------------------------
    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    @on(Input.Submitted, "#connect-target")
    def _go(self) -> None:
        self._submit(self.query_one("#connect-target", Input).value)

    def _submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        hops = self.query_one("#connect-hops", Input).value.strip()
        _path, error = _validate_target_and_hops(text, hops)
        if error:
            self.query_one("#connect-error", Label).update(f"[red]{error}[/red]")
            return
        credential_select = self.query_one("#connect-credential", Select)
        cred_value = credential_select.value
        credential = ""
        new_credential_text = ""
        if cred_value == _ADD_CREDENTIAL:
            # A name turns the box below into a NEW, reusable, named
            # credential (`KissTermApp.action_connect` is what actually
            # writes it to `Config.credentials`); no name keeps it exactly
            # what a hand-typed login has always been -- literal text used
            # once and saved only on this address-book entry.
            name = self.query_one("#connect-credential-name", Input).value.strip()
            body = self.query_one("#connect-script", TextArea).text
            if name and body:
                credential = name
                new_credential_text = body
        elif _select_has_value(credential_select):
            credential = str(cred_value)
        script_name_select = self.query_one("#connect-script-name", Select)
        script_value = script_name_select.value
        script_name = (
            str(script_value)
            if not credential and _select_has_value(script_name_select) and script_value != _SHOW_HOPS
            else ""
        )
        # A credential (saved or newly-named) or a saved script is
        # authoritative once present -- the literal-text box is disabled
        # whenever one of those wins (see `_sync_login_controls`)
        # specifically so its leftover text is never read here. Otherwise
        # the box's text is read unconditionally, exactly as it always was:
        # that covers both an unnamed "+ Add new credential..." entry (a
        # one-off login) AND a plain address-book preview that carries a
        # per-station literal script with neither dropdown touched.
        script = "" if (credential or script_name) else self.query_one("#connect-script", TextArea).text
        # Recorded on the ATTEMPT, not on success: a connect that failed is
        # the one about to be retried, and withholding it until a UA arrives
        # would keep it out of the list at exactly the moment it is wanted.
        # Everything else travels the same way, blank or not -- a deliberate
        # blank clears a script/hop-chain/credential/saved-script the
        # operator no longer wants.
        transport_name = ""
        if len(self.transports) > 1:
            transport_name = str(self.query_one("#connect-transport", Select).value)
        port = 0
        if self.ports > 1:
            port = int(self.query_one("#connect-port", Select).value)
        self.book.record_attempt(text, script, hops, credential, script_name)
        self.dismiss(
            ConnectRequest(
                text,
                script,
                hops,
                credential,
                script_name,
                transport_name,
                new_credential_text=new_credential_text,
                port=port,
            )
        )


@dataclass(frozen=True)
class AddressBookEdit:
    """What `AddressBookEntryScreen` hands back -- a full entry, not just a
    connect request. `frequency`/`connection_type`/`paclen`/`window` only
    ever come from here; the quick Connect dialog does not manage them, so
    `ConnectRequest` has no equivalent fields and `AddressBook.record_
    attempt` never touches them (see that method's docstring). `paclen`/
    `window` are validated by `_validate_link_params` before this is built,
    so by the time `AddressBook.upsert` sees them they are either empty or a
    string `int()` will accept. `note` is free text an operator wants to
    see again on the next connect ("BBS is on -2, chat needs a callsign") --
    shown by `RadioReminderScreen`, same trigger as `frequency`/
    `connection_type`."""

    target: str
    script: str = ""
    hops: str = ""
    credential: str = ""
    script_name: str = ""
    frequency: str = ""
    connection_type: str = ""
    paclen: str = ""
    window: str = ""
    note: str = ""


class AddressBookEntryScreen(ModalScreen[AddressBookEdit | None]):
    """Add or hand-edit one address-book entry directly, without
    attempting a live connect.

    Same fields and the same via/hops and credential/script rules as the
    lower half of `ConnectScreen`, plus frequency and connection type,
    which exist only here -- a station reached node-to-node, or one with a
    saved login, or one that needs a radio retuned first, should be set up
    correctly once from the Address Book rather than the operator having to
    attempt (and possibly fail) a real connect just to create the entry.
    No history browsing here: the whole point of this screen is that a
    caller already knows which entry it is editing, or that it is a new one.

    "Connection type" picks from `Config.transports` by name rather than
    taking free text -- a reminder is worth nothing if it does not match
    anything the operator actually has set up. It does not change which
    transport a dial actually uses (see `KissTermApp.action_connect`): this
    stays informational, shown on `RadioReminderScreen` before connecting,
    the same way `frequency` always has been. A Telnet/SSH/VARA/Mercury
    transport, or a second entry for hardware already found by a scan, is
    added from Settings (`F6`) > Transports > New (`TransportEntryScreen`);
    this only lists whatever is already configured there.

    "Paclen"/"Window", unlike frequency and connection type, are NOT just a
    reminder -- see `addressbook.Entry.paclen`/`window`. They are exactly
    `ax25.session.LinkParams.paclen`/`window`, so the placeholders describe
    what leaving them blank does (fall back to Settings' global paclen/
    window) rather than repeating field names the operator can already see.

    "Note" is purely informational too, same as frequency and connection
    type -- free text an operator wants back in front of them right before
    connecting ("BBS is on -2, chat needs a callsign"), not something
    kissterm parses or acts on.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        target: str = "",
        script: str = "",
        hops: str = "",
        credential: str = "",
        script_name: str = "",
        frequency: str = "",
        connection_type: str = "",
        paclen: str = "",
        window: str = "",
        note: str = "",
        credentials: list[dict] | None = None,
        scripts: list[dict] | None = None,
        transports: list[dict] | None = None,
    ) -> None:
        super().__init__()
        self._target = target
        self._script = script
        self._hops = hops
        self._credential = credential
        self._script_name = script_name
        self._frequency = frequency
        self._connection_type = connection_type
        self._paclen = paclen
        self._window = window
        self._note = note
        self.credentials = credentials or []
        self.scripts = scripts or []
        self.transports = transports or []

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Address book entry", id="connect-title")
            yield Input(
                value=self._target,
                placeholder="WS1EC-7  or  WS1EC-7 via W1AW-1",
                id="connect-target",
            )
            yield Input(
                value=self._hops,
                placeholder="Node hops, e.g. N1QFY, AB1KI-15 (optional)",
                id="connect-hops",
            )
            with Horizontal(id="addressbook-radio-row"):
                yield Input(
                    value=self._frequency,
                    placeholder="Frequency (optional)",
                    id="addressbook-frequency",
                )
                yield Select(
                    [],
                    id="addressbook-connection-type",
                    allow_blank=True,
                    prompt="Connection type",
                )
            with Horizontal(id="addressbook-link-row"):
                yield Input(
                    value=self._paclen,
                    placeholder="Paclen (optional, default from Settings)",
                    id="addressbook-paclen",
                )
                yield Input(
                    value=self._window,
                    placeholder="Window/k (optional, default from Settings)",
                    id="addressbook-window",
                )
            yield Input(
                value=self._note,
                placeholder="Note, shown before connecting (e.g. 'BBS is on -2')",
                id="addressbook-note",
            )
            yield Label("", id="connect-error")
            yield Label("Auto-login (optional)", id="connect-script-title")
            yield Static(
                "Pick a saved credential or script, or type a login below.",
                id="connect-script-hint",
            )
            yield Select(
                [],
                id="connect-credential",
                allow_blank=True,
                prompt="Saved credential",
            )
            yield Select(
                [],
                id="connect-script-name",
                allow_blank=True,
                prompt="Saved script",
            )
            yield TextArea(
                self._script,
                id="connect-script",
                tab_behavior="focus",
                placeholder="One line per prompt, e.g. your callsign then password",
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        credential_select = self.query_one("#connect-credential", Select)
        credential_select.set_options(
            (name, name) for c in self.credentials if (name := c.get("name"))
        )
        valid_credentials = {c.get("name") for c in self.credentials}
        credential_select.value = (
            self._credential if self._credential in valid_credentials else Select.NULL
        )
        script_name_select = self.query_one("#connect-script-name", Select)
        script_name_select.set_options(
            (name, name) for s in self.scripts if (name := s.get("name"))
        )
        valid_scripts = {s.get("name") for s in self.scripts}
        script_name_select.value = (
            self._script_name if self._script_name in valid_scripts else Select.NULL
        )
        self._sync_login_controls()
        self._render_connection_types()
        field = self.query_one("#connect-target", Input)
        field.focus()
        field.action_end()

    def _render_connection_types(self) -> None:
        """List the operator's own configured transports by name, e.g.
        "direwolf-local (TCP KISS)" -- see the class docstring for why this
        is a picklist of real transports rather than free text.
        """
        from ..transport import KIND_LABELS

        options = [
            (f"{name} ({KIND_LABELS.get(t.get('kind', ''), t.get('kind', '?'))})", name)
            for t in self.transports
            if (name := t.get("name"))
        ]
        known = {value for _, value in options}
        # A value saved before this became a picklist, or naming a transport
        # since renamed or removed, must still round-trip -- show exactly
        # what was saved as its own option rather than crashing (a plain
        # `Select` raises if `.value` is set outside its options) or
        # silently discarding it.
        if self._connection_type and self._connection_type not in known:
            options.append((self._connection_type, self._connection_type))
        select = self.query_one("#addressbook-connection-type", Select)
        select.set_options(options)
        select.value = self._connection_type if self._connection_type else Select.NULL

    @on(Select.Changed, "#connect-credential")
    @on(Select.Changed, "#connect-script-name")
    def _login_source_changed(self) -> None:
        self._sync_login_controls()

    def _sync_login_controls(self) -> None:
        _sync_login_source_controls(
            self.query_one("#connect-credential", Select),
            self.query_one("#connect-script-name", Select),
            self.query_one("#connect-script", TextArea),
        )

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    @on(Input.Submitted, "#connect-target")
    def _save(self) -> None:
        text = self.query_one("#connect-target", Input).value.strip()
        if not text:
            return
        hops = self.query_one("#connect-hops", Input).value.strip()
        _path, error = _validate_target_and_hops(text, hops)
        if error:
            self.query_one("#connect-error", Label).update(f"[red]{error}[/red]")
            return
        credential_select = self.query_one("#connect-credential", Select)
        credential = str(credential_select.value) if _select_has_value(credential_select) else ""
        script_name_select = self.query_one("#connect-script-name", Select)
        script_name = (
            str(script_name_select.value)
            if not credential and _select_has_value(script_name_select)
            else ""
        )
        script = (
            "" if (credential or script_name) else self.query_one("#connect-script", TextArea).text
        )
        frequency = self.query_one("#addressbook-frequency", Input).value.strip()
        type_value = self.query_one("#addressbook-connection-type", Select).value
        connection_type = (
            str(type_value) if type_value and type_value is not Select.NULL else ""
        )
        paclen = self.query_one("#addressbook-paclen", Input).value.strip()
        window = self.query_one("#addressbook-window", Input).value.strip()
        link_error = _validate_link_params(paclen, window)
        if link_error:
            self.query_one("#connect-error", Label).update(f"[red]{link_error}[/red]")
            return
        note = self.query_one("#addressbook-note", Input).value.strip()
        self.dismiss(
            AddressBookEdit(
                text,
                script,
                hops,
                credential,
                script_name,
                frequency,
                connection_type,
                paclen,
                window,
                note,
            )
        )


class RadioReminderScreen(ModalScreen[bool]):
    """A checkpoint before connecting to a station with a frequency or
    connection type on file.

    kissterm does not control a radio -- it cannot tune one or turn a modem
    on -- so a saved frequency or connection type is worth nothing if the
    operator only sees it after the SABMs have already gone out on
    whatever the radio happened to be left on. This is a blocking Connect/
    Cancel step, not a notification, for the same reason `_arm_for`
    requires a confirmed, targeted action rather than firing on a bare
    keystroke: a reminder nobody has to look at is not a reminder. Shown
    only when the entry actually has something to remind about -- most
    connects skip it entirely.

    `note` is the same idea for anything that is not a frequency or a
    connection type -- "BBS is on -2, chat needs a callsign" is exactly
    the kind of thing an operator wants back in front of them here, not
    something they should have to remember on their own between sessions.
    """

    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(
        self, frequency: str = "", connection_type: str = "", note: str = ""
    ) -> None:
        super().__init__()
        self._frequency = frequency
        self._connection_type = connection_type
        self._note = note

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Before connecting", id="connect-title")
            lines = []
            if self._frequency:
                lines.append(f"Frequency: {self._frequency}")
            if self._connection_type:
                lines.append(f"Connection: {self._connection_type}")
            if self._note:
                lines.append(f"Note: {self._note}")
            yield Static("\n".join(lines), id="reminder-detail")
            yield Label(
                "Turn on or tune the radio/modem, then Connect.",
                id="connect-hint",
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Connect", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        self.query_one("#connect-go", Button).focus()

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#connect-go")
    def _go(self) -> None:
        self.dismiss(True)


class SessionTransportPickerScreen(ModalScreen[str | None]):
    """Pick which session-tier transport to connect through (Telnet, SSH,
    VARA, Mercury, kernel AX.25) -- `Ctrl+N`'s equivalent of `ConnectScreen`
    for this tier.

    Only ever shown with a real choice to make: `KissTermApp.action_connect`
    skips this entirely when the app has one session-tier transport
    configured, which is the overwhelming common case, and goes straight to
    `_connect_session_transport` exactly as it always has. There is no
    target field here at all -- a session transport's destination is fixed
    at its own configuration (a host and port, or a callsign for VARA/
    kernel AX.25), not something typed per attempt; see `SessionTransport.
    connect`'s docstring. Switching tiers (to or from a frame-tier KISS TNC)
    is not offered here or anywhere live -- see `transport.FRAME_TIER_
    KINDS`'s docstring.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, transports: list[dict], active_name: str = "") -> None:
        super().__init__()
        self.transports = transports
        self.active_name = active_name

    def compose(self) -> ComposeResult:
        from ..transport import KIND_LABELS

        options = [
            (f"{name} ({KIND_LABELS.get(t.get('kind', ''), '?')})", name)
            for t in self.transports
            if (name := t.get("name"))
        ]
        known = {value for _, value in options}
        with Vertical(id="connect-box"):
            yield Label("Connect via", id="connect-title")
            yield Select(
                options,
                value=self.active_name if self.active_name in known else options[0][1],
                id="connect-transport",
                allow_blank=False,
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Connect", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        self.query_one("#connect-go", Button).focus()

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    def _go(self) -> None:
        self.dismiss(str(self.query_one("#connect-transport", Select).value))


@dataclass(frozen=True)
class Credential:
    """One saved login, as `CredentialScreen` hands it back."""

    name: str
    text: str


class CredentialScreen(ModalScreen[Credential | None]):
    """Add or edit one saved credential OR one saved script (Settings >
    Credentials / Scripts) -- same shape, same dialog.

    Kept deliberately simple -- a name and a block of text, nothing
    structured -- because packet BBS logins do not agree on a shape: some
    want a bare password, some want a real name and a password, some want a
    CBBS-style multi-field login, and a script is any sequence at all. A
    named block of text sent one line at a time covers all of them without
    guessing a schema that will not fit the next BBS someone connects to.

    `kind` picks only the words shown -- "credential" or "script" -- never
    the shape of what is saved or how it is used; `Config.credentials` and
    `Config.scripts` are kept as two separate lists by the CALLER
    (`SettingsPane`), for the reasons in that field's docstring. This
    dialog has no opinion on which list it is editing.

    Saving here does not touch `config.toml` itself -- the caller
    (`SettingsPane`) folds the result into the right list and saves the
    whole config, same as every other Settings field.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, name: str = "", text: str = "", kind: str = "credential") -> None:
        super().__init__()
        self._name = name
        self._text = text
        self._kind = kind

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label(f"Saved {self._kind}", id="connect-title")
            yield Input(
                value=self._name,
                placeholder=(
                    "Personal BBS login" if self._kind == "credential" else "Check WS1EC mail"
                ),
                id="credential-name",
            )
            yield Label("", id="credential-error")
            yield Label(
                "Text -- one or more lines, sent in order once referenced by a station",
                id="connect-script-title",
            )
            yield TextArea(self._text, id="credential-text", tab_behavior="focus")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="credential-save")
                yield Button("Cancel", id="credential-cancel")

    def on_mount(self) -> None:
        field = self.query_one("#credential-name", Input)
        field.focus()
        field.action_end()

    @on(Button.Pressed, "#credential-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#credential-save")
    @on(Input.Submitted, "#credential-name")
    def _save(self) -> None:
        name = self.query_one("#credential-name", Input).value.strip()
        if not name:
            self.query_one("#credential-error", Label).update(
                f"[red]Name this {self._kind} something -- it is how a station's "
                "Connect entry will find it.[/red]"
            )
            return
        text = self.query_one("#credential-text", TextArea).text
        self.dismiss(Credential(name, text))


_APRS_SERVICE_CHOICES = [
    ("Station (plain APRS message)", "station"),
    ("SMS gateway", "sms"),
    ("Email gateway", "email"),
]

#: The "this contact is nobody in the shipped directory" option. A plain
#: empty string cannot be a `Select` value here (`Select.NULL` is the blank
#: sentinel and assigning `""` alongside `allow_blank=False` is asking for
#: the `Select.BLANK` class of bug AGENTS.md documents), so the no-gateway
#: choice carries a real, distinguishable value that maps to `""` on save.
_NO_GATEWAY = "__none__"


def _gateway_choices() -> list[tuple[str, str]]:
    """Every shipped service, plus "not a gateway" first.

    Built at call time rather than at import so a test can point the
    directory somewhere else, and so a directory that failed to load (a
    missing `package-data` entry in an installed wheel) degrades to just the
    "not a gateway" option instead of raising inside `compose`.
    """
    from ..aprs_services import load_all

    choices = [("Not a gateway service", _NO_GATEWAY)]
    choices.extend((f"{s.name} ({s.callsign})", s.id) for s in load_all())
    return choices


class AprsContactScreen(ModalScreen[Contact | None]):
    """Add or edit one APRS messaging contact (`Config.aprs_contacts`).

    Deliberately small, the same "one screen, no live validation against a
    transport" shape as `CredentialScreen` -- a contact is just a name, an
    addressee, a service, and (for a gateway service) the phone number or
    email address that gateway needs. `service` picks which of the two
    detail-field placeholders/labels apply; changing it just re-renders the
    hint text under the detail field rather than swapping widgets, since a
    plain `Input` covers both shapes.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        name: str = "",
        callsign: str = "",
        service: str = "station",
        detail: str = "",
        notes: str = "",
        sms_gateway: str = "",
        email_gateway: str = "",
        gateway: str = "",
    ) -> None:
        super().__init__()
        self._name = name
        self._callsign = callsign
        self._service = normalize_service(service)
        self._detail = detail
        self._notes = notes
        #: A shipped-directory id, or "" for an ordinary contact. An id that
        #: is no longer in the directory falls back to "not a gateway" rather
        #: than raising -- a `Select` raises if set to a value outside its own
        #: options, which is exactly how a stale theme name crashed Settings
        #: once already (see AGENTS.md sec. 7a).
        self._gateway = gateway.strip()
        #: `Config.aprs_sms_gateway`/`aprs_email_gateway` -- pre-filled into
        #: the callsign field on switching to that service, ONLY while the
        #: field is still empty (see `_service_changed`). Never overwrites a
        #: callsign the operator already typed or that an existing contact
        #: already has.
        self._sms_gateway = sms_gateway
        self._email_gateway = email_gateway

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("APRS contact", id="connect-title")
            yield Input(value=self._name, placeholder="Name / alias", id="aprs-contact-name")
            yield Input(
                value=self._callsign,
                placeholder="Callsign to send to, e.g. K1ABC-9 (or a gateway's callsign)",
                id="aprs-contact-callsign",
            )
            yield Select(
                _APRS_SERVICE_CHOICES,
                id="aprs-contact-service",
                value=self._service,
                allow_blank=False,
            )
            yield Static("", id="aprs-contact-detail-hint")
            yield Input(value=self._detail, placeholder="", id="aprs-contact-detail")
            choices = _gateway_choices()
            known = {value for _, value in choices}
            yield Select(
                choices,
                id="aprs-contact-gateway",
                value=self._gateway if self._gateway in known else _NO_GATEWAY,
                allow_blank=False,
            )
            # The description is the whole point of naming a gateway here --
            # "MPAD" means nothing on its own. Updated on change by
            # `_sync_gateway_hint`, same shape as the detail hint above.
            yield Static("", id="aprs-contact-gateway-hint")
            yield Input(value=self._notes, placeholder="Notes (optional)", id="aprs-contact-notes")
            yield Label("", id="connect-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="aprs-contact-save")
                yield Button("Cancel", id="aprs-contact-cancel")

    def on_mount(self) -> None:
        self._sync_detail_field()
        self._sync_gateway_hint()
        field = self.query_one("#aprs-contact-name", Input)
        field.focus()
        field.action_end()

    @on(Select.Changed, "#aprs-contact-service")
    def _service_changed(self) -> None:
        self._sync_detail_field()
        self._prefill_gateway()

    @on(Select.Changed, "#aprs-contact-gateway")
    def _gateway_changed(self) -> None:
        self._sync_gateway_hint()
        self._prefill_gateway_callsign()

    def _selected_gateway(self) -> str:
        """The chosen directory id, or `""` for none. Also normalises
        `Select.NULL` -- reachable if a future edit sets `allow_blank=True`
        -- so callers never have to compare against a sentinel."""
        value = self.query_one("#aprs-contact-gateway", Select).value
        if value in (_NO_GATEWAY, Select.NULL) or not isinstance(value, str):
            return ""
        return value

    def _sync_gateway_hint(self) -> None:
        """Show what the selected service actually is.

        A contact list full of callsigns like `WLNK-1`, `MPAD` and `CQSRVR`
        is unreadable without this, and the operator is choosing from that
        list right here -- so the one-line summary from the shipped
        directory goes directly under the picker rather than being something
        they have to go and look up.
        """
        from ..aprs_services import lookup

        hint = self.query_one("#aprs-contact-gateway-hint", Static)
        gateway = self._selected_gateway()
        if not gateway:
            hint.update(
                "Not a known gateway -- no command templates will be offered "
                "for this contact."
            )
            return
        service = lookup(gateway)
        if service is None:
            # A saved id from a newer/older kissterm. Say so rather than
            # silently showing nothing, so "why are there no templates?" is
            # answerable from the screen.
            hint.update(f"{gateway}: not in this version's service directory.")
            return
        hint.update(f"{service.summary} -- addressed to {service.callsign}.")

    def _prefill_gateway_callsign(self) -> None:
        """Fill the callsign from the chosen service, while it is still
        empty. Exactly the rule `_prefill_gateway` already applies for the
        SMS/email defaults, and for the same reason: a convenience that
        overwrites something the operator typed is not a convenience."""
        gateway = self._selected_gateway()
        if not gateway:
            return
        from ..aprs_services import lookup

        service = lookup(gateway)
        if service is None:
            return
        callsign_field = self.query_one("#aprs-contact-callsign", Input)
        if not callsign_field.value.strip():
            callsign_field.value = service.callsign

    def _prefill_gateway(self) -> None:
        """Pre-fill the callsign field from `Config.aprs_sms_gateway`/
        `aprs_email_gateway` when switching to that service -- only while
        the field is still empty, so this never overwrites a callsign the
        operator already typed or that an existing contact already has."""
        service = self.query_one("#aprs-contact-service", Select).value
        gateway = self._sms_gateway if service == "sms" else self._email_gateway if service == "email" else ""
        if not gateway:
            return
        callsign_field = self.query_one("#aprs-contact-callsign", Input)
        if not callsign_field.value.strip():
            callsign_field.value = gateway

    def _sync_detail_field(self) -> None:
        service = self.query_one("#aprs-contact-service", Select).value
        detail = self.query_one("#aprs-contact-detail", Input)
        hint = self.query_one("#aprs-contact-detail-hint", Static)
        if service == "sms":
            detail.placeholder = "Phone number the SMS gateway delivers to"
            note = "" if self._sms_gateway else " (no default gateway set -- Settings > APRS messaging)"
            hint.update(f"SMS gateway: the gateway's own callsign goes above.{note}")
        elif service == "email":
            detail.placeholder = "Email address the email gateway delivers to"
            note = "" if self._email_gateway else " (no default gateway set -- Settings > APRS messaging)"
            hint.update(f"Email gateway: the gateway's own callsign goes above.{note}")
        else:
            detail.placeholder = "(not used for a plain station contact)"
            hint.update("")

    @on(Button.Pressed, "#aprs-contact-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#aprs-contact-save")
    @on(Input.Submitted, "#aprs-contact-name")
    def _save(self) -> None:
        name = self.query_one("#aprs-contact-name", Input).value.strip()
        callsign = self.query_one("#aprs-contact-callsign", Input).value.strip()
        service = str(self.query_one("#aprs-contact-service", Select).value)
        detail = self.query_one("#aprs-contact-detail", Input).value.strip()
        notes = self.query_one("#aprs-contact-notes", Input).value.strip()
        problem = validate_contact(name, callsign, service, detail)
        if problem:
            self.query_one("#connect-error", Label).update(f"[red]{problem}[/red]")
            return
        self.dismiss(
            Contact(
                name=name,
                callsign=callsign.upper(),
                service=service,
                detail=detail,
                notes=notes,
                gateway=self._selected_gateway(),
            )
        )


@dataclass(frozen=True)
class _TransportField:
    """One kind-specific input. `key` is exactly the config key it fills --
    the same name `build_transport` forwards to that kind's constructor."""

    key: str
    label: str
    placeholder: str = ""
    default: str = ""
    numeric: bool = False
    password: bool = False


#: Which fields each kind needs, and whether it is a session transport --
#: that decides whether the auto-login section applies at all (`Transport.
#: script`/`credential` are meaningful only to a `SessionTransport`; see
#: that field's docstring in `transport/base.py`). This is each kind's
#: REQUIRED constructor arguments, not its full parameter list -- an
#: advanced knob like serial's `kiss_params` or vara's `bandwidth` stays
#: something only `config.toml.example` documents, same as before this
#: dialog existed. Editing an entry that already has one of those set
#: preserves it rather than dropping it -- see `TransportEntryScreen._save`.
_TRANSPORT_KINDS: dict[str, tuple[bool, tuple[_TransportField, ...]]] = {
    "tcp": (False, (
        _TransportField("host", "Host", "e.g. 192.168.1.50"),
        _TransportField("port", "Port", default="8001", numeric=True),
    )),
    "agwpe": (False, (
        _TransportField("host", "Host", "e.g. 192.168.1.50"),
        _TransportField("port", "Port", default="8000", numeric=True),
    )),
    "serial": (False, (
        _TransportField("device", "Serial device", "e.g. /dev/ttyUSB0 or COM3"),
        _TransportField("baud", "Baud rate", default="9600", numeric=True),
    )),
    "bluetooth": (False, (
        _TransportField("address", "Bluetooth address", "e.g. 00:11:22:33:44:55"),
        _TransportField("channel", "RFCOMM channel", default="1", numeric=True),
    )),
    "ble": (False, (
        _TransportField("address", "Bluetooth address", "e.g. 00:11:22:33:44:55"),
    )),
    "kernel": (True, (
        _TransportField("ax25_port", "AX.25 port", "e.g. radio0, from /etc/ax25/axports"),
        _TransportField("mycall", "Callsign for this port", "e.g. N1ABC-1"),
    )),
    "vara": (True, (
        _TransportField("host", "Host", "e.g. 127.0.0.1"),
        _TransportField("mycall", "Callsign", "e.g. N1ABC-1"),
        _TransportField("cmd_port", "Command port", default="8300", numeric=True),
        _TransportField("data_port", "Data port", default="8301", numeric=True),
    )),
    "varafm": (True, (
        _TransportField("host", "Host", "e.g. 127.0.0.1"),
        _TransportField("mycall", "Callsign", "e.g. N1ABC-1"),
        _TransportField("cmd_port", "Command port", default="8300", numeric=True),
        _TransportField("data_port", "Data port", default="8301", numeric=True),
    )),
    "mercury": (True, (
        _TransportField("host", "Host", "e.g. 127.0.0.1"),
        _TransportField("port", "Port", numeric=True),
        _TransportField("mycall", "Callsign", "e.g. N1ABC-1"),
    )),
    "telnet": (True, (
        _TransportField("host", "Host", "e.g. bbs.example.net"),
        _TransportField("port", "Port", default="23", numeric=True),
    )),
    "ssh": (True, (
        _TransportField("host", "Host", "e.g. ws1ec.mainepacketradio.org"),
        _TransportField("username", "Username", "e.g. packet"),
        _TransportField("password", "Password", password=True),
        _TransportField("port", "Port", default="22", numeric=True),
    )),
}


class TransportEntryScreen(ModalScreen[dict | None]):
    """Add or hand-edit one `[[transports]]` entry (Settings > Transports).

    'Scan for hardware' only finds what a network probe or a serial listing
    can identify by itself -- KISS TNCs and AGWPE engines (see `discovery.
    py`'s own docstring on why a probe must never emit a config it cannot
    complete). It cannot invent a VARA modem's callsign, an SSH login, or a
    Telnet host nobody has typed yet. Before this screen, the only way to
    add one of those was hand-editing `config.toml` -- which is also why the
    Address Book's Connection-type picklist could show a scanned TCP KISS
    TNC but nothing at all for a Telnet/SSH node or a second modem, even
    after the operator had set one up and believed it saved.

    The field set changes with the chosen kind (`_TRANSPORT_KINDS`) because
    each transport's constructor takes different arguments -- there is no
    one form that fits a serial device path and an SSH login. This screen
    only builds the dict; it does not construct or validate the transport
    itself. The caller (`SettingsPane`) does that through `transport.
    build_transport()`, the one place a `Transport` is ever built from
    config, and refuses to save if it raises -- the same rule the first-run
    wizard follows, for the same reason: a config entry that looks right and
    fails at `open()` is worse than catching it here, while the operator is
    still looking at the form that produced it.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        entry: dict | None = None,
        credentials: list[dict] | None = None,
        scripts: list[dict] | None = None,
        existing_names: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._entry = dict(entry) if entry else {}
        self._credentials = credentials or []
        self._scripts = scripts or []
        # Names already in use, for the "pick a different name" check --
        # excluding this entry's OWN current name, or editing without
        # renaming would refuse to save because it collides with itself.
        self._existing_names = tuple(
            n for n in existing_names if n != self._entry.get("name", "")
        )
        self._kind = self._entry.get("kind") or next(iter(_TRANSPORT_KINDS))

    def compose(self) -> ComposeResult:
        from ..transport import KIND_LABELS

        # `VerticalScroll`, not the plain `Vertical` every shorter dialog
        # uses: an `Input` is 3 rows tall by default, and SSH's four fields
        # plus name/kind/error/auto-login add up to more than a typical
        # terminal's height. `#transport-box` caps at 90% of the screen and
        # this scrolls inside that cap instead of pushing Save/Cancel off
        # the bottom, unreachable, the way an un-capped `height: auto` did.
        with Vertical(id="transport-box"):
            yield Label(
                "Edit transport" if self._entry else "New transport",
                id="connect-title",
            )
            with VerticalScroll(id="transport-form"):
                yield Input(
                    value=str(self._entry.get("name", "")),
                    placeholder="Name, e.g. direwolf-local or ws1ec",
                    id="transport-name",
                )
                yield Select(
                    [
                        (label, kind)
                        for kind, label in KIND_LABELS.items()
                        if kind in _TRANSPORT_KINDS
                    ],
                    value=self._kind,
                    id="transport-kind",
                    allow_blank=False,
                )
                yield Label("", id="transport-error")
                with Vertical(id="transport-fields"):
                    yield from self._field_rows(self._kind, self._entry)
                yield Label("Auto-login (optional)", id="transport-script-title")
                yield Static(
                    "Pick a saved credential or script, or type a login "
                    "below. Sent right after this transport connects.",
                    id="transport-script-hint",
                )
                yield Select(
                    [],
                    id="transport-credential",
                    allow_blank=True,
                    prompt="Saved credential",
                )
                yield Select(
                    [],
                    id="transport-script-name",
                    allow_blank=True,
                    prompt="Saved script",
                )
                yield TextArea(
                    str(self._entry.get("script", "")),
                    id="transport-script",
                    tab_behavior="focus",
                    placeholder="One line per prompt, e.g. your callsign then password",
                )
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="transport-save")
                yield Button("Cancel", id="transport-cancel")

    def on_mount(self) -> None:
        self._render_credentials()
        self._render_scripts()
        self._show_script_section(self._kind)
        field = self.query_one("#transport-name", Input)
        field.focus()
        field.action_end()

    # -- kind-specific fields ----------------------------------------------
    def _field_rows(self, kind: str, prefill: dict) -> list[Horizontal]:
        """Built with children passed directly to `Horizontal(...)` rather
        than the `with Horizontal(): yield ...` compose sugar, since this is
        also called from `_kind_changed` to feed `mount_all` -- outside an
        active `compose()` walk, the context-manager form has no compose
        stack to append itself to and raises `IndexError`."""
        _session_tier, fields = _TRANSPORT_KINDS[kind]
        return [
            Horizontal(
                Label(field.label, classes="settings-label"),
                Input(
                    value=str(prefill.get(field.key, field.default)),
                    placeholder=field.placeholder,
                    id=f"transport-field-{field.key}",
                    password=field.password,
                ),
                classes="settings-row",
            )
            for field in fields
        ]

    def _show_script_section(self, kind: str) -> None:
        session_tier, _fields = _TRANSPORT_KINDS[kind]
        for widget_id in (
            "#transport-script-title",
            "#transport-script-hint",
            "#transport-credential",
            "#transport-script-name",
            "#transport-script",
        ):
            self.query_one(widget_id).display = session_tier

    @on(Select.Changed, "#transport-kind")
    async def _kind_changed(self, event: Select.Changed) -> None:
        kind = str(event.value)
        if kind not in _TRANSPORT_KINDS:
            return
        self._kind = kind
        container = self.query_one("#transport-fields", Vertical)
        await container.remove_children()
        # A field from the PREVIOUS kind is not carried over even when the
        # key happens to match (both "tcp" and "vara" have a "host") --
        # switching kind is the operator starting a different transport, not
        # editing this one's host, and half-carried values from a form that
        # no longer matches what is on screen would be worse than a blank.
        await container.mount_all(self._field_rows(kind, {}))
        self._show_script_section(kind)

    # -- credentials / scripts -----------------------------------------------
    def _render_credentials(self) -> None:
        select = self.query_one("#transport-credential", Select)
        select.set_options(
            (name, name) for c in self._credentials if (name := c.get("name"))
        )
        credential = str(self._entry.get("credential", ""))
        if credential:
            select.value = credential
        self._sync_login_controls()

    def _render_scripts(self) -> None:
        select = self.query_one("#transport-script-name", Select)
        select.set_options(
            (name, name) for s in self._scripts if (name := s.get("name"))
        )
        script_name = str(self._entry.get("script_name", ""))
        if script_name:
            select.value = script_name
        self._sync_login_controls()

    @on(Select.Changed, "#transport-credential")
    @on(Select.Changed, "#transport-script-name")
    def _login_source_changed(self) -> None:
        self._sync_login_controls()

    def _sync_login_controls(self) -> None:
        _sync_login_source_controls(
            self.query_one("#transport-credential", Select),
            self.query_one("#transport-script-name", Select),
            self.query_one("#transport-script", TextArea),
        )

    # -- save / cancel -------------------------------------------------------
    @on(Button.Pressed, "#transport-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#transport-save")
    def _save(self) -> None:
        error = self.query_one("#transport-error", Label)
        name = self.query_one("#transport-name", Input).value.strip()
        if not name:
            error.update(
                "[red]Name this transport something -- it is how Settings "
                "and the Address Book will find it.[/red]"
            )
            return
        if name in self._existing_names:
            error.update(f"[red]{name!r} is already in use -- pick another name.[/red]")
            return

        session_tier, fields = _TRANSPORT_KINDS[self._kind]
        values: dict[str, object] = {}
        for field in fields:
            raw = self.query_one(f"#transport-field-{field.key}", Input).value.strip()
            if field.numeric:
                if not raw:
                    error.update(f"[red]{field.label} is required.[/red]")
                    return
                try:
                    values[field.key] = int(raw)
                except ValueError:
                    error.update(f"[red]{field.label} must be a number.[/red]")
                    return
            elif not raw and not field.password:
                error.update(f"[red]{field.label} is required.[/red]")
                return
            else:
                values[field.key] = raw

        # Start from a copy of what was already there, not a blank dict, so
        # an advanced knob this form does not expose (serial's `ports`,
        # vara's `bandwidth`, ...) survives an edit made through this
        # screen instead of being silently dropped -- see the class
        # docstring on why those stay config.toml-only for now.
        entry = dict(self._entry) if self._entry.get("kind") == self._kind else {}
        entry.update(values)
        entry["name"] = name
        entry["kind"] = self._kind
        if session_tier:
            credential_select = self.query_one("#transport-credential", Select)
            credential = str(credential_select.value) if _select_has_value(credential_select) else ""
            script_name_select = self.query_one("#transport-script-name", Select)
            script_name = (
                str(script_name_select.value)
                if not credential and _select_has_value(script_name_select)
                else ""
            )
            script = (
                ""
                if (credential or script_name)
                else self.query_one("#transport-script", TextArea).text
            )
            entry["script"] = script
            entry["credential"] = credential
            entry["script_name"] = script_name
        else:
            entry.pop("script", None)
            entry.pop("credential", None)
            entry.pop("script_name", None)
        self.dismiss(entry)


class CallsignScreen(ModalScreen[str | None]):
    """Change the station callsign without leaving the app.

    This exists because operators change callsign far more often than the
    "set it once at install time" model assumes: a `-1` SSID for a personal
    mailbox, a different SSID for portable or emergency-net operation, a club
    call for an event, a fresh SSID after someone else claimed the one you were
    using on the same channel. Before this dialog the only route was
    `kissterm --setup`, which re-runs the whole first-run wizard -- including a
    multi-second LAN sweep and transport re-selection -- to change one string.

    Validation is `AX25Address.parse`, the same function the wire encoder uses,
    so anything this dialog accepts is guaranteed encodable into an address
    field. Rejecting here is much better than discovering it at SABM time.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, current: str = "") -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Station callsign", id="connect-title")
            yield Input(
                value=self._current,
                placeholder="N1ABC-1",
                id="callsign-value",
            )
            yield Label(
                "Saved to config.toml and used for the next connection.",
                id="callsign-hint",
            )
            yield Label("", id="callsign-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="callsign-save")
                yield Button("Cancel", id="callsign-cancel")

    def on_mount(self) -> None:
        field = self.query_one("#callsign-value", Input)
        field.focus()
        # Cursor to the end, so backspacing an SSID off the current call is
        # one keystroke away -- the most common edit by far is N1ABC-1 to
        # N1ABC-9, not typing a whole new callsign.
        field.action_end()

    @on(Button.Pressed, "#callsign-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#callsign-save")
    @on(Input.Submitted, "#callsign-value")
    def _save(self) -> None:
        text = self.query_one("#callsign-value", Input).value.strip().upper()
        if not text:
            return
        from ..ax25 import AX25Address

        try:
            AX25Address.parse(text)
        except Exception as exc:
            self.query_one("#callsign-error", Label).update(f"[red]{exc}[/red]")
            return
        self.dismiss(text)


class AprsCannedMessageScreen(ModalScreen["CannedMessage | None"]):
    """Add or edit one of the operator's own saved APRS messages.

    Deliberately tiny, the same shape as `CredentialScreen`: a name, the
    text, and which service it belongs to. The scope `Select` is the whole
    reason this is not just a flat list -- see `CannedMessage.gateway`.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, name: str = "", text: str = "", gateway: str = "") -> None:
        super().__init__()
        self._name = name
        self._text = text
        self._gateway = gateway.strip()

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Saved message", id="connect-title")
            yield Input(value=self._name, placeholder="Name, e.g. Net check-in", id="canned-name")
            yield Input(value=self._text, placeholder="Message text", id="canned-text")
            choices = _gateway_choices()
            known = {value for _, value in choices}
            # Reuses the gateway list, with the "not a gateway" entry
            # relabelled: here it means "offer this everywhere", which is a
            # different idea from a contact's "this is not a gateway" even
            # though both store "".
            choices = [("Show for every recipient", _NO_GATEWAY)] + choices[1:]
            yield Select(
                choices,
                id="canned-gateway",
                value=self._gateway if self._gateway in known else _NO_GATEWAY,
                allow_blank=False,
            )
            yield Label("", id="connect-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="canned-save")
                yield Button("Cancel", id="canned-cancel")

    def on_mount(self) -> None:
        field = self.query_one("#canned-name", Input)
        field.focus()
        field.action_end()

    @on(Button.Pressed, "#canned-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#canned-save")
    @on(Input.Submitted, "#canned-text")
    def _save(self) -> None:
        name = self.query_one("#canned-name", Input).value.strip()
        text = self.query_one("#canned-text", Input).value
        problem = validate_canned_message(name, text)
        if problem:
            self.query_one("#connect-error", Label).update(f"[red]{problem}[/red]")
            return
        gateway = self.query_one("#canned-gateway", Select).value
        if gateway in (_NO_GATEWAY, Select.NULL) or not isinstance(gateway, str):
            gateway = ""
        self.dismiss(CannedMessage(name=name, text=text, gateway=gateway))


class AprsServiceScreen(ModalScreen[str | None]):
    """What to say to an APRS gateway: shipped commands plus saved messages.

    The APRS counterpart to `CommandReferenceScreen` above, and it exists for
    the same reason: a gateway's command set is knowable in advance, and
    asking the gateway itself costs channel time every operator would have to
    spend separately. See `kissterm/aprs_services/directory.py`.

    **Choosing an entry fills the compose box and does not send it.** That is
    not a new rule invented here, it is AGENTS.md's existing one -- "a
    completion that transmits on its own is a defect on a shared channel" --
    and it is what makes a seventeen-service template library safe rather
    than alarming. `AprsPane` still routes the actual transmission through
    `KissTermApp._send_aprs_message` and the master transmit gate, exactly as
    it does for a hand-typed message.

    The screen shows the service's own description and source URL, not just
    its commands. An operator looking at `MPAD` needs to know what it is
    before they need to know its verbs, and the `confidence` column is the
    honest answer to "can I trust this line enough to spend airtime on it?"
    -- several shipped entries are `recalled` rather than `documented`.
    """

    #: `show=True` and a `Footer` in `compose`: the keys belong in the
    #: context-aware bar along the bottom, the same place every other
    #: shortcut in this app is advertised, not in a line of hint text
    #: wedged under the buttons. A modal gets its own Footer because the
    #: app's is on the base screen underneath and does not track a screen
    #: pushed over it.
    BINDINGS = [
        Binding("enter", "select_row", "Use"),
        Binding("insert", "new_message", "Save a message"),
        Binding("f2", "edit_message", "Edit"),
        Binding("delete", "forget_message", "Forget"),
        Binding("escape", "dismiss(None)", "Close"),
    ]

    def __init__(self, service, saved: list, addressee: str = "") -> None:
        """`service` is an `aprs_services.Service` or None (an addressee that
        is nobody in the directory -- the operator's own saved messages are
        still worth offering). `saved` is `CannedMessage`s already scoped by
        `canned_messages_for`."""
        super().__init__()
        self._service = service
        self._saved = list(saved)
        self._addressee = addressee
        #: Row key -> the text to insert. Built in `_populate` so a filtered
        #: table never hands back a stale row's text.
        self._rows: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        from textual.widgets import DataTable

        with Vertical(id="ref-box"):
            yield Label(self._title(), id="ref-title")
            yield Static(self._note(), id="ref-note")
            yield Input(placeholder="search", id="aprs-service-search")
            yield DataTable(id="aprs-service-table", cursor_type="row", zebra_stripes=True)
            # The ONE thing that is not a keyboard shortcut and so does not
            # belong in the Footer: what selecting actually does. An
            # operator about to put a command on a shared channel should not
            # have to find out by trying it.
            yield Static(
                "Selecting puts the text in the message box. Nothing is sent "
                "until you press Enter there or click Send.",
                id="ref-help",
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Use", variant="primary", id="aprs-service-use")
                yield Button("Save a message", id="aprs-service-new")
                yield Button("Close", id="aprs-service-close")
        yield Footer()

    def _title(self) -> str:
        if self._service is None:
            target = self._addressee or "this recipient"
            return f"Messages -- {target}"
        return f"{self._service.name} -- {self._service.callsign}"

    def _note(self) -> str:
        """What this service is, and how much to trust the list.

        Mirrors `CommandReferenceScreen._note`, including its "this reference
        is unverified" warning -- the same question ("should I spend airtime
        on this line?") with the same stakes.
        """
        if self._service is None:
            return (
                "Not one of the gateway services kissterm ships, so there are no "
                "command templates for it -- only your own saved messages. Set a "
                "gateway on the contact (F2 in the contacts list) if it is one."
            )
        parts = [self._service.note.replace("\n", " ").strip()]
        if self._service.region:
            parts.append(f"Coverage: {self._service.region}.")
        if any(c.confidence == "recalled" for c in self._service.commands):
            parts.append(
                "Some lines below are marked 'recalled' -- their exact arguments "
                "were not confirmed against the source. Check one before spending "
                "airtime on it."
            )
        # The source is shown, not just cited in a docstring: an operator who
        # wants the authoritative answer should be one URL away, and a
        # directory entry with a date is honest about being a snapshot.
        checked = f" (checked {self._service.checked})" if self._service.checked else ""
        parts.append(f"Source: {self._service.source}{checked}")
        return " ".join(p for p in parts if p)

    def on_mount(self) -> None:
        from textual.widgets import DataTable

        table = self.query_one("#aprs-service-table", DataTable)
        table.add_columns("From", "Command", "Send", "What it does", "Source")
        self._populate("")
        self.query_one("#aprs-service-search", Input).focus()

    def _populate(self, needle: str) -> None:
        from textual.widgets import DataTable

        table = self.query_one("#aprs-service-table", DataTable)
        table.clear()
        self._rows = {}
        needle_lower = needle.strip().lower()

        # Saved messages first: they are the operator's own words, and
        # someone who took the trouble to save a line usually wants it more
        # often than any one shipped command.
        for index, message in enumerate(self._saved):
            if needle_lower and needle_lower not in f"{message.name} {message.text}".lower():
                continue
            key = f"saved:{index}"
            scope = "yours" if message.gateway else "yours (all)"
            table.add_row(scope, message.name, message.text, "", "saved", key=key)
            self._rows[key] = message.text

        if self._service is not None:
            for command in self._service.find(needle):
                key = f"cmd:{command.name}"
                table.add_row(
                    self._service.callsign,
                    command.name,
                    command.insert_text,
                    command.summary,
                    command.confidence,
                    key=key,
                )
                self._rows[key] = command.insert_text

    @on(Input.Changed, "#aprs-service-search")
    def _search(self, event: Input.Changed) -> None:
        self._populate(event.value)

    @on(Button.Pressed, "#aprs-service-close")
    def _close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#aprs-service-use")
    def _use_pressed(self) -> None:
        self.action_select_row()

    def action_select_row(self) -> None:
        """Enter, and the Use button. Hands back the row under the cursor.

        Separate from `on_data_table_row_selected` because the cursor can be
        on a row without the table having raised a selection event -- the
        operator arrowed to it. Both paths end at `dismiss`, which is the
        only thing this screen does.
        """
        from textual.widgets import DataTable

        table = self.query_one("#aprs-service-table", DataTable)
        if table.row_count == 0 or table.cursor_coordinate is None:
            return
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return
        text = self._rows.get(str(row_key.value or ""))
        if text is not None:
            self.dismiss(text)

    def on_data_table_row_selected(self, event) -> None:
        """Hand the text back for the caller to put in the compose box."""
        key = str(event.row_key.value or "")
        text = self._rows.get(key)
        if text is not None:
            self.dismiss(text)

    # -- the operator's own saved messages -----------------------------------
    def _selected_saved_index(self) -> int | None:
        """The `self._saved` index under the cursor, or None if the cursor is
        on a shipped command (which the operator does not own and cannot
        edit)."""
        from textual.widgets import DataTable

        table = self.query_one("#aprs-service-table", DataTable)
        if table.row_count == 0 or table.cursor_coordinate is None:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        key = str(row_key.value or "")
        if not key.startswith("saved:"):
            return None
        return int(key.split(":", 1)[1])

    def action_new_message(self) -> None:
        self._edit_message(None)

    @on(Button.Pressed, "#aprs-service-new")
    def _new_pressed(self) -> None:
        self.action_new_message()

    def action_edit_message(self) -> None:
        index = self._selected_saved_index()
        if index is None:
            self.app.notify(
                "Select one of your own saved messages to edit -- the shipped "
                "commands come from kissterm and cannot be changed here.",
                severity="warning",
            )
            return
        self._edit_message(index)

    def action_forget_message(self) -> None:
        index = self._selected_saved_index()
        if index is None:
            return
        message = self._saved[index]
        self._apply(lambda raw: _forget_canned(raw, message))
        self._saved.pop(index)
        self._populate(self.query_one("#aprs-service-search", Input).value)

    @work
    async def _edit_message(self, index: int | None) -> None:
        existing = self._saved[index] if index is not None else None
        default_gateway = self._service.id if self._service is not None else ""
        result = await self.app.push_screen_wait(
            AprsCannedMessageScreen(
                name=existing.name if existing else "",
                text=existing.text if existing else "",
                gateway=existing.gateway if existing else default_gateway,
            )
        )
        if result is None:
            return
        old = existing
        self._apply(lambda raw: _replace_canned(raw, old, result))
        if index is not None:
            self._saved[index] = result
        else:
            self._saved.insert(0, result)
        self._populate(self.query_one("#aprs-service-search", Input).value)

    def _apply(self, change) -> None:
        """Mutate `Config.aprs_templates` in place and persist.

        In place because `Config` is handed around by reference everywhere in
        this app -- rebinding the attribute to a new list would leave any
        other holder looking at the old one, the same reason
        `AprsPane._forget_selected` pops from the live list rather than
        rebuilding it.
        """
        raw = self.app.config.aprs_templates  # type: ignore[attr-defined]
        raw[:] = change(raw)
        self.app._save_config()  # type: ignore[attr-defined]


def _replace_canned(raw: list[dict], old, new) -> list[dict]:
    """`raw` with `old` swapped for `new`, or `new` appended if `old` is None.

    Matched on the stored dict rather than on an index because the picker
    shows a FILTERED, re-ordered view (scoped before global, saved before
    shipped) -- a position in that view is not a position in the config list,
    and using one as the other is how an edit silently rewrites the wrong
    entry.
    """
    out = list(raw)
    if old is not None:
        target = old.to_dict()
        for i, entry in enumerate(out):
            if CannedMessage.from_dict(entry) == old or entry == target:
                out[i] = new.to_dict()
                return out
    out.append(new.to_dict())
    return out


def _forget_canned(raw: list[dict], message) -> list[dict]:
    """`raw` without the first entry equal to `message`. Same
    match-on-content reasoning as `_replace_canned`."""
    out = list(raw)
    for i, entry in enumerate(out):
        if CannedMessage.from_dict(entry) == message:
            del out[i]
            return out
    return out


class HarvestConfirmScreen(ModalScreen[str | None]):
    """Confirm spending airtime on a node's own command list, once.

    Same reasoning as `RadioReminderScreen`: a cost the operator only learns
    about after paying it is not a warning, so this blocks
    `KissTermApp.harvest_commands` until the operator explicitly says to
    proceed. The estimate is a RANGE, not a single number -- kissterm has no
    way to know how verbose this particular node's `?` reply will be before
    asking it, so showing a false-precision figure would be worse than
    showing the honest range from `docs/ROADMAP.md`'s own airtime table.

    That range prices wire time only. A real report against WS1EC-15/CCEMA
    needed three T1 retry/REJ recovery cycles and ~18.8 seconds before a
    two-line reply even started arriving -- legitimate lossy-link behaviour
    `describe_airtime` cannot see coming, which is why the copy below also
    says a marginal link can run past the estimate.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, peer: str) -> None:
        super().__init__()
        self._peer = peer

    def compose(self) -> ComposeResult:
        from ..nodes.reference import describe_airtime

        low = describe_airtime(512)
        high = describe_airtime(8192)
        with Vertical(id="connect-box"):
            yield Label(f"Ask {self._peer} for its command list?", id="connect-title")
            yield Static(
                f"This is real airtime on a shared channel -- anywhere from "
                f"{low} to {high} depending on how verbose the node is, "
                "during which nobody else on the frequency can transmit. "
                "A marginal or busy link can take longer than that estimate; "
                "kissterm keeps listening either way and stops as soon as "
                "the reply looks finished, not on a fixed timer. The result "
                "is cached forever, so this is asked at most once per node.",
                id="reminder-detail",
            )
            yield Select(
                [
                    ("Node commands", "node"),
                    ("BBS commands", "bbs"),
                    ("Other application commands", "application"),
                ],
                value="node",
                allow_blank=False,
                id="harvest-context",
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Ask", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        self.query_one("#connect-go", Button).focus()

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    def _go(self) -> None:
        self.dismiss(str(self.query_one("#harvest-context", Select).value))


class CommandReferenceScreen(ModalScreen[str | None]):
    """The shipped command reference for the node we are talking to, plus a
    glossary of packet terminology in the same pane.

    Exists because asking the node itself is expensive: at 1200 baud
    half-duplex, a couple of kilobytes of help text is roughly twenty seconds
    during which nobody else on the frequency can transmit, and eight kilobytes
    is over a minute. A reference that ships with the app costs nothing and is
    available before the first byte is exchanged.

    Selecting a command **fills the input line and does not send it**. The
    operator still commits deliberately -- see `TerminalPane.send_line`, which
    is the only path to the air. Selecting a glossary term does nothing --
    there is nothing to send a definition to -- so `on_data_table_row_
    selected` only dismisses while in Commands mode.

    Commands and glossary share one search box and one table
    (`docs/ROADMAP.md`'s own wording: a glossary should be "searchable in the
    same pane as commands") rather than a second binding or a second modal --
    switching modes just repaints the same table with different columns.

    **"Learn from node"** (only shown when `can_harvest` -- an actual
    connected link exists to ask) is the opt-in harvesting AGENTS.md
    describes: confirmed via `HarvestConfirmScreen` first, sent and cached
    by `KissTermApp.harvest_commands`, never by this screen directly.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(
        self,
        reference,
        detected: str = "",
        *,
        session_key: str = "",
        can_harvest: bool = False,
        peer: str = "",
    ) -> None:
        super().__init__()
        self._reference = reference
        self._detected = detected
        self._mode = "commands"
        self._session_key = session_key
        self._can_harvest = can_harvest
        self._peer = peer
        # A command can be valid in both a node and its BBS application.
        # DataTable row keys must stay unique, while selecting either row
        # still needs to return only the text the operator wants to type.
        self._command_row_values: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        from textual.widgets import DataTable, Static

        with Vertical(id="ref-box"):
            yield Label(self._title(), id="ref-title")
            yield Static(self._note(), id="ref-note")
            yield Tabs(
                Tab("Commands", id="ref-mode-commands"),
                Tab("Glossary", id="ref-mode-glossary"),
                id="ref-mode-tabs",
            )
            yield Input(placeholder="search commands", id="ref-search")
            yield DataTable(id="ref-table", cursor_type="row", zebra_stripes=True)
            # DataTable deliberately keeps every cell to one physical line.
            # That is useful for commands, whose rows can be selected, but a
            # glossary definition is prose and must remain readable in a
            # normal-width terminal.  The glossary view therefore uses the
            # same wrapping scrollback primitive as the operational panes.
            yield WrapLog(
                id="ref-glossary",
                wrap=True,
                markup=False,
                highlight=False,
                auto_scroll=False,
            )
            yield Static("", id="ref-harvest-status")
            yield WrapLog(
                id="ref-harvest-output",
                wrap=True,
                markup=False,
                highlight=False,
                auto_scroll=False,
            )
            yield Static(
                "Enter puts a command in the input line. It is not sent until "
                "you press Enter there or click Send.",
                id="ref-help",
            )
            with Horizontal(id="connect-buttons"):
                if self._can_harvest:
                    yield Button("Learn from node", id="ref-harvest")
                    yield Button("Show captured reply", id="ref-show-harvest")
                yield Button("Close", id="ref-close")

    def _title(self) -> str:
        if self._mode == "glossary":
            return "Glossary -- packet radio terms"
        family = self._reference.family
        return f"Commands -- {family.name}" if family else "Commands -- unknown node"

    def _note(self) -> str:
        if self._mode == "glossary":
            return "Aimed at an operator who knows radio but not packet."
        family = self._reference.family
        if family is None:
            return (
                "The node has not been identified from its banner or prompt, so "
                "this list may not apply. Nothing has been asked of the node -- "
                "that would cost airtime."
            )
        parts = [family.note.replace("\n", " ").strip()]
        if family.confidence == "recalled":
            parts.append(
                "This reference is unverified; check a command before spending "
                "airtime on it."
            )
        return " ".join(p for p in parts if p)

    def on_mount(self) -> None:
        self._render_columns()
        self._populate("")
        self.query_one("#ref-search", Input).focus()

    def _render_columns(self) -> None:
        from textual.widgets import DataTable

        table = self.query_one("#ref-table", DataTable)
        table.clear(columns=True)
        if self._mode == "glossary":
            table.display = False
            self.query_one("#ref-glossary", WrapLog).display = True
        else:
            table.display = True
            self.query_one("#ref-glossary", WrapLog).display = False
            table.add_columns("Command", "Usage", "What it does", "Context", "Source")

    @on(Tabs.TabActivated, "#ref-mode-tabs")
    def _mode_tab_activated(self, event: Tabs.TabActivated) -> None:
        event.stop()
        self._switch_mode(
            "glossary" if event.tab.id == "ref-mode-glossary" else "commands"
        )

    def _switch_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self.query_one("#ref-title", Label).update(self._title())
        self.query_one("#ref-note", Static).update(self._note())
        search = self.query_one("#ref-search", Input)
        search.placeholder = "search glossary" if mode == "glossary" else "search commands"
        # A filter belongs to the view where it was typed. Carrying it across
        # silently makes an unrelated view look empty.
        search.value = ""
        self._render_columns()
        self._populate("")
        if self._can_harvest:
            # Nothing to harvest from a glossary -- hide the button rather
            # than leave it sitting there doing nothing while browsing terms.
            self.query_one("#ref-harvest", Button).display = mode != "glossary"

    def _populate(self, needle: str) -> None:
        if self._mode == "glossary":
            self._populate_glossary(needle)
        else:
            self._populate_commands(needle)

    def _populate_glossary(self, needle: str) -> None:
        from .. import glossary
        from rich.table import Column, Table

        log = self.query_one("#ref-glossary", WrapLog)
        log.clear()
        table = Table(
            Column("Term", style="bold", no_wrap=True),
            Column("Definition", ratio=1, overflow="fold"),
            expand=True,
            header_style="bold",
            show_edge=False,
            pad_edge=False,
        )
        for term in glossary.search(needle):
            table.add_row(term.name, term.definition)
        log.write(table, expand=True)

    def _populate_commands(self, needle: str) -> None:
        from textual.widgets import DataTable

        table = self.query_one("#ref-table", DataTable)
        table.clear()
        self._command_row_values.clear()
        for index, command in enumerate(self._reference.find(needle)):
            names = command.name
            if command.aliases:
                names += " / " + " / ".join(command.aliases)
            row_key = f"{index}:{command.context}:{command.name}"
            self._command_row_values[row_key] = command.name
            table.add_row(
                names,
                command.usage or command.name,
                command.summary,
                {"node": "Node", "bbs": "BBS", "application": "Application"}.get(
                    command.context, command.context.title()
                ),
                # Say where each line came from. A reference that silently
                # mixes documented fact with half-remembered syntax is worse
                # than none: the operator types it, at 1200 baud, and finds out.
                command.confidence,
                key=row_key,
            )

    @on(Input.Changed, "#ref-search")
    def _search(self, event: Input.Changed) -> None:
        self._populate(event.value)

    @on(Button.Pressed, "#ref-close")
    def _close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#ref-harvest")
    async def _harvest(self) -> None:
        """Confirm the airtime cost, then ask `KissTermApp.harvest_commands`
        to do the actual send-and-capture -- this screen never touches the
        link itself, same separation `_edit_message` above uses for pushing
        a nested modal from within one already open.

        `self._reference` and the app's session both point at the SAME
        `CommandReference` instance (`KissTermApp.reference`'s property
        getter returns it directly, not a copy), so once `harvest_commands`
        sets `.learned` on it, repainting this table with the search box's
        current text is enough to show the result -- no extra plumbing back
        from the app needed.
        """
        context = await self.app.push_screen_wait(HarvestConfirmScreen(self._peer))
        if not context:
            return
        harvest = self.query_one("#ref-harvest", Button)
        harvest.label = "Asking node..."
        harvest.disabled = True
        names = await self.app.harvest_commands(  # type: ignore[attr-defined]
            self._session_key, context=context
        )
        text = self.app.last_harvest_text(self._session_key)  # type: ignore[attr-defined]
        status = self.query_one("#ref-harvest-status", Static)
        status.update(
            f"Captured {len(text)} byte(s); learned {len(names)} command(s)."
            if text
            else "No reply was captured from the node."
        )
        status.display = True
        show = self.query_one("#ref-show-harvest", Button)
        show.display = True
        harvest.label = "Learn from node"
        harvest.disabled = False
        self._populate(self.query_one("#ref-search", Input).value)

    @on(Button.Pressed, "#ref-show-harvest")
    def _toggle_harvest_output(self) -> None:
        """Reveal the exact sanitized reply behind the parsed command list.

        Parsing a node's menu necessarily throws information away (headings,
        errors, local application entries), so an operator needs to inspect
        the capture without leaving the reference screen. This is a view
        toggle only; it cannot ask the node again or transmit anything.
        """
        output = self.query_one("#ref-harvest-output", WrapLog)
        show = self.query_one("#ref-show-harvest", Button)
        output.display = not output.display
        if output.display:
            show.label = "Hide captured reply"
            # A just-revealed WrapLog has no laid-out width until Textual has
            # completed its visibility/layout pass. Writing now makes
            # RichLog render at zero width and lose the reply; a brief timer
            # puts the write after that pass, rather than relying on whether
            # this button press happened to coincide with a refresh.
            self.set_timer(0.05, self._write_harvest_output)
        else:
            show.label = "Show captured reply"

    def _write_harvest_output(self) -> None:
        """Write the capture only after its revealed log has real geometry."""
        output = self.query_one("#ref-harvest-output", WrapLog)
        if not output.display:
            return
        output.clear()
        text = self.app.last_harvest_text(self._session_key)  # type: ignore[attr-defined]
        output.write(text or "No reply was captured.")

    def on_data_table_row_selected(self, event) -> None:
        """Hand the command back to the app, which fills the input line.
        Glossary mode has nothing to hand back -- a definition is not
        something `TerminalPane.send_line` could ever do anything with."""
        if self._mode == "glossary":
            return
        self.dismiss(self._command_row_values.get(str(event.row_key.value), ""))


def _human_size(n: int) -> str:
    """Bytes, KB or MB -- whichever reads best. Transcripts are plain text,
    so anything past a few hundred KB is unusual enough to be worth noticing
    rather than rounding away."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class TranscriptsScreen(ModalScreen[None]):
    """Past session transcripts: find one, read it, copy it out.

    `kissterm/session_log.py` writes one plain-text file per connected
    session, and did so long before this screen existed -- what was missing
    was a way to find one again from inside the app. `kissterm/transcripts.py`
    does the actual listing/searching/copying; this screen is display and
    wiring only.

    Read-only over the transcripts themselves: nothing here can delete or
    edit one, only copy it elsewhere. That mirrors the terminal pane's own
    read-only scrollback -- a session record is something to consult, not
    something a stray keypress in a list screen should be able to alter.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, directory) -> None:
        super().__init__()
        self._directory = directory
        self._rows: list = []
        self._current = None

    def compose(self) -> ComposeResult:
        from textual.widgets import DataTable, RichLog

        with Vertical(id="transcripts-box"):
            yield Label("Session Transcripts", id="transcripts-title")
            yield Static(
                f"Reading from {self._directory}", id="transcripts-note"
            )
            yield Input(
                placeholder="search by callsign or by what was said",
                id="transcripts-search",
            )
            with Horizontal(id="transcripts-body"):
                yield DataTable(
                    id="transcripts-table", cursor_type="row", zebra_stripes=True
                )
                yield RichLog(
                    id="transcripts-preview", wrap=True, markup=False, highlight=False
                )
            with Horizontal(id="transcripts-export-row"):
                yield Input(placeholder="export to path...", id="transcripts-dest")
                yield Button("Export", id="transcripts-export")
            with Horizontal(id="connect-buttons"):
                yield Button("Close", id="transcripts-close")

    def on_mount(self) -> None:
        from textual.widgets import DataTable

        table = self.query_one("#transcripts-table", DataTable)
        table.add_columns("Started", "Peer", "Mycall", "Size")
        self._populate("")
        self.query_one("#transcripts-search", Input).focus()

    def _populate(self, needle: str) -> None:
        from textual.widgets import DataTable

        from ..transcripts import search_transcripts

        table = self.query_one("#transcripts-table", DataTable)
        table.clear()
        self._rows = search_transcripts(self._directory, needle)
        for info in self._rows:
            table.add_row(
                info.started or "?",
                info.peer or "?",
                info.mycall or "?",
                _human_size(info.size),
                key=str(info.path),
            )

    @on(Input.Changed, "#transcripts-search")
    def _search(self, event: Input.Changed) -> None:
        self._populate(event.value)

    def _row_for(self, path_str: str):
        return next((r for r in self._rows if str(r.path) == path_str), None)

    def _show_preview(self, path_str: str | None) -> None:
        from pathlib import Path

        from textual.widgets import RichLog

        preview = self.query_one("#transcripts-preview", RichLog)
        preview.clear()
        self._current = self._row_for(path_str) if path_str else None
        if self._current is None:
            return
        try:
            # Transcripts are written by `SessionLog`, which only ever
            # receives already-sanitized text (see that module's docstring)
            # -- safe to display raw, the same trust boundary `TerminalPane.
            # log` relies on for locally-generated text.
            text = self._current.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            preview.write(f"(could not read this file: {exc})")
            return
        preview.write(text)
        dest = self.query_one("#transcripts-dest", Input)
        if not dest.value:
            dest.value = str(Path.home() / self._current.path.name)

    def on_data_table_row_highlighted(self, event) -> None:
        self._show_preview(str(event.row_key.value) if event.row_key else None)

    @on(Button.Pressed, "#transcripts-export")
    def _export(self) -> None:
        from pathlib import Path

        from ..transcripts import export_transcript

        if self._current is None:
            self.app.notify("Select a transcript first.", severity="warning")
            return
        dest = self.query_one("#transcripts-dest", Input).value.strip()
        if not dest:
            self.app.notify("Enter a destination path.", severity="warning")
            return
        try:
            export_transcript(self._current, Path(dest).expanduser())
        except OSError as exc:
            self.app.notify(f"Export failed: {exc}", severity="error")
            return
        self.app.notify(f"Exported to {dest}")

    @on(Button.Pressed, "#transcripts-close")
    def _close(self) -> None:
        self.dismiss(None)
