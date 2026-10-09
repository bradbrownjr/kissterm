# kissterm/launch — local contract

Starting the modem program beside the radio (ROADMAP P3a). **M1 is data
only**: `presets.py` holds what a Programs entry starts from; nothing here
starts a process yet. The supervisor (M2) will, with `create_subprocess_exec`
and never a shell, and only a process kissterm started is ever stopped.

- A preset path is a starting point, never a fact about this machine; each
  carries its provenance (`documented`, `recalled`, `unverified`).
- `default_path`/`needs_wine` take the platform as a parameter; never read
  `sys.platform` inside them.
- Discovery never starts a program (AGENTS.md: nothing is sent to a transport
  the operator did not ask for).
