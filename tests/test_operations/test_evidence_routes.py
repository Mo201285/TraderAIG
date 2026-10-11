"""The Evidence Plane routes over the real app (row 746, P1 slice).

The layer under test is the one the domain tests cannot see: routes that
resolve the acting principal, accept either a normalised payload or a
`{kind, raw}` bundle, map `ValueError` to `400` and an unreachable store to
`503`, and serialise the trust ladder. The route-specific failures guarded
here are:

- intake needs an acting principal (`409`);
- intake accepts a normalised payload (with `source_kind`) or `{kind, raw}` it
  normalises, and refuses a bare item with no de-duplication key (`400`);
- an unknown `source_kind` is `400`, never a half-written row;
- the same inbound item delivered twice stores once (``is_new=False`` on the
  second delivery) -- the idempotency n8n works against;
- classify/trust need the row (else `404`), trust is monotonic and bounded
  (downward/out-of-bounds `400`);
- reads carry `is_authorisation: False` and name the Risk Governor;
- an unreachable store is `503`, not an empty result;
- the tenancy report truthfully describes the evidence plane.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import EvidenceRecord  # noqa: E402

OPERATOR = "evidence-route-principal"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def evidence_db(monkeypatch):
    session = bind_test_session()
    session.execute(delete(EvidenceRecord))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture(autouse=True)
def _principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)


def _normalised_payload():
    return {
        "source_kind": "arxiv",
        "external_id": "2401.00010",
        "source_uri": "http://arxiv.org/abs/2401.00010",
        "topic": "q-fin.ST",
        "headline": "A route-level paper",
        "payload_hash": "f" * 64,
        "markets": ["BTC"],
    }


def test_intake_needs_a_principal(evidence_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    r = TestClient(app).post("/evidence/intake", json=_normalised_payload())
    assert r.status_code == 409
    assert r.json()["reason"] == "no_principal"


def test_intake_normalised_payload_stores_one_row(client):
    r = client.post("/evidence/intake", json=_normalised_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["is_new"] is True
    ev = body["evidence"]
    assert ev["source_kind"] == "arxiv"
    assert ev["trust_ladder"] == 1
    assert ev["trust_label"] == "external_evidence"
    assert ev["is_authorisation"] is False
    assert ev["trade_authority"] == "risk/governor.py"


def test_intake_accepts_kind_and_raw_and_normalises(client):
    r = client.post("/evidence/intake", json={
        "kind": "github",
        "raw": {"action": "published",
                "repository": {"full_name": "acme/signal",
                               "topics": ["btc"]},
                "release": {"name": "v3.0.0"}},
    })
    assert r.status_code == 200
    ev = r.json()["evidence"]
    assert ev["source_kind"] == "github"
    assert "v3.0.0" in ev["headline"]


def test_intake_unknown_kind_is_400(client):
    r = client.post("/evidence/intake", json={
        "kind": "youtube", "raw": {"id": "x"}})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_intake"


def test_intake_bare_item_without_dedup_key_is_400(client):
    r = client.post("/evidence/intake", json={
        "source_kind": "arxiv", "external_id": "2401.00011",
        "headline": "no key"})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_intake"


def test_intake_same_item_delivered_twice_stores_once(client):
    first = client.post("/evidence/intake", json=_normalised_payload())
    second = client.post("/evidence/intake", json=_normalised_payload())
    assert first.json()["evidence"]["evidence_id"] == \
        second.json()["evidence"]["evidence_id"]
    assert first.json()["is_new"] is True
    assert second.json()["is_new"] is False


def test_internal_idea_starts_at_level_zero(client):
    r = client.post("/evidence/intake", json={
        "source_kind": "internal", "external_id": "idea-1",
        "headline": "lab hypothesis", "payload_hash": "0" * 64})
    assert r.json()["evidence"]["trust_ladder"] == 0
    assert r.json()["evidence"]["trust_label"] == "ai_idea"


def test_classify_updates_supplied_fields_only(client):
    ev = client.post("/evidence/intake", json=_normalised_payload()).json()["evidence"]
    r = client.post(f"/evidence/{ev['evidence_id']}/classify",
                    json={"relevance": 0.55, "markets": ["BTC", "ETH"]})
    assert r.status_code == 200
    out = r.json()["evidence"]
    assert out["relevance"] == 0.55
    assert out["markets"] == ["BTC", "ETH"]
    assert out["confidence"] is None


def test_classify_unknown_evidence_is_404(client):
    r = client.post("/evidence/no-such/classify", json={"relevance": 0.1})
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_evidence"


def test_trust_advance_is_monotonic(client):
    ev = client.post("/evidence/intake", json=_normalised_payload()).json()["evidence"]
    r = client.post(f"/evidence/{ev['evidence_id']}/trust", json={"level": 7})
    assert r.status_code == 200
    assert r.json()["evidence"]["trust_ladder"] == 7
    r = client.post(f"/evidence/{ev['evidence_id']}/trust", json={"level": 2})
    assert r.status_code == 400  # downward is refused
    assert r.json()["reason"] == "invalid_trust"


def test_trust_advance_out_of_bounds_is_400(client):
    ev = client.post("/evidence/intake", json=_normalised_payload()).json()["evidence"]
    r = client.post(f"/evidence/{ev['evidence_id']}/trust", json={"level": 11})
    assert r.status_code == 400


def test_trust_needs_an_integer(client):
    ev = client.post("/evidence/intake", json=_normalised_payload()).json()["evidence"]
    for bad in ("7", True, None):
        r = client.post(f"/evidence/{ev['evidence_id']}/trust",
                        json={"level": bad})
        assert r.status_code == 400


def test_get_evidence_returns_row_and_distinct_404(client):
    ev = client.post("/evidence/intake", json=_normalised_payload()).json()["evidence"]
    r = client.get(f"/evidence/{ev['evidence_id']}")
    assert r.status_code == 200
    assert r.json()["evidence"]["trust_label"] == "external_evidence"
    assert r.json()["is_authorisation"] is False
    nf = client.get("/evidence/never-existed")
    assert nf.status_code == 404
    assert nf.json()["reason"] == "unknown_evidence"


def test_list_filters_and_trust_surface(client):
    client.post("/evidence/intake", json=_normalised_payload())
    client.post("/evidence/intake", json={
        "source_kind": "macro", "external_id": "CPI:2026Q4:US",
        "headline": "cpi", "payload_hash": "e" * 64})
    listed = client.get("/evidence", params={"source_kind": "arxiv"})
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["read_only"] is True
    trust = client.get("/research/trust")
    assert trust.status_code == 200
    t = trust.json()["trust"]
    assert t["total"] == 2
    assert t["per_ladder"]["1"] == 2
    assert t["is_authorisation"] is False
    # an unsafe min_trust filter is refused
    bad = client.get("/evidence", params={"min_trust": 42})
    assert bad.status_code == 400


def test_list_accepts_every_family_the_plane_can_hold(client):
    """The read filter and the store vocabulary may not drift apart (row 751).

    Row 750 added `news` to `KNOWN_SOURCE_KINDS`, so the plane can receive
    news rows -- but `GET /evidence` still validated the `source_kind`
    filter against its own hard-coded tuple, which had no `news` in it:
    every news row would be unreadable through the filter while the store
    held it. The filter now reads the shared constant, so a family the
    plane can ingest can always be listed, and an unknown family is still
    refused as `invalid_filter` rather than silently returning nothing.
    """
    from persistence.repositories_accounts import KNOWN_SOURCE_KINDS

    for kind in KNOWN_SOURCE_KINDS:
        r = client.get("/evidence", params={"source_kind": kind})
        assert r.status_code == 200, (
            f"source_kind={kind} is in KNOWN_SOURCE_KINDS but the read "
            f"filter refused it: {r.text}")
        assert r.json()["ok"] is True
    bad = client.get("/evidence", params={"source_kind": "youtube"})
    assert bad.status_code == 400
    assert bad.json()["reason"] == "invalid_filter"


def test_reads_need_a_principal(client, evidence_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    assert client.get("/evidence").status_code == 409
    assert client.get("/research/trust").status_code == 409


def test_unreachable_store_is_503(client, evidence_db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    r = client.get("/research/trust")
    assert r.status_code == 503
    assert r.json()["reason"] == "store_unavailable"


def test_tenancy_report_describes_evidence_plane(client):
    r = client.get("/system/health")
    t = r.json().get("tenancy", {})
    assert "evidence_plane" in t
    assert "POST /evidence/intake" in t["evidence_plane"]
    assert any("evidence" in entry for entry in t["ownership_enforced_on"])
