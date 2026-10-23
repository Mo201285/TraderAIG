"""Tests for the live MT5 adapter (mocked terminal; no real connection)."""

from types import SimpleNamespace

import pytest

import execution.mt5_adapter as adapter_mod
from core.contracts import TradeDirection
from core.market_plane import MarketPlane, market_plane
from core.state import CanonicalState, PositionState, state
from decision.thesis import TradeCandidate
from execution.mt5_adapter import MT5Adapter
from learning.experience import ErrorType, ledger
from risk.governor import RiskDecisionKind


@pytest.fixture(autouse=True)
def _reset_canonical_state():
    """Hermetic tests: never bleed canonical positions/orders/ledger into
    other files via the module-global singleton `state`."""
    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    yield
    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)


def _no_creds(monkeypatch):
    monkeypatch.setattr(adapter_mod, "settings", SimpleNamespace(mt5=SimpleNamespace(
        login=0, password="", server="", terminal_path="")))


def _live_creds(monkeypatch):
    monkeypatch.setattr(adapter_mod, "settings", SimpleNamespace(mt5=SimpleNamespace(
        login=123456, password="secret", server="Broker-Demo",
        terminal_path="D:\\One\\mt5-portable\\terminal64.exe")))


def _make_fake_mt5():
    mt5 = SimpleNamespace()
    mt5.TRADE_ACTION_DEAL = 1
    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.ORDER_TIME_GTC = 0
    mt5.ORDER_FILLING_IOC = 1
    mt5.ORDER_FILLING_FOK = 0
    mt5.ORDER_FILLING_RETURN = 2
    mt5.ORDER_FILLING_BOC = 3
    mt5.TIMEFRAME_M1 = 1
    mt5.TIMEFRAME_M5 = 5
    mt5.TIMEFRAME_M15 = 15
    mt5.TIMEFRAME_H1 = 16385
    mt5.TRADE_RETCODE_DONE = 10009
    mt5.last_error = lambda: (10011, "no error")
    mt5.initialize = lambda **kw: True
    mt5.shutdown = lambda: None
    mt5.symbol_select = lambda sym, select: True
    mt5.terminal_info = lambda: SimpleNamespace(name="fake",
                                                trade_allowed=True,
                                                connected=True)
    return mt5


def _candidate(**kwargs) -> TradeCandidate:
    base = {
        "candidate_id": "cand-1",
        "thesis_id": "thesis-1",
        "symbol": "XAUUSD",
        "direction": TradeDirection.LONG,
        "entry": 2000.0,
        "stop_loss": 1990.0,
        "take_profit": 2020.0,
        "size": 0.10,
        "risk_reward": 2.0,
        "confidence": 0.7,
    }
    base.update(kwargs)
    return TradeCandidate(**base)


@pytest.fixture
def adapter():
    return MT5Adapter()


def test_observer_mode_without_credentials(monkeypatch, adapter):
    """Without credentials and with no live terminal the adapter must
    degrade gracefully into read-only observer mode."""
    _no_creds(monkeypatch)
    monkeypatch.setattr(adapter, "_terminal_running", lambda: False)
    assert adapter.available is False
    assert adapter.connect() is False
    assert adapter.place_position(_candidate(), RiskDecisionKind.APPROVED) is None
    assert adapter.start_watcher() is False
    st = adapter.status()
    assert st["available"] is False
    assert "LOCKED" in st["last_error"]


def test_session_attach_without_credentials(monkeypatch, adapter):
    """A running portable terminal can be adopted without a password."""
    _no_creds(monkeypatch)
    adapter_mod.settings.mt5.terminal_path = "D:\\One\\mt5-portable\\terminal64.exe"
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    monkeypatch.setattr(adapter, "_terminal_running", lambda: True)
    fake.account_info = lambda: SimpleNamespace(
        login=1363114, broker="FakeBroker", balance=100000.0, equity=100000.0,
        margin=0.0, margin_free=100000.0, leverage=1, currency="USD",
        server="FTTrading-Server")

    assert adapter.connect() is True
    assert adapter.attach_mode is True
    acc = adapter.sync_account()
    assert acc is not None
    assert state.get_account().login == 1363114


