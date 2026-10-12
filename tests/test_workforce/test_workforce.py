"""S3 AI Workforce tests: the roster, the gateway and the governed worker loop.

Three claims, pinned in three ways:

* the roster is the section-8 org chart -- ten named seats, a valid reporting
  line, and every ``observes`` route is one FastAPI actually registers (so the
  roster cannot cite a route that was never built);
* the AI Action Gateway refuses the four forbidden actions (Promote Live /
  Change Risk / Execute a Trade / Modify Production) and routes them to the Risk
  Governor / Governance OS, and refuses anything it does not explicitly allow;
* the worker loop produces PROPOSALS, never execution -- every proposal carries
  ``executed: False`` and no trade permission, and an unknown seat or empty
  brief is refused (fail-closed).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.workforce.gateway import (  # noqa: E402
    AI_ACTION_GATEWAY,
    AIActionGateway,
    FORBIDDEN_ACTIONS,
)
from research.workforce.registry import (  # noqa: E402
    LAYER_ORDER,
    SEATS,
    WorkforceRegistry,
)
from research.workforce.service import (  # noqa: E402
    WorkerProposalStore,
    WorkforceService,
)

EXPECTED_SEATS = {
    "ceo", "cto", "research_director",
    "research_engineer", "backend_engineer", "frontend_engineer",
    "quant_engineer",
    "paper_researcher", "data_researcher", "strategy_researcher",
}


# ---------------------------------------------------------------------------
# the roster
# ---------------------------------------------------------------------------

def test_the_roster_is_the_ten_named_seats():
    assert {s.seat_id for s in SEATS} == EXPECTED_SEATS
    assert len(SEATS) == 10
    assert len(SEATS) == len({s.seat_id for s in SEATS})


def test_the_org_chart_is_well_formed():
    ids = {s.seat_id for s in SEATS}
    for seat in SEATS:
        assert seat.reports_to is None or seat.reports_to in ids, seat.seat_id
        assert seat.layer in LAYER_ORDER, seat.seat_id
        assert seat.department in ("executive", "engineering", "research")
        assert seat.reports_to != seat.seat_id


def test_every_observed_route_is_registered_by_the_api():
    """Honesty guard: a seat may only observe a route that exists."""
    from operations.api import app

    registered = {getattr(r, "path", "") for r in app.routes}
    for seat in SEATS:
        for path in seat.observes:
            assert path in registered, f"{seat.seat_id} observes {path}"


def test_registry_reads_and_summary():
    reg = WorkforceRegistry()
    assert reg.get("ceo") is not None
    assert reg.get("nobody") is None
    summary = reg.summary()
    assert summary["count"] == 10
    assert summary["by_layer"]["paperclip"] == 3
    assert summary["by_layer"]["crewai"] == 3
    assert summary["by_layer"]["engineering"] == 4
    assert summary["read_only"] is True


def test_seat_payload_never_carries_trade_permission():
    for seat in WorkforceRegistry().list():
        payload = seat.as_dict()
        assert payload["is_authorisation"] is False
        assert payload["trade_authority"] == "risk/governor.py"
        assert payload["proposes_never_executes"] is True


# ---------------------------------------------------------------------------
# the AI Action Gateway
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", sorted(FORBIDDEN_ACTIONS))
def test_the_four_forbidden_actions_are_refused_and_routed(action):
    decision = AI_ACTION_GATEWAY.request("cto", action, target="x")
    assert decision.allowed is False
    assert decision.reason == "forbidden_gateway_action"
    assert decision.routed_to
    assert "risk/governor.py" in decision.routed_to or \
        "governance" in decision.routed_to


def test_the_forbidden_set_is_exactly_the_spec_four():
    assert set(FORBIDDEN_ACTIONS) == {"promote_live", "change_risk",
                                      "execute_trade", "modify_production"}


def test_aliases_land_on_the_same_refusal():
    gateway = AIActionGateway()
    assert gateway.request("cto", "promote").action == "promote_live"
    assert gateway.request("cto", "trade").action == "execute_trade"
    assert gateway.request("cto", "go_live").allowed is False


def test_propose_is_allowed_and_anything_else_is_refused():
    gateway = AIActionGateway()
    assert gateway.request("ceo", "propose").allowed is True
    unknown = gateway.request("ceo", "self_destruct")
    assert unknown.allowed is False
    assert unknown.reason == "unknown_gateway_action"


def test_decision_payload_carries_the_honesty_keys():
    payload = AI_ACTION_GATEWAY.request("ceo", "execute_trade").as_dict()
    assert payload["is_authorisation"] is False
    assert payload["trade_authority"] == "risk/governor.py"


# ---------------------------------------------------------------------------
# the governed worker loop
# ---------------------------------------------------------------------------

def _service(tmp_path=None):
    store = WorkerProposalStore(str(tmp_path / "wp.json")) if tmp_path else \
        WorkerProposalStore()
    return WorkforceService(store=store)


def test_a_seat_produces_a_proposal_never_execution():
    service = _service()
    proposal = service.propose(seat_id="quant_engineer",
                               brief="does momentum persist after a gap")
    assert proposal["seat_id"] == "quant_engineer"
    assert proposal["status"] == "proposed"
    assert proposal["executed"] is False
    assert proposal["act"] == "propose"
    assert proposal["gateway"]["allowed"] is True
    assert proposal["is_authorisation"] is False
    assert proposal["trade_authority"] == "risk/governor.py"


def test_an_empty_brief_is_refused():
    service = _service()
    with pytest.raises(ValueError):
        service.propose(seat_id="ceo", brief="   ")


def test_an_unknown_seat_is_refused():
    service = _service()
    with pytest.raises(ValueError):
        service.propose(seat_id="cto_2", brief="do something")


def test_the_task_is_deterministic_and_the_model_is_never_invented():
    service = _service()
    a = service.propose(seat_id="quant_engineer", brief="claim X")
    b = service.propose(seat_id="quant_engineer", brief="claim X")
    assert a["task"] == b["task"]
    assert a["proposal_id"] != b["proposal_id"]
    assert a["model"] == ""  # empty stays empty; never an invented model


def test_proposals_persist_and_filter_by_seat(tmp_path):
    path = str(tmp_path / "wp.json")
    store = WorkerProposalStore(path)
    service = WorkforceService(store=store)
    service.propose(seat_id="ceo", brief="study the tariff regime")
    service.propose(seat_id="data_researcher", brief="summarise CPI data")

    reloaded = WorkforceService(store=WorkerProposalStore(path))
    assert len(reloaded.proposals()) == 2
    assert len(reloaded.proposals_for("ceo")) == 1
    assert reloaded.summary()["proposals"] == 2


def test_request_action_refuses_forbidden_and_allows_propose():
    service = _service()
    refused = service.request_action(seat_id="cto", action="execute_trade")
    assert refused["allowed"] is False
    assert refused["reason"] == "forbidden_gateway_action"
    allowed = service.request_action(seat_id="cto", action="propose")
    assert allowed["allowed"] is True
    with pytest.raises(ValueError):
        service.request_action(seat_id="ghost", action="propose")
