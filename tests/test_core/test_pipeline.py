"""End-to-end pipeline tests with synthetic candles."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import TradeDirection
from core.state import AccountState, CanonicalState, MarketState, PositionState, state
from core.pipeline import TradingLoop, ReconciliationEngine
from main import make_demo_candles


def test_pipeline_produces_positions():
    """Synthetic trending data should yield at least one approved execution."""
    s = CanonicalState()
    # Reset the module singleton to a clean instance for the test.
    state.__dict__.clear()
    state.__dict__.update(s.__dict__)
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))

    candles = make_demo_candles("XAUUSD", n=400)
    loop = TradingLoop("XAUUSD", enable_execution=True)

    for i in range(50, len(candles)):
        mk = MarketState(symbol="XAUUSD", bid=candles[i].close, ask=candles[i].close + 0.05,
                         spread=0.05, last_price=candles[i].close,
                         last_tick_time=candles[i].time)
        state.upsert_market(mk)
        loop.on_new_candle(candles[:i + 1])

    assert len(state.orders) > 0
    assert len(state.positions) > 0


def test_reconciliation_detects_drift():
    s = CanonicalState()
    state.__dict__.clear()
    state.__dict__.update(s.__dict__)
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    state.add_position(PositionState(
        position_id="p_remote", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.5, entry_price=2000.0, current_price=2000.0,
    ))

    engine = ReconciliationEngine(state_ref=state)
    # Remote does not know about p_remote -> mismatch
    assert engine.verify([]) is False


def test_reconciliation_with_presync_baseline_catches_external_close():
    """E3 (appendix B): verifying against a pre-sync snapshot makes reconcile
    a real detector; after sync the store equals the broker, so checking the
    *current* store is vacuous and would never flag the external close."""
    from core.pipeline import recon_engine

    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    state.add_position(PositionState(
        position_id="ext", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.2, entry_price=2000.0, current_price=2000.0,
    ))

    before = {p.position_id: p.as_dict() for p in state.open_positions()}
    # sync_positions already dropped "ext" because the broker no longer has it
    remote = []
    old = list(recon_engine._mismatches)
    ok = recon_engine.verify(remote, baseline=before)
    added = [m for m in recon_engine._mismatches
             if m not in old and m.get("type") == "missing_remote"]
    assert ok is False
    assert any(m["position_id"] == "ext" for m in added)


def test_htf_feed_is_cached_and_respected():
    from tests.test_schools.conftest import steady_uptrend, swing_path
    from intelligence.regime import classify_trend

    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))

    loop = TradingLoop("XAUUSD", "M5", enable_execution=False,
                       use_school_board=True, htf_timeframe="H1")
    htf_path = steady_uptrend(60)
    loop.on_htf_candles(htf_path)
    assert loop._htf is not None
    assert classify_trend(htf_path) != "sideways"

    # same-length buffer must not re-trigger a recompute
    loop.on_htf_candles(htf_path)
    assert loop._htf_last_len == len(htf_path)

    # HTF context is passed into the (M5) school-board deliberation
    from core.state import MarketState
    state.upsert_market(MarketState(symbol="XAUUSD", bid=108.5, ask=108.55,
                                    spread=0.05, last_price=108.5,
                                    last_tick_time=1.0))
    loop.on_new_candle(swing_path())
    assert loop._htf is not None


def test_scalp_timeframe_hardens_spread_gate():

    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    from core.state import MarketState
    # ratio = 2.0 / 2000 = 0.001 -> ok for M15 (0.002), vetoed for M1
    state.upsert_market(MarketState(symbol="XAUUSD", bid=1999.0, ask=2001.0,
                                    spread=2.0, last_price=2000.0,
                                    last_tick_time=1.0))
    loop15 = TradingLoop("XAUUSD", "M15", enable_execution=False,
                         use_school_board=True)
    loop1 = TradingLoop("XAUUSD", "M1", enable_execution=False,
                        use_school_board=True)
    assert loop15._spread_ratio_limit is None
    assert loop1._spread_ratio_limit == 0.0008
