"""Challenge routes over the real MT5 account: wiring, provenance, refusals.

The calculator's correctness is covered in `test_challenge_policy.py`. This file
covers the seams where a correct layer can still be wired up wrongly -- reading
the wrong account, accepting a rule nobody sourced, advancing the baseline from
a read, and reporting an allowance that does not count.

Every test here asserts against the running `app` rather than a stub, because
the failure mode being guarded is exactly the seam: a policy engine that scores
nothing because it is pointed at the wrong account, or a route that lets a
caller move the reference points a decision is measured from.
"""

from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from challenge.registry import PolicyRegistry  # noqa: E402
from challenge.service import ChallengeService  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from operations.api import app, state  # noqa: E402

SOURCE = "provider-terms-2026-09.pdf"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Leave the account, the registry, the env and the identity store as found.

    The identity maps are restored here for the reason row 731 paid for once:
    a throwaway user left in the store becomes the acting principal for whatever
    runs next, which makes the suite's result depend on collection order. This
    file sorts before `test_subscription_lifecycle.py`, so without the restore
    these tests decide whether that file passes -- sixteen failures that exist
    only because of alphabetical ordering.

    The service is process-wide too, so it is rebuilt rather than poked at.
    """
    from challenge.service import challenge_service
    from governance.identity import identity

    account = dict(state.account.__dict__)
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    audit_len = len(identity._audit)
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROGRAM", raising=False)
    fresh = ChallengeService(PolicyRegistry())
    held = {k: v for k, v in fresh.__dict__.items()}
    try:
        yield
    finally:
        for key, value in list(challenge_service.__dict__.items()):
            if key not in held:
                delattr(challenge_service, key)
        for key, value in held.items():
            setattr(challenge_service, key, value)
        for key, value in account.items():
            if hasattr(state.account, key):
                setattr(state.account, key, value)
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        del identity._audit[audit_len:]


def _full_policy_payload(**overrides) -> dict:
    payload = {
        "provider": "DemoProp", "program": "Classic 2-Step",
        "policy_version": "2026.09", "account_size": 100_000,
        "effective_from": "2026-09-01",
        "profit_target": {"value": 0.08, "source": SOURCE},
        "daily_loss_limit": {"value": 0.05, "source": SOURCE},
        "max_drawdown": {"value": 0.04, "source": SOURCE},
        "minimum_trading_days": {"value": 10, "source": SOURCE},
        "max_leverage": {"value": 100, "source": SOURCE},
        "drawdown_type": "static",
        "instruments_default": "allowed", "overnight": "allowed",
        "weekend": "denied",
    }
    payload.update(overrides)
    return payload


def _operator(client, monkeypatch) -> None:
    """Give the caller the entitlement every challenge route requires."""
    email = f"chal{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate", json={"plan": "institutional"})


def _unentitled(client, monkeypatch) -> None:
    """A real user who exists but holds no risk entitlement.

    Not the same as having no user at all: with no principal the guard passes on
    purpose so a fresh install can still enrol itself (row 730's bootstrap
    allowance), so testing a refusal against an empty identity store would
    assert the opposite of what it means.
    """
    from governance.identity import SubscriptionPlan

    email = f"plain{time.time_ns()}@x.co"
    client.post("/users", json={"email": email})
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post("/users", json={"email": f"other{time.time_ns()}@x.co"})
    assert SubscriptionPlan.FREE.value == "free"


# ---------------------------------------------------------------------------
# the routes answer, and they answer honestly
# ---------------------------------------------------------------------------

def test_the_challenge_routes_are_readable_without_an_entitlement(client):
    """Reads stay open by design (row 732) and must not 403 the dashboard."""
    for path in ("/challenge/status", "/challenge/headroom", "/challenge/policies"):
        assert client.get(path).status_code == 200


def test_a_disconnected_account_reports_unconnected_rather_than_failing(client):
    """A read with no terminal attached must still answer."""
    payload = client.get("/challenge/status").json()

    assert payload["ok"] is True
    assert payload["account_id"] == "unconnected"


def test_with_no_policy_the_account_is_halted_and_says_why(client):
    """34.6: no policy means UNKNOWN, and the reason is reported, not guessed."""
    payload = client.get("/challenge/status").json()

    assert payload["decision"]["permission"] == "halt"
    assert payload["counts"] is False
    assert any("policy" in reason for reason in payload["blocking_reasons"])


def test_an_allowance_that_does_not_count_is_reported_as_not_counting(client, monkeypatch):
    """The load-bearing field.

    A brand-new service has no baseline, so an ALLOW would be an allowance
    computed from nothing. Downgrading it to PROTECT is what stops a restart
    from turning a breached account into a permission.
    """
    from challenge.service import challenge_service as svc
    svc.observe("12345", equity=100_000, balance=100_000)

    payload = svc.evaluate("12345", None, equity=100_000, balance=100_000)

    assert payload["counts"] is False
    assert payload["decision"]["permission"] != "allow"


def _policy():
    """A fully specified policy, as an object rather than a request payload."""
    from challenge.policy import (ChallengePolicy, DrawdownType, InstrumentPolicy,
                                 Restriction, RuleValue)

    return ChallengePolicy(
        provider="DemoProp", program="Classic 2-Step", account_size=100_000.0,
        policy_version="2026.09",
        profit_target=RuleValue.known(0.08, source=SOURCE),
        daily_loss_limit=RuleValue.known(0.05, source=SOURCE),
        max_drawdown=RuleValue.known(0.04, source=SOURCE),
        minimum_trading_days=RuleValue.known(10, source=SOURCE),
        max_leverage=RuleValue.known(100, source=SOURCE),
        drawdown_type=DrawdownType.STATIC,
        instruments=InstrumentPolicy(default=Restriction.ALLOWED, source=SOURCE),
        overnight=Restriction.ALLOWED, weekend=Restriction.DENIED)


def test_a_watched_account_is_not_graded_against_an_inferred_opening_balance():
    """The defect this milestone exists for, in the shape the live account hit it.

    Real account 1787174 on FTTrading-Server: 10,473 deals over five days, net
    -6,221.32, balance 95,975.13. The process restarted, the first reading was
    taken, and a baseline was built from 95,975.13 -- the account's *current*
    value. Every drawdown is measured from the opening balance, so an account
    roughly 4% down scores 0% used, and the layer would have reported it as
    untouched while a static-drawdown challenge was already most of the way
    spent. The numbers here are that account's real figures.
    """
    from challenge.registry import PolicyRegistry as Registry
    from challenge.service import ChallengeService

    service = ChallengeService(Registry())
    policy = _policy()

    # First reading after a restart: all we know is what it is worth now.
    service.observe("1787174", equity=95_975.13, balance=95_975.13)
    payload = service.evaluate("1787174", policy,
                               equity=95_975.13, balance=95_975.13)

    assert payload["counts"] is False
    assert payload["decision"]["permission"] == "halt"
    assert payload["baseline"]["origin"] == "observed"
    assert payload["baseline"]["gradeable"] is False

    # No dimension may report a number measured from the inferred baseline.
    for name, dimension in payload["headroom"]["dimensions"].items():
        assert dimension["is_known"] is False, f"{name} reported a number"
        assert dimension["used"] is None, f"{name} reported used={dimension['used']}"
        assert dimension["remaining"] is None, f"{name} reported a headroom"

    assert any("inferred" in (r or "") for r in payload["blocking_reasons"])
    # The reason has to reach the operator, not just the boolean. A decision that
    # reports HALT with no visible cause is the kind of halt an operator learns
    # to work around, so the baseline check is asserted to be present and to
    # name the problem.
    checks = {c["check"]: c for c in payload["decision"]["checks"]}
    assert "baseline" in checks, f"no baseline check in {sorted(checks)}"
    assert checks["baseline"]["permission"] == "halt"
    assert "inferred" in checks["baseline"]["detail"]


def test_declaring_the_opening_balance_makes_the_account_gradable():
    """And the fix is the documented number, not a cleverer guess."""
    from challenge.registry import PolicyRegistry as Registry
    from challenge.service import ChallengeService

    service = ChallengeService(Registry())
    policy = _policy()

    service.observe("1787174", equity=95_975.13, balance=95_975.13)
    service.declare_baseline("1787174", 100_000.0,
                             source="FTTrading competition terms, account size")
    payload = service.evaluate("1787174", policy,
                               equity=95_975.13, balance=95_975.13)

    assert payload["baseline"]["gradeable"] is True
    assert payload["counts"] is True
    # Now the drawdown is real: 4024.87 of a 4,000 limit is a breach, which is
    # the opposite of what the inferred baseline reported.
    drawdown = payload["headroom"]["dimensions"]["max_drawdown"]
    assert drawdown["is_known"] is True
    assert drawdown["used"] == pytest.approx(4_024.87)
    assert payload["decision"]["permission"] == "halt"


def test_an_opening_balance_with_no_source_is_refused(client, monkeypatch):
    """The route will not accept a number it cannot trace to a document."""
    _operator(client, monkeypatch)

    missing_source = client.post("/challenge/accounts/a1/baseline",
                                 json={"start_equity": 100_000})
    assert missing_source.status_code == 400
    assert "source is required" in missing_source.json()["detail"]

    missing_amount = client.post("/challenge/accounts/a1/baseline",
                                 json={"source": "terms"})
    assert missing_amount.status_code == 400

    impossible = client.post("/challenge/accounts/a1/baseline",
                             json={"start_equity": -5, "source": "terms"})
    assert impossible.status_code == 400


def test_a_declared_baseline_needs_the_risk_entitlement(client, monkeypatch):
    """It is the one route that can make an account gradable."""
    _unentitled(client, monkeypatch)

    assert client.post("/challenge/accounts/a1/baseline",
                       json={"start_equity": 100_000,
                             "source": "terms"}).status_code == 403


def test_a_declared_baseline_needs_its_source_at_the_service_too():
    """Not only at the route.

    The route rejects a sourceless baseline, which is what protects the HTTP
    surface. The service is the library, and the next caller will be a script
    or a seeding job that does not go through HTTP at all -- so the guard has to
    live at the level where the baseline is actually written down, or it is
    only a guard on the one path that happened to be built first.
    """
    from challenge.registry import PolicyRegistry as Registry
    from challenge.service import ChallengeService

    service = ChallengeService(Registry())

    for source in ("", "   ", None):
        with pytest.raises(ValueError, match="source"):
            service.declare_baseline("a1", 100_000, source=source)

    with pytest.raises(ValueError, match="positive"):
        service.declare_baseline("a1", 0, source="terms")

    # And a rejected declaration leaves the account exactly as untrusted as it
    # was, rather than half-seeded.
    assert service.baseline_status("a1")["has_baseline"] is False


def test_a_completed_baseline_against_a_real_policy_is_allowed(client, monkeypatch):
    """The end-to-end happy path: real account facts, verified policy, ALLOW."""
    from challenge.service import challenge_service as svc
    from challenge.policy import (ChallengePolicy, DrawdownType, InstrumentPolicy,
                                 Restriction, RuleValue)
    _operator(client, monkeypatch)
    assert client.post("/challenge/policies",
                       json=_full_policy_payload()).status_code == 200

    policy = ChallengePolicy(
        provider="DemoProp", program="Classic 2-Step", account_size=100_000.0,
        policy_version="2026.09",
        profit_target=RuleValue.known(0.08, source=SOURCE),
        daily_loss_limit=RuleValue.known(0.05, source=SOURCE),
        max_drawdown=RuleValue.known(0.04, source=SOURCE),
        minimum_trading_days=RuleValue.known(10, source=SOURCE),
        max_leverage=RuleValue.known(100, source=SOURCE),
        drawdown_type=DrawdownType.STATIC,
        instruments=InstrumentPolicy(default=Restriction.ALLOWED, source=SOURCE),
        overnight=Restriction.ALLOWED, weekend=Restriction.DENIED)

    svc.observe("acct", equity=100_000, balance=100_000)
    # Watching the account is not knowing how it began. Until the opening
    # balance is declared from the provider's terms this must not read ALLOW,
    # which is what the next test asserts; here we declare it so the rest of the
    # decision -- verified policy, real numbers, room to trade -- is reachable.
    svc.declare_baseline("acct", 100_000, source="DemoProp terms 2026-09 p.1")
    payload = svc.evaluate("acct", policy, equity=100_000, balance=100_000)

    assert payload["counts"] is True
    assert payload["decision"]["permission"] == "allow"
    assert payload["headroom"]["dimensions"]["max_drawdown"]["remaining"] \
        == pytest.approx(4_000.0)


# ---------------------------------------------------------------------------
# provenance: the rule that stops invented numbers
# ---------------------------------------------------------------------------

def test_a_rule_with_no_source_document_is_refused(client, monkeypatch):
    """34.6: a number nobody can trace to provider terms is not a rule.

    The 400 matters more than the shape of the check: accepting a bare float
    and storing a blank source would leave the registry looking complete while
    every limit in it was a guess.
    """
    _operator(client, monkeypatch)
    payload = _full_policy_payload(max_drawdown=0.04)

    response = client.post("/challenge/policies", json=payload)

    assert response.status_code == 400
    assert "source" in response.json()["detail"]


def test_a_rule_with_a_value_but_no_source_is_refused(client, monkeypatch):
    _operator(client, monkeypatch)
    payload = _full_policy_payload(max_drawdown={"value": 0.04})

    assert client.post("/challenge/policies", json=payload).status_code == 400


def test_a_policy_registered_without_a_version_is_refused(client, monkeypatch):
    _operator(client, monkeypatch)
    payload = _full_policy_payload()
    payload.pop("policy_version")

    assert client.post("/challenge/policies", json=payload).status_code == 400


def test_a_partial_policy_registers_but_reports_what_is_missing(client, monkeypatch):
    """Registering half a policy is legitimate; not knowing that you did is not."""
    _operator(client, monkeypatch)
    payload = _full_policy_payload(policy_version="draft")
    payload.pop("profit_target")

    body = client.post("/challenge/policies", json=payload).json()

    assert body["is_fully_specified"] is False
    assert "profit_target" in body["missing_rules"]
    assert "RESTRICT" in body["effect"]


def test_registering_a_policy_without_the_risk_entitlement_is_refused(client, monkeypatch):
    """These routes mutate governance state, so they are guarded like any other."""
    _unentitled(client, monkeypatch)

    assert client.post("/challenge/policies",
                       json=_full_policy_payload()).status_code == 403


# ---------------------------------------------------------------------------
# the baseline is advanced only by observation
# ---------------------------------------------------------------------------

def test_reading_headroom_does_not_move_the_reference_points(client):
    """A dashboard refresh must not lower the high-water marks it reports on.

    If a read could set the equity low, then repeatedly polling a losing
    account would keep resetting its own baseline, and the low that decides a
    static breach would drift upward with every page view.
    """
    from challenge.service import challenge_service as svc
    svc.observe("acct", equity=100_000, balance=100_000)
    before = svc.baseline_status("acct")["equity_low"]

    svc.snapshot("acct", equity=10_000, balance=100_000)
    svc.evaluate("acct", None, equity=10_000, balance=100_000)

    assert svc.baseline_status("acct")["equity_low"] == before


def test_the_day_roll_returns_a_floating_accounts_room():
    """Floating drawdown resets daily; without the roll it never would."""
    from challenge.headroom import max_drawdown_headroom
    from challenge.policy import (ChallengePolicy, DrawdownType, InstrumentPolicy,
                                 Restriction, RuleValue)
    from challenge.service import ChallengeService

    service = ChallengeService(PolicyRegistry())
    policy = ChallengePolicy(
        provider="P", program="C", policy_version="v1",
        profit_target=RuleValue.known(0.08, source=SOURCE),
        daily_loss_limit=RuleValue.known(0.05, source=SOURCE),
        max_drawdown=RuleValue.known(0.04, source=SOURCE),
        minimum_trading_days=RuleValue.known(10, source=SOURCE),
        max_leverage=RuleValue.known(100, source=SOURCE),
        drawdown_type=DrawdownType.FLOATING,
        instruments=InstrumentPolicy(default=Restriction.ALLOWED, source=SOURCE),
        overnight=Restriction.ALLOWED, weekend=Restriction.ALLOWED)

    service.observe("a", equity=100_000, balance=100_000, day_epoch=1000)
    service.observe("a", equity=96_000, balance=100_000, day_epoch=1000)
    assert max_drawdown_headroom(
        policy, service.snapshot("a", equity=96_000, balance=100_000)).used \
        == pytest.approx(4_000.0)

    service.observe("a", equity=100_000, balance=100_000, day_epoch=1001)
    next_day = service.snapshot("a", equity=100_000, balance=100_000)
    assert max_drawdown_headroom(policy, next_day).used == pytest.approx(0.0)


def test_a_service_that_has_never_seen_an_account_refuses_to_grade_it():
    """No observation means no baseline, and no baseline means no ALLOW."""
    from challenge.service import ChallengeService
    from challenge.registry import PolicyRegistry as Registry

    service = ChallengeService(Registry())
    payload = service.evaluate("never-seen", None, equity=100_000, balance=100_000)

    assert payload["counts"] is False
    assert payload["baseline"]["has_baseline"] is False
    assert "no observation" in payload["baseline"]["reason"]


def test_an_account_reporting_zero_is_not_graded_as_a_healthy_one():
    """A terminal that is attached but reporting nothing.

    equity=0/balance=0 would otherwise build a baseline of zero, and every limit
    would then read as fully available -- the disconnected account would look
    like the healthiest account on the platform.
    """
    from challenge.registry import PolicyRegistry as Registry
    from challenge.service import ChallengeService

    service = ChallengeService(Registry())
    service.observe("dead-feed", equity=0, balance=0)

    status = service.baseline_status("dead-feed")
    payload = service.evaluate("dead-feed", None, equity=0, balance=0)

    assert status["has_baseline"] is False
    assert payload["counts"] is False
    assert payload["decision"]["permission"] != "allow"


def test_a_complete_baseline_is_graded():
    """The counterpart, so the guard above cannot be satisfied by always refusing."""
    from challenge.registry import PolicyRegistry as Registry
    from challenge.service import ChallengeService

    service = ChallengeService(Registry())
    service.observe("live", equity=100_000, balance=100_000)

    assert service.baseline_status("live")["has_baseline"] is True


def test_the_process_wide_registry_starts_empty():
    """The module-level registry, not a locally constructed one.

    Asserting on a fresh `PolicyRegistry()` proves the class is empty; it says
    nothing about the singleton the API actually resolves against. Seeding the
    shared registry with invented provider terms would leave this test green
    while every account in the deployment got graded against made-up limits.
    """
    from challenge.registry import registry

    assert registry.all_policies() == []
    assert registry.resolve("DemoProp", "Classic 2-Step") is None


def test_two_accounts_do_not_share_a_baseline():
    """34.13/34.14 as a data property: one account's history is another's
    business, and the only thing enforcing it is the keying."""
    from challenge.service import ChallengeService
    from challenge.registry import PolicyRegistry as Registry

    service = ChallengeService(Registry())
    service.observe("acct-1", equity=100_000, balance=100_000)
    service.observe("acct-1", equity=90_000, balance=100_000)
    service.observe("acct-2", equity=100_000, balance=100_000)

    assert service.baseline_status("acct-1")["equity_low"] == pytest.approx(90_000)
    assert service.baseline_status("acct-2")["equity_low"] == pytest.approx(100_000)
    assert service.forget("acct-1") is True
    assert "acct-1" not in service.accounts()
    assert "acct-2" in service.accounts()


# ---------------------------------------------------------------------------
# state transitions over HTTP
# ---------------------------------------------------------------------------

def test_transitioning_without_the_risk_entitlement_is_refused(client, monkeypatch):
    _unentitled(client, monkeypatch)

    assert client.post("/challenge/accounts/a1/state",
                       json={"state": "active", "reason": "x"}).status_code == 403


def test_a_halted_account_cannot_be_resumed_through_the_route(client, monkeypatch):
    """The wire-level version of 34.10's prohibition."""
    _operator(client, monkeypatch)
    base = {"reason": "connected"}
    assert client.post("/challenge/accounts/a1/state",
                       json={"state": "active", **base}).status_code == 200
    assert client.post("/challenge/accounts/a1/state",
                       json={"state": "halted", "reason": "breached"}).status_code == 200

    response = client.post("/challenge/accounts/a1/state",
                           json={"state": "active", "reason": "feels better"})

    assert response.status_code == 409
    assert "cannot move from halted" in response.json()["detail"]


