"""Update check and upgrade, against the GitHub repository kissterm installs from.

Why `main` and not releases. kissterm is installed with
``pipx install git+https://github.com/bradbrownjr/kissterm`` (or ``uv tool
install``), not from PyPI, and `hooks/pre-commit` bumps the patch version on
every commit -- so every commit on `main` is a version, and `main` is what
`pipx upgrade` / `uv tool upgrade` would fetch. Checking anything else (tags,
releases) would announce versions the upgrade command cannot get, or miss ones
it can.

Why one raw file. The check reads `kissterm/__init__.py` from
raw.githubusercontent.com and parses `__version__`: one small anonymous
request, no API token, and none of the GitHub API's 60-an-hour anonymous rate
limit that a club's shared NAT would hit.

What it never does:

- **Block startup or a live link.** The app runs the check in a thread worker
  after the first screen is up, at most once a day (`due`), and every
  failure -- no network, a timeout, a page that is not Python -- returns None
  and is logged at DEBUG. A radio-room laptop with no Internet is the normal
  case, not an error.
- **Touch the radio.** Nothing here imports a transport or the transmit gate;
  update traffic is Internet only.
- **Upgrade on its own.** Swapping a program's files while it holds an AX.25
  link is how a link dies mid-transfer, and this is software that can key a
  transmitter. The operator chooses "Update now", the app refuses while a
  link is up (`KissTermApp._update_blocker`), the exact command is shown
  first, and kissterm asks for a restart rather than re-executing itself.
- **Edit a source checkout.** An editable install is a working tree someone
  is developing in; it gets told to ``git pull``, never has it run for them.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Callable

from . import __version__

log = logging.getLogger(__name__)

REPO_URL = "https://github.com/bradbrownjr/kissterm"
#: What `pipx install` / `uv tool install` was given; also the manual hint.
INSTALL_SPEC = f"git+{REPO_URL}"
VERSION_URL = (
    "https://raw.githubusercontent.com/bradbrownjr/kissterm/main/kissterm/__init__.py"
)
#: Seconds between automatic checks. "Check for updates" in the menu ignores it.
CHECK_INTERVAL = 24 * 60 * 60
#: Short: the worker holds a thread, and a radio room's flaky link should
#: give up quickly rather than leave a check hanging for the whole session.
FETCH_TIMEOUT = 8.0

_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([0-9]+(?:\.[0-9]+)*)["']""", re.M)


def parse_version(text: str) -> tuple[int, ...] | None:
    """`"0.1.345"` -> `(0, 1, 345)`; None for anything else.

    Plain integers only: the pre-commit hook writes nothing else, and
    anything fancier is not a version this check knows how to order.
    """
    parts = text.strip().split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(latest: str, current: str = __version__) -> bool:
    """True only when both parse and `latest` is strictly ahead.

    A local checkout with commits not yet pushed is *ahead* of `main`; that
    is not an update and must not be offered as one.
    """
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def extract_version(source: str) -> str | None:
    """The `__version__` string from the text of `kissterm/__init__.py`."""
    match = _VERSION_RE.search(source)
    return match.group(1) if match else None


