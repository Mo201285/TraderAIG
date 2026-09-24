"""Event feed + copy-engine consumer tests (Redis pub/sub orphan).

The feed is transport-agnostic: it always records in process (zero infra) and
mirrors to Redis only when available. The copy engine is a pure consumer of
that same stream — it mirrors master transitions and flags governance disputes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

import operations.api as api
from operations.event_feed import EventFeed, event_feed as shared_feed
from operations.copy_engine import CopyEngine, copy_engine as shared_engine

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
def fresh_feed():
    return EventFeed(maxlen=8)


@pytest.fixture()
def feed_reset():
    """Start the shared feed clean; restore prior state afterwards."""
    saved_seq = shared_feed._seq
    saved_events = list(shared_feed._events)
    shared_feed._seq = 0
    shared_feed._events.clear()
    yield shared_feed
    shared_feed._seq = saved_seq
    shared_feed._events.clear()
    shared_feed._events.extend(saved_events)


@pytest.fixture()
def copy_reset(feed_reset):
    saved = shared_engine.follower_portfolio()
    shared_engine.reset()
    yield shared_engine
    shared_engine.reset()
    shared_engine._cursor = saved["cursor"]
    shared_engine._follower.update(saved["strategies"])
    shared_engine._overrides = list(saved["overrides"])
    shared_engine._decisions = saved["decisions_consumed"]


@pytest.fixture()
def lab_env(tmp_path, monkeypatch):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    registry.register(strategy_v0, "h",
                      StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
                      initial=PromotionStage.PAPER, validation=_passing_report())
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def cr_board():
    from governance.change_requests import change_board
    saved = dict(change_board._requests)
    seq = change_board._seq
    yield change_board
    change_board._requests = saved
    change_board._seq = seq


# ---------------------------------------------------------------------------
# feed semantics
# ---------------------------------------------------------------------------

def test_publish_and_since_ordering(fresh_feed):
    e1 = fresh_feed.publish("transition", "registry", actor="review_loop",
                            payload={"strategy_id": "s0", "to_stage": "production"})
    e2 = fresh_feed.publish("decided", "change", actor="admin",
                            payload={"target": "s0", "outcome": "quarantined"})
    assert e1["id"] == 1 and e2["id"] == 2
    rows = fresh_feed.since(after=0)
    assert [r["id"] for r in rows] == [1, 2]
    assert [r["id"] for r in fresh_feed.since(after=1)] == [2]


def test_since_topic_filter(fresh_feed):
    fresh_feed.publish("transition", "registry")
    fresh_feed.publish("decided", "change")
    only = fresh_feed.since(after=0, topic="change")
    assert len(only) == 1 and only[0]["topic"] == "change"


def test_feed_ring_is_bounded(fresh_feed):
    for i in range(12):
        fresh_feed.publish("transition", "registry", payload={"i": i})
    assert fresh_feed.latest == 12
    rows = fresh_feed.since(after=0)
    assert len(rows) == 8  # maxlen keeps only the last 8
    assert rows[-1]["id"] == 12


def test_unknown_topic_falls_back_to_ops(fresh_feed):
    assert fresh_feed.publish("ping", "nowhere")["topic"] == "ops"


def test_redis_unavailable_is_graceful(fresh_feed, monkeypatch):
    class _Down:
        enabled = False

        def publish_snapshot(self, key, obj):  # pragma: no cover - defensive
            raise AssertionError("must not be called when disabled")

    monkeypatch.setattr("core.redis_state.redis_sync", _Down())
    assert fresh_feed.publish("risk", "risk", payload={"v": 1})["id"] == 1


def test_redis_mirror_fires_when_available(fresh_feed, monkeypatch):
    seen = []

    class _Up:
        enabled = True

        def publish_snapshot(self, key, obj):
            seen.append((key, obj))

    monkeypatch.setattr("core.redis_state.redis_sync", _Up())
    fresh_feed.publish("transition", "registry", payload={"strategy_id": "s0"})
    assert seen and seen[0][0] == "events"


# ---------------------------------------------------------------------------
# copy-engine consumer
# ---------------------------------------------------------------------------

def test_copy_engine_mirrors_transitions(fresh_feed):
    engine = CopyEngine(feed=fresh_feed)
    fresh_feed.publish("transition", "registry", actor="review_loop",
                       payload={"strategy_id": "s0", "to_stage": "production"})
    fresh_feed.publish("decided", "change", actor="admin",
                       payload={"target": "s1", "outcome": "quarantined"})
    engine.consume()
    pf = engine.follower_portfolio()
    assert pf["decisions_consumed"] == 2
    assert pf["strategies"]["s0"]["state"] == "production"
    assert pf["strategies"]["s1"]["state"] == "quarantined"


def test_copy_engine_flags_governance_dispute(fresh_feed):
    engine = CopyEngine(feed=fresh_feed)
    fresh_feed.publish("transition", "registry",
                       payload={"strategy_id": "s0", "to_stage": "production"})
    fresh_feed.publish("decided", "change",
                       payload={"target": "s0", "outcome": "quarantined"})
    engine.consume()
    pf = engine.follower_portfolio()
    assert len(pf["overrides"]) == 1
    assert pf["overrides"][0]["previous_state"] == "production"


def test_copy_engine_resumes_from_cursor(fresh_feed):
    engine = CopyEngine(feed=fresh_feed)
    fresh_feed.publish("transition", "registry",
                       payload={"strategy_id": "s0", "to_stage": "p"})
    assert engine.consume() == 1
    assert engine.consume() == 0  # nothing new
    assert engine.follower_portfolio()["decisions_consumed"] == 1


# ---------------------------------------------------------------------------
# API surface (dashboard + copy consumers read the same stream)
# ---------------------------------------------------------------------------

def test_events_endpoint_returns_feed(feed_reset):
    out = api.ops_events(after=0)
    assert out["ok"] is True
    assert "events" in out and "latest" in out
    assert out["count"] == 0


def test_review_apply_publishes_transition_event(lab_env, feed_reset):
    out = api.review_apply({"kind": "promote", "strategy_id": strategy_v0})
    assert out["ok"] is True and out["applied"] is True
    events = api.ops_events(after=0)["events"]
    assert any(e["kind"] == "transition" and e["topic"] == "registry"
               and e["payload"].get("strategy_id") == strategy_v0
               for e in events)


def test_change_flow_events_and_copy_consumer(lab_env, feed_reset, copy_reset,
                                              cr_board):
    # submit -> pending request event
    out = api.change_request_submit({"kind": "promote", "target": strategy_v0,
                                     "reason": "copy flow"})
    cr_id = out["request"]["id"]
    assert any(e["kind"] == "requested" for e in api.ops_events(after=0)["events"])

    # approve -> decided event with applied stage; no engine running
    got = api.change_request_approve(cr_id, {"decided_by": "admin"})
    assert got["ok"] is True and got["to_stage"] == "production"

    events = api.ops_events(after=0)["events"]
    decided = [e for e in events if e["kind"] == "decided"]
    assert decided and decided[0]["payload"]["outcome"] == "production"

    # the copy engine mirrors it via the SAME /ops stream
    portfolio = api.copy_follower()["portfolio"]
    assert portfolio["strategies"][strategy_v0]["state"] == "production"
    assert portfolio["decisions_consumed"] >= 1


def test_copy_endpoint_is_read_only(lab_env, feed_reset, copy_reset, cr_board):
    before = {e["strategy_id"]: e["stage"] for e in api.lab_strategies()}
    api.copy_follower()
    after = {e["strategy_id"]: e["stage"] for e in api.lab_strategies()}
    assert before == after  # consumer never mutates the master registry
