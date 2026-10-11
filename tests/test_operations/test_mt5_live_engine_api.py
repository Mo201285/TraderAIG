"""Live MT5 execution must be unreachable by accident.

`operations.live_engine` already holds a module-level singleton built with
`paper=False`, wired to a real `LiveMT5Executor`. That is deliberate -- it is the
engine `main.py --mt5` always built -- but it also means the API process has a
live order path sitting in memory at all times.

These tests pin the three properties that keep that safe:
  1. the arm flag is default-off and only the operator sets it,
  2. nothing order-eligible means nothing trades, even when armed,
  3. the boot path has no way to arm a venue.
"""

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _not_armed(monkeypatch):
    """Every test starts from 'the operator has not armed live trading'."""
    monkeypatch.delenv("MT5_LIVE_TRADING", raising=False)


@pytest.fixture()
def cleared(monkeypatch):
    """Set the promotion-cleared set the route will see."""
    def _set(ids):
        monkeypatch.setattr("operations.live_engine.promotion_cleared_strategies",
                            lambda: list(ids))
    return _set


@pytest.fixture()
def stub_live_start(monkeypatch):
    """Never let a route test reach MT5 or spawn the loop."""
    from operations.live_engine import live_engine

    seen = {}

    def fake_start(interval=30.0):
        seen["interval"] = interval
        seen["called"] = True
        return True

    monkeypatch.setattr(live_engine, "start", fake_start)
    monkeypatch.setattr(live_engine, "status",
                        lambda: {"running": False, "paper": False,
                                 "symbols": ["XAUUSD"]})
    return seen


# -- what the process is holding -----------------------------------------

def test_the_live_singleton_really_is_live():
    """Document the hazard rather than pretend it away.

    If this ever flips to `paper=True` the arming tests below would keep passing
    while the thing under test stopped being a live order path.
    """
    from execution.mt5_adapter import LiveMT5Executor
    from operations.live_engine import live_engine

    assert live_engine.status()["paper"] is False
    assert live_engine._loops, "live engine has no symbol loops"
    for symbol, loop in live_engine._loops.items():
        assert isinstance(loop._executor, LiveMT5Executor), (
            f"{symbol} live loop is not wired to a venue executor")


def test_a_fresh_process_is_not_running_live_trading():
    """Constructing the singleton must not start it."""
    from operations.live_engine import live_engine
    assert live_engine.status()["running"] is False


def test_paper_and_live_desks_keep_separate_ledgers():
    from operations.live_engine import live_engine, paper_engine
    assert (paper_engine._pos_manager._ledger_path
            != live_engine._pos_manager._ledger_path)


# -- the status surface ---------------------------------------------------

def test_status_is_visible_without_trading_entitlement(client):
    """Same reasoning as /paper/engine: an operator must be able to see that
    live trading is OFF without holding CAN_TRADE."""
    resp = client.get("/mt5/engine")
    assert resp.status_code == 200
    body = resp.json()
    assert body["armed"] is False
    assert body["arm_flag"] == "MT5_LIVE_TRADING"
    assert body["would_start"] is False
    assert body["refusals"]
    for forbidden in ("password", "api_key", "secret", "token"):
        assert forbidden not in body


def test_status_reports_both_gates_separately(client, cleared, monkeypatch):
    """A single 'ready' boolean would hide which of the two gates is shut."""
    cleared(["s1"])
    assert client.get("/mt5/engine").json()["refusals"] == [
        "MT5_LIVE_TRADING is not enabled"]

    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    cleared([])
    body = client.get("/mt5/engine").json()
    assert body["refusals"] == ["no strategy is at the paper/production stage"]

    cleared(["s1"])
    body = client.get("/mt5/engine").json()
    assert body["would_start"] is True
    assert body["refusals"] == []


# -- the refusals ---------------------------------------------------------

def test_start_is_refused_while_the_flag_is_off(client, cleared, stub_live_start):
    cleared(["s1"])
    resp = client.post("/mt5/engine/start", json={"interval": 30})
    assert resp.status_code == 403
    assert "MT5_LIVE_TRADING" in resp.json()["detail"]
    assert "called" not in stub_live_start, "the engine must not be reached"


