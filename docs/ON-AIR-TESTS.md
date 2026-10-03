# On-air tests waiting for the operator

Things built or fixed without a radio, waiting to be tried on the air.
Newest first within each section. When a test passes, tick it and add the
date; when it fails, note what happened and tell Claude (the transcript in
`~/.local/state/kissterm/logs/` and `kissterm.log` there are the evidence).
A ticked item is removed once the matching ROADMAP or CHANGELOG entry
records it.

Where things are: Settings is F9; the Address Book is Ctrl+G on the
Terminal, Mail, Bulletins or Files tab (E edits an entry); Mail is F2.

## Bulletins (G and I on the Bulletins tab)

- [ ] **First collection over the Internet.** On the Bulletins tab press
  **I**. Expected: the category list appears with WS1EC-2's counts (WX
  310, SPACWX 142, ...). Tick WX only and Save. kissterm sends
  `LB> WX 3005-3104` (numbers will have moved on), then the hundred before
  only if every bulletin listed is still within 7 days, reads those within
  7 days oldest first, and files them under Bulletins > WX. The Terminal
  tab (F5) shows each command. Send Claude the transcript name: the
  `LB> WX n-m` range form is from the LinBPQ source, not yet seen.
- [ ] **A second I lists only what is new.** Straight after: no category
  list this time, `LB> WX <newest+1>-` only, and "No new bulletins" unless
  one arrived meanwhile.
- [ ] **The same over the air with G**, once the Yagi is up: the windows
  are short, so the first collection should take minutes, not hours.

## Files (YAPP and AutoBIN)

- [ ] **Asking WS1EC-2 for a file downloads it by itself.** Over the
  air, connected to WS1EC-2 (or the node, then `BBS`), type `FILES`, then
  `YAPP bulletin.html.zip`. Expected: nothing to arm first; the status
  bar counts `YAPP bulletin.html.zip n/2286` up, the toast says "YAPP
  download complete: bulletin.html.zip, in Files > Downloads (F4)", the
  file is listed there and unzips. Ask again: saved as
  `bulletin.html-1.zip` beside the first. (Failed before the 2026-10-03
  YAPP framing fix: "YAPP peer did not respond before the crash timer".)
- [ ] **The same over WS1EC's SSH login** (`BBS`, then `YAPP
  bulletin.html.zip`). Unknown whether binary survives the server's pty
  and `telnet` client: either it completes and the zip opens, or it fails
  with "YAPP file exceeds advertised size" / "ended unexpectedly". Either
  result is the answer; send the transcript name.
- [ ] **An upload to WS1EC-2.** F10 > Session > File transfer, YAPP,
  Upload, a small file, Start. Expected: "YAPP upload complete"; `FILES`
  then lists it. The same name again: "YAPP upload failed: YAPP peer
  refused: YAPP File <name> already exists".

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
