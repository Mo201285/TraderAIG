"""Experimental soak gate: --soak must not run anywhere unless the
operator explicitly opts in via QT_EXPERIMENTAL_SOAK=1 (maturing feature)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from core.contracts import Candle
from operations import backtest as bt


def _candles(n: int) -> list:
    out = []
    price = 2000.0
    for i in range(n):
        d = 0.1 * (i % 5 - 2)
        o, c = price, price + d
        out.append(Candle(symbol="XAUUSD", timeframe="M15", time=float(i),
                          open=o, high=max(o, c) + 0.5, low=min(o, c) - 0.5,
                          close=c, volume=100.0, tick_volume=10.0))
        price = c
    return out


def test_soak_disabled_by_default(monkeypatch):
    monkeypatch.delenv("QT_EXPERIMENTAL_SOAK", raising=False)
    assert bt.soak_enabled() is False
    with pytest.raises(RuntimeError):
        bt.Backtester(symbol="XAUUSD", timeframe="M15", warmup=4)._soak(
            _candles(40))


def test_soak_honours_flag(monkeypatch):
    monkeypatch.setenv("QT_EXPERIMENTAL_SOAK", "1")
    assert bt.soak_enabled() is True
    bt.reset_runtime_state()
    from schools import quant
    candles = _candles(120)
    report = bt.Backtester(symbol="XAUUSD", timeframe="M15",
                           warmup=4).run(candles, soak=60, bars=70)
    assert len(quant.quant_governor._patterns) > 0  # gate armed by the soak
    assert report.bars == 70                       # reported window stays clean
    assert bt.soak_enabled()


def test_soak_flag_off_means_flag_off(monkeypatch):
    monkeypatch.setenv("QT_EXPERIMENTAL_SOAK", "0")
    assert bt.soak_enabled() is False
