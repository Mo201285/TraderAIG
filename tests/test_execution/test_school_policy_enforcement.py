"""Tests for live/paper school policy enforcement in TradingLoop.

The live core is the approved strategy: ICT/SMC (zone-ownership) and
Institutional Flow (raw liquidity events). Everything else runs under
evaluation (research) and is excluded from live execution.
"""

from types import SimpleNamespace

from core.contracts import TradeDirection
from core.pipeline import TradingLoop
from schools.board import Deliberation


def _delib(school_id="ict", confluence_kind="single_source_exception",
           confidence=0.7):
    d = Deliberation("XAUUSD", 1.0)
    d.selected = SimpleNamespace(
        school_id=school_id,
        pattern="trend_continuation",
        direction=TradeDirection.LONG,
        meta={},
        anchor="a1",
        confidence=confidence,
    )
    d.confluence_kind = confluence_kind
    return d


def test_live_allows_smc_single_source_exception():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    assert loop._school_live_allowed(
        _delib("ict", "single_source_exception", confidence=0.7)) is True


def test_live_blocks_weak_single_source_below_confidence_floor():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    assert loop._school_live_allowed(
        _delib("ict", "single_source_exception", confidence=0.4)) is False
    # promotion is bookkeeping, not a license: no confidence field = blocked
    d = _delib("ict", "single_source_exception")
    del d.selected.confidence
    assert loop._school_live_allowed(d) is False


def test_live_blocks_research_school_even_if_exception():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    assert loop._school_live_allowed(_delib("structure", "single_source_exception")) is False
    assert loop._school_live_allowed(_delib("ai", "single_source_exception")) is False


def test_research_tag_never_trades_live():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    d = _delib("ict", "single_source_exception", confidence=0.9)
    d.selected.meta["research"] = True
    assert loop._school_live_allowed(d) is False


def test_live_allows_multi_source_for_core_selection():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    assert loop._school_live_allowed(_delib("ict", "multi_source")) is True
    assert loop._school_live_allowed(_delib("institutional", "multi_source")) is True


def test_paper_mode_keeps_analysis_available():
    loop = TradingLoop("XAUUSD", enable_execution=False, use_school_board=True)
    assert loop._school_live_allowed(_delib("institutional", "single_source_exception")) is True
    assert loop._school_live_allowed(_delib("structure", "single_source_exception")) is True
