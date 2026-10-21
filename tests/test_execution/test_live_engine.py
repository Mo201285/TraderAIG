"""Hermetic tests for the live MT5 executor and the LiveEngine, using a
fake adapter so no real terminal is ever touched."""
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, ".")
import core.contracts as contracts
from core.state import AccountState, CanonicalState, MarketState, OrderStatus, state
from core.pipeline import TradingLoop
from decision.candidate import TradeCandidate
from execution.engine import ExecutionStatus
from execution.mt5_adapter import LiveMT5Executor
from risk.governor import RiskDecision, RiskDecisionKind


@pytest.fixture(autouse=True)
def _reset_canonical_state():
    """Hermetic tests: never bleed canonical positions/orders into other
    files via the module-global singleton `state`."""
    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    yield
    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)


def make_candidate() -> TradeCandidate:
    return TradeCandidate(
        candidate_id="cand-live-1",
        thesis_id="thesis-live-1",
        symbol="XAUUSD",
        direction=contracts.TradeDirection.LONG,
        entry=4350.0,
        stop_loss=4320.0,
        take_profit=4410.0,
        size=0.01,
        risk_reward=2.0,
        confidence=0.65,
    )


def approved_decision() -> RiskDecision:
    return RiskDecision(decision_id="d-live-1", candidate_id="cand-live-1",
                        kind=RiskDecisionKind.APPROVED, reason="ok")


class FakePos:
    position_id = "mt5-pos-77"
    entry_price = 4350.21
    volume = 0.01
    symbol = "XAUUSD"

    def as_dict(self):
        return {"position_id": self.position_id, "entry_price": self.entry_price,
                "volume": self.volume, "symbol": self.symbol}


class FakeAdapter:
    def __init__(self, result):
        self.result = result
        self.connected = False
        self._last_error = ""
        self.synced = 0
        self.positions = []
        self.fetch_candles = MagicMock()

    @property
    def available(self):
        return True

    def status(self):
        return {"last_error": self._last_error, "positions": self.positions,
                "session_login": "123"}

    def connect(self):
        self.connected = True
        return True

    def _lazy_connect_if_possible(self):
        self.connected = True
        return True

    def sync_positions(self):
        self.synced += 1
        if self.result is not None:
            self.positions = [FakePos()]
        return self.positions

    def sync_account(self):
        pass

    def sync_market(self, symbol):
        pass

    def sync_history(self):
        pass

    def place_position(self, candidate, decision_kind):
        if self.result is None:
            self._last_error = "AutoTrading disabled by client"
        return self.result


def test_live_executor_fills_and_syncs():
    adapter = FakeAdapter(FakePos())
    ex = LiveMT5Executor(adapter)

    ticket = ex.execute(make_candidate(), approved_decision())

    assert ticket.status == ExecutionStatus.FILLED
    assert "filled at 4350.21" in ticket.note
    assert adapter.synced >= 1
    order = state.get_order(ticket.order_id)
    assert order is not None and order.status.name == "FILLED"


def test_live_executor_rejects_on_broker_refusal():
    adapter = FakeAdapter(None)
    ex = LiveMT5Executor(adapter)

    ticket = ex.execute(make_candidate(), approved_decision())

    assert ticket.status == ExecutionStatus.REJECTED
    assert "AutoTrading disabled by client" in ticket.note
    order = state.get_order(ticket.order_id)
    assert order.status == OrderStatus.REJECTED


def test_live_executor_refuses_unapproved():
    adapter = FakeAdapter(FakePos())
    ex = LiveMT5Executor(adapter)
    dec = RiskDecision(decision_id="d2", candidate_id="cand-live-1",
                       kind=RiskDecisionKind.VETOED, reason="nope")
    assert ex.execute(make_candidate(), dec) is None
    assert adapter.synced == 0


def test_live_executor_returns_error_when_disconnect():
    adapter = FakeAdapter(FakePos())
    adapter.connect = lambda: False
    adapter._lazy_connect_if_possible = lambda: False
    ex = LiveMT5Executor(adapter)

    ticket = ex.execute(make_candidate(), approved_decision())

    assert ticket.status == ExecutionStatus.ERROR
    assert "not reachable" in ticket.note


def test_live_engine_cycle_feeds_pipeline():
    from operations.live_engine import LiveEngine
    adapter = FakeAdapter(FakePos())
    adapter.fetch_candles.return_value = [
        contracts.Candle(symbol="XAUUSD", timeframe="M15",
                         time=1000.0 + i * 900,
                         open=4300.0 + i, high=4301.0 + i,
                         low=4299.0 + i, close=4300.5 + i,
                         volume=100.0, tick_volume=10)
        for i in range(80)
    ]
    engine = LiveEngine(symbols=["XAUUSD"], adapter=adapter)

    cycles = engine.cycle()

    assert cycles == 1
    assert len(engine.status()["errors"]) == 0


