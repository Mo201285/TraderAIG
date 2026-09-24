"""HTTP-surface verification — real routes, methods, status codes, JSON shapes.

All our endpoint tests call the handler functions directly; this suite goes
through the actual FastAPI routing (app decorators → HTTP layer) so a typo in
a path, a wrong method, a non-serializable payload, or a mis-mapped status
code fails here instead of at runtime behind a browser.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

import operations.api as api
from operations.event_feed import event_feed as shared_feed
from operations.copy_engine import copy_engine as shared_engine

from research.strategy_lab.contracts import (
    ExitReason,
    OosSplit,
    PromotionStage,
    SpreadBucket,
    StrategyFamily,
    TradeObservation,
    VolatilityBucket,
)
from research.strategy_lab.registry import StrategyRegistry

strategy_v0 = "xauusd:ict_liquidity_sweep_reversal:v0"


def _passing_report(strategy_id=strategy_v0):
    def _r(i):
        return -0.5 if i % 5 == 4 else 0.7

    obs = [
        TradeObservation(
            experiment_id="e", strategy_id=strategy_id,
            family=StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, variant_hash="h",
            asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
            session="london", weekday=2, regime="bullish/normal",
            volatility_bucket=VolatilityBucket.MEDIUM,
            spread_bucket=SpreadBucket.NORMAL,
            entry_type="matrix_pool", sl_model="lt", tp_model="zt",
            pattern_geometry="", macro_state="",
            mfe_r=1.0, mae_r=-0.5,
            exit_reason=ExitReason.TARGET if _r(i) > 0 else ExitReason.STOP,
            oos_split=(OosSplit.OUT_OF_SAMPLE if i >= 30 else OosSplit.IN_SAMPLE),
            walkforward_window=i % 2,
            pnl=_r(i), r_multiple=_r(i))
        for i in range(40)
    ]
    from research.strategy_lab.validation import ValidationLab
    return ValidationLab().evaluate(strategy_id, "XAUUSD", obs)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(api.app)  # no lifespan: no server-side startup side effects


@pytest.fixture()
def lab_env(tmp_path, monkeypatch):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    registry.register(strategy_v0, "h",
                      StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
                      initial=PromotionStage.PAPER, validation=_passing_report())
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def feed_reset():
    saved_seq = shared_feed._seq
    saved_events = list(shared_feed._events)
    shared_feed._seq = 0
    shared_feed._events.clear()
    yield shared_feed
    shared_feed._seq = saved_seq
    shared_feed._events.clear()
    shared_feed._events.extend(saved_events)


@pytest.fixture()
def cr_board():
    from governance.change_requests import change_board
    saved = dict(change_board._requests)
    seq = change_board._seq
    yield change_board
    change_board._requests = saved
    change_board._seq = seq


@pytest.fixture()
def copy_reset(feed_reset):
    shared_engine.reset()
    yield shared_engine
    shared_engine.reset()


# ---------------------------------------------------------------------------
# core read routes
# ---------------------------------------------------------------------------

def test_health_route(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "account" in body


def test_system_health_route(client):
    r = client.get("/system/health")
    assert r.status_code == 200
    body = r.json()
    assert "components" in body and "overall" in body


def test_strategies_route(client, lab_env):
    r = client.get("/strategies")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert any(x["strategy_id"].endswith(strategy_v0) or x["strategy_id"] == strategy_v0
               for x in rows)


# ---------------------------------------------------------------------------
# monitoring + review over HTTP
# ---------------------------------------------------------------------------

def test_monitoring_quality_route(client, lab_env):
    r = client.get("/monitoring/quality")
    assert r.status_code == 200
    body = r.json()
    assert set(body["areas"]) == {"macro_freshness", "ownership_integrity",
                                  "confluence_quality"}


def test_review_queue_route(client, lab_env):
    r = client.get("/monitoring/review")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and body["count"] == 1


def test_review_apply_http_publishes_to_feed(client, lab_env, feed_reset):
    r = client.post("/ops/review/apply", json={
        "kind": "promote", "strategy_id": strategy_v0})
    assert r.status_code == 200
    assert r.json()["applied"] is True and r.json()["to_stage"] == "production"
    # the same HTTP router that applied the transition also pushed an event
    feed = client.get("/ops/events?after=0").json()
    assert feed["count"] >= 1
    assert any(e["kind"] == "transition" and e["topic"] == "registry"
               for e in feed["events"])


def test_review_apply_unknown_strategy_404(client, lab_env, feed_reset):
    r = client.post("/ops/review/apply", json={
        "kind": "promote", "strategy_id": "xauusd:ghost:v9"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# governance over HTTP (routing, status codes, serialization)
# ---------------------------------------------------------------------------

def test_governance_flow_http(client, lab_env, feed_reset, cr_board, copy_reset):
    # submit
    r = client.post("/governance/change-requests", json={
        "kind": "promote", "target": strategy_v0, "reason": "http flow"})
    assert r.status_code == 200
    cr_id = r.json()["request"]["id"]

    # list shows it
    r = client.get("/governance/change-requests?status=pending")
    assert r.status_code == 200
    assert any(x["id"] == cr_id for x in r.json()["requests"])

    # approve applies under the guard
    r = client.post(f"/governance/change-requests/{cr_id}/approve",
                    json={"decided_by": "admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["to_stage"] == "production"

    # a second decision on the same request is a 409
    r = client.post(f"/governance/change-requests/{cr_id}/approve",
                    json={"decided_by": "admin"})
    assert r.status_code == 409

    # unknown request is a 404
    r = client.post("/governance/change-requests/nope/approve",
                    json={"decided_by": "admin"})
    assert r.status_code == 404

    # bad kind is a 400
    r = client.post("/governance/change-requests", json={
        "kind": "explode", "target": "x", "reason": "bad"})
    assert r.status_code == 400

    # copy consumer sees the applied mirror over HTTP
    r = client.get("/ops/copy/follower")
    assert r.status_code == 200
    pf = r.json()["portfolio"]
    assert pf["strategies"][strategy_v0]["state"] == "production"


def test_governance_deny_and_cancel_http(client, lab_env, feed_reset, cr_board):
    r = client.post("/governance/change-requests", json={
        "kind": "config", "target": "risk.max_daily_loss_pct", "reason": "tune"})
    cr_id = r.json()["request"]["id"]
    assert client.post(f"/governance/change-requests/{cr_id}/deny",
                       json={"decided_by": "admin", "reason": "veto"}).status_code == 200
    assert client.post(f"/governance/change-requests/{cr_id}/deny",
                       json={"decided_by": "admin"}).status_code == 409

    r = client.post("/governance/change-requests", json={
        "kind": "config", "target": "k2", "reason": "r"})
    cr_id2 = r.json()["request"]["id"]
    assert client.post(f"/governance/change-requests/{cr_id2}/cancel",
                       json={"requested_by": "operator"}).status_code == 200


# ---------------------------------------------------------------------------
# ops feed / copy routes
# ---------------------------------------------------------------------------

def test_ops_events_route_http(client, feed_reset):
    r = client.get("/ops/events?after=0")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "latest" in body and body["count"] == 0
    # query param validation: non-int after is rejected by FastAPI (422)
    assert client.get("/ops/events?after=abc").status_code == 422


def test_copy_route_http_read_only(client, lab_env, feed_reset, cr_board):
    r = client.get("/ops/copy/follower")
    assert r.status_code == 200
    pf = r.json()["portfolio"]
    assert "strategies" in pf and "decisions_consumed" in pf


def test_all_new_routes_registered_on_app():
    paths = {r.path for r in api.app.routes}
    for expected in (
        "/health", "/system/health", "/monitoring/quality", "/monitoring/review",
        "/ops/review/apply", "/governance/change-requests",
        "/governance/change-requests/{cr_id}/approve",
        "/governance/change-requests/{cr_id}/deny",
        "/governance/change-requests/{cr_id}/cancel",
        "/ops/events", "/ops/copy/follower",
    ):
        assert expected in paths, f"route not registered: {expected}"