def test_account_sync_mirrors_into_canonical_state(monkeypatch, adapter):
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.account_info = lambda: SimpleNamespace(
        login=123456, broker="FakeBroker", balance=10000.0, equity=10100.0,
        margin=500.0, margin_free=9600.0, leverage=100, currency="USD",
        server="Broker-Demo")
    adapter._initialized = True

    acc = adapter.sync_account()
    assert acc is not None
    s = state.get_account()
    assert s.login == 123456
    assert s.balance == 10000.0
    assert s.equity == 10100.0
    assert s.leverage == 100
    assert s.currency == "USD"


def test_fetch_candles_maps_real_rates(monkeypatch, adapter):
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.copy_rates_from_pos = lambda sym, tf, pos, count: [
        {"time": 1000 + i, "open": 2000.0, "high": 2000.5, "low": 1999.5,
         "close": 2000.2, "tick_volume": 10, "real_volume": 0}
        for i in range(5)
    ]

    candles = adapter.fetch_candles("XAUUSD")
    assert len(candles) == 5
    assert candles[0].symbol == "XAUUSD"
    assert candles[0].timeframe == "M15"
    assert candles[-1].close == 2000.2


def test_fetch_candles_normalizes_venue_timeframe_spelling(monkeypatch, adapter):
    """A window can never mix MT5 constants with venue interval strings."""
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    seen = {}

    def copy_rates(sym, tf, pos, count):
        seen["tf"] = tf
        return [{"time": 1000, "open": 1.0, "high": 2.0, "low": 0.5,
                 "close": 1.5, "tick_volume": 1, "real_volume": 0}]

    fake.copy_rates_from_pos = copy_rates
    candles = adapter.fetch_candles("BTC-USDT", "1h")
    assert candles[0].timeframe == "H1"
    assert candles[0].symbol == "BTCUSDT"
    assert seen["tf"] == fake.TIMEFRAME_H1


def test_missing_symbol_on_a_connected_terminal_is_not_a_connection_fault(
        monkeypatch, adapter):
    """The CEX paper loop asks this FX/metals terminal for BTCUSDT every cycle.

    `last_error` is what the operator reads as connection health, so "this book
    does not carry crypto" must not be written there -- it was, once per pass,
    and it buried the real `Call failed` lines it sat beside.
    """
    import logging

    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.copy_rates_from_pos = lambda sym, tf, pos, count: None
    fake.symbol_info = lambda sym: None  # unknown to this terminal
    fake.last_error = lambda: (-1, "Terminal: Call failed")

    lines = []

    class _Capture(logging.Handler):
        def emit(self, record):
            lines.append((record.levelno, record.getMessage()))

    handler = _Capture()
    adapter_logger = adapter_mod.log._logger
    adapter_logger.addHandler(handler)
    try:
        assert adapter.fetch_candles("BTCUSDT") == []
        assert adapter.fetch_candles("BTCUSDT") == []
    finally:
        adapter_logger.removeHandler(handler)

    assert adapter.status()["last_error"] == ""
    said = [m for lvl, m in lines if "BTCUSDT" in m]
    assert len(said) == 1, "the fact belongs in the log once, not once per pass"
    assert all(lvl < logging.WARNING for lvl, _ in lines)


def test_a_dropped_terminal_still_reports_the_candle_failure(
        monkeypatch, adapter):
    """`symbol_info() is None` is also what a disconnected terminal answers for
    every symbol, so absence alone must not be read as "the venue does not
    carry it"."""
    import logging

    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.copy_rates_from_pos = lambda sym, tf, pos, count: None
    fake.symbol_info = lambda sym: None
    fake.terminal_info = lambda: SimpleNamespace(name="fake",
                                                 trade_allowed=True,
                                                 connected=False)
    fake.last_error = lambda: (-1, "Terminal: Call failed")

    lines = []

    class _Capture(logging.Handler):
        def emit(self, record):
            lines.append((record.levelno, record.getMessage()))

    handler = _Capture()
    adapter_logger = adapter_mod.log._logger
    adapter_logger.addHandler(handler)
    try:
        assert adapter.fetch_candles("XAUUSD") == []
    finally:
        adapter_logger.removeHandler(handler)

    assert "Call failed" in adapter.status()["last_error"]
    assert any(lvl == logging.WARNING and "copy_rates failed" in m
               for lvl, m in lines)


