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
| `service.py` | `Core`: station, session transport, transmit gate, transport lifecycle (open, switch, rebind, subscriber wiring), the Address Book and heard list, `save_config`, `set_activity`, `ask_callsign`. `build_station`, `MAX_LINKS`. |
| `operator.py` | The `Operator` port: `notice(Notice)` and `await ask(Question)`. `NullOperator` declines everything. |
| `events.py` | Domain events and the `EventBus` (sequence-numbered, synchronous). |
| `connect.py` | `Connector` (`core.connector`): gate arming, the radio reminder, the dial and its failure wording, Internet contacts, the session tier, hop chain, auto-login, disconnect/cancel, reconnect. `ConnectRequest`, `session_key`. `SessionView` is what a client provides: which session is on screen, room for another, putting one in front of the operator. |
| `sessions.py` | `Sessions` (`core.sessions`): every live session (`LiveSession`) -- binding, transcripts and records, `send_line` (the one path for a typed line), passive node identification and application tracking, the hop watch, harvest (opt-in `?`, cached), the reply watch, incoming calls and stray polls. `data_interceptors`/`sent_hooks` let the terminal UI's file transfers read session bytes until they move here. |
| `aprs.py` | `Aprs` (`core.aprs`): the APRS decode on the frame fan-out (`on_frame`, registered after the heard list's own subscriber), the conversation store, auto-ack, `compose` (a typed message: arms, sends, tracks), the ack-and-retry queue and its loop, objects, position-now, both beacons (BTEXT and APRS, never conflated), GPS, the receive-only APRS-IS debug watch. Events: `AprsMessage`, `AprsAcked`, `AprsPacketHeard`, `AprsBulletinHeard`, `AprsRetried`, `Alert`. |
| `mail.py` | `Mail` (`core.mail`): the message store and bulletin subscriptions, Send/Receive (G and I) for the Home BBS and Winlink, bulletins, files; every setup question asked before the first dial; outcome notices; `MailChanged`. |
| `channel.py` | `Channel` (`core.channel`): first on the frame fan-out -- the heard list, NET/ROM claims (`known_nodes`), mail-for beacons, watched callsigns; every frame each way as `FrameSeen` for a client's monitor. |
| `settings_schema.py` | Every editable setting, declaratively (moved from `ui/`); `register_choices` lets a client supply a list that is its own (the theme). |
| `settings.py` | `Settings` (`core.settings`): `save(draft)` -- all or nothing -- and applying it to the station and what runs on its own. |
| `transfers.py` | `Transfers` (`core.transfers`): YAPP/AutoBIN on a session -- the requested-download window, the byte interceptor, explicit transfers (which arm). |
| `questions.py` | The typed questions: `RadioReminder`, `TrustHostKey`, `ChooseSessionTransport`, `CallsignAsk`; Send/Receive's `HomeBbsRoute`, `WinlinkGateway`, `LoginAsk`, `InternetLoginAsk`, `ChooseCategories`, `HowManyBulletins`, `PickFiles`; their answer types (`Credential`, `GatewayChoice`, `InternetLogin`, `SETUP_SKIP`, `SETUP_GO`). |
| `restart.py` | `Restarter` (`core.restarter`): Restart from either front end -- stop the unattended transmitters, disconnect every session, force an unanswered DISC after `DISCONNECT_WAIT`, then the front end's `on_restart`; `__main__` re-executes on `RESTART_EXIT`, a watchdog after `SHUTDOWN_WAIT`. `again=False` is Shut down (no re-exec; the watchdog `halt`s). Never refuses. |
| `hops.py` | `HopConfirmation` and `HOP_TIMEOUT`: the one definition of "the hop came up". |
| `wording.py` | Key and view tokens in notice text, and their neutral rendering (`neutral`); `TRANSMIT_DISABLED`. |
| `links.py` | `SessionLinkAdapter`: a session-tier `Session` in `AX25Link`'s shape. |

## The rules

1. **Talk to the operator only through `Operator`.** A flow that needs to
   say something calls `self.operator.notice(...)`; one that needs a
   decision awaits `self.operator.ask(SomeQuestion(...))`. Never a widget,
   never a toast. **Never a key or tab name in the core's words**: write a
   token (`wording.py`: `{key:toggle_transmit}`, `{view:monitor}`,
   `{view:settings/Radio}`) and each client renders it -- the terminal as
   "Ctrl+T" and "Monitor tab (F8)", anything else neutrally ("the
   Transmit switch", "Monitor"). Transcripts and the log get the neutral
   form. **Known gap:** some `settings_schema.py` help texts still name
   keys ("Ctrl+G", "F10 menu"); tokenize them before the schema is
   served to another client.
2. **A question is data**: a frozen dataclass subclassing `Question`, with
   its answer type in the docstring. Each client draws it its own way; the
   terminal UI maps it to a screen in `ui/operator.py`'s `SCREENS`.
3. **`ask()` returning None is cancel**, and a cancelled flow transmits
   nothing. A setup question's `SETUP_GO` cancels too, and publishes
   `SetupRequested(place)`: where "there" is, is the client's to know.
4. **Only the core arms the transmit gate** (`Connector.arm_for`), for a
   confirmed, operator-named request. No client arms it directly
   (AGENTS.md "The transmit gate").
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
8. **One configuration: `core.config`.** A client that replaces its
   config (Settings save) replaces the core's; the terminal UI's
   `app.config` is a read-through property for exactly that reason.
9. **Unattended APRS never arms.** An auto-ack, a retry and a beacon tick
   go out only through an open gate; `compose`, `send_position_now` and
   `send_object_now` are operator-committed and arm it.
10. **One loop, no threads.** Call `attach_station()` from the loop the
   station runs on; it captures that context for frame callbacks.
   `core.aprs.start()` (the retry loop) likewise.
