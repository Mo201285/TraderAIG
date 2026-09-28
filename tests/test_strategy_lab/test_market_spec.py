"""Canonical market specification for the strategy lab (28.6 / 3.1).

The specification must be *derived from the detector it describes*, must
identify ambiguous user language instead of silently interpreting it, and must
report the real provenance of the series a run consumed — including admitting
when that series cannot be attributed to a live source.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from core.contracts import Candle
from research.strategy_lab.contracts import StrategyFamily
from research.strategy_lab.market_spec import (
    LAB_BAR_TIMEFRAME,
    MIN_FEATURE_BARS,
    MIN_SPLIT_BARS,
    detect_ambiguity,
    feature_specification,
    market_provenance,
    required_features,
    required_market_data,
)


def _bars(count: int = 300, step: float = 60.0) -> list:
    base = time.time() - count * step
    return [Candle(symbol="XAUUSD", timeframe="M1", time=base + i * step,
                   open=100 + i, high=101 + i, low=99 + i, close=100.5 + i,
                   volume=1.0, tick_volume=10.0)
            for i in range(count)]


# -- ambiguity detection (28.6) --------------------------------------------

def test_ambiguous_phrases_are_identified_with_a_measured_definition():
    found = detect_ambiguity("buy after a strong move near support with high volume")
    phrases = {a["phrase"] for a in found}
    assert {"strong move", "near support", "high volume"} <= phrases
    for item in found:
        # every ambiguous term must come with the definition actually applied
        assert item["meaning"] and item["resolved_to"]


def test_ambiguity_detection_is_case_and_order_insensitive():
    a = detect_ambiguity("Strong Move then pullback")
    b = detect_ambiguity("after a strong move")
    assert a[0]["phrase"] == b[0]["phrase"] == "strong move"


def test_duplicate_phrase_is_reported_once():
    found = detect_ambiguity("strong move, then another strong move later")
    assert [a["phrase"] for a in found].count("strong move") == 1


def test_no_ambiguity_found_returns_empty_not_a_guess():
    assert detect_ambiguity("") == []
    assert detect_ambiguity("buy XAUUSD at 2400, stop 2380, target 2450") == []


# -- required features (derived from the live FamilySpec) -------------------

def test_required_features_come_from_the_real_family_spec():
    from intelligence.scalp_matrix import by_id

    spec = by_id("fvg_continuation")
    feats = required_features("fvg_continuation")
    # 'fvg' is a hard requirement of that family -> the FVG features must be
    # in the specification, or the spec is lying about what the run needs.
    assert "fvg" in spec.required
    assert {"fvg", "fvg_side"} <= set(feats)
    assert {"atr", "close", "session", "regime"} <= set(feats)


def test_feature_specification_unions_every_matrix_family_of_a_lab_family():
    spec = feature_specification(StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL)
    assert spec["resolved"] is True
    assert len(spec["matrix_families"]) > 1
    # liquidity + session + structure are all required somewhere in that union
    assert {"liquidity", "session", "structure"} <= set(
        spec["confirmations_required"])
    assert spec["needs_liquidity_pools"] is True


def test_unknown_family_says_it_is_unresolved_instead_of_guessing():
    spec = feature_specification("not_a_real_family")
    assert spec["resolved"] is False
    assert spec["matrix_families"] == []
    assert spec["confirmations_required"] == []
    # ...and still reports the base surface every run needs
    assert {"atr", "close", "time"} <= set(spec["features"])


def test_resolved_false_for_no_family_at_all():
    assert feature_specification(None)["resolved"] is False


# -- required market data ---------------------------------------------------

def test_required_market_data_states_the_real_minimum():
    block = required_market_data("xauusd", "H1", "M15", "M1", 25000)
    assert block["symbol"] == "XAUUSD"
    assert block["timeframes"] == {"htf": "H1", "setup": "M15", "trigger": "M1"}
    assert block["required_bars"] == MIN_SPLIT_BARS
    assert block["requested_bars"] == 25000
    assert block["sufficient"] is True
    assert block["candle_fields"] == ["time", "open", "high", "low", "close"]
    # the lab replays bars, so it must not claim it needs a live two-sided quote
    assert block["requires_two_sided_quote"] is False


def test_required_market_data_flags_an_insufficient_request():
    block = required_market_data("XAUUSD", "H1", "M15", "M1", 50)
    assert block["sufficient"] is False
    assert block["requested_bars"] == 50


def test_required_market_data_normalizes_symbol_and_timeframes():
    block = required_market_data("btc-usdt", "1h", "15m", "1m", 1000)
    assert block["symbol"] == "BTCUSDT"
    assert block["timeframes"] == {"htf": "H1", "setup": "M15", "trigger": "M1"}


def test_required_market_data_states_the_timeframe_the_run_really_uses():
    """It must not claim the family setup timeframe was the replayed series.

    `strategy_lab_run.load_candles` is pinned to M1 for every source, so a
    `bar_timeframe` of `setup_tf` (M15/H1/...) was stating a requirement the
    lab never met. The definition's timeframes stay visible separately, and the
    constant is tied to the loader so it cannot drift from it.
    """
    import inspect

    from scripts.strategy_lab_run import load_candles

    block = required_market_data("XAUUSD", "H1", "M15", "M1", 1000)
    assert block["bar_timeframe"] == "M1" == LAB_BAR_TIMEFRAME
    assert "M1" in block["bar_timeframe_note"]
    assert block["timeframes"] == {"htf": "H1", "setup": "M15", "trigger": "M1"}
    # the loader really is M1: that is where the constant comes from
    assert '"M1"' in inspect.getsource(load_candles)


def test_required_market_data_records_session_requirements():
    block = required_market_data("XAUUSD", "H1", "M15", "M1", 1000,
                                 sessions=("london",))
    assert block["requires_sessions"] == ["london"]


def test_min_bars_exceed_the_feature_floor():
    assert MIN_SPLIT_BARS > MIN_FEATURE_BARS


# -- provenance (3.1) -------------------------------------------------------

def test_provenance_of_a_synthetic_run_is_not_live():
    prov = market_provenance("synthetic", _bars(300), asset="XAUUSD")
    assert prov["live"] is False
    assert prov["attributed"] is False
    assert prov["freshness"] == "unattributed"
    assert prov["bars"] == 300
    assert prov["first_bar"] is not None and prov["last_bar"] > prov["first_bar"]
    assert prov["age_seconds"] >= 0.0


def test_provenance_with_a_plane_read_carries_the_real_source():
    read = {"symbol": "XAUUSD", "timeframe": "M15", "source": "mt5",
            "version": 7, "quote_source": "mt5", "freshness": "fresh",
            "single_source": True, "bars": 300, "read_at": time.time()}
    prov = market_provenance("mt5", _bars(300), plane_read=read)
    assert prov["live"] is True
    assert prov["attributed"] is True
    assert prov["source_name"] == "mt5"
    assert prov["source_version"] == 7
    assert prov["freshness"] == "fresh"
    assert prov["single_source"] is True
    assert prov["plane"]["version"] == 7


def test_provenance_reports_a_genuinely_mixed_read():
    read = {"symbol": "XAUUSD", "timeframe": "M15", "source": "cex",
            "quote_source": "mt5", "version": 2, "freshness": "fresh",
            "single_source": False, "bars": 100, "read_at": time.time()}
    prov = market_provenance("cex", _bars(100), plane_read=read)
    assert prov["single_source"] is False


def test_provenance_of_an_empty_series_is_honest():
    prov = market_provenance("mt5", [], asset="XAUUSD")
    assert prov["bars"] == 0
    assert prov["coverage"] == "empty"
    assert prov["first_bar"] is None and prov["last_bar"] is None


def test_provenance_span_is_computed_from_the_real_bars():
    bars = _bars(10, step=60.0)
    prov = market_provenance("csv", bars)
    assert prov["span_seconds"] == pytest.approx(9 * 60.0, abs=0.01)
