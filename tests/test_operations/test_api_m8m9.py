"""Phase 8/9 API surface tests (M8.5, M9.1, M9.2, M9.3, learning split)."""

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


def _passing_report(strategy_id="xauusd:ict_liquidity_sweep_reversal:v0"):
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
    """tmp lab data dir with validated PAPER entries (eligible priors)."""
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    live = _passing_report("xauusd:ict_liquidity_sweep_reversal:v0")
    registry.register(
        "xauusd:ict_liquidity_sweep_reversal:v0", "h",
        StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
        initial=PromotionStage.PAPER, validation=live)
    notyet = _passing_report("xauusd:ict_liquidity_sweep_reversal:v1")
    notyet.gates["positive_ev"] = False
    notyet.passed = False
    registry.register(
        "xauusd:ict_liquidity_sweep_reversal:v1", "h",
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


# ---------------------------------------------------------------------------
# M9.1 research summaries
# ---------------------------------------------------------------------------

def test_research_summary_exposes_bottlenecks(lab_env):
    out = api.research_summary()
    assert out["registered"] == 2
    assert out["by_stage"]["paper"] == 1
    assert out["by_stage"]["candidate"] == 1
    # the only failing gate (positive_ev) across all reports is a bottleneck
    fail = {b["gate"]: b["fails"] for b in out["bottlenecks"]}
    assert fail.get("positive_ev", 0) >= 1


def test_research_gates_table(lab_env):
    rows = api.research_gates()
    by_id = {r["strategy_id"]: r for r in rows}
    assert by_id["xauusd:ict_liquidity_sweep_reversal:v0"]["passed"] is True
    assert by_id["xauusd:ict_liquidity_sweep_reversal:v1"]["passed"] is False


# ---------------------------------------------------------------------------
# M9.2 promotion monitoring
# ---------------------------------------------------------------------------

def test_promotions_timeline_from_history(lab_env):
    out = api.research_promotions()
    entry = next(t for t in out["timeline"]
                 if t["strategy_id"] == "xauusd:ict_liquidity_sweep_reversal:v0")
    kinds = [e["kind"] for e in entry["events"]]
    assert "registered" in kinds           # registered#paper
    assert entry["stage"] == "paper"
    assert out["by_stage"]["paper"] == 1


# ---------------------------------------------------------------------------
# M8.4 learning split endpoint
# ---------------------------------------------------------------------------

def test_learning_split_endpoint(lab_env):
    out = api.learning_split()
    assert out["research"]["track"] == "research"
    assert out["execution"]["track"] == "execution"


# ---------------------------------------------------------------------------
# M9.3 drift endpoint
# ---------------------------------------------------------------------------

def test_drift_endpoint_read_only(lab_env, monkeypatch, ledger_snapshot):
    from learning.experience import ExperienceRecord

    def _emit():
        ledger = api.ledger
        ledger._records.append(ExperienceRecord(
            record_id="drift-1", decision_id="d", timestamp=0.0,
            actual_result={"filled": True, "pnl": -2.0, "slippage": 0.05,
                           "origin": "system"},
            metadata={"strategy_id": "xauusd:ict_liquidity_sweep_reversal:v0"}))
        for _ in range(20):
            ledger._records.append(ExperienceRecord(
                record_id=f"drift-h-{_}", decision_id="d", timestamp=0.0,
                actual_result={"filled": True, "pnl": 1.0, "slippage": 0.005,
                               "origin": "system"},
                metadata={"strategy_id":
                          "xauusd:ict_liquidity_sweep_reversal:v0"}))

    _emit()
    out = api.drift_status()
    assert out["ok"] is True
    assert out["watched"] >= 1
    assert "contract" in out           # quarantine remains a governance act
    # endpoint must not mutate the registry
    rows = {e["strategy_id"]: e for e in api.lab_strategies()}
    assert rows["xauusd:ict_liquidity_sweep_reversal:v0"]["stage"] == "paper"


# ---------------------------------------------------------------------------
# M8.5 ownership isolation in /performance
# ---------------------------------------------------------------------------

def test_performance_ownership_split(lab_env, monkeypatch, ledger_snapshot):
    from learning.experience import ExperienceRecord

    api.ledger.clear()
    api.ledger._records.append(ExperienceRecord(
        record_id="sys-1", decision_id="d", timestamp=0.0,
        actual_result={"filled": True, "pnl": 12.0, "origin": "system"}))
    api.ledger._records.append(ExperienceRecord(
        record_id="man-1", decision_id="d", timestamp=0.0,
        actual_result={"filled": True, "pnl": 99.0, "origin": "manual"}))
    both = api.performance_report()
    assert both["note"]
    assert both["system"]["total_trades"] == 1
    assert both["system"]["net_pnl"] == 12.0
    assert both["manual"]["total_trades"] == 1
    assert both["manual"]["net_pnl"] == 99.0
    only_sys = api.performance_report(ownership="system")
    assert only_sys["total_trades"] == 1


def test_performance_hydrates_ledger_from_persistence(lab_env, monkeypatch):
    """L4 (appendix B): /performance used to read the stale in-memory ledger
    after a restart. Now it hydrates from persistence like /learning/experiences,
    so a fresh process reports the persisted trades instead of an empty table."""
    import persistence.db as pdb
    import persistence.repositories as prepos
    from learning.experience import ExperienceRecord

    class _StubStore:
        def __init__(self):
            self.rows = [ExperienceRecord(
                record_id="db-1", decision_id="d", timestamp=1.0,
                actual_result={"filled": True, "pnl": 7.0, "origin": "system"})]

        def list(self, limit=500, owner_user_id=None):
            return self.rows

    monkeypatch.setattr(pdb, "persistence_enabled", lambda: True)
    monkeypatch.setattr(pdb, "make_live_session", lambda: object())
    monkeypatch.setattr(prepos, "ExperienceRepository", lambda _session: _StubStore())

    api.ledger.clear()
    try:
        out = api.performance_report()
        assert out["system"]["total_trades"] == 1
        assert out["system"]["net_pnl"] == 7.0  # came from the (fake) DB
    finally:
        api.ledger.clear()


def test_lab_live_feed_endpoint_metadata_only(lab_env, monkeypatch):
    """L3 (appendix B): POST /research/live-feed folds executed performance
    into the corpus without ever transitioning a stage (governed upgrade path
    stays intact)."""
    from learning.experience import ExperienceRecord
    from research.strategy_lab import live_feed as lf

    api.ledger.clear()
    api.ledger._records.append(ExperienceRecord(
        record_id="lf-1", decision_id="d", timestamp=0.0,
        actual_result={"filled": True, "pnl": 1.0, "origin": "system"}))
    calls = []
    try:
        monkeypatch.setattr(lf, "default_registry", lambda _d: {"fake": "reg"})
        monkeypatch.setattr(
            lf, "feed_registry_from_ledger",
            lambda reg, recs, min_trades=30:
                calls.append((reg, recs, min_trades)) or
                {"fed": {"x": {"total_trades": 31}}, "skipped": {}})
        out = api.lab_live_feed({"min_trades": 30})

        assert out["ok"] is True
        assert out["fed"] == 1
        assert out["skipped"] == {}
        assert len(calls) == 1 and calls[0][2] == 30
    finally:
        api.ledger.clear()
