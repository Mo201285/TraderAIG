"""Phase B tests: Feature Store (reproducible features) + Event Store (archive).

Two related 28.15 gaps, pinned down honestly:
  * Feature Store -- a lab run records a *manifest* (spec + provenance + row
    content hash) so the run is reproducible, and a re-extraction can prove it.
  * Event Store -- the ephemeral `ops/events` ring is archived into the durable
    log and replayed back, without touching a single publisher.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

import operations.api as api
from operations import event_archive as archive_mod
from operations.event_archive import EventArchive
from operations.event_feed import EventFeed
from research.strategy_lab.feature_store import (
    FeatureStore,
    feature_fingerprint,
)
from persistence.db import bind_test_session
from persistence.repositories import EventLogRepository


# ---------------------------------------------------------------------------
# Feature Store
# ---------------------------------------------------------------------------

class _Row:
    def __init__(self, t, **kw):
        self.time = t
        self.__dict__.update(kw)

    def as_dict(self):
        return dict(vars(self))


def _rows(n=5):
    return [_Row(float(i), close=1.0 + i, regime="bullish/normal",
                 matrix_best_family="ob_mitigation", matrix_best_score=0.5)
            for i in range(n)]


def test_fingerprint_stable_and_order_sensitive():
    a = _rows(5)
    b = _rows(5)
    assert feature_fingerprint(a) == feature_fingerprint(b)
    assert feature_fingerprint(a) != feature_fingerprint(_rows(4))
    c = list(reversed(a))
    assert feature_fingerprint(a) != feature_fingerprint(c)


def test_fingerprint_empty_series_is_a_real_digest():
    assert isinstance(feature_fingerprint([]), str)
    assert len(feature_fingerprint([])) == 64


def test_store_records_manifest_and_roundtrips(tmp_path):
    path = tmp_path / "feature_store.json"
    store = FeatureStore(str(path))
    manifest = store.record(
        "xauusd:ob_mitigation:v0", rows=_rows(7),
        provenance={"source": "mt5", "bars": 2000, "first_bar": 1.0,
                    "last_bar": 2000.0},
        family="ob_mitigation", asset="xauusd",
        timeframes={"htf": "H1", "setup": "M15", "trigger": "M1"})
    assert manifest["row_count"] == 7
    assert manifest["asset"] == "XAUUSD"
    assert manifest["provenance"]["bars"] == 2000
    assert manifest["feature_specification"]["resolved"] is True
    assert len(manifest["sample_rows"]) == 5

    reloaded = FeatureStore(str(path))
    assert reloaded.get("xauusd:ob_mitigation:v0")["row_count"] == 7


def test_store_never_invents_provenance(tmp_path):
    store = FeatureStore(str(tmp_path / "s.json"))
    manifest = store.record("s:v0", rows=_rows(3))
    assert manifest["provenance"] is None
    assert manifest["feature_specification"]["resolved"] is False


def test_verify_proves_reproducibility(tmp_path):
    store = FeatureStore(str(tmp_path / "s.json"))
    rows = _rows(7)
    store.record("s:v0", rows=rows)
    same = store.verify("s:v0", _rows(7))
    assert same["reproduced"] is True and same["expected"] == same["actual"]
    drift = store.verify("s:v0", _rows(6))
    assert drift["reproduced"] is False
    assert store.verify("ghost", rows) is None


def test_feature_store_route(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    store = FeatureStore(str(tmp_path / "feature_store.json"))
    store.record("xauusd:ob_mitigation:v0", rows=_rows(4), asset="xauusd")
    out = api.features_store()
    assert out["ok"] is True and out["count"] == 1
    one = api.features_store(strategy_id="xauusd:ob_mitigation:v0")
    assert one["found"] is True and one["manifest"]["row_count"] == 4
    assert api.features_store(strategy_id="ghost")["found"] is False


def test_feature_store_route_registered():
    paths = {r.path for r in api.app.routes}
    assert "/features/store" in paths


# ---------------------------------------------------------------------------
# Event Store
# ---------------------------------------------------------------------------

@pytest.fixture()
def session():
    s = bind_test_session()
    yield s
    s.close()


def test_archive_event_idempotent_by_feed_id(session):
    event = {"id": 42, "at": 1000.0, "kind": "transition",
             "topic": "registry", "actor": "review_loop",
             "payload": {"strategy_id": "s:v0"}}
    first = archive_mod.archive_event(event, session=session)
    second = archive_mod.archive_event(event, session=session)
    assert first == second == "feed-42-transition"
    got = EventLogRepository(session).get(first)
    assert got is not None
    assert got["source"] == "event_feed"
    assert got["event_type"] == "ops.transition"


def test_feed_subscribe_notifies_handlers():
    feed = EventFeed()
    seen = []
    feed.subscribe(lambda e: seen.append(e["id"]))
    feed.publish("transition", "registry", payload={})
    feed.publish("veto", "risk", payload={})
    assert seen == [1, 2]


def test_feed_subscriber_error_never_breaks_publish():
    feed = EventFeed()

    def boom(_e):
        raise RuntimeError("bad consumer")

    feed.subscribe(boom)
    event = feed.publish("transition", "registry", payload={})
    assert event["id"] == 1 and feed.latest == 1


def test_archive_attach_opt_in(monkeypatch, session):
    monkeypatch.delenv(archive_mod.ENV_FLAG, raising=False)
    feed = EventFeed()
    box = EventArchive(feed)
    assert box.attach() is False
    # enabled: attaches and archives subsequent publishes
    monkeypatch.setenv(archive_mod.ENV_FLAG, "1")
    monkeypatch.setattr(archive_mod, "archive_event",
                        lambda e, **k: archive_mod._envelope_from_feed(e)["event_id"])
    assert box.attach() is True
    feed.publish("transition", "registry", actor="review_loop", payload={})
    assert box._archived == 1


def test_archive_replay_returns_feed_shape(session, monkeypatch):
    events = [
        {"id": 1, "at": 1000.0, "kind": "transition", "topic": "registry",
         "actor": "review_loop", "payload": {"strategy_id": "a"}},
        {"id": 2, "at": 1001.0, "kind": "quarantine", "topic": "registry",
         "actor": "autonomous_ops", "payload": {"strategy_id": "b"}},
    ]
    for e in events:
        archive_mod.archive_event(e, session=session)
    box = EventArchive()
    monkeypatch.setattr("persistence.repositories.EventLogRepository",
                        lambda *a, **k: EventLogRepository(session))
    out = box.replay(limit=10)
    ids = {e["id"] for e in out["events"]}
    assert {"1", "2"} <= ids
    by_id = {e["id"]: e for e in out["events"]}
    assert by_id["1"]["kind"] == "transition"
    assert by_id["1"]["topic"] == "registry"
    assert "archive" in out["note"]
    # narrow to one kind: every returned row is that kind
    only = box.replay(limit=10, event_type="transition")
    assert only["count"] >= 1
    assert all(e["kind"] == "transition" for e in only["events"])


def test_replay_route_registered_and_reads(monkeypatch, session):
    monkeypatch.setattr("persistence.repositories.EventLogRepository",
                        lambda *a, **k: EventLogRepository(session))
    archive_mod.archive_event(
        {"id": 7, "at": 2000.0, "kind": "transition", "topic": "registry",
         "actor": "review_loop", "payload": {}}, session=session)
    r = api.events_replay(limit=10)
    assert r["ok"] is True
    assert any(e["id"] == "7" for e in r["events"])


def test_event_routes_registered():
    paths = {r.path for r in api.app.routes}
    assert "/events/replay" in paths
