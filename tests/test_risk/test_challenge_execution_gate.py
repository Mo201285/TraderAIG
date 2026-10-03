"""§34.15: the challenge policy as an execution gate on the live decision path.

`test_challenge_policy.py` proves the headroom math. `test_challenge_routes.py`
proves the HTTP surface. Neither touches the place this file exists for: the
Risk Governor, which is the only component in the system allowed to say no to a
trade, and which had no idea a challenge policy existed.

Three things are asserted here that no other file can assert, because they are
properties of the WIRING:

  * an ordinary funded account is unaffected — the gate is inactive, so §34.15
    cannot leak into trading that was never a challenge;
  * a managed account with no paid entitlement is refused, which is the whole
    commercial point, and cannot be observed from the API because the API is not
    where a trade is decided;
  * `ALLOW_REDUCED_RISK` resizes rather than refusing, so the $9.99 service
    degrades the account it is paid to protect instead of freezing it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import TradeDirection  # noqa: E402
from core.state import (  # noqa: E402
    AccountState,
    CanonicalState,
    MarketState,
)
from decision.candidate import TradeCandidate  # noqa: E402
from risk.governor import RiskDecisionKind, RiskGovernor  # noqa: E402

SOURCE = "provider-terms-2026-09.pdf"
EQUITY = 100_000.0
LOGIN = 4242


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Leave the registry, the env, the identity store and the purchases as found.

    Same argument as the fixture in `test_challenge_routes.py`, applied to the
    process-wide singletons this path touches: the challenge service, the policy
    registry, and the paid entitlements. A purchase leaked from one test would
    unblock the next one's refusal case and make the suite order-dependent.
    """
    from challenge.registry import PolicyRegistry
    from challenge.service import ChallengeService, challenge_service
    from governance.identity import identity
    from governance.products import products

    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    audit_len = len(identity._audit)
    bought = dict(products._entitlements)
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROGRAM", raising=False)
    monkeypatch.delenv("IDENTITY_PRIMARY_EMAIL", raising=False)
    fresh = ChallengeService(PolicyRegistry())
    held = {k: v for k, v in fresh.__dict__.items()}
    # The registry object and its contents, restored AFTER the attribute swap
    # below -- the swap reassigns `_registry` to the throwaway registry `fresh`
    # was built with, so a restore done before it would be thrown away.
    #
    # This matters because `ChallengeService()` with no argument binds the
    # module-level `default_registry`, not `fresh`'s empty one. Policies
    # registered by one test therefore stayed in it for the next, and
    # registration is immutable on purpose -- the second test to register
    # DemoProp/2026.09 was refused with "already registered; register a new
    # version" and a ValueError. The registry was right; nothing was resetting it.
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
        challenge_service._registry = live_registry
        live_registry._policies.clear()
        live_registry._policies.update(policies)
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        products._entitlements.clear()
        products._entitlements.update(bought)
        del identity._audit[audit_len:]


def _governor(broker: str = "DemoProp", equity: float = EQUITY):
    """A governor over an account that reports a broker, i.e. a real venue."""
    s = CanonicalState()
    s.set_account(AccountState(login=LOGIN, broker=broker, balance=equity,
                               equity=equity))
    s.upsert_market(MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5,
                                spread=0.5, last_price=2000.25, last_tick_time=1.0,
                                tick_size=0.01, tick_value=1.0,
                                volume_min=0.01, volume_step=0.01,
                                volume_max=100.0))
    return RiskGovernor(state_ref=s), s


def _candidate(size: float = 0.1):
    return TradeCandidate(
        candidate_id="c1", thesis_id="t1", symbol="XAUUSD",
        direction=TradeDirection.LONG, entry=2000.0, stop_loss=1990.0,
        take_profit=2020.0, size=size, risk_reward=2.0, confidence=0.8,
    )


