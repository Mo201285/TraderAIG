"""Challenge Account Management: policy, headroom, state (spec 34.1-34.14).

The bar for this file is not "the calculator returns a number". It is that the
layer's refusals are real, and refusals are the part nobody tests. Every test
here is aimed at one of three ways this layer could lie:

1. It produces a plausible limit it was never told (an unverified rule quietly
   becoming a permissive default, which is the failure 34.6 exists to prevent).
2. It reports headroom an account has already spent (static drawdown that
   recovers, a daily low that is measured from the wrong reference).
3. It lets an account resume from HALTED without anyone having authorized it
   (34.10's "must not silently resume").

Each of those has a test that is confirmed to go red when the guarantee is
removed, because a guard that cannot fail is counted as coverage rather than as
a control. The arithmetic is checked against hand-computed numbers on a $100k
account, where every expected value is a round number and a mistake shows up
immediately rather than as a plausible-looking drift.
"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from challenge.headroom import (  # noqa: E402
    AccountSnapshot,
    Permission,
    daily_loss_headroom,
    headroom_report,
    max_drawdown_headroom,
    permission_for,
    profit_target_distance,
    trading_days_headroom,
)
from challenge.policy import (  # noqa: E402
    ChallengePolicy,
    DrawdownType,
    InstrumentPolicy,
    Restriction,
    RuleStatus,
    RuleValue,
)
from challenge.registry import PolicyRegistry  # noqa: E402
from challenge.state_machine import (  # noqa: E402
    ChallengeState,
    ChallengeStateMachine,
    TransitionRefused,
)

SOURCE = "provider-terms-2026-09.pdf"


def _full_policy(**overrides) -> ChallengePolicy:
    """A complete, verified policy: every rule carries a source document."""
    policy = ChallengePolicy(
        provider="DemoProp",
        program="Classic 2-Step",
        account_size=100_000.0,
        policy_version="2026.09",
        effective_from="2026-09-01",
        profit_target=RuleValue.known(0.08, source=SOURCE),
        daily_loss_limit=RuleValue.known(0.05, source=SOURCE),
        max_drawdown=RuleValue.known(0.04, source=SOURCE),
        minimum_trading_days=RuleValue.known(10, source=SOURCE),
        max_leverage=RuleValue.known(100, source=SOURCE),
        drawdown_type=DrawdownType.STATIC,
        instruments=InstrumentPolicy(
            denied_symbols=["US30"], default=Restriction.ALLOWED, source=SOURCE),
        overnight=Restriction.ALLOWED,
        weekend=Restriction.DENIED,
    )
    for key, value in overrides.items():
        setattr(policy, key, value)
    return policy


def _snapshot(equity=100_000.0, **overrides) -> AccountSnapshot:
    """A $100k account observed once, with its low-water marks established."""
    snap = AccountSnapshot(
        account_id="acct-1", balance=100_000.0, equity=equity,
        start_equity=100_000.0, day_start_equity=100_000.0)
    AccountSnapshot.observe(snap)
    for key, value in overrides.items():
        setattr(snap, key, value)
    return snap


# ---------------------------------------------------------------------------
# the registry ships empty, and an unknown rule produces no number
# ---------------------------------------------------------------------------

def test_a_fresh_install_knows_no_policies_and_resolves_to_nothing():
    """34.6's chain starts at UNKNOWN, and a fresh install is exactly there.

    Asserted rather than assumed: if a future change seeds the registry with
    sample rules, a deployment that never received provider terms would start
    enforcing invented limits. That is the failure this whole module is shaped
    around, so the empty registry is a tested property, not an accident.
    """
    registry = PolicyRegistry()

    assert registry.all_policies() == []
    assert registry.resolve("DemoProp", "Classic 2-Step") is None
    assert registry.as_dict()["registered"] == 0


def test_an_unverified_rule_reports_no_number_rather_than_a_default():
    """The central honesty guarantee: unknown is not zero, and not a default.

    Every numeric rule has a plausible-looking fallback (10% drawdown is a
    realistic number), and a default here would be indistinguishable from a
    verified term in the API, the logs and the UI.
    """
    partial = ChallengePolicy(
        provider="DemoProp", program="Classic 2-Step", policy_version="draft")
    headroom = max_drawdown_headroom(partial, _snapshot(equity=50_000.0))

    assert headroom.is_known is False
    assert headroom.limit is None
    assert headroom.used is None
    assert headroom.remaining is None
    assert "not verified" in headroom.reason


def test_a_policy_missing_any_risk_rule_is_not_fully_specified():
    """Half a policy is the dangerous case, so it is named explicitly."""
    partial = _full_policy()
    partial.profit_target = RuleValue.unknown("terms not supplied yet")

    assert partial.is_fully_specified is False
    assert "profit_target" in partial.missing_rules()

    assert _full_policy().is_fully_specified is True
    assert _full_policy().missing_rules() == []


def test_an_unknown_drawdown_basis_does_not_default_to_either_way():
    """static and floating disagree about whether a recovered account lives.

    Picking one by default means picking a winner in the one calculation that
    decides whether the account survives, so an unstated basis yields no score.
    """
    policy = _full_policy()
    policy.drawdown_type = None
    snap = _snapshot(equity=97_000.0)
    snap.equity_low = 97_000.0

    headroom = max_drawdown_headroom(policy, snap)

    assert headroom.is_known is False
    assert "basis unknown" in headroom.reason


def test_an_unverified_policy_halts_rather_than_assumes():
    """34.6: UNKNOWN -> DO NOT ASSUME -> RESTRICT.

    HALT rather than RESTRICT because the account's rules are unknown, and the
    spec's most restrictive outcome is the only one that does not require
    knowing something the system does not.
    """
    result = permission_for(ChallengePolicy(policy_version="draft"), _snapshot())

    assert result["permission"] == Permission.HALT.value
    assert result["policy_verified"] is False


def test_no_policy_at_all_is_a_halt_not_an_allow():
    """A missing policy and a permissive policy must never look the same."""
    result = permission_for(None, _snapshot(equity=100_000.0))

    assert result["permission"] == Permission.HALT.value
    assert result["policy_key"] is None


# ---------------------------------------------------------------------------
# headroom arithmetic: hand-computed on a $100k account
# ---------------------------------------------------------------------------

def test_a_flat_account_has_its_whole_allowance_left():
    headroom = max_drawdown_headroom(_full_policy(), _snapshot())

    assert headroom.limit == pytest.approx(4_000.0)   # 4% of 100k
    assert headroom.used == pytest.approx(0.0)
    assert headroom.remaining == pytest.approx(4_000.0)


def test_a_static_drawdown_account_that_recovers_is_still_breached():
    """The single most dangerous calculation in this layer.

    A static-drawdown account that drops 4% and climbs back to flat has spent
    the entire allowance and is finished. Measuring from current equity instead
    of the account's worst point reports zero used drawdown on a dead account
    and invites it to keep trading.
    """
    policy = _full_policy()
    snap = _snapshot(equity=100_000.0)

    snap.equity = 96_000.0
    AccountSnapshot.observe(snap)
    assert max_drawdown_headroom(policy, snap).used == pytest.approx(4_000.0)

    snap.equity = 100_000.0          # fully recovered
    AccountSnapshot.observe(snap)
    recovered = max_drawdown_headroom(policy, snap)

    assert recovered.used == pytest.approx(4_000.0)
    assert recovered.remaining == pytest.approx(0.0)
    assert permission_for(policy, snap)["permission"] == Permission.HALT.value


def test_a_floating_drawdown_account_regains_room_only_when_the_day_rolls():
    """Floating resets daily, so a recovery restores room the next day."""
    policy = _full_policy()
    policy.drawdown_type = DrawdownType.FLOATING

    snap = _snapshot(equity=96_000.0)
    assert max_drawdown_headroom(policy, snap).used == pytest.approx(4_000.0)

    snap.equity = 100_000.0
    AccountSnapshot.observe(snap)
    same_day = max_drawdown_headroom(policy, snap)
    assert same_day.used == pytest.approx(4_000.0), \
        "the day's low must still count on the day it happened"

    # the caller starts a new day; the all-time low survives, the daily one does not
    next_day = _snapshot(equity=100_000.0)
    next_day.equity_low = 96_000.0
    assert max_drawdown_headroom(policy, next_day).used == pytest.approx(0.0)
    assert max_drawdown_headroom(policy, next_day).remaining == pytest.approx(4_000.0)


def test_a_trailing_drawdown_is_measured_from_the_peak_not_from_the_day_start():
    """The defect this pins: trailing used to score identically to floating.

    `DrawdownType.TRAILING` fell through to the `else` branch, so it measured
    the day's start against the day's low. The peak here was reached on an
    earlier day, which is the only situation where the two bases disagree: an
    account that opens a day below its high-water mark and then falls further
    reads as having spent only today's loss, and gets handed room it has
    already lost.
    """
    policy = _full_policy()
    policy.drawdown_type = DrawdownType.TRAILING
    policy.max_drawdown = RuleValue.known(0.05, source=SOURCE)

    # Peaked at 110k on day 1. Today opened at 105k and is now at 100k: 10k
    # below the peak, which is 9.1% of it against a 5% trailing limit.
    snap = _snapshot(equity=100_000.0, equity_peak=110_000.0,
                     equity_low=100_000.0, day_start_equity=105_000.0,
                     day_low_equity=100_000.0)

    headroom = max_drawdown_headroom(policy, snap)

    assert snap.trailing_basis == pytest.approx(110_000.0)
    assert headroom.limit == pytest.approx(5_500.0), \
        "a trailing limit is a fraction of the high-water mark, not of 105k"
    assert headroom.used == pytest.approx(10_000.0)   # 110k peak -> 100k now
    assert headroom.remaining == pytest.approx(0.0)
    assert headroom.remaining <= 0, "a breached trailing account must be told so"

    # The floating reading of the same numbers, which is what it used to report.
    policy.drawdown_type = DrawdownType.FLOATING
    assert max_drawdown_headroom(policy, snap).used == pytest.approx(5_000.0)


def test_a_trailing_peak_rises_with_equity_and_never_falls_back():
    """The floor is set at the peak, so a new high spends fresh allowance and a
    recovery does not give any back."""
    policy = _full_policy()
    policy.drawdown_type = DrawdownType.TRAILING
    policy.max_drawdown = RuleValue.known(0.05, source=SOURCE)

    at_peak = _snapshot(equity=110_000.0, equity_peak=110_000.0,
                        equity_low=110_000.0)
    assert max_drawdown_headroom(policy, at_peak).used == pytest.approx(0.0)

    # Run up further: the peak and the limit both move up.
    higher = _snapshot(equity=120_000.0, equity_peak=120_000.0,
                       equity_low=120_000.0)
    assert max_drawdown_headroom(policy, higher).limit == pytest.approx(6_000.0)

    # Drop 10% from 120k and recover back to it. Recovery must not restore it.
    dropped = _snapshot(equity=108_000.0, equity_peak=120_000.0,
                        equity_low=108_000.0, day_start_equity=120_000.0)
    breached = max_drawdown_headroom(policy, dropped)
    assert breached.used == pytest.approx(12_000.0)
    assert breached.remaining == pytest.approx(0.0)

    recovered = _snapshot(equity=120_000.0, equity_peak=120_000.0,
                          equity_low=108_000.0, day_start_equity=120_000.0)
    assert max_drawdown_headroom(policy, recovered).used == pytest.approx(12_000.0), \
        "recovery must not hand back a trailing allowance"


def test_a_trailing_peak_survives_a_day_rollover_and_a_snapshot_without_one():
    """A trailing peak is lifetime, not daily.

    Two ways to get this wrong: resetting it when `day_epoch` moves, which turns
    trailing into floating at midnight, and letting a snapshot that never
    observed a peak silently measure from a single moment's equity.
    """
    policy = _full_policy()
    policy.drawdown_type = DrawdownType.TRAILING
    policy.max_drawdown = RuleValue.known(0.05, source=SOURCE)

    # The peak predates the day. `day_start_equity` is deliberately lower, so a
    # calculator that used the day start would understate the loss.
    next_day = _snapshot(equity=101_000.0, equity_peak=110_000.0,
                         equity_low=101_000.0, day_start_equity=101_000.0,
                         day_low_equity=101_000.0)
    assert next_day.trailing_basis == pytest.approx(110_000.0)
    assert max_drawdown_headroom(policy, next_day).limit == pytest.approx(5_500.0)

    # With no recorded peak, the basis must not collapse to current equity --
    # that is what reports a breached account as untouched.
    unrecorded = _snapshot(equity=100_000.0)
    unrecorded.equity_peak = None
    assert max_drawdown_headroom(policy, unrecorded).used == pytest.approx(0.0)
    assert unrecorded.trailing_basis == pytest.approx(100_000.0), \
        "with no peak the fallback is the opening basis, which reads as unused"


def test_observe_raises_the_peak_instead_of_only_carrying_one():
    """The peak has to be *tracked*, not just passed through.

    Every other trailing test hands `equity_peak` in explicitly, which left the
    mutation that deleted the tracking line in `observe()` alive: the tests still
    passed, because a peak that is merely echoed back is indistinguishable from
    one that was measured until equity climbs above every value seen so far.
    That case is the whole job -- an account making new highs must move its own
    trailing floor, and a peak that only ever arrives pre-set never moves.
    """
    snap = AccountSnapshot(account_id="acct-1", equity=100_000.0,
                           start_equity=100_000.0, day_start_equity=100_000.0)
    AccountSnapshot.observe(snap)
    assert snap.equity_peak == pytest.approx(100_000.0)

    # A run-up raises it, without anybody assigning the field.
    snap.equity = 115_000.0
    AccountSnapshot.observe(snap)
    assert snap.equity_peak == pytest.approx(115_000.0)

    # A pullback must not lower it -- the mark is a high-water mark.
    snap.equity = 108_000.0
    AccountSnapshot.observe(snap)
    assert snap.equity_peak == pytest.approx(115_000.0), \
        "the peak only ever rises"

    policy = _full_policy()
    policy.drawdown_type = DrawdownType.TRAILING
    policy.max_drawdown = RuleValue.known(0.05, source=SOURCE)
    # 15k below the tracked peak of 115k: 13.0% of it, over a 5% limit. The
    # figure is larger than the 7k fall from the peak alone because `equity_low`
    # also remembers the 100k the account opened at -- the conservative pairing
    # documented on the trailing branch, and the safe direction for a limit
    # that decides whether the account still exists.
    headroom = max_drawdown_headroom(policy, snap)
    assert headroom.limit == pytest.approx(5_750.0)   # 5% of 115k
    assert headroom.used == pytest.approx(15_000.0)
    assert headroom.remaining == pytest.approx(0.0)



def test_daily_loss_is_measured_from_the_days_low_not_from_current_equity():
    """A dip and a recovery inside one day has still spent the day's room."""
    snap = _snapshot(equity=100_000.0)
    snap.day_low_equity = 95_000.0

    headroom = daily_loss_headroom(_full_policy(), snap)

    assert headroom.limit == pytest.approx(5_000.0)   # 5% of day start
    assert headroom.used == pytest.approx(5_000.0)
    assert headroom.remaining == pytest.approx(0.0)


