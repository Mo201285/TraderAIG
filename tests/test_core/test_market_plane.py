"""Unit tests for the canonical market data plane (Phase B - 28.6).

Covers the contract the rest of the system now depends on:
  * one symbol/timeframe vocabulary (normalization) at every ingest point;
  * bounded windows + bounded shadow/error records (no unbounded memory);
  * single-source windows: a lower-priority feed is shadowed, never mixed;
  * provenance + monotonic versioning so a read is reproducible (3.1);
  * honest freshness from real bar/tick clocks (never "file exists = healthy");
  * one shared pull per cache miss instead of N terminal round-trips;
  * quotes: canonical object, mirrored into core.state for existing consumers;
  * streaming append semantics (bridge/EA) vs full-series publish (MT5/CEX);
  * bridge frames: real values only, junk rejected rather than defaulted.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle
from core.market_plane import (
    MarketPlane,
    canonical_symbol,
    canonical_timeframe,
    current_bar_start,
    is_known_timeframe,
    source_rank,
    timeframe_seconds,
)
from core.state import MarketState, state


BASE = 1_700_000_000.0


def live():
    """A real "now" anchor, resolved per call.

    A module-level constant would be captured at *collection* time, so a slow
    first test module would silently age every freshness assertion.
    """
    return time.time()


def bar(time: float, close: float = 100.0, symbol: str = "XAUUSD",
        timeframe: str = "M15") -> Candle:
    return Candle(symbol=symbol, timeframe=timeframe, time=time,
                  open=close, high=close + 1, low=close - 1, close=close,
                  volume=1.0, tick_volume=10.0)


def series(count: int, start: float = BASE, step: float = 900.0,
           close: float = 100.0, **kw) -> list:
    return [bar(start + i * step, close + i, **kw) for i in range(count)]


def quote(symbol: str = "XAUUSD", tick: float = BASE, last: float = 2000.0):
    return MarketState(symbol=symbol, bid=last - 0.5, ask=last + 0.5,
                       spread=1.0, last_price=last, last_tick_time=tick)


# -- normalization ---------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("M15", "M15"), ("m15", "M15"), ("TIMEFRAME_M15", "M15"),
    ("15m", "M15"), ("1H", "H1"), ("1h", "H1"), ("4h", "H4"), ("1D", "D1"),
    ("1w", "W1"), ("", "M15"), (None, "M15"), ("garbage", "M15"),
])
def test_canonical_timeframe_normalizes_every_spelling(raw, expected):
    assert canonical_timeframe(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("btc-usdt", "BTCUSDT"), ("BTCUSDT", "BTCUSDT"), ("BTC-USDT", "BTCUSDT"),
    (" xauusd ", "XAUUSD"), ("", "XAUUSD"), (None, "XAUUSD"),
])
def test_canonical_symbol_normalizes_to_one_spelling(raw, expected):
    assert canonical_symbol(raw) == expected


def test_timeframe_seconds_uses_real_bar_durations():
    assert timeframe_seconds("15m") == 900
    assert timeframe_seconds("TIMEFRAME_M15") == 900
    assert timeframe_seconds("1h") == 3600
    assert timeframe_seconds("1w") == 604800


def test_source_rank_orders_live_feeds_above_pulls():
    assert source_rank("mt5") > source_rank("cex") > source_rank("bridge")
    assert source_rank("fallback") < source_rank("bridge")
    # family aliases keep the family's rank
    assert source_rank("cex:okx") == source_rank("cex")
    assert source_rank("bridge:session-1") == source_rank("bridge")


def test_current_bar_start_is_aligned_to_the_bar_duration():
    # 1_700_000_800 sits 700s into the 900s M15 bar that started at 1_700_000_100
    assert current_bar_start("M15", 1_700_000_800.0) == 1_700_000_100.0
    assert current_bar_start("H1", 1_700_000_800.0) == 1_699_999_200.0
    # 1_700_000_800 is 40s into the minute that started at 1_700_000_760
    assert current_bar_start("M1", 1_700_000_800.0) == 1_700_000_760.0


def test_window_reports_whether_its_last_bar_is_the_forming_one():
    p = MarketPlane()
    now = live()
    forming = current_bar_start("M15", now)
    p.publish_candles("XAUUSD", "M15", [bar(forming, 1.0)], source="mt5")
    win = p.window("XAUUSD", "M15")
    assert win.is_current_bar(now + 100) is True
    # once the bar closed, the window is behind the market
    assert win.is_current_bar(now + 900) is False


def test_a_window_behind_the_market_is_re_pulled_even_while_fresh():
    """After a bar rollover a cached window must not be served silently."""
    calls = []

    def feed(symbol, timeframe, count):
        calls.append(count)
        # the feed is one bar behind: its newest bar already closed
        return [bar(current_bar_start("M15") - 900, float(len(calls)))]

    p = MarketPlane(min_pull_interval=0.0)
    p.register_feed("mt5", feed)
    p.read("XAUUSD", "M15", count=1)
    p.read("XAUUSD", "M15", count=1)
    assert len(calls) == 2
    assert p.candles("XAUUSD", "M15")[-1].close == 2.0


def test_max_age_seconds_gives_a_polling_producer_a_fresh_forming_bar():
    calls = []

    def feed(symbol, timeframe, count):
        calls.append(count)
        return [bar(current_bar_start("M15"), 1.0 + len(calls))]

    p = MarketPlane(min_pull_interval=0.0)
    p.register_feed("mt5", feed)
    first = p.read("XAUUSD", "M15", count=1, max_age_seconds=0.0)
    second = p.read("XAUUSD", "M15", count=1, max_age_seconds=0.0)
    assert len(calls) == 2, "a polling producer re-reads on its own cadence"
    assert second.candles[-1].close > first.candles[-1].close
    assert second.version == 2


def test_without_max_age_a_producer_also_shares_the_cached_window():
    calls = []

    def feed(symbol, timeframe, count):
        calls.append(count)
        return [bar(current_bar_start("M15"), 1.0)]

    p = MarketPlane(min_pull_interval=0.0)
    p.register_feed("mt5", feed)
    p.read("XAUUSD", "M15", count=1)
    p.read("XAUUSD", "M15", count=1)
    assert len(calls) == 1


def test_a_producer_poll_is_still_throttled_within_the_interval():
    calls = []

    def feed(symbol, timeframe, count):
        calls.append(count)
        return [bar(current_bar_start("M15"), 1.0)]

    p = MarketPlane(min_pull_interval=60.0)
    p.register_feed("mt5", feed)
    for _ in range(5):
        p.read("XAUUSD", "M15", count=1, max_age_seconds=0.0)
    assert len(calls) == 1


# -- full-series publish + bounded storage ---------------------------------

def test_publish_candles_replaces_window_and_stamps_provenance():
    p = MarketPlane()
    win = p.publish_candles("xauusd", "15m", series(5), source="mt5")
    assert win is not None
    assert win.symbol == "XAUUSD" and win.timeframe == "M15"
    assert len(win.bars) == 5
    assert win.source == "mt5" and win.version == 1
    assert win.fetched_at > 0
    # a later full fetch replaces the series and bumps the version
    win2 = p.publish_candles("XAUUSD", "M15", series(3, close=200.0), source="mt5")
    assert len(win2.bars) == 3 and win2.version == 2
    assert win2.bars[-1].close == 202.0


def test_publish_normalizes_every_bar_so_windows_cannot_mix_vocabularies():
    p = MarketPlane()
    mixed = [bar(BASE, symbol="btc-usdt", timeframe="15m"),
             bar(BASE + 900, symbol="BTC-USDT", timeframe="1H")]
    win = p.publish_candles("BTCUSDT", "M15", mixed, source="cex")
    assert all(b.symbol == "BTCUSDT" and b.timeframe == "M15" for b in win.bars)


def test_window_is_bounded_by_max_bars():
    p = MarketPlane(max_bars=10)
    win = p.publish_candles("XAUUSD", "M15", series(50), source="mt5")
    assert len(win.bars) == 10
    # the newest bars survive
    assert win.bars[-1].time == BASE + 49 * 900


def test_empty_publish_is_not_a_window():
    p = MarketPlane()
    assert p.publish_candles("XAUUSD", "M15", [], source="mt5") is None
    assert p.window("XAUUSD", "M15") is None


def test_window_count_is_bounded_by_most_recent_publish():
    p = MarketPlane(max_windows=3)
    for i, sym in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"]):
        p.publish_candles(sym, "M15", series(1, start=BASE + i * 900), source="mt5")
    assert len(p.snapshot()["windows"]) == 3
    assert "EEE" in p.symbols() and "AAA" not in p.symbols()


# -- single-source windows (no silent mixing) ------------------------------

def test_lower_priority_source_is_shadowed_and_never_mixes():
    p = MarketPlane()
    live = p.publish_candles("XAUUSD", "M15", series(4), source="mt5")
    shadowed = p.publish_candles("XAUUSD", "M15", series(4, close=999.0),
                                 source="fallback")
    assert shadowed is None
    assert len(live.bars) == 4
    assert all(b.close != 999.0 for b in live.bars)
    assert live.source == "mt5"
    assert live.shadowed[-1]["source"] == "fallback"


def test_higher_priority_source_takes_over_a_lower_priority_window():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(2, close=50.0), source="fallback")
    win = p.publish_candles("XAUUSD", "M15", series(2, close=70.0), source="cex")
    assert win.source == "cex" and win.bars[-1].close == 71.0


def test_equal_priority_publish_is_allowed_for_the_same_source():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(2), source="mt5")
    win = p.publish_candles("XAUUSD", "M15", series(4), source="mt5")
    assert len(win.bars) == 4 and win.source == "mt5"


def test_shadow_records_are_bounded():
    p = MarketPlane(max_bars=5, max_shadow=2)
    p.publish_candles("XAUUSD", "M15", series(2), source="mt5")
    for i in range(5):
        p.publish_candles("XAUUSD", "M15", series(1, close=float(i)),
                          source="fallback")
    win = p.window("XAUUSD", "M15")
    assert len(win.shadowed) == 2


# -- streaming append (bridge / EA) ----------------------------------------

def test_append_bars_never_wipes_history():
    p = MarketPlane()
    p.append_bars("XAUUSD", "M15", series(3), source="bridge")
    p.append_bars("XAUUSD", "M15", [bar(BASE + 3 * 900, 150.0)], source="bridge")
    bars = p.candles("XAUUSD", "M15")
    assert len(bars) == 4 and bars[-1].close == 150.0


def test_append_replaces_the_last_bar_in_place_for_a_live_bar():
    p = MarketPlane()
    p.append_bars("XAUUSD", "M15", series(3), source="bridge")
    # the same M15 bar re-published with a newer close
    p.append_bars("XAUUSD", "M15", [bar(BASE + 2 * 900, 500.0)], source="bridge")
    bars = p.candles("XAUUSD", "M15")
    assert len(bars) == 3, "an updating live bar must not add a row"
    assert bars[-1].close == 500.0


def test_append_ignores_out_of_order_frames():
    p = MarketPlane()
    p.append_bars("XAUUSD", "M15", series(3), source="bridge")
    assert p.append_bars("XAUUSD", "M15", [bar(BASE, 1.0)], source="bridge") == 0
    assert p.candles("XAUUSD", "M15")[0].close == 100.0


def test_streaming_frame_is_normalized_and_bounded():
    p = MarketPlane(max_bars=4)
    for i in range(10):
        p.publish_tick_bar({"symbol": "btc-usdt", "timeframe": "1h",
                            "time": BASE + i * 3600, "open": 1, "high": 2,
                            "low": 0.5, "close": 1.5}, source="bridge")
    bars = p.candles("BTCUSDT", "H1")
    assert len(bars) == 4
    assert all(b.symbol == "BTCUSDT" and b.timeframe == "H1" for b in bars)


def test_frame_missing_ohlc_is_rejected_not_defaulted():
    p = MarketPlane()
    assert p.publish_tick_bar({"symbol": "XAUUSD", "timeframe": "M1",
                               "time": BASE, "close": 1.0}, source="bridge") is None
    assert p.window("XAUUSD", "M1") is None
    assert p.publish_tick_bar({"symbol": "XAUUSD", "close": 1.0, "open": 1,
                               "high": 1, "low": 1}, source="bridge") is None


def test_tick_frame_becomes_a_one_price_bar_plus_quote():
    p = MarketPlane()
    win = p.publish_bridge_quote(quote("XAUUSD", tick=BASE, last=2000.0),
                                 source="bridge", timeframe="M1")
    assert win is not None and len(win.bars) == 1
    b = win.bars[0]
    assert b.open == b.high == b.low == b.close == 2000.0
    assert b.tick_volume == 1.0
    assert p.quote("XAUUSD").bid == 1999.5
    assert p.quote_read("XAUUSD").quote_source == "bridge"


def test_bridge_quote_without_a_price_is_not_invented():
    p = MarketPlane()
    assert p.publish_bridge_quote(quote(tick=BASE, last=0.0), source="bridge") is None
    assert p.window("XAUUSD", "M1") is None


# -- quotes ----------------------------------------------------------------

def test_publish_quote_mirrors_the_same_object_into_canonical_state():
    p = MarketPlane()
    q = quote("XAUUSD")
    p.publish_quote(q, source="mt5")
    assert p.quote("xauusd") is q
    assert state.get_market("XAUUSD") is q
    state.market.pop("XAUUSD", None)


def test_publish_quote_normalizes_the_symbol_in_place():
    p = MarketPlane()
    q = quote("btc-usdt")
    p.publish_quote(q, source="cex")
    assert q.symbol == "BTCUSDT"
    assert p.quote("BTCUSDT") is q


def test_quote_read_reports_real_age_and_provenance():
    p = MarketPlane(stale_quote_seconds=120.0)
    p.publish_quote(quote(tick=BASE, last=2000.0), source="mt5")
    r = p.quote_read("XAUUSD", now=BASE + 10.0)
    assert r.freshness == "fresh" and r.quote_age_seconds == 10.0
    assert r.quote_source == "mt5" and r.derived_quote is False
    r2 = p.quote_read("XAUUSD", now=BASE + 500.0)
    assert r2.freshness == "stale" and r2.quote_age_seconds == 500.0


def test_quote_without_a_tick_time_is_never_reported_fresh():
    p = MarketPlane()
    p.publish_quote(MarketState(symbol="XAUUSD", bid=1.0, ask=1.0), source="mt5")
    r = p.quote_read("XAUUSD", now=BASE)
    assert r.freshness == "stale" and r.quote_age_seconds is None


def test_missing_quote_is_reported_missing():
    p = MarketPlane()
    r = p.quote_read("NOSUCH", now=BASE)
    assert r.freshness == "missing" and r.quote is None


def test_derived_quote_is_flagged_so_a_bar_price_is_not_passed_off_as_a_tick():
    p = MarketPlane()
    p.publish_quote(quote(), source="cex", derived=True)
    assert p.quote_read("XAUUSD").derived_quote is True


def test_lower_priority_quote_cannot_replace_the_owners_quote():
    """A venue/bridge rail must not overwrite the window owner's tick.

    Quotes follow the same precedence as candles: cex (90) and bridge (50)
    are both below mt5 (100), so the canonical tick stays MT5's and the
    refused publish is recorded rather than silently dropped.
    """
    p = MarketPlane()
    owner = quote("XAUUSD", tick=live(), last=2000.0)
    p.publish_quote(owner, source="mt5")
    p.publish_quote(quote("XAUUSD", tick=live(), last=9999.0), source="cex")
    assert p.quote("XAUUSD") is owner
    assert p.quote("XAUUSD").last_price == 2000.0
    shadow = p.quote_shadow("XAUUSD")
    assert shadow[-1]["source"] == "cex"
    assert shadow[-1]["owner"] == "mt5"
    # ...and the mirror in core.state was not overwritten either.
    assert state.get_market("XAUUSD") is owner
    state.market.pop("XAUUSD", None)


def test_bridge_quote_cannot_replace_a_cex_owner_either():
    p = MarketPlane()
    cex = quote("XAUUSD", tick=live(), last=50000.0)
    p.publish_quote(cex, source="cex:okx")
    p.publish_quote(quote("XAUUSD", tick=live(), last=1.0), source="bridge:abc")
    assert p.quote("XAUUSD") is cex
    state.market.pop("XAUUSD", None)


def test_higher_priority_quote_takes_over_ownership():
    p = MarketPlane()
    p.publish_quote(quote("XAUUSD", tick=live(), last=50000.0), source="cex")
    mt5 = quote("XAUUSD", tick=live(), last=2000.0)
    p.publish_quote(mt5, source="mt5")
    assert p.quote("XAUUSD") is mt5
    assert p.quote_read("XAUUSD").quote_source == "mt5"
    state.market.pop("XAUUSD", None)


def test_same_priority_quote_refresh_is_allowed():
    """An MT5 tick arriving every second must be able to update its own quote."""
    p = MarketPlane()
    p.publish_quote(quote("XAUUSD", tick=live(), last=2000.0), source="mt5")
    p.publish_quote(quote("XAUUSD", tick=live(), last=2001.0), source="mt5")
    assert p.quote("XAUUSD").last_price == 2001.0
    assert p.quote_shadow("XAUUSD") == []
    state.market.pop("XAUUSD", None)


def test_derived_quote_never_takes_ownership_from_a_live_tick():
    """A bar-derived close is a fallback, not a takeover."""
    p = MarketPlane()
    mt5 = quote("XAUUSD", tick=live(), last=2000.0)
    p.publish_quote(mt5, source="mt5")
    p.publish_quote(quote("XAUUSD", tick=live(), last=2000.0), source="backtest",
                    derived=True)
    assert p.quote("XAUUSD") is mt5
    state.market.pop("XAUUSD", None)


def test_quote_shadow_is_bounded():
    p = MarketPlane(max_shadow=2)
    p.publish_quote(quote("XAUUSD", tick=live()), source="mt5")
    for _ in range(5):
        p.publish_quote(quote("XAUUSD", tick=live()), source="bridge:x")
    assert len(p.quote_shadow("XAUUSD")) == 2
    state.market.pop("XAUUSD", None)


def test_read_reports_single_source_and_flags_a_genuine_mix():
    p = MarketPlane()
    p.publish_quote(quote("XAUUSD", tick=live(), last=2000.0), source="mt5")
    p.publish_candles("XAUUSD", "M15", series(4, start=BASE), source="mt5")
    r = p.read("XAUUSD", "M15", allow_pull=False)
    assert r.single_source is True
    # A CEX *bar* window under an MT5 quote is a real mix: say so, do not hide it.
    p2 = MarketPlane()
    p2.publish_quote(quote("XAUUSD", tick=live(), last=2000.0), source="mt5")
    p2.publish_candles("XAUUSD", "M15", series(4, start=BASE), source="cex")
    assert p2.read("XAUUSD", "M15", allow_pull=False).single_source is False
    # bars-only read: not enough information, not a claim of consistency
    p3 = MarketPlane()
    p3.publish_candles("XAUUSD", "M15", series(4, start=BASE), source="mt5")
    assert p3.read("XAUUSD", "M15", allow_pull=False).single_source is None
    state.market.pop("XAUUSD", None)


def test_provenance_carries_the_single_source_verdict():
    p = MarketPlane()
    p.publish_quote(quote("XAUUSD", tick=live()), source="mt5")
    p.publish_candles("XAUUSD", "M15", series(4, start=BASE), source="mt5")
    prov = p.read("XAUUSD", "M15", allow_pull=False).provenance
    assert prov["single_source"] is True
    state.market.pop("XAUUSD", None)


# -- freshness -------------------------------------------------------------

def test_window_freshness_uses_the_real_bar_clock():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(1, start=BASE), source="mt5")
    win = p.window("XAUUSD", "M15")
    assert win.freshness(BASE + 60) == "fresh"
    # two M15 durations (1800s) without a newer bar -> honest "stale"
    assert win.freshness(BASE + 1800) == "fresh"
    assert win.freshness(BASE + 1801) == "stale"


def test_empty_window_is_missing_not_fresh():
    p = MarketPlane()
    win = p.publish_candles("XAUUSD", "M15", series(1), source="mt5")
    win.bars.clear()
    assert win.freshness() == "missing"
    assert win.staleness() == 0.0


def test_expire_stale_drops_windows_past_the_ceiling():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(1, start=BASE), source="mt5")
    assert p.expire_stale(1.0) == 1
    assert p.window("XAUUSD", "M15") is None


def test_expire_stale_keeps_live_windows():
    p = MarketPlane()
    now = p.snapshot()["at"]
    p.publish_candles("XAUUSD", "M15", series(1, start=now), source="mt5")
    assert p.expire_stale(3600.0) == 0
    assert p.window("XAUUSD", "M15") is not None


# -- the canonical read + shared pulls -------------------------------------

def test_read_returns_bars_quote_and_provenance_together():
    p = MarketPlane()
    p.publish_quote(quote(tick=live(), last=2000.0), source="mt5")
    p.publish_candles("XAUUSD", "M15", series(4, start=live() - 2700), source="mt5")
    r = p.read("xauusd", "15m", count=4, allow_pull=False)
    assert r.symbol == "XAUUSD" and r.timeframe == "M15"
    assert len(r.candles) == 4 and r.quote is not None
    assert r.source == "mt5" and r.version == 1
    assert r.quote_source == "mt5"
    prov = r.provenance
    assert prov["source"] == "mt5" and prov["version"] == 1
    assert prov["bars"] == 4 and prov["quote_age_seconds"] < 5.0
    assert prov["freshness"] == "fresh"


def test_read_honours_the_count_argument():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(10), source="mt5")
    assert len(p.read("XAUUSD", "M15", count=3, allow_pull=False).candles) == 3
    assert len(p.candles("XAUUSD", "M15", limit=2)) == 2


def test_read_pulls_once_from_a_registered_feed_and_caches_it():
    calls = []

    def feed(symbol, timeframe, count):
        calls.append((symbol, timeframe, count))
        return series(5)

    p = MarketPlane()
    p.register_feed("MT5", feed)
    assert p.feeds() == ["mt5"]
    a = p.read("XAUUSD", "M15", count=5)
    b = p.read("XAUUSD", "M15", count=5)
    c = p.read("xauusd", "15m", count=5)
    assert len(calls) == 1, "N consumers must share one pull, not N round-trips"
    assert a.source == "mt5" and b.candles == a.candles == c.candles
    assert p.snapshot()["counters"]["pulls"] == 1


def test_read_asks_the_feed_for_a_longer_window_when_the_cache_is_short():
    calls = []

    def feed(symbol, timeframe, count):
        calls.append(count)
        return series(count)

    p = MarketPlane(min_pull_interval=0.0)
    p.register_feed("mt5", feed)
    p.read("XAUUSD", "M15", count=2)
    p.read("XAUUSD", "M15", count=7)
    assert calls == [2, 7]


def test_a_stale_window_is_not_re_pulled_on_every_read():
    """The shared-read promise: a feed that stopped moving is throttled, not
    hammered once per consumer per cycle."""
    calls = []

    def feed(symbol, timeframe, count):
        calls.append(count)
        return series(2, start=BASE)          # permanently old bars

    p = MarketPlane(min_pull_interval=30.0)
    p.register_feed("mt5", feed)
    for _ in range(5):
        p.read("XAUUSD", "M15", count=2)
    assert len(calls) == 1
    assert p.window("XAUUSD", "M15").freshness() == "stale"


def test_a_throttled_pull_still_serves_the_cached_window():
    def feed(symbol, timeframe, count):
        return series(2, start=BASE)

    p = MarketPlane(min_pull_interval=30.0)
    p.register_feed("mt5", feed)
    first = p.read("XAUUSD", "M15", count=2)
    second = p.read("XAUUSD", "M15", count=2)
    assert second.candles == first.candles and len(second.candles) == 2


def test_a_failing_feed_is_throttled_too():
    calls = []

    def dead(symbol, timeframe, count):
        calls.append(1)
        raise RuntimeError("terminal disconnected")

    p = MarketPlane(min_pull_interval=30.0)
    p.register_feed("mt5", dead)
    for _ in range(5):
        assert p.read("XAUUSD", "M15", count=5).candles == []
    assert len(calls) == 1
    # the failure is visible on a real window instead of a silent gap
    win = p.window("XAUUSD", "M15")
    assert win is not None and not win.bars
    assert "terminal disconnected" in win.errors[-1]
    assert p.snapshot()["summary"]["live"] is False


def test_feed_errors_are_recorded_bounded_on_the_window():
    calls = {"n": 0}

    def flaky(symbol, timeframe, count):
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            raise RuntimeError("timeout")
        return series(2, start=BASE)

    p = MarketPlane(max_errors=1, min_pull_interval=0.0)
    p.register_feed("mt5", flaky)
    p.read("XAUUSD", "M15", count=2)
    win = p._windows.get(("XAUUSD", "M15"))
    assert win is not None and len(win.errors) == 1
    p.read("XAUUSD", "M15", count=2)          # succeeds
    p.read("XAUUSD", "M15", count=2)          # fails again
    assert len(win.errors) == 1  # bounded, not an unbounded log


def test_read_prefers_the_feed_that_owns_the_window():
    def mt5(symbol, timeframe, count):
        return series(3, close=100.0)

    def cex(symbol, timeframe, count):
        return series(3, close=900.0)

    p = MarketPlane()
    p.register_feed("mt5", mt5)
    p.register_feed("cex", cex)
    p.read("BTCUSDT", "H1", count=3)          # highest priority feed wins
    assert p.window("BTCUSDT", "H1").source == "mt5"
    p.reset("BTCUSDT")
    p.publish_candles("BTCUSDT", "H1", series(2, close=1.0), source="cex")
    p.read("BTCUSDT", "H1", count=3)
    assert p.window("BTCUSDT", "H1").source == "cex"


def test_a_rank_tie_resolves_deterministically_not_by_dict_order():
    def feed_for(name):
        return lambda s, t, c: series(2, close=1.0 if name == "alpha" else 2.0)

    p = MarketPlane(min_pull_interval=0.0)
    p.register_feed("alpha", feed_for("alpha"))
    p.register_feed("omega", feed_for("omega"))
    for _ in range(3):
        p.reset()
        r = p.read("XAUUSD", "M15", count=2)
        assert r.source == "omega", "same rank must resolve the same way every time"


def test_allow_pull_false_never_calls_a_feed():
    calls = []
    p = MarketPlane()
    p.register_feed("mt5", lambda s, t, c: calls.append(1) or series(2))
    assert p.read("XAUUSD", "M15", allow_pull=False).candles == []
    assert calls == []


def test_no_registered_feed_means_read_returns_the_cached_window_only():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(3), source="mt5")
    r = p.read("XAUUSD", "M15", count=5)
    assert len(r.candles) == 3


def test_refresh_forces_a_pull_and_names_one_feed():
    calls = []

    def feed(symbol, timeframe, count):
        calls.append(count)
        return series(2, start=BASE, close=float(len(calls)))

    p = MarketPlane(min_pull_interval=30.0)
    p.register_feed("mt5", feed)
    win = p.refresh("XAUUSD", "M15", count=2)
    assert win is not None and win.bars[-1].close == 2.0
    # refresh bypasses the read throttle: it is an explicit operator action
    p.refresh("XAUUSD", "M15", count=4, source="mt5")
    assert calls == [2, 4]


def test_refresh_rejects_an_unregistered_feed():
    p = MarketPlane()
    assert p.refresh("XAUUSD", "M15", source="nope") is None


# -- bridge frame ingest ---------------------------------------------------

def test_ingest_bridge_frame_publishes_quote_and_bars_in_one_read():
    p = MarketPlane()
    now = live()
    got = p.ingest_bridge_frame({
        "symbol": "btc-usdt", "timeframe": "1h", "time": now,
        "quote": {"bid": 99.0, "ask": 101.0, "last_price": 100.0,
                  "time": now, "spread": 2.0},
        "bars": [{"time": now - 3600, "open": 1, "high": 2, "low": 0.5,
                  "close": 1.5, "volume": 3.0}],
    }, source="bridge:session-1")
    assert got["symbol"] == "BTCUSDT" and got["timeframe"] == "H1"
    assert got.get("quote") is True and got["bars"] == 1
    r = p.read("BTCUSDT", "H1", allow_pull=False)
    assert r.quote is not None and r.quote.bid == 99.0
    assert r.quote_source == "bridge:session-1"
    assert r.candles[-1].close == 1.5
    assert r.freshness == "fresh"


def test_ingest_bridge_frame_computes_spread_from_bid_ask_when_absent():
    p = MarketPlane()
    p.ingest_bridge_frame({"symbol": "XAUUSD", "timeframe": "M1",
                           "quote": {"bid": 10.0, "ask": 10.5, "time": BASE}},
                          source="bridge")
    assert p.quote("XAUUSD").spread == pytest.approx(0.5)


def test_ingest_bridge_frame_rejects_an_empty_frame():
    p = MarketPlane()
    got = p.ingest_bridge_frame({"symbol": "XAUUSD", "timeframe": "M1"},
                                source="bridge")
    assert "rejected" in got
    assert p.window("XAUUSD", "M1") is None


def test_ingest_bridge_frame_rejects_junk_bars_but_keeps_a_real_quote():
    p = MarketPlane()
    got = p.ingest_bridge_frame({
        "symbol": "XAUUSD", "timeframe": "M1", "time": BASE,
        "quote": {"bid": 10.0, "ask": 10.5, "time": BASE},
        "bars": [{"time": BASE, "close": 1.0}]},   # no o/h/l -> not usable
    source="bridge")
    assert got.get("quote") is True and got.get("bars", 0) == 0
    assert p.quote("XAUUSD").bid == 10.0
    assert p.window("XAUUSD", "M1") is None


def test_ingest_bridge_frame_is_rejected_by_priority_not_applied():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(3), source="mt5")
    got = p.ingest_bridge_frame({
        "symbol": "XAUUSD", "timeframe": "M15", "time": BASE + 9000,
        "bars": [{"time": BASE + 9000, "open": 1, "high": 2, "low": 1,
                  "close": 1.5}]}, source="bridge")
    assert got.get("bars", 0) == 0
    assert len(p.candles("XAUUSD", "M15")) == 3


def test_bridge_frame_marks_a_derived_quote():
    p = MarketPlane()
    p.ingest_bridge_frame({"symbol": "XAUUSD", "timeframe": "M1", "time": BASE,
                           "derived": True,
                           "quote": {"bid": 1.0, "ask": 1.0, "time": BASE}},
                          source="bridge")
    assert p.quote_read("XAUUSD").derived_quote is True


def test_bridge_frame_without_a_symbol_is_rejected_not_defaulted():
    """The one field we must never fill in: a frame's symbol."""
    p = MarketPlane()
    got = p.ingest_bridge_frame({"timeframe": "M1",
                                 "quote": {"bid": 1.0, "ask": 1.1,
                                           "time": BASE}}, source="bridge")
    assert "no symbol" in got["rejected"]
    assert p.quote("XAUUSD") is None      # not defaulted into XAUUSD


