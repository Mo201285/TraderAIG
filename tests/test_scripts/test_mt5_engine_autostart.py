"""Tests for the live-MT5 autostart helper.

The two invariants that matter: it must never bypass the arm flag, and it must
never start a second engine when one is already running.
"""
from __future__ import annotations

import inspect
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import mt5_engine_autostart as ma  # noqa: E402


def test_status_reader_returns_none_on_transport_error(monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(ma.urllib.request, "urlopen", boom)
    assert ma.engine_status("http://127.0.0.1:8000/mt5/engine") is None


def test_live_running_ignores_the_paper_desk():
    assert ma.live_running({"status": {"running": True, "paper": False}}) is True
    assert ma.live_running({"status": {"running": True, "paper": True}}) is False
    assert ma.live_running({"status": {"running": False}}) is False
    assert ma.live_running(None) is False


def test_main_reports_an_unhealthy_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: False)
    assert ma.main(["--wait", "0", "--log", str(tmp_path / "a.log")]) == 2


def test_main_needs_a_machine_token(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: True)
    monkeypatch.setattr(ma, "service_headers", lambda: {})
    assert ma.main(["--log", str(tmp_path / "a.log")]) == 3


def test_main_reports_an_unreadable_status(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: True)
    monkeypatch.setattr(ma, "service_headers", lambda: {"X-Service-Token": "t"})
    monkeypatch.setattr(ma, "engine_status", lambda *_a, **_k: None)
    assert ma.main(["--log", str(tmp_path / "a.log")]) == 3


def test_main_leaves_an_already_running_live_desk_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: True)
    monkeypatch.setattr(ma, "service_headers", lambda: {"X-Service-Token": "t"})
    monkeypatch.setattr(ma, "engine_status", lambda *_a, **_k: {
        "armed": True, "status": {"running": True, "paper": False}})
    monkeypatch.setattr(ma, "http_post",
                        lambda *_a, **_k: pytest.fail("must not start twice"))
    assert ma.main(["--log", str(tmp_path / "a.log")]) == 0


def test_main_never_arms_a_disarmed_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: True)
    monkeypatch.setattr(ma, "service_headers", lambda: {"X-Service-Token": "t"})
    monkeypatch.setattr(ma, "engine_status", lambda *_a, **_k: {
        "armed": False, "status": {"running": False}})
    monkeypatch.setattr(ma, "http_post",
                        lambda *_a, **_k: pytest.fail("must not bypass the flag"))
    assert ma.main(["--log", str(tmp_path / "a.log")]) == 1


def test_main_surfaces_a_refused_start(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: True)
    monkeypatch.setattr(ma, "service_headers", lambda: {"X-Service-Token": "t"})
    monkeypatch.setattr(ma, "engine_status", lambda *_a, **_k: {
        "armed": True, "status": {"running": False}})
    monkeypatch.setattr(ma, "http_post",
                        lambda *_a, **_k: (403, {"detail": "no cleared strategy"}))
    assert ma.main(["--log", str(tmp_path / "a.log")]) == 1


def test_main_starts_the_desk_and_writes_the_log(monkeypatch, tmp_path):
    log = tmp_path / "logs" / "autostart.log"
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: True)
    monkeypatch.setattr(ma, "service_headers", lambda: {"X-Service-Token": "t"})
    monkeypatch.setattr(ma, "engine_status", lambda *_a, **_k: {
        "armed": True, "status": {"running": False, "paper": False}})
    monkeypatch.setattr(ma, "http_post", lambda *_a, **_k: (
        200, {"started": True, "status": {"symbols": ["BTCUSD", "XAUUSD"]}}))
    assert ma.main(["--interval", "30", "--log", str(log)]) == 0
    text = log.read_text(encoding="utf-8")
    assert "started" in text and "BTCUSD" in text


def test_main_reports_a_refused_start(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "wait_healthy", lambda **_k: True)
    monkeypatch.setattr(ma, "service_headers", lambda: {"X-Service-Token": "t"})
    monkeypatch.setattr(ma, "engine_status", lambda *_a, **_k: {
        "armed": True, "status": {"running": False, "paper": False}})
    monkeypatch.setattr(ma, "http_post", lambda *_a, **_k: (
        403, {"detail": "no strategy is at the paper/production stage"}))
    assert ma.main(["--log", str(tmp_path / "a.log")]) == 1


def test_the_script_cannot_set_the_arm_flag_itself():
    """The operator's `.env` is the only place `MT5_LIVE_TRADING` may be set.

    A helper that armed the venue would make the task, not the operator, the
    authority - the same reason `ensure_backend.py` is pinned clean.
    """
    source = inspect.getsource(ma)
    for forbidden in ("MT5_LIVE_ALLOWED", "os.environ", "putenv", "setenv",
                      "MT5_LIVE_TRADING="):
        assert forbidden not in source, (
            f"the autostart helper must not touch the environment via {forbidden!r}")
