"""Save as text on the phone and browser: a mail message or bulletin, an
APRS conversation or a Terminal tab as a .txt file on this device (operator,
2026-10-09: "export or download individual mail, bulletins, aprs messages,
and terminal output as txt files to the local system from the web UI").

**The station makes the text** (`export_text`, `core/export.py`), the
same file the terminal's X saves, sanitized there; this only hands it to
the device. In a browser that is a download into its Downloads folder; the
desktop client opens a Save dialog. Nothing is written on the station and
nothing is sent.

One `FilePicker` per page, kept on the app: a service added twice is two
pickers, and a picker is only useful once it is in `page.services`.
"""

from __future__ import annotations

import flet as ft

from . import sheets


def _picker(app) -> ft.FilePicker:
    picker = getattr(app, "_save_picker", None)
    if picker is None:
        picker = ft.FilePicker()
        app.page.services.append(picker)
        app._save_picker = picker
    return picker


async def save_text(app, kind: str, ref: str = "") -> None:
    """Ask the station for `kind`/`ref` as text and save it on this device."""
    made = await app.command("export_text", kind=kind, ref=ref)
    if not made:
        return
    name, data = made["name"], made["text"].encode("utf-8")
    try:
        where = await _picker(app).save_file(dialog_title="Save as text", file_name=name,
                                             src_bytes=data)
    except Exception as exc:  # a picker that cannot save on this platform
        sheets.snack(app.page, f"Could not save {name}: {exc}", error=True)
        return
    if app.page.web:
        sheets.snack(app.page, f"Downloaded {name}")
    elif where:
        sheets.snack(app.page, f"Saved {where}")