def test_bridge_frame_with_an_unknown_timeframe_is_rejected():
    p = MarketPlane()
    got = p.ingest_bridge_frame({"symbol": "XAUUSD", "timeframe": "5min",
                                 "quote": {"bid": 1.0, "ask": 1.1, "time": BASE}},
                                source="bridge")
    assert "timeframe" in got["rejected"]
    assert p.window("XAUUSD", "M1") is None


def test_one_sided_bridge_quote_is_rejected():
    p = MarketPlane()
    got = p.ingest_bridge_frame({"symbol": "XAUUSD", "timeframe": "M1",
                                 "quote": {"bid": 1.0, "time": BASE}},
                                source="bridge")
    assert "bid and ask" in got["rejected"]
    assert p.quote("XAUUSD") is None


def test_bridge_quote_without_a_tick_time_is_rejected():
    p = MarketPlane()
    got = p.ingest_bridge_frame({"symbol": "XAUUSD", "timeframe": "M1",
                                 "quote": {"bid": 1.0, "ask": 1.1}}, source="bridge")
    assert "tick time" in got["rejected"]
    assert p.quote("XAUUSD") is None


def test_junk_bridge_bars_without_a_quote_are_rejected_outright():
    p = MarketPlane()
    got = p.ingest_bridge_frame({"symbol": "XAUUSD", "timeframe": "M1",
                                 "bars": [{"time": BASE, "open": 1, "high": 2,
                                           "low": 1, "close": "abc"}]},
                                source="bridge")
    assert "unusable bars" in got["rejected"]
    assert p.window("XAUUSD", "M1") is None


