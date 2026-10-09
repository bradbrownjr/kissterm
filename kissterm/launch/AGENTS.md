# kissterm/launch — local contract

Starting the modem program beside the radio (ROADMAP P3a). `presets.py` is data
(what a Programs entry starts from); `supervisor.py` starts, watches and
stops the program (`create_subprocess_exec`, never a shell; only a process
kissterm started is ever stopped; Restart never waits on a child);
`browse.py` lists folders and executables on the station for choosing one.

- A preset path is a starting point, never a fact about this machine; each
  carries its provenance (`documented`, `recalled`, `unverified`).
- `default_path`/`needs_wine` take the platform as a parameter; never read
  `sys.platform` inside them.
- Discovery never starts a program (AGENTS.md: nothing is sent to a transport
  the operator did not ask for).
