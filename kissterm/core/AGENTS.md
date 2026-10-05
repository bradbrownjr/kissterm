# kissterm/core — local contract

> **Nothing here imports Textual or `kissterm.ui`.**
> `tests/unit/test_core_boundary.py` fails if anything does, directly or
> through another module. The core is what every front end drives: the
> terminal UI today, a WebSocket API for phone, desktop and browser clients
> next (ROADMAP P7a).

The station with no user interface. Flows move here from `ui/app.py` one
milestone at a time, each with no change the operator can see and the
same tests passing unchanged.

## File map

| File | What it owns |
|---|---|
| `service.py` | `Core`: station, session transport, transmit gate, transport lifecycle (open, switch, rebind, subscriber wiring). `build_station`, `MAX_LINKS`. |
| `operator.py` | The `Operator` port: `notice(Notice)` and `await ask(Question)`. `NullOperator` declines everything. |
| `events.py` | Domain events and the `EventBus` (sequence-numbered, synchronous). |
| `connect.py` | `Connector` (`core.connector`): gate arming, the radio reminder, the dial and its failure wording, Internet contacts, the session tier, hop chain, auto-login, disconnect/cancel, reconnect. `ConnectRequest`, `session_key`. `SessionView` is what a client provides: which session is on screen, room for another, putting one in front of the operator. |
| `sessions.py` | `Sessions` (`core.sessions`): every live session (`LiveSession`) -- binding, transcripts and records, `send_line` (the one path for a typed line), passive node identification and application tracking, the hop watch, harvest (opt-in `?`, cached), the reply watch, incoming calls and stray polls. `data_interceptors`/`sent_hooks` let the terminal UI's file transfers read session bytes until they move here. |
| `questions.py` | The typed questions: `RadioReminder`, `TrustHostKey`. |
| `hops.py` | `HopConfirmation` and `HOP_TIMEOUT`: the one definition of "the hop came up". |
| `links.py` | `SessionLinkAdapter`: a session-tier `Session` in `AX25Link`'s shape. |

## The rules

1. **Talk to the operator only through `Operator`.** A flow that needs to
   say something calls `self.operator.notice(...)`; one that needs a
   decision awaits `self.operator.ask(SomeQuestion(...))`. Never a widget,
   never a toast, never screen wording such as a key name. **Known gap:**
   notices moved from the terminal UI kept their words so nothing changed
   on screen ("Ctrl+T turns it back off", "the Monitor tab (F8)",
   "Settings (F9) > Radio > Test" in `connect.py`; "(Ctrl+T)", "the
   Monitor tab (F8)" and `tx.DISABLED_MESSAGE` in `sessions.py`). They become
   client-neutral before any other client exists (the WebSocket server);
   do not add more.
2. **A question is data**: a frozen dataclass subclassing `Question`, with
   its answer type in the docstring. Each client draws it its own way; the
   terminal UI maps it to a screen in `ui/operator.py`'s `SCREENS`.
3. **`ask()` returning None is cancel**, and a cancelled flow transmits
   nothing.
4. **Only the core arms the transmit gate**, after a confirming answer to a
   question it asked. No client command arms it (AGENTS.md "The transmit
   gate").
5. **Events say what happened, not how it looks.** No colours, no
   status-bar text. A client formats.
6. **A session is the core's; a tab is the client's.** Bind, record and
   send through `core.sessions`; a client learns of it from events
   (`SessionOpened`, `SessionData` -- raw bytes, the client filters them --
   `LineSent`, `SessionStateChanged`, `SessionUpdated`) and never keeps
   its own copy of session state.
7. **Register subscribers before `attach_station()`**, and never subscribe
   to a transport directly: the core moves `frame_subscribers`,
   `sent_subscribers`, `incoming_subscribers` and `stray_poll_subscribers`
   when the transport changes.
8. **One loop, no threads.** Call `attach_station()` from the loop the
   station runs on; it captures that context for frame callbacks.