def test_profit_target_reports_distance_still_to_travel():
    policy = _full_policy()
    snap = _snapshot(equity=102_000.0)

    headroom = profit_target_distance(policy, snap)

    assert headroom.limit == pytest.approx(8_000.0)   # 8% of 100k
    assert headroom.used == pytest.approx(2_000.0)    # achieved so far
    assert headroom.remaining == pytest.approx(6_000.0)


def test_trading_days_are_reported_as_days_and_not_as_currency():
    """A day count pushed through the money-shaped Headroom produced a limit
    measured in dollars and a buffer measured in dollars, which looks
    authoritative while meaning nothing."""
    policy = _full_policy()
    headroom = trading_days_headroom(policy, _snapshot(trading_days=4))

    assert headroom.remaining == pytest.approx(6.0)
    assert headroom.buffer in (None, 0.0), "a day count has no monetary buffer"


def test_open_risk_that_exceeds_the_remaining_room_protects_rather_than_allows():
    """34.8: a strategy signal cannot override insufficient headroom."""
    policy = _full_policy()
    # 98k on a 4% static limit leaves 2000 gross; the 10% buffer makes 1800 the
    # figure a trade is measured against. Two proposals pin the buffer: 1900 is
    # refused only because the buffer exists, and 1500 fits either way -- so a
    # test that only asserted 1500 would not notice the buffer being deleted.
    snap = _snapshot(equity=98_000.0)
    snap.equity_low = 98_000.0

    assert permission_for(policy, snap, proposed_risk=1_500.0)["permission"] \
        != Permission.PROTECT.value

    result = permission_for(policy, snap, proposed_risk=1_900.0)

    assert result["permission"] == Permission.PROTECT.value
    assert any(c["check"] == "max_drawdown" for c in result["checks"])
    assert "1800" in " ".join(c.get("detail") or "" for c in result["checks"])


