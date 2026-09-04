# SETUP.md — setting up kissterm

kissterm is a terminal, not a modem — it needs something else on the other
end of a KISS (or AGWPE, or VARA, or kernel AX.25) connection to actually get
frames onto the air. This walkthrough covers installing kissterm itself and
getting each of those backends talking to it. Pick the sections that match
your hardware; you don't need all of them.

## 1. Install kissterm

Three ways, in order of how most people should do this:

**`uv tool install` (recommended if you have `uv`):**

```
uv tool install kissterm
```

Installs kissterm into its own isolated environment and puts the `kissterm`
command on your PATH, without touching any other Python project's
dependencies. `uv tool upgrade kissterm` updates it later.

**`pipx` (the traditional equivalent):**

```
pipx install kissterm
```

Same isolation guarantee as `uv tool install`, if you don't already have
`uv`. `pipx upgrade kissterm` updates it.

**From source, in a virtual environment (for development, or to run an
unreleased branch):**

```
git clone https://github.com/bradbrownjr/kissterm.git
cd kissterm
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The `-e` (editable) install means edits to the source tree take effect
immediately without reinstalling — the right mode for working on kissterm
itself, not for daily use as an end user.

Whichever path you pick, if you plan to use a serial TNC (most hardware TNCs,
and any Bluetooth TNC bound to a serial device) also install the `serial`
extra for faster asyncio I/O:

```
uv tool install "kissterm[serial]"          # or: pipx install "kissterm[serial]"
pip install -e ".[serial]"                  # from-source
```

This is optional — kissterm falls back to a slower thread-pumped serial path
without it (see `kissterm/transport/serial_kiss.py`) — but the fast path is
worth having if it installs cleanly on your platform.

### Raspberry Pi notes

`pyserial-asyncio-fast` (the `serial` extra) pulls in a C extension chain
that does not always build cleanly on ARM, particularly on an older Raspbian
image without build tools installed. If it fails, that's fine — skip the
extra entirely; kissterm still works, just through the blocking serial
fallback instead of the fast asyncio one. Plain `pyserial` (a base
dependency, not optional) has never had this problem on Pi hardware.

If you do want the fast path on a Pi, install build tools first:

```
sudo apt install build-essential python3-dev
```

then retry the `[serial]` extra install.

## 2. Serial TNC setup

This covers any hardware TNC that presents as a serial device: a KPC-3,
TNC2-class TNC, an Arduino-based soundcard modem, or a USB-serial adapter to
any of those. (A Bluetooth TNC bound to `/dev/rfcomm0` also lands here once
paired — see §4.)

### Finding the device

```
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

A USB-serial chip (FTDI, CP210x, CH340 — common in TNC and Arduino-modem
cables) shows up as `/dev/ttyUSB0`; a device with native USB-CDC (some
Arduino boards) shows up as `/dev/ttyACM0`. If more than one shows up and you
aren't sure which is the TNC, unplug it and re-run the command — the entry
that disappears is the one you want.

### The `dialout` group problem

The first connection attempt will very likely fail with a permission error —
serial devices are owned by `root:dialout` on most Linux distributions, and
your user account isn't in that group by default. Fix it once, permanently:

```
sudo usermod -aG dialout $USER
```

**Log out and back in** (or reboot) for the new group membership to take
effect — `usermod` does not apply to your *current* login session, which is
the single most common cause of "I ran the command and it still doesn't
work." Confirm it took with `groups` after logging back in; `dialout` should
be in the list.

### Baud rate

The serial baud rate between your computer and the TNC (often 9600 or
19200) is independent of the *radio* baud rate the TNC transmits at (1200 on
VHF FM, up to 9600 on some VHF/UHF setups, various rates on HF). Check your
TNC's manual for its serial default — many KPC-3-class TNCs default to 9600
serial regardless of radio speed. kissterm's serial transport takes the
serial baud as a parameter; get that number from the TNC, not from the radio
mode you intend to use.

### Putting a KPC-3/TNC2-class TNC into KISS mode

These TNCs boot into their own command-mode terminal, not KISS, by default.
Using a plain terminal program (`screen /dev/ttyUSB0 9600`, `minicom`, or
similar — not kissterm itself, which expects KISS bytes already), send:

```
KISS ON
RESTART
```

The TNC drops into KISS mode immediately and stops responding to command-mode
text — that's expected, not a hang. If you need to get back to command mode
later (to change a setting), the standard escape is powering the TNC off and
on, or sending the KISS `RETURN` command bytes it defines
(`kissterm.transport.kiss.exit_kiss` does this from kissterm's own side, via
whatever key or setting exposes it once that UI exists).

## 3. Direwolf setup

