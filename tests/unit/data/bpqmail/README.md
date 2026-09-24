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

Not yet captured: the reply to `LM` when there is no mail at all.