def test_sync_market_publishes_the_quote_into_the_plane(monkeypatch, adapter):
    """MT5 is the plane's quote producer; state and the plane share one object."""
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.symbol_info_tick = lambda sym: SimpleNamespace(
        bid=2000.0, ask=2000.5, last=2000.2, time=1700)
    fake.symbol_info = lambda sym: SimpleNamespace(
        trade_tick_size=0.01, trade_tick_value=1.0, trade_contract_size=100.0,
        volume_min=0.01, volume_step=0.01, volume_max=10.0, trade_mode=4)
    adapter._initialized = True

    mk = adapter.sync_market("XAUUSD")
    assert mk is not None
    assert market_plane.quote("XAUUSD") is mk
    assert state.get_market("XAUUSD") is mk
    read = market_plane.quote_read("XAUUSD")
    assert read.quote_source == "mt5"
    assert read.derived_quote is False
    assert read.freshness in ("fresh", "stale")
    state.market.pop("XAUUSD", None)


def test_register_market_feed_makes_the_terminal_pullable(monkeypatch, adapter):
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.copy_rates_from_pos = lambda sym, tf, pos, count: [
        {"time": 1700000000 + 900 * i, "open": 1.0, "high": 2.0, "low": 0.5,
         "close": 1.5, "tick_volume": 1, "real_volume": 0} for i in range(3)]

    plane = MarketPlane()
    original = market_plane
    try:
        # point the adapter's publish/registration at the isolated plane
        monkeypatch.setattr(adapter_mod, "market_plane", plane)
        adapter.register_market_feed()
        assert plane.feeds() == ["mt5"]
        r = plane.read("XAUUSD", "M15", count=3)
        assert r.source == "mt5" and len(r.candles) == 3
    finally:
        monkeypatch.setattr(adapter_mod, "market_plane", original)
        plane.reset()


def test_positions_sync_and_reconcile(monkeypatch, adapter):
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    calls = {"n": 0}

    def positions_get():
        calls["n"] += 1
        if calls["n"] == 1:
            return [SimpleNamespace(
                ticket=9001, symbol="XAUUSD", type=0, volume=0.1,
                price_open=2000.0, price_current=2005.0, sl=1990.0, tp=2020.0,
                time=1000, profit=50.0, swap=-1.2)]
        return []

    fake.positions_get = positions_get

    adapter.sync_positions()
    assert state.get_position("9001") is not None
    assert len(state.open_positions()) == 1

    adapter.sync_positions()
    assert len(state.open_positions()) == 0
    closed = state.get_position("9001")
    assert closed is not None
    assert closed.unrealized_pnl == 0.0


def test_history_feeds_experience_ledger(monkeypatch, adapter):
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.history_deals_get = lambda f, t: [
        SimpleNamespace(deal=11, time=1000, symbol="XAUUSD", volume=0.1,
                        price=2000.0, type=0, entry=0, profit=60.0,
                        commission=-1.0, swap=-0.5),
        SimpleNamespace(deal=12, time=1001, symbol="XAUUSD", volume=0.1,
                        price=2010.0, type=1, entry=1, profit=-40.0,
                        commission=-1.0, swap=-0.5),
    ]

    before = len(ledger.all())
    adapter.sync_history(days=7)
    after = len(ledger.all())
    assert after - before >= 2

    win = [r for r in ledger.all() if r.record_id == "mt5:11"][-1]
    loss = [r for r in ledger.all() if r.record_id == "mt5:12"][-1]
    assert win.error_classification is None
    assert loss.error_classification == ErrorType.EXPECTED_LOSS
    assert win.actual_result["source"] == "mt5"


def test_replaying_the_same_history_window_adds_nothing(monkeypatch, adapter):
    """The watcher re-reads the same deals every few seconds; a replay must not
    append a second copy to the ledger, nor keep the experience counter
    climbing with no new trades."""
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.history_deals_get = lambda f, t: [
        SimpleNamespace(deal=9901, time=1000, symbol="XAUUSD", volume=0.1,
                        price=2000.0, type=0, entry=0, profit=0.0,
                        commission=0.0, swap=0.0),
        SimpleNamespace(deal=9902, time=1001, symbol="XAUUSD", volume=0.1,
                        price=2010.0, type=1, entry=1, profit=5.0,
                        commission=0.0, swap=0.0),
    ]

    adapter.sync_history(days=7)
    first_count = len(ledger.all())
    first_experienced = adapter._sync_stats["experienced"]

    adapter.sync_history(days=7)
    assert len(ledger.all()) == first_count
    assert adapter._sync_stats["experienced"] == first_experienced
    assert len([r for r in ledger.all() if r.record_id == "mt5:9902"]) == 1


