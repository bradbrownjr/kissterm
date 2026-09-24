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

__version__ = "0.1.233"

__all__ = ["__version__"]

# --------------------------------------------------------------------------
# Turn OFF Textual's enhanced (Kitty) keyboard protocol, unless the operator
# has said otherwise.
#
# MUST happen here, before anything imports Textual. `textual.constants` reads
# this variable at IMPORT time into `DISABLE_KITTY_KEY`, so setting it later --
# in `__main__`, in `ui.app`, anywhere downstream -- does nothing at all. Same
# import-order hazard as `kissterm._isolate`, for the same reason, and it fails
# just as silently.
#
# Why kissterm wants it off. `linux_driver.py` writes `CSI > 15 u`
# (disambiguate + report-all-keys + report-associated-text) on startup. Under
# report-all-keys, Enter stops being a plain CR and becomes a bare `CSI 13 u`
# sequence carrying no text, while ordinary letters still arrive with their
# text attached. So when that protocol state goes wrong -- a terminal
# multiplexer detaching and reattaching the window, a previous program leaving
# the protocol stack pushed -- typing keeps working and Enter silently
# disappears. Measured on a real station (KC1JMH, 2026-09-22, Konsole under
# herdr): a key probe logged `b`, `y`, `e` and NO event whatsoever for Enter,
# and the send line could only be sent with the mouse. With this variable set,
# the same probe in the same tab reported
# `key='enter' character='\r' ... -> Input.Submitted fired`.
#
# It costs kissterm nothing. The enhanced protocol only buys key combinations a
# plain terminal cannot encode -- Ctrl+Shift, Ctrl+Alt, Alt -- and DESIGN.md's
# keyboard standard bans every one of them precisely because an ordinary
# terminal delivers Ctrl+Shift+X and Ctrl+X as the same byte. Nothing in the
# command catalog needs it.
#
# `setdefault`, not assignment: an operator whose terminal handles the protocol
# correctly can re-enable it with `TEXTUAL_DISABLE_KITTY_KEY=0`.
import os as _os

_os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")
del _os
