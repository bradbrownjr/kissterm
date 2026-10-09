"""What a Programs entry starts from: pure data, no process, no I/O.

A modem program (VARA, Mercury, Direwolf, a sound-card modem) is a separate
executable the operator installs. A preset fills a new Programs entry with
the path and arguments that program's own documentation gives, so the
operator picks "Mercury" instead of typing a command line.

**Every default is a starting point, not a fact about this machine.** The
operator's install may be anywhere; the form shows the path and the file
browser at the station finds the real one. `default_path` takes the platform
as a parameter (never `sys.platform` inside it) so every platform's answer
is tested on any platform.

**Provenance per field** (AGENTS.md "Record provenance"): `source` is one of
`documented` (read from the program's own README or manual, cited in
`docs/SOURCES.md`), `recalled` (known from use, not re-read) or
`unverified` (a guess; the form says so). An `unverified` path is the
first thing the operator should check.

The passing of PTT to the program (Mercury `-R`/`-A`, Direwolf `PTT RIG`)
belongs to the rig entry and M2's argument building; `args` here are the
program's own, with `{port}` and `{conf}` placeholders the supervisor fills.
"""

from __future__ import annotations

from dataclasses import dataclass

WINDOWS = "windows"
LINUX = "linux"
DARWIN = "darwin"
PLATFORMS = (WINDOWS, LINUX, DARWIN)


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    #: The transport kind that talks to it ("" for a custom program).
    transport_kind: str
    #: Candidate executables per platform, most likely first. A Windows-only
    #: program lists nothing for Linux; `runs_under_wine` says it can still
    #: run there.
    paths: dict[str, tuple[str, ...]]
    args: str = ""
    runs_under_wine: bool = False
    #: Where the Wine prefix keeps a Windows install (POSIX paths, `~` kept).
    wine_paths: tuple[str, ...] = ()
    #: documented | recalled | unverified -- of the path and arguments
    source: str = "unverified"
    #: The program reads its settings from its working folder, so the
    #: supervisor starts it in the program's own folder unless `cwd` is set.
    cwd_is_program_folder: bool = False
    note: str = ""


PRESETS: dict[str, Preset] = {
    "vara-hf": Preset(
        "vara-hf", "VARA HF", "vara",
        {WINDOWS: (r"C:\VARA\VARA.exe",)},
        runs_under_wine=True,
        wine_paths=("~/.wine/drive_c/VARA/VARA.exe",),
        source="documented",
        note="The installer's default folder, from VARA setup guides (not "
             "EA5HVK's own pages); its ports are set in VARA's Settings.",
    ),
    "vara-fm": Preset(
        "vara-fm", "VARA FM", "varafm",
        {WINDOWS: (r"C:\VARA FM\VaraFM.exe",)},
        runs_under_wine=True,
        wine_paths=("~/.wine/drive_c/VARA FM/VaraFM.exe",),
        source="documented",
        note="The installer's default folder, from VARA setup guides (not "
             "EA5HVK's own pages); its ports are set in VARA's Settings.",
    ),
    "mercury": Preset(
        "mercury", "Mercury", "mercury",
        {
            LINUX: ("/usr/bin/mercury", "/usr/local/bin/mercury"),
            WINDOWS: ("mercury.exe",),
            DARWIN: ("/Applications/Mercury",),
        },
        args="-p {port}",
        source="documented",
        note="/usr/bin from the Debian package, /usr/local/bin from make "
             "install; -p is the ARQ base port (default 8300).",
    ),
    "direwolf": Preset(
        "direwolf", "Direwolf", "tcp",
        {
            LINUX: ("/usr/bin/direwolf", "/usr/local/bin/direwolf"),
            WINDOWS: (r"C:\direwolf\direwolf.exe",),
            DARWIN: ("/usr/local/bin/direwolf",),
        },
        args="-t 0 -c {conf}",
        source="documented",
        note="Options from direwolf(1): -c file (default direwolf.conf in the "
             "working folder), -t n (0 turns colours off). The path is a guess "
             "from a package or `make install`; check it.",
    ),
    "qtsoundmodem": Preset(
        "qtsoundmodem", "QtSoundModem", "tcp",
        {
            LINUX: ("/usr/local/bin/QtSoundModem", "/usr/bin/QtSoundModem"),
            WINDOWS: (r"C:\QtSoundModem\QtSoundModem.exe",),
        },
        source="unverified",
        cwd_is_program_folder=True,
        note="Built from source (github.com/g8bpq/QtSoundModem), so no standard "
             "path. It reads QtSoundModem.ini from its working folder, so it "
             "starts in its own folder; its KISS and AGW ports are in that file.",
    ),
    "uz7ho": Preset(
        "uz7ho", "UZ7HO SoundModem", "agwpe",
        {WINDOWS: (r"C:\SoundModem\soundmodem.exe",)},
        runs_under_wine=True,
        wine_paths=("~/.wine/drive_c/SoundModem/soundmodem.exe",),
        source="unverified",
        note="Windows program; its AGWPE port is set in its own settings.",
    ),
    "custom": Preset("custom", "Another program", "", {}, source="documented"),
}


def default_path(preset: str, platform: str) -> str:
    """The first candidate path for `preset` on `platform`, "" if none.

    A program that only exists for Windows answers its Wine prefix path on
    Linux and macOS (the entry then needs `wine` set; see `needs_wine`).
    """
    entry = PRESETS.get(preset)
    if entry is None:
        return ""
    found = entry.paths.get(platform, ())
    if found:
        return found[0]
    if platform != WINDOWS and entry.runs_under_wine and entry.wine_paths:
        return entry.wine_paths[0]
    return ""


def needs_wine(preset: str, platform: str) -> bool:
    """True when `preset` has no native build for `platform` and can run
    under Wine there. The form shows its `wine` choice only then."""
    entry = PRESETS.get(preset)
    return bool(
        entry and platform != WINDOWS and not entry.paths.get(platform) and entry.runs_under_wine
    )


def default_args(preset: str) -> str:
    entry = PRESETS.get(preset)
    return entry.args if entry else ""