def test_is_known_timeframe_separates_real_from_defaulted():
    assert is_known_timeframe("M15") and is_known_timeframe("15m")
    assert is_known_timeframe("TIMEFRAME_H4")
    assert not is_known_timeframe("5min") and not is_known_timeframe("")
    assert not is_known_timeframe(None)
    # the normalizer still defaults, so callers always get a usable name
    assert canonical_timeframe("5min") == "M15"


def test_last_bar_snapshot_refuses_a_one_sided_quote():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(2, start=BASE), source="mt5")
    p.publish_quote(MarketState(symbol="XAUUSD", bid=10.0, ask=0.0,
                                last_price=10.0, last_tick_time=BASE),
                    source="mt5")
    assert p.read("XAUUSD", "M15", allow_pull=False).last_bar_snapshot() is None
    state.market.pop("XAUUSD", None)


# -- snapshot / health -----------------------------------------------------

def test_snapshot_reports_real_feed_truth():
    p = MarketPlane()
    p.register_feed("mt5", lambda s, t, c: series(1))
    p.publish_quote(quote(tick=live(), last=2000.0), source="mt5")
    p.publish_candles("XAUUSD", "M15", series(3, start=live() - 2700),
                      source="mt5")
    snap = p.snapshot()
    assert snap["feeds"] == ["mt5"]
    assert snap["symbols"] == ["XAUUSD"]
    assert snap["summary"]["quotes_fresh"] == 1
    assert snap["summary"]["windows_fresh"] == 1
    assert snap["summary"]["live"] is True
    assert snap["quotes"]["XAUUSD"]["source"] == "mt5"
    assert snap["windows"][0]["freshness"] == "fresh"
    assert snap["windows"][0]["source"] == "mt5"
    assert snap["counters"]["publishes"] >= 2