def fetch_latest(
    url: str = VERSION_URL,
    timeout: float = FETCH_TIMEOUT,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> str | None:
    """The version on `main`, or None if it could not be learned.

    Never raises: called from a worker thread, where an exception would
    surface as a crash report for what is only "no Internet right now".
    """
    request = urllib.request.Request(url, headers={"User-Agent": f"kissterm/{__version__}"})
    try:
        with opener(request, timeout=timeout) as response:  # type: ignore[operator]
            body = response.read(64 * 1024)
        return extract_version(body.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 -- any failure means "unknown"
        log.debug("update check failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Throttle: one automatic check a day, remembered across launches
# ---------------------------------------------------------------------------
def _read_stamp(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def due(path: Path, now: float | None = None, interval: float = CHECK_INTERVAL) -> bool:
    """True when the last automatic check is older than `interval`.

    A stamp from the future (a clock that was wrong) counts as due, or a
    bad clock once would silence the check for however far it was off.
    """
    now = time.time() if now is None else now
    checked = _read_stamp(path).get("checked")
    if not isinstance(checked, (int, float)) or checked > now:
        return True
    return now - checked >= interval


def cached_latest(path: Path) -> str | None:
    """The version the last successful check found, without asking again.

    So a launch inside the 24 hours still mentions an update found earlier
    in the day, instead of going quiet until tomorrow.
    """
    latest = _read_stamp(path).get("latest")
    return latest if isinstance(latest, str) and parse_version(latest) else None


def record_check(path: Path, latest: str | None, now: float | None = None) -> None:
    """Remember when we asked and what we heard. A failed check still counts
    as asked, so a station without Internet tries once a day, not every
    launch; `latest` keeps the last version actually learned."""
    data = _read_stamp(path)
    data["checked"] = time.time() if now is None else now
    if latest is not None:
        data["latest"] = latest
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError as exc:
        log.debug("could not record update check: %s", exc)


# ---------------------------------------------------------------------------
# How this copy was installed, and so how to upgrade it
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InstallMethod:
    #: "pipx" | "uv" | "source" | "other"
    kind: str
    #: The command "Update now" runs; None when kissterm should not run one.
    command: tuple[str, ...] | None
    #: One sentence for the operator: what will run, or what to do instead.
    advice: str


def _direct_url(dist_name: str = "kissterm") -> dict:
    """PEP 610's `direct_url.json`: how pip/uv recorded the install source."""
    try:
        text = metadata.distribution(dist_name).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return {}
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def detect_install(
    prefix: str | Path | None = None,
    direct_url: dict | None = None,
    which: Callable[[str], str | None] = shutil.which,
    package_dir: str | Path | None = None,
) -> InstallMethod:
    """Work out how this copy was installed.

    The environment's own marker files decide it, not path guessing: pipx
    writes `pipx_metadata.json` into each venv it manages, and uv writes
    `uv-receipt.toml` into each tool environment. An editable install says
    so in PEP 610's `direct_url.json`, and that check comes first: a source
    checkout is someone's working tree, whatever environment it sits in.
    A `.git` beside the package counts too, because the metadata is not
    always what this process runs: run from the repository, Python finds
    the checkout's own `kissterm.egg-info` first, and an editable install's
    dist-info keeps the version it was installed at, not the one checked out.
    """
    root = Path(sys.prefix if prefix is None else prefix)
    info = _direct_url() if direct_url is None else direct_url
    tree = Path(__file__).resolve().parent.parent if package_dir is None else Path(package_dir)
    if (info.get("dir_info") or {}).get("editable") or (tree / ".git").exists():
        where = str(info.get("url", "")).removeprefix("file://") or str(tree)
        return InstallMethod(
            "source", None,
            f"This is a source checkout ({where}); update it with git pull there.",
        )
    if (root / "pipx_metadata.json").exists():
        exe = which("pipx")
        if exe:
            return InstallMethod("pipx", (exe, "upgrade", "kissterm"), "pipx upgrade kissterm")
        return InstallMethod("pipx", None, "Installed by pipx, but pipx is not on PATH; run pipx upgrade kissterm.")
    if (root / "uv-receipt.toml").exists():
        exe = which("uv")
        # UNVERIFIED: that `uv tool upgrade` re-fetches a git-sourced tool's
        # branch rather than keeping the commit it first resolved. uv's
        # documentation says upgrade respects the original requirement; the
        # result is checked after the run (`installed_version`), so a no-op
        # upgrade is reported as one rather than as success.
        if exe:
            return InstallMethod("uv", (exe, "tool", "upgrade", "kissterm"), "uv tool upgrade kissterm")
        return InstallMethod("uv", None, "Installed by uv, but uv is not on PATH; run uv tool upgrade kissterm.")
    return InstallMethod(
        "other", None,
        f'Upgrade it the way it was installed, e.g. pip install --upgrade "{INSTALL_SPEC}".',
    )


def installed_version(dist_name: str = "kissterm") -> str | None:
    """The version now on disk, which after an upgrade differs from the
    `__version__` this running process imported."""
    try:
        return metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return None


@dataclass(frozen=True)
class UpgradeResult:
    ok: bool
    #: The version on disk afterwards, when it could be read.
    version: str | None
    #: The command's combined output, for the terminal and the log.
    output: str


def run_upgrade(
    method: InstallMethod,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeout: float = 600.0,
) -> UpgradeResult:
    """Run `method.command`. Blocking: call it from a worker thread.

    `ok` means the command succeeded *and* the installed version moved; a
    tool that exits 0 having changed nothing is not an update.
    """
    if method.command is None:
        return UpgradeResult(False, None, method.advice)
    before = installed_version()
    try:
        proc = runner(
            list(method.command),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return UpgradeResult(False, before, str(exc))
    output = "\n".join(s for s in (proc.stdout, proc.stderr) if s).strip()
    after = installed_version()
    moved = after is not None and after != before
    return UpgradeResult(proc.returncode == 0 and moved, after, output)
