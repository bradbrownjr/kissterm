"""kissterm -- a terminal for KISS TNCs, packet nodes, and HF modems.

kissterm brings its own AX.25 connected-mode implementation (see
`kissterm.ax25.session`) rather than relying on an operating-system AX.25
stack. That is what lets it talk to a KISS TNC over a serial cable, a Bluetooth
link, or a TCP socket on another machine, unprivileged, on any platform --
and it is the capability the existing Linux packet terminals do not have.

This file must exist and must define `__version__`. It is the source of truth
that `pyproject.toml` and `scripts/bump_version.py` are kept in lockstep with,
and `kissterm.ui.app` imports it for the status bar. Deleting it turns the
package into an implicit namespace package, at which point `from kissterm
import __version__` fails with a confusing "unknown location" ImportError --
this has already happened once.
"""

__version__ = "0.1.18"

__all__ = ["__version__"]