def test_snapshot_of_an_idle_plane_is_honestly_not_live():
    p = MarketPlane()
    snap = p.snapshot()
    assert snap["summary"]["live"] is False
    assert snap["summary"]["quotes_total"] == 0
    assert snap["windows"] == []


def test_snapshot_marks_a_stale_quote_and_window():
    p = MarketPlane(stale_quote_seconds=60.0)
    p.publish_quote(quote(tick=BASE), source="mt5")
    p.publish_candles("XAUUSD", "M15", series(1, start=BASE), source="mt5")
    p._quotes["XAUUSD"].last_tick_time = BASE - 10_000
    for w in p._windows.values():
        w.bars[-1].time = BASE - 10_000
    snap = p.snapshot()
    assert snap["quotes"]["XAUUSD"]["freshness"] == "stale"
    assert snap["summary"]["live"] is False


# -- isolation + reset -----------------------------------------------------

def test_a_second_plane_is_isolated_from_the_singleton():
    from core.market_plane import market_plane

    mine = MarketPlane()
    mine.publish_candles("XAUUSD", "M15", series(2, close=1.0), source="backtest")
    assert mine.window("XAUUSD", "M15") is not None
    assert market_plane.window("XAUUSD", "M15") is None


def test_reset_drops_one_window_one_symbol_or_everything():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(1), source="mt5")
    p.publish_candles("XAUUSD", "H1", series(1), source="mt5")
    p.publish_candles("BTCUSDT", "M15", series(1), source="mt5")
    assert p.reset("XAUUSD", "M15") == 1
    assert p.window("XAUUSD", "H1") is not None
    assert p.reset("XAUUSD") == 1
    assert p.reset() == 1
    assert p.window("BTCUSDT", "M15") is None


