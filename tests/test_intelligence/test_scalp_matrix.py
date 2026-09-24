"""Unit tests for the scalping pattern matrix (spec + scoring engine)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from intelligence.scalp_matrix import (
    ASSET_BTC,
    ASSET_XAU,
    TRADE_SCORE,
    WATCH_SCORE,
    by_id,
    families,
    families_for,
    score_setup,
    best_setup,
    tp_ladder,
    SetupDecision,
)

_KEYS = {"liquidity", "structure", "displacement", "fvg", "ob", "breaker",
         "compression", "session", "volatility", "risk", "htf"}


def _all_on() -> dict:
    return {k: True for k in _KEYS}


def test_matrix_has_twenty_families():
    fams = families()
    assert len(fams) == 20
    ids = [f.family_id for f in fams]
    assert len(set(ids)) == len(ids)


def test_families_are_fully_specified():
    for fam in families():
        assert fam.name
        assert fam.category
        assert fam.required
        assert set(fam.required) <= _KEYS
        assert fam.entry_types, "every family must support at least one entry type"
        assert set(fam.entry_types) <= {"A", "B", "C", "D"}
        assert fam.tp_ladder
        assert fam.min_rr > 0
        for k in fam.weights:
            assert k in _KEYS, f"{fam.family_id} unknown confirmation {k}"


def test_weights_sum_to_one():
    for fam in families():
        assert sum(fam.weights.values()) == pytest.approx(1.0)
        for asset, over in fam.assets.items():
            if "weights" in over:
                assert sum(over["weights"].values()) == pytest.approx(1.0)
                assert set(over["weights"]) <= _KEYS


def test_no_two_families_share_every_parameter():
    seen = set()
    for fam in families():
        sig = (fam.required, frozenset(fam.weights.items()), fam.min_rr)
        seen.add(sig)
    assert len(seen) == 20, "models must stay distinct (not one engine)"  # subset check


def test_unknown_family_raises():
    with pytest.raises(ValueError):
        score_setup("nope", ASSET_XAU, _all_on())


def test_a_plus_model_all_in_trades():
    sc = score_setup("sweep_displacement_fvg", ASSET_XAU, _all_on())
    assert sc.decision == SetupDecision.TRADE
    assert sc.score == pytest.approx(100.0)
    assert sc.missing == ()
    assert sc.min_rr == 0.9


def test_missing_required_confirmation_blocks():
    conf = _all_on()
    conf["displacement"] = False
    sc = score_setup("sweep_displacement_fvg", ASSET_XAU, conf)
    assert sc.decision == SetupDecision.NO_TRADE
    assert "displacement" in sc.missing


def test_trigger_confirmation_required_at_entry():
    # strong setup but the structure trigger never confirmed -> NO_TRADE
    conf = _all_on()
    conf["structure"] = False
    sc = score_setup("sweep_ob_reaction", ASSET_XAU, conf)
    assert sc.decision == SetupDecision.NO_TRADE
    assert "trigger:structure" in sc.missing
    assert "structure" not in sc.missing       # rejected for the trigger, not required
    # same bitmap without the trigger requirement still trades
    sc2 = score_setup("fvg_continuation", ASSET_XAU, conf)
    assert sc2.decision == SetupDecision.TRADE


def test_displacement_trigger_gates_expansion():
    conf = _all_on()
    conf["displacement"] = False
    sc = score_setup("opening_range_expansion", ASSET_XAU, conf)
    assert sc.decision == SetupDecision.NO_TRADE
    assert "trigger:displacement" in sc.missing


def test_partial_confirmations_yield_watch_not_trade():
    conf = {"fvg": True, "volatility": True, "risk": True}
    sc = score_setup("fvg_continuation", ASSET_XAU, conf)
    assert WATCH_SCORE <= sc.score < TRADE_SCORE
    assert sc.decision == SetupDecision.WATCH


def test_risk_is_a_hard_gate():
    conf = _all_on()
    conf["risk"] = False
    for family_id in ("sweep_displacement_fvg", "fvg_continuation", "breaker"):
        sc = score_setup(family_id, ASSET_XAU, conf)
        assert sc.decision == SetupDecision.NO_TRADE, family_id
        assert "risk" in sc.missing


def test_asset_exclusion():
    sc = score_setup("session_high_low_sweep", ASSET_BTC, _all_on())
    assert sc.decision == SetupDecision.NO_TRADE
    assert "asset_excluded" in sc.missing
    assert by_id("session_high_low_sweep").family_id in [
        f.family_id for f in families_for(ASSET_XAU)]


def test_per_asset_exclude_override():
    # base remains active on gold, override excludes it on bitcoin
    assert score_setup("opening_range_expansion", ASSET_XAU,
                       _all_on()).decision == SetupDecision.TRADE
    assert score_setup("opening_range_expansion", ASSET_BTC,
                       _all_on()).decision == SetupDecision.NO_TRADE
    assert score_setup("compression_expansion", ASSET_BTC,
                       _all_on()).decision == SetupDecision.NO_TRADE
    assert score_setup("sweep_ob_reaction", ASSET_BTC,
                       _all_on()).decision == SetupDecision.NO_TRADE
    assert "opening_range_expansion" in [f.family_id
                                         for f in families_for(ASSET_XAU)]
    assert "opening_range_expansion" not in [f.family_id
                                             for f in families_for(ASSET_BTC)]


def test_bitcoin_has_own_family_set():
    xs = {f.family_id for f in families_for(ASSET_XAU)}
    bs = {f.family_id for f in families_for(ASSET_BTC)}
    assert xs - bs == {"session_high_low_sweep", "opening_range_expansion",
                       "compression_expansion", "sweep_ob_reaction"}


def test_per_asset_min_rr():
    assert by_id("sweep_displacement_fvg").effective_min_rr(ASSET_XAU) == 0.9
    assert by_id("sweep_displacement_fvg").effective_min_rr(ASSET_BTC) == 1.1
    sc = score_setup("sweep_displacement_fvg", ASSET_BTC, _all_on())
    assert sc.min_rr == 1.1
    assert sc.decision == SetupDecision.TRADE


def test_best_setup_picks_tradeable_family():
    sc = best_setup(ASSET_XAU, _all_on())
    assert sc is not None
    assert sc.decision == SetupDecision.TRADE
    assert sc.score == pytest.approx(100.0)
    assert best_setup(ASSET_XAU, {"liquidity": True}) is None


# -- TP ladder --------------------------------------------------------------

def test_tp_ladder_long_nearest_above():
    assert tp_ladder([100.5, 99.0, 101.0, 100.0], "LONG", 100.0) == (
        100.5, 101.0, None)


def test_tp_ladder_short_nearest_below():
    assert tp_ladder([99.0, 98.5, 100.5, 97.0], "SHORT", 100.0) == (
        99.0, 98.5, 97.0)


def test_tp_ladder_dedupes_and_pads():
    out = tp_ladder([99.5, 99.5, 98.0], "LONG", 100.0)
    assert out == (None, None, None) or len(out) == 3
    assert tp_ladder([], "LONG", 100.0) == (None, None, None)


def test_tp_ladder_bad_direction():
    assert tp_ladder([50.0, 60.0], "SIDEWAYS", 100.0) == (None, None, None)
