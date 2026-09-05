"""The transport package: tier ABCs, `Session`, and a config-driven factory.

`build_transport` is the one place that knows how a config dict turns into a
concrete transport instance, so the setup wizard and any config-file loader
share exactly one mapping from ``kind`` string to class -- add a transport
here once and every caller gets it, instead of each call site growing its own
copy of the dispatch table that drifts out of sync with the others.

Every concrete transport module is imported *inside* `build_transport`, not
at the top of this file. Several of them depend on optional third-party
packages (`pyserial`/`pyserial-asyncio-fast` for serial, nothing extra for
TCP/AGWPE, platform-specific socket families for Bluetooth and kernel AX.25)
or are only meaningful on Linux. If this package imported all of them eagerly,
`import kissterm.transport` -- which plenty of code needs just to reach
`Transport`/`Session`/`TransportError` -- would fail on any machine missing
one optional dependency, even for a user who only ever wants plain TCP KISS.
Lazy imports keep the base ABCs importable everywhere and push the "is this
optional dependency installed" question to the moment a transport of that
specific kind is actually requested.
"""

from __future__ import annotations

from typing import Any

from .base import (
    FrameHandler,
    FrameTransport,
    Session,
    SessionState,
    SessionTransport,
    Transport,
    TransportError,
    TransportInfo,
    TransportState,
)

__all__ = [
    "FrameHandler",
    "FrameTransport",
    "Session",
    "SessionState",
    "SessionTransport",
    "Transport",
    "TransportError",
    "TransportInfo",
    "TransportState",
    "build_transport",
]

#: Keys that describe the config ENTRY rather than the transport, and so must
#: never reach a constructor.
#:
#: `name` is the operator's label for this entry -- what `active_transport`
#: matches on and what the status bar shows. It is not a constructor argument
#: to any transport, and forwarding it blindly is what made every
#: wizard-written config fail to open with "unexpected keyword argument
#: 'name'" -- on a first run, for every transport kind, which is as broken as
#: a program gets. Everything NOT listed here is still forwarded, so a typo in
#: a real setting still surfaces loudly as a TypeError instead of being
#: silently dropped.
_ENTRY_ONLY_KEYS = frozenset({"kind", "name"})

#: Config ``kind`` values `build_transport` accepts, kept as a tuple (rather
#: than derived from a dict of already-imported classes) precisely so this
#: list can exist without importing anything optional.
_VALID_KINDS = (
    "serial",
    "tcp",
    "agwpe",
    "bluetooth",
    "kernel",
    "vara",
    "varafm",
    "mercury",
)


def build_transport(config: dict[str, Any]) -> Transport:
    """Build a transport from a plain config dict.

    ``config["kind"]`` selects the transport; every key except the
    entry-level ones in `_ENTRY_ONLY_KEYS` is passed through as keyword
    arguments to that transport's constructor, so the accepted keys are
    whatever each transport class's ``__init__`` declares (see that class's
    docstring). Raises `TransportError` for an unknown or missing ``kind``
    rather than letting a typo surface as a `KeyError` deep inside a dispatch
    dict.

    **This is the only way a transport is constructed from config.** Anything
    that builds one from a config entry -- the app, the wizard, `--doctor` --
    comes through here. A second dispatch table somewhere else looks harmless
    and is not: `--doctor` had one, so it picked constructor arguments by hand,
    reported every transport healthy, and validated a path the app never took
    while the app itself could not open a single one.
    """
    kind = config.get("kind")
    if kind not in _VALID_KINDS:
        raise TransportError(
            f"unknown transport kind {kind!r}; valid kinds are: "
            + ", ".join(_VALID_KINDS)
        )

    kwargs = {k: v for k, v in config.items() if k not in _ENTRY_ONLY_KEYS}
    label = config.get("name")

    if kind == "serial":
        from .serial_kiss import SerialKissTransport

        return _named(SerialKissTransport(**kwargs), label)

    if kind == "tcp":
        from .tcp_kiss import TcpKissTransport

        return _named(TcpKissTransport(**kwargs), label)

    if kind == "agwpe":
        from .agwpe import AgwpeTransport

        return _named(AgwpeTransport(**kwargs), label)

    if kind == "bluetooth":
        from .bluetooth import BluetoothKissTransport

        return _named(BluetoothKissTransport(**kwargs), label)

    if kind == "kernel":
        from .kernel_ax25 import KernelAx25Transport

        return _named(KernelAx25Transport(**kwargs), label)

    if kind == "vara":
        from .vara import VaraHfTransport

        return _named(VaraHfTransport(**kwargs), label)

    if kind == "varafm":
        from .vara import VaraFmTransport

        return _named(VaraFmTransport(**kwargs), label)

    if kind == "mercury":
        from .mercury import MercuryTransport

        return _named(MercuryTransport(**kwargs), label)

    # Unreachable: _VALID_KINDS and the branches above are kept in sync, but
    # fail loudly rather than falling through to `None` if they ever drift.
    raise AssertionError(f"transport kind {kind!r} listed as valid but not dispatched")


def _named(transport: Transport, label: str | None) -> Transport:
    """Let the config entry's `name` win over the class's derived one.

    The operator named this entry, `active_transport` matches on that name,
    and the status bar shows it -- so the transport agreeing with the config
    is what keeps "which one am I on?" answerable from one string instead of
    two that can differ.
    """
    if label:
        transport.info.name = label
    return transport
