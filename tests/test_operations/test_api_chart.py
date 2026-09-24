"""Chart context API endpoint tests (operations/api.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.contracts import Candle
from research.strategy_lab.contracts import (
    PromotionStage,
    StrategyFamily,
    ValidationReport,
)
from research.strategy_lab.registry import StrategyRegistry

import operations.api as api


def _synthetic(rows: int = 300, base: float = 2500.0) -> list[Candle]:
    return [
        Candle(symbol="XAUUSD", timeframe="M5", time=float(10_000_000 + i),
               open=base + i * 0.1, high=base + i * 0.1 + 1.0,
               low=base + i * 0.1 - 1.0, close=base + i * 0.1 + 0.3,
               volume=10.0, tick_volume=10.0)
        for i in range(rows)
    ]


def _fake_adapter(rows=300) -> SimpleNamespace:
    candles = _synthetic(rows)
    return SimpleNamespace(
        connected=True,
        fetch_candles=lambda s, tf, count: candles,
        status=lambda: {"connected": True, "attach_mode": "script",
                        "last_error": None},
    )


def test_chart_timeframes_lists_symbols_and_tfs(monkeypatch):
    monkeypatch.setattr(api, "mt5_adapter", _fake_adapter())
    body = api.chart_timeframes()
    assert "XAUUSD" in body["symbols"]
    assert "BTCUSD" in body["symbols"]
    assert {"M1", "M5", "M15", "H1", "D1"} <= set(body["timeframes"])


def test_chart_context_returns_candles_and_context(monkeypatch):
    monkeypatch.setattr(api, "mt5_adapter", _fake_adapter(300))
    body = api.chart_context(symbol="xauusd", timeframe="M5", bars=300)
    assert body["ok"] is True
    assert body["symbol"] == "XAUUSD"
    assert len(body["candles"]) == 300
    c0 = body["candles"][0]
    assert {"time", "date", "open", "high", "low", "close"} <= set(c0)
    ctx = body["context"]
    assert ctx["regime"].count("/") == 1
    assert isinstance(ctx["support_zones"], list)
    assert isinstance(ctx["resistance_zones"], list)
    assert ctx["context_score"] >= 0
    assert "market_story" in ctx
    assert body["mt5_status"]["connected"] is True


def test_chart_context_bars_clamped(monkeypatch):
    seen = {}
    fake = _fake_adapter(300)
    orig = fake.fetch_candles
    def capture(s, tf, count):
        seen["count"] = count
        return orig(s, tf, count)
    fake.fetch_candles = capture
    monkeypatch.setattr(api, "mt5_adapter", fake)
    api.chart_context(symbol="XAUUSD", timeframe="M5", bars=99999)
    assert seen["count"] == 5000
    api.chart_context(symbol="XAUUSD", timeframe="H1", bars=10)
    assert seen["count"] == 50


def test_chart_context_no_candles_reports_error(monkeypatch):
    fake = SimpleNamespace(
        connected=True,
        fetch_candles=lambda s, tf, count: [],
        status=lambda: {"connected": True, "attach_mode": "script",
                        "last_error": "copy_rates failed"},
    )
    monkeypatch.setattr(api, "mt5_adapter", fake)
    body = api.chart_context(symbol="XAUUSD", timeframe="M5", bars=300)
    assert body["ok"] is False
    assert body["error"] == "no_candles"
    assert body["candles"] == []
    assert body["context"] is None


def test_chart_context_rejects_unsupported_symbol(monkeypatch):
    monkeypatch.setattr(api, "mt5_adapter", _fake_adapter())
    with pytest.raises(HTTPException) as exc:
        api.chart_context(symbol="ETHUSD", timeframe="M5", bars=100)
    assert exc.value.status_code == 400


def test_chart_context_reconnects_if_disconnected(monkeypatch):
    calls = {"connect": 0}
    fake = SimpleNamespace(
        connected=False,
        _terminal_running=lambda: True,
        connect=lambda: calls.__setitem__("connect", calls["connect"] + 1),
        fetch_candles=lambda s, tf, count: _synthetic(200),
        status=lambda: {"connected": True, "attach_mode": "script",
                        "last_error": None},
    )
    monkeypatch.setattr(api, "mt5_adapter", fake)
    body = api.chart_context(symbol="XAUUSD", timeframe="M5", bars=200)
    assert body["ok"] is True
    assert calls["connect"] == 1


def _seed_registry(tmp_path) -> None:
    reg = StrategyRegistry(str(tmp_path / "registry.json"))
    rep = ValidationReport(strategy_id="xauusd:ob_mitigation:v3",
                           asset="XAUUSD", samples=300,
                           expected_value=0.05, passed=True)
    rep.regime_concentration = {"sideways/high": 0.03}
    reg.register("xauusd:ob_mitigation:v3", "h",
                 StrategyFamily.OB_MITIGATION, "XAUUSD",
                 initial=PromotionStage.VALIDATED, validation=rep)
    rep2 = ValidationReport(strategy_id="btcusd:ict_fvg_continuation:v0",
                            asset="BTCUSD", samples=100, passed=False)
    reg.register("btcusd:ict_fvg_continuation:v0", "h",
                 StrategyFamily.ICT_FVG_CONTINUATION, "BTCUSD",
                 initial=PromotionStage.RESEARCH, validation=rep2)


def test_chart_strategies_filters_by_symbol_and_extracts_regimes(monkeypatch,
                                                                 tmp_path):
    _seed_registry(tmp_path)
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    out = api.chart_strategies("XAUUSD")
    assert len(out) == 1
    row = out[0]
    assert row["strategy_id"] == "xauusd:ob_mitigation:v3"
    assert row["stage"] == "validated"
    assert row["by_regime"]["sideways/high"] == pytest.approx(0.03)
    assert row["trades"] == 300
    assert row["passed"] is True


def test_chart_strategies_empty_for_absent_symbol(monkeypatch, tmp_path):
    _seed_registry(tmp_path)
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    assert api.chart_strategies("ETHUSD") == []


def test_mt5_bounded_uses_connected_fetch_directly(monkeypatch):
    fake = SimpleNamespace(
        connected=True,
        fetch_candles=lambda s, tf, count: _synthetic(50),
    )
    monkeypatch.setattr(api, "mt5_adapter", fake)
    out = api._mt5_candles_bounded("XAUUSD", "M5", 50)
    assert len(out) == 50


def test_mt5_bounded_fails_fast_when_terminal_not_running(monkeypatch):
    calls = {"terminal": 0}
    fake = SimpleNamespace(
        connected=False,
        _terminal_running=lambda: calls.__setitem__("terminal", calls["terminal"] + 1),
    )
    monkeypatch.setattr(api, "mt5_adapter", fake)
    out = api._mt5_candles_bounded("XAUUSD", "M5", 300, timeout=1.0)
    assert out == []
    assert calls["terminal"] == 1
    assert "terminal64.exe not running" in fake._last_error


def test_mt5_bounded_reconnects_in_background_thread(monkeypatch):
    calls = {"connect": 0}
    fake = SimpleNamespace(
        connected=False,
        _terminal_running=lambda: True,
        connect=lambda: calls.__setitem__("connect", calls["connect"] + 1),
        fetch_candles=lambda s, tf, count: _synthetic(120),
    )
    monkeypatch.setattr(api, "mt5_adapter", fake)
    out = api._mt5_candles_bounded("XAUUSD", "M15", 120, timeout=5.0)
    assert len(out) == 120
    assert calls["connect"] >= 1
