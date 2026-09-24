"""Unit tests for the Risk Governor gate."""

import sys
from pathlib import Path

import pytest
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import TradeDirection
from core.state import AccountState, CanonicalState, MarketState, PositionState
from decision.candidate import TradeCandidate
from risk.governor import RiskGovernor, RiskDecisionKind


def make_governor_with_positions(n_open: int = 0, equity: float = 10000.0):
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=equity, equity=equity))
    s.upsert_market(MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5,
                                spread=0.5, last_price=2000.25, last_tick_time=1.0,
                                tick_size=0.01, tick_value=1.0,
                                volume_min=0.01, volume_step=0.01, volume_max=100.0))
    for i in range(n_open):
        s.add_position(PositionState(
            position_id=f"p{i}", symbol="XAUUSD", direction=TradeDirection.LONG,
            volume=0.1, entry_price=2000.0, current_price=2000.0,
        ))
    g = RiskGovernor(state_ref=s)
    return g, s


def make_candidate():
    return TradeCandidate(
        candidate_id="c1", thesis_id="t1", symbol="XAUUSD",
        direction=TradeDirection.LONG, entry=2000.0, stop_loss=1990.0,
        take_profit=2020.0, size=0.1, risk_reward=2.0, confidence=0.8,
    )


def test_approves_valid_candidate():
    g, _ = make_governor_with_positions(n_open=0)
    d = g.veto_reason(make_candidate())
    assert d.kind == RiskDecisionKind.APPROVED


def test_vetoes_when_capacity_reached():
    g, _ = make_governor_with_positions(n_open=5)
    d = g.veto_reason(make_candidate())
    assert d.kind == RiskDecisionKind.VETOED
    assert "too many open positions" in d.reason


def test_veto_recorded_in_state():
    g, s = make_governor_with_positions(n_open=5)
    g.veto_reason(make_candidate())
    assert len(s.risk.vetoes) == 1
    assert s.risk.vetoes[0]["candidate_id"] == "c1"


def test_compute_volume_from_risk_budget():
    g, _ = make_governor_with_positions(n_open=0, equity=10000.0)
    c = make_candidate()

    # XAU tick-aware: 10.0 price / 0.01 tick = 1000 ticks, $1 per tick =>
    # $1000 risk per lot, so $100 risk budget sizes to 0.10 lots.
    vol = g.compute_volume(c, max_risk_fraction=0.01)
    assert vol == pytest.approx(0.10, abs=0.01)


def test_compute_volume_caps_xau_size():
    g, s = make_governor_with_positions(n_open=0, equity=1_000_000.0)
    c = make_candidate()
    c.stop_loss = 1999.9
    vol = g.compute_volume(c, max_risk_fraction=0.01)
    assert vol <= 3.0


def test_compute_volume_caps_btc_size():
    g, s = make_governor_with_positions(n_open=0, equity=1_000_000.0)
    s.upsert_market(MarketState(symbol="BTCUSD", bid=60000.0, ask=60010.0,
                                spread=10.0, last_price=60005.0, last_tick_time=1.0,
                                tick_size=0.01, tick_value=0.01,
                                volume_min=0.01, volume_step=0.01, volume_max=100.0))
    c = TradeCandidate(
        candidate_id="c2", thesis_id="t2", symbol="BTCUSD",
        direction=TradeDirection.LONG, entry=60000.0, stop_loss=59900.0,
        take_profit=60300.0, size=0.1, risk_reward=3.0, confidence=0.8,
    )
    vol = g.compute_volume(c, max_risk_fraction=0.01)
    assert vol <= 2.0


def test_default_spread_limit_tolerates_medium_spread():
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    # ratio 3.0 / 2000 = 0.0015 < institutional 0.002
    s.upsert_market(MarketState(symbol="XAUUSD", bid=1998.5, ask=2001.5,
                                spread=3.0, last_price=2000.0, last_tick_time=1.0))
    g = RiskGovernor(state_ref=s)
    d = g.veto_reason(make_candidate())
    assert d.kind == RiskDecisionKind.APPROVED


