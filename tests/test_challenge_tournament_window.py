"""Tournament windows: the broker's clock, and what happens when one closes.

A tournament's start and end are stated in the broker's own time, and this suite
exists because the code used to compare them against the host's wall clock with
no offset anywhere in the expression. Nothing raised. The window simply resolved
differently depending on where the server happened to sit relative to UTC, and
the account was judged against a schedule it never entered.

The second half is the worse half. Resolving "no policy in force" and reading that
as "no tournament governs this account" is how enforcement switched itself off: a
tournament that ended on schedule stopped being graded, and its daily-loss and
book-risk caps went inactive, which is precisely backwards. Enforcement must not
expire because a schedule ran out. Only new entries stop.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from challenge import live as live_mod  # noqa: E402
from challenge.policy import ChallengePolicy, RuleValue  # noqa: E402
from challenge.registry import (  # noqa: E402
    CLOCK_UNKNOWN,
    WINDOW_CLOSED,
    broker_local_now,
)
from challenge.registry import PolicyRegistry  # noqa: E402
from core.state import AccountState, CanonicalState  # noqa: E402

SERVER = "FTTrading-Server"
PROVIDER = "For Traders"
PROGRAM = "Weekend Crypto Clash"


def _policy(**over) -> ChallengePolicy:
    """A fully specified policy; the window is what each test varies."""
    base = dict(
        provider=PROVIDER, program=PROGRAM, account_size=100_000.0,
        policy_version="test-v1", server=SERVER,
        profit_target=RuleValue(10000.0, source="doc"),
        daily_loss_limit=RuleValue(5000.0, source="doc"),
        max_drawdown=RuleValue(10000.0, source="doc"),
    )
    base.update(over)
    return ChallengePolicy(**base)


# -- the clock ----------------------------------------------------------

def test_a_window_with_no_registered_offset_is_not_evaluated_as_open():
    """Fail closed on an unknowable clock, rather than assume the host's.

    The alternative is to compare a broker's stated 13:00 start against the
    server's own wall clock. That is wrong by the offset, every day, silently.
    """
    reg = PolicyRegistry()
    reg.register(_policy(effective_from="2026-10-09T15:00:00",
                         effective_until="2026-10-12T15:00:00"))

    got = reg.resolve_ex(PROVIDER, PROGRAM, server=SERVER)

    assert got.resolved is False
    assert got.reason == CLOCK_UNKNOWN
    assert got.clock_known is False
    # "Cannot tell" is never reported as "open", which is the whole point.
    assert got.window_open is False


def test_registering_the_broker_offset_makes_the_window_answerable():
    """Same policy, same moment -- one field is the difference between them."""
    reg = PolicyRegistry()
    now = broker_local_now(0.0)
    reg.register(_policy(effective_from=(now - timedelta(hours=1)).isoformat(),
                         effective_until=(now + timedelta(hours=1)).isoformat(),
                         server_utc_offset_hours=0.0))

    got = reg.resolve_ex(PROVIDER, PROGRAM, server=SERVER)

    assert got.resolved is True
    assert got.window_open is True


def test_the_window_is_read_on_the_brokers_clock_not_the_hosts():
    """A window that is open in broker time is open, whatever the host thinks.

    `now_offset_hours` stands in for the registered broker offset. With it at
    +3 and the window straddling that broker-local moment, the policy resolves;
    the same query with the offset left unknown refuses, which is the difference
    this test exists to pin rather than to exercise incidentally.
    """
    reg = PolicyRegistry()
    broker_now = datetime.now(timezone.utc) + timedelta(hours=3)
    reg.register(_policy(
        effective_from=(broker_now - timedelta(hours=1)).replace(
            tzinfo=None).isoformat(),
        effective_until=(broker_now + timedelta(hours=1)).replace(
            tzinfo=None).isoformat(),
        server_utc_offset_hours=3.0))

    got = reg.resolve_ex(PROVIDER, PROGRAM, server=SERVER)

    assert got.resolved is True
    assert got.window_open is True


def test_window_start_is_inclusive_and_end_is_exclusive():
    """A tournament ending at 13:00 is not open at 13:00.

    Half-open intervals are the only reading under which consecutive windows can
    tile a schedule without either a gap (nobody governs that minute) or an
    overlap (two versions both claim it).
    """
    reg = PolicyRegistry()
    reg.register(_policy(effective_from="2026-10-09T15:00:00",
                         effective_until="2026-10-12T15:00:00",
                         server_utc_offset_hours=0.0))

    assert reg.resolve(PROVIDER, PROGRAM, on="2026-10-09T15:00:00",
                       server=SERVER) is not None
    assert reg.resolve(PROVIDER, PROGRAM, on="2026-10-12T14:59:59",
                       server=SERVER) is not None
    assert reg.resolve(PROVIDER, PROGRAM, on="2026-10-12T15:00:00",
                       server=SERVER) is None


def test_an_open_ended_policy_needs_no_clock_at_all():
    """No window means no schedule, so there is nothing for an offset to decide."""
    reg = PolicyRegistry()
    reg.register(_policy())

    got = reg.resolve_ex(PROVIDER, PROGRAM, server=SERVER)

    assert got.resolved is True
    assert got.reason != CLOCK_UNKNOWN


def test_ignoring_the_window_still_returns_the_governing_terms():
    """The question a bound account needs is "what am I judged by", not "is it on"."""
    reg = PolicyRegistry()
    reg.register(_policy(effective_from="2020-01-01T00:00:00",
                         effective_until="2020-01-02T00:00:00"))

    closed = reg.resolve_ex(PROVIDER, PROGRAM, server=SERVER,
                            ignore_window=True)

    assert closed.resolved is True
    assert closed.window_open is False
    assert closed.policy.policy_version == "test-v1"


def test_a_closed_window_says_so_rather_than_saying_nothing():
    """"Ended" and "never registered" are the same None and opposite problems."""
    reg = PolicyRegistry()
    reg.register(_policy(effective_from="2020-01-01T00:00:00",
                         effective_until="2020-01-02T00:00:00",
                         server_utc_offset_hours=0.0))

    got = reg.resolve_ex(PROVIDER, PROGRAM, server=SERVER)

    assert got.reason == WINDOW_CLOSED
    assert "2020-01-02" in got.detail


# -- what the decision path does with it -------------------------------

@pytest.fixture
def bound(monkeypatch):
    """An account explicitly bound to a tournament, with terms registered.

    Returns a builder so each test can pick the window it needs. The binding is
    what makes the account a tournament account; everything downstream about
    enforcement hangs off that one claim.
    """
    import challenge.service as service_mod

    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", PROVIDER)
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROGRAM", raising=False)

    def build(effective_from=None, effective_until=None, offset=0.0,
              version="test-v1"):
        svc = service_mod.challenge_service
        saved = list(svc._program_bindings)
        saved_pol = list(svc._registry.all_policies())
        svc._program_bindings.clear()
        for p in svc._registry.all_policies():
            svc._registry._policies.get(
                svc._registry._slot(p.provider, p.program), []).remove(p)
        svc.bind_program("4242", provider=PROVIDER, program=PROGRAM,
                         server=SERVER, source="test operator claim")
        if effective_from is not None or effective_until is not None:
            svc._registry.register(_policy(
                effective_from=effective_from, effective_until=effective_until,
                server_utc_offset_hours=offset, policy_version=version))

        store = CanonicalState()
        store.account = AccountState(login=4242, broker="", server=SERVER,
                                     balance=100_000.0, equity=100_000.0)

        def restore():
            svc._program_bindings.clear()
            svc._program_bindings.extend(saved)
            for p in saved_pol:
                svc._registry._policies.setdefault(
                    svc._registry._slot(p.provider, p.program), []).append(p)

        return store, restore

    return build


def test_a_tournament_that_has_ended_still_governs_its_account(bound):
    """The core regression: a closed window must not read as an unmanaged account.

    Before this, `live_policy()` went through the window and returned None once
    the tournament ended, which set `managed=False`, which switched the daily-loss
    and book-risk caps off. Enforcement disappearing at the end of a tournament is
    the opposite of what ending a tournament means.
    """
    store, restore = bound(effective_from="2020-10-01T00:00:00",
                           effective_until="2020-10-02T00:00:00")
    try:
        status = live_mod.tournament_status(store)

        assert status.applies is True
        assert status.managed is True
        assert status.policy is not None
        assert status.window_open is False
        assert live_mod.is_managed(store) is True
    finally:
        restore()


def test_a_closed_window_refuses_a_new_entry(bound):
    """Entries stop; grading does not."""
    store, restore = bound(effective_from="2020-10-01T00:00:00",
                           effective_until="2020-10-02T00:00:00")
    try:
        status = live_mod.tournament_status(store)

        assert status.can_open_new_position is False
        assert status.refusal_reason() == "tournament_window_closed"
        assert live_mod.can_open_new_position(store) is False
    finally:
        restore()


def test_an_open_window_admits_a_new_entry(bound):
    store, restore = bound(effective_from="2020-10-01T00:00:00",
                           effective_until="2099-10-02T00:00:00")
    try:
        status = live_mod.tournament_status(store)

        assert status.can_open_new_position is True
        assert status.refusal_reason() is None
    finally:
        restore()


def test_an_unregistered_clock_refuses_entries_rather_than_guessing(bound):
    """Terms known, schedule unknowable: still a refusal.

    This is the case a naive "the policy exists, so allow it" fix would wave
    through. The account's rules are perfectly well registered; what is missing
    is the offset that says whether the tournament is running, and an open window
    assumed rather than established is not a fact about the account.
    """
    store, restore = bound(effective_from="2020-10-01T00:00:00",
                           effective_until="2099-10-02T00:00:00", offset=None)
    try:
        status = live_mod.tournament_status(store)

        # The terms themselves resolved -- this is not a terms gap.
        assert status.managed is True
        assert status.policy is not None
        # What cannot be established is whether the tournament is open.
        assert status.clock_known is False
        assert status.can_open_new_position is False
        assert status.refusal_reason() == "window_clock_unknown"
    finally:
        restore()


def test_a_binding_with_no_registered_terms_refuses_entries(bound):
    """§34.6: an unanswered question about an account's terms restricts.

    The binding is a sourced claim that this login is in this tournament. Having
    no rules for it is a gap in the registration, and trading through the gap is
    how an account gets graded against terms nobody wrote down.
    """
    import challenge.service as service_mod

    svc = service_mod.challenge_service
    saved = list(svc._program_bindings)
    saved_pol = list(svc._registry.all_policies())
    svc._program_bindings.clear()
    for p in saved_pol:
        rows = svc._registry._policies.get(
            svc._registry._slot(p.provider, p.program), [])
        if p in rows:
            rows.remove(p)
    svc.bind_program("4242", provider=PROVIDER, program=PROGRAM,
                     server=SERVER, source="test operator claim")
    store = CanonicalState()
    store.account = AccountState(login=4242, broker="", server=SERVER,
                                 balance=100_000.0, equity=100_000.0)
    try:
        status = live_mod.tournament_status(store)

        assert status.applies is True
        assert status.policy is None
        assert status.can_open_new_position is False
        assert status.refusal_reason() == "policy_unknown"
    finally:
        svc._program_bindings.clear()
        svc._program_bindings.extend(saved)
        for p in saved_pol:
            svc._registry._policies.setdefault(
                svc._registry._slot(p.provider, p.program), []).append(p)


def test_a_deployment_default_with_no_policies_is_not_a_tournament(monkeypatch):
    """A stale env default must not halt an ordinary demo deployment.

    `TRADERAIG_CHALLENGE_PROGRAM` is a fallback string, not an assertion that
    every account on the host is in that tournament. A deployment that sets it
    while registering no policies at all is running plain accounts, and reading
    it as an ungraded tournament would halt everything.
    """
    import challenge.service as service_mod

    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", PROVIDER)
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROGRAM", PROGRAM)
    svc = service_mod.challenge_service
    saved = list(svc._program_bindings)
    saved_pol = list(svc._registry.all_policies())
    svc._program_bindings.clear()
    for p in saved_pol:
        rows = svc._registry._policies.get(
            svc._registry._slot(p.provider, p.program), [])
        if p in rows:
            rows.remove(p)
    store = CanonicalState()
    store.account = AccountState(login=777, broker="", server=SERVER,
                                 balance=10_000.0, equity=10_000.0)
    try:
        status = live_mod.tournament_status(store)

        assert status.applies is False
        assert status.can_open_new_position is True
        assert live_mod.is_managed(store) is False
    finally:
        svc._program_bindings.clear()
        svc._program_bindings.extend(saved)
        for p in saved_pol:
            svc._registry._policies.setdefault(
                svc._registry._slot(p.provider, p.program), []).append(p)


def test_an_unresolvable_account_is_left_completely_alone(monkeypatch):
    """No provider, no binding, no policy: an ordinary account. Untouched."""
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROVIDER", raising=False)
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROGRAM", raising=False)
    store = CanonicalState()
    store.account = AccountState(login=999, broker="", server=SERVER,
                                 balance=10_000.0, equity=10_000.0)

    status = live_mod.tournament_status(store)

    assert status.applies is False
    assert status.can_open_new_position is True


def test_a_failure_to_resolve_refuses_rather_than_assumes(monkeypatch):
    """"I could not find out" is not evidence of "there is nothing there"."""
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", PROVIDER)
    import challenge.service as service_mod

    def boom(*a, **k):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(service_mod.challenge_service, "resolve_account_program",
                        boom)
    store = CanonicalState()
    store.account = AccountState(login=4242, broker="", server=SERVER,
                                 balance=100_000.0, equity=100_000.0)

    status = live_mod.tournament_status(store)

    assert status.applies is True
    assert status.can_open_new_position is False


# -- the execution gate itself ----------------------------------------

def _governor(store: CanonicalState):
    from core.state import MarketState
    from risk.governor import RiskGovernor

    store.upsert_market(MarketState(
        symbol="XAUUSD", bid=2000.0, ask=2000.5, spread=0.5,
        last_price=2000.25, last_tick_time=1.0, tick_size=0.01,
        tick_value=1.0, volume_min=0.01, volume_step=0.01, volume_max=100.0))
    return RiskGovernor(state_ref=store)


def _candidate():
    from core.contracts import TradeDirection
    from decision.candidate import TradeCandidate

    return TradeCandidate(
        candidate_id="c1", thesis_id="t1", symbol="XAUUSD",
        direction=TradeDirection.LONG, entry=2000.0, stop_loss=1990.0,
        take_profit=2020.0, size=0.1, risk_reward=2.0, confidence=0.8)


def test_the_governor_vetoes_an_entry_into_a_closed_tournament(bound):
    """The refusal has to reach the only component allowed to say no.

    Asserting on `tournament_status()` alone would prove the answer exists while
    leaving open whether anything asks. The Governor is where a trade is actually
    decided, so the window has to be visible there.
    """
    from risk.governor import RiskDecisionKind

    store, restore = bound(effective_from="2020-10-01T00:00:00",
                           effective_until="2020-10-02T00:00:00")
    try:
        decision = _governor(store).veto_reason(_candidate())

        assert decision.kind == RiskDecisionKind.VETOED
        assert "tournament window" in decision.reason
    finally:
        restore()


def test_the_governor_still_applies_the_caps_to_a_closed_tournament(bound):
    """Enforcement outlives the schedule; only entries stop.

    Asserted on the cap check itself, because that is where the failure would be
    invisible: the entry is refused by the window either way, so a decision-level
    assertion passes whether or not the 2% book cap also ran. This asks the cap
    directly.
    """
    store, restore = bound(effective_from="2020-10-01T00:00:00",
                           effective_until="2020-10-02T00:00:00")
    try:
        gov = _governor(store)
        reasons: list = []
        cap = gov._check_total_risk_cap(_candidate(), reasons)

        assert cap["detail"]["active"] is True
        assert cap["detail"]["cap_fraction"] == pytest.approx(0.02)
    finally:
        restore()


def test_an_open_tournament_reaches_the_normal_challenge_evaluation(bound):
    """The window gate must not swallow the ordinary challenge path.

    With no entitlement behind it, an open tournament account still has to be
    refused -- and refused by the entitlement check, not by the window. A test
    that only asserted "vetoed" would pass if the window gate were vetoing
    everything unconditionally.
    """
    from risk.governor import RiskDecisionKind

    store, restore = bound(effective_from="2020-10-01T00:00:00",
                           effective_until="2099-10-02T00:00:00")
    try:
        decision = _governor(store).veto_reason(_candidate())

        assert decision.kind == RiskDecisionKind.VETOED
        assert "tournament window" not in decision.reason
        assert "challenge management not entitled" in decision.reason
    finally:
        restore()


# -- what the operator can see -----------------------------------------

def test_the_window_endpoint_reports_the_closed_window_with_its_reason(monkeypatch, bound):
    """An operator has to be able to tell "ended" from "never registered".

    Both arrive as a refusal on the trading side, and they are opposite problems
    at the keyboard: one needs a new programme bound, the other needs nothing.
    Asserted over HTTP because the console reads this endpoint and nothing else.
    """
    from fastapi.testclient import TestClient

    from operations.api import app, state as live_state

    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", PROVIDER)
    _, restore = bound(effective_from="2020-10-01T00:00:00",
                       effective_until="2020-10-02T00:00:00")
    held = dict(live_state.account.__dict__)
    live_state.account = AccountState(login=4242, broker="", server=SERVER,
                                      balance=100_000.0, equity=100_000.0)
    try:
        body = TestClient(app).get("/challenge/window").json()

        assert body["applies"] is True
        assert body["managed"] is True
        assert body["window_open"] is False
        assert body["can_open_new_position"] is False
        assert body["refusal_reason"] == "tournament_window_closed"
        assert body["closes_at"] == "2020-10-02T00:00:00"
        assert body["detail"]
    finally:
        live_state.account = AccountState(**held)
        restore()


def test_the_window_endpoint_is_quiet_for_an_ordinary_account(monkeypatch):
    """No tournament means no window, and saying so must not invent a schedule."""
    from fastapi.testclient import TestClient

    from operations.api import app, state as live_state

    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROVIDER", raising=False)
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROGRAM", raising=False)
    held = dict(live_state.account.__dict__)
    live_state.account = AccountState(login=999, broker="", server=SERVER,
                                      balance=10_000.0, equity=10_000.0)
    try:
        body = TestClient(app).get("/challenge/window").json()

        assert body["applies"] is False
        assert body["window_open"] is True
        assert body["can_open_new_position"] is True
        assert body["opens_at"] is None
    finally:
        live_state.account = AccountState(**held)
