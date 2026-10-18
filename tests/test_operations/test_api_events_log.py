"""Durable event-log reader endpoint tests (GET /events/log)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import operations.api as api


class _FakeRepo:
    calls: dict = {}
    rows: list = []

    def __init__(self, *args, **kwargs):  # noqa: D401 - mirror the real ctor
        pass

    def list(self, limit=200, *, event_type=None, account_id=None):
        _FakeRepo.calls["list"] = (limit, event_type)
        return list(_FakeRepo.rows)

    def by_correlation(self, correlation_id, limit=500):
        _FakeRepo.calls["corr"] = (correlation_id, limit)
        return [dict(r, correlation_id=correlation_id) for r in _FakeRepo.rows]


def _wire(monkeypatch, rows, enabled=True):
    _FakeRepo.calls = {}
    _FakeRepo.rows = rows
    monkeypatch.setattr("persistence.repositories.EventLogRepository", _FakeRepo)
    monkeypatch.setattr("persistence.events.enabled_by_env", lambda: enabled)


def test_events_log_lists_with_type_filter(monkeypatch):
    _wire(monkeypatch, [{"event_id": "a", "event_type": "risk.veto"},
                        {"event_id": "b", "event_type": "risk.veto"}])
    body = api.events_log(limit=50, event_type="risk.veto")
    assert body["ok"] is True
    assert body["enabled"] is True
    assert body["count"] == 2
    assert [e["event_id"] for e in body["events"]] == ["a", "b"]
    assert _FakeRepo.calls["list"] == (50, "risk.veto")


def test_events_log_by_correlation(monkeypatch):
    _wire(monkeypatch, [{"event_id": "a", "event_type": "risk.veto"}])
    body = api.events_log(correlation_id="corr-1")
    assert body["count"] == 1
    assert _FakeRepo.calls["corr"][0] == "corr-1"
    assert body["events"][0]["correlation_id"] == "corr-1"


def test_events_log_clamps_limit(monkeypatch):
    _wire(monkeypatch, [])
    api.events_log(limit=99999)
    assert _FakeRepo.calls["list"][0] == 1000
    api.events_log(limit=0)
    assert _FakeRepo.calls["list"][0] == 1


def test_events_log_reports_disabled_honestly(monkeypatch):
    _wire(monkeypatch, [], enabled=False)
    body = api.events_log()
    assert body["ok"] is True
    assert body["enabled"] is False
    assert body["count"] == 0


def test_events_log_route_is_registered():
    paths = {r.path for r in api.app.routes}
    assert "/events/log" in paths
