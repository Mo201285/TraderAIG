"""Strategy Lab genome + mapping tests (STRATEGY_LAB_SPEC.md 7.1/7.3)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.strategy_lab.contracts import (
    ExitModel,
    PromotionStage,
    StrategyFamily,
    TriggerModel,
)
from research.strategy_lab.genome import GenomeGrid, VariantSpec, generate_variants, matrix_variants
from research.strategy_lab.models import family_for, variant_hash, build_variant
from research.strategy_lab.contracts import StrategyDefinition


def test_matrix_family_mapping_covers_ob_mitigation():
    assert family_for("ob_mitigation") == StrategyFamily.OB_MITIGATION
    assert family_for("sweep_ob_reaction") == StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL
    assert family_for("does_not_exist") is None


def test_variant_hash_is_stable_and_sensitive():
    a = StrategyDefinition(
        strategy_id="t", family=StrategyFamily.OB_MITIGATION, asset="XAUUSD",
        htf_tf="H1", setup_tf="M15", trigger_tf="M1",
        trigger_model=TriggerModel.ZONE_TOUCH, exit_model=ExitModel.FIXED_R,
        params={"min_rr": 1.5})
    b = StrategyDefinition(
        strategy_id="t", family=StrategyFamily.OB_MITIGATION, asset="XAUUSD",
        htf_tf="H1", setup_tf="M15", trigger_tf="M1",
        trigger_model=TriggerModel.ZONE_TOUCH, exit_model=ExitModel.FIXED_R,
        params={"min_rr": 2.0})
    assert variant_hash(a) == variant_hash(a)
    assert variant_hash(a) != variant_hash(b)


def test_generate_variants_deduped_and_bounded():
    vs = generate_variants(StrategyFamily.OB_MITIGATION, "XAUUSD")
    assert len(vs) >= 3
    assert len(vs) <= 8
    hashes = {v.variant_hash for v in vs}
    assert len(hashes) == len(vs)


def test_generate_variants_deterministic():
    a = generate_variants(StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "BTCUSD")
    b = generate_variants(StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "BTCUSD")
    assert [v.variant_hash for v in a] == [v.variant_hash for v in b]


def test_matrix_variants_skips_unmapped_and_dedups_families():
    vs = matrix_variants(["ob_mitigation", "nope", "breaker"], "XAUUSD")
    fams = {v.family for v in vs}
    assert fams == {StrategyFamily.OB_MITIGATION, StrategyFamily.STRUCTURE_CHOCH_REVERSAL}
    # breaker + fvg_flip map to the same lab family; both matrix ids together
    # must not blow up the strategy count with colliding strategy_ids.
    vs_full = matrix_variants(
        ["liquidity_choch_fvg", "fvg_flip", "breaker"], "XAUUSD")
    ids = [v.definition.strategy_id for v in vs_full]
    assert len(ids) == len(set(ids))
    assert len(vs_full) <= 8 * len({family_for(i) for i in
                                    ["liquidity_choch_fvg", "fvg_flip", "breaker"]
                                    if family_for(i) is not None})


def test_grid_serialization():
    grid = GenomeGrid(
        family=StrategyFamily.OB_MITIGATION,
        default_params={"min_rr": 1.5},
        specs=(VariantSpec(exit_model=ExitModel.FIXED_R, min_rr=2.0),))
    d = grid.as_dict()
    assert d["family"] == "ob_mitigation"
    assert d["specs"][0]["min_rr"] == 2.0


def test_promotion_stage_ordering():
    assert PromotionStage.RESEARCH.promotes_to(PromotionStage.VALIDATED)
    assert not PromotionStage.PRODUCTION.promotes_to(PromotionStage.PAPER)
    assert not PromotionStage.QUARANTINED.promotes_to(PromotionStage.CANDIDATE)


def test_build_variant_carries_hash():
    v = build_variant(StrategyDefinition(
        strategy_id="t", family=StrategyFamily.OB_MITIGATION, asset="XAUUSD",
        htf_tf="H1", setup_tf="M15", trigger_tf="M1"))
    assert v.variant_hash == variant_hash(v.definition)
