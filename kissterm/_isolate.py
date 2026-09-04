"""Test isolation: redirect `platformdirs` before `kissterm` is ever imported.

`kissterm.config` computes `config_path()`, `log_path()`, and `state_path()`
from `platformdirs` **at import time** (see the CRITICAL SAFETY RULE in that
module's docstring), not lazily on each call. That is the right call for the
running app -- every part of it agrees on one location without threading a
path through every constructor -- but it means the *only* window in which a
test can safely redirect those paths is before `kissterm.config` (or
anything that imports it, which in practice means anything under
`kissterm`) is imported for the first time in the process. Patch
`platformdirs` after that point and it does nothing: the real paths were
already computed and are already sitting in module-level constants.

This module exists so that "patch before import" is one function call
instead of something every test file has to remember to get right in the
correct order. Usage, at the very top of a test file, before any
`import kissterm...`::

    from kissterm import _isolate
    _isolate.isolate()

    from kissterm import config  # only safe now

Do not call `isolate()` and then assume it is safe to `shutil.rmtree()` the
directory it hands back without checking, in that same process, that this
module was imported and `isolate()` was called *before* `kissterm.config`.
If some other test file, fixture, or plugin imported `kissterm.config` first
(directly or via another `kissterm` submodule), the real `platformdirs`
paths are already locked in and no amount of patching afterward will move
them -- a cleanup step that trusts otherwise is exactly how a real user's
config directory gets destroyed by what looked like a scoped test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def isolate(root: str | Path | None = None) -> Path:
    """Monkeypatch `platformdirs` to a scratch directory tree and return it.

    Call this before any `import kissterm...` (see module docstring). Safe
    to call more than once; each call creates (or reuses, if `root` is
    given) a directory and repoints `platformdirs.user_config_dir`,
    `platformdirs.user_state_dir`, and `platformdirs.user_data_dir` at
    subdirectories of it, ignoring whatever application name is asked for --
    tests do not need per-app separation, only separation from the real
    user directories.
    """
    import platformdirs

    base = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="kissterm-test-"))
    config_dir = base / "config"
    state_dir = base / "state"
    data_dir = base / "data"
    for d in (config_dir, state_dir, data_dir):
        d.mkdir(parents=True, exist_ok=True)

    platformdirs.user_config_dir = lambda *a, **k: str(config_dir)  # type: ignore[assignment]
    platformdirs.user_state_dir = lambda *a, **k: str(state_dir)  # type: ignore[assignment]
    platformdirs.user_data_dir = lambda *a, **k: str(data_dir)  # type: ignore[assignment]

    return base
