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
  BBS carries (for example `TEST` or one from `LC`), @ a local
  distribution. Then G. SB is built from the LinBPQ source only; the
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
- [ ] **Immediate SABM when polled** (Settings > Link > Retry at once when
  polled, on). On a marginal connect, the Monitor should show a SABM right
  after a poll from the node instead of waiting out T1.
- [ ] **A single click in the Address Book does not dial**; double click
  or Enter does, through the frequency reminder.
- [ ] **One connect, not two**: a double click on an entry sends one
  stream of SABMs.
- [ ] **T1 and T2**: your saved values were t1=3, t2=3; the defaults are
  now T1 5 and T2 1. Check Settings > Link shows what you want.

## Standing verifications (from AGENTS.md section 8)

- [ ] **Mic-E** decoding against a real off-air packet.
- [ ] Modulo 128, VARA, Mercury, kernel AX.25 and BLE on real hardware.
