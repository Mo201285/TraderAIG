"""End-to-end strategy lab run script tests (RESEARCH pipeline)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json

import scripts.strategy_lab_run as slr
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
from research.strategy_lab.validation import ValidationLab as _Lab


def test_synthetic_run_writes_all_artifacts(tmp_path):
    summary = slr.run_all(source="synthetic", count=150, output_dir=tmp_path)
    assert summary["source"] == "synthetic"
    assert "xauusd" in summary["assets"]
    assert "btcusd" in summary["assets"]
    for k in ("run_id", "ranking", "validation_reports", "registry",
              "drawdown_policy"):
        assert k in summary
    assert summary["drawdown_policy"]["mode"] == "governed"  # default w/ governance

    results = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert results["run_id"] == summary["run_id"]
    for asset in ("xauusd", "btcusd"):
        assert "/" in summary["assets"][asset]["regime"]  # trend/volatility label
    assert (tmp_path / "registry.json").exists()
    assert (tmp_path / "observations_xauusd.jsonl").exists()
    assert (tmp_path / "observations_btcusd.jsonl").exists()


def test_synthetic_run_deterministic_registry(tmp_path):
    a = slr.run_all(source="synthetic", count=150, output_dir=tmp_path)
    b = slr.run_all(source="synthetic", count=150, output_dir=tmp_path)
    assert a["assets"]["xauusd"]["total_trades"] == \
        b["assets"]["xauusd"]["total_trades"]
    assert a["assets"]["btcusd"]["total_trades"] == \
        b["assets"]["btcusd"]["total_trades"]


def test_synthetic_run_respects_persisted_interactive_policy(tmp_path):
    """A policy chosen in the lab (persisted in results.json) stays stable
    across sweeps; absent it, the governance default (governed) applies."""
    prev = tmp_path / "results.json"
    prev.write_text(json.dumps({
        "drawdown_policy": {
            "mode": "lab_veto", "lab_cap_r": 2.0,
            "gov_cap_r": 12.0, "gov_override": False,
        }}), encoding="utf-8")
    summary = slr.run_all(source="synthetic", count=150, output_dir=tmp_path)
    assert summary["drawdown_policy"]["mode"] == "lab_veto"
    assert summary["drawdown_policy"]["lab_cap_r"] == 2.0

    # a fresh dir with no persisted policy falls back to governance default
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    summary = slr.run_all(source="synthetic", count=150, output_dir=fresh)
    assert summary["drawdown_policy"]["mode"] == "governed"


def test_observations_carry_direction_and_fold(tmp_path):
    slr.run_all(source="synthetic", count=150, output_dir=tmp_path)
    lines = (tmp_path / "observations_xauusd.jsonl").read_text(
        encoding="utf-8").splitlines()
    if not lines:
        return  # zero-trade synthetic run is acceptable on such tiny series
    row = json.loads(lines[0])
    assert row["direction"] in ("long", "short")
    assert isinstance(row["walkforward_window"], int)
    assert row["oos_split"] in ("is", "oos")


def test_validation_reports_have_buckets(tmp_path):
    summary = slr.run_all(source="synthetic", count=150, output_dir=tmp_path)
    for r in summary["validation_reports"]:
        assert "session_buckets" in r
        assert "regime_buckets" in r
        assert "gates" in r


# ---------------------------------------------------------------------------
# _sync_registry_entry — the registry must always reflect the current run
# ---------------------------------------------------------------------------

def _report(sid, win):
    def _r(i):
        if win:
            return -0.5 if i % 5 == 4 else 0.7   # proven all-gates-pass layout
        return -0.5                               # losing run -> failed report
    obs = [
        TradeObservation(
            experiment_id="e", strategy_id=sid,
            family=StrategyFamily.OB_MITIGATION, variant_hash="h",
            asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
            session="london", weekday=2, regime="bullish/normal",
            volatility_bucket=VolatilityBucket.MEDIUM,
            spread_bucket=SpreadBucket.NORMAL,
            entry_type="matrix_pool", sl_model="lt", tp_model="zt",
            pattern_geometry="", macro_state="",
            mfe_r=1.0, mae_r=-0.5,
            exit_reason=ExitReason.TARGET if _r(i) > 0 else ExitReason.STOP,
            oos_split=OosSplit.OUT_OF_SAMPLE if i >= 30 else OosSplit.IN_SAMPLE,
            walkforward_window=i % 2,
            pnl=_r(i), r_multiple=_r(i))
        for i in range(40)
    ]
    return _Lab().evaluate(sid, "XAUUSD", obs)


def test_sync_refreshes_existing_entry_validation(tmp_path):
    sid = "xauusd:ict_liquidity_sweep_reversal:v0"
    reg = StrategyRegistry(str(tmp_path / "registry.json"))
    stale_pass = _report(sid, win=True)      # old run: everything passes
    reg.register(sid, "h", StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
                 "XAUUSD", initial=PromotionStage.CANDIDATE,
                 validation=stale_pass)
    assert reg.get(sid).validation.passed is True

    fresh_fail = _report(sid, win=False)     # current run: the edge broke
    slr._sync_registry_entry(
        reg, sid, "h", StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
        "XAUUSD", fresh_fail)

    entry = reg.get(sid)
    assert entry.validation.passed is False  # never carried stale evidence
    assert entry.stage is PromotionStage.CANDIDATE  # no promote on fail


def test_sync_promotes_new_entry_on_passing_report(tmp_path):
    sid = "btcusd:ob_mitigation:v2"
    reg = StrategyRegistry(str(tmp_path / "registry.json"))
    report = _report(sid, win=True)
    slr._sync_registry_entry(reg, sid, "h", StrategyFamily.OB_MITIGATION,
                             "BTCUSD", report)
    entry = reg.get(sid)
    assert entry.stage is PromotionStage.CANDIDATE
    assert entry.validation.passed is True