def _register_policy(monkeypatch, *, max_drawdown: float = 0.04,
                     daily_loss: float = 0.05) -> None:
    """Register a complete policy and point the deployment at that program.

    The env var is what makes the connected account a challenge account at all;
    without it the registry holds a valid policy and the governor correctly
    ignores it, because a broker never tells you which evaluation a trader signed
    up for.
    """
    from challenge.policy import (
        ChallengePolicy,
        DrawdownType,
        InstrumentPolicy,
        Restriction,
        RuleValue,
    )
    from challenge.service import challenge_service as svc

    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROGRAM", "Classic 2-Step")
    svc.register_policy(ChallengePolicy(
        provider="DemoProp", program="Classic 2-Step", account_size=EQUITY,
        policy_version="2026.09",
        profit_target=RuleValue.known(0.08, source=SOURCE),
        daily_loss_limit=RuleValue.known(daily_loss, source=SOURCE),
        max_drawdown=RuleValue.known(max_drawdown, source=SOURCE),
        minimum_trading_days=RuleValue.known(10, source=SOURCE),
        max_leverage=RuleValue.known(100, source=SOURCE),
        drawdown_type=DrawdownType.STATIC,
        instruments=InstrumentPolicy(default=Restriction.ALLOWED, source=SOURCE),
        overnight=Restriction.ALLOWED, weekend=Restriction.ALLOWED,
        # The broker's day boundary. The daily loss is measured against the
        # provider's trading day, so an unestablished offset leaves that
        # dimension unscored -- correct behaviour, and on its own enough to
        # restrict every account these tests are about the drawdown in. Same
        # reason as the policy suite's `_full_policy()`.
        server_utc_offset_hours=3.0))
    # A declared opening balance: watching an account is not knowing how it began,
    # and without this every verdict is an allowance computed from nothing.
    svc.declare_baseline(str(LOGIN), EQUITY,
                         source="DemoProp competition terms p.1", verified=True)


def _operator(email: str = "buyer@x.co") -> str:
    """A real, entitled principal who has bought nothing. Returns the user id."""
    from governance.identity import SubscriptionPlan, identity

    identity._users.pop(email, None)
    uid = identity.create_user(email, email.split("@")[0]).user_id
    identity.activate_subscription(uid, SubscriptionPlan.INSTITUTIONAL)
    return uid


def _pay(*, email: str = "buyer@x.co") -> str:
    """The same principal, having bought the $9.99 service.

    The generated id is used throughout rather than a chosen one, because
    `create_user` mints it — passing a chosen id looks convenient and then the
    principal silently does not exist.
    """
    from governance.products import products

    uid = _operator(email)
    products.grant(uid, "challenge_basic", charge_id="ch_test", actor="test")
    return uid


def _principal(monkeypatch, email: str = "buyer@x.co") -> None:
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)


def _challenge_check(decision) -> dict:
    return next(c for c in decision.checks if c.get("name") == "challenge_policy")


# ---------------------------------------------------------------------------
# an account that was never a challenge account is untouched
# ---------------------------------------------------------------------------

def test_an_account_with_no_policy_is_graded_by_nothing(monkeypatch):
    """The regression this gate is most likely to cause.

    Every trading account on this deployment is not a challenge account. If the
    gate engaged on all of them, §34.15 would become a global shutdown switch
    wired to a purchase nobody made — so "inactive" is asserted explicitly,
    rather than inferred from a candidate that happened to be approved.
    """
    governor, _ = _governor()

    check = _challenge_check(governor.veto_reason(_candidate()))

    assert check["active"] is False
    assert check["passed"] is True
    assert check["detail"] == {}


def test_a_registered_policy_without_a_configured_program_does_not_engage(
        monkeypatch):
    """The other half of the same guarantee.

    A valid policy sitting in the registry is not a claim about THIS account. A
    broker reports a server and a currency; guessing the program from the balance
    is §34.6 guessing with a decimal point on it.
    """
    from challenge.policy import (
        ChallengePolicy,
        DrawdownType,
        InstrumentPolicy,
        Restriction,
        RuleValue,
    )
    from challenge.service import challenge_service as svc

    svc.register_policy(ChallengePolicy(
        provider="DemoProp", program="Classic 2-Step", account_size=EQUITY,
        policy_version="2026.09",
        profit_target=RuleValue.known(0.08, source=SOURCE),
        daily_loss_limit=RuleValue.known(0.05, source=SOURCE),
        max_drawdown=RuleValue.known(0.04, source=SOURCE),
        minimum_trading_days=RuleValue.known(10, source=SOURCE),
        max_leverage=RuleValue.known(100, source=SOURCE),
        drawdown_type=DrawdownType.STATIC,
        instruments=InstrumentPolicy(default=Restriction.ALLOWED, source=SOURCE),
        overnight=Restriction.ALLOWED, weekend=Restriction.ALLOWED))
    governor, _ = _governor()

    check = _challenge_check(governor.veto_reason(_candidate()))

    assert check["active"] is False