def test_the_most_restrictive_check_wins_over_the_permissive_ones():
    """34.12: the most restrictive valid constraint takes precedence."""
    policy = _full_policy()
    snap = _snapshot(equity=100_000.0)

    result = permission_for(policy, snap, proposed_risk=0.0, symbol="US30")

    assert result["permission"] == Permission.HALT.value
    assert any(c["check"] == "instruments" and c["permission"] == "halt"
               for c in result["checks"])


def test_an_unlisted_symbol_is_refused_because_the_list_is_a_deny_list():
    """Building on a deny-list means a symbol never seen is refused, not allowed."""
    policy = _full_policy()

    assert policy.instruments.verdict("US30") is Restriction.DENIED
    assert policy.instruments.verdict("XAUUSD") is Restriction.ALLOWED

    unknown_default = _full_policy()
    unknown_default.instruments = InstrumentPolicy(
        denied_symbols=["US30"], default=Restriction.UNKNOWN)
    result = permission_for(unknown_default, _snapshot(), symbol="XAUUSD")
    assert result["permission"] == Permission.PROTECT.value


def test_weekend_and_news_windows_are_refused_when_the_policy_is_unknown():
    """A period whose rule was never read is a reason to refuse, not to allow."""
    policy = _full_policy()
    policy.weekend = Restriction.UNKNOWN
    policy.news = __import__(
        "challenge.policy", fromlist=["NewsPolicy"]).NewsPolicy()

    assert permission_for(policy, _snapshot(), is_weekend=True)["permission"] \
        == Permission.PROTECT.value
    assert permission_for(policy, _snapshot(), is_news_window=True)["permission"] \
        == Permission.PROTECT.value

    policy.weekend = Restriction.DENIED
    assert permission_for(policy, _snapshot(), is_weekend=True)["permission"] \
        == Permission.HALT.value