def test_live_engine_keeps_evaluating_after_the_bar_window_fills():
    """New-bar detection must key on bar TIME, not buffer length.

    The engine reads a fixed 300-bar window, so once warm the buffer length is
    constant. A guard keyed on "the buffer grew" then fed the strategy pipeline
    exactly once and went silent for ever -- while `cycles` kept climbing and
    `errors` stayed empty. That is a healthy-looking engine that has stopped
    deciding anything, which is worse than one that reports it is down.
    """
    from core.market_plane import MarketPlane, MarketRead
    from operations.live_engine import LiveEngine

    adapter = FakeAdapter(FakePos())
    plane = MarketPlane(min_pull_interval=0.0)
    engine = LiveEngine(symbols=["XAUUSD"], adapter=adapter, htf_timeframe=None,
                        use_school_board=False, plane=plane, poll_seconds=0.0)

    def window(last_time):
        return [contracts.Candle(
                    symbol="XAUUSD", timeframe="M15",
                    time=last_time - 900.0 * (299 - i),
                    open=4300.0, high=4301.0, low=4299.0, close=4300.5,
                    volume=100.0, tick_volume=10)
                for i in range(300)]

    bars = {"last": 5_000_000.0}

    class StubPlane:
        def read(self, sym, tf, count=300, **_kw):
            return MarketRead(symbol=sym, timeframe=tf,
                              candles=window(bars["last"]), source="mt5",
                              freshness="live")

    engine._plane = StubPlane()

    seen = []
    engine._loops["XAUUSD"].on_new_candle = lambda c: seen.append(c[-1].time)

    engine.cycle()                     # first bar of the window
    assert len(seen) == 1
    engine.cycle()                     # same bar still forming: no re-run
    assert len(seen) == 1
    bars["last"] += 900.0              # a new M15 bar closed
    engine.cycle()
    assert len(seen) == 2, "a new bar must reach the pipeline, not starve it"


def test_live_engine_reconciles_positions():
    from operations.live_engine import LiveEngine
    from core.pipeline import recon_engine
    from core.state import PositionState
    adapter = FakeAdapter(FakePos())
    adapter.fetch_candles.return_value = []
    engine = LiveEngine(symbols=["XAUUSD"], adapter=adapter)
    for p in state.open_positions():
        state.close_position(p.position_id, p.entry_price)
    state.add_position(PositionState(
        position_id="mt5-pos-77", symbol="XAUUSD",
        direction=contracts.TradeDirection.LONG, volume=0.01,
        entry_price=4350.21, current_price=4350.21))

    assert engine.cycle() == 1
    assert recon_engine.verify(
        [p.as_dict() for p in adapter.sync_positions()]) is True


def test_live_engine_reconcile_uses_presync_baseline(monkeypatch):
    """E3 (appendix B): _reconcile verifies against a PRE-sync snapshot, so
    the reconcile result measures broker-vs-store divergence instead of being
    vacuously true after sync_positions rewrites the store to match."""
    from core.pipeline import recon_engine
    from operations.live_engine import LiveEngine
    from core.state import PositionState

    adapter = FakeAdapter(FakePos())
    adapter.fetch_candles.return_value = []
    engine = LiveEngine(symbols=["XAUUSD"], adapter=adapter)
    for p in state.open_positions():
        state.close_position(p.position_id, p.entry_price)
    state.add_position(PositionState(
        position_id="mt5-pos-77", symbol="XAUUSD",
        direction=contracts.TradeDirection.LONG, volume=0.01,
        entry_price=4350.21, current_price=4350.21))

    captured = {}
    real_verify = recon_engine.verify

    def wrapped(remote, baseline=None):
        captured["baseline"] = dict(baseline or {})
        return real_verify(remote, baseline=baseline)

    monkeypatch.setattr(recon_engine, "verify", wrapped)

    assert engine.cycle() == 1
    assert "mt5-pos-77" in captured["baseline"]
    assert captured["baseline"]["mt5-pos-77"]["volume"] == 0.01


def test_trading_loop_uses_injected_executor():
    adapter = FakeAdapter(FakePos())
    ex = LiveMT5Executor(adapter)
    loop = TradingLoop("XAUUSD", "M15", enable_execution=True, executor=ex)

    captured = {}
    loop._run_full_pipeline = lambda candles, ctx: captured.update(
        {"ticket": ex.execute(make_candidate(), approved_decision())})

    loop._run_full_pipeline([], None)

    assert captured["ticket"].status == ExecutionStatus.FILLED


class PaperFeedAdapter:
    """Fake live feed: growing candle window + live bid/ask market state."""

    def __init__(self, candles):
        self.candles = list(candles)
        self.connected = False
        self._last_error = ""
        self.i = 0
        self.placed = 0

    @property
    def available(self):
        return True

    def status(self):
        return {"last_error": self._last_error, "session_login": "paper"}

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def sync_account(self):
        state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))

    def sync_market(self, symbol):
        c = self.candles[min(max(self.i, 0), len(self.candles) - 1)]
        state.upsert_market(MarketState(symbol=symbol, bid=c.close,
                                        ask=c.close + 0.05, spread=0.05,
                                        last_price=c.close,
                                        last_tick_time=c.time))

    def fetch_candles(self, symbol, timeframe, count):
        self.i = min(self.i + 1, len(self.candles))
        return list(self.candles[:self.i])

    def place_position(self, *a, **k):
        self.placed += 1
        return None


