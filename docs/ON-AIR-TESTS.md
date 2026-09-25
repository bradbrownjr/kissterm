# On-air tests waiting for the operator

Things built or fixed without a radio, waiting to be tried on the air.
Newest first within each section. When a test passes, tick it and add the
date; when it fails, note what happened and tell Claude (the transcript in
`~/.local/state/kissterm/logs/` and `kissterm.log` there are the evidence).
A ticked item is removed once the matching ROADMAP or CHANGELOG entry
records it.

Where things are: Settings is F9; the Address Book is Ctrl+G on the
Terminal tab (E edits an entry); Mail is F2.

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