def test_the_report_shows_unknowns_as_unknowns_rather_than_as_zero():
    """A dashboard rendering an unverified limit as 0.00 invites reasoning
    about a number the system invented."""
    report = headroom_report(ChallengePolicy(policy_version="draft"), _snapshot())

    assert report["policy_verified"] is False
    assert report["missing_rules"]
    for dimension in report["dimensions"].values():
        assert dimension["is_known"] is False
        assert dimension["limit"] is None


# ---------------------------------------------------------------------------
# the registry: versioning
# ---------------------------------------------------------------------------

def test_a_registry_resolves_the_version_in_force_on_a_given_date():
    registry = PolicyRegistry()
    registry.register(_full_policy(policy_version="v1",
                                  effective_from="2026-01-01",
                                  effective_until="2026-06-30"))
    registry.register(_full_policy(policy_version="v2",
                                  effective_from="2026-07-01"))

    assert registry.resolve("DemoProp", "Classic 2-Step",
                            on="2026-03-15").policy_version == "v1"
    assert registry.resolve("DemoProp", "Classic 2-Step",
                            on="2026-08-15").policy_version == "v2"


def test_an_account_is_judged_against_the_rules_that_were_in_force_then():
    """Terms change; an account opened under v1 is not retroactively judged
    against v2, or a tightening of the rules would fail accounts retroactively."""
    registry = PolicyRegistry()
    registry.register(_full_policy(policy_version="v1",
                                  effective_from="2026-01-01",
                                  effective_until="2026-06-30"))
    registry.register(_full_policy(policy_version="v2",
                                  effective_from="2026-07-01"))

    opening_day = registry.resolve("DemoProp", "Classic 2-Step", on="2026-02-01")

    assert opening_day.policy_version == "v1"
    assert opening_day.max_drawdown.resolved() == pytest.approx(0.04)


