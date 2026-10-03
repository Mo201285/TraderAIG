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

    Paid product entitlements are restored for the same reason and by the same
    argument: a purchase left behind outlives its user, and the acting principal
    of the next file would inherit a service nobody in that file bought.

    The service is process-wide too, so it is rebuilt rather than poked at.
    """
    from challenge.service import challenge_service
    from governance.identity import identity
    from governance.products import products

    account = dict(state.account.__dict__)
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    audit_len = len(identity._audit)
    bought = dict(products._entitlements)
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROGRAM", raising=False)
    fresh = ChallengeService(PolicyRegistry())
    held = {k: v for k, v in fresh.__dict__.items()}
    # The registry OBJECT and its contents, both restored after the attribute
    # swap below and for the same reason it needs its own snapshot: restoring the
    # service attributes points `_registry` at the throwaway registry `fresh` was
    # built with, which happens to be empty -- and an empty registry is not the
    # state this file started in, so whichever test ran first would silently
    # decide the starting state for all the others.
    #
    # Without this, a policy registered by one test is still there for the next,
    # and registration is immutable on purpose ("register a new version rather
    # than replacing one"), so the second test gets a 422 for doing nothing
    # wrong. The registry was right; the fixture was leaking.
    live_registry = challenge_service._registry
    policies = {slot: list(versions)
                for slot, versions in live_registry._policies.items()}
    try:
        yield
    finally:
        for key, value in list(challenge_service.__dict__.items()):
            if key not in held:
                delattr(challenge_service, key)
        for key, value in held.items():
            setattr(challenge_service, key, value)
        # After the attribute swap, because it reassigns `_registry` wholesale.
        challenge_service._registry = live_registry
        live_registry._policies.clear()
        live_registry._policies.update(policies)
        for key, value in account.items():
            if hasattr(state.account, key):
                setattr(state.account, key, value)
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        products._entitlements.clear()
        products._entitlements.update(bought)
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
    """Give the caller everything every challenge route requires.

    Two separate authorities, because §34.15 requires both and they are granted
    by different subsystems: the institutional plan supplies `can_manage_risk`,
    and the $9.99 product supplies `challenge_management`. The second one used to
    be free with the first, which made the commercial half of the feature
    untestable — every operator passed the gate and nothing exercised the
    refusal. Buying it here keeps the tests honest about what the product is for.
    """
    from governance.products import products

    email = f"chal{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate", json={"plan": "institutional"})
    products.grant(uid, "challenge_basic", charge_id="ch_test", actor="test")


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


def _purchased_but_no_risk(client, monkeypatch) -> None:
    """The operator §34.18 exists for: institutional, and paid nothing for the
    challenge service.

    The gate must still refuse. An institutional subscription buys authority over
    the platform; it is not a receipt for the $9.99 product, and treating it as
    one would make the paid tier unbuyable and the free tier unprotected.
    """
    from governance.identity import Entitlement, identity

    email = f"unpaid{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate",
                json={"plan": "institutional"})

    assert identity.can(uid, Entitlement.CAN_MANAGE_RISK) is True
    assert identity.can(uid, Entitlement.CHALLENGE_MANAGEMENT) is False


# ---------------------------------------------------------------------------
# the routes answer, and they answer honestly
# ---------------------------------------------------------------------------

def test_the_challenge_routes_are_readable_without_an_entitlement(client):
    """Reads stay open by design (row 732) and must not 403 the dashboard."""
    for path in ("/challenge/status", "/challenge/headroom", "/challenge/policies"):
        assert client.get(path).status_code == 200


def test_a_disconnected_account_reports_unconnected_rather_than_failing(client,
                                                                        monkeypatch):
    """A read with no terminal attached must still answer.

    The account is unconnected here on purpose rather than by luck. `state` is a
    process-wide singleton, and the autouse fixture snapshots whatever it finds,
    so a test in another file that leaves a login behind is faithfully preserved
    into this one -- and the assertion below then fails on the ambient account
    rather than on anything about this route. Arranging login 0 tests what the
    name says: no terminal, still an answer.
    """
    monkeypatch.setattr(state.account, "login", 0)
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
    service.declare_baseline("1787174", 100_000.0, source="FTTrading competition terms, account size", verified=True)
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

    # Same argument for withdrawal, and the same mistake twice: the route checks
    # the reason, so testing withdrawal through HTTP only ever exercises the
    # route. The service guard is the one a script or a seeding job would meet.
    with pytest.raises(ValueError, match="reason"):
        service.withdraw_baseline("a1", reason="")
    with pytest.raises(ValueError, match="reason"):
        service.withdraw_baseline("a1", reason=None)

    # A withdraw naming an account with no baseline is a 404, not a silent
    # success -- nothing was withdrawn, and reporting otherwise would let a
    # caller believe a wrong figure had been cleared.
    assert service.withdraw_baseline("never-seen", reason="x")["withdrawn"] is False

    # And a rejected declaration leaves the account exactly as untrusted as it
    # was, rather than half-seeded.
    assert service.baseline_status("a1")["has_baseline"] is False


def test_an_unverified_declaration_is_recorded_but_never_graded(client, monkeypatch):
    """The mistake this endpoint actually invites, made into a test.

    Somebody who does not have the terms will still want to seed the account,
    and the old signature let them do it by typing a plausible source string
    next to a guessed number -- which is precisely how a 100,000 was written
    into a live account from a conversation that never contained the document.
    A `source` is a promise nobody can check, so the claim about having read the
    document has to be its own field, and lacking it must cost the permission.
    """
    from challenge.service import challenge_service as svc

    _operator(client, monkeypatch)
    svc.observe("a1", equity=95_975.13, balance=95_975.13)

    response = client.post("/challenge/accounts/a1/baseline",
                           json={"start_equity": 100_000,
                                 "source": "FTTrading competition terms",
                                 "verified": False})

    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "asserted"
    assert body["gradeable"] is False
    assert "ASSERTED" in body["warning"]

    status = svc.baseline_status("a1")
    assert status["has_baseline"] is True      # the figure is remembered
    assert status["gradeable"] is False        # but it earns nothing
    assert "asserted" in status["reason"]

    # Omitting `verified` is the same as asserting it is false. Silence must
    # never be read as consent.
    default = client.post("/challenge/accounts/a1/baseline",
                          json={"start_equity": 100_000,
                                "source": "FTTrading competition terms"})
    assert default.json()["origin"] == "asserted"
    assert default.json()["gradeable"] is False

    # And an asserted baseline still blocks a real decision, it does not just
    # annotate one.
    payload = svc.evaluate("a1", _policy(), equity=95_975.13, balance=95_975.13)
    assert payload["counts"] is False
    assert payload["decision"]["permission"] == "halt"


def test_a_verified_declaration_is_graded(client, monkeypatch):
    from challenge.service import challenge_service as svc

    _operator(client, monkeypatch)
    svc.observe("a1", equity=100_000, balance=100_000)

    response = client.post("/challenge/accounts/a1/baseline",
                           json={"start_equity": 100_000,
                                 "source": "DemoProp terms 2026-09 p.1",
                                 "verified": True})

    assert response.json()["origin"] == "declared"
    assert response.json()["graded"] is True
    assert svc.baseline_status("a1")["gradeable"] is True


def test_a_wrong_declaration_can_be_withdrawn_without_a_restart(client, monkeypatch):
    """A declared figure that turns out wrong must be takeable back.

    The alternative is to leave a wrong opening balance in place and restart the
    host, which on a 24/7 box is a much bigger event than admitting a number
    was wrong. The measured low-water marks survive; only the claim is dropped.
    """
    from challenge.service import challenge_service as svc

    _operator(client, monkeypatch)
    svc.observe("a1", equity=95_975.13, balance=95_975.13)
    client.post("/challenge/accounts/a1/baseline",
                json={"start_equity": 100_000, "source": "terms", "verified": True})
    assert svc.baseline_status("a1")["gradeable"] is True
    low_before = svc.baseline_status("a1")["equity_low"]

    refused = client.post("/challenge/accounts/a1/baseline/withdraw", json={})
    assert refused.status_code == 400

    response = client.post("/challenge/accounts/a1/baseline/withdraw",
                           json={"reason": "account size was 50,000, not 100,000"})
    assert response.status_code == 200
    body = response.json()
    assert body["withdrawn"] is True
    assert body["was_start_equity"] == 100_000.0
    assert body["was_origin"] == "declared"

    # Untrusted again, and the measured history is still there.
    status = svc.baseline_status("a1")
    assert status["gradeable"] is False
    assert status["equity_low"] == low_before

    # Re-seeding correctly afterwards works, and the wrong figure is gone.
    client.post("/challenge/accounts/a1/baseline",
                json={"start_equity": 50_000, "source": "corrected terms",
                      "verified": True})
    reseeded = svc.baseline_status("a1")
    assert reseeded["gradeable"] is True
    assert reseeded["start_equity"] == 50_000.0


def test_withdrawing_needs_the_risk_entitlement(client, monkeypatch):
    _unentitled(client, monkeypatch)

    assert client.post("/challenge/accounts/a1/baseline/withdraw",
                       json={"reason": "x"}).status_code == 403


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
        overnight=Restriction.ALLOWED, weekend=Restriction.DENIED,
        # The broker's day boundary. The daily loss is measured against the
        # provider's trading day, so an unestablished offset leaves that
        # dimension unscored and PROTECTs the account. Correct behaviour, and
        # the reason the endpoint can now be given one at all -- it was
        # unreachable through registration before this workstream.
        server_utc_offset_hours=3.0)

    svc.observe("acct", equity=100_000, balance=100_000)
    # Watching the account is not knowing how it began. Until the opening
    # balance is declared from the provider's terms this must not read ALLOW,
    # which is what the next test asserts; here we declare it so the rest of the
    # decision -- verified policy, real numbers, room to trade -- is reachable.
    svc.declare_baseline("acct", 100_000, source="DemoProp terms 2026-09 p.1",
                         verified=True)
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


# ---------------------------------------------------------------------------
# 34.2/34.15/34.18: the $9.99 service, and what refuses without it
# ---------------------------------------------------------------------------

def test_the_challenge_routes_refuse_an_institutional_operator_who_has_not_paid(
        client, monkeypatch):
    """§34.18, over the wire.

    The most likely way this feature gets wired up wrong is to treat an
    institutional subscription as if it included the service. It does not: the
    plan answers what an operator may do to the platform, the product answers
    what they have paid for, and only the second one may unblock challenge
    protection.
    """
    _purchased_but_no_risk(client, monkeypatch)
    payload = _full_policy_payload()

    response = client.post("/challenge/policies", json=payload)

    assert response.status_code == 403
    assert "challenge_management" in response.json()["detail"]


def test_reads_still_answer_when_nobody_has_paid(client, monkeypatch):
    """The panel must be able to say WHY an account is unprotected.

    Gating the reads would leave the operator with a 403 and no information,
    which is the worst of both: no service and no diagnosis.
    """
    _purchased_but_no_risk(client, monkeypatch)

    payload = client.get("/challenge/status").json()

    assert payload["ok"] is True
    assert payload["commercial"]["gate"]["active"] is False
    assert payload["commercial"]["price_usd"] == pytest.approx(9.99)


def test_an_expired_entitlement_stops_the_service_and_reports_the_state(
        client, monkeypatch):
    """§34.20: expiry is a state, and it takes the service with it.

    Not by deleting anything. The protection is not removed, so an account that
    was mid-challenge is not suddenly unmanaged by being late on a payment; the
    governor refuses new entries instead. This test only asserts the record and
    the refusal.
    """
    from governance.products import products

    _purchased_but_no_risk(client, monkeypatch)
    from governance.identity import identity
    uid = identity.principal_user_id()

    record = products.get(uid, "challenge_basic")
    assert record is None
    products.grant(uid, "challenge_basic", charge_id="ch_expiring", actor="test")
    record = products.get(uid, "challenge_basic")
    record.expires_at = time.time() - 1.0
    record.grace_until = time.time() - 1.0

    assert products.has(uid, "challenge_management") is False
    assert products.get(uid, "challenge_basic").state == "expired"
    assert client.post("/challenge/policies",
                       json=_full_policy_payload()).status_code == 403


def test_the_offset_and_the_weekend_terms_survive_registration(client, monkeypatch):
    """What the operator states must arrive at the stored policy intact."""
    from challenge.service import challenge_service as svc

    _operator(client, monkeypatch)
    payload = _full_policy_payload(
        server_utc_offset_hours={"value": 3.0, "source": "FTTrading-Server clock"},
        weekend_close_lead_minutes={"value": 120.0, "source": SOURCE},
        weekend_risk_multiplier={"value": 0.5, "source": SOURCE},
        margin_level_stop_out={"value": 95.0, "source": SOURCE},
        symbol_schedules={"BTCUSD": {"observed_close": 1790896131.0,
                                     "observed_at": 1790896000.0,
                                     "next_open": 1790934000.0,
                                     "source": "mt5 sessions document"}},
    )
    assert client.post("/challenge/policies", json=payload).status_code == 200

    stored = svc._registry.all_policies()[-1]
    assert stored.server_utc_offset_hours == 3.0
    assert stored.weekend_close_lead_minutes == 120.0
    assert stored.weekend_risk_multiplier == 0.5
    assert stored.margin_level_stop_out == 95.0
    assert stored.margin_level_stop_out_source == SOURCE
    assert stored.symbol_schedules["BTCUSD"]["observed_close"] == 1790896131.0
    # next_open is what bounds the reduced-risk window; losing it here would
    # leave a Friday reading that halves risk forever.
    assert stored.symbol_schedules["BTCUSD"]["next_open"] == 1790934000.0


def test_a_bare_offset_is_refused(client, monkeypatch):
    """A guessed offset is the permissive kind of wrong.

    The daily allowance resets on the provider's day, so an offset nobody
    recorded hands the account a fresh 3% at the wrong hour, on the one rule
    that ends accounts. A bare number is refused for the same reason the
    tournament rules are.
    """
    _operator(client, monkeypatch)
    resp = client.post("/challenge/policies",
                       json=_full_policy_payload(server_utc_offset_hours=3.0))
    assert resp.status_code == 400
    assert "source" in resp.json()["detail"]


def test_a_weekend_multiplier_above_one_is_refused(client, monkeypatch):
    """The reduction window must not be registerable as a risk increase.

    It would raise risk on exactly the days positions are held longest, and it
    is refused rather than clamped: a value that needs clamping is one the
    operator did not mean.
    """
    _operator(client, monkeypatch)
    resp = client.post("/challenge/policies", json=_full_policy_payload(
        weekend_risk_multiplier={"value": 1.5, "source": SOURCE}))
    assert resp.status_code == 400
    assert "above 1" in resp.json()["detail"]


def test_a_schedule_without_an_observed_close_is_refused(client, monkeypatch):
    """A close window with no close cannot be placed at all.

    Accepted, it would read as "already shut" for every symbol forever -- safe,
    but for the wrong reason and indistinguishable from a real holiday.
    """
    _operator(client, monkeypatch)
    resp = client.post("/challenge/policies", json=_full_policy_payload(
        symbol_schedules={"BTCUSD": {"observed_at": 1790896000.0}}))
    assert resp.status_code == 400
    assert "observed_close" in resp.json()["detail"]


def test_the_stopout_source_is_what_makes_it_confirmable(client, monkeypatch):
    """A stopout with no source cannot be source-confirmed, by construction.

    This is the whole reason the source is registered: without it the field
    exists but the confirmation that treats it as a real limit can never pass,
    and a limit that can never be confirmed is an internal floor with a
    broker's number on it.
    """
    from challenge.service import challenge_service as svc

    _operator(client, monkeypatch)
    assert client.post("/challenge/policies", json=_full_policy_payload(
        margin_level_stop_out={"value": 95.0, "source": SOURCE})).status_code == 200
    sourced = svc._registry.all_policies()[-1]
    assert sourced.margin_level_stop_out_source == SOURCE

    assert client.post("/challenge/policies", json=_full_policy_payload(
        policy_version="2026.10",
        margin_level_stop_out={"value": 95.0})).status_code == 400