def test_sync_history_hydrates_the_ledger_before_replaying(monkeypatch, adapter):
    """A restart replays the persisted window, so the ledger has to know those
    ids before the deals arrive -- otherwise the replay counts as new
    experience again and re-teaches lessons that were already learned."""
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.history_deals_get = lambda f, t: []

    calls = []
    monkeypatch.setattr(
        ledger, "load_from_db", lambda *a, **k: calls.append((a, k)) or 0)

    adapter.sync_history(days=7)

    assert calls, "sync_history must hydrate the ledger before replaying deals"


def test_record_execution_stamps_strategy_id(monkeypatch):
    """E1 (appendix B): exec: attempts carry strategy provenance."""
    adapter = MT5Adapter()
    seen = []
    monkeypatch.setattr("learning.experience.ledger.record",
                        lambda rec: seen.append(rec), raising=False)
    c = _candidate()
    c.strategy_id = "s:prod"
    adapter._record_execution(c, None, SimpleNamespace(order=123))
    assert seen
    assert seen[-1].metadata["strategy_id"] == "s:prod"


def test_deal_to_record_stamps_strategy_from_position_map(monkeypatch):
    """E1 (appendix B): history deals replay the ticket->strategy bridge."""
    adapter = MT5Adapter()
    adapter._strategy_by_position[99] = "s:prod"
    seen = []
    monkeypatch.setattr("learning.experience.ledger.record",
                        lambda rec: seen.append(rec), raising=False)
    deal = SimpleNamespace(
        deal=77, ticket=77, time=1500, symbol="XAUUSD", volume=0.1,
        price=4000.0, type=1, entry=1, profit=20.0, commission=0.0, swap=0.0,
        magic=123456, comment="TraderAIG:xyz", position=99,
    )
    adapter._deal_to_record(deal)
    assert seen
    assert seen[-1].metadata["strategy_id"] == "s:prod"


def test_deal_records_carry_the_attached_account(monkeypatch):
    """The truth plane can only call a fill "real" if it names the account."""
    adapter = MT5Adapter()
    adapter._account_ref = "TEST-ACCT-777"
    seen = []
    monkeypatch.setattr("learning.experience.ledger.record",
                        lambda rec: seen.append(rec), raising=False)
    deal = SimpleNamespace(
        deal=78, ticket=78, time=1500, symbol="XAUUSD", volume=0.1,
        price=4000.0, type=1, entry=1, profit=20.0, commission=0.0, swap=0.0,
        magic=123456, comment="TraderAIG:xyz", position=99,
    )
    adapter._deal_to_record(deal)
    assert seen
    assert seen[-1].metadata["account"] == "TEST-ACCT-777"


def test_sync_preserves_partial_realized_and_keeps_swap_separate(monkeypatch, adapter):
    """E4 (appendix B): a broker sync must NOT mislabel swap as realized PnL
    nor wipe the realized accumulation from our own partial closes."""
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.positions_get = lambda: [SimpleNamespace(
        ticket=9002, symbol="XAUUSD", type=0, volume=0.1,
        price_open=2000.0, price_current=2005.0, sl=1990.0, tp=2020.0,
        time=1000, profit=50.0, swap=-1.2)]

    # a partial close already booked +0.3 realized on ticket 9002
    state.add_position(PositionState(
        position_id="9002", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=2000.0, current_price=2005.0))
    state.settle_realized("9002", 0.3)

    adapter.sync_positions()

    synced = state.get_position("9002")
    assert synced.realized_pnl == pytest.approx(0.3)   # preserved, not p.swap
    assert synced.swap == pytest.approx(-1.2)          # financing cost, separate
    assert state.risk.daily_pnl == pytest.approx(0.3)  # partial stays booked


def test_close_partial_books_daily_pnl_from_the_partial(monkeypatch, adapter):
    """E4 (appendix B): a successful partial close reaches the daily-loss
    guard immediately instead of waiting (and being wiped by) the final close."""
    _live_creds(monkeypatch)
    adapter._initialized = True  # `connected` is a derived property
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.symbol_info_tick = lambda sym: SimpleNamespace(bid=2010.0, ask=2010.2)
    dispatched = []
    fake.order_send = lambda req: dispatched.append(req) or SimpleNamespace(
        retcode=10009, comment="done")

    state.add_position(PositionState(
        position_id="9003", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.2, entry_price=2000.0, current_price=2008.0))

    assert adapter.close_partial("9003", 0.1) is True

    pos = state.get_position("9003")
    assert pos.volume == pytest.approx(0.1)
    assert pos.realized_pnl == pytest.approx(1.0)   # (2010-2000)*0.1
    assert state.risk.daily_pnl == pytest.approx(1.0)  # guard sees the partial
    assert state.get_position("9003").status.value == "open"
    assert dispatched  # the deal actually reached the (fake) broker