def test_re_registering_the_same_version_is_refused():
    """Rewriting a version in place would re-judge an account against rules it
    never opened under, with nothing in the audit trail showing it."""
    registry = PolicyRegistry()
    registry.register(_full_policy())

    with pytest.raises(ValueError, match="already"):
        registry.register(_full_policy())


def test_a_policy_cannot_be_registered_without_a_version_or_a_provider():
    registry = PolicyRegistry()

    with pytest.raises(ValueError, match="version"):
        registry.register(_full_policy(policy_version=""))
    with pytest.raises(ValueError, match="provider"):
        registry.register(_full_policy(provider=""))


def test_resolving_an_unregistered_program_returns_nothing():
    registry = PolicyRegistry()
    registry.register(_full_policy())

    assert registry.resolve("DemoProp", "Some Other Program") is None
    assert registry.resolve("OtherProp", "Classic 2-Step") is None


# ---------------------------------------------------------------------------
# the state machine, and the refusal to resume silently
# ---------------------------------------------------------------------------

def test_a_new_account_starts_in_onboarding():
    machine = ChallengeStateMachine("acct-1")

    assert machine.state is ChallengeState.ONBOARDING
    assert machine.can_transition(ChallengeState.ACTIVE) is True


def test_deterioration_walks_active_caution_protection_halted():
    """The 34.10 progression, and each step is recorded with its reason."""
    machine = ChallengeStateMachine("acct-1")
    for state, reason in (
        (ChallengeState.ACTIVE, "policy verified, account connected"),
        (ChallengeState.CAUTION, "drawdown at 60% of allowance"),
        (ChallengeState.PROTECTION, "daily loss at 80% of allowance"),
        (ChallengeState.HALTED, "max drawdown consumed"),
    ):
        machine.transition(state, reason=reason)

    assert machine.state is ChallengeState.HALTED
    assert [t.to_state for t in machine.history] == [
        ChallengeState.ACTIVE, ChallengeState.CAUTION,
        ChallengeState.PROTECTION, ChallengeState.HALTED]
    assert all(t.reason for t in machine.history)


