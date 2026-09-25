# BPQMail captures

Real sessions with WS1EC-2 (BPQMail 6.0.23.1), 2026-09-22 and 2026-09-23,
from the operator's kissterm session logs: timestamps and the `< ` prefix
removed, and the operator's own keystrokes (`> ...`) dropped.

- `read_2738_aborted.txt`: direct connect to WS1EC-2 (SID, greeting,
  prompt), `R 2738`, two page prompts, then `A`. Blank line between
  `Title:` and the `R:` lines.
- `read_2712_aborted.txt`: `R 2712` from a listing's page prompt; `R:`
  lines straight after `Title:`; aborted.
- `list_lr.txt`: `LR`, preceded by its page prompt.
- `read_2686_excerpt.txt`: a read that reached `[End of Message #2686 from
  N4SD]`. An excerpt: the middle of the body is left out, and lines that
  the pre-2026-09-22 display bug split at frame boundaries are rejoined.
  Nothing else is changed.

- `read_2578_private.txt`: 2026-09-24, direct connect (SID, greeting,
  prompt), then `R 2578`, a private message read to its end marker.
- `kill_2578.txt`: the reply to `K 2578`.
- `read_99999_not_found.txt`: the reply to `R 99999`.

- `list_lm.txt`: 2026-09-24, `LM` typed before the greeting arrived, with
  nothing unread; lists read private mail only (the node's "Include SYSOP
  msgs in LM" is off).

- `list_lm_empty.txt`: 2026-09-24, the reply to a second `LM` with no mail
  at all: the prompt alone.

- `send_sr_2784.txt`, `send_sp_w1bkw.txt`: 2026-09-25, a reply (`SR
  2784`) and a new private message (`SP W1BKW`), **with the operator's
  lines kept**, since what is sent is the point: `SR` asks no title; both
  add the @ address from the recipient's Home BBS; a bare `SP` is refused;
  `/EX` ends the text; acceptance is `Message: N Bid:  N_WS1EC Size: S`
  (two spaces after `Bid:`). Size counts CRLF line endings: 54 and 214
  match the bodies with their blank lines, so the BBS stored them.