[Direwolf](https://github.com/wb2osz/direwolf) is a software TNC — a
soundcard modem plus a KISS/AGWPE server — and the easiest way to get
kissterm on the air without dedicated TNC hardware. A minimal working
`direwolf.conf`:

```
ADEVICE plughw:1,0
CHANNEL 0
MYCALL WS1EC-1
MODEM 1200
AGWPORT 8000
KISSPORT 8001
```

- `ADEVICE` names your soundcard. Run `arecord -l` to list ALSA capture
  devices and match the card/device numbers; `plughw:1,0` means card 1,
  device 0.
- `CHANNEL 0` is the radio port number — this is the value that shows up in
  KISS frames' port nibble (see `kissterm/transport/kiss.py`'s docstring on
  why the port lives there).
- `MYCALL` is your callsign — required, Direwolf won't start meaningfully
  without it.
- `MODEM 1200` selects Bell 202 1200-baud AFSK, the standard for VHF/UHF
  packet and APRS. Use `MODEM 9600` for 9600-baud G3RUH-style packet if your
  radio and soundcard interface support it.
- `AGWPORT 8000` / `KISSPORT 8001` are Direwolf's two TCP interfaces. kissterm
  uses `KISSPORT` for its primary KISS-over-TCP transport
  (`kissterm/transport/tcp_kiss.py`) and `AGWPORT` only if you specifically
  choose the AGWPE transport instead (`kissterm/transport/agwpe.py`) — you
  don't need both configured on the kissterm side, just both left enabled in
  Direwolf in case you want to switch later.

Start it with `direwolf -c direwolf.conf` and point kissterm at
`localhost:8001` (KISS) or `localhost:8000` (AGWPE).

### Reaching Direwolf from another machine on the LAN

By default Direwolf's `KISSPORT`/`AGWPORT` bind to all interfaces, so a
Raspberry Pi running Direwolf next to the radio is reachable from your
kissterm machine elsewhere on the LAN at `<pi-ip-address>:8001` with no
Direwolf config change needed. Two things that do trip people up:

- **Firewall.** If the Pi (or whatever host runs Direwolf) has `ufw` or
  similar enabled, open the port: `sudo ufw allow 8001/tcp` (and `8000/tcp`
  if you'll use AGWPE too).
- **Only one client at a time on most Direwolf builds.** If kissterm can't
  connect and nothing else is obviously wrong, check whether another
  program (a second kissterm instance, a monitoring tool) already has that
  KISS port open.

## 4. Bluetooth TNC pairing (Mobilinkd and similar)

A Mobilinkd TNC3/TNC4 in its classic-Bluetooth (SPP) mode pairs like any
Bluetooth serial device:

```
bluetoothctl
> power on
> scan on
                       # wait for the TNC to appear, then note its MAC address
> scan off
> pair AA:BB:CC:DD:EE:FF
> trust AA:BB:CC:DD:EE:FF
> quit
```

From there you have two options:

- **Bind a persistent `/dev/rfcomm0`** and use kissterm's ordinary serial
  transport against it, which is the simpler and more predictable path:

  ```
  sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF
  ```

  This creates `/dev/rfcomm0`, which behaves like any other serial TNC from
  here — see §2 for baud rate and the `dialout` group note (it applies to
  `/dev/rfcomm0` the same as `/dev/ttyUSB0`).

- **Let kissterm open the RFCOMM socket directly**, once that path exists in
  the Bluetooth transport (see ROADMAP P3) — no `rfcomm bind` step needed,
  at the cost of one more moving part on kissterm's side. Until that lands,
  the `rfcomm bind` approach above is the one that works today.

A Mobilinkd TNC4 running in **BLE** mode instead of classic Bluetooth is a
different case entirely — it does not show up as a serial device at all, and
needs the `ble` extra (`bleak`) and GATT-level support that is not yet
implemented (ROADMAP P3). If your TNC supports both modes, classic Bluetooth
via `rfcomm bind` is the one to use with kissterm today.

## 5. VARA HF/FM on Linux under Wine

**This path is not yet verified against real hardware.** VARA (both HF and
FM) is Windows-only software; running it on Linux means running it under
Wine. The notes below describe the intended setup, not a confirmed-working
one — treat them as a starting point, not a guarantee.

VARA exposes two TCP ports per mode: a control port and a data port.

| Mode | Control port | Data port |
|---|---|---|
| VARA HF | 8300 | 8301 |
| VARA FM | 8400 | 8401 |

The control port takes text commands (connect, disconnect, status) and the
data port carries the actual byte stream once connected — this is why VARA
is a `SessionTransport` in kissterm's architecture (see
`kissterm/transport/base.py`), not a `FrameTransport`: VARA's own software
runs the link layer, so kissterm's AX.25 state machine (`ax25/session.py`)
is not involved at all for a VARA link, by design.

