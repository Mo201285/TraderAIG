"""Tests for per-user risk policy enforcement."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import TradeDirection
from core.state import AccountState, CanonicalState, MarketState
from decision.candidate import TradeCandidate
from governance.identity import RiskPolicy
from risk.governor import RiskDecisionKind, RiskGovernor


def make_state(equity: float = 10000.0, daily_pnl: float = 0.0):
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=equity, equity=equity))
    s.upsert_market(MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5,
                                spread=0.5, last_price=2000.25, last_tick_time=1.0,
                                tick_size=0.01, tick_value=1.0,
                                volume_min=0.01, volume_step=0.01, volume_max=100.0))
    s.risk.daily_pnl = daily_pnl
    return s


def make_candidate():
    return TradeCandidate(
        candidate_id="c1", thesis_id="t1", symbol="XAUUSD",
        direction=TradeDirection.LONG, entry=2000.0, stop_loss=1990.0,
        take_profit=2020.0, size=0.1, risk_reward=2.0, confidence=0.8,
    )


def test_strict_user_policy_tightens_open_positions():
    g = RiskGovernor(make_state())
    strict = RiskPolicy(max_open_positions=1)

    # First position is fine under the strict policy (now 1 open).
    s = g._state
    from core.state import PositionState
    s.add_position(PositionState(
        position_id="p1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=2000.0, current_price=2000.0,
    ))

    d = g.veto_reason(make_candidate(), policy=strict)
    assert d.kind == RiskDecisionKind.VETOED
    assert "too many open positions" in d.reason


def test_default_policy_still_allows_one_open():
    g = RiskGovernor(make_state())
    from core.state import PositionState
    g._state.add_position(PositionState(
        position_id="p1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=2000.0, current_price=2000.0,
    ))
    d = g.veto_reason(make_candidate())
    assert d.kind == RiskDecisionKind.APPROVED


def test_daily_loss_limit_respected():
    g = RiskGovernor(make_state(daily_pnl=-500.0))
    # daily loss 500 / 10000 = 5% > default 3% cap -> veto
    d = g.veto_reason(make_candidate())
    assert d.kind == RiskDecisionKind.VETOED
    assert "daily loss" in d.reason


def test_user_policy_can_be_looser_but_is_capped():
    # A user asking for 5% per trade is still capped at the 1% institutional max.
    g = RiskGovernor(make_state())
    loose = RiskPolicy(max_risk_per_trade=0.05)
    limit = g._enforceable_limits(loose)
    assert limit["max_risk_per_trade"] == pytest.approx(0.01)