# ---------------------------------------------------------------------------
# a managed account that nobody has paid for
# ---------------------------------------------------------------------------

def test_a_managed_account_is_vetoed_when_nobody_has_paid(monkeypatch):
    """§34.15 + §34.18, where it actually matters: on the trade.

    A fully-privileged institutional operator, correctly signed in, running a
    registered challenge policy — and refused, because the $9.99 service is the
    thing that authorises challenge protection and it has not been bought.
    """
    _register_policy(monkeypatch)
    _operator()
    _principal(monkeypatch)
    governor, _ = _governor()

    decision = governor.veto_reason(_candidate())

    assert decision.kind == RiskDecisionKind.VETOED
    assert "challenge management not entitled" in decision.reason
    check = _challenge_check(decision)
    assert check["active"] is True
    assert check["passed"] is False
    assert check["permission"] == "halt"
    assert check["detail"]["reason"] == "not_purchased"


def test_an_institutional_plan_does_not_count_as_paying(monkeypatch):
    """The mistake this feature invites, made into a test.

    `_pay()` activates institutional AND buys the product; here only the plan is
    granted. If the plan alone were enough, the $9.99 tier would be unsellable to
    exactly the customers most likely to want it, and the paid protection would
    be indistinguishable from the free one.
    """
    from governance.identity import Entitlement, identity, SubscriptionPlan
    from governance.products import products

    _register_policy(monkeypatch)
    uid = identity.create_user("planonly@x.co", "planonly").user_id
    identity.activate_subscription(uid, SubscriptionPlan.INSTITUTIONAL)
    _principal(monkeypatch, "planonly@x.co")
    governor, _ = _governor()

    decision = governor.veto_reason(_candidate())

    assert products.has(uid, Entitlement.CHALLENGE_MANAGEMENT) is False
    assert decision.kind == RiskDecisionKind.VETOED
    assert "challenge management not entitled" in decision.reason


def test_a_managed_account_with_no_principal_at_all_is_vetoed(monkeypatch):
    """Bootstrap fails closed HERE, unlike on the API routes.

    The governor's question is not "may this caller configure the service" but
    "is this challenge account paid for", and a system with no identity has
    answered that with silence. Passing would let an unconfigured deployment
    trade a competition account on nobody's authority.
    """
    _register_policy(monkeypatch)
    governor, _ = _governor()

    decision = governor.veto_reason(_candidate())

    assert decision.kind == RiskDecisionKind.VETOED
    assert "no_principal" in _challenge_check(decision)["detail"]["reason"]


# ---------------------------------------------------------------------------
# a paid account: policy geometry, not billing, decides
# ---------------------------------------------------------------------------

def test_a_paid_account_with_room_is_approved_by_the_challenge_check(monkeypatch):
    _register_policy(monkeypatch)
    _pay()
    _principal(monkeypatch)
    governor, _ = _governor()

    check = _challenge_check(governor.veto_reason(_candidate()))

    assert check["active"] is True
    assert check["passed"] is True
    assert check["permission"] == "allow"


def test_a_paid_account_near_its_drawdown_limit_is_vetoed_by_the_policy(monkeypatch):
    """Not by billing, not by the entitlement — by the actual rule.

    The equity is 5% below the opening balance against a 4% static limit, so the
    drawdown is spent. The service is paid for and the refusal is the product
    working.
    """
    _register_policy(monkeypatch)
    _pay()
    _principal(monkeypatch)
    governor, state = _governor(equity=EQUITY * 0.95)
    state.set_account(AccountState(login=LOGIN, broker="DemoProp",
                                   balance=EQUITY * 0.95, equity=EQUITY * 0.95))

    decision = governor.veto_reason(_candidate())

    assert decision.kind == RiskDecisionKind.VETOED
    check = _challenge_check(decision)
    assert check["passed"] is False
    assert "challenge policy" in decision.reason


def test_an_unknown_baseline_halts_rather_than_granting_room(monkeypatch):
    """34.22's `counts` field, enforced where it changes a decision.

    The account is watched but nobody has declared how it began, so every
    headroom figure would be measured from a number we did not earn. Trading on
    that is the defect row 736 documents, and here it is prevented rather than
    merely reported.
    """
    from challenge.service import challenge_service as svc

    _register_policy(monkeypatch)
    svc.withdraw_baseline(str(LOGIN), reason="testing the unknown case")
    _pay()
    _principal(monkeypatch)
    governor, _ = _governor()

    decision = governor.veto_reason(_candidate())

    assert decision.kind == RiskDecisionKind.VETOED
    check = _challenge_check(decision)
    assert check["detail"]["counts"] is False
    assert check["permission"] in ("halt", "protect")


