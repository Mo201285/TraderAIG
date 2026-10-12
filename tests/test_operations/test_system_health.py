"""Performance of the aggregated /system/health surface (UPDATE.md §50)."""

import pytest

from operations.api import app

ALLOWED = ("Healthy", "Degraded", "Disconnected", "Error")

COMPONENT_LABELS = (
    "api", "database", "market_data", "ai", "dspy", "governance", "risk",
    "execution", "reconciliation", "learning", "storage",
)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_system_health_shape(client):
    resp = client.get("/system/health")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["ok"], bool)
    assert body["overall"] in ALLOWED
    assert "generated_at" in body
    for label in COMPONENT_LABELS:
        comp = body["components"][label]
        assert comp["status"] in ALLOWED
        assert isinstance(comp["ok"], bool)
        assert isinstance(comp["detail"], str)
    assert "single authority" in body["governance"]


def test_system_health_every_component_is_consistent(client):
    body = client.get("/system/health").json()
    for label, comp in body["components"].items():
        if comp["status"] == "Healthy":
            assert comp["ok"] is True, label
        elif comp["status"] in ("Disconnected", "Error"):
            assert comp["ok"] is False, label


# ---------------------------------------------------------------------------
# market_data must report the real feed plane, not a research corpus
# ---------------------------------------------------------------------------


def test_market_data_health_is_disconnected_when_no_feed_published(client):
    """An idle plane is honestly Disconnected — never "healthy because a
    strategy-lab corpus has observations"."""
    comp = client.get("/system/health").json()["components"]["market_data"]
    assert comp["status"] == "Disconnected"
    assert comp["ok"] is False
    assert "canonical plane" in comp["detail"]
    assert "corpus" not in comp["detail"]


def test_market_data_health_is_healthy_only_with_a_fresh_feed(client):
    import time as _time

    from core.market_plane import market_plane
    from core.contracts import Candle
    from core.state import MarketState

    now = _time.time()
    market_plane.register_feed(
        "mt5", lambda s, t, c: [
            Candle(symbol=s, timeframe="M15", time=now, open=1.0, high=2.0,
                   low=0.5, close=1.5, volume=1.0, tick_volume=1.0)])
    market_plane.publish_quote(
        MarketState(symbol="XAUUSD", bid=1.0, ask=1.1, spread=0.1,
                    last_price=1.05, last_tick_time=now), source="mt5")
    try:
        comp = client.get("/system/health").json()["components"]["market_data"]
        assert comp["status"] == "Healthy"
        assert comp["ok"] is True
        assert "mt5" in comp["detail"]
        assert "1 fresh quote" in comp["detail"]
    finally:
        market_plane.reset()
        market_plane.unregister_feed("mt5")


def test_market_data_health_names_the_publisher_not_the_pull_registry(client):
    """A registered puller that never published must not be named as the
    origin of a price.

    Regression: the detail line was built from the *pull registry*, so a
    `mt5` fetcher registered at boot made a bridge-published price report
    "fresh window(s) from mt5" — attributing data to a source it did not
    come from. Only sources that actually published may appear.
    """
    import time as _time

    from core.market_plane import market_plane

    now = _time.time()
    # registered, but never publishes
    market_plane.register_feed("mt5", lambda s, t, c: [])
    market_plane.ingest_bridge_frame(
        {"symbol": "XAUUSD", "timeframe": "M15", "time": now,
         "quote": {"bid": 1.0, "ask": 1.1, "last": 1.05, "tick_time": now},
         "bars": [{"time": now, "open": 1.0, "high": 2.0, "low": 0.5,
                   "close": 1.5, "tick_volume": 1.0}]},
        source="bridge:test")
    try:
        detail = client.get("/system/health").json()["components"][
            "market_data"]["detail"]
        assert "bridge:test" in detail, detail
        assert "mt5" not in detail, detail
    finally:
        market_plane.reset()
        market_plane.unregister_feed("mt5")


def test_market_plane_snapshot_separates_publishers_from_pullers():
    """`feeds` is who the plane may pull from; `sources` is who published."""
    import time as _time

    from core.market_plane import MarketPlane
    from core.contracts import Candle

    plane = MarketPlane()
    plane.register_feed("mt5", lambda s, t, c: [])
    plane.publish_candles("XAUUSD", "M15", [
        Candle(symbol="XAUUSD", timeframe="M15", time=_time.time(), open=1.0,
               high=2.0, low=0.5, close=1.5, volume=1.0, tick_volume=1.0)],
        source="bridge:file")
    snap = plane.snapshot()
    assert snap["feeds"] == ["mt5"], snap["feeds"]
    assert snap["sources"] == ["bridge:file"], snap["sources"]