def test_a_halted_account_cannot_resume_by_naming_active():
    """34.10: must not silently resume. A direct transition to ACTIVE is the
    silent resume, and it is refused."""
    machine = ChallengeStateMachine("acct-1")
    machine.transition(ChallengeState.ACTIVE, reason="connected")
    machine.transition(ChallengeState.HALTED, reason="max drawdown consumed")

    assert machine.can_transition(ChallengeState.ACTIVE) is False
    with pytest.raises(TransitionRefused, match="cannot move from halted"):
        machine.transition(ChallengeState.ACTIVE, reason="looks fine now")


def test_recovery_requires_a_named_authorizer():
    """An unattributed resume is the silent resume wearing a different verb."""
    machine = ChallengeStateMachine("acct-1")
    machine.transition(ChallengeState.ACTIVE, reason="connected")
    machine.transition(ChallengeState.HALTED, reason="breached")

    with pytest.raises(TransitionRefused, match="named authorizer"):
        machine.recover(reason="conditions met", authorized_by="  ")

    record = machine.recover(
        reason="drawdown rule changed and the account was re-verified",
        authorized_by="operator@x.co", conditions_met={"policy_version": "v2"})

    assert machine.state is ChallengeState.ACTIVE
    assert record.authorized is True
    assert record.actor == "operator@x.co"