def test_scalp_spread_limit_vetoes_medium_spread():
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    # ratio 0.0015 is fine for M15 but kills an M1 scalp with limit 0.0008
    s.upsert_market(MarketState(symbol="XAUUSD", bid=1998.5, ask=2001.5,
                                spread=3.0, last_price=2000.0, last_tick_time=1.0))
    g = RiskGovernor(state_ref=s)
    d = g.veto_reason(make_candidate(), spread_ratio_limit=0.0008)
    assert d.kind == RiskDecisionKind.VETOED
    assert "spread too wide for execution" in d.reason
    quality = next(c for c in d.checks if c["name"] == "price_quality")
    assert quality["detail"]["limit"] == 0.0008


def test_daily_pnl_resets_on_new_day():
    s = CanonicalState()
    day = int(time.time()) // 86400
    s.risk.daily_pnl = -50.0
    s.risk.last_day_epoch = day - 1
    assert s.roll_risk_day() is True
    assert s.risk.daily_pnl == 0.0
    assert s.risk.last_day_epoch == day
    # Same-day call is a no-op.
    assert s.roll_risk_day() is False
    assert s.risk.daily_pnl == 0.0


def test_governor_rolls_stale_daily_pnl_defensively():
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    s.upsert_market(MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5,
                                spread=0.5, last_price=2000.25, last_tick_time=1.0,
                                tick_size=0.01, tick_value=1.0, volume_min=0.01,
                                volume_step=0.01, volume_max=100.0))
    g = RiskGovernor(state_ref=s)
    s.risk.daily_pnl = -500.0
    s.risk.last_day_epoch = int(time.time()) // 86400 - 1
    d = g.veto_reason(make_candidate())
    assert d.kind == RiskDecisionKind.APPROVED


def test_close_position_rolls_day_then_counts_realized_pnl():
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    s.add_position(PositionState(
        position_id="p9", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=1.0, entry_price=2000.0, current_price=2000.0,
    ))
    s.risk.daily_pnl = -100.0
    s.risk.last_day_epoch = int(time.time()) // 86400 - 1
    s.close_position("p9", 2010.0)
    assert s.risk.daily_pnl == pytest.approx(10.0)


def test_exposure_updated_on_add_partial_and_close():
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    s.add_position(PositionState(
        position_id="x1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=1.0, entry_price=2000.0, current_price=2000.0,
    ))
    s.add_position(PositionState(
        position_id="x2", symbol="XAUUSD", direction=TradeDirection.SHORT,
        volume=0.5, entry_price=2000.0, current_price=2000.0,
    ))
    assert s.risk.exposure_by_symbol["XAUUSD"] == pytest.approx(1.5)

    partial = s.get_position("x1")
    partial.volume = 0.5
    s.update_position(partial)
    assert s.risk.exposure_by_symbol["XAUUSD"] == pytest.approx(1.0)

    s.close_position("x2", 2001.0)
    assert s.risk.exposure_by_symbol["XAUUSD"] == pytest.approx(0.5)


def test_symbol_exposure_vetoes_aggregate_volume():
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    s.upsert_market(MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5,
                                spread=0.5, last_price=2000.25, last_tick_time=1.0,
                                tick_size=0.01, tick_value=1.0, volume_min=0.01,
                                volume_step=0.01, volume_max=100.0))
    s.add_position(PositionState(
        position_id="z1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=4.4, entry_price=2000.0, current_price=2000.0,
    ))
    # Default max_leverage=10 -> per-symbol cap 5.0 lots; 4.4 + 1.5 => veto.
    c = make_candidate()
    c.size = 1.5
    g = RiskGovernor(state_ref=s)
    d = g.veto_reason(c)
    assert d.kind == RiskDecisionKind.VETOED
    assert "symbol exposure" in d.reason
