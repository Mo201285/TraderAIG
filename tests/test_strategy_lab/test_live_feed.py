"""L3 (appendix B): real executed performance feeds the strategy corpus."""

import pytest

from learning.experience import ExperienceRecord
from research.strategy_lab.contracts import PromotionStage, StrategyFamily
from research.strategy_lab.live_feed import (
    default_registry, feed_registry_from_ledger)
from research.strategy_lab.registry import StrategyRegistry


def _rec(rid, sid, pnl):
    return ExperienceRecord(
        record_id=rid, decision_id=f"d:{rid}", timestamp=1.0,
        actual_result={"pnl": pnl, "filled": True, "origin": "system"},
        metadata={"strategy_id": sid},
    )


def _registry(tmp_path):
    r = StrategyRegistry(str(tmp_path / "registry.json"))
    for sid in ("s:one", "s:small"):
        r.register(sid, "h1", StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
                   "XAUUSD", initial=PromotionStage.PAPER)
    return r


def test_feed_attaches_live_performance_to_registered_strategies(tmp_path):
    registry = _registry(tmp_path)
    records = [_rec(f"r{i}", "s:one", 10.0) for i in range(30)]
    records += [_rec(f"r{i}", "s:small", -5.0) for i in range(5)]

    outcome = feed_registry_from_ledger(registry, records, min_trades=30)

    assert "s:one" in outcome["fed"]
    assert outcome["fed"]["s:one"]["total_trades"] == 30
    assert outcome["fed"]["s:one"]["net_pnl"] == pytest.approx(300.0)
    # too-few and un-stamped strategies are skipped, never faked into evidence
    assert outcome["skipped"]["s:small"].startswith("too_few_trades")
    assert registry.get("s:one").live_performance["source"] == "experience_ledger"


def test_feed_never_transitions_stage(tmp_path):
    registry = _registry(tmp_path)
    before = registry.get("s:one").stage
    records = [_rec(f"x{i}", "s:one", 1.0) for i in range(40)]

    feed_registry_from_ledger(registry, records)

    assert registry.get("s:one").stage is before  # metadata only, no promote
    assert registry.get("s:one").history[-1].startswith("live_feed#")


def test_registry_roundtrip_preserves_live_performance(tmp_path):
    registry = _registry(tmp_path)
    feed_registry_from_ledger(
        registry, [_rec(f"y{i}", "s:one", 2.0) for i in range(31)])

    reloaded = StrategyRegistry(str(tmp_path / "registry.json"))
    reloaded.load()

    entry = reloaded.get("s:one")
    assert entry.live_performance["total_trades"] == 31
    assert entry.as_dict()["live_performance"]["net_pnl"] == pytest.approx(62.0)


def test_default_registry_points_at_lab_data_dir(tmp_path, monkeypatch):
    from research.strategy_lab import priors
    monkeypatch.setattr(priors, "registry_path_for",
                        lambda data_dir=None: str(tmp_path / "registry.json"))
    reg = default_registry()
    assert reg.load() == 0  # no file yet -> clean empty registry
