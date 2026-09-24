"""M8.1/M8.2: validated prior provider tests (research/strategy_lab/priors.py)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from research.strategy_lab.contracts import (
    PromotionStage,
    StrategyFamily,
    ValidationReport,
)
from research.strategy_lab.priors import (
    PriorProvider,
    registry_path_for,
)


def _report(strategy_id="s1", ev=0.2, passed=True, regime=None, session=None,
            regimes_allowed=None):
    gates = {"sample_size": True, "positive_ev": True, "profit_factor": True,
             "oos_pass": True, "walkforward": True, "drawdown": True,
             "survivability": True}
    if not passed:
        gates["positive_ev"] = False
    return ValidationReport(
        strategy_id=strategy_id, asset="XAUUSD", samples=100,
        win_rate=0.55, expected_value=ev, profit_factor=1.4,
        max_drawdown=2.0, oos_ev=ev * 0.8, monte_carlo_survival=0.9,
        regime_concentration=regime or {"bullish/normal": ev},
        session_concentration=session or {"london": ev},
        passed=passed, gates=gates,
    )


def _dump_entries(tmp_path, entries):
    path = str(tmp_path / "registry.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False)
    return path


def _entry(strategy_id, stage, ev=0.2, passed=True):
    return {
        "strategy_id": strategy_id,
        "variant_hash": "h",
        "family": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL.value,
        "asset": "XAUUSD",
        "stage": stage.value,
        "validation": _report(strategy_id, ev=ev, passed=passed).as_dict(),
        "history": ["registered#research"],
    }


def test_provider_exposes_only_eligible_stages(tmp_path):
    path = _dump_entries(tmp_path, [
        _entry("s:research", PromotionStage.RESEARCH),
        _entry("s:candidate", PromotionStage.CANDIDATE),
        _entry("s:validated", PromotionStage.VALIDATED),
        _entry("s:paper", PromotionStage.PAPER),
        _entry("s:production", PromotionStage.PRODUCTION),
        _entry("s:quarantined", PromotionStage.QUARANTINED),
    ])
    p = PriorProvider(path)
    assert p.load() == 3
    ids = {x.strategy_id for x in p.all()}
    assert ids == {"s:validated", "s:paper", "s:production"}


def test_failed_validation_never_becomes_prior(tmp_path):
    path = _dump_entries(tmp_path, [
        dict(_entry("s:paper-fail", PromotionStage.PAPER, ev=-0.3, passed=False)),
    ])
    p = PriorProvider(path)
    assert p.load() == 0
    assert p.all() == []


def test_missing_registry_is_graceful(tmp_path):
    p = PriorProvider(str(tmp_path / "nope.json"))
    assert p.load() == 0
    assert p.best_for(asset="XAUUSD") is None


def test_lookup_filters_by_asset_and_family(tmp_path):
    path = _dump_entries(tmp_path, [
        dict(_entry("x", PromotionStage.PRODUCTION), **{"asset": "XAUUSD"}),
        dict(_entry("b", PromotionStage.PRODUCTION),
             **{"asset": "BTCUSD",
                "validation": ValidationReport(
                    strategy_id="b", asset="BTCUSD", samples=10, win_rate=0.5,
                    expected_value=0.2, profit_factor=1.4, max_drawdown=1.0,
                    oos_ev=0.1, monte_carlo_survival=0.9, passed=True,
                    gates={"positive_ev": True}).as_dict()}),
    ])
    p = PriorProvider(path)
    p.load()
    assert {x.strategy_id for x in p.by_asset("xauusd")} == {"x"}
    assert {x.strategy_id for x in p.by_asset("btcusd")} == {"b"}
    assert p.by_family(StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL.value)


def test_best_for_changes_conditional_edge_by_regime(tmp_path):
    path = _dump_entries(tmp_path, [
        dict(_entry("s:weak", PromotionStage.PRODUCTION, ev=0.05)),
        dict(_entry("s:strong", PromotionStage.PRODUCTION, ev=0.4)),
    ])
    p = PriorProvider(path)
    p.load()
    assert p.best_for(asset="XAUUSD").strategy_id == "s:strong"
    assert p.best_for(asset="XAUUSD", min_edge=0.5) is None


def test_edge_for_respects_bucket_and_min_edge(tmp_path):
    path = _dump_entries(tmp_path, [
        dict(_entry("s", PromotionStage.PRODUCTION, ev=0.2),
             **{"validation": ValidationReport(
                 strategy_id="s", asset="XAUUSD", samples=10, win_rate=0.5,
                 expected_value=0.2, profit_factor=1.4, max_drawdown=1.0,
                 oos_ev=0.1, monte_carlo_survival=0.9, passed=True,
                 regime_concentration={"sideways/high": 0.6,
                                       "bullish/normal": -0.1},
                 session_concentration={"london": 0.2},
                 gates={"positive_ev": True}).as_dict()}),
    ])
    p = PriorProvider(path)
    p.load()
    prior = p.all()[0]
    assert prior.edge_for(regime="sideways/high") == pytest.approx(0.6)
    assert prior.edge_for(regime="bullish/normal") == pytest.approx(-0.1)
    assert prior.edge_for() == pytest.approx(0.2)


def test_live_eligibility_flags():
    from research.strategy_lab.priors import PriorEdge
    live = PriorEdge(strategy_id="a", family="f", asset="XAUUSD",
                     stage="production", expected_value=0.2, win_rate=0.5,
                     samples=10, oos_ev=0.1, survival=0.8, passed=True)
    val = PriorEdge(strategy_id="b", family="f", asset="XAUUSD",
                    stage="validated", expected_value=0.2, win_rate=0.5,
                    samples=10, oos_ev=0.1, survival=0.8, passed=True)
    assert live.is_live_eligible is True
    assert val.is_live_eligible is False


def test_registry_path_for_defaults_into_lab_data():
    assert registry_path_for().endswith("registry.json")
    custom = registry_path_for("/tmp/data")
    assert custom == os.path.join("/tmp/data", "registry.json")


def test_candidate_board_blends_prior_into_priority(tmp_path):
    """M8.2: the decision layer consumes the conditional edge."""
    from decision.candidate import CandidateBoard
    from decision.thesis import Thesis, TradeDirection
    from research.strategy_lab.priors import PriorEdge

    board = CandidateBoard()
    thesis = Thesis(
        thesis_id="t1", timestamp=1.0, symbol="XAUUSD",
        direction=TradeDirection.LONG, entry_zone=[2000.0, 2000.2],
        stop_loss=1990.0, take_profit=[2030.0], invalidation=[1989.0],
        confidence=0.5, risk_reward=3.0,
    )
    plain = board.add_candidate(thesis)
    assert plain.strategy_id is None

    prior = PriorEdge(strategy_id="s:prod", family="ict_liquidity_sweep_reversal",
                      asset="XAUUSD", stage="production", expected_value=0.9,
                      win_rate=0.6, samples=100, oos_ev=0.7, survival=0.9,
                      passed=True, regime_edge={"bullish/normal": 0.9})
    boosted = board.add_candidate(thesis, prior=prior)
    assert boosted.strategy_id == "s:prod"
    assert boosted.strategy_stage == "production"
    assert boosted.priority >= plain.priority
    assert boosted.strategy_edge["stage"] == "production"


def test_default_provider_reloads_on_registry_change(tmp_path):
    """G2 (appendix B): a governance transition written to registry.json is
    picked up by the SAME cached provider — no process restart required."""
    from research.strategy_lab.priors import default_provider

    path = str(tmp_path / "registry.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([_entry("s:paper", PromotionStage.PAPER)], fh, ensure_ascii=False)

    prov = default_provider(str(tmp_path))
    assert [p.strategy_id for p in prov.all()] == ["s:paper"]

    # quarantine lands on disk mid-process
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([_entry("s:paper", PromotionStage.QUARANTINED)],
                  fh, ensure_ascii=False)

    prov2 = default_provider(str(tmp_path))
    assert prov2 is prov
    assert prov2.all() == []


def test_registry_stage_resolver_tracks_mid_cycle_quarantine(tmp_path):
    """G3 (appendix B): the live resolver reads current disk truth so a
    quarantine vetoes the next candidate instead of stale recorded stage."""
    from types import SimpleNamespace

    from research.strategy_lab.priors import registry_stage_resolver

    path = tmp_path / "registry.json"
    path.write_text(json.dumps([_entry("s:prod", PromotionStage.PAPER)]),
                    encoding="utf-8")

    resolve = registry_stage_resolver(str(tmp_path))
    cand = SimpleNamespace(strategy_id="s:prod")
    assert resolve(cand) == "paper"

    # quarantine lands mid-cycle
    path.write_text(json.dumps([_entry("s:prod", PromotionStage.QUARANTINED)]),
                    encoding="utf-8")
    assert resolve(cand) == "quarantined"

    assert resolve(SimpleNamespace(strategy_id="unknown")) is None
    assert resolve(SimpleNamespace(strategy_id=None)) is None
