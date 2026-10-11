"""Evidence intake bus + the raw-shaped webhook seams (row 747, P2 slice;
SSRN/News seams join with row 750, RMI-02).

`operations.bus.EvidenceIntakeBus` is the batch delivery contract n8n works
against: a receipt (stored / already stored / refused-with-reason) where one
bad item or one store hiccup never kills the rest of the delivery. The webhook
routes (`POST /webhooks/macro`, `POST /webhooks/sentiment`,
`POST /webhooks/ssrn`, `POST /webhooks/news`) are the raw-shaped seams whose
URL fixes the source family. The tests pin:

- a batch delivery stores each accepted item once and returns
  ``action=duplicate``/``is_new=False`` on the second hit -- inside one batch
  or across deliveries;
- one bad item is isolated (``invalid_intake``/``kind_mismatch``), and a store
  failure is reported per item as ``store_unavailable`` (retryable), never
  fatal to the batch and never conflated with a rejected item;
- a pinned kind means the webhook URL is the contract: an item that claims a
  different ``source_kind`` is refused, a raw item is normalised under the pin,
  and a sentiment snapshot cannot be mislabelled as a macro print;
- every record and every receipt carry ``is_authorisation: False`` and name
  the Risk Governor -- evidence arrives as institutional knowledge, never as a
  permission;
- the webhooks need an acting principal (``409``), refuse a non-object body
  (``400``), and the tenancy report names the seams.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.bus import EvidenceIntakeBus  # noqa: E402
from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import EvidenceRecord  # noqa: E402
from persistence.repositories_accounts import EvidenceRepository  # noqa: E402
from research.evidence_plane import EvidencePlaneService  # noqa: E402

OPERATOR = "evidence-bus-principal"


def _macro_raw(code="CPI", region="US", currency="USD", actual=6.1,
               period="OCT", when="2026-10-07T12:30:00Z"):
    return {"code": code, "region": region, "currency": currency,
            "actual": actual, "forecast": 5.9, "previous": 5.4,
            "period": period, "datetime": when}


def _sent_raw(market="BTC", when="2026-10-07T08:00:00Z", **parts):
    return {"market": market, "datetime": when, **parts}


def _ssrn_raw(paper_id="5432109", title="Funding stress and intraday vol"):
    return {"id": paper_id, "title": title,
            "abstract": "We show funding stress raises intraday vol.",
            "keywords": ["market microstructure", "BTC"],
            "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id="
                   + paper_id}


def _news_raw(news_id="wire-a", title="Policymakers hold rates steady"):
    return {"id": news_id, "title": title,
            "url": f"https://example.com/{news_id}",
            "source": "ExampleWire", "published": "2026-10-07T06:00:00Z",
            "summary": "The benchmark rate was left unchanged.",
            "markets": ["XAUUSD"]}


# ---------------------------------------------------------------------------
# Bus unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    s = bind_test_session()
    s.execute(delete(EvidenceRecord))
    s.commit()
    return s


@pytest.fixture
def bus(session):
    return EvidenceIntakeBus(EvidencePlaneService(EvidenceRepository(session)))


def test_webhook_style_raw_item_pinned_kind_stores_once(bus):
    r = bus.deliver([_macro_raw()], kind="macro", delivered_by="n8n-node")
    assert r["delivered"] == 1
    assert r["accepted"] == 1 and r["duplicates"] == 0 and r["rejected"] == 0
    item = r["items"][0]
    assert item["ok"] is True and item["action"] == "intaken"
    assert item["is_new"] is True
    assert item["source_kind"] == "macro"
    assert item["trust_ladder"] == 1
    assert item["trust_label"] == "external_evidence"
    assert item["is_authorisation"] is False
    assert item["trade_authority"] == "risk/governor.py"
    assert r["is_authorisation"] is False
    assert r["trade_authority"] == "risk/governor.py"
    assert r["delivered_by"] == "n8n-node" and r["kind"] == "macro"
    assert len(bus._service.list_all()) == 1


def test_redelivery_is_a_duplicate_not_a_second_copy(bus):
    first = bus.deliver([_macro_raw()], kind="macro")
    assert first["accepted"] == 1
    again = bus.deliver([_macro_raw()], kind="macro")
    assert again["accepted"] == 0 and again["duplicates"] == 1
    assert again["items"][0]["action"] == "duplicate"
    assert again["items"][0]["is_new"] is False
    assert len(bus._service.list_all()) == 1  # one canonical row, forever


def test_same_item_twice_inside_one_batch_stores_once(bus):
    r = bus.deliver([_macro_raw(), _macro_raw(), _macro_raw(actual=7.0)],
                    kind="macro")
    assert r["delivered"] == 3
    assert r["accepted"] == 2 and r["duplicates"] == 1 and r["rejected"] == 0
    actions = [i["action"] for i in r["items"]]
    assert actions.count("intaken") == 2 and actions.count("duplicate") == 1
    assert len(bus._service.list_all()) == 2


def test_mixed_batch_isolates_bad_items(bus):
    r = bus.deliver([
        {"kind": "macro", "raw": _macro_raw()},
        {"kind": "pluto", "raw": {"everything": 1}},
        {"no_kind_no_raw_no_hash": True},
        {"source_kind": "arxiv", "external_id": "2401.1", "headline": "h"},
    ])
    assert r["accepted"] == 1
    assert r["rejected"] == 3
    assert r["store_unavailable"] == 0
    reasons = [i["reason"] for i in r["items"] if not i["ok"]]
    assert reasons == ["invalid_intake", "invalid_intake", "invalid_intake"]
    assert len(bus._service.list_all()) == 1  # the one good item is safe


def test_pinned_kind_refuses_a_mislabeled_item(bus):
    r = bus.deliver([
        _macro_raw(),
        {"source_kind": "sentiment", "market": "BTC", "datetime": "t",
         "payload_hash": "a" * 64},
    ], kind="macro")
    assert r["accepted"] == 1 and r["rejected"] == 1
    bad = [i for i in r["items"] if not i["ok"]][0]
    assert bad["reason"] == "kind_mismatch"
    kinds = [i["source_kind"] for i in r["items"] if i["ok"]]
    assert kinds == ["macro"]


def test_unpinned_normalised_payload_is_accepted(bus):
    r = bus.deliver([{
        "source_kind": "arxiv", "external_id": "2401.00010",
        "headline": "batch paper", "payload_hash": "b" * 64}])
    assert r["accepted"] == 1
    assert r["items"][0]["source_kind"] == "arxiv"


def test_store_failure_is_reported_per_item_not_fatal(session):
    svc = EvidencePlaneService(EvidenceRepository(session))
    original = svc.ingest

    def raiser(**kw):
        if kw.get("source_kind") == "macro":
            raise RuntimeError("store is down")
        return original(**kw)

    svc.ingest = raiser  # type: ignore[method-assign]
    r = EvidenceIntakeBus(svc).deliver([
        {"kind": "macro", "raw": _macro_raw()},
        {"source_kind": "arxiv", "external_id": "2401.2", "headline": "ok",
         "payload_hash": "c" * 64},
    ])
    assert r["accepted"] == 1 and r["rejected"] == 1
    assert r["store_unavailable"] == 1
    failed = [i for i in r["items"] if not i["ok"]][0]
    assert failed["reason"] == "store_unavailable"
    assert "store is down" in str(failed.get("error", ""))
    assert len(svc.list_all()) == 1  # the healthy item still landed


def test_deliver_requires_a_list(bus):
    with pytest.raises(ValueError):
        bus.deliver({"kind": "macro", "raw": _macro_raw()})


# ---------------------------------------------------------------------------
# Webhook route tests
# ---------------------------------------------------------------------------


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


def test_macro_webhook_single_raw_item(client):
    r = client.post("/webhooks/macro", json=_macro_raw())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["kind"] == "macro"
    assert body["accepted"] == 1 and body["duplicates"] == 0
    item = body["items"][0]
    assert item["action"] == "intaken" and item["source_kind"] == "macro"
    assert item["trust_ladder"] == 1 and item["is_authorisation"] is False
    trust = client.get("/research/trust").json()["trust"]
    assert trust["total"] == 1 and trust["per_source"]["macro"] == 1


def test_webhook_redelivery_is_a_duplicate(client):
    client.post("/webhooks/macro", json=_macro_raw())
    second = client.post("/webhooks/macro", json=_macro_raw()).json()
    assert second["accepted"] == 0 and second["duplicates"] == 1
    assert second["items"][0]["is_new"] is False
    assert client.get("/research/trust").json()["trust"]["total"] == 1


def test_sentiment_webhook_burst(client):
    burst = [
        _sent_raw(composite=55),
        _sent_raw(market="XAUUSD", when="2026-10-07T09:00:00Z"),
        _sent_raw(market="ETH", when="2026-10-07T09:05:00Z", social=4.2),
    ]
    r = client.post("/webhooks/sentiment", json=burst)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 3 and body["rejected"] == 0
    assert {i["source_kind"] for i in body["items"]} == {"sentiment"}
    trust = client.get("/research/trust").json()["trust"]
    assert trust["per_source"]["sentiment"] == 3


def test_missing_composite_stays_missing(client):
    r = client.post("/webhooks/sentiment", json=_sent_raw()).json()
    evidence_id = r["items"][0]["evidence_id"]
    row = client.get(f"/evidence/{evidence_id}").json()["evidence"]
    assert row["confidence"] is None
    assert row["headline"].endswith("components only")


def test_webhook_refuses_a_mislabeled_item(client):
    r = client.post("/webhooks/macro", json={
        "source_kind": "sentiment", "market": "BTC", "datetime": "x",
        "payload_hash": "d" * 64})
    assert r.status_code == 200
    bad = [i for i in r.json()["items"] if not i["ok"]][0]
    assert bad["reason"] == "kind_mismatch"
    assert client.get("/research/trust").json()["trust"]["total"] == 0


def test_webhook_needs_a_principal(client, evidence_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    r = client.post("/webhooks/macro", json=_macro_raw())
    assert r.status_code == 409
    assert r.json()["reason"] == "no_principal"


def test_webhook_rejects_non_object_bodies(client):
    scalar = client.post("/webhooks/macro", json=5)
    assert scalar.status_code == 400
    assert scalar.json()["reason"] == "invalid_delivery"
    empty = client.post("/webhooks/sentiment", json=[])
    assert empty.status_code == 400
    assert empty.json()["reason"] == "invalid_delivery"


# ---------------------------------------------------------------------------
# SSRN and News seams (row 750, RMI-02)
# ---------------------------------------------------------------------------


def test_ssrn_webhook_stores_a_paper_as_evidence(client):
    r = client.post("/webhooks/ssrn", json=_ssrn_raw())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["kind"] == "ssrn"
    assert body["accepted"] == 1 and body["rejected"] == 0
    item = body["items"][0]
    assert item["action"] == "intaken" and item["source_kind"] == "ssrn"
    assert item["trust_ladder"] == 1 and item["trust_label"] == \
        "external_evidence"
    assert item["is_authorisation"] is False
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    trust = client.get("/research/trust").json()["trust"]
    assert trust["total"] == 1 and trust["per_source"]["ssrn"] == 1
    assert "news" in trust["known_source_kinds"] and \
        "ssrn" in trust["known_source_kinds"]


def test_ssrn_redelivery_is_a_duplicate_not_a_second_copy(client):
    client.post("/webhooks/ssrn", json=_ssrn_raw())
    again = client.post("/webhooks/ssrn", json=_ssrn_raw()).json()
    assert again["accepted"] == 0 and again["duplicates"] == 1
    assert again["items"][0]["is_new"] is False
    assert client.get("/research/trust").json()["trust"]["total"] == 1


def test_news_webhook_burst_lands_as_news(client):
    burst = [_news_raw(), _news_raw(news_id="wire-b", title="Yield dips"),
             _news_raw(news_id="wire-c", title="Dollar steady")]
    r = client.post("/webhooks/news", json=burst)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 3 and body["rejected"] == 0
    assert {i["source_kind"] for i in body["items"]} == {"news"}
    trust = client.get("/research/trust").json()["trust"]
    assert trust["per_source"]["news"] == 3


def test_ssrn_seam_refuses_a_news_item_and_vice_versa(client):
    mislabelled = client.post("/webhooks/ssrn", json={
        "source_kind": "news", "title": "not a paper",
        "payload_hash": "e" * 64})
    assert mislabelled.status_code == 200
    bad = [i for i in mislabelled.json()["items"] if not i["ok"]][0]
    assert bad["reason"] == "kind_mismatch"
    news_side = client.post("/webhooks/news", json={
        "source_kind": "ssrn", "title": "not a story",
        "payload_hash": "f" * 64})
    bad2 = [i for i in news_side.json()["items"] if not i["ok"]][0]
    assert bad2["reason"] == "kind_mismatch"
    assert client.get("/research/trust").json()["trust"]["total"] == 0


def test_new_seams_need_a_principal(client, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    for route, payload in (("/webhooks/ssrn", _ssrn_raw()),
                           ("/webhooks/news", _news_raw())):
        r = client.post(route, json=payload)
        assert r.status_code == 409
        assert r.json()["reason"] == "no_principal"


def test_tenancy_report_names_the_webhook_seams(client):
    r = client.get("/system/health")
    t = r.json().get("tenancy", {})
    assert "webhooks/macro" in t["evidence_plane"]
    assert "webhooks/sentiment" in t["evidence_plane"]
    assert "webhooks/ssrn" in t["evidence_plane"]
    assert "webhooks/news" in t["evidence_plane"]
    assert any("webhooks/macro" in entry
               for entry in t["ownership_enforced_on"])
    assert any("webhooks/ssrn" in entry
               for entry in t["ownership_enforced_on"])
