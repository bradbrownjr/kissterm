# kissterm

A terminal for packet radio that talks to your TNC directly — over a serial
cable, over Bluetooth, or over TCP/IP to a KISS TNC anywhere on your network.
No kernel AX.25 stack. No root. No Windows.

![kissterm connected to a BPQ32 node](assets/screenshot.png)

The monitor pane shows everything on the channel, and the heard list shows who
has been active and whether you heard them directly:

![The monitor pane](assets/screenshot-monitor.png)

![The heard list](assets/screenshot-heard.png)

Everything the first-run wizard asks for stays editable in the app -- callsign,
transport, link timing, APRS:

![The settings pane](assets/screenshot-settings.png)

## Why this exists

Packet radio on Linux has been stuck with a hard choice: use `linpac`, which
needs the kernel AX.25 stack configured with root and cannot talk to a KISS TNC
over the network at all — or boot Windows for BPQTerminal or UZ7HO EasyTerm.

kissterm implements **AX.25 connected mode itself, in userspace, over KISS**.
That one decision is what lets it run unprivileged, on any platform, against a
TNC on a USB cable, a Bluetooth TNC in your pocket, or a Direwolf instance on a
Raspberry Pi in the garage — with nothing to configure at the OS level.

| | kissterm | linpac | BPQTerminal | EasyTerm |
|---|---|---|---|---|
| KISS over serial | yes | via kernel | yes | yes |
| KISS over TCP/IP | **yes** | no | yes | yes |
| Bluetooth TNC | yes | via kernel | no | no |
| Needs kernel AX.25 | **no** | yes | no | no |
| Needs root to set up | **no** | yes | no | no |
| Runs on Linux / macOS / BSD | **yes** | Linux | no | no |
| Terminal UI (works over SSH) | **yes** | yes | no | no |
| VARA / HF modems | in progress | no | yes | no |
| APRS decode | yes | no | no | separate app |

## Features

- **Connect to any packet node or BBS.** Full AX.25 2.2 connected mode with
  retransmission and timer recovery, so a marginal path recovers instead of
  dropping you. Modulo 128 (extended sequence numbers) is supported; modulo 8
  is the default because it is what everything on the air actually speaks.
- **Every transport.** KISS over serial, over TCP/IP, and over Bluetooth;
  AGWPE (Direwolf, UZ7HO SoundModem); the Linux kernel AX.25 stack if you
  already have one. VARA HF/FM and Mercury are implemented but not yet verified
  against hardware — see [docs/ROADMAP.md](docs/ROADMAP.md).
- **USB TNCs are noticed when you plug them in.** No rescan, no restart --
  enumerating serial ports costs 0.4 ms and touches nothing but the local
  machine, so kissterm just watches. If the TNC you are *using* gets unplugged,
  it says so instead of failing quietly later. **The network is never scanned
  automatically**: a sweep is around 1,500 connection attempts, which is fine
  when you ask for it and antisocial on a timer. A configured host that goes
  away is reconnected to by address, not rediscovered by scanning.
- **It finds your hardware.** First run enumerates serial ports, recognises the
  common TNC chipsets by USB ID, sweeps your LAN for the well-known KISS, AGWPE
  and VARA ports, and lists paired Bluetooth TNCs — then asks you to pick one.
  Getting on the air should not require reading a manual first.
- **A real monitor pane.** Every frame on the channel, decoded the way `listen`
  and BPQ show it, with filtering by callsign or payload text.
- **Heard list.** Who you have heard, when, how often, by what path, and
  whether you heard them directly or through a digipeater.
- **APRS.** Positions (uncompressed, compressed, and Mic-E), messages, status,
  objects, weather and telemetry — APRS is just an AX.25 UI frame, so it comes
  almost free on top of the same stack.
- **`kissterm --doctor`.** Diagnoses the things that actually go wrong: serial
  permissions, missing dependencies, an unreachable TNC host, a bad callsign.

## Install

```bash
uv tool install kissterm      # or: pipx install kissterm
kissterm
```

From source:

```bash
git clone https://github.com/bradbrownjr/kissterm
cd kissterm
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/kissterm
```

