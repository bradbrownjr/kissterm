# On-air tests waiting for the operator

Things built or fixed without a radio, waiting to be tried on the air.
Newest first within each section. When a test passes, tick it and add the
date (Claude ticks one from a result the operator reports); when it fails, note what happened and tell Claude (the transcript in
`~/.local/state/kissterm/logs/` and `kissterm.log` there are the evidence).
A ticked item is removed once the matching ROADMAP or CHANGELOG entry
records it.

Where things are: Settings is F9; the Address Book is Ctrl+G on the
Terminal, Mail, Bulletins or Files tab (E edits an entry); Mail is F2.

## The APRS map (0.1.444, 2026-10-06)

Listen on the local APRS frequency for a while first, so the Heard list
has stations with positions. Your own position is Settings > APRS
(latitude and longitude) or the GPS.

- [ ] **Off-air stations land where they are.** F10 > APRS > Map.
  Expected: the stations you heard, at their real places against the
  roads and towns you know (zoom in with I until counties and roads
  show), distances and bearings in the list that match the Heard tab's.
- [ ] **An object off the air shows, and a killed one goes.** When a
  station sends an object (a net, an event), it appears with `+` and
  "by" its reporter; when it is killed, it leaves the map within a few
  seconds.
- [ ] **The phone's Map matches.** Messages > Map on the phone, with the
  map open in the terminal too. Expected: the same points; a tap on one
  shows its distance, bearing, last heard and comment; new stations
  appear without reopening it.
- [ ] **An object placed from the map goes out and shows** (0.1.446).
  Terminal: F10 > APRS > Map, pan until the `x` is on a place, Insert,
  name it, Send object. Phone: long-press the map, name it, Send. Expected:
  on your map at once, "yours"; heard by another station or aprs.fi at
  that place. Then Delete (terminal) or Kill (phone): it leaves your map
  and theirs.
- [ ] **Mic-E positions land where they are** (AGENTS.md section 8: Mic-E
  is not yet checked against off-air traffic). A mobile with a Mic-E
  radio (a Kenwood TH-D74, a Yaesu FTM) on the map. Expected: on the
  road it is on, not hundreds of miles off.

## Remote control from a phone (0.1.414, 2026-10-05)

Install the `web` extra on the station (SETUP.md section 11), turn on
Settings > Remote > Remote control, and open Session > Remote pairing.

- [x] **The phone opens the link** (2026-10-06, Galaxy S25 Ultra). Scan
  the QR code. Expected: the remote control in the phone's browser,
  "TX OFF" in the corner, and the `#t=...` gone from the address bar.
- [ ] **A reload keeps the pairing.** Reload the page. Expected: it still
  connects (the browser kept the key).
- [x] **Send/Receive from the phone, by radio** (2026-10-06). Mail >
  Send/Receive. Expected: the Home BBS run over RF, the new mail in
  BBS/Inbox on the phone.
- [ ] **A Send/Receive signs off with B** (0.1.424). Run Send/Receive by
  radio. Expected: after the outcome notice, `B` in the session, the
  BBS's "73 de WS1EC", and the BBS hanging up (the tab shows the link
  off); the Monitor shows the BBS's DISC, not one from kissterm.
- [ ] **Watch and cancel a Send/Receive** (0.1.422). Start Send/Receive
  from the phone's Mail. Expected: the button's icon turns and the
  progress line ("Receiving 1 of 2") counts dots until the run ends.
  Start another and tap the turning button partway: "Cancelling
  Send/Receive...", the link is disconnected (a DISC in the Monitor), and
  the notice says "Send/Receive stopped: cancelled". Tapped while the
  station is still calling, the SABMs stop and the notice is
  "Send/Receive cancelled."
- [ ] **A connect shows at once, and Cancel stops it** (0.1.421). Connect
  from Stations to a station that will not answer. Expected: Sessions
  at once, an hourglass over the new session with Cancel; Cancel stops
  the SABMs (the Monitor shows no more) and the session's tab goes.
