"""Macro / Intermarket school: calendar blackout + alignment veto."""
import pytest

from schools.macro import BLACKOUT_MINUTES, EconomicEvent, macro_school
from schools.base import VerdictKind, Suggestion
from core.contracts import TradeDirection

from .conftest import mk


@pytest.fixture(autouse=True)
def clean_macro():
    macro_school._context = macro_school._context.__class__()
    macro_school.blackout_interventions = 0
    yield
    macro_school._context.calendar = []
    macro_school._context.risk_off = False
    macro_school._context.risk_on = False


def make_sugg(direction=TradeDirection.LONG):
    return Suggestion(school_id="structure", pattern="trend_continuation",
                      direction=direction, entry_zone=[100.0, 100.5],
                      stop_loss=99.5, take_profit=[103.0], invalidation=99.5,
                      confidence=0.6, anchor="structure:1")


def test_no_event_in_window_passes():
    ev = macro_school.evaluate([mk(100, 101, 99, 100.5)], "XAUUSD", now=12345)
    assert ev.verdict.kind == VerdictKind.PASS
    assert ev.meta["blackout_interventions"] == 0


def test_high_impact_event_vetoes_and_counts():
    macro_school.set_calendar([
        EconomicEvent("NFP", start=1000, end=2000, impact="high", symbol="XAUUSD")])
    ev = macro_school.evaluate([mk(100, 101, 99, 100.5)], "XAUUSD", now=1500)
    assert ev.verdict.kind == VerdictKind.REJECT
    assert "blackout" in ev.verdict.reason
    assert macro_school.blackout_interventions == 1
    assert ev.verdict.meta["lesson_key"] == "missed_blackout_count"


def test_risk_off_blocks_long_even_when_technicals_agree():
    macro_school.set_context(risk_off=True)
    v = macro_school.gate(make_sugg(TradeDirection.LONG))
    assert v.kind == VerdictKind.REJECT
    assert "risk-off" in v.reason


def test_aligned_short_gets_cross_asset_lift():
    macro_school.set_context(dxy_trend="up", risk_off=True)
    v = macro_school.gate(make_sugg(TradeDirection.SHORT))
    assert v.kind == VerdictKind.PASS
    assert isinstance(v.size_multiplier, float) and v.size_multiplier >= 1.0


def test_blackout_window_uses_both_ends():
    e = EconomicEvent("FOMC", start=5000 - BLACKOUT_MINUTES * 60,
                      end=5000 + BLACKOUT_MINUTES * 60, impact="high")
    macro_school.set_calendar([e])
    assert e.active_at(5000 - BLACKOUT_MINUTES * 60)
    assert e.active_at(5000)
    assert e.active_at(5000 + BLACKOUT_MINUTES * 60)
    assert not e.active_at(5000 + BLACKOUT_MINUTES * 60 + 1)