def _paper_trend_series():
    """Deterministic rising BOS chain; constant enough to fill the paper desk."""
    candles = []
    price = 2300.0
    t = 300000.0
    for cyc in range(10):
        for i in range(18):
            o = price
            c = o + 8.0
            candles.append(contracts.Candle(
                symbol="XAUUSD", timeframe="M15", time=t, open=o,
                high=c + 2.0, low=o - 3.0, close=c,
                volume=100.0, tick_volume=50.0))
            t += 900.0
            price = c
        for i in range(3):  # sharp pullback retest
            o = price
            c = o - 10.0
            candles.append(contracts.Candle(
                symbol="XAUUSD", timeframe="M15", time=t, open=o,
                high=o + 1.0, low=c - 1.0, close=c,
                volume=80.0, tick_volume=40.0))
            t += 900.0
            price = c
    return candles


def test_live_engine_paper_watch_fills_desk_without_orders():
    from operations.live_engine import LiveEngine
    from core.market_plane import MarketPlane
    from learning.experience import ledger

    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    adapter = PaperFeedAdapter(_paper_trend_series())
    # The plane caches on a real clock, so a 180-cycle simulation gets its own
    # plane with the pull floor removed: each cycle is a fresh terminal read.
    plane = MarketPlane(min_pull_interval=0.0)
    engine = LiveEngine(symbols=["XAUUSD"], timeframe="M15", adapter=adapter,
                        learn_every=2, paper=True, htf_timeframe=None,
                        poll_seconds=0.0, plane=plane)

    for _ in range(180):
        engine.cycle()

    status = engine.status()
    assert status["paper"] is True
    assert len(status["errors"]) == 0
    stats = status["paper_stats"]["XAUUSD"]
    assert stats["trades"] >= 1
    assert adapter.placed == 0  # broker was never touched

    paper_recs = [r for r in ledger.all() if r.record_id.startswith("paper:")]
    assert len(paper_recs) >= stats["trades"]
    assert all(r.metadata.get("filled") is True for r in paper_recs)


def test_live_engine_live_mode_is_not_paper():
    from operations.live_engine import LiveEngine
    adapter = FakeAdapter(FakePos())
    adapter.fetch_candles.return_value = [
        contracts.Candle(symbol="XAUUSD", timeframe="M15",
                         time=1000.0 + i * 900, open=4300.0 + i,
                         high=4301.0 + i, low=4299.0 + i, close=4300.5 + i,
                         volume=100.0, tick_volume=10)
        for i in range(80)
    ]
    engine = LiveEngine(symbols=["XAUUSD"], adapter=adapter)
    assert engine.status()["paper"] is False
    assert "paper_stats" not in engine.status()


def test_live_engine_cycle_reads_market_through_the_canonical_plane():
    """One cycle = one shared plane read per symbol, with provenance.

    Before the plane, the engine called `fetch_candles` directly while the
    quote came from a separate `sync_market`, so nothing tied the two to one
    source or version.
    """
    from core.market_plane import MarketPlane, current_bar_start
    from operations.live_engine import LiveEngine

    adapter = FakeAdapter(FakePos())
    adapter.fetch_candles = MagicMock(
        return_value=[contracts.Candle(
            symbol="XAUUSD", timeframe="M15",
            time=current_bar_start("M15") - 900.0 * i, open=4300.0 + i,
            high=4301.0 + i, low=4299.0 + i, close=4300.5 + i,
            volume=100.0, tick_volume=10) for i in range(80)])
    plane = MarketPlane(min_pull_interval=0.0)
    engine = LiveEngine(symbols=["XAUUSD"], adapter=adapter, htf_timeframe=None,
                        use_school_board=False, plane=plane, poll_seconds=0.0)

    assert plane.feeds() == ["mt5"], "the engine wires the terminal into the plane"
    assert engine.cycle() == 1
    assert adapter.fetch_candles.call_count == 1, "one shared read, not one per consumer"

    win = plane.window("XAUUSD", "M15")
    assert win is not None and win.source == "mt5" and len(win.bars) == 80
    read = plane.read("XAUUSD", "M15", count=10, allow_pull=False)
    assert read.provenance["source"] == "mt5"
    assert read.provenance["version"] == win.version
    assert len(read.candles) == 10


def test_live_engine_cycle_does_not_pull_when_there_is_no_terminal():
    """A dead terminal must degrade to an honest gap, not an exception."""
    from core.market_plane import MarketPlane
    from operations.live_engine import LiveEngine

    adapter = FakeAdapter(FakePos())
    adapter.fetch_candles = MagicMock(side_effect=RuntimeError("no terminal"))
    plane = MarketPlane(min_pull_interval=0.0)
    engine = LiveEngine(symbols=["XAUUSD"], adapter=adapter, htf_timeframe=None,
                        use_school_board=False, plane=plane, poll_seconds=0.0)

    assert engine.cycle() == 1          # the cycle completed
    win = plane.window("XAUUSD", "M15")
    assert win is not None and not win.bars
    assert "no terminal" in win.errors[-1]
    snap = plane.snapshot()
    assert snap["summary"]["live"] is False