- [ ] **A swipe connects only when asked.** In Stations > Contacts, swipe
  a contact that has a frequency to the right. Expected: "Connect to
  ...?" and nothing on the air; Cancel, and still nothing. Swipe again
  and press Connect: the radio reminder comes up on the phone (and on
  the station's screen; answer on either), then the SABM, "TX ON" in red
  on the phone and the station, and the phone moves to Sessions with the
  node's banner.
- [ ] **Type to the node.** Send a command from Sessions. Expected: the
  line in bold, the node's answer below it with its colours, and the
  same lines on the station's own Terminal tab.
- [x] **Get bulletins from the phone** (0.1.426). On a Bulletins folder
  tap the button: "Get bulletins?" with By Internet and By radio; By
  radio runs the bulletin collection over RF. **Passed 2026-10-06** from
  the mobile web UI: By radio started the run over the air (the link
  failure after `LC` is under Bulletins below), then By Internet
  collected over SSH.
- [ ] **Files and By Internet from the phone** (0.1.426). On Files: "Get
  files from the Home BBS?", then the station's file list as a question
  on the phone. On BBS/Inbox, By Internet: the run over Telnet with
  nothing in the Monitor's transmit lines.
- [ ] **Send position and Send beacon from the phone** (0.1.426).
  APRS messages > Send position > Send: transmit turns on and one
  position report shows in the Monitor. More > Send beacon asks Packet
  or APRS (0.1.436): Packet beacon with transmit on sends the beacon
  text once; with transmit off, the notice that transmit is off and
  nothing on the air. APRS position: one position report, as above.
- [ ] **Mail written on the phone goes out** (0.1.433). BBS Mail > the pencil (Write)
  a short private message to yourself at the Home BBS (or Reply to one),
  Save to Outbox, then Send/Receive by radio. Expected: the message in
  BBS/Outbox until the run, then sent (the session shows the `SP` or
  `SR` and the text), and in Sent. A swipe-deleted message is in
  BBS/Deleted, and Undo put one back.
- [ ] **A radiogram written on the phone goes out** (0.1.440). BBS
  Mail > the pencil > Type: NTS radiogram (ST); fill it in to a real
  NTS addressee (or one your net expects as a test, Test switched on),
  Save to Outbox, then Send/Receive by radio. Expected: the session
  shows `ST <zip> @ NTS<state>` with the title the form showed, the
  BBS takes it, and it is in Sent.
- [ ] **Reconnect from the phone** (0.1.434). Connect to the node from
  the phone, disconnect it, then tap **Reconnect** and confirm.
  Expected: the radio reminder, then the same route and login as the
  first time, and the session back in the same tab.
- [ ] **Turn transmit off from the phone.** Tap "TX ON". Expected: off at
  once, on the phone and the station's status bar, with no question.
- [ ] **Sleep and wake.** Lock the phone for a minute while the node
  sends something, then unlock. Expected: the remote control reconnects
  by itself and shows what arrived meanwhile.
- [ ] **Add to Home screen.** Install it from the browser's menu.
  Expected: it opens full screen with the kissterm name.

## Remote control server (0.1.408, 2026-10-05)

`kissterm --serve` (SETUP.md section 11). Use the phone's remote control
(above), or for the raw protocol a WebSocket test client (for example
`python -m websockets ws://HOST:7425/v1`, then paste
`{"type":"hello","token":"<the part after #t=>"}`).

- [ ] **Behind Caddy.** Set Settings > Remote > Public URL to the proxy's
  address and start `kissterm --serve`. Expected: the printed link and QR
  code use the `https://` address; a client reaches `wss://.../v1` through
  the proxy and gets a `welcome`; kissterm.log names the client's own
  address (from `X-Forwarded-For`), not the proxy's.
- [ ] **A remote connect.** With the client, send
  `{"type":"command","id":"1","name":"connect","args":{"target":"<node>"}}`
  with TX off. Expected: a "Transmit ENABLED" notice, the SABM on the
  air, `SessionOpened` and the node's banner as `SessionData` events.
  Then `send_line` a command and `disconnect`.
- [ ] **Inside the terminal.** Turn on Settings > Remote > Remote
  control, open Session > Remote pairing and scan the QR code with a
  phone. Expected: the phone's browser opens the `http://...:7425/#t=...`
  link (the remote control, with the `web` extra), `REMOTE`
  in the status bar, and after Rotate (confirmed) the old link refused.
- [ ] **A reminder with no client.** Give a contact a frequency reminder,
  close the client, and trigger a connect to it from another client that
  then disconnects at once. Expected: nothing transmitted.

## The channel and Settings, after the core rework (0.1.404, 2026-10-05)

What kissterm hears (the heard list, the Monitor, NET/ROM nodes, "mail
for" beacons, watched callsigns) and saving Settings moved into kissterm's
core, with nothing meant to change on screen.

- [ ] **Monitor and Heard.** Listen a few minutes. Expected: the Monitor
  (F8) shows frames both ways; Heard (F7) lists the stations, with
  distance and bearing for APRS stations and nodes that beacon a grid.
- [ ] **A "mail for" beacon.** When your node beacons mail for your call:
  one toast "... has mail waiting for ...", not one per beacon.
- [ ] **Settings save on the air.** Change Paclen in Settings and Save,
  then connect. Expected: the new paclen used on the new link (Monitor,
  frame lengths), and a bad value in any field saves nothing.

## Mail, bulletins and files, after the core rework (0.1.403, 2026-10-05)

Send/Receive, Get bulletins, Get files and YAPP/AutoBIN transfers moved
out of the terminal UI into kissterm's core, with nothing meant to change
on screen. One session with the Home BBS confirms it.

- [ ] **G on Mail.** Expected: "Connecting to ... to send and receive
  mail" toast, the phase in green in the status bar, the session in its
  Terminal tab (lines sent echoed, a password as `********`), one outcome
  toast, and the link disconnected at the end.
- [ ] **G on Bulletins and on Files.** Bulletins: the categories question
  on a first run; Files: the file list, then the download into Files >
  Downloads. Each ends with one outcome toast.
- [ ] **A typed YAPP download.** Connected to the BBS in the Terminal, type
  `YAPP <name>`. Expected: the download starts by itself, its progress in
  the status bar, the file in Files > Downloads.
- [ ] **S on Files with TX off.** Expected: "Transmit ENABLED" toast once
  you press Start, then the upload.

## APRS, after the core rework (0.1.402, 2026-10-05)

APRS decoding, messages, the ack-and-retry queue, both beacons and GPS
moved out of the terminal UI into kissterm's core, with nothing meant to
change on screen. One APRS session confirms it.

- [ ] **A message to you, TX on.** Have a station (or APRS-IS through an
  igate) send you a numbered message. Expected: its tab opens and is
  marked unread, and the Monitor (F8) shows your ack go out under your
  APRS identity.
- [ ] **The same with TX off.** Expected: one "needs an acknowledgment,
  but Transmit is OFF" toast, not one per retry, and no ack on the Monitor.
- [ ] **Sending with TX off.** Type a message to a station and Send.
  Expected: "Transmit ENABLED" toast, the message on the Monitor, "sent"
  then "ack" in the conversation once it answers; with no answer, a retry
  about every 30 s or more on the Monitor, never with TX off.
- [ ] **Beacons after a Settings save.** Change the BTEXT or APRS beacon
  text in Settings and Save, then Send beacon / Send position. Expected:
  the new text on the Monitor, not the old one.

## Connecting and sessions, after the core rework (0.1.399 and 0.1.401, 2026-10-05)

The connect flow (0.1.399) and then the sessions themselves (0.1.401:
sending, receiving, transcripts, node identification, incoming calls)
moved out of the terminal UI into kissterm's core, with nothing meant to
change on screen. Worth one session on the air to confirm.

- [ ] **Typing to a node with TX off.** Connect, press Ctrl+T to turn TX
  off, type `I` and Enter. Expected: "Transmit ENABLED" toast, the line in
  the Terminal, the node's answer below it, and both in the transcript
  (Session > Transcripts).
- [ ] **The node is named in the status bar.** Connected to WS1EC-15: the
  status bar shows `BPQ32` after its prompt arrives; `BBS` there shows
  `BPQ32 > BPQMAIL`, and `B` back at the node drops the `> BPQMAIL`.
- [ ] **Someone calls you.** With Answering on (Settings), have another
  station connect to you while a session is open. Expected: a new tab,
  not switched to, marked unread; a "Connection from" toast.

- [ ] **A dial from the Address Book with a frequency on file.** Give a
  node a frequency (E in the Address Book), then dial it. Expected: the
  "Before connecting" reminder first; Cancel sends nothing (Monitor, F8,
  stays quiet). Dial again and Connect: "Transmit ENABLED" toast if TX was
  off, SABMs on the Monitor, the node's banner in its own Terminal tab.
- [ ] **Ctrl+D while it is still calling.** Dial a station that will not
  answer and press Ctrl+D during the SABMs. Expected: no more SABMs on the
  Monitor, and the transcript says the connect was cancelled.
- [ ] **A saved login and a hop.** A contact with a hop (via WS1EC-7) and
  a saved login: the "C <node>" goes out, then the login lines, each shown
  in the Terminal, the password as `********`.

## Bulletins (G and I on the Bulletins tab)

- [x] **First collection over the Internet.** On the Bulletins tab press
  **I**. Expected: the category list appears with WS1EC-2's counts (WX
  310, SPACWX 142, ...). Tick WX only and Save. kissterm sends
  `LB> WX 3005-3104` (numbers will have moved on), then the hundred before
  only if every bulletin listed is still within 7 days, reads those within
  7 days oldest first, and files them under Bulletins > WX. The Terminal
  tab (F5) shows each command. Send Claude the transcript name: the
  `LB> WX n-m` range form is from the LinBPQ source, not yet seen.
  **Passed 2026-10-06** (`20261006-231343_KC1JMH_WS1ECSSH.log`): the
  14 categories with counts, ALERT, DTN, NTS and WX chosen, `LB> ALERT
  3112-3211` and older windows answered, the WX listing stopped with `A`
  once it reached older dates, then 72 bulletins of the last 7 days
  (#3004 of 29 September first) read oldest first and filed under
  Bulletins > WX; cancelled by the operator after 10, all 10 filed.
- [ ] **A second I lists only what is new.** Straight after: no category
  list this time, `LB> WX <newest+1>-` only, and "No new bulletins" unless
  one arrived meanwhile.
- [ ] **The same over the air with G**, once the Yagi is up: the windows
  are short, so the first collection should take minutes, not hours.
  **Failed twice on 2026-10-06** (`20261006-202640_KC1JMH_WS1EC-2.log`,
  `20261006-225734_KC1JMH_WS1EC-2.log`): the greeting and prompt
  arrived, `LC` went out, then nothing came back and the link failed
  after 11 retries (68 s and 140 s later). No frame log: run the station
  with `--log-level debug` for the next try, so kissterm.log shows
  whether the BBS's reply was heard and what was acknowledged.

- [ ] **More than 20 new asks first** (0.1.449). A first collection of
  WX (72 new on 2026-10-06): before any `R`, "72 new bulletins on
  WS1EC-2" with Newest 20, All 72 and None, on the terminal and on the
  phone. Newest 20 reads only the 20 highest numbers; None reads nothing
  and the next run offers them again.
- [ ] **A small category is one listing** (0.1.449). Tick a category the
  list counts 20 or fewer in (NTS had 1): kissterm sends `LB> NTS` once,
  not `LB> NTS n-m` window after window.

## Files (YAPP and AutoBIN)

- [x] **Asking WS1EC-2 for a file downloads it by itself.** Over the
  air, connected to WS1EC-2 (or the node, then `BBS`), type `FILES`, then
  `YAPP bulletin.html.zip`. Expected: nothing to arm first; the toast
  says "YAPP download complete: bulletin.html.zip, in Files > Downloads
  (F4)", the file is listed there and unzips. **Passed 2026-10-03**
  (operator: "File download worked great!"; the zip opened in the Files
  viewer). Failed before that day's YAPP framing fix.
- [ ] **A second download of the same file is kept beside the first.**
  `YAPP bulletin.html.zip` again: saved as `bulletin.html-1.zip`, the
  first untouched. (Not reported with the download above.)
- [ ] **Over WS1EC's SSH login, YAPP is refused before it goes out.**
  (`BBS`, then `YAPP bulletin.html.zip`.) Expected: a notice "File
  transfers are not supported over SSH...", the line still in the send
  field, nothing new from the BBS; F10 > Session > File transfer gives
  the same notice. (2026-10-04: sent, the download stalled because the
  server's telnet held kissterm's replies until the next line.)
- [x] **An upload to WS1EC-2.** F10 > Session > File transfer, YAPP,
  Upload, a small file, Start. Expected: "YAPP upload complete"; `FILES`
  then lists it. **Passed 2026-10-04** over RF (operator: "Test file
  uploaded over RF", `test.md`, picked with Enter before the picker had
  a Choose button).
- [ ] **Uploading a name the BBS already has is refused with its
  reason.** Upload `test.md` again: "YAPP upload failed: YAPP peer
  refused: YAPP File test.md already exists". (Not reported with the
  upload above.)
- [ ] **After a YAPP transfer fails, the BBS takes the next command.**
  Only when one fails by itself (a timeout on a weak path, say): the
  Terminal shows "File Rejected - ..." from the BBS, and the next command
  typed (`FILES`) is answered normally, not with "Unexpected message
  during YAPP Transfer". (kissterm sends YAPP CAN on failure since
  2026-10-04, per BPQ's source; never seen on the air.)
- [ ] **G on the Files tab downloads what is ticked.** F4, G (the Home
  BBS over the air, Settings > Mail's route). Expected: after the
  reminder and the BBS prompt, a checklist of WS1EC-2's files (eight in
  October, not the `zType YAPP...` hint), each with its size and "about
  N s", nothing ticked; tick one, Download. The status bar counts the
  bytes, the Terminal shows `FILES` and `YAPP <name>` but none of the
  file, the toast says "1 file(s) downloaded into Files > Downloads",
  and the link disconnects. Tick two the next time: both arrive, one
  after the other. (Built 2026-10-04 against the 2026-10-03 capture and
  BPQ's source.)

## Mail: Send/Receive (G on the Mail tab)

- [ ] **Resend the message to W1BKW** ("Hello from kissterm", still in
  Mail > BBS > Outbox). Three tries on 2026-09-25 failed the same way:
  the body went as one 182-byte frame, retried 30-37 times, and the node
  never received it while it answered every poll. Try it with the new
  yagi first, unchanged. If it fails again the same way, set **Paclen** on
  the WS1EC-2 Address Book entry to 64 and try once more; say which worked.
- [ ] **No half-sent copies reached the BBS.** Connect to WS1EC-2 by hand
  and type `L< KC1JMH` (messages from you). Expected: #2820 (the reply to
  Dave) and nothing addressed to W1BKW until the resend above succeeds.
  This confirms BPQMail drops an unfinished message on disconnect (read
  from the LinBPQ source, not yet seen).
- [ ] **The status bar during G** shows green progress: `Connecting to
  WS1EC-2`, `Waiting for the BBS`, `Sending 1 of 1`, `Checking for mail`,
  `Receiving 1 of 2`, then nothing. Toasts at the start and the end only.
- [ ] **A stopped run explains itself.** If a send stalls again, the
  toast should say what was sent "had not reached the BBS" with the frame
  size and the paclen hint, not "nothing from the BBS".
- [ ] **First bulletin (SB).** Insert, Type: Bulletin, To a category the
  BBS carries (for example `TEST` or one from `LC`), and for a first
  try pick "This BBS only (no @)" in the Distribution list. Then G. SB is built from the LinBPQ source only; the
  transcript of this first send becomes the test fixture.
- [ ] **First radiogram (ST).** Insert, Type: NTS radiogram. Address it
  to someone you can check with, TEST ticked if it is an exercise. The
  status line should read `ST <zip> @ NTS<state>` and a title like
  `AUGUSTA 207 555`. Then G: the BBS should ask for the title, take it,
  and answer `Message: N Bid: ...`. Afterwards, `L` on the BBS shows it
  as type T. ST is built from the ARRL MPG, the 2026 RRI guidelines,
  KY2D's review and LinBPQ; the transcript of this first send becomes
  the test fixture.
- [ ] **First Radiogram-ICS213**, to a traffic handler who can say
  whether it reads right (KY2D, if willing): Type: Radiogram-ICS213,
  HXI is filled in, add a Subject. The body should end BT, the
  signature with position, then the subject line.
- [ ] **What NTS titles look like on WS1EC.** While connected, `LT`
  lists the NTS traffic the BBS holds (one listing, no reads). Note the
  titles other stations use: kissterm's `CITY CALLSIGN` / `CITY NXX NXX`
  / `CITY - -` came from KY2D, and the published guides disagree, so a
  real listing settles it (`nts.py`'s docstring marks it UNVERIFIED).
- [ ] **First ICS-213 (form).** Insert, Type: ICS-213 General Message
  (form), fill it in, Continue, address it to yourself, Save, then G.
  Read it back: the numbered blocks should arrive as sent. If a Winlink
  Express user can receive one, ask whether it reads as an ICS-213 to
  them (it has no XML attachment, so it shows as text, not the form).
- [ ] **PKTNET check-in during the next net week** (none early: the net
  refuses check-ins before its window opens). Insert, Type: PKTNET
  Check-in (form), Continue: it should come back as a bulletin to
  `PKTNET @ USA` titled "Name, Call, Town, State". Save, G, and look for
  your call in that month's results on vden.org.
- [ ] **ICS-309 to a Winlink station**: after an exercise, send the
  log as a P message to someone on Winlink Express and ask whether it
  reads as a 309 (tabs arrive as spaces; the 214 and 205 likewise).
- [ ] **A form from another station reads as a form**: ask a Winlink
  Express user (or bpq-apps' forms) to send you an ICS-213 or a check-in
  through the BBS. After G, open it: it should show as the form, and V
  should show the text. Note anything that lands under the wrong label.
- [ ] **ICS-213 reply**: R on that ICS-213, Reply on form, fill block 9,
  Save, G. Ask the sender whether Winlink Express shows it as a reply.
- [ ] **GYX Weather strip** during a SKYWARN activation or net: Insert,
  Type: GYX Weather Report (strip), fill it, address it as the net asks.
  The body should be one line, `GYX WEATHER/.../...//`; ask net control
  whether it pasted into their sheet, and whether blanks as three spaces
  are what they want.
- [ ] **Answer strip on a reply**: when a net sends a request strip, R on
  it, Answer strip, fill, Save. The reply's text should be the answer
  strip alone, sent as SR.
- [x] **Reply by number (SR)** went out and was accepted as #2820
  (2026-09-25), and moved to Mail > BBS > Sent with its number and BID.

## Mail: writing and reading

- [ ] **Compose at your terminal size**: R on a message. The text area
  should take most of the dialog, with no empty rows between To, Title
  and the text.
- [ ] **Q quotes, R does not** (Settings > Mail > Quote in replies off);
  turn the setting on and R quotes too.
- [ ] **One click on a message shows it** in the reader.
- [ ] **Transcripts keep blank lines** that fall at the end of a frame:
  read a message with paragraphs (for example `R 2801`) and compare the
  transcript file with the screen.

## Connecting

- [ ] **Each line shows once over WS1EC SSH.** Connect to the WS1EC SSH
  contact and type `routes`, then `c 8 kc1uix-3`. Expected: each line you
  typed appears once, not twice; the login's password shows as
  `********` in the Terminal and in the transcript (Session >
  Transcripts); the status bar reads `KC1UIX-3 via WS1EC`. If a blank
  line or a stray fragment of your own text still appears, send the
  transcript.

- [ ] **A JNOS mailbox is recognised** (KC1UIX's node, AXIP/UDP through
  WS1EC port 8: connect to WS1EC, then `C 8 KC1UIX` or whatever call
  Dave gives you; or ask Dave KC1UIX to connect from kissterm and send
  his transcript). Expected: the greeting ends "TCP/IP Mailbox (JNOS
  ...)." or "TCP/IP Server (JNOS ...).", the prompt is a menu line like
  `?,A,B,C,...,X >` (or `(#N) >` in expert mode), and F10 > Help > Node
  commands shows "JNOS mailbox" with L, R, S, K, C, T. Then type `?` and
  compare its list to the menu; send the transcript either way, since
  this is the first real JNOS session kissterm will have seen.

- [ ] **A serial TNC** (if you have one: USB-serial, KPC-3 or TNC2 in
  KISS mode, NinoTNC). Settings > Radio, Scan for hardware: it should be
  listed as "Serial KISS (experimental)". Use it, watch the Monitor for
  frames heard, then connect to WS1EC-7. Say whether it worked; it then
  loses the experimental label.
- [ ] **A Bluetooth Classic TNC** (Mobilinkd TNC2/TNC3), both ways from
  SETUP.md section 4: `rfcomm bind` then the serial transport, and
  `kind = "bluetooth"`. Same checks as the serial TNC.
- [ ] **Address Book on the Mail tab** (Ctrl+G there): pick WS1EC-2, Enter.
  It should close, move to Terminal, and connect through the frequency
  reminder as from Terminal. (Not a radio test until the connect.)
- [ ] **Address Book entry dialog** (Ctrl+G, then E on an entry): every
  field on its own row with a label, Paclen and Window visible, Save and
  Cancel on screen at your terminal size. (Not a radio test, but yours to
  confirm.)
- [ ] **WS1EC by SSH from the Address Book** (no radio): at the next
  launch a notice should say your Telnet/SSH connections are now in the
  Address Book. Open it (Ctrl+G), pick the WS1EC one, E: By should say
  SSH, with host, port 4122 and your known-hosts file, and Sign in
  naming its login (username packet). Enter on it: a new Terminal tab named after it opens
  beside any radio session, says "Connecting ... over the Internet", then
  the node's greeting. Type a command: it goes, and the status bar still
  says TX OFF. Ctrl+D hangs up (still TX OFF); Ctrl+R dials it again.
- [ ] **SSH asks to trust a new server** (no radio): save your WS1EC SSH
  contact with Known left empty (Save should now work). Enter on it: a
  "Trust this SSH server?" dialog shows its key fingerprint, with Cancel
  highlighted. Cancel: the tab says host key not trusted. Enter again,
  Trust: it connects, and the next dial asks nothing. Compare the
  fingerprint with `ssh-keyscan -p 4722 ws1ec.mainepacketradio.org |
  ssh-keygen -lf -` if you like.
- [ ] **Immediate SABM when polled** (Settings > Link > Retry at once when
  polled, on). On a marginal connect, the Monitor should show a SABM right
  after a poll from the node instead of waiting out T1.
- [ ] **A single click in the Address Book does not dial**; double click
  or Enter does, through the frequency reminder.
- [ ] **One connect, not two**: a double click on an entry sends one
  stream of SABMs.
- [ ] **T1 and T2**: your saved values were t1=3, t2=3; the defaults are
  now T1 5 and T2 1. Check Settings > Link shows what you want.

## Stray polls

- [ ] **Quit mid-connection, relaunch.** Connect to WS1EC-2, kill kissterm
  (not Ctrl+Q). Relaunch within a minute. Expected: one Terminal line
  naming WS1EC-2 as polling a connection kissterm does not have, and no
  new tab. Say whether the node stops polling after the DM.

## Saved logins

- [ ] **Your logins after the username-and-password change** (not a
  radio test). Launch, then Settings > Logins: each login shows
  "Username X; password saved in the system keyring." A login that was
  two lines (username, then password) is now split that way; the Home
  BBS node login carries your old "Node username". Edit one: Name,
  Username and a masked Password, and Save with the password left empty
  keeps it.
- [ ] **I asks for what it needs, once.** In Settings > Mail set "Node
  login" to (none) and Save, then I on the BBS inbox. Expected: "Send
  and Receive by Internet" with your WS1EC contact chosen, your callsign
  as Username, and an empty Password. Type the node password, then Save
  and continue. The run should log in (`user:`, then `password:`, then
  BBS), and Settings > Mail > Node login should now name
  "<contact> login". Press I again: no question this time.
- [ ] **G asks a BBS login as username and password** (only if your
  BBS asks for a login by radio: Settings > Mail > Login prompt set, BBS
  login (none)). G shows "Home BBS login" with Username and a masked
  Password; the run should answer the prompt with the username line,
  then the password.
- [ ] **An SSH contact signs in with its login.** Ctrl+G, E on the SSH
  contact: "Sign in" should name its login, with no User or Password
  box. Connect to it; it should sign in as before.

- [ ] **Keyring on your desktop** (not a radio test): launch kissterm from
  your desktop session. A notice should say your saved logins moved into
  the system keyring; Settings > Logins should say "in the system
  keyring" for each, config.toml should hold only their names, and a
  connect that uses one should still log in.

## Winlink

Set up: nothing beforehand. On a Winlink folder, G asks which gateway
(WS1EC-10, a node entry whose login script sends RMS, or another
callsign; tick "Remember as my gateway" to skip the question next time)
and then your Winlink password, before dialing. The password is saved
(Settings > Logins); the gateway only if remembered.

- [ ] **First: Winlink over the Internet** (no radio). On the Mail tab,
  select Winlink > Inbox and press I (Footer: "By Internet"). It asks for
  your Winlink password if none is saved, connects to server.winlink.org:8772, and
  runs the exchange: toast "No new Winlink mail" or new messages in
  Winlink > Inbox. Anything in Winlink > Outbox is sent, so leave it
  empty the first time, or put one message to yourself there. Then send
  the transcript (Session > Transcripts, the newest `..._WL2K.log`) to be
  made a test fixture. If it stops right after the handshake, say what
  the toast said: the likely cause is the CMS not accepting "kissterm"
  as a client name.
- [ ] **Home BBS by Internet (SSH to WS1EC)** (no radio): the WS1EC
  contact from the Address Book test under Connecting (or a new one:
  Address Book, New, By SSH, host ws1ec.mainepacketradio.org, port 4122,
  user packet; the first connect asks you to Trust its key). On BBS >
  Inbox press I: pick that contact, give your node password. Expect in the transcript (Session
  > Transcripts): the node's `user:` answered with your call, `(password
  sent)`, `BBS`, the BBS greeting and `LM`. If it stalls after the
  password, tell me what the node sent: the After login step
  (Settings > Mail) fires on the first thing heard after the password.
- [ ] **A Winlink attachment** (no radio, with I): from ordinary email,
  send KC1JMH@winlink.org a message with a small text file attached. I on
  Winlink > Inbox: the message's Attachments line should say
  `Files/Attachments/<name> (<size> bytes)`, and F4 Files > Attachments
  should list it, its text shown in the preview.
- [ ] **Winlink's test server** (no radio): Settings > Mail > Internet
  server: Test (cms-z.winlink.org). On a Winlink folder, I. It should log
  in (no "Unknown client" refusal) and say "No new Winlink mail" or file
  what is waiting. Then send yourself a short message and see whether it
  arrives at KC1JMH@winlink.org from Winlink Express or the web: that
  says whether the test server delivers anywhere. Keep the transcript.
- [ ] **A Winlink form opens in Winlink Express** (no radio, with I):
  on a Winlink folder, Insert, Type: ICS-213 (form), fill it, Continue,
  address it to a Winlink Express user (or your own account, read in
  Winlink Express), Save without changing the text, I. In Winlink
  Express it should open in the ICS-213 viewer with every block filled
  and no `{var ...}` left on the page; the message should list
  `RMS_Express_Form_ICS213_Initial_Viewer.xml`. Then the same with a
  Winlink Check-in, an ICS-213RR with two order lines (the table should
  fill its first two rows), a Damage Assessment with HOUSES and one
  category of your own (HOUSES in its row, yours under Other), and R,
  Reply on form on a received ICS-213 (the reply viewer should name the
  original sender).
- [ ] **A Winlink Express form read from its XML** (no radio, with I):
  have a Winlink Express user send you an ICS-213 by Winlink. It should
  show as the form, with the message exactly as typed. A form kissterm
  does not ship (any other Winlink template) should show as "Winlink
  form: <name>" with its fields listed. Keep the message: its `.b2f` in
  Mail/Winlink/Inbox is the first real capture for the tests.
- [ ] **First Winlink session over the radio, nothing to send**: on the Mail tab, select
  Winlink > Inbox; the Footer should say "Send/Receive Winlink". Press G.
  Expect the frequency reminder, then in the Terminal tab (F5): the
  gateway's `[WL2K-...]` line, our `;FW: KC1JMH`, our
  `[kissterm-...-B2FHM$]`, `;PR: <8 digits>` (never your password), then
  `FF` and the gateway's `FQ`, and a disconnect. Toast: "No new Winlink
  mail", or new messages in Winlink > Inbox. **Keep the session
  transcript** (Session > Transcripts) and send it to be made a test
  fixture: it is the first real exchange this code has seen.
- [ ] **A message from Winlink arrives**: send yourself a message from
  winlink.org webmail or another station first, then G. It should land in
  Winlink > Inbox with the right sender, subject and text; the Terminal
  tab should show `[message <MID>, N bytes]` rather than binary.
- [ ] **A wrong password** (temporarily change the saved login): G should
  stop with a toast quoting the gateway ("Secure login failed ...") and
  pointing at Settings > Mail > Winlink. Put the password back.
- [ ] **Sending**: on a Winlink folder, Insert (Type is already "Winlink
  message"), To your own callsign or an email address, then G: it should
  propose it (`FC EM ...`),
  send it after `FS +`, and move it to Winlink > Sent. Check it arrives
  at the recipient.
- [ ] **All Inboxes**: with both the Home BBS and Winlink set up, G on
  All Inboxes (Footer: "Send/Receive all") should run the BBS, disconnect,
  then dial the RMS and run Winlink, with no question in between.
- [ ] **Through a node**: an Address Book entry for the node with a login
  script line `RMS` (or a hop chain to an upstream gateway). The
  exchange should start only when the `[WL2K-` line arrives; the node's
  own lines before it should show as normal session text.

## Standing verifications (from AGENTS.md section 8)

- [ ] **Mic-E** decoding against a real off-air packet.
- [ ] Modulo 128, VARA, Mercury, kernel AX.25 and BLE on real hardware.