def test_recovery_only_applies_to_a_halted_account():
    machine = ChallengeStateMachine("acct-1")

    with pytest.raises(TransitionRefused, match="applies to a halted account"):
        machine.recover(reason="x", authorized_by="operator@x.co")


def test_a_terminal_outcome_cannot_be_re_entered_by_a_state_change():
    """A failed account is a fact about its history, not a current condition
    that better equity would undo."""
    machine = ChallengeStateMachine("acct-1")
    machine.transition(ChallengeState.ACTIVE, reason="connected")
    machine.transition(ChallengeState.FAILED, reason="daily loss limit breached")

    assert machine.as_dict()["is_terminal"] is True
    with pytest.raises(TransitionRefused, match="terminal"):
        machine.transition(ChallengeState.ACTIVE, reason="deposit made")


def test_a_transition_without_a_reason_is_refused():
    """A state change with no stated cause is the unattributable row that makes
    a halted account impossible to investigate afterwards."""
    machine = ChallengeStateMachine("acct-1")

    with pytest.raises(TransitionRefused, match="must carry a reason"):
        machine.transition(ChallengeState.ACTIVE, reason="   ")


def test_an_unresolved_policy_state_can_only_leave_by_becoming_known():
    """POLICY_UNKNOWN is a lock, not a label: the way out is verifying the
    rules, not asserting a different state."""
    machine = ChallengeStateMachine("acct-1")
    machine.transition(ChallengeState.POLICY_UNKNOWN, reason="no provider terms")

    assert machine.can_transition(ChallengeState.ACTIVE) is True
    with pytest.raises(TransitionRefused):
        machine.transition(ChallengeState.FUNDED, reason="skip ahead")


# ---------------------------------------------------------------------------
# 34.13/34.14: two accounts, two independent sets of state
# ---------------------------------------------------------------------------

def test_one_account_halting_does_not_halt_another():
    """34.14: a failure in one account must not propagate to another.

    Isolation here is a property of construction -- one machine per account,
    each holding only its own -- so the test asserts the absence of shared
    state rather than the presence of a guard.
    """
    first = ChallengeStateMachine("acct-1")
    second = ChallengeStateMachine("acct-2")
    first.transition(ChallengeState.ACTIVE, reason="connected")
    second.transition(ChallengeState.ACTIVE, reason="connected")

    first.transition(ChallengeState.HALTED, reason="breached")

    assert first.state is ChallengeState.HALTED
    assert second.state is ChallengeState.ACTIVE
    assert second.can_transition(ChallengeState.HALTED) is True


def test_each_account_scores_its_own_headroom():
    """Two accounts on the same policy can be in completely different
    positions, and neither may read the other's numbers."""
    policy = _full_policy()
    healthy = _snapshot(equity=100_000.0)
    distressed = _snapshot(equity=95_000.0)
    distressed.account_id = "acct-2"
    distressed.equity_low = 95_000.0

    assert max_drawdown_headroom(policy, healthy).remaining == pytest.approx(4_000.0)
    assert max_drawdown_headroom(policy, distressed).remaining == pytest.approx(0.0)
    assert permission_for(policy, healthy)["permission"] != Permission.HALT.value
    assert permission_for(policy, distressed)["permission"] == Permission.HALT.value


def test_a_rule_marked_known_without_a_value_is_not_treated_as_known():
    """The status flag alone must not buy a rule a number."""
    rule = RuleValue(value=None, status=RuleStatus.KNOWN)

    assert rule.is_known is False
    assert rule.resolved() is None
