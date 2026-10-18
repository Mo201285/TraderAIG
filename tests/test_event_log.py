"""Tests for the unified event log envelope, repository and writer."""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.events import Event, EventType  # noqa: E402
from persistence import events as events_mod  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_events import EVENT_SCHEMA_VERSION  # noqa: E402
from persistence.repositories import EventLogRepository  # noqa: E402


@pytest.fixture
def session():
    s = bind_test_session()
    yield s
    s.close()


def _etype() -> str:
    return f"test.{uuid.uuid4().hex}"


def test_build_event_sets_envelope_defaults():
    env = events_mod.build_event("risk.veto", payload={"why": "cap"})
    assert env["schema_version"] == EVENT_SCHEMA_VERSION
    assert env["event_type"] == "risk.veto"
    assert env["retention_class"] == "operational"
    assert env["event_id"]
    assert env["occurred_at"] > 0
    assert env["recorded_at"] >= env["occurred_at"]
    assert env["content_hash"]


def test_build_event_rejects_unknown_retention_class():
    with pytest.raises(ValueError):
        events_mod.build_event("x", retention_class="forever")


def test_content_hash_is_order_independent():
    assert events_mod.content_hash({"a": 1, "b": 2}) == events_mod.content_hash(
        {"b": 2, "a": 1})
    assert events_mod.content_hash({"a": 1}) != events_mod.content_hash({"a": 2})


def test_append_and_read_roundtrip(session):
    etype = _etype()
    eid = uuid.uuid4().hex
    env = events_mod.build_event(
        etype, payload={"n": 1}, account_id="acct-1", actor="risk",
        retention_class="long", correlation_id="corr-1", event_id=eid)
    repo = EventLogRepository(session)
    assert repo.append(env) == eid

    got = repo.get(eid)
    assert got is not None
    assert got["event_type"] == etype
    assert got["payload"] == {"n": 1}
    assert got["account_id"] == "acct-1"
    assert got["retention_class"] == "long"
    assert got["schema_version"] == EVENT_SCHEMA_VERSION

    listed = repo.list(event_type=etype)
    assert [e["event_id"] for e in listed] == [eid]
    assert repo.count(event_type=etype) == 1
    assert repo.by_correlation("corr-1")[0]["event_id"] == eid


def test_append_is_idempotent_by_event_id(session):
    etype = _etype()
    eid = uuid.uuid4().hex
    repo = EventLogRepository(session)
    repo.append(events_mod.build_event(etype, event_id=eid))
    repo.append(events_mod.build_event(etype, event_id=eid))
    assert repo.count(event_type=etype) == 1


def test_append_requires_event_id(session):
    with pytest.raises(ValueError):
        EventLogRepository(session).append({"event_type": "x"})


def test_emit_persists_via_injected_session(session):
    etype = _etype()
    env = events_mod.emit(etype, payload={"ok": True}, session=session)
    assert env is not None
    assert EventLogRepository(session).count(event_type=etype) == 1


def test_emit_degrades_to_none_on_store_failure(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr("persistence.repositories.EventLogRepository", boom)
    assert events_mod.emit("x.y", payload={}) is None


def test_record_event_maps_the_bus_event(session):
    event = Event(type=EventType.ORDER_FILLED, payload={"qty": 2},
                  source="execution", correlation_id="corr-9")
    env = events_mod.record_event(event, session=session)
    assert env is not None
    assert env["event_type"] == EventType.ORDER_FILLED.value
    assert env["payload"] == {"qty": 2}
    assert env["source"] == "execution"
    assert env["correlation_id"] == "corr-9"
    assert env["event_id"] == event.event_id
    assert EventLogRepository(session).get(event.event_id) is not None


def test_attach_subscribes_to_the_bus():
    captured = {}

    class _Bus:
        def subscribe_all(self, handler):
            captured["handler"] = handler

    events_mod.attach(_Bus())
    assert captured["handler"] is events_mod.record_event


def test_enabled_by_env_defaults_off(monkeypatch):
    monkeypatch.delenv("TRADERAIG_EVENT_LOG", raising=False)
    assert events_mod.enabled_by_env() is False
    monkeypatch.setenv("TRADERAIG_EVENT_LOG", "")
    assert events_mod.enabled_by_env() is False
    monkeypatch.setenv("TRADERAIG_EVENT_LOG", "0")
    assert events_mod.enabled_by_env() is False
    monkeypatch.setenv("TRADERAIG_EVENT_LOG", "no")
    assert events_mod.enabled_by_env() is False


def test_enabled_by_env_truthy_values(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on", " On "):
        monkeypatch.setenv("TRADERAIG_EVENT_LOG", value)
        assert events_mod.enabled_by_env() is True, value
