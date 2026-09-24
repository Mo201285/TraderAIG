"""Tests for the CEX gateway + venue adapters (look at mocks, no network)."""

from types import SimpleNamespace

import pytest

from core.contracts import TradeDirection
from core.state import AccountState, state
from decision.thesis import TradeCandidate
from execution.cex import venues as venues_mod
from execution.cex.gateway import CexGateway
from execution.cex.venues import (
    BinanceVenue,
    BybitVenue,
    OKXVenue,
    VenueLockedError,
)
from risk.governor import RiskDecision, RiskDecisionKind


def _candidate(symbol="BTCUSDT") -> TradeCandidate:
    return TradeCandidate(
        candidate_id="cex-cand-1",
        thesis_id="cex-thesis-1",
        symbol=symbol,
        direction=TradeDirection.LONG,
        entry=60000.0,
        stop_loss=59000.0,
        take_profit=62000.0,
        size=0.001,
        risk_reward=2.0,
        confidence=0.7,
    )


def _approved() -> RiskDecision:
    return RiskDecision(decision_id="d1", candidate_id="cex-cand-1",
                        kind=RiskDecisionKind.APPROVED)


def _paper_settings(monkeypatch, venue="binance", mode="paper"):
    monkeypatch.setattr(venues_mod, "settings", SimpleNamespace(
        cex=SimpleNamespace(
            mode=mode, live_allowed=False, venue=venue,
            binance_api_key="", binance_api_secret="",
            binance_testnet_key="", binance_testnet_secret="",
            okx_api_key="", okx_api_secret="", okx_passphrase="",
            okx_broker_id="", bybit_api_key="", bybit_api_secret="",
            bybit_testnet_key="", bybit_testnet_secret=""),
    ))


def test_binance_locked_without_keys(monkeypatch):
    """Default (paper mode) must be reachable; live without keys must lock."""
    _paper_settings(monkeypatch, mode="paper")
    venue = BinanceVenue(mode="paper")
    assert venue.locked is False
    assert venue.mode == "paper"

    _paper_settings(monkeypatch, mode="live")
    live = BinanceVenue(mode="live")
    assert live.locked is True
    assert live.live_armed is False
    with pytest.raises(VenueLockedError):
        live.place_market_order("BTCUSDT", "buy", 0.001)


def test_live_requires_explicit_arm(monkeypatch):
    """CEX_LIVE_ALLOWED=1 alone must not unlock a venue without keys."""
    _paper_settings(monkeypatch, mode="live")
    monkeypatch.setattr(venues_mod.settings.cex, "live_allowed", True)
    venue = BinanceVenue(mode="live")
    assert venue.locked is True  # no api keys
    with pytest.raises(VenueLockedError):
        venue.place_market_order("BTCUSDT", "buy", 0.001)


def test_binance_fetch_ticker_maps_fields(monkeypatch):
    _paper_settings(monkeypatch, mode="testnet")
    venue = BinanceVenue(mode="testnet", api_key="k", api_secret="s")
    venue._request = lambda *a, **kw: {"bidPrice": "60001.0",
                                       "askPrice": "60002.0"}
    ticker = venue.fetch_ticker("BTCUSDT")
    assert ticker["ok"] is True
    assert ticker["bid"] == 60001.0
    assert ticker["ask"] == 60002.0


def test_binance_place_order_signed(monkeypatch):
    """A real signed order must hit the venue when keys + testnet mode."""
    _paper_settings(monkeypatch, mode="testnet")
    venue = BinanceVenue(mode="testnet", api_key="k", api_secret="s")
    captured = {}

    def fake_request(method, url, body=None, headers=None):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {"orderId": 5001, "executedQty": "0.001",
                "cummulativeQuoteQty": "60.0", "status": "FILLED"}

    venue._request = fake_request
    result = venue.place_market_order("BTCUSDT", "buy", 0.001)
    assert result["ok"] is True
    assert result["order_id"] == "5001"
    assert captured["method"] == "POST"
    assert "signature=" in captured["url"]
    assert captured["headers"]["X-MBX-APIKEY"] == "k"
    assert captured["body"]["side"] == "BUY"


def test_okx_and_bybit_locked_live_before_guard(monkeypatch):
    _paper_settings(monkeypatch, mode="live")
    with pytest.raises(VenueLockedError):
        OKXVenue(mode="live").place_market_order("BTC-USDT", "buy", 0.001)
    with pytest.raises(VenueLockedError):
        BybitVenue(mode="live").place_market_order("BTCUSDT", "buy", 0.001)


def test_build_venue_unknown_fails():
    from execution.cex.venues import build_venue
    with pytest.raises(ValueError):
        build_venue("does-not-exist")


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


def _paper_gateway(monkeypatch, symbol="BTCUSDT") -> CexGateway:
    _paper_settings(monkeypatch)
    from core.state import CanonicalState, MarketState
    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    state.set_account(AccountState(login=0, balance=10_000.0,
                                   equity=10_000.0, leverage=1))
    state.risk.daily_pnl = 0.0
    state.upsert_market(MarketState(symbol=symbol, bid=60000.0, ask=60001.0,
                                    last_price=60000.0, spread=1.0))
    return CexGateway(venue=BinanceVenue(mode="paper"))


def test_gateway_refuses_unapproved(monkeypatch):
    gate = _paper_gateway(monkeypatch)
    decision = RiskDecision(decision_id="d2", candidate_id="cex-cand-1",
                            kind=RiskDecisionKind.VETOED)
    assert gate.execute(_candidate(), decision) is None


def test_gateway_paper_fills_deterministically(monkeypatch):
    gate = _paper_gateway(monkeypatch)
    before = len(state.open_positions())
    ticket = gate.execute(_candidate(), _approved())
    assert ticket is not None
    assert ticket.status.value == "filled"
    assert len(state.open_positions()) == before + 1


def test_gateway_paper_close_marks_closed(monkeypatch):
    gate = _paper_gateway(monkeypatch)
    gate.execute(_candidate(), _approved())
    positions = [p for p in state.open_positions()]
    assert len(positions) == 1
    assert gate.close_position(positions[0].position_id) is True
    assert len(state.open_positions()) == 0


def test_gateway_live_without_arm_rejects(monkeypatch):
    _paper_settings(monkeypatch, mode="live")
    gate = CexGateway(venue=BinanceVenue(mode="live"))
    ticket = gate.execute(_candidate(), _approved())
    assert ticket is not None
    assert ticket.status.value == "rejected"


def test_gateway_status_reports_gate(monkeypatch):
    _paper_settings(monkeypatch)
    gate = CexGateway(venue=BinanceVenue(mode="paper"))
    st = gate.status()
    assert st["venue"] == "binance"
    assert "gate_live_allowed" in st
