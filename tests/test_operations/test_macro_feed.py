"""Tests for runtime macro context wiring."""


from operations.macro_feed import MacroContextUpdater
from schools.macro import EconomicEvent, macro_school


def test_macro_updater_refreshes_context_from_env(monkeypatch):
    monkeypatch.setenv("TRADERAIG_MACRO_RISK_MODE", "risk_off")
    monkeypatch.setenv("TRADERAIG_DXY_TREND", "up")
    monkeypatch.setenv("TRADERAIG_RATES_UP", "1")

    updater = MacroContextUpdater(refresh_seconds=0.0)
    snap = updater.refresh(now=1000.0, force=True)

    assert snap.risk_off is True
    assert snap.risk_on is False
    assert snap.dxy_trend == "up"
    assert snap.rates_up is True
    assert macro_school._context.risk_off is True


def test_macro_updater_preserves_calendar_and_reports_status():
    updater = MacroContextUpdater(refresh_seconds=0.0)
    updater.set_calendar([EconomicEvent("CPI", start=1000, end=1200, impact="high")])
    updater.refresh(now=1100.0, force=True)
    status = updater.status(now=1150.0)

    assert status["configured"] is True
    assert status["event_count"] == 1
    assert status["stale_seconds"] == 50.0