def test_history_position_keyed_fallback(monkeypatch, adapter):
    """When the time-window query comes back empty (server-local zone gap or
    terminal cache warming), closed position ids fall back to a direct
    position-keyed deal pull so the round-trip still reaches the ledger."""
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)

    def deals_get(*args, **kwargs):
        if kwargs.get("position"):
            return [
                SimpleNamespace(deal=31, time=2000, symbol="XAUUSD", volume=0.01,
                                price=4300.0, type=0, entry=0, profit=5.0,
                                commission=-0.5, swap=0.0),
                SimpleNamespace(deal=32, time=2001, symbol="XAUUSD", volume=0.01,
                                price=4310.0, type=1, entry=1, profit=-3.0,
                                commission=-0.5, swap=0.0),
            ]
        return []

    fake.history_deals_get = deals_get
    adapter._recent_closed_ids = [777]

    adapter.sync_history(days=7)

    ids = {r.record_id for r in ledger.all()}
    assert "mt5:31" in ids
    assert "mt5:32" in ids
    assert adapter._recent_closed_ids == []
    assert adapter._sync_stats["history"] == 2


def test_place_position_refuses_unapproved(monkeypatch, adapter):
    _no_creds(monkeypatch)
    assert adapter.place_position(_candidate(), RiskDecisionKind.VETOED) is None


def test_place_position_fills_when_approved_and_connected(monkeypatch, adapter):
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    adapter._initialized = True
    fake.symbol_info = lambda sym: SimpleNamespace(name=sym)
    fake.symbol_info_tick = lambda sym: SimpleNamespace(bid=1999.9, ask=2000.1,
                                                        last=2000.0, time=1000)

    # Fresh canonical state so the gate passes.
    from core.state import AccountState
    state.set_account(AccountState(login=123, balance=10_000.0,
                                   equity=10_000.0, leverage=100))
    state.risk.daily_pnl = 0.0

    fake.order_send = lambda req: SimpleNamespace(
        retcode=10009, order=777, price=2000.1, comment="done")
    fake.positions_get = lambda: [SimpleNamespace(
        ticket=777, symbol="XAUUSD", type=0, volume=0.1,
        price_open=2000.1, price_current=2000.1, sl=1990.0, tp=2020.0,
        time=1000, profit=0.0, swap=0.0)]

    pos = adapter.place_position(_candidate(strategy_id="xauusd:loop:v1",
                                            strategy_stage="production"),
                                  RiskDecisionKind.APPROVED)
    assert pos is not None
    assert pos.position_id == "777"
    assert state.get_position("777") is not None


def test_the_fill_log_reports_the_booked_price_not_zero(monkeypatch, adapter):
    """`OrderSendResult.price` reads 0.0 for market sends on this build, so the
    audit line said every live trade filled at 0.0. Log the price the terminal
    actually booked on the position instead.

    The adapter's logger is configured with `propagate` off, so caplog never
    sees it: capture through a handler on the adapter's own logger.
    """
    import logging

    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    adapter._initialized = True
    fake.symbol_info = lambda sym: SimpleNamespace(name=sym)
    fake.symbol_info_tick = lambda sym: SimpleNamespace(bid=1999.9, ask=2000.1,
                                                        last=2000.0, time=1000)

    from core.state import AccountState
    state.set_account(AccountState(login=123, balance=10_000.0,
                                   equity=10_000.0, leverage=100))
    state.risk.daily_pnl = 0.0

    fake.order_send = lambda req: SimpleNamespace(
        retcode=10009, order=778, price=0.0, comment="done")
    fake.positions_get = lambda: [SimpleNamespace(
        ticket=778, symbol="XAUUSD", type=0, volume=0.1,
        price_open=2000.7, price_current=2001.0, sl=1990.0, tp=2020.0,
        time=1000, profit=0.0, swap=0.0)]

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture()
    adapter_logger = adapter_mod.log._logger
    adapter_logger.addHandler(handler)
    try:
        adapter.place_position(_candidate(strategy_id="xauusd:loop:v1",
                                          strategy_stage="production"),
                               RiskDecisionKind.APPROVED)
    finally:
        adapter_logger.removeHandler(handler)

    filled = [line for line in records if line.startswith("MT5 FILLED")]
    assert filled, "the fill was never logged"
    assert "@ 2000.7" in filled[0]
    assert "@ 0.0" not in filled[0]


