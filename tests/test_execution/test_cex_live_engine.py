"""Tests for CEX public klines mapping and the CEX live engine (no network)."""

from types import SimpleNamespace


from core.contracts import TradeDirection  # noqa: F401
from execution.cex import venues as venues_mod
from execution.cex.venues import (
    BinanceVenue,
    BybitVenue,
    OKXVenue,
    _TF_INTERVAL_BYBIT,
    _TF_INTERVAL_OKX,
)


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


# ---------------------------------------------------------------------------
# Public klines -> canonical Candle rows
# ---------------------------------------------------------------------------


def test_binance_fetch_candles_maps_klines(monkeypatch):
    _paper_settings(monkeypatch)
    venue = BinanceVenue(mode="paper")
    rows = [
        [1700000000000, "60000.0", "60100.0", "59900.0", "60050.0", "1.5",
         1700000059999, "90000.0", 3, 1, "0", "0"],
        [1700000060000, "60050.0", "60200.0", "60000.0", "60200.0", "2.0",
         1700000119999, "120000.0", 4, 2, "0", "0"],
    ]
    venue._request = lambda *a, **kw: rows
    candles = venue.fetch_candles("BTCUSDT", "M15", 2)
    assert len(candles) == 2
    assert candles[0].open == 60000.0
    assert candles[0].close == 60050.0
    assert candles[1].high == 60200.0
    assert candles[0].timeframe == "M15"
    assert candles[0].symbol == "BTCUSDT"


def test_binance_fetch_candles_error_returns_empty(monkeypatch):
    _paper_settings(monkeypatch)
    venue = BinanceVenue(mode="paper")
    venue._request = lambda *a, **kw: {"error": "rate limited"}
    assert venue.fetch_candles("BTCUSDT") == []


def test_okx_fetch_candles_reverses_newest_first(monkeypatch):
    _paper_settings(monkeypatch, venue="okx")
    venue = OKXVenue(mode="paper")
    # OKX returns newest first
    data = {"data": [
        ["1700000060000", "60200", "60300", "60100", "60250", "2", "0", "0"],
        ["1700000000000", "60000", "60100", "59900", "60050", "1", "0", "0"],
    ]}
    venue._request = lambda *a, **kw: data
    candles = venue.fetch_candles("BTC-USDT", "M15", 2)
    assert len(candles) == 2
    assert candles[0].time < candles[1].time  # oldest first after reverse
    assert candles[0].close == 60050.0
    assert candles[1].close == 60250.0


def test_okx_interval_map_uses_hour_token():
    assert _TF_INTERVAL_OKX["H1"] == "1H"
    assert _TF_INTERVAL_OKX["D1"] == "1D"


def test_bybit_fetch_candles_reverses_newest_first(monkeypatch):
    _paper_settings(monkeypatch, venue="bybit")
    venue = BybitVenue(mode="paper")
    data = {"result": {"list": [
        ["1700000060000", "60200", "60300", "60100", "60250", "2", "0"],
        ["1700000000000", "60000", "60100", "59900", "60050", "1", "0"],
    ]}}
    venue._request = lambda *a, **kw: data
    candles = venue.fetch_candles("BTCUSDT", "M15", 2)
    assert len(candles) == 2
    assert candles[0].time < candles[1].time
    assert candles[0].close == 60050.0
    assert _TF_INTERVAL_BYBIT["H1"] == "60"


# ---------------------------------------------------------------------------
# CexLiveEngine (paper watch mode, no network)
# ---------------------------------------------------------------------------


class _FakeFeed:
    def __init__(self):
        self.name = "binance"
        self.mode = "paper"
        self.calls = {"candles": 0}

    def health(self):
        return {"venue": self.name, "mode": self.mode, "locked": False,
                "live_armed": False, "testnet_armed": False}

    def fetch_candles(self, symbol, timeframe, count):
        self.calls["candles"] += 1
        from core.contracts import Candle
        return [Candle(symbol=symbol, timeframe=timeframe,
                       time=1700000000.0 + 900 * i,
                       open=60000.0 + i, high=60010.0 + i,
                       low=59990.0 + i, close=60005.0 + i,
                       volume=1.0, tick_volume=1.0) for i in range(count)]

    def fetch_balances(self):
        return {"ok": True, "balances": {"USD": {"free": 100000.0}}}

    def fetch_ticker(self, symbol):
        return {"ok": True, "bid": 60000.0, "ask": 60002.0, "last": 60001.0}


def test_cex_live_engine_paper_watch_cycle(monkeypatch):
    _paper_settings(monkeypatch)
    from operations.cex_engine import CexLiveEngine

    feed = _FakeFeed()
    engine = CexLiveEngine(symbols=["BTCUSDT"], paper=True)
    engine._venue = feed  # swap in fake feed, keep real paper desk loops
    assert engine.connect() is True
    cycles = engine.cycle()
    assert cycles == 1
    assert feed.calls["candles"] >= 1
    assert engine.status()["venue"] == "binance"
    assert engine.status()["paper"] is True
    assert "paper_stats" in engine.status()


def test_cex_live_engine_refuses_locked_live_loop(monkeypatch):
    _paper_settings(monkeypatch, mode="live")
    from execution.cex.venues import BinanceVenue as LockedBinance
    from operations.cex_engine import CexLiveEngine

    engine = CexLiveEngine(symbols=["BTCUSDT"], paper=False)
    # locked live venue (no keys) -> live loop refuses to run
    engine._venue = LockedBinance(mode="live")
    assert engine.venue_locked is True
    assert engine.cycle() == -1
    assert "venue_locked" in engine._errors
