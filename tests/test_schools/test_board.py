"""SchoolBoard: source/confirmation/gate layering + live feedback loop."""
import pytest

from schools import quant
from schools.board import SchoolBoard
from core.contracts import (LiquidityState, MarketStructure, RegimeSnapshot,
                            TradingSession, TradeDirection, TrendDirection,
                            VolatilityRegime)
from core.events import bus, EventType

from .conftest import swing_path, tagged_record


@pytest.fixture(autouse=True)
def clean_global_gates():
    from schools import macro
    from .conftest import reset_school_runtime
    reset_school_runtime()
    macro.macro_school._context = macro.macro_school._context.__class__()
    macro.macro_school.blackout_interventions = 0
    yield
    reset_school_runtime()
    macro.macro_school._context.calendar = []
    macro.macro_school._context.risk_off = False


def regime():
    return RegimeSnapshot(snapshot_id="R1", timestamp=1.0, symbol="XAUUSD",
                          trend=TrendDirection.BULLISH,
                          structure=MarketStructure.IMPULSE,
                          volatility=VolatilityRegime.NORMAL,
                          session=TradingSession.LONDON,
                          liquidity=LiquidityState.MEDIUM,
                          confidence=0.7)


def seed_quant(school="structure", pattern="trend_continuation", pnl=1.0, n=5):
    quant.quant_governor.learn(
        [tagged_record(school, pattern, "bullish/medium", pnl)
         for _ in range(n)])


def test_board_selects_strongest_confirmed_source():
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert delib.selected is not None
    assert delib.selected.direction == TradeDirection.LONG
    assert not delib.blocked
    assert delib.confidence > 0
    assert delib.confluence_kind in ("multi_source", "single_source_exception")
    assert delib.supporting_sources


def test_dedupes_correlated_sources_same_anchor():
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    anchors = [s.anchor for s in delib.suggestions if s.anchor]
    assert len(anchors) == len(set(anchors))


def test_macro_blackout_vetoes_everything():
    from schools.macro import EconomicEvent
    from schools import macro
    macro.macro_school.set_calendar([
        EconomicEvent("NFP", start=0, end=2000, impact="high", symbol="XAUUSD")])
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1000)
    assert delib.blocked
    assert delib.blocked_by == "macro"
    assert "blackout" in delib.blocked_reason


def test_risk_off_vetoes_long_technical_signal():
    from schools import macro
    macro.macro_school.set_context(risk_off=True)
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert delib.blocked
    assert delib.blocked_by == "macro"
    assert "risk-off" in delib.blocked_reason


def test_negative_expectancy_blocks_at_statistical_gate():
    quant.quant_governor.require_stats = True
    seed_quant(pnl=-1.0)
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert delib.blocked
    assert delib.blocked_by == "quant"


def test_positive_expectancy_sizes_the_trade():
    seed_quant(pnl=1.0)
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert not delib.blocked
    assert delib.size_multiplier >= 0.5


def test_emits_events_on_pass_and_veto():
    from schools import macro
    macro.macro_school.set_context(risk_off=True)
    seen = []
    bus.subscribe(EventType.SCHOOL_VETO, lambda e: seen.append(e.payload))
    SchoolBoard().deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert any(s["by"] == "macro" for s in seen)


def test_attribution_reaches_ledger_record_for_filled_ticket():
    from learning.experience import ExperienceRecord
    board = SchoolBoard()
    board.attribute_ticket("T-9", {"school_id": "structure",
                                   "pattern": "trend_continuation",
                                   "regime_key": "bullish/medium"})
    rec = ExperienceRecord(record_id="mt5-deal:T-9",
                           decision_id="mt5-deal:T-9",
                           timestamp=1.0,
                           actual_result={"pnl": 0.0, "filled": True},
                           metadata={})
    board.attach_attribution([rec])
    assert rec.metadata["school_id"] == "structure"
    assert rec.metadata["pattern"] == "trend_continuation"
    assert rec.metadata["filled"] is True
    n = board.learn_from_ledger([rec])
    assert n == 1


def test_school_board_runs_inside_trading_loop():
    """The school-board branch must execute through TradingLoop.on_new_candle
    without exceptions and emit a deliberation event for a real setup."""
    from core.state import AccountState, state
    from core.pipeline import TradingLoop
    from core.events import bus, EventType

    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    seen = []
    bus.subscribe(EventType.SCHOOL_DELIBERATED, lambda e: seen.append(e.payload))

    loop = TradingLoop("XAUUSD", enable_execution=False, use_school_board=True)
    loop.on_new_candle(swing_path())

    assert seen, "school deliberation must run inside the pipeline"
    assert seen[0]["symbol"] == "XAUUSD"