def test_place_position_falls_back_across_filling_modes(monkeypatch, adapter):
    """Some brokers advertise one filling mode but accept another; the
    adapter must walk the chain (e.g. FOK for XAUUSD on FTTrading)."""
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    adapter._initialized = True
    fake.symbol_info = lambda sym: SimpleNamespace(name=sym)
    fake.symbol_info_tick = lambda sym: SimpleNamespace(bid=1999.9, ask=2000.1,
                                                        last=2000.0, time=1000)

    from core.state import AccountState
    state.set_account(AccountState(login=123, balance=10_000.0,
                                   equity=10_000.0, leverage=100))
    state.risk.daily_pnl = 0.0

    filled = {"done": False}
    fake.positions_get = lambda: ([SimpleNamespace(
        ticket=888, symbol="XAUUSD", type=0, volume=0.1,
        price_open=2000.1, price_current=2000.1, sl=1990.0, tp=2020.0,
        time=1000, profit=0.0, swap=0.0)] if filled["done"] else [])

    def order_send(req):
        if req.get("type_filling") == fake.ORDER_FILLING_FOK:
            filled["done"] = True
            return SimpleNamespace(retcode=10009, order=888, price=2000.1,
                                   comment="done")
        return SimpleNamespace(retcode=10022, order=0, price=0.0,
                               comment="Unsupported filling mode")

    fake.order_send = order_send

    pos = adapter.place_position(_candidate(strategy_id="xauusd:loop:v1",
                                            strategy_stage="production"),
                                  RiskDecisionKind.APPROVED)
    assert pos is not None
    assert pos.position_id == "888"
    assert filled["done"] is True


# ---------------------------------------------------------------------------
# Position management: modify SL/TP and partial close on the live terminal
# ---------------------------------------------------------------------------


def _open_position(adapter, monkeypatch):
    _live_creds(monkeypatch)
    fake = _make_fake_mt5()
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)
    fake.TRADE_ACTION_SLTP = 6
    fake.ORDER_TYPE_SELL = 1
    fake.ORDER_TYPE_BUY = 0
    return fake


def test_modify_position_sends_sltp_and_updates_state(monkeypatch, adapter):
    fake = _open_position(adapter, monkeypatch)
    sent = {}

    def order_send(req):
        sent["req"] = req
        return SimpleNamespace(retcode=fake.TRADE_RETCODE_DONE)

    fake.order_send = order_send
    adapter._initialized = True

    from core.state import AccountState, PositionState
    state.set_account(AccountState(login=123, balance=10_000.0,
                                   equity=10_000.0, leverage=100))
    position = PositionState(
        position_id="50", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=2000.0, current_price=2000.0,
        sl=1995.0, tp=2020.0)
    state.risk.daily_pnl = 0.0
    state.add_position(position)
    adapter.sync_positions = lambda: None

    ok = adapter.modify_position("50", new_sl=2000.0, new_tp=2020.0)
    assert ok is True
    assert sent["req"]["action"] == 6
    assert sent["req"]["sl"] == 2000.0
    assert sent["req"]["tp"] == 2020.0
    assert state.get_position("50").sl == 2000.0


def test_close_partial_reduces_volume(monkeypatch, adapter):
    fake = _open_position(adapter, monkeypatch)
    fake.symbol_info_tick = lambda sym: SimpleNamespace(bid=2000.1, ask=2000.2)

    def order_send(req):
        return SimpleNamespace(retcode=fake.TRADE_RETCODE_DONE)

    fake.order_send = order_send
    adapter._initialized = True

    from core.state import AccountState, PositionState
    state.set_account(AccountState(login=123, balance=10_000.0,
                                   equity=10_000.0, leverage=100))
    state.risk.daily_pnl = 0.0
    state.add_position(PositionState(
        position_id="51", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.2, entry_price=2000.0, current_price=2000.0,
        sl=1995.0, tp=2020.0))
    adapter.sync_positions = lambda: None

    ok = adapter.close_partial("51", volume=0.1)
    assert ok is True
    assert abs(state.get_position("51").volume - 0.1) < 1e-6
