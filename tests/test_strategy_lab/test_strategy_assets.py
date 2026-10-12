"""RMI-05 Strategy Asset Layer tests.

Pins the two RMI-05 claims (asset metadata + valuation hooks on the existing
registry) and the honesty rules around them:

* metadata attaches only to a strategy that exists in the registry;
* valuation is derived from real evidence only, is bounded to [0,1], names
  every component, and reports an honest ``unproven`` when there is nothing;
* the registry itself is never modified by this layer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.strategy_lab.contracts import (
    ExitReason,
    OosSplit,
    PromotionStage,
    SpreadBucket,
    StrategyFamily,
    TradeObservation,
    VolatilityBucket,
)
from research.strategy_lab.assets import (
    StrategyAssetError,
    StrategyAssetLayer,
    StrategyAssetMetadataStore,
)
from research.strategy_lab.registry import StrategyRegistry
from research.strategy_lab.validation import ValidationLab


def _passing_report(strategy_id="s1"):
    def _r(i):
        return -0.5 if i % 5 == 4 else 0.8
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
            oos_split=OosSplit.OUT_OF_SAMPLE if i >= 80 else OosSplit.IN_SAMPLE,
            walkforward_window=i % 2,
            pnl=_r(i), r_multiple=_r(i))
        for i in range(120)
    ]
    return ValidationLab().evaluate(strategy_id, "XAUUSD", obs)


def _layer(tmp_path):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    store = StrategyAssetMetadataStore(str(tmp_path / "assets.json"))
    return StrategyAssetLayer(registry, metadata=store), registry, store


def test_unproven_valuation_when_no_evidence(tmp_path):
    layer, registry, _ = _layer(tmp_path)
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    valuation = layer.value(registry.get("s1"))
    assert valuation.score == 0.0
    assert valuation.tier == "unproven"
    assert valuation.components == {}
    assert "nothing to value" in valuation.basis


def test_valuation_from_passing_validation_is_bounded_and_explained(tmp_path):
    layer, registry, _ = _layer(tmp_path)
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    registry.attach_validation("s1", _passing_report("s1"))
    registry.promote("s1")                       # -> CANDIDATE
    registry.promote("s1", validation=_passing_report("s1"))  # -> VALIDATED
    valuation = layer.value(registry.get("s1"))
    assert 0.0 < valuation.score <= 1.0
    assert valuation.tier in ("emerging", "proven", "institutional")
    assert valuation.has_validation is True
    assert "validation_pass" in valuation.components
    assert "stage_weight" in valuation.components


def test_stage_weight_lowers_a_research_valuation(tmp_path):
    layer, registry, _ = _layer(tmp_path)
    report = _passing_report("s1")
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    registry.attach_validation("s1", report)
    research_val = layer.value(registry.get("s1")).score

    registry.register("s2", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    registry.attach_validation("s2", report)
    while registry.get("s2").stage is not PromotionStage.PRODUCTION:
        registry.promote("s2", validation=report)
    production_val = layer.value(registry.get("s2")).score
    assert production_val > research_val


def test_quarantined_strategy_is_valued_at_zero(tmp_path):
    layer, registry, _ = _layer(tmp_path)
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    registry.attach_validation("s1", _passing_report("s1"))
    registry.demote("s1", "drift")
    assert layer.value(registry.get("s1")).score == 0.0


def test_live_performance_blends_into_valuation(tmp_path):
    layer, registry, _ = _layer(tmp_path)
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    registry.promote("s1")
    registry.attach_live_performance("s1", {"realized_r": 6.0})
    valuation = layer.value(registry.get("s1"))
    assert valuation.has_live is True
    assert "live_realized_quality" in valuation.components


def test_metadata_attaches_only_to_a_registered_strategy(tmp_path):
    layer, _, _ = _layer(tmp_path)
    try:
        layer.attach_metadata("ghost", {"owner": "x"})
    except StrategyAssetError:
        pass
    else:  # pragma: no cover
        raise AssertionError("attaching metadata to an unregistered id must fail")


def test_metadata_persists_and_merges(tmp_path):
    layer, registry, store = _layer(tmp_path)
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    layer.attach_metadata("s1", {"owner": "ops", "tags": ["gold"]})
    layer.attach_metadata("s1", {"description": "sweep reversal"})
    reloaded = StrategyAssetMetadataStore(str(tmp_path / "assets.json"))
    row = reloaded.get("s1")
    assert row["owner"] == "ops"
    assert row["description"] == "sweep reversal"
    assert "tags" in row


def test_asset_view_combines_registry_metadata_and_valuation(tmp_path):
    layer, registry, _ = _layer(tmp_path)
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    registry.register("s2", "h2", StrategyFamily.ICT_FVG_CONTINUATION, "BTCUSD")
    registry.promote("s2")
    layer.attach_metadata("s2", {"owner": "ops"})
    asset = layer.asset("s2")
    assert asset.strategy_id == "s2"
    assert asset.metadata["owner"] == "ops"
    assert asset.stage is PromotionStage.CANDIDATE
    assert asset.valuation is not None
    assert len(layer.assets()) == 2
    assert layer.asset("missing") is None


def test_valuation_never_grants_a_permission(tmp_path):
    layer, registry, _ = _layer(tmp_path)
    registry.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    payload = layer.asset("s1").as_dict()
    assert payload["is_authorisation"] is False
    assert payload["trade_authority"] == "risk/governor.py"
