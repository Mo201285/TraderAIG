"""Tests for LiveEngine macro refresh integration."""

from types import SimpleNamespace

from operations.live_engine import LiveEngine


class _FakeAdapter:
    connected = True

    def connect(self):
        return True

    def sync_account(self):
        return None

    def sync_positions(self):
        return []

    def sync_history(self):
        return []

    def sync_market(self, sym):
        return None

    def fetch_candles(self, sym, timeframe, count=300):
        return []

    def status(self):
        return {"available": True, "connected": True}

    def disconnect(self):
        return None


def test_live_engine_refreshes_macro_each_cycle(monkeypatch):
    seen = []

    def fake_refresh(force=False):
        seen.append(force)
        return SimpleNamespace(updated_at=1000.0)

    monkeypatch.setattr("operations.live_engine.macro_updater.refresh", fake_refresh)
    monkeypatch.setattr("operations.live_engine.macro_updater.status", lambda: {"configured": True})

    engine = LiveEngine(adapter=_FakeAdapter(), paper=False)
    engine.cycle()
    assert seen
    assert engine.status()["macro"]["configured"] is True
