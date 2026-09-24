"""Tests for dynamic vs fixed sizing policy resolution."""

from types import SimpleNamespace

from core.contracts import TradeDirection
from core.pipeline import TradingLoop
from decision.thesis import TradeCandidate
from schools.board import Deliberation


def _candidate():
    return TradeCandidate(
        candidate_id="c1",
        thesis_id="t1",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        entry=2000.0,
        stop_loss=1990.0,
        take_profit=2020.0,
        size=0.01,
        risk_reward=2.0,
        confidence=0.8,
    )


def _delib(kind="multi_source"):
    d = Deliberation("XAUUSD", 1.0)
    d.confluence_kind = kind
    d.selected = SimpleNamespace(school_id="structure", pattern="trend_continuation",
                                 direction=TradeDirection.LONG, anchor="a1", meta={})
    return d


def test_fixed_size_override_wins(monkeypatch):
    monkeypatch.setenv("TRADERAIG_SIZING_MODE", "fixed")
    monkeypatch.setenv("TRADERAIG_FIXED_SIZE", "0.12")
    monkeypatch.setenv("TRADERAIG_PILOT_MAX_SIZE", "0.25")
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    c = _candidate()
    size = loop._resolve_position_size(c, _delib("multi_source"))
    assert size == 0.12
    assert c.sizing_mode == "fixed"
    assert c.size_reason == "fixed_override"


def test_dynamic_size_is_capped_and_discounted_for_single_source(monkeypatch):
    monkeypatch.setenv("TRADERAIG_SIZING_MODE", "dynamic")
    monkeypatch.setenv("TRADERAIG_PILOT_MAX_SIZE", "0.25")
    monkeypatch.setenv("TRADERAIG_SINGLE_SOURCE_SIZE_MULTIPLIER", "0.5")
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    c = _candidate()
    monkeypatch.setattr("core.pipeline.risk_governor.compute_volume", lambda candidate: 0.8)
    size = loop._resolve_position_size(c, _delib("single_source_exception"))
    assert size == 0.25
    assert c.sizing_mode == "dynamic"
    assert "single_source_discount" in c.size_reason


def test_dynamic_size_without_discount_uses_computed_volume(monkeypatch):
    monkeypatch.setenv("TRADERAIG_SIZING_MODE", "dynamic")
    monkeypatch.setenv("TRADERAIG_PILOT_MAX_SIZE", "2.0")
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    c = _candidate()
    monkeypatch.setattr("core.pipeline.risk_governor.compute_volume", lambda candidate: 0.3)
    size = loop._resolve_position_size(c, _delib("multi_source"))
    assert size == 0.3
    assert c.size_reason == "dynamic_risk"
