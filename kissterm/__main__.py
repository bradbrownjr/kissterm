"""Command-line entry point: argument handling, setup, and app launch.

Everything that has to talk to the operator *before* the TUI exists lives here
-- discovery, the first-run wizard, `--doctor` -- and it is all plain stdout on
purpose. A user whose terminal, config, or serial permissions are broken is
exactly the user who cannot get a Textual app on screen to be told about it, so
the diagnostics must never depend on the thing being diagnosed.

The first-run wizard is the feature that separates kissterm from the terminals
it replaces. linpac assumes you have already configured a kernel AX.25 stack;
EasyTerm assumes you know which COM port your TNC is on. kissterm looks: it
enumerates serial ports, sweeps the LAN for the well-known KISS/AGW/VARA ports,
lists paired Bluetooth TNCs, ranks what it found, and asks the operator to pick
one. Getting on the air should not require reading a manual first.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kissterm",
        description="A terminal for KISS TNCs, packet nodes, and HF modems.",
        epilog="See SETUP.md, or run 'kissterm --doctor' if something is wrong.",
    )
    parser.add_argument("--version", action="version", version=f"kissterm {__version__}")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="run diagnostics and exit (paste the output into a bug report)",
    )
    parser.add_argument(
        "--callsign",
        metavar="CALL",
        help="set your callsign and exit, e.g. --callsign W1AW-1 (no wizard)",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="re-run the first-run wizard even if a config already exists",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="scan for TNCs and modems, print what was found, and exit",
    )
    parser.add_argument(
        "--transport",
        metavar="NAME",
        help="open this configured transport instead of the saved default",
    )
    parser.add_argument(
        "--connect",
        metavar="CALL",
        help="connect to this station once the app is up, e.g. WS1EC-7",
    )
    parser.add_argument(
        "--no-discover",
        action="store_true",
        help="skip the LAN sweep on first run (serial and Bluetooth only)",
    )
    parser.add_argument(
        "--log-level",
        default="warning",
        choices=["debug", "info", "warning", "error"],
        help="file log verbosity (default: warning)",
    )
    return parser


def _setup_logging(level: str) -> None:
    from .config import log_path

    try:
        # log_path() is a DIRECTORY, not a file. Treating it as a file creates
        # a zero-byte regular file where the log directory should be, which
        # then makes every later mkdir fail with EEXIST -- and `--doctor`
        # reports the directory as unwritable, which is true but baffling.
        directory = log_path()
        directory.mkdir(parents=True, exist_ok=True)
        # Root stays at WARNING and only the `kissterm` tree gets the
        # requested level. `--log-level debug` is a request to see what THIS
        # program did on the air; letting it also uncork asyncio's and
        # Textual's debug streams buries the twenty frames that matter under
        # thousands of lines about selector events, which is the difference
        # between a log an operator will read and one they will not.
        logging.basicConfig(
            filename=str(directory / "kissterm.log"),
            level=logging.WARNING,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        )
        logging.getLogger("kissterm").setLevel(getattr(logging, level.upper()))
    except OSError:
        # An unwritable log directory must never stop the app from running --
        # the operator can still use the radio without a log file.
        logging.basicConfig(level=logging.CRITICAL)


# ---------------------------------------------------------------------------
# Discovery / wizard
# ---------------------------------------------------------------------------
def _print_devices(devices) -> None:
    if not devices:
        print("Nothing found.")
        print()
        print("That is not proof there is no TNC: a silent KISS TNC looks")
        print("exactly like a wrong serial port until a frame arrives off the")
        print("air. If you know the device or the host, add it to config.toml")
        print("by hand -- see config.toml.example.")
        return
    width = max(len(d.label) for d in devices)
    for i, dev in enumerate(devices, 1):
        bar = "*" * round(dev.confidence * 5)
        print(f"  {i:2d}. {dev.label:<{width}}  {dev.detail}")
        if dev.note:
            print(f"      {' ' * width}  {dev.note}")
        print(f"      {' ' * width}  confidence {bar or '-'}")


async def _run_discovery(no_network: bool):
    from . import discovery

    print("Looking for TNCs and modems...")
    if not no_network:
        print("  (sweeping the local network -- this takes a few seconds)")
    return await discovery.discover_all(deadline=3.0 if no_network else 16.0)


def _prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(1)
    return answer or default


def _wizard_pick_theme(config) -> None:
    """Offer the theme catalog. Enter alone keeps whatever `config` already
    has -- `Config.theme`'s own default (Tokyo Night) on a fresh install, or
    an existing choice if the wizard is being re-run with `--setup`.

    This mirrors the Settings tab's dropdown (`kissterm.ui.settings_schema`)
    exactly, from the same catalog (`kissterm.ui.themes`), so there is one
    list of themes in the whole app, not a wizard-specific copy that could
    drift out of sync with what Settings actually offers.
    """
    from .ui import themes

    print()
    print("Pick a theme (Enter to keep the current one):")
    catalog = themes.choices()
    current_index = next(
        (i for i, (_label, tid) in enumerate(catalog) if tid == config.theme), None
    )
    for i, (label, _theme_id) in enumerate(catalog, 1):
        marker = " (current)" if i - 1 == current_index else ""
        print(f"  {i:2d}. {label}{marker}")
    default = str(current_index + 1) if current_index is not None else ""
    choice = _prompt("Theme number", default)
    if not choice:
        return
    try:
        config.theme = catalog[int(choice) - 1][1]
    except (ValueError, IndexError):
        print("  Not a listed number; keeping the current theme.")


def _wizard_save_transport(config, dev) -> None:
    """Write a discovered device into the config -- but prove it first.

    The wizard used to write whatever `dev.config` held and print "Saved".
    That is how kissterm shipped a release whose very first run wrote a
    valid-looking config file and then failed to open it, with a TypeError
    out of a constructor, every time and for every transport kind. The wizard
    is the last point where the operator is still sitting there and can be
    told something is wrong, so it now builds the transport it is about to
    save and refuses to claim success if that fails.

    Construction only -- nothing is opened. Opening needs the hardware
    powered on and reachable, which does not belong in the middle of a setup
    prompt; that is what `--doctor` is for.
    """
    if not dev.config.get("kind"):
        # Discovery found it but cannot configure it from a probe -- a VARA
        # modem, whose entry needs a callsign and two ports. See
        # discovery._WELL_KNOWN_PORTS.
        print(f"  {dev.label} cannot be set up automatically.")
        if dev.note:
            print(f"  {dev.note}")
        print("  See config.toml.example for a worked [[transports]] entry.")
        return

    entry = dict(dev.config)
    entry.setdefault("name", dev.label)

    from .transport import build_transport

    try:
        build_transport(entry)
    except Exception as exc:  # noqa: BLE001 -- reporting this IS the feature
        print(f"  Could not use {dev.label}: {exc}")
        print("  Nothing was saved. Please report this -- a discovered device")
        print("  should always produce a usable config entry.")
        return

    config.transports = [t for t in config.transports if t.get("name") != entry["name"]]
    config.transports.append(entry)
    config.active_transport = entry["name"]
    print(f"  Saved transport '{entry['name']}'.")


async def _run_wizard(config, no_network: bool) -> bool:
    """Interactive first-run setup. Returns False if the operator bailed out."""
    from .ax25.address import AX25Address, AX25AddressError
    from .config import config_path, save_config

    print()
    print(f"kissterm {__version__} -- first-run setup")
    print("=" * 46)
    print()

    while True:
        call = _prompt("Your callsign (with SSID, e.g. N1ABC-1)", config.mycall)
        try:
            AX25Address.parse(call)
        except AX25AddressError as exc:
            print(f"  {exc}")
            continue
        config.mycall = call.upper()
        break

    _wizard_pick_theme(config)

    devices = await _run_discovery(no_network)
    print()
    if devices:
        print("Found:")
        _print_devices(devices)
        print()
        choice = _prompt("Use which one? (number, or 'skip')", "1")
        if choice.lower() not in ("skip", "s", ""):
            try:
                dev = devices[int(choice) - 1]
            except (ValueError, IndexError):
                print("  Not a listed number; skipping transport setup.")
            else:
                _wizard_save_transport(config, dev)
    else:
        _print_devices(devices)

    save_config(config)
    print()
    print(f"Config written to {config_path()}")
    print("Run 'kissterm --doctor' any time to check things over.")
    print()
    return True


# ---------------------------------------------------------------------------
# App launch
# ---------------------------------------------------------------------------
def _select_transport_entry(config, name: str | None) -> dict | None:
    if not config.transports:
        return None
    wanted = name or config.active_transport
    if wanted:
        for entry in config.transports:
            if entry.get("name") == wanted:
                return entry
        print(f"No transport named {wanted!r}; using the first configured one.")
    return config.transports[0]


async def _amain(args) -> int:
    from .config import load_config, save_config

    config = load_config()
    for warning in config.warnings:
        print(f"config: {warning}", file=sys.stderr)

    if args.callsign:
        # A one-shot so changing callsign never means sitting through the
        # wizard's LAN sweep. Operators change SSID often -- portable, a -1
        # mailbox, a club call for an event -- and re-running first-run setup
        # to edit one string is the wrong shape for that.
        from .ax25.address import AX25Address, AX25AddressError

        try:
            AX25Address.parse(args.callsign)
        except AX25AddressError as exc:
            print(f"Not a valid callsign: {exc}", file=sys.stderr)
            return 2
        config.mycall = args.callsign.upper()
        save_config(config)
        from .config import config_path

        print(f"Callsign set to {config.mycall} in {config_path()}")
        return 0

    if args.discover:
        _print_devices(await _run_discovery(args.no_discover))
        return 0

    if args.doctor:
        from .doctor import format_report, run_diagnostics

        print(format_report(await run_diagnostics(config)))
        return 0

    if args.setup or not config.mycall:
        if not await _run_wizard(config, args.no_discover):
            return 1
        config = load_config()

    entry = _select_transport_entry(config, args.transport)
    if entry is None:
        print("No transport is configured. Run 'kissterm --setup'.", file=sys.stderr)
        return 2

    from .ax25 import AX25Address, AX25Station, LinkParams
    from .app import KissTermApp
    from .transport import build_transport
    from .transport.base import FrameTransport, TransportError

    try:
        transport = build_transport(entry)
        await transport.open()
    except (TransportError, Exception) as exc:  # noqa: BLE001 - reported, not raised
        print(f"Could not open transport {entry.get('name')!r}: {exc}", file=sys.stderr)
        print("Run 'kissterm --doctor' for a full check.", file=sys.stderr)
        return 3

    station = None
    if isinstance(transport, FrameTransport):
        station = AX25Station(
            AX25Address.parse(config.mycall),
            transport,
            LinkParams(
                paclen=config.paclen,
                window=config.window,
                modulo=config.modulo,
                retries=config.retries,
                connect_retries=config.connect_retries,
                t1=config.t1,
                t2=config.t2,
                t3=config.t3,
            ),
            aliases=tuple(AX25Address.parse(a) for a in config.mycall_aliases),
            accept_incoming=config.accept_incoming,
        )

    # A log that does not say what it is a log OF is guesswork later. This
    # one line is what makes a file the operator mails in reconstructible:
    # which build, which radio path, whose callsign.
    logging.getLogger("kissterm").info(
        "kissterm %s starting: mycall=%s transport=%s",
        __version__,
        getattr(config, "mycall", "") or "(unset)",
        transport.info.detail or transport.info.kind,
    )
    app = KissTermApp(config, station)
    try:
        await app.run_async()
    finally:
        if station is not None:
            await station.disconnect_all()
            station.close()
        await transport.close()
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    _setup_logging(args.log_level)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
