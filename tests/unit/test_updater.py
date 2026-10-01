"""kissterm/updater.py: version ordering, the daily throttle, install
detection, and that every failure is quiet. No test here touches the network:
the fetcher and the subprocess runner are passed in."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import io  # noqa: E402
import subprocess  # noqa: E402

from kissterm import updater  # noqa: E402


def test_versions_compare_numerically_not_as_text():
    assert updater.is_newer("0.1.346", "0.1.345")
    assert updater.is_newer("0.1.1000", "0.1.999")
    assert updater.is_newer("0.2.0", "0.1.999")
    assert not updater.is_newer("0.1.345", "0.1.345")
    # A local checkout ahead of main is not offered an "update" backwards.
    assert not updater.is_newer("0.1.340", "0.1.345")
    assert not updater.is_newer("garbage", "0.1.345")
    assert not updater.is_newer("0.1.346", "")


def test_extract_version_from_init_source():
    src = '"""doc"""\n\nimport x\n__version__ = "0.1.400"\n'
    assert updater.extract_version(src) == "0.1.400"
    assert updater.extract_version("<html>rate limited</html>") is None


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_reads_the_version_and_never_raises():
    ok = lambda req, timeout: _Response(b'__version__ = "9.9.9"\n')  # noqa: E731
    assert updater.fetch_latest(opener=ok) == "9.9.9"

    def offline(req, timeout):
        raise OSError("Network is unreachable")

    assert updater.fetch_latest(opener=offline) is None
    not_python = lambda req, timeout: _Response(b"<html>404</html>")  # noqa: E731
    assert updater.fetch_latest(opener=not_python) is None


def test_the_launch_check_runs_once_a_day(tmp_path):
    stamp = tmp_path / "update-check.json"
    assert updater.due(stamp, now=1000.0), "never checked: due"
    updater.record_check(stamp, "0.1.500", now=1000.0)
    assert not updater.due(stamp, now=1000.0 + 3600)
    assert updater.due(stamp, now=1000.0 + updater.CHECK_INTERVAL)
    assert updater.cached_latest(stamp) == "0.1.500"
    # A failed check counts as asked but keeps the last version learned.
    updater.record_check(stamp, None, now=2000.0)
    assert not updater.due(stamp, now=2001.0)
    assert updater.cached_latest(stamp) == "0.1.500"
    # A stamp from the future (a clock that was wrong) does not silence it.
    assert updater.due(stamp, now=10.0)
    stamp.write_text("not json")
    assert updater.due(stamp) and updater.cached_latest(stamp) is None


def test_install_detection(tmp_path, monkeypatch):
    which = {"pipx": "/usr/bin/pipx", "uv": "/usr/bin/uv"}.get
    # Every case below but the last runs as an installed copy, not this
    # repository's own checkout (which has a .git beside the package).
    installed = tmp_path / "site-packages"
    installed.mkdir()
    real = updater.detect_install
    monkeypatch.setattr(
        updater, "detect_install",
        lambda *a, **kw: real(*a, **{"package_dir": installed, **kw}),
    )
    pipx_env = tmp_path / "pipx"
    pipx_env.mkdir()
    (pipx_env / "pipx_metadata.json").write_text("{}")
    m = updater.detect_install(pipx_env, direct_url={"url": "https://github.com/x"}, which=which)
    assert m.kind == "pipx" and m.command == ("/usr/bin/pipx", "upgrade", "kissterm")

    uv_env = tmp_path / "uv"
    uv_env.mkdir()
    (uv_env / "uv-receipt.toml").write_text("")
    m = updater.detect_install(uv_env, direct_url={}, which=which)
    assert m.kind == "uv" and m.command == ("/usr/bin/uv", "tool", "upgrade", "kissterm")

    # pipx-managed, but pipx gone from PATH: advice, no command.
    m = updater.detect_install(pipx_env, direct_url={}, which=lambda _: None)
    assert m.kind == "pipx" and m.command is None

    # A source checkout is never upgraded for its owner, even inside a
    # pipx-looking environment.
    editable = {"url": "file:///home/op/kissterm", "dir_info": {"editable": True}}
    m = updater.detect_install(pipx_env, direct_url=editable, which=which)
    assert m.kind == "source" and m.command is None and "git pull" in m.advice

    m = updater.detect_install(tmp_path, direct_url={}, which=which)
    assert m.kind == "other" and m.command is None

    # A git working tree is a checkout even when the metadata does not say
    # editable (run from the repository, the egg-info there wins).
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    m = updater.detect_install(pipx_env, direct_url={}, which=which, package_dir=checkout)
    assert m.kind == "source" and m.command is None


def test_an_upgrade_that_changes_nothing_is_not_success(monkeypatch):
    method = updater.InstallMethod("pipx", ("pipx", "upgrade", "kissterm"), "pipx upgrade kissterm")
    versions = iter(["0.1.345", "0.1.345"])
    monkeypatch.setattr(updater, "installed_version", lambda: next(versions))
    ran = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "already latest", "")  # noqa: E731
    result = updater.run_upgrade(method, runner=ran)
    assert not result.ok and "already latest" in result.output

    versions = iter(["0.1.345", "0.1.360"])
    result = updater.run_upgrade(method, runner=ran)
    assert result.ok and result.version == "0.1.360"

    def missing(cmd, **kw):
        raise FileNotFoundError("pipx")

    versions = iter(["0.1.345", "0.1.345"])
    assert not updater.run_upgrade(method, runner=missing).ok
    # No command: nothing runs, the advice comes back.
    advice = updater.InstallMethod("other", None, "do it yourself")
    assert updater.run_upgrade(advice, runner=missing).output == "do it yourself"
