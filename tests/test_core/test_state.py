"""Unit tests for the canonical state store."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import OrderStatus, OrderType, TradeDirection
from core.state import AccountState, CanonicalState, MarketState, OrderState, PositionState


def make_state() -> CanonicalState:
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    return s


def test_account_update_tracks_peak_equity():
    s = make_state()
    s.set_account(AccountState(login=1, balance=10000.0, equity=11000.0))
    s.set_account(AccountState(login=1, balance=10500.0, equity=10500.0))
    assert s.risk.peak_equity == 11000.0


def test_market_upsert_and_get():
    s = CanonicalState()
    mk = MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5, spread=0.5,
                     last_price=2000.25, last_tick_time=1.0)
    s.upsert_market(mk)
    assert s.get_market("XAUUSD").bid == 2000.0


def test_order_lifecycle():
    s = CanonicalState()
    order = OrderState(
        order_id="o1", symbol="XAUUSD", order_type=OrderType.MARKET,
        direction=TradeDirection.LONG, volume=0.1,
        price=2000.0, sl=1990.0, tp=2020.0,
    )
    s.add_order(order)
    order.status = OrderStatus.FILLED
    s.update_order(order)
    assert s.get_order("o1").status == OrderStatus.FILLED
    assert len(s.orders_by_status(OrderStatus.FILLED)) == 1


def test_position_open_close_pnl():
    s = CanonicalState()
    pos = PositionState(
        position_id="p1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=2000.0, current_price=2000.0,
    )
    s.add_position(pos)
    assert s.risk.open_positions == 1

    s.close_position("p1", 2010.0)
    closed = s.get_position("p1")
    assert closed.status.value == "closed"
    assert closed.realized_pnl == pytest.approx(1.0)  # (2010-2000)*0.1
    assert s.risk.open_positions == 0


def test_record_veto_stamps_recorded_at():
    s = CanonicalState()
    veto = {"decision_id": "d-1", "candidate_id": "c-1",
            "kind": "vetoed", "reason": "r", "checks": []}
    s.record_veto(veto)
    assert veto["recorded_at"] > 0
    assert len(s.risk.vetoes) == 1
    assert s.risk.vetoes[0]["recorded_at"] > 0


def test_settle_realized_books_partial_into_daily_pnl():
    """E4 (appendix B): a partial close must reach the daily-loss guard,
    not wait for the final (possibly far-future) close."""
    s = CanonicalState()
    pos = PositionState(
        position_id="p1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.2, entry_price=100.0, current_price=101.0,
    )
    s.add_position(pos)

    s.settle_realized("p1", 0.6)  # realized on a half-lot exit

    live = s.get_position("p1")
    assert live.realized_pnl == pytest.approx(0.6)
    assert s.risk.daily_pnl == pytest.approx(0.6)  # guard sees it immediately


def test_close_accumulates_partial_realized_plus_swap_once():
    """E4: close after partial exits reports full realized result (partial +
    final piece), books the final piece once, and swap exactly once."""
    s = CanonicalState()
    pos = PositionState(
        position_id="p1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.2, entry_price=100.0, current_price=101.0,
    )
    s.add_position(pos)
    s.settle_realized("p1", 0.6)  # first half closed earlier
    p = s.get_position("p1")
    p.volume = 0.1                # remaining half
    p.swap = -0.3                 # broker financing cost (sync-provided)
    s.close_position("p1", 101.0)

    closed = s.get_position("p1")
    assert closed.realized_pnl == pytest.approx(0.7)  # 0.6 partial + 0.1 final
    assert s.risk.daily_pnl == pytest.approx(0.6 + 0.1 - 0.3)  # no double count