def test_market_data_health_is_degraded_when_a_feed_exists_but_nothing_is_fresh(
        client):
    from core.market_plane import market_plane
    from core.contracts import Candle

    market_plane.register_feed("mt5", lambda s, t, c: [
        Candle(symbol=s, timeframe="M15", time=1.0, open=1.0, high=2.0,
               low=0.5, close=1.5, volume=1.0, tick_volume=1.0)])
    try:
        market_plane.publish_candles("XAUUSD", "M15", [
            Candle(symbol="XAUUSD", timeframe="M15", time=1.0, open=1.0,
                   high=2.0, low=0.5, close=1.5, volume=1.0, tick_volume=1.0)],
            source="mt5")
        comp = client.get("/system/health").json()["components"]["market_data"]
        assert comp["status"] == "Degraded"
        assert comp["ok"] is False
        assert "nothing fresh" in comp["detail"]
    finally:
        market_plane.reset()
        market_plane.unregister_feed("mt5")


def _patch_venue(monkeypatch, available: bool) -> None:
    from types import SimpleNamespace
    monkeypatch.setattr("execution.mt5_adapter.mt5_adapter",
                        SimpleNamespace(available=available))


def _reset_recon(recon_engine):
    saved = (list(recon_engine._mismatches), recon_engine._checks,
             recon_engine._last_ok, recon_engine._last_at)
    recon_engine._mismatches = []
    recon_engine._checks = 0
    recon_engine._last_ok = None
    recon_engine._last_at = None
    return saved


def _restore_recon(recon_engine, saved):
    recon_engine._mismatches = saved[0]
    recon_engine._checks = saved[1]
    recon_engine._last_ok = saved[2]
    recon_engine._last_at = saved[3]


def test_reconciliation_health_is_idle_and_healthy_without_a_live_venue(
        client, monkeypatch):
    """No live venue attached means nothing to reconcile -- and that is fine."""
    from types import SimpleNamespace
    monkeypatch.setattr("execution.mt5_adapter.mt5_adapter",
                        SimpleNamespace(available=False))
    comp = client.get("/system/health").json()["components"]["reconciliation"]
    assert comp["status"] == "Healthy"
    assert comp["ok"] is True
    assert "nothing to reconcile" in comp["detail"]


def test_reconciliation_health_degrades_when_a_venue_is_attached_but_unchecked(
        client, monkeypatch):
    from types import SimpleNamespace
    from core.pipeline import recon_engine

    monkeypatch.setattr("execution.mt5_adapter.mt5_adapter",
                        SimpleNamespace(available=True))
    saved = (list(recon_engine._mismatches), recon_engine._checks,
             recon_engine._last_ok, recon_engine._last_at)
    recon_engine._mismatches = []
    recon_engine._checks = 0
    recon_engine._last_ok = None
    recon_engine._last_at = None
    try:
        comp = client.get("/system/health").json()["components"][
            "reconciliation"]
        assert comp["status"] == "Degraded"
        assert comp["ok"] is False
        assert "no reconciliation pass recorded yet" in comp["detail"]
    finally:
        recon_engine._mismatches = saved[0]
        recon_engine._checks = saved[1]
        recon_engine._last_ok = saved[2]
        recon_engine._last_at = saved[3]


def test_reconciliation_health_reports_the_last_pass_honestly(client, monkeypatch):
    from types import SimpleNamespace
    from core.pipeline import recon_engine

    monkeypatch.setattr("execution.mt5_adapter.mt5_adapter",
                        SimpleNamespace(available=True))
    saved = (list(recon_engine._mismatches), recon_engine._checks,
             recon_engine._last_ok, recon_engine._last_at)
    recon_engine._mismatches = []
    recon_engine._checks = 0
    recon_engine._last_ok = None
    recon_engine._last_at = None
    try:
        clean = {"p1": {"position_id": "p1", "symbol": "EURUSD",
                        "volume": 0.10, "entry_price": 1.1000}}
        assert recon_engine.verify(
            [{"position_id": "p1", "volume": 0.10, "entry_price": 1.1000}],
            baseline=clean) is True
        matched = client.get("/system/health").json()["components"][
            "reconciliation"]
        assert matched["status"] == "Healthy" and matched["ok"] is True
        assert "matched" in matched["detail"]

        assert recon_engine.verify(
            [{"position_id": "p1", "volume": 0.90, "entry_price": 1.1000}],
            baseline=clean) is False
        drifted = client.get("/system/health").json()["components"][
            "reconciliation"]
        assert drifted["status"] == "Degraded" and drifted["ok"] is False
        assert "divergence" in drifted["detail"]
    finally:
        recon_engine._mismatches = saved[0]
        recon_engine._checks = saved[1]
        recon_engine._last_ok = saved[2]
        recon_engine._last_at = saved[3]
