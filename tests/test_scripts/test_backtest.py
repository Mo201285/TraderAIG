"""Smoke tests for the backtest CLI script."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

from core.contracts import Candle  # noqa: E402


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "backtest_cli", ROOT / "scripts" / "backtest.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backtest_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(args, tmp_path):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backtest.py"), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120)


def test_cli_help_prints_options(tmp_path):
    r = _run(["--help"], tmp_path)
    assert r.returncode == 0
    assert "--timeframe" in r.stdout
    assert "--warmup" in r.stdout


def test_cli_replays_csv(tmp_path):
    rows = []
    price = 100.0
    for i in range(30):
        rows.append(f"{i},{price},{price + 5},{price - 5},{price + 2},100")
        price += 2
    for i in range(30):  # flat-to-down leg gives a structure change
        rows.append(f"{30 + i},{price},{price + 5},{price - 8},{price - 3},100")
        price -= 3

    csv_path = tmp_path / "candles.csv"
    csv_path.write_text("\n".join(["timestamp,open,high,low,close,volume", *rows]),
                        encoding="utf-8")

    r = _run([str(csv_path), "--symbol", "XAUUSD", "--timeframe", "M15",
              "--warmup", "5"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Backtest XAUUSD M15 over 60 bars" in r.stdout
    assert "Trades:" in r.stdout
    assert "Equity:" in r.stdout


class _FakeMT5Adapter:
    def __init__(self, candles):
        self._candles = candles
        self._last_error = ""

    def connect(self):
        return True

    def fetch_candles(self, symbol, timeframe, count=300):
        return self._candles[:count]


def _fake_candle(t):
    return Candle(symbol="XAUUSD", timeframe="M15", time=t, open=100.0,
                  high=102.0, low=98.0, close=101.0, volume=10.0,
                  tick_volume=10.0)


def test_script_mt5_source_loads_real_candles(monkeypatch):
    sbt = _load_script()
    fake = _FakeMT5Adapter([_fake_candle(float(i)) for i in range(50)])
    monkeypatch.setattr("execution.mt5_adapter.mt5_adapter", fake)

    candles = sbt.load_candles_source("mt5", None, "XAUUSD", "M15", 40)
    assert len(candles) == 40
    assert candles[0].symbol == "XAUUSD"
    assert candles[0].high == 102.0


def test_script_mt5_source_raises_when_empty(monkeypatch):
    sbt = _load_script()
    monkeypatch.setattr("execution.mt5_adapter.mt5_adapter",
                        _FakeMT5Adapter([]))
    with pytest.raises(RuntimeError):
        sbt.load_candles_source("mt5", None, "XAUUSD", "M15", 40)


def test_script_csv_roundtrip(tmp_path):
    sbt = _load_script()
    src_path = tmp_path / "src.csv"
    out_path = tmp_path / "cached.csv"
    rows = []
    for i in range(12):
        rows.append(f"{i},{100+i},{102+i},{99+i},{101+i},10")
    src_path.write_text("\n".join(["timestamp,open,high,low,close,volume",
                                   *rows]), encoding="utf-8")

    candles = sbt.load_candles_csv(src_path, "XAUUSD", "M15")
    sbt.write_candles_csv(candles, out_path)
    reloaded = sbt.load_candles_csv(out_path, "XAUUSD", "M15")
    assert [c.close for c in reloaded] == [c.close for c in candles]
    assert out_path.read_text(encoding="utf-8").startswith(
        "timestamp,open,high,low,close,volume,tick_volume")
