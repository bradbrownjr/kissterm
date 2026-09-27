# On-air tests waiting for the operator

Things built or fixed without a radio, waiting to be tried on the air.
Newest first within each section. When a test passes, tick it and add the
date; when it fails, note what happened and tell Claude (the transcript in
`~/.local/state/kissterm/logs/` and `kissterm.log` there are the evidence).
A ticked item is removed once the matching ROADMAP or CHANGELOG entry
records it.

Where things are: Settings is F9; the Address Book is Ctrl+G on the
Terminal, Mail, Bulletins or Files tab (E edits an entry); Mail is F2.

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
  SSH, with host, port 4122, user packet and your known-hosts file, and
  Password "saved". Enter on it: a new Terminal tab named after it opens
  beside any radio session, says "Connecting ... over the Internet", then
  the node's greeting. Type a command: it goes, and the status bar still
  says TX OFF. Ctrl+D hangs up (still TX OFF); Ctrl+R dials it again.
- [ ] **Immediate SABM when polled** (Settings > Link > Retry at once when
  polled, on). On a marginal connect, the Monitor should show a SABM right
  after a poll from the node instead of waiting out T1.
- [ ] **A single click in the Address Book does not dial**; double click
  or Enter does, through the frequency reminder.
- [ ] **One connect, not two**: a double click on an entry sends one
  stream of SABMs.
- [ ] **T1 and T2**: your saved values were t1=3, t2=3; the defaults are
  now T1 5 and T2 1. Check Settings > Link shows what you want.

## Saved logins

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
  user packet, and a known_hosts file holding its host key). On BBS >
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
