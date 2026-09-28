"""Tests for the 24/7 backend/rail bootstrap helper.

The two failure modes that must stay impossible: a second backend stealing the
port, and reporting the tier-100 rail as live when the watcher never started.
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import ensure_backend as eb  # noqa: E402


def test_backend_healthy_needs_the_endpoint_not_just_a_listener(monkeypatch):
    class _Resp:
        def __init__(self, status=200):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(eb.urllib.request, "urlopen",
                        lambda *_a, **_k: _Resp(200))
    assert eb.backend_healthy() is True

    def _refused(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(eb.urllib.request, "urlopen", _refused)
    assert eb.backend_healthy() is False


def test_wait_healthy_polls_until_the_budget_runs_out(monkeypatch):
    ticks = {"now": 0.0}
    answers = [False, False, True]

    def fake_sleep(_seconds):
        ticks["now"] += 5.0

    monkeypatch.setattr(eb, "backend_healthy", lambda **_k: answers.pop(0))
    assert eb.wait_healthy(wait=40.0, sleep=fake_sleep, clock=lambda: ticks["now"]) is True
    assert answers == []

    monkeypatch.setattr(eb, "backend_healthy", lambda **_k: False)
    assert eb.wait_healthy(wait=10.0, sleep=fake_sleep, clock=lambda: ticks["now"]) is False


def test_rail_reports_a_rejected_connect(monkeypatch):
    monkeypatch.setattr(eb, "http_post", lambda *_a, **_k: (403, {"detail": "entitlement"}))
    ok, detail = eb.start_mt5_rail()
    assert ok is False and "403" in detail


def test_rail_is_not_ok_when_the_watcher_did_not_start(monkeypatch):
    calls = []

    def fake_post(url, *_a, **_k):
        calls.append(url)
        if url.endswith("/mt5/connect"):
            return 200, {"connected": True}
        return 200, {"started": False, "status": {}}

    monkeypatch.setattr(eb, "http_post", fake_post)
    ok, detail = eb.start_mt5_rail()
    assert ok is False and "not started" in detail
    assert len(calls) == 2


def test_rail_is_ok_when_the_watcher_started(monkeypatch):
    def fake_post(url, *_a, **_k):
        if url.endswith("/mt5/connect"):
            return 200, {"connected": True}
        return 200, {"started": True, "status": {}}

    monkeypatch.setattr(eb, "http_post", fake_post)
    ok, detail = eb.start_mt5_rail(interval=7.0, symbols=["BTCUSD"])
    assert ok is True and detail == "watcher running"


def test_main_does_not_start_a_second_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(eb, "backend_healthy", lambda **_k: True)
    monkeypatch.setattr(eb, "port_listening", lambda *_a, **_k: True)
    monkeypatch.setattr(eb, "start_backend",
                        lambda **_k: pytest.fail("must not start twice"))
    assert eb.main(["--port", "8000", "--log", str(tmp_path / "b.log")]) == 0


def test_main_starts_once_and_waits_for_real_health(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(eb, "backend_healthy", lambda **_k: False)
    monkeypatch.setattr(eb, "port_listening", lambda *_a, **_k: False)
    monkeypatch.setattr(eb, "start_backend", lambda **_k: started.append(1) or 4321)
    monkeypatch.setattr(eb, "wait_healthy", lambda **_k: True)
    assert eb.main(["--log", str(tmp_path / "b.log")]) == 1
    assert started == [1]


def test_main_reports_an_unhealthy_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(eb, "backend_healthy", lambda **_k: False)
    monkeypatch.setattr(eb, "port_listening", lambda *_a, **_k: False)
    monkeypatch.setattr(eb, "start_backend", lambda **_k: 1)
    monkeypatch.setattr(eb, "wait_healthy", lambda **_k: False)
    assert eb.main(["--wait", "0", "--log", str(tmp_path / "b.log")]) == 2


def test_main_surfaces_a_blocked_rail(monkeypatch, tmp_path):
    monkeypatch.setattr(eb, "backend_healthy", lambda **_k: True)
    monkeypatch.setattr(eb, "start_mt5_rail", lambda **_k: (False, "watcher rejected (403)"))
    assert eb.main(["--start-mt5-sync", "--log", str(tmp_path / "b.log")]) == 3


def test_main_writes_the_boot_log(monkeypatch, tmp_path):
    log = tmp_path / "logs" / "boot.log"
    monkeypatch.setattr(eb, "backend_healthy", lambda **_k: True)
    monkeypatch.setattr(eb, "start_mt5_rail", lambda **_k: (True, "watcher running"))
    assert eb.main(["--start-mt5-sync", "--log", str(log)]) == 0
    text = log.read_text(encoding="utf-8")
    assert "already healthy" in text and "mt5 rail -> OK" in text


def test_http_get_returns_none_on_transport_error(monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(eb.urllib.request, "urlopen", boom)
    assert eb.http_get("http://127.0.0.1:8000/system/health") is None


def test_backend_healthy_accepts_any_http_status(monkeypatch):
    """A healthy backend can answer 503 under load. Treating that as dead
    makes the 5-minute supervisor report a false alarm on a live server."""
    class _Resp:
        status = 503

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(eb.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    assert eb.backend_healthy(port=8000) is True


def test_backend_healthy_rejects_a_connection_error(monkeypatch):
    def _boom(*_a, **_k):
        raise eb.urllib.error.URLError("connection refused")

    monkeypatch.setattr(eb.urllib.request, "urlopen", _boom)
    assert eb.backend_healthy(port=8000) is False


def test_backend_healthy_probe_allows_slow_answers():
    assert eb.HEALTH_TIMEOUT >= 15.0
