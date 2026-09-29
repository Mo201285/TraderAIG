"""The paper watch must run INSIDE the API process (28.1: one canonical state).

These tests exist to pin the property that made `scripts/paper_engine.py`
unusable: a paper engine in its own process owns its own `MarketPlane`, its own
`core.state` and its own opportunity board, so every fill it made was invisible
to `/system/health`, `/opportunities` and the dashboard. Two states that
disagree quietly is worse than one state that is plainly missing.
"""

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


@pytest.fixture()
def paper_engine():
    from operations.live_engine import paper_engine
    return paper_engine


def test_paper_engine_is_a_singleton_in_the_api_process(paper_engine):
    """The same object every call sees - not a per-request or per-process copy."""
    from operations.live_engine import paper_engine as again
    assert paper_engine is again
    assert paper_engine.status()["paper"] is True


def test_paper_engine_never_builds_a_venue_order_path(paper_engine):
    """`paper=True` must be structural, not a label on a live executor.

    A PaperExecutor per symbol is the only thing standing between an approved
    candidate and `mt5.order_send`, so assert the wiring rather than trust the
    flag.
    """
    from operations.backtest import PaperExecutor
    from execution.mt5_adapter import LiveMT5Executor

    assert paper_engine._loops, "paper engine has no symbol loops"
    for symbol, loop in paper_engine._loops.items():
        assert isinstance(loop._executor, PaperExecutor), (
            f"{symbol} paper loop is wired to {type(loop._executor).__name__}")
        assert not isinstance(loop._executor, LiveMT5Executor)


def test_paper_and_live_engines_do_not_share_a_position_ledger(paper_engine):
    """One file for both desks would let paper fills rewrite the live ledger."""
    from operations.live_engine import live_engine

    paper_path = paper_engine._pos_manager._ledger_path
    live_path = live_engine._pos_manager._ledger_path
    assert paper_path and live_path
    assert paper_path != live_path


def test_paper_engine_status_is_visible_without_trading_entitlement(client):
    """Read-only: the operator must be able to SEE the desk is off without
    CAN_TRADE, and the payload carries no position or credential data."""
    resp = client.get("/paper/engine")
    assert resp.status_code == 200
    body = resp.json()
    assert body["paper"] is True
    assert "running" in body
    assert "paper_stats" in body
    for forbidden in ("password", "api_key", "secret", "token"):
        assert forbidden not in body


def test_paper_engine_start_stop_lifecycle(client, monkeypatch, paper_engine):
    """Start/stop round-trips without ever touching the terminal."""
    from execution.mt5_adapter import mt5_adapter

    monkeypatch.setattr(mt5_adapter, "connect", lambda: True)
    monkeypatch.setattr(paper_engine, "cycle", lambda: 0)
    monkeypatch.setattr(paper_engine, "_reconcile", lambda: None)

    resp = client.post("/paper/engine/start", json={"interval": 3600})
    assert resp.status_code == 200
    body = resp.json()
    assert body["started"] is True
    assert body["status"]["running"] is True
    assert body["status"]["paper"] is True
    assert body["symbols"]

    resp2 = client.post("/paper/engine/stop")
    assert resp2.status_code == 200
    assert resp2.json()["stopped"] is True
    assert resp2.json()["status"]["running"] is False


def test_paper_engine_start_honours_the_interval(client, monkeypatch, paper_engine):
    """The operator's interval must reach the loop, not a hardcoded default."""
    from execution.mt5_adapter import mt5_adapter

    seen = {}

    def fake_start(interval=30.0):
        seen["interval"] = interval
        return True

    monkeypatch.setattr(mt5_adapter, "connect", lambda: True)
    monkeypatch.setattr(paper_engine, "start", fake_start)

    resp = client.post("/paper/engine/start", json={"interval": 45})
    assert resp.status_code == 200
    assert resp.json()["interval"] == 45
    assert seen["interval"] == 45.0


def test_ensure_backend_reasserts_the_paper_desk(monkeypatch):
    """After every reboot the loop is in-process state and dies with the API.

    A 403 here is the entitlement gate doing its job, not a failure to retry
    around - the fix is an identity with CAN_TRADE.
    """
    import scripts.ensure_backend as eb

    calls = []

    def fake_post(url, payload=None, timeout=30.0):
        calls.append((url, payload))
        return 200, {"started": True, "symbols": ["XAUUSD"]}

    monkeypatch.setattr(eb, "http_post", fake_post)
    ok, detail = eb.start_paper_watch(port=8000, interval=30)
    assert ok is True
    assert "running" in detail
    assert calls[0][0].endswith("/paper/engine/start")
    assert calls[0][1] == {"interval": 30.0}


def test_ensure_backend_surfaces_a_paper_denied_entitlement(monkeypatch):
    import scripts.ensure_backend as eb

    monkeypatch.setattr(eb, "http_post", lambda *a, **k: (403, {"detail": "forbidden"}))
    ok, detail = eb.start_paper_watch(port=8000)
    assert ok is False
    assert "403" in detail


def test_ensure_backend_paper_failure_has_its_own_exit_code(monkeypatch):
    """A silent half-boot is the failure mode: backend up, no paper desk."""
    import scripts.ensure_backend as eb

    monkeypatch.setattr(eb, "backend_healthy", lambda **k: True)
    monkeypatch.setattr(eb, "start_paper_watch", lambda **k: (False, "nope"))
    assert eb.main(["--start-paper-sync"]) == 4
