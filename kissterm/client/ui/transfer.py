"""File transfers (the terminal's S on the Files tab, and its File transfer
dialog): send a file from Files over a connected session, or start receiving
one, by YAPP or AutoBIN.

Both ask first and say what they do, because both put frames on the air
(**the confirm button is the commitment**, DESIGN.md "A swipe never
transmits"). The station refuses a session that is not connected or cannot
carry binary (an SSH one), and a session already running a transfer; the
transfer runs on the station and its outcome arrives as a notice
(`transfer_start` answers at once). A phone's own files are not uploaded:
a file to send is one already in the station's Files.
"""

from __future__ import annotations

import flet as ft

from . import sheets

PROTOCOLS = (("YAPP", "yapp"), ("AutoBIN", "autobin"))


def _live_sessions(app) -> list:
    return [s for s in app.state.sessions.values() if s.connected]


def ask(app, *, ref: str = "", name: str = "", current: str | None = None) -> None:
    """The sheet for sending the file `ref` (named `name`) or, with no
    `ref`, receiving one, over a connected session."""
    sessions = _live_sessions(app)
    receiving = not ref
    title = "Receive a file" if receiving else f"Send {name}"
    if not sessions:
        sheets.snack(app.page, "Connect before starting a file transfer.", error=True)
        return
    pick = ft.Dropdown(
        label="Over session", dense=True,
        value=current if current in {s.key for s in sessions} else sessions[0].key,
        options=[ft.DropdownOption(key=s.key, text=s.title) for s in sessions])
    protocol = ft.Dropdown(label="Protocol", value="yapp", dense=True,
                           options=[ft.DropdownOption(key=v, text=t) for t, v in PROTOCOLS])

    async def go() -> None:
        args = {"key": pick.value, "protocol": protocol.value or "yapp",
                "mode": "download" if receiving else "upload"}
        if not receiving:
            args["ref"] = ref
        if await app.command("transfer_start", **args):
            sheets.snack(app.page, "Receiving started: waiting for the sender."
                         if receiving else f"Sending {name}: progress shows in the notices.")

    sheets.form(
        app.page, title, [pick, protocol], "Start" if receiving else "Send", go,
        detail=("Waits on the far end to send a file, as AutoBIN needs, or a sender that wants "
                "the receiver started first; it is saved in Files > Downloads. A YAPP download "
                "from a BPQ BBS needs none of this: type YAPP <name> and it starts by itself. "
                if receiving else
                "Turns transmit on and sends the file over the session chosen: real airtime "
                "on a shared channel, until it is done. YAPP suits a BPQ BBS; AutoBIN other "
                "software."))
