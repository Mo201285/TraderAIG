"""S3 AI Workforce routes over the real app (row 778).

The layer the domain tests cannot see: routes that resolve the acting principal,
map refusals to the right status (409 no principal, 404 unknown seat/proposal,
400 empty brief), make the AI Action Gateway's refusal a real HTTP 403 with the
routing destination, and serialise every payload with `is_authorisation: False`
naming the Risk Governor.
"""

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    from governance.identity import identity
    from research.workforce.service import (
        WorkerProposalStore,
        WorkforceService,
    )

    monkeypatch.setenv("TRADERAIG_AUTH", "0")
    users = dict(identity._users)
    subs = dict(identity._subscriptions)

    def _service():
        return WorkforceService(
            store=WorkerProposalStore(str(tmp_path / "workforce.json")))

    monkeypatch.setattr("operations.api._workforce_service", _service)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)


def _operator(client, monkeypatch, plan="institutional"):
    email = f"wf{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate", json={"plan": plan})
    return uid


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def test_list_seats_returns_the_ten_seats(client):
    res = client.get("/workforce/seats")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 10
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


def test_get_one_seat_and_a_distinct_404(client):
    ok = client.get("/workforce/seats/quant_engineer")
    assert ok.status_code == 200
    assert ok.json()["seat"]["seat_id"] == "quant_engineer"

    missing = client.get("/workforce/seats/cto_2")
    assert missing.status_code == 404
    assert missing.json()["reason"] == "unknown_seat"


def test_proposals_list_and_404(client):
    assert client.get("/workforce/proposals").json()["count"] == 0
    missing = client.get("/workforce/proposals/prop-ceo-0001")
    assert missing.status_code == 404
    assert missing.json()["reason"] == "unknown_proposal"


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------

def test_propose_requires_a_principal(client, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    res = client.post("/workforce/ceo/propose",
                      json={"brief": "study the tariff regime"})
    assert res.status_code == 409
    assert res.json()["reason"] == "no_principal"


def test_propose_creates_a_proposal_never_execution(client, monkeypatch):
    _operator(client, monkeypatch)
    res = client.post("/workforce/quant_engineer/propose",
                      json={"brief": "does momentum persist after a gap"})
    assert res.status_code == 200
    proposal = res.json()["proposal"]
    assert proposal["executed"] is False
    assert proposal["act"] == "propose"
    assert proposal["gateway"]["allowed"] is True

    listed = client.get("/workforce/proposals").json()
    assert listed["count"] == 1
    one = client.get(f"/workforce/proposals/{proposal['proposal_id']}")
    assert one.status_code == 200
    assert one.json()["proposal"]["proposal_id"] == proposal["proposal_id"]


def test_propose_unknown_seat_is_404_and_empty_brief_is_400(client, monkeypatch):
    _operator(client, monkeypatch)
    assert client.post("/workforce/ghost/propose",
                       json={"brief": "x"}).status_code == 404
    bad = client.post("/workforce/ceo/propose", json={"brief": "  "})
    assert bad.status_code == 400
    assert bad.json()["reason"] == "invalid_assignment"


# ---------------------------------------------------------------------------
# the AI Action Gateway, as a live control
# ---------------------------------------------------------------------------

def test_action_route_refuses_the_forbidden_four(client, monkeypatch):
    _operator(client, monkeypatch)
    for action in ("promote_live", "change_risk", "execute_trade",
                   "modify_production"):
        res = client.post("/workforce/cto/action", json={"action": action})
        assert res.status_code == 403, action
        body = res.json()
        assert body["reason"] == "forbidden_gateway_action"
        assert body["routed_to"]
        assert body["is_authorisation"] is False
        assert body["trade_authority"] == "risk/governor.py"


def test_action_route_allows_propose_and_refuses_unknown(client, monkeypatch):
    _operator(client, monkeypatch)
    ok = client.post("/workforce/cto/action", json={"action": "propose"})
    assert ok.status_code == 200
    assert ok.json()["decision"]["allowed"] is True

    unknown = client.post("/workforce/cto/action",
                          json={"action": "self_destruct"})
    assert unknown.status_code == 403
    assert unknown.json()["reason"] == "unknown_gateway_action"


def test_action_route_requires_the_risk_capability(client, monkeypatch):
    """The gateway is a governed surface: a principal without CAN_MANAGE_RISK
    cannot even ask it, so the forbidden-action refusal is not the only guard."""
    uid = client.post("/users",
                      json={"email": f"wf{time.time_ns()}@x.co"}).json()["user_id"]
    client.post(f"/users/{uid}/subscription/activate", json={"plan": "free"})
    # _guard compares against _acting_actor(); pin it to this free principal
    monkeypatch.setattr("operations.api._acting_actor", lambda: uid)
    res = client.post("/workforce/ceo/action", json={"action": "propose"})
    assert res.status_code == 403
