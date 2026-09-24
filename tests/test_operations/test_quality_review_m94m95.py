"""Phase 9 API surface tests (M9.4 quality monitoring + M9.5 review loop)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException

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
from operations.quality import (
    confluence_quality,
    macro_freshness,
    ownership_snapshot,
)

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


@pytest.fixture()
def lab_env(tmp_path, monkeypatch):
    """tmp lab data dir with a validated PAPER entry + a failing CANDIDATE."""
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
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def ledger_snapshot():
    """Restore the shared in-memory ledger after each mutating test."""
    saved = list(api.ledger._records)
    yield
    api.ledger._records[:] = saved


@pytest.fixture()
def board_history_snapshot():
    from schools.board import school_board
    saved = list(school_board._confluence_history)
    yield school_board
    school_board._confluence_history.clear()
    school_board._confluence_history.extend(saved)


# ---------------------------------------------------------------------------
# M9.4 monitors (pure functions)
# ---------------------------------------------------------------------------

def test_macro_freshness_verdicts():
    stale = macro_freshness({"configured": False})
    assert stale["status"] == "degraded" and stale["ok"] is False
    fresh = macro_freshness({"configured": True, "stale_seconds": 10,
                             "source_status": "env_runtime", "event_count": 2,
                             "risk_off": False, "risk_on": False})
    assert fresh["status"] == "healthy" and fresh["ok"] is True
    old = macro_freshness({"configured": True, "stale_seconds": 2000,
                           "source_status": "env_runtime", "event_count": 2,
                           "risk_off": False, "risk_on": False},
                          refresh_seconds=300.0)
    assert old["status"] == "watch" and old["ok"] is False


def test_ownership_snapshot_flags_integrity(lab_env, ledger_snapshot):
    from learning.experience import ExperienceRecord
    api.ledger._records.clear()
    api.ledger._records.append(ExperienceRecord(
        record_id="sys-1", decision_id="d", timestamp=0.0,
        actual_result={"filled": True, "pnl": 1.0, "origin": "system"}))
    api.ledger._records.append(ExperienceRecord(
        record_id="man-1", decision_id="d", timestamp=0.0,
        actual_result={"filled": True, "pnl": 2.0, "origin": "manual"}))
    ok = ownership_snapshot(api.ledger._records)
    assert ok["status"] == "healthy" and ok["by_origin"] == {"system": 1,
                                                             "manual": 1}
    api.ledger._records.append(ExperienceRecord(
        record_id="rogue-1", decision_id="d", timestamp=0.0,
        actual_result={"filled": True, "pnl": 3.0, "origin": "subscriber"}))
    bad = ownership_snapshot(api.ledger._records)
    assert bad["status"] == "degraded"
    assert any("unknown origin" in p for p in bad["problems"])


def test_confluence_quality_verdicts():
    empty = confluence_quality([])
    assert empty["status"] == "degraded" and empty["sampled"] == 0
    multi = [{"kind": "multi_source", "confidence": 0.8, "blocked": False}
             for _ in range(40)]
    multi.append({"kind": "multi_source", "confidence": 0.7, "blocked": False})
    good = confluence_quality(multi)
    assert good["status"] == "healthy" and good["multi_source_ratio"] == 1.0
    mixed = [{"kind": "single_source_exception", "confidence": 0.65,
              "blocked": False} for _ in range(9)]
    mixed.extend([{"kind": "multi_source", "confidence": 0.7, "blocked": False}
                  for _ in range(1)])
    weak = confluence_quality(mixed)
    assert weak["status"] == "degraded"
    assert any("single-source exception" in p for p in weak["problems"])


# ---------------------------------------------------------------------------
# M9.4 /monitoring/quality endpoint
# ---------------------------------------------------------------------------

def test_quality_endpoint_areas(lab_env, board_history_snapshot):
    board_history_snapshot._confluence_history.clear()
    out = api.quality_status()
    assert out["ok"] is True
    assert out["status"] in ("healthy", "watch", "degraded")
    assert set(out["areas"]) == {"macro_freshness", "ownership_integrity",
                                 "confluence_quality"}
    assert out["areas"]["confluence_quality"]["sampled"] == 0


def test_quality_endpoint_reads_board_history(lab_env, board_history_snapshot):
    board = board_history_snapshot
    board._confluence_history.clear()
    for _ in range(3):
        board._confluence_history.append(
            {"kind": "multi_source", "confidence": 0.8, "blocked": False,
             "symbol": "XAUUSD"})
    assert len(board.confluence_history()) == 3
    out = api.quality_status()
    assert out["areas"]["confluence_quality"]["sampled"] == 3
    assert out["areas"]["confluence_quality"]["status"] == "healthy"


# ---------------------------------------------------------------------------
# M9.5 review queue (read-only)
# ---------------------------------------------------------------------------

def test_review_queue_is_read_only(lab_env, ledger_snapshot):
    before = {e["strategy_id"]: e["stage"]
              for e in api.lab_strategies()}
    out = api.review_queue()
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["promotion_candidates"] == 2
    by_id = {i["strategy_id"]: i for i in out["items"]}
    assert by_id[strategy_v0]["to_stage"] == "production"
    assert by_id[strategy_v0]["eligible"] is True
    assert by_id[strategy_v0]["engine_running"] is False
    assert by_id[strategy_v1]["eligible"] is False
    assert "passing validation" in by_id[strategy_v1]["reasons"][0]
    # queue must not mutate the registry
    after = {e["strategy_id"]: e["stage"]
             for e in api.lab_strategies()}
    assert before == after


# ---------------------------------------------------------------------------
# M9.5 guarded apply
# ---------------------------------------------------------------------------

def test_review_apply_promote(lab_env, ledger_snapshot):
    out = api.review_apply({"kind": "promote", "strategy_id": strategy_v0})
    assert out["ok"] is True and out["applied"] is True
    assert out["from_stage"] == "paper" and out["to_stage"] == "production"
    assert any("promote#production" in h for h in out["history"])


def test_review_apply_quarantine(lab_env, ledger_snapshot):
    out = api.review_apply({"kind": "quarantine", "strategy_id": strategy_v0,
                            "reason": "sustained_drift"})
    assert out["ok"] is True and out["applied"] is True
    assert out["to_stage"] == "quarantined"
    assert any("quarantine#sustained_drift" in h for h in out["history"])


def test_review_apply_refuses_without_passing_validation(lab_env, ledger_snapshot):
    with pytest.raises(HTTPException) as exc:
        api.review_apply({"kind": "promote", "strategy_id": strategy_v1})
    assert exc.value.status_code == 409
    assert "registry refused" in exc.value.detail


def test_review_apply_unknown_strategy(lab_env, ledger_snapshot):
    with pytest.raises(HTTPException) as exc:
        api.review_apply({"kind": "promote", "strategy_id": "xauusd:ghost:v9"})
    assert exc.value.status_code == 404


def test_review_apply_deferred_while_engine_running(lab_env, ledger_snapshot,
                                                    monkeypatch):
    import operations.quality as quality
    monkeypatch.setattr(quality, "default_engine_guard", lambda asset: True)
    with pytest.raises(HTTPException) as exc:
        api.review_apply({"kind": "promote", "strategy_id": strategy_v0})
    assert exc.value.status_code == 409
    assert "under active engine execution" in exc.value.detail
    # nothing changed
    rows = {e["strategy_id"]: e for e in api.lab_strategies()}
    assert rows[strategy_v0]["stage"] == "paper"


def test_default_engine_guard_idle_is_false(lab_env):
    from operations.quality import default_engine_guard
    assert default_engine_guard("XAUUSD") is False
