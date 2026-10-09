# kissterm/rig — local contract

Radio control through Hamlib's `rigctld` over TCP (ROADMAP P3a). `rigctld`
is Hamlib's own daemon, so this is Hamlib; kissterm links no Hamlib library
(pip cannot install one) and talks to the binary.

- **Reading never keys.** `f`, `m`, `t`, `l`, `\chk_vfo`, `\dump_state` are
  reads. A method that sets (`F`, `M`, `U`) or keys (`T`, `G TUNE`) says so in
  its name and docstring, and the caller owns the transmit gate: a keying
  call never arms it (AGENTS.md "The transmit gate").
- **`rigctld` listens on every interface unless told otherwise.** Anyone who
  can reach its port can key the radio, so `rigctld_command` always passes
  `-T` with the rig entry's host.
- **No exception leaves a background task.** `RigctldClient.poll` counts and
  logs; the raising methods are for a caller that handles `RigError`.
- Nothing here starts a process except `list_models`, a local read-only
  command. Starting `rigctld` itself is the supervisor's (`kissterm/launch`).