**Soundcard routing** under Wine needs VARA's Windows-side audio device
selection to actually reach your Linux ALSA/PulseAudio soundcard — this
typically means running Wine with PulseAudio's ALSA compatibility layer
active, or routing through `pavucontrol` to confirm VARA's Wine process is
actually reading from and writing to the interface connected to your radio,
not your desktop's default mic/speakers. Get audio confirmed working (VARA's
own level meters moving in response to received audio) before troubleshooting
anything on the kissterm side.

Until this is verified against real hardware, treat any kissterm-VARA
connection issue as equally likely to be a Wine/audio-routing problem as a
kissterm bug.

## 6. Linux kernel AX.25 as an alternative

If you already have a working `kissattach`/`ax25d` setup — an `axports`
file, a kernel AX.25 stack in use by other software (some node/BBS packages
still assume it) — kissterm can sit on top of the kernel's own connected-mode
implementation instead of running its own, through a kernel `AF_AX25`
`SessionTransport` (see ROADMAP P3 — not yet implemented).

**When you'd want this instead of kissterm's own KISS-over-TCP/serial path:**
mainly if you're running other AX.25-aware software on the same machine that
needs the kernel stack anyway (so it's already configured and you'd rather
not run two independent AX.25 implementations against the same TNC
simultaneously), or if you specifically want the kernel's routing/multi-app
port-sharing behavior. If you have no existing kernel AX.25 setup and no
other software that needs one, there's no reason to set one up just for
kissterm — KISS over serial or TCP (§2–3) is simpler and is what kissterm is
built around.

## 7. First run

Launch `kissterm` with no arguments the first time and the setup wizard
walks you through:

- **Transport selection** — serial device (auto-detected candidates from
  `/dev/ttyUSB*`, `/dev/ttyACM*`, `/dev/rfcomm*`) or a KISS/AGWPE TCP host,
  with a short LAN probe offered for the latter so you don't need to already
  know your Direwolf host's IP address.
- **Baud rate** (serial) or **host/port** (TCP), pre-filled with the most
  common defaults (9600 baud; Direwolf's 8001/8000).
- **Your callsign**, used as the default source address for outgoing
  connections.

The wizard writes what it collects to kissterm's config so it doesn't ask
again on the next launch. If something's already misconfigured — wrong
device, TNC not responding — you don't need to re-run the interactive wizard
to check:

```
kissterm --doctor
```

This runs the same checks the wizard would (can the configured transport
open, does a KISS TNC answer, is the configured serial device present and
permission-readable) and prints the results non-interactively, without
launching the full TUI. Use it first whenever something that used to work
stops working — it's faster than launching the app and hitting a dead
monitor pane before figuring out which layer failed.

## 8. Troubleshooting

**No traffic in the monitor pane.**
Confirm the transport itself is open (`kissterm --doctor`, or the status bar
once inside the app) before suspecting anything higher up — an open-but-
silent transport usually means either nothing is actually on the air
nearby, or Direwolf/your TNC isn't hearing anything (check Direwolf's own
console output, or a hardware TNC's status LEDs, independent of kissterm
entirely). If the transport shows open and *other* software confirms traffic
exists, check that you're on the matching KISS port number — a multi-channel
Direwolf setup with `CHANNEL 0`/`CHANNEL 1` puts each channel's frames on a
different port nibble (`kissterm/transport/kiss.py`), and listening on the
wrong one looks identical to no traffic at all.

**Permission denied on `/dev/ttyUSB0` (or similar).**
This is the `dialout` group issue from §2 almost every time. Run `groups`
and confirm `dialout` is listed; if you just added yourself to the group,
you need to log out and back in — `usermod` doesn't retroactively apply to
an already-open session. If `dialout` is present and it still fails, check
whether another process already has the device open (`lsof /dev/ttyUSB0`).

**Connects then times out.**
The SABM/UA handshake completed but no I-frames are flowing, or T1 keeps
expiring — check paclen/window settings aren't set higher than the link can
actually sustain (a marginal RF path with a large window means one dropped
frame stalls a whole batch waiting on retransmission), and confirm both ends
agree on modulo (8 vs. 128) — a mismatch here isn't detectable from the wire
format alone (see the note in `kissterm/ax25/frame.py`'s `decode()`
docstring), so it has to be a matching configuration choice on both sides,
not something kissterm can silently work around.

## 9. Developer setup

Clone and install from source per §1, then enable the repo's git hooks
(bumps the version on every commit, re-syncs your venv's dependencies after
a pull that touched `pyproject.toml`):

```
git config core.hooksPath hooks
```

This is a one-time, per-clone setting — it is not something cloning the repo
does for you automatically, and it is not stored in the commit history
itself.

Run the test suite with:

```
pip install -e ".[dev]"
pytest
```