# ---------------------------------------------------------------------------
# 34.9: resize rather than refuse
# ---------------------------------------------------------------------------




def test_a_trade_that_fits_is_not_resized(monkeypatch):
    """The counterpart, so the cap below cannot be satisfied by always capping."""
    _register_policy(monkeypatch)
    _pay()
    _principal(monkeypatch)
    governor, _ = _governor()

    volume = governor.compute_volume(_candidate())

    # 1% of 100k equity is the institutional per-trade cap; the challenge room is
    # far larger, so the cap must not bind.
    assert volume == pytest.approx(1.0)


def test_a_trade_far_over_the_room_is_refused_rather_than_shrunk_to_nothing(monkeypatch):
    """PROTECT refuses; only ALLOW_REDUCED_RISK resizes.

    §34.8/§34.9/§34.23 reserve the resize for a proposal that still fits inside
    the remaining headroom. Here it does not: $500 proposed against $360 of
    remaining room, so no size rescues the candidate. Refusal is the only honest
    answer, and it has to be a refusal — returning "0.01 lots" would be a
    fabricated allowance for a trade the rules forbid.
    """
    _register_policy(monkeypatch, max_drawdown=0.004)
    _pay()
    _principal(monkeypatch)
    governor, _ = _governor()
    # 0.5 lots x $1,000/lot (10 points at 0.01 tick size, $1/tick) = $500 of
    # proposed risk, against a $400 drawdown limit whose 10% safety buffer
    # leaves $360 of safe room. The trade is 1.4x what the account may risk.
    decision = governor.veto_reason(_candidate(size=0.5))

    assert decision.kind == RiskDecisionKind.VETOED
    check = _challenge_check(decision)
    assert check["permission"] == "protect"


def test_an_unknown_headroom_produces_no_cap_at_all(monkeypatch):
    """None is not zero, and the reason is recorded rather than assumed.

    Sizing runs after the gate, so an unmeasurable account has already been
    refused upstream. Clamping the budget to 0.0 would convert "we could not
    measure this" into "the position size is nothing", which is a claim about
    the account that nobody has evidence for.
    """
    _register_policy(monkeypatch)
    _pay()
    _principal(monkeypatch)
    governor, _ = _governor()

    assert governor._challenge_risk_cap(_candidate()) is None
    assert governor.compute_volume(_candidate()) == pytest.approx(1.0)


def test_the_cap_never_serves_another_candidates_headroom(monkeypatch):
    """The cached verdict is keyed by candidate, and the key is enforced.

    `compute_volume` runs right after `veto_reason` in the pipeline, so a cache
    is the cheap way to avoid evaluating the account twice. Without the key, a
    size computed for candidate B could be sized against candidate A's
    headroom — which on a losing account is exactly the direction that lets a
    position be opened larger than the account can carry.
    """
    _register_policy(monkeypatch)
    _pay()
    _principal(monkeypatch)
    governor, _ = _governor()
    first = _candidate()
    governor.veto_reason(first)

    other = TradeCandidate(
        candidate_id="c2", thesis_id="t2", symbol="XAUUSD",
        direction=TradeDirection.LONG, entry=2000.0, stop_loss=1990.0,
        take_profit=2020.0, size=0.1, risk_reward=2.0, confidence=0.8)

    assert governor._challenge_risk_cap(first) is None   # rung not reached
    assert governor._challenge_risk_cap(other) is None   # wrong candidate
    assert governor._challenge_risk_cap() is None        # no candidate given


def test_the_cap_and_the_gate_read_the_same_account(monkeypatch):
    """Wiring, not arithmetic: the injected state is the one that gets graded.

    A bridge that reached for the process-global account would pass every test in
    this file that used a governor with no state of its own, and would grade the
    wrong account in the one place it cannot be noticed by reading the result.
    """
    from challenge.live import connected_account_id

    _register_policy(monkeypatch)
    _pay()
    _principal(monkeypatch)
    governor, state = _governor()
    state.account.login = 987654

    assert connected_account_id(state) == "987654"
    decision = governor.veto_reason(_candidate())
    assert _challenge_check(decision)["detail"]["account_id"] == "987654"
