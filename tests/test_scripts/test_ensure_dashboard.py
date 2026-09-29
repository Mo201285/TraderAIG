"""The dashboard supervisor must be idempotent and must never serve a blank page.

A Control Plane surface that answers 200 with an empty bundle looks identical to
a working one in a health check, so these tests pin the two cases that matter:
it recognises a live server, and it refuses to start one over a missing build.
"""

import pytest

import scripts.ensure_dashboard as ed


@pytest.fixture()
def log_path(tmp_path):
    return tmp_path / "dashboard_boot.log"


def test_serving_probe_asks_for_the_real_document(monkeypatch):
    """A bound socket is not a served dashboard: probe the actual page."""
    seen = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url, timeout=None):
        seen["url"] = url
        return _Response()

    monkeypatch.setattr(ed.urllib.request, "urlopen", fake_urlopen)
    assert ed.dashboard_serving(port=8443) is True
    assert seen["url"] == "http://127.0.0.1:8443/"


def test_serving_probe_survives_a_mis_mounted_bundle(monkeypatch):
    """A 404 is still a LIVE server - starting a second one helps nobody."""
    import urllib.error

    def fake_urlopen(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(ed.urllib.request, "urlopen", fake_urlopen)
    assert ed.dashboard_serving(port=8443) is True


def test_serving_probe_reports_a_dead_server(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(ed.urllib.request, "urlopen", fake_urlopen)
    assert ed.dashboard_serving(port=8443) is False


def test_main_leaves_a_live_dashboard_alone(monkeypatch, log_path):
    """A scheduled task runs this forever; a second server is the failure."""
    started = []
    monkeypatch.setattr(ed, "dashboard_serving", lambda **k: True)
    monkeypatch.setattr(ed, "start_dashboard", lambda **k: started.append(1))
    assert ed.main(["--log", str(log_path)]) == 0
    assert started == []


def test_main_refuses_to_serve_a_missing_build(monkeypatch, log_path, tmp_path):
    """Blank page beats no page: exit 3 and say what to run, start nothing."""
    started = []
    monkeypatch.setattr(ed, "dashboard_serving", lambda **k: False)
    monkeypatch.setattr(ed, "build_ready", lambda: False)
    monkeypatch.setattr(ed, "start_dashboard", lambda **k: started.append(1))
    assert ed.main(["--log", str(log_path)]) == 3
    assert started == []
    assert "build" in log_path.read_text(encoding="utf-8").lower()


def test_main_starts_and_waits_for_the_new_server(monkeypatch, log_path):
    checks = {"n": 0}

    def fake_serving(**kwargs):
        checks["n"] += 1
        return checks["n"] > 1

    monkeypatch.setattr(ed, "dashboard_serving", fake_serving)
    monkeypatch.setattr(ed, "build_ready", lambda: True)
    monkeypatch.setattr(ed, "start_dashboard", lambda **k: 4242)
    assert ed.main(["--log", str(log_path), "--wait", "5"]) == 1
    assert "serving" in log_path.read_text(encoding="utf-8")


def test_main_reports_a_server_that_never_came_up(monkeypatch, log_path):
    monkeypatch.setattr(ed, "dashboard_serving", lambda **k: False)
    monkeypatch.setattr(ed, "build_ready", lambda: True)
    monkeypatch.setattr(ed, "start_dashboard", lambda **k: 4242)
    assert ed.main(["--log", str(log_path), "--wait", "0"]) == 2


def test_operator_console_starts_the_same_server(monkeypatch):
    """`tradraig start dash` and this script must not be two different servers.

    Same argument vector, same working directory, same log name - otherwise a
    3am operator is debugging which of the two is actually listening.
    """
    import tools.tradraig as tc

    calls = []

    def fake_start(cmd, cwd, log_name, extra_env=None):
        calls.append((cmd, cwd, log_name))
        return 1

    monkeypatch.setattr(tc, "_start_detached", fake_start)
    args = type("A", (), {"target": "dash"})()
    assert tc.cmd_start(args) == 0
    assert ed.start_dashboard(port=tc.DASH_PORT) == 1

    assert len(calls) == 2
    (cmd_a, cwd_a, log_a), (cmd_b, cwd_b, log_b) = calls
    assert cmd_a == cmd_b
    assert cwd_a == cwd_b == str(ed.DASH_DIR)
    assert log_a == log_b
    # the verified build, not the dev server with HMR left running
    assert "preview" in cmd_a
    assert "run" not in cmd_a and "dev" not in cmd_a
    assert "--strictPort" in cmd_a
    assert str(tc.DASH_PORT) in cmd_a
