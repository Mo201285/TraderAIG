"""Shared fixtures for the schools test suite."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle  # noqa: E402
from core.state import state  # noqa: E402
from decision.candidate import candidate_board  # noqa: E402
from learning.experience import ExperienceRecord, ledger  # noqa: E402


def mk(open_, high, low, close, volume=100.0, t=None, i=0,
       tick_volume=10) -> Candle:
    return Candle(symbol="XAUUSD", timeframe="M15",
                  time=float(t if t is not None else 100000 + i * 900),
                  open=open_, high=high, low=low, close=close,
                  volume=volume, tick_volume=tick_volume)


def leg(base, steps, maker):
    """Build `steps` candles trending from `base` using `maker(price)`."""
    out = []
    price = base
    for i in range(steps):
        o, h, l, c = maker(price)
        out.append(mk(o, max(o, h, c), min(o, l, c), c, t=200000 + i * 900, i=i))
        price = c
    return price, out


def pullback_uptrend():
    """Rising HH/HL series ending with a pullback near the protected low."""
    out: list = []
    price = 100.0
    for _ in range(6):                      # up-leg to a swing high
        off = 0.5
        price, leg_out = leg(price, 3, lambda p: (p, p + off, p - off, p + 0.2))
        out += leg_out
    price, leg_out = leg(price, 2, lambda p: (p, p + 1.2, p - 0.6, p + 0.1))  # swing high
    out += leg_out
    price, leg_out = leg(price, 4, lambda p: (p, p + 0.1, p - 0.9, p - 0.4))  # pullback
    out += leg_out
    return out


def steady_uptrend(steps=40):
    """Monotonic upward drive - no pullback, strong BOS context."""
    out = []
    price = 5000.0
    for i in range(steps):
        o = price
        c = o + 10.0
        out.append(mk(o, c + 2.0, o - 3.0, c, volume=100.0,
                      t=300000 + i * 900, i=i))
        price = c
    return out


def swing_path():
    """Deterministic HH/HL structure. Confirmed swing lows at 100@3 and
    103@13, swing highs at 104@8 and 107@18. Ends in a shallow pullback
    (close 104.5) that stays inside the protected-low zone above 103."""
    lows = [100.4, 100.6, 101.0, 100.0, 101.0, 101.6, 102.2, 102.8, 103.2,
            103.4, 103.5, 103.3, 103.1, 103.0, 103.4, 103.7, 103.9, 104.1,
            104.3, 104.4]
    highs = [102.6, 102.9, 103.3, 103.2, 103.6, 103.9, 104.3, 104.6, 105.0,
             104.8, 104.5, 104.0, 103.6, 103.3, 104.0, 105.0, 106.0, 106.9,
             107.8, 107.4]
    closes = [(l + h) / 2 for l, h in zip(lows, highs)]
    closes[-1] = 104.5                        # pullback, above the 103 HL
    return [mk(closes[i], highs[i], lows[i], closes[i],
               t=400000 + i * 900, i=i) for i in range(len(lows))]


def bos_breakout():
    """swing_path then a candle closing clearly above the last high 107."""
    base = swing_path()
    last = base[-1]
    nxt = mk(107.6, 108.8, 107.4, 108.5,
             t=float(last.time) + 1, i=99)
    return base + [nxt]


def deep_pushdown():
    """Rising HH/HL then a candle closing cleanly below the 103 HL -> CHoCH."""
    base = swing_path()
    last = base[-1]
    nxt = mk(104.3, 104.9, 102.2, 102.5,
             t=float(last.time) + 1, i=99)
    return base + [nxt]


@pytest.fixture(autouse=True)
def clean_runtime_state():
    """Each school test starts from a clean singleton state."""
    reset_school_runtime()
    ledger.clear()
    candidate_board._candidates = []
    for pos in list(state.positions.values()):
        if pos.status.value == "open":
            state.close_position(pos.position_id, pos.entry_price)
    state.orders.clear()
    state.positions.clear()
    state.market.clear()
    yield
    reset_school_runtime()


def reset_school_runtime() -> None:
    """Restore registry/quant singletons so tests never leak learned state."""
    from schools.base import PolicyStatus
    from schools import registry, quant
    quant.quant_governor._patterns = {}
    quant.quant_governor.require_stats = False
    for s in registry._schools:
        s.policy.status = PolicyStatus.INIT
        s.policy.confidence_multiplier = 1.0
        s.policy.expectancy_by_regime = {}
        s.policy.sample_by_regime = {}
        s.policy.winrate_by_regime = {}
        s.policy.last_learned_at = 0.0


def tagged_record(school, pattern, regime, pnl, filled=True,
                  record_id="mt5:777") -> ExperienceRecord:
    rec = ExperienceRecord(
        record_id=record_id,
        decision_id=f"mt5-deal:{record_id}",
        timestamp=1.0,
        actual_result={"pnl": pnl, "filled": filled},
        metadata={"school_id": school, "pattern": pattern,
                  "regime_key": regime, "filled": filled},
    )
    rec.error_classification = None
    return rec