def snapshot(trend="bullish", structure="impulse"):
    return RegimeSnapshot(snapshot_id="HTF", timestamp=1.0, symbol="XAUUSD",
                          trend=TrendDirection(trend),
                          structure=MarketStructure(structure),
                          volatility=VolatilityRegime.NORMAL,
                          session=TradingSession.LONDON,
                          liquidity=LiquidityState.MEDIUM,
                          confidence=0.8)


def test_htf_context_reported_and_aligned_kept():
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(),
                             now=1.0, htf=snapshot("bullish", "impulse"))
    assert delib.htf_key == "bullish/impulse"
    assert delib.selected is not None
    assert delib.selected.pattern == "trend_continuation"
    assert delib.selected.meta.get("htf_align") == "aligned"


def test_htf_against_trend_removes_continuation():
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(),
                             now=1.0, htf=snapshot("bearish", "breakdown"))
    assert delib.htf_key == "bearish/breakdown"
    assert not any(s.pattern == "trend_continuation" for s in delib.suggestions)
    ht_marks = [g for g in delib.gates if g["school"] == "htf"]
    assert ht_marks and any(g["kind"] == "reject" for g in ht_marks)


def test_no_htf_keeps_board_neutral():
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert delib.htf_key == "?"
    assert delib.selected is not None
    assert delib.selected.meta.get("htf_align") is None

def test_single_source_low_confidence_is_not_clean_exception(monkeypatch):
    from schools import registry
    from schools.base import SchoolEvidence, SchoolTier, Suggestion

    def only_one_source(candles, symbol, regime=None, zones_from_others=None, now=None):
        ev = SchoolEvidence(
            school_id="structure",
            tier=SchoolTier.SOURCE,
            symbol=symbol,
            timestamp=now or 0.0,
        )
        ev.suggestions = [Suggestion(
            school_id="structure",
            pattern="trend_continuation",
            direction=TradeDirection.LONG,
            entry_zone=[100.0, 101.0],
            stop_loss=99.0,
            take_profit=[103.0],
            invalidation=99.0,
            confidence=0.55,
            anchor="sw:test",
            meta={},
        )]
        return ev

    def no_source(candles, symbol, regime=None, zones_from_others=None, now=None):
        return SchoolEvidence(
            school_id="ict",
            tier=SchoolTier.SOURCE,
            symbol=symbol,
            timestamp=now or 0.0,
        )

    monkeypatch.setattr(registry.structure.structure_school, "evaluate", only_one_source)
    monkeypatch.setattr(registry.ict.ict_school, "evaluate", no_source)
    monkeypatch.setattr(registry.wyckoff.wyckoff_school, "evaluate", no_source)
    monkeypatch.setattr(registry.institutional.institutional_school, "evaluate", no_source)

    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert not delib.blocked
    assert delib.selected is not None
    assert delib.confluence_kind == "single_source_exception"


def test_single_source_high_confidence_can_pass_as_exception(monkeypatch):
    from schools import registry
    from schools.base import SchoolEvidence, SchoolTier, Suggestion

    def only_one_source(candles, symbol, regime=None, zones_from_others=None, now=None):
        ev = SchoolEvidence(
            school_id="structure",
            tier=SchoolTier.SOURCE,
            symbol=symbol,
            timestamp=now or 0.0,
        )
        ev.suggestions = [Suggestion(
            school_id="structure",
            pattern="trend_continuation",
            direction=TradeDirection.LONG,
            entry_zone=[100.0, 101.0],
            stop_loss=99.0,
            take_profit=[103.0],
            invalidation=99.0,
            confidence=0.72,
            anchor="sw:test",
            meta={},
        )]
        return ev

    def no_source(candles, symbol, regime=None, zones_from_others=None, now=None):
        return SchoolEvidence(
            school_id="ict",
            tier=SchoolTier.SOURCE,
            symbol=symbol,
            timestamp=now or 0.0,
        )

    monkeypatch.setattr(registry.structure.structure_school, "evaluate", only_one_source)
    monkeypatch.setattr(registry.ict.ict_school, "evaluate", no_source)
    monkeypatch.setattr(registry.wyckoff.wyckoff_school, "evaluate", no_source)
    monkeypatch.setattr(registry.institutional.institutional_school, "evaluate", no_source)

    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert not delib.blocked
    assert delib.selected is not None
    assert delib.confluence_kind == "single_source_exception"