def test_reset_also_drops_quotes():
    """A reset that kept quotes would leave a phantom live symbol behind."""
    p = MarketPlane()
    p.publish_quote(quote("XAUUSD"), source="mt5")
    p.publish_candles("XAUUSD", "M15", series(1), source="mt5")
    assert p.reset("XAUUSD") == 2
    assert p.quote("XAUUSD") is None
    assert p.window("XAUUSD", "M15") is None
    p.publish_quote(quote("BTCUSDT"), source="cex")
    p.reset()
    assert p.quote("BTCUSDT") is None
    assert p.snapshot()["summary"]["quotes_total"] == 0
    assert p.snapshot()["summary"]["live"] is False


def test_reset_counters_zeroes_statistics_only():
    p = MarketPlane()
    p.publish_candles("XAUUSD", "M15", series(2), source="mt5")
    p.read("XAUUSD", "M15", allow_pull=False)
    assert p.snapshot()["counters"]["publishes"] == 1
    p.reset_counters()
    assert p.snapshot()["counters"]["publishes"] == 0
    assert p.snapshot()["counters"]["reads"] == 0
    assert p.window("XAUUSD", "M15") is not None, "data is untouched"


def test_publish_is_thread_safe_under_concurrent_producers():
    import threading

    p = MarketPlane(max_bars=5000)

    def producer(name: str):
        for i in range(200):
            p.append_bars(f"SYM{name}", "M1", [bar(BASE + i * 60, float(i))],
                          source="bridge")

    def consumer():
        for _ in range(200):
            p.read("SYMA", "M1", count=10, allow_pull=False)
            p.snapshot()

    threads = [threading.Thread(target=producer, args=(n,)) for n in "ABC"]
    threads += [threading.Thread(target=consumer) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(p.candles("SYMA", "M1")) == 200
    assert p.snapshot()["counters"]["appends"] == 600
