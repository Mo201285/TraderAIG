"""Tests for the backtest / paper-replay harness."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle, TradeDirection
from core.state import AccountState, PositionState, state
from learning.experience import ledger
from operations.backtest import Backtester, PaperExecutor, reset_runtime_state
from schools import quant


def _candle(open_, high, low, close, t=1.0):
    return Candle(symbol="XAUUSD", timeframe="M15", time=t, open=open_,
                  high=high, low=low, close=close, volume=100.0,
                  tick_volume=100.0)


def _trend_then_reversal(drift=12.0, up_cycles=5, dn_cycles=5, steps=24):
    """Deterministic HH/HL uptrend, then a sustained breakdown/reversal."""
    from tests.test_schools import conftest as cx

    def up(p):
        return p, p + drift * 0.2, p - drift * 0.3, p + drift

    def dn(p):
        return p, p + drift * 0.3, p - drift * 0.5, p - drift

    out = []
    price = 5000.0

    def push(maker, cycles):
        nonlocal price
        for cyc in range(cycles):
            for i in range(steps):
                o, h, l, c = maker(price)
                out.append(cx.mk(o, h, l, c, volume=100, tick_volume=50, i=i,
                                 t=float(out[-1].time + 900) if out else 900000.0))
                price = c
            for i in range(4):  # sharp counter-pullback to refresh structure
                o = price
                c = price - drift * 1.3 if maker is up else price + drift * 1.3
                out.append(cx.mk(o, max(o, c) + 0.1, min(o, c) - 0.1, c,
                                 volume=80, t=float(out[-1].time + 900)))
                price = c

    push(up, up_cycles)
    push(dn, dn_cycles)
    return out


def _executor_with_position(direction, entry, sl, tp, volume=0.1):
    reset_runtime_state()
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    ex = PaperExecutor()
    pos = PositionState(
        position_id="p1", symbol="XAUUSD", direction=direction,
        volume=volume, entry_price=entry, current_price=entry, sl=sl, tp=tp,
    )
    state.add_position(pos)
    ex._by_ticket["t1"] = {"position_id": "p1"}
    ex.trades.append({
        "ticket": "t1", "position_id": "p1", "symbol": "XAUUSD",
        "direction": direction.value, "entry": entry, "size": volume,
        "sl": sl, "tp": tp, "bars_held": 0, "open_time": 0.0,
    })
    return ex


def test_paper_executor_exits_on_tp_when_alone():
    ex = _executor_with_position(TradeDirection.LONG, 100.0, 99.0, 101.0)
    ex.mark(_candle(100.2, 101.3, 100.1, 101.1))
    assert len(ex.closed) == 1
    t = ex.closed[0]
    assert t["reason"] == "tp"
    assert t["exit"] == 101.0
    assert t["pnl"] > 0


def test_paper_executor_worst_case_sl_first():
    ex = _executor_with_position(TradeDirection.LONG, 100.0, 99.0, 101.0)
    ex.mark(_candle(99.5, 101.4, 98.6, 99.9))
    assert len(ex.closed) == 1
    t = ex.closed[0]
    assert t["reason"] == "sl"
    assert t["pnl"] < 0
    recs = [r for r in ledger.all() if r.record_id.startswith("paper:")]
    assert len(recs) == 1
    assert recs[0].metadata["direction"] == "long"


def test_paper_executor_short_position_exits_on_sl():
    ex = _executor_with_position(TradeDirection.SHORT, 100.0, 101.0, 99.0)
    ex.mark(_candle(100.5, 101.3, 100.2, 100.6))
    assert len(ex.closed) == 1
    assert ex.closed[0]["reason"] == "sl"


def test_paper_executor_flattens_remaining():
    ex = _executor_with_position(TradeDirection.LONG, 100.0, 99.0, 101.0)
    ex.mark(_candle(100.1, 100.4, 99.9, 100.2))  # no exit
    assert len(ex.closed) == 0
    ex.flatten(100.5)
    assert len(ex.closed) == 1
    assert ex.closed[0]["reason"] == "flat"
    assert ex.closed[0]["exit"] == 100.5


def test_backtester_replays_history_and_learns():
    report = Backtester(symbol="XAUUSD", timeframe="M15",
                        warmup=40, learn_every=5).run(_trend_then_reversal())

    assert report.bars == 280
    assert report.n_trades >= 4
    assert report.pnl == pytest.approx(sum(t["pnl"] for t in report.trades))
    assert len(report.equity_curve) == 280 - 40 + 1  # bars - warmup + initial

    # mixed outcomes across directions and schools
    reasons = {t["reason"] for t in report.trades}
    assert "tp" in reasons  # the discipline admits high-quality entries
    assert all(r in {"sl", "tp", "time_stop", "flat", "breakeven"} for r in reasons)
    assert len({t["direction"] for t in report.trades}) >= 1
    assert len({t["school"] for t in report.trades}) >= 1
    assert 0.0 <= report.win_rate <= 1.0

    for t in report.trades:
        assert t["school"] is not None
        assert t["pattern"] is not None

    # Learning loop ran: ledger has paper records carrying school attribution
    paper_recs = [r for r in ledger.all() if r.record_id.startswith("paper:")]
    assert len(paper_recs) >= report.n_trades
    assert all(r.metadata.get("school_id") for r in paper_recs)

    # Policy statistics were updated from the closed paper trades
    learned = {p for p in quant.quant_governor._patterns}
    assert len(learned) > 0


def test_ict_order_block_entry_never_crashes_on_zone_mid():
    """Regression: ob.mid crashed; the SMC OB scalp still builds entry zones.

    Series: calm base -> down OHLC (the OB) -> strong up impulse ->
    no further tests -> first-touch pullback closing INSIDE the OB.
    """
    from schools.ict import ICTSchool

    base = []
    price = 100.0
    for i in range(20):                       # oscillating, calm base
        o = price
        c = price + (0.4 if i % 2 else -0.3)
        base.append(_candle(o, max(o, c) + 0.3, min(o, c) - 0.3, c, t=1000.0 + i))
        price = c
    last = base[-1].time
    ob_down = _candle(100.6, 100.75, 100.15, 100.2, t=last + 1)   # OB body
    impulse = _candle(100.2, 101.35, 100.2, 101.3, t=last + 2)   # up impulse
    follow = _candle(101.3, 101.5, 101.1, 101.4, t=last + 3)
    first_touch = _candle(100.3, 100.7, 100.1, 100.55, t=last + 4)  # bull pullback inside
    evid = ICTSchool().evaluate(base + [ob_down, impulse, follow, first_touch],
                                "XAUUSD")
    signals = [s for s in evid.suggestions
               if s.pattern in ("breaker_mitigation", "order_block")]
    assert signals, "expected a first-touch SMC order-block scalp"
    for s in signals:
        assert all(isinstance(x, float) and x > 0 for x in s.entry_zone)
        assert s.meta.get("chart_ref", {}).get("type") == "order_block"
        assert s.direction == TradeDirection.LONG
        assert s.take_profit and s.meta.get("time_stop_seconds", 0) > 0


def test_backtester_is_deterministic_across_runs():
    candles = _trend_then_reversal()
    r1 = Backtester(symbol="XAUUSD", warmup=40).run(candles)
    r2 = Backtester(symbol="XAUUSD", warmup=40).run(candles)
    assert r1.n_trades == r2.n_trades
    assert r1.pnl == r2.pnl
    assert r1.equity_curve == r2.equity_curve


def test_paper_executor_breakeven_lock_long():
    ex = _executor_with_position(TradeDirection.LONG, 100.0, 99.0, 103.0)
    ex.mark(_candle(100.3, 101.4, 100.2, 101.0))  # close == entry + 1R
    assert len(ex.closed) == 0
    assert ex.trades[0]["be_done"] is True
    assert state.get_position("p1").sl == 100.0

    ex.mark(_candle(99.8, 100.1, 99.6, 99.9))     # dips under old 99.0 SL
    assert len(ex.closed) == 1
    t = ex.closed[0]
    assert t["reason"] == "sl"
    assert t["exit"] == 100.0
    assert -0.05 < t["pnl"] <= 0.0                # breakeven: cost = fees only


def test_paper_executor_breakeven_lock_short():
    ex = _executor_with_position(TradeDirection.SHORT, 100.0, 101.0, 97.0)
    ex.mark(_candle(99.8, 100.2, 99.0, 99.0))     # close == entry - 1R
    assert len(ex.closed) == 0
    assert ex.trades[0]["be_done"] is True
    assert state.get_position("p1").sl == 100.0

    ex.mark(_candle(100.2, 100.4, 99.8, 100.1))   # bounces to old 101.0 SL area
    assert len(ex.closed) == 1
    t = ex.closed[0]
    assert t["reason"] == "sl"
    assert t["exit"] == 100.0
    assert -0.05 < t["pnl"] <= 0.0


def test_backtester_rejects_too_few_candles():
    with pytest.raises(ValueError):
        Backtester(warmup=60).run([_candle(1, 1, 1, 1)] * 10)