def test_recovery_without_a_named_authorizer_is_refused(client, monkeypatch):
    _operator(client, monkeypatch)
    client.post("/challenge/accounts/a2/state",
                json={"state": "active", "reason": "connected"})
    client.post("/challenge/accounts/a2/state",
                json={"state": "halted", "reason": "breached"})

    response = client.post("/challenge/accounts/a2/recover",
                           json={"reason": "re-verified"})

    assert response.status_code == 400
    assert "authorized_by" in response.json()["detail"]


def test_a_named_recovery_resumes_the_account_and_is_audited(client, monkeypatch):
    from governance.identity import identity

    _operator(client, monkeypatch)
    client.post("/challenge/accounts/a3/state",
                json={"state": "active", "reason": "connected"})
    client.post("/challenge/accounts/a3/state",
                json={"state": "halted", "reason": "breached"})

    response = client.post("/challenge/accounts/a3/recover", json={
        "reason": "policy re-verified after a terms change",
        "authorized_by": "operator@x.co", "conditions_met": {"policy": "v2"}})

    assert response.status_code == 200
    assert response.json()["state"] == "active"
    actions = [entry.action for entry in identity.audit_log(limit=50)]
    assert "challenge.state.recovered" in actions


def test_an_unknown_state_name_is_a_400_naming_the_legal_values(client, monkeypatch):
    _operator(client, monkeypatch)

    response = client.post("/challenge/accounts/a4/state",
                           json={"state": "yolo", "reason": "x"})

    assert response.status_code == 400
    assert "halted" in response.json()["detail"]


def test_a_negative_proposed_risk_is_rejected(client):
    response = client.get("/challenge/headroom?proposed_risk=-100")

    assert response.status_code == 400
