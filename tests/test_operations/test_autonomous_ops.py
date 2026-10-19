"""Phase D Autonomous Operations tests (ENGINEERING MAST 27.3 / 28.7).

The autonomous loop must be a *scheduled view* of the M9.5 ReviewLoop and
nothing more: it applies the same transitions the operator would, defers under
the same engine guard, never forces an ineligible promotion, and never trades.
These tests pin that contract down at the handler level plus the HTTP surface.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

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
from research.strategy_lab.validation import ValidationLab

import operations.api as api
from operations.autonomous import AutonomousOps, autonomous_enabled_by_env

strategy_v0 = "xauusd:ict_liquidity_sweep_reversal:v0"
strategy_v1 = "xauusd:ict_liquidity_sweep_reversal:v1"


def _passing_report(strategy_id=strategy_v0):
    def _r(i):
        return -0.5 if i % 5 == 4 else 0.7

    obs = [
        TradeObservation(
            experiment_id="e", strategy_id=strategy_id,
            family=StrategyFamily.OB_MITIGATION, variant_hash="h",
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
    return ValidationLab().evaluate(strategy_id, "XAUUSD", obs)


def _build_registry(tmp_path):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    live = _passing_report(strategy_v0)
    registry.register(strategy_v0, "h",
                      StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
                      initial=PromotionStage.PAPER, validation=live)
    notyet = _passing_report(strategy_v1)
    notyet.gates["positive_ev"] = False
    notyet.passed = False
    registry.register(strategy_v1, "h",
                      StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
                      initial=PromotionStage.CANDIDATE, validation=notyet)
    return registry


@pytest.fixture()
def lab_env(tmp_path, monkeypatch):
    _build_registry(tmp_path)
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def feed_reset():
    from operations.event_feed import event_feed as shared_feed
    saved_seq = shared_feed._seq
    saved_events = list(shared_feed._events)
    shared_feed._seq = 0
    shared_feed._events.clear()
    yield shared_feed
    shared_feed._seq = saved_seq
    shared_feed._events.clear()
    shared_feed._events.extend(saved_events)


def _loop(tmp_path, records, guard=None):
    """Loop over an isolated registry + injected ledger records."""
    import operations.quality as quality

    registry = _build_registry(tmp_path)
    if guard is not None:
        return AutonomousOps(
            registry_factory=lambda: registry,
            ledger_loader=lambda: records,
            review_loop_factory=lambda reg: quality.ReviewLoop(
                registry=reg, engine_guard=guard))
    return AutonomousOps(registry_factory=lambda: registry,
                         ledger_loader=lambda: records)


# ---------------------------------------------------------------------------
# the loop is a scheduled view of ReviewLoop (never a second writer)
# ---------------------------------------------------------------------------

def test_cycle_promotes_eligible_and_refuses_ineligible(tmp_path):
    loop = _loop(tmp_path, [])
    summary = loop.cycle()
    by_id = {row["strategy_id"]: row for row in summary["applied"]}
    # PAPER -> PRODUCTION is eligible (engine idle); CANDIDATE -> VALIDATED is
    # refused because its report did not pass.
    assert by_id[strategy_v0]["to_stage"] == "production"
    assert strategy_v1 not in by_id
    assert any(r["strategy_id"] == strategy_v1 and "passing" in r["reason"]
               for r in summary["refused"])


def test_cycle_defers_while_engine_running(tmp_path):
    loop = _loop(tmp_path, [], guard=lambda asset: True)
    summary = loop.cycle()
    assert summary["applied"] == []
    assert all(d["reason"] == "engine_running" for d in summary["deferred"])
    # nothing moved: the registry is untouched when the guard defers
    from research.strategy_lab.registry import StrategyRegistry
    reg = StrategyRegistry(str(tmp_path / "registry.json"))
    reg.load()
    assert reg.get(strategy_v0).stage.value == "paper"


def test_cycle_reports_contract_and_reads_gated(tmp_path):
    loop = _loop(tmp_path, [])
    summary = loop.cycle()
    assert summary["reads_gated"] is True
    assert "ReviewLoop" in summary["contract"]
    assert "never trades" in summary["contract"]


def test_run_once_increments_and_keeps_last(tmp_path):
    loop = _loop(tmp_path, [])
    first = loop.run_once()
    assert first["cycle"] == 1
    assert loop.status()["cycles"] == 1
    assert loop.status()["last"]["cycle"] == 1


# ---------------------------------------------------------------------------
# opt-in + never trades
# ---------------------------------------------------------------------------

def test_start_refused_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADERAIG_AUTONOMOUS_OPS", raising=False)
    loop = _loop(tmp_path, [])
    assert autonomous_enabled_by_env() is False
    assert loop.start(interval=30) is False
    assert loop.status()["running"] is False
    assert any("not enabled" in e for e in loop.status()["errors"])


def test_start_stop_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADERAIG_AUTONOMOUS_OPS", "1")
    loop = _loop(tmp_path, [])
    assert loop.start(interval=30) is True
    try:
        assert loop.status()["running"] is True
        assert loop.status()["enabled_by_env"] is True
    finally:
        loop.stop()
    assert loop.status()["running"] is False


def test_loop_never_trades(tmp_path, monkeypatch):
    """The module owns no order path: it may not import an executor/venue."""
    import operations.autonomous as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("place_order", "send_order", "LiveMT5Executor",
                      "order_send", "CexExecutor"):
        assert forbidden not in src, f"autonomous loop must not reference {forbidden}"


# ---------------------------------------------------------------------------
# HTTP surface (guarded routes + read-only status)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(api.app)


def test_autonomous_status_route_read_only(client, lab_env):
    r = client.get("/ops/autonomous/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "contract" in body and "ReviewLoop" in body["contract"]


def test_autonomous_cycle_route_applies(client, lab_env, feed_reset):
    r = client.post("/ops/autonomous/cycle")
    assert r.status_code == 200
    result = r.json()["result"]
    assert any(a["to_stage"] == "production" for a in result["applied"])
    feed = client.get("/ops/events?after=0").json()
    assert any(e["topic"] == "registry" and e["actor"] == "autonomous_ops"
               for e in feed["events"])


def test_autonomous_start_route_refused_without_env(client, lab_env,
                                                    monkeypatch):
    monkeypatch.delenv("TRADERAIG_AUTONOMOUS_OPS", raising=False)
    r = client.post("/ops/autonomous/start", json={"interval": 30})
    assert r.status_code == 409
    assert "TRADERAIG_AUTONOMOUS_OPS" in r.json()["detail"]


def test_autonomous_routes_registered_on_app():
    paths = {r.path for r in api.app.routes}
    for expected in ("/ops/autonomous/status", "/ops/autonomous/start",
                     "/ops/autonomous/stop", "/ops/autonomous/cycle"):
        assert expected in paths, f"route not registered: {expected}"