First run asks for your callsign and then goes looking for your TNC. See
[SETUP.md](SETUP.md) for Direwolf, Bluetooth pairing, serial permissions, and
the rest.

**Nothing you answer at setup is locked in.** The Settings tab (`Ctrl+5`)
edits your callsign, which TNC or modem to use, AX.25 timing (paclen, window,
T1/T2/T3, retries) and APRS beaconing -- with validation, and a note on each
field saying whether it takes effect now, on the next connection, or at
restart. "Scan for hardware" re-runs discovery from inside the app, so moving
your Direwolf host to a new IP does not mean editing a TOML file. Link
parameters deliberately do not change under an established link; they were
negotiated when it came up.

**Changing your callsign specifically takes one keystroke.** `Ctrl+K` in the app, or
`kissterm --callsign W1AW-9` from a shell -- neither re-runs the setup wizard.
Operators change SSID constantly (a `-1` mailbox, a different SSID for portable
or an emergency net, a club call for an event), so this is a first-class
action, not something buried in a config file. It is refused while a link is
up: the callsign is in the address field of every frame of an established
conversation, and swapping it mid-session would kill the link by timeout.

## Keys

| Key | Action |
|-----|--------|
| `F1`..`F4` / `Ctrl+1`..`Ctrl+5` | Terminal / Monitor / Heard / APRS / Settings |
| `Ctrl+N` | Connect to a station |
| `Ctrl+D` | Disconnect |
| `Ctrl+K` | Change your callsign |
| `Ctrl+L` | Clear the active log |
| `Ctrl+Q` | Quit |

Connect targets accept a digipeater path: `WS1EC-7 via W1AW-1,W1XYZ`.

## Command line

```
kissterm                     launch
kissterm --doctor            run diagnostics and exit
kissterm --discover          scan for TNCs and modems, print, exit
kissterm --callsign W1AW-1   set your callsign and exit (no wizard)
kissterm --setup             re-run the first-run wizard
kissterm --transport NAME    open a specific configured transport
kissterm --connect WS1EC-7   connect once the app is up
```

## Safety notes

kissterm never transmits anything you did not ask it to. **It does not answer
calls from other stations unless you turn that on** -- answering is unattended
transmission under your callsign, and a fresh install must not start doing that
on its own. With it off, a station calling you gets a polite refusal (a DM) and
stops retrying rather than transmitting into silence. With it on, the status
bar says `ANSWERING` for as long as that is true, and callers get a banner you
configure. Automatic-control rules differ by country and band; check what your
licence allows before enabling it. Discovery and probing
listen only — nothing in the scan will key your rig.

Text arriving from a remote node is treated as untrusted and stripped of
terminal escape sequences before it is displayed. A corrupt frame off a noisy
channel produces the same bytes as a malicious one, and neither should be able
to repaint your screen in the middle of a net.

## Status

Version 0.1. The AX.25 stack, the KISS transports, the monitor, the heard list
and APRS decoding are implemented and tested. VARA, Mercury and BLE TNCs are
not yet verified against hardware. See [docs/ROADMAP.md](docs/ROADMAP.md) for
what is open and [docs/CHANGELOG.md](docs/CHANGELOG.md) for what has changed.

Bug reports are much more useful with `kissterm --doctor` output attached.

## Development

[AGENTS.md](AGENTS.md) is the design document — read it before changing
anything. Each package also has its own short contract file
(`kissterm/ax25/AGENTS.md`, `kissterm/transport/AGENTS.md`, and so on) so a
single-file change does not require reading the whole repo.

```bash
.venv/bin/pip install -e ".[dev]"
git config core.hooksPath hooks     # once per clone: version bump + dep resync
.venv/bin/python -m pytest -q
```

The AX.25 stack is tested against a software loopback with injectable frame
loss (`tests/loopback.py`), so the link layer — including retransmission and
timer recovery — is exercised without a radio.

## License

MIT. See [LICENSE](LICENSE).

Portions of this project were developed with AI assistance (Claude).

## Author

Brad Brown Jr — [github.com/bradbrownjr](https://github.com/bradbrownjr)