def test_start_is_refused_when_nothing_is_promotion_cleared(
        client, cleared, stub_live_start, monkeypatch):
    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    cleared([])
    resp = client.post("/mt5/engine/start", json={"interval": 30})
    assert resp.status_code == 403
    assert "paper/production" in resp.json()["detail"]
    assert "called" not in stub_live_start


def test_a_validated_but_unpromoted_strategy_still_cannot_trade(
        client, cleared, stub_live_start, monkeypatch):
    """Armed and tested is still not the same as promoted."""
    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    cleared([])
    resp = client.post("/mt5/engine/start", json={"interval": 30})
    assert resp.status_code == 403
    assert "called" not in stub_live_start


def test_start_proceeds_when_both_gates_are_open(client, cleared, stub_live_start,
                                                 monkeypatch):
    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    cleared(["s1", "s2"])
    resp = client.post("/mt5/engine/start", json={"interval": 45})
    assert resp.status_code == 200
    body = resp.json()
    assert body["started"] is True
    assert body["live"] is True
    assert body["promotion_cleared"] == ["s1", "s2"]
    assert stub_live_start["interval"] == 45.0


def test_a_refusal_from_the_engine_is_reported_not_swallowed(
        client, cleared, stub_live_start, monkeypatch):
    """The engine re-checks its own gates, so its refusal is the real answer."""
    from operations.live_engine import live_engine

    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    cleared(["s1"])
    monkeypatch.setattr(live_engine, "start", lambda interval=30.0: False)
    monkeypatch.setattr(live_engine, "status",
                        lambda: {"running": False, "errors": ["no promotion-cleared strategy"]})
    resp = client.post("/mt5/engine/start", json={"interval": 30})
    assert resp.status_code == 409
    assert "no promotion-cleared strategy" in resp.json()["detail"]


# -- one account, one desk ----------------------------------------------

def test_starting_paper_stops_a_running_live_desk(client, monkeypatch):
    """Otherwise one opportunity is consumed twice and paper fills are reported
    against an account that never took them."""
    from operations.live_engine import live_engine, paper_engine

    running = {"live": True}
    stopped = {"live": False}

    monkeypatch.setattr(live_engine, "status", lambda: {"running": running["live"]})
    monkeypatch.setattr(live_engine, "stop", lambda: stopped.update(live=False))
    monkeypatch.setattr(paper_engine, "status", lambda: {"running": False, "paper": True})

    resp = client.post("/paper/engine/start", json={"interval": 3600})
    assert resp.status_code == 200
    assert stopped["live"] is False, "live desk was left running alongside paper"


def test_starting_live_stops_a_running_paper_desk(client, cleared, stub_live_start,
                                                  monkeypatch):
    from operations.live_engine import paper_engine

    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    cleared(["s1"])
    stopped = {"paper": False}
    monkeypatch.setattr(paper_engine, "status", lambda: {"running": True, "paper": True})
    monkeypatch.setattr(paper_engine, "stop", lambda: stopped.update(paper=True))

    resp = client.post("/mt5/engine/start", json={"interval": 30})
    assert resp.status_code == 200
    assert stopped["paper"] is True, "paper desk was left running alongside live"


# -- the boot path --------------------------------------------------------

def test_the_boot_script_has_no_way_to_arm_a_venue(monkeypatch):
    """A scheduled task must not be a back door around the arm flag.

    `ensure_backend.py` re-asserts the paper desk and the CEX paper feed after
    every reboot; it must never carry a payload or flag that can arm live MT5.
    """
    import inspect

    import scripts.ensure_backend as eb

    source = inspect.getsource(eb)
    for forbidden in ("MT5_LIVE_TRADING", "/mt5/engine/start", "MT5_LIVE_ALLOWED"):
        assert forbidden not in source, (
            f"the boot script must not be able to arm live trading via {forbidden!r}")

    calls = []

    def fake_post(url, payload=None, timeout=30.0):
        calls.append((url, payload))
        return 200, {"started": True, "status": {"paper": True}}

    monkeypatch.setattr(eb, "http_post", fake_post)
    eb.start_paper_watch(port=8000, interval=30)
    assert calls[0][0].endswith("/paper/engine/start")
