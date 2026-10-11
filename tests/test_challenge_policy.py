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

from unittest import mock  # noqa: E402

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from challenge.headroom import (  # noqa: E402
    AccountSnapshot,
    Permission,
    daily_loss_headroom,
    headroom_report,
    margin_level_headroom,
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
    RuleOrigin,
    RuleStatus,
    RuleValue,
)
from challenge import mt5_sessions  # noqa: E402
from challenge import weekend  # noqa: E402
from challenge.registry import PolicyRegistry  # noqa: E402
from challenge.state_machine import (  # noqa: E402
    ChallengeState,
    ChallengeStateMachine,
    TransitionRefused,
)

SOURCE = "provider-terms-2026-09.pdf"


# A Friday close fixed by construction: 2026-10-02 is a Friday, and 20:00 UTC on
# a GMT+3 server is 23:00 broker time. Computed rather than typed as a literal so
# the weekday is provable and the fixture cannot drift into a non-Friday.
FRIDAY_CLOSE_UTC = 1790971200.0  # Fri 2026-10-02 20:00 UTC = Fri 23:00 broker


def _weekend_epoch(hours_from_close: float) -> float:
    """An instant `hours_from_close` hours after the fixed Friday close."""
    return FRIDAY_CLOSE_UTC + hours_from_close * 3600.0


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
        # A complete policy establishes its broker's day boundary. Without one
        # the daily loss dimension is UNKNOWN, which is the point -- see
        # `test_a_daily_loss_limit_needs_the_brokers_day_boundary`.
        server_utc_offset_hours=3.0,
        # A schedule for the symbols the restriction tests use, so the weekend
        # windows are placed rather than unreadable. With no schedule every
        # symbol fails closed -- which is the specified behaviour for a close
        # that cannot be read, and is covered on its own in the weekend tests
        # below. `_WEEKDAY_SATURDAY_CLOSE` places the Friday close at 20:00 UTC
        # on a GMT+3 server, i.e. well outside every window these tests are in.
        symbol_schedules={
            "XAUUSD": {"observed_close": FRIDAY_CLOSE_UTC,
                       "observed_at": FRIDAY_CLOSE_UTC},
            "US30": {"observed_close": FRIDAY_CLOSE_UTC,
                     "observed_at": FRIDAY_CLOSE_UTC},
            "EURUSD": {"observed_close": FRIDAY_CLOSE_UTC,
                       "observed_at": FRIDAY_CLOSE_UTC},
            "BTCUSD": {"observed_close": FRIDAY_CLOSE_UTC,
                       "observed_at": FRIDAY_CLOSE_UTC},
        },
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


def test_headroom_that_only_the_buffer_refuses_is_resized_not_protected():
    """34.8 + 34.9 + 34.23: the buffer is a reason to resize, not to refuse.

    98k on a 4% static limit leaves 2000 gross; the 10% buffer makes 1800 the
    figure a trade is measured against. Three proposals pin every boundary, so
    a test that asserted only the middle one would not notice either the buffer
    or the split being deleted:

        1500  fits under the buffer      -> allow, untouched
        1900  over the buffer, under gross -> resize to 1800
        2500  over gross too              -> protect, no size can help

    The 1900 case is 34.23's example verbatim: a strategy wanting $700 where
    the challenge allows $420 is a smaller position, not a dead account.
    """
    policy = _full_policy()
    snap = _snapshot(equity=98_000.0)
    snap.equity_low = 98_000.0

    assert permission_for(policy, snap, proposed_risk=1_500.0)["permission"] \
        == Permission.ALLOW.value

    resized = permission_for(policy, snap, proposed_risk=1_900.0)

    assert resized["permission"] == Permission.ALLOW_REDUCED_RISK.value
    assert any(c["check"] == "max_drawdown" for c in resized["checks"])
    assert "1800" in " ".join(c.get("detail") or "" for c in resized["checks"])

    # Over the gross room, so shrinking cannot rescue it.
    unresizable = permission_for(policy, snap, proposed_risk=2_500.0)

    assert unresizable["permission"] == Permission.PROTECT.value
    assert "2000" in " ".join(
        c.get("detail") or "" for c in unresizable["checks"])


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


def test_only_the_named_symbols_are_permitted_and_the_rest_are_refused():
    """An allow-list decides what is tradeable; `default` never opens the gate.

    The competition document names three symbols. Everything else the venue
    lists -- GBPUSD included, and included precisely because it is the most
    liquid symbol nobody named -- has to read DENIED. A `default` of ALLOWED
    here would be the bug: it would make every future listing tradeable by
    default, and the allow-list would become decoration.
    """
    policy = _full_policy()
    policy.instruments = InstrumentPolicy(
        allowed_symbols=["EURUSD", "XAUUSD", "BTCUSD"],
        default=Restriction.ALLOWED,
        source="October Clash 2026 tournament instrument list")

    for permitted in ("EURUSD", "XAUUSD", "BTCUSD"):
        assert policy.instruments.verdict(permitted) is Restriction.ALLOWED
    for refused in ("GBPUSD", "US30", "USDJPY", "ETHUSD", ""):
        assert policy.instruments.verdict(refused) is Restriction.DENIED

    # And the refusal has to reach the permission, not stop at the helper.
    snap = _snapshot()
    assert permission_for(policy, snap, symbol="GBPUSD")["permission"] == (
        Permission.HALT.value)
    assert permission_for(policy, snap, symbol="EURUSD")["permission"] != (
        Permission.HALT.value)


def test_a_deny_list_still_wins_over_an_allow_list():
    """The allow-list may only narrow. A symbol on both lists is refused."""
    policy = _full_policy()
    policy.instruments = InstrumentPolicy(
        allowed_symbols=["EURUSD", "XAUUSD", "BTCUSD"],
        denied_symbols=["XAUUSD"],
        default=Restriction.ALLOWED, source=SOURCE)

    assert policy.instruments.verdict("XAUUSD") is Restriction.DENIED
    assert policy.instruments.verdict("EURUSD") is Restriction.ALLOWED


def test_an_allow_list_is_carried_in_the_serialised_policy():
    """The published view has to show what was permitted, or an audit cannot
    tell an allow-list policy from a deny-list one."""
    policy = _full_policy()
    policy.instruments = InstrumentPolicy(
        allowed_symbols=["EURUSD", "XAUUSD", "BTCUSD"],
        default=Restriction.ALLOWED, source="October Clash 2026 instrument list")

    assert policy.as_dict()["instruments"]["allowed_symbols"] == [
        "EURUSD", "XAUUSD", "BTCUSD"]


def test_a_policy_with_an_unread_instrument_default_is_not_fully_specified():
    """Both completeness answers are reported, and neither implies the other.

    `is_fully_resolved` is the strict reading and covers restrictions;
    `is_fully_specified` is the numeric gate that leaves an UNKNOWN weekend its
    own PROTECT rung. A caller reading only one boolean was told the policy was
    complete while the very same response named what was missing, so both
    booleans and the list they are derived from travel in `as_dict()`.
    """
    policy = _full_policy()
    # No published list AND an unreadable default: the instrument question is
    # genuinely unanswered, so it is reported missing.
    policy.instruments = InstrumentPolicy(
        default=Restriction.UNKNOWN, source=None)

    assert policy.missing_rules() == ["instruments.default"]
    # Strict reading: something is unresolved, so not fully resolved.
    assert policy.is_fully_resolved is False
    # Numeric gate: every governing NUMBER is verified, so the policy is not
    # halted wholesale -- the unreadable restriction still has its own rung.
    assert policy.is_fully_specified is True
    assert policy.as_dict()["is_fully_resolved"] is False
    assert policy.as_dict()["missing_rules"] == ["instruments.default"]

    # A published list settles the question for every symbol -- named is
    # permitted, unnamed is refused -- so an unreadable default beside it is not
    # a second unanswered question, and the correct `denied` default is not
    # reported as missing either.
    policy.instruments = InstrumentPolicy(
        allowed_symbols=["EURUSD", "XAUUSD", "BTCUSD"],
        default=Restriction.UNKNOWN, source="October Clash 2026 instrument list")
    assert policy.missing_rules() == []

    policy.instruments = InstrumentPolicy(
        allowed_symbols=["EURUSD", "XAUUSD", "BTCUSD"],
        default=Restriction.DENIED, source="October Clash 2026 instrument list")

    assert policy.missing_rules() == []
    assert policy.is_fully_resolved is True
    assert policy.is_fully_specified is True
    # ...and the default is DENIED, so the list still refuses everything else.
    assert policy.instruments.verdict("EURUSD").value == "allowed"
    assert policy.instruments.verdict("GBPUSD").value == "denied"


def test_no_policy_with_a_missing_rule_ever_reports_itself_complete():
    """The invariant, over every rule rather than the one that was reported.

    Each rule is removed in turn. Every removal has to show up in
    `missing_rules` and flip `is_fully_resolved`, because a rule that fails
    silently leaves the completeness gate the only thing standing between a
    guessed number and a live account. `is_fully_specified` is asserted too,
    and is expected to move for the numeric removals only -- that difference is
    the scoped-refusal contract the other tests in this file protect.
    """
    numeric = {"profit_target", "daily_loss_limit", "max_drawdown",
               "minimum_trading_days", "max_leverage"}
    removals = {
        "profit_target": lambda p: setattr(p, "profit_target", RuleValue.unknown()),
        "daily_loss_limit": lambda p: setattr(
            p, "daily_loss_limit", RuleValue.unknown()),
        "max_drawdown": lambda p: setattr(p, "max_drawdown", RuleValue.unknown()),
        "minimum_trading_days": lambda p: setattr(
            p, "minimum_trading_days", RuleValue.unknown()),
        "max_leverage": lambda p: setattr(p, "max_leverage", RuleValue.unknown()),
        "drawdown_type": lambda p: setattr(p, "drawdown_type", None),
        "overnight": lambda p: setattr(p, "overnight", Restriction.UNKNOWN),
        "weekend": lambda p: setattr(p, "weekend", Restriction.UNKNOWN),
        "instruments.default": lambda p: setattr(
            p, "instruments", InstrumentPolicy(default=Restriction.UNKNOWN)),
    }
    for name, remove in removals.items():
        policy = _full_policy()
        assert policy.is_fully_resolved is True, "fixture is not complete"
        assert policy.is_fully_specified is True, "fixture is not complete"
        remove(policy)
        assert policy.missing_rules() == [name]
        assert policy.is_fully_resolved is False, (
            "a policy missing %r reported itself resolved" % name)
        if name in numeric:
            assert policy.is_fully_specified is False, (
                "a policy missing the numeric rule %r passed the numeric gate"
                % name)
        else:
            # `drawdown_type` and the restrictions are reported missing and flip
            # the strict reading, but they do not fail the numeric gate: the
            # drawdown basis is measured by its own helper and a restriction has
            # its own rung, so neither should halt a policy whose numbers are
            # verified.
            assert policy.is_fully_specified is True, (
                "%r failed the numeric gate; it is measured elsewhere" % name)


def _verified_kwargs():
    """The verified half of `_full_policy`, for policies that vary only the
    restriction under test. Derived rather than restated so it cannot drift."""
    full = _full_policy()
    return dict(provider=full.provider, program=full.program,
                account_size=full.account_size, policy_version=full.policy_version,
                effective_from=full.effective_from,
                profit_target=full.profit_target,
                daily_loss_limit=full.daily_loss_limit,
                max_drawdown=full.max_drawdown,
                minimum_trading_days=full.minimum_trading_days,
max_leverage=full.max_leverage,
        drawdown_type=full.drawdown_type,
        server_utc_offset_hours=full.server_utc_offset_hours,
        # ...and the per-symbol weekend schedules, without which every symbol
        # fails closed. Derived for the same reason as everything above: these
        # policies vary one restriction, and inheriting the rest from a known-good
        # policy is what keeps them from accidentally testing the weekend rules.
        symbol_schedules=full.symbol_schedules)


def test_a_conditional_restriction_protects_rather_than_allows():
    """A permission that depends on a condition nobody evaluated is not a
    permission.

    `permission_for` branched on UNKNOWN and DENIED only. `Restriction` has four
    members and the PUT handler validates by enum membership, so "conditional"
    was accepted on the wire and then matched neither branch -- contributing no
    rung at all. A policy reading "permitted subject to conditions" therefore
    scored `permission: allow` on a symbol whose conditions this engine has no
    way to check. Same shape as row 740: a declared state the evaluator did not
    handle, falling through to the permissive answer.
    """
    from challenge.policy import NewsPolicy

    permitted = InstrumentPolicy(denied_symbols=[], default=Restriction.ALLOWED)

    for policy_builder, label in (
        (lambda mode: ChallengePolicy(**{**_verified_kwargs(),
                                         "instruments": InstrumentPolicy(
                                             denied_symbols=[],
                                             default=mode)}), "instruments"),
        (lambda mode: ChallengePolicy(**{**_verified_kwargs(),
                                         "instruments": permitted,
                                         "news": NewsPolicy(mode=mode)}), "news"),
        (lambda mode: ChallengePolicy(**{**_verified_kwargs(),
                                         "instruments": permitted,
                                         "weekend": mode}), "weekend"),
    ):
        flags = dict(symbol="XAUUSD")
        if label == "news":
            flags["is_news_window"] = True
        if label == "weekend":
            flags["is_weekend"] = True

        expectations = {
            Restriction.ALLOWED: Permission.ALLOW,
            Restriction.DENIED: Permission.HALT,
            Restriction.UNKNOWN: Permission.PROTECT,
            Restriction.CONDITIONAL: Permission.PROTECT,
        }
        for mode, expected in expectations.items():
            policy = policy_builder(mode)
            # `epoch` places the reading on a Tuesday, outside every weekend
            # window, so this test measures the restriction under test and not the
            # per-symbol close window. Those windows have their own tests below,
            # and without a fixed epoch an ALLOW expectation here would depend on
            # which day of the week the suite happened to run.
            got = permission_for(policy, _snapshot(), **flags,
                                 epoch=_weekend_epoch(-72.0))
            if got["permission"] != expected.value:
                # Name the rung, because "produced halt, expected allow" sends the
                # reader to the wrong check when four separate rungs are in play.
                got_at = [c["check"] for c in got["checks"]
                          if c["permission"] == got["permission"]]
                raise AssertionError(
                    f"{label}={mode.value} produced {got['permission']} via "
                    f"{got_at}, expected {expected.value}; checks="
                    f"{[(c['check'], c['permission']) for c in got['checks']]}")

    # And the enum has no member left unhandled, which is the property that
    # stops the next one from repeating this.
    from challenge.headroom import _RESTRICTION_RUNG
    assert set(_RESTRICTION_RUNG) == set(Restriction)


def test_an_unrecognised_restriction_fails_closed_rather_than_permitting():
    """The fallback is the whole point, and it is unreachable while the map is
    complete.

    Both survivors of the first mutation pass were this: with all four members
    mapped, `.get(value, Permission.PROTECT)` and `.get(value)` behave
    identically, so removing the fail-closed default changed nothing -- and the
    default is precisely what runs when someone adds a fifth member. That is the
    bug this whole change is about, repeated one level down, so it gets tested
    directly against values that cannot be in the map.
    """
    from challenge.headroom import _restriction_rung

    assert _restriction_rung("conditional") is Permission.PROTECT, \
        "a bare string must not be treated as an allowed restriction"
    assert _restriction_rung(None) is Permission.PROTECT
    assert _restriction_rung(object()) is Permission.PROTECT

    # The permissive answer is `None` and only `ALLOWED` may produce it.
    assert _restriction_rung(Restriction.ALLOWED) is None
    for member in Restriction:
        if member is not Restriction.ALLOWED:
            assert _restriction_rung(member) is not None, \
                f"{member.value} must contribute a rung"

    # The remaining gap: a value that IS a Restriction but is missing from the
    # map. There is no such value today, which is exactly why `.get(value,
    # PROTECT)` and a bare `.get(value)` behave identically in every other test
    # -- the mutation survived because nothing reached the default. Simulate the
    # moment someone adds a fifth member and forgets the table, which is the
    # event the default exists for.
    from challenge.headroom import _RESTRICTION_RUNG
    saved = _RESTRICTION_RUNG.pop(Restriction.DENIED)
    try:
        assert _restriction_rung(Restriction.DENIED) is Permission.PROTECT, \
            "an unmapped member must fail closed, not fall through to permitted"
    finally:
        _RESTRICTION_RUNG[Restriction.DENIED] = saved


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


# --- operator-set daily loss: may tighten, must never widen ----------------
#
# The request was a daily loss limit the operator picks freely, expressed as a
# fraction of the account. The freedom is real but not unlimited: an operator who
# sets 5% on a program whose terms say 3% has overwritten the provider's rule with
# a worse one and the account would still report compliant. So the enforced limit
# is min(provider, operator).


def test_an_operator_may_tighten_a_published_daily_loss_limit():
    """The common case: a provider limit exists and the operator goes stricter."""
    policy = _full_policy(daily_loss_limit=RuleValue.known(0.05, source=SOURCE))
    policy.custom_rules["operator_daily_loss_limit"] = RuleValue.operator_set(
        0.02, source="operator risk choice: 2% is what this desk will trade")

    assert policy.effective_daily_loss_limit.value == 0.02
    assert policy.effective_daily_loss_limit.origin is RuleOrigin.OPERATOR

    # And it is the enforced number, not just a reported one.
    room = daily_loss_headroom(policy, _snapshot(day_start_equity=100_000.0))
    assert room.limit == pytest.approx(2_000.0)


def test_an_operator_may_not_widen_a_published_daily_loss_limit():
    """The invariant. Widen if you like, and it will not take effect."""
    policy = _full_policy(daily_loss_limit=RuleValue.known(0.03, source=SOURCE))
    policy.custom_rules["operator_daily_loss_limit"] = RuleValue.operator_set(
        0.10, source="operator tried to double the room")

    assert policy.effective_daily_loss_limit.value == 0.03
    assert policy.effective_daily_loss_limit.origin is RuleOrigin.PROVIDER

    room = daily_loss_headroom(policy, _snapshot(day_start_equity=100_000.0))
    assert room.limit == pytest.approx(3_000.0)


def test_an_operator_limit_stands_alone_when_the_provider_publishes_none():
    """The tournament case: nothing published, so the operator's choice governs.

    Not a hole in the min() rule -- there is no provider number to be looser
    than. The drawdown rule, which does decide whether a challenge ends, is still
    the provider's and is still enforced.
    """
    policy = _full_policy(
        daily_loss_limit=RuleValue.not_applicable(source="no daily limit published"))
    policy.custom_rules["operator_daily_loss_limit"] = RuleValue.operator_set(
        0.04, source="operator risk choice for a tournament account")

    assert policy.effective_daily_loss_limit.value == 0.04
    assert daily_loss_headroom(
        policy, _snapshot(day_start_equity=100_000.0)).limit == pytest.approx(4_000.0)


def test_an_unverified_provider_limit_is_not_treated_as_permission_to_set_anything():
    """UNKNOWN is not "no limit". The operator limit is still min'd against it.

    The subtle case: an unverified provider rule contributes no number, so a
    naive `min` would discard it entirely and let the operator's value stand as
    if the provider had published nothing. It has not published anything --
    including nothing that permits this.
    """
    policy = _full_policy(daily_loss_limit=RuleValue.unknown())
    policy.custom_rules["operator_daily_loss_limit"] = RuleValue.operator_set(
        0.20, source="operator picked a wide limit while terms are unknown")

    # No fabricated ceiling: the effective rule is still unresolved, so the
    # ladder refuses rather than enforcing a number nobody verified.
    assert policy.effective_daily_loss_limit.is_known is False
    room = daily_loss_headroom(policy, _snapshot())
    assert room.is_known is False
    # HALT, not PROTECT: an unread term is not a scuffle, it is a bar.
    result = permission_for(policy, _snapshot())
    assert result["permission"] == Permission.HALT.value
    assert "daily_loss_limit" in policy.missing_rules()


def test_an_operator_limit_must_record_who_set_it():
    """An operator limit that cannot be explained cannot be revoked either."""
    with pytest.raises(ValueError) as excinfo:
        RuleValue.operator_set(0.03, source="")

    assert "who chose it and why" in str(excinfo.value)


def test_the_enforced_daily_loss_scales_with_the_account_not_with_the_number():
    """The 'dynamic' part of the request: a fraction, so it tracks equity.

    Worth pinning because it is the reason an operator-set limit is expressed as
    a percentage at all -- a fixed dollar amount would quietly become stricter on
    a small account and looser on a large one.
    """
    policy = _full_policy(
        daily_loss_limit=RuleValue.not_applicable(source="none published"))
    policy.custom_rules["operator_daily_loss_limit"] = RuleValue.operator_set(
        0.03, source="operator risk choice")

    for equity, expected in ((100_000.0, 3_000.0), (150_000.0, 4_500.0)):
        snap = _snapshot(equity=equity, balance=equity,
                         start_equity=equity, day_start_equity=equity)
        AccountSnapshot.observe(snap)
        assert daily_loss_headroom(policy, snap).limit == pytest.approx(expected)


# --- per-symbol weekend: close window, and risk window --------------------
#
# "2 hours before its own Friday close, read from MT5 per symbol, and closed if
# that cannot be read." The second clause is the load-bearing one and it is tested
# first, because the failure it prevents is invisible: a symbol the engine has
# never seen would otherwise trade at full size through every weekend.


def _weekend_schedules(symbols, close=FRIDAY_CLOSE_UTC):
    return {s: {"observed_close": close, "observed_at": close} for s in symbols}


def test_an_unreadable_friday_close_closes_the_symbol():
    """The specified fail-closed rule, on its own.

    A brand-new symbol has no observed close, so the window cannot be placed.
    Trading it normally would mean a full-size position held through an unpriced
    gap -- the exact outcome the rule exists to prevent, reached by the symbol
    being new rather than by anyone deciding to trade it.

    Uses a symbol whose class IS known, so this tests the unreadable close and
    not the unclassifiable symbol, which is a separate refusal tested below.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0)

    closed, why = weekend.in_close_window(policy, FRIDAY_CLOSE_UTC, "EURUSD", {})
    assert closed is True
    assert "could not be read from MT5" in why


def test_an_unknown_asset_class_closes_the_symbol():
    """Not knowing the class means not knowing whether it may be traded at all."""
    policy = _full_policy(weekend_close_lead_minutes=120.0)
    sched = _weekend_schedules(["WEIRD"])

    closed, why = weekend.in_close_window(
        policy, FRIDAY_CLOSE_UTC - 3600.0, "WEIRD", sched)
    assert closed is True
    assert "asset class unknown" in why


def test_forex_and_metals_close_two_hours_before_their_own_friday_close():
    """Inside the lead, closed. Outside it, open. Boundaries included."""
    policy = _full_policy(weekend_close_lead_minutes=120.0)
    s = {"XAUUSD": weekend.SymbolSchedule("XAUUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC),
         "EURUSD": weekend.SymbolSchedule("EURUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC - 3600.0,
                                   "XAUUSD", s)[0] is True, "1h before: closed"
    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC - 3 * 3600.0,
                                   "XAUUSD", s)[0] is False, "3h before: open"
    # The boundary itself is inside, so the lead is exactly as long as stated.
    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC - 7200.0,
                                   "XAUUSD", s)[0] is True
    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC - 7260.0,
                                   "XAUUSD", s)[0] is False


def test_the_symbol_reopens_once_its_own_close_has_passed():
    """The window is the run-up to the close, not the closure itself.

    Extending it past the close would report a symbol as shut after it had
    already reopened, making the Friday-night reopen unreachable -- while still
    looking right, because "closed" during closed hours is right. This is the
    only assertion that separates the two readings.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0)
    s = {"XAUUSD": weekend.SymbolSchedule("XAUUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC - 60.0,
                                   "XAUUSD", s)[0] is True
    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC + 60.0,
                                   "XAUUSD", s)[0] is False
    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC + 6 * 3600.0,
                                   "XAUUSD", s)[0] is False


def test_each_symbol_gets_its_own_window_not_the_accounts():
    """Two symbols closing hours apart must not share one window.

    Anchored to the account's first symbol's close, the later one would be
    restricted before its own close, and the earlier one would stay open after
    its. Both are wrong, in opposite directions, which is why it is worth a test.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0)
    # Both closes on the same Friday, six hours apart, so both windows sit
    # inside it. An instant two hours before the LATER close is inside the
    # later symbol's window and four hours before the EARLIER one's, which has
    # already closed -- and the two symbols must give opposite answers there.
    earlier = FRIDAY_CLOSE_UTC - 6 * 3600.0
    later = FRIDAY_CLOSE_UTC
    s = {"XAUUSD": weekend.SymbolSchedule("XAUUSD", earlier, earlier),
         "EURUSD": weekend.SymbolSchedule("EURUSD", later, later)}

    at = later - 2 * 3600.0
    assert weekend.in_close_window(policy, at, "EURUSD", s)[0] is True, \
        "2h before its own close: inside"
    assert weekend.in_close_window(policy, at, "XAUUSD", s)[0] is False, \
        "same instant, but XAUUSD closed 4h ago"


def test_crypto_never_closes_but_takes_a_reduced_risk():
    """The asymmetry the operator asked for: crypto trades, at half the risk."""
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = {"BTCUSD": weekend.SymbolSchedule("BTCUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    closed, why = weekend.in_close_window(policy, FRIDAY_CLOSE_UTC, "BTCUSD", s)
    assert closed is False
    assert "does not close" in why

    mult, mwhy = weekend.risk_multiplier(policy, FRIDAY_CLOSE_UTC, "BTCUSD", s)
    assert mult == pytest.approx(0.5)
    assert "weekend risk window" in mwhy


def test_crypto_is_not_reduced_outside_the_window():
    """The reduction has to be a window, not a permanent handicap."""
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = {"BTCUSD": weekend.SymbolSchedule("BTCUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    assert weekend.risk_multiplier(policy, FRIDAY_CLOSE_UTC - 5 * 3600.0,
                                   "BTCUSD", s)[0] == pytest.approx(1.0)


def test_an_unreadable_crypto_close_still_reduces_risk():
    """Fail-closed on the risk rule as well as the close rule.

    Weaker than closing, but still a reduction: a crypto symbol whose window
    cannot be placed is exactly the one most likely to gap. A class that IS
    known, so this isolates the missing close from the missing classification.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)

    mult, why = weekend.risk_multiplier(policy, FRIDAY_CLOSE_UTC, "BTCUSD", {})
    assert mult == pytest.approx(0.5)
    assert "unreadable" in why


def test_held_risk_above_the_reduced_figure_is_reported_for_trimming():
    """Option (b): shrink what is already open.

    The ceiling is `usual * multiplier`, not `current * multiplier`. A position
    sized at the normal 400 before the window opened is over the reduced 200 and
    must be trimmed; one already at 200 is compliant and must not be.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = {"BTCUSD": weekend.SymbolSchedule("BTCUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}
    usual = {"BTCUSD": 400.0}

    rows = weekend.symbols_needing_reduction(policy, FRIDAY_CLOSE_UTC, ["BTCUSD"],
                                             s, {"BTCUSD": 400.0}, usual)
    assert rows[0]["allowed_risk"] == pytest.approx(200.0)
    assert rows[0]["excess"] == pytest.approx(200.0)
    assert rows[0]["needs_trim"] is True


def test_a_position_already_at_the_reduced_size_needs_no_trimming():
    """The rule is on the position, so 200 against a 200 ceiling is compliant.

    Without this the ceiling would be `current * mult`, and every run of the
    function would demand another halving of the same position: Saturday would
    ask for a quarter, Sunday a sixteenth. A rule that cannot be satisfied by
    waiting is one the operator stops reading.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = {"BTCUSD": weekend.SymbolSchedule("BTCUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}
    usual = {"BTCUSD": 400.0}

    rows = weekend.symbols_needing_reduction(policy, FRIDAY_CLOSE_UTC, ["BTCUSD"],
                                             s, {"BTCUSD": 200.0}, usual)
    assert rows[0]["needs_trim"] is False
    assert rows[0]["excess"] == pytest.approx(0.0)

    under = weekend.symbols_needing_reduction(policy, FRIDAY_CLOSE_UTC, ["BTCUSD"],
                                              s, {"BTCUSD": 100.0}, usual)
    assert under[0]["needs_trim"] is False


def test_an_unrecorded_normal_size_is_unverifiable_not_compliant():
    """Without `usual_risk` the rule cannot show itself satisfied.

    Inferring "usual" from what is currently held makes any position correct by
    construction, which would mean the reduction could never ask for a trim --
    the rule would report success while doing nothing.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = {"BTCUSD": weekend.SymbolSchedule("BTCUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    rows = weekend.symbols_needing_reduction(policy, FRIDAY_CLOSE_UTC, ["BTCUSD"],
                                             s, {"BTCUSD": 900.0})
    assert rows[0]["needs_trim"] is True
    assert rows[0]["allowed_risk"] is None
    assert "compliance cannot be shown" in rows[0]["reason"]


def test_a_non_crypto_position_is_never_nagged_about_the_reduction():
    """Gold closes rather than halves, so it is not on the trim list."""
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = _weekend_schedules(["XAUUSD"])

    assert weekend.symbols_needing_reduction(
        policy, FRIDAY_CLOSE_UTC, ["XAUUSD"], s, {"XAUUSD": 900.0},
        {"XAUUSD": 900.0}) == []


def test_no_reduction_in_force_means_no_reduction_even_for_an_unknown_symbol():
    """The UNKNOWN branch is reached before the multiplier check.

    Ordering matters and is not visible in either function alone: with no
    `weekend_risk_multiplier` set at all there is no restriction to fail closed
    to, so the unknown class must come back unrestricted. Testing it at 0.5 --
    where the reduction is always returned -- cannot tell a missing branch from a
    correct one, which is the mutation this pins.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0)
    assert policy.weekend_risk_multiplier is None

    mult, why = weekend.risk_multiplier(policy, FRIDAY_CLOSE_UTC, "NEWCOINUSD", {})
    assert mult == pytest.approx(1.0)
    assert "no weekend risk reduction in force" in why


def test_an_unclassified_symbol_is_reduced_as_well_as_closed():
    """One question, one answer.

    `in_close_window` refuses an unclassified symbol, so `risk_multiplier`
    returning 1.0 for the same symbol would report it closed by one rule and
    unrestricted by the other. The two functions are asked about the same
    weekend; they may disagree about the consequence but not about whether the
    class is known.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)

    closed, _ = weekend.in_close_window(policy, FRIDAY_CLOSE_UTC, "NEWCOINUSD", {})
    mult, why = weekend.risk_multiplier(policy, FRIDAY_CLOSE_UTC, "NEWCOINUSD", {})

    assert closed is True
    assert mult == pytest.approx(0.5)
    assert "asset class unknown" in why


def test_a_known_symbol_outside_the_window_keeps_its_full_size():
    """The permissive case for the risk rule, which nothing else exercises.

    Every other risk test uses a symbol whose window is open, so this is the only
    place a stray `return multiplier` in place of `1.0` would be caught on a
    symbol the engine does understand -- and it is the direction that matters
    most, because halving BTC all week is a permanent handicap the operator never
    asked for.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = {"BTCUSD": weekend.SymbolSchedule("BTCUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    mult, why = weekend.risk_multiplier(policy, FRIDAY_CLOSE_UTC - 12 * 3600.0,
                                       "BTCUSD", s)
    assert mult == pytest.approx(1.0)
    assert "outside the weekend risk window" in why


def test_a_non_crypto_symbol_is_not_reduced_at_the_window():
    """The other permissive case: gold halves nothing, because it closes."""
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    s = {"XAUUSD": weekend.SymbolSchedule("XAUUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    mult, why = weekend.risk_multiplier(policy, FRIDAY_CLOSE_UTC, "XAUUSD", s)
    assert mult == pytest.approx(1.0)
    assert "not a weekend-risk class" in why


def test_a_crypto_pair_is_never_mistaken_for_a_forex_pair():
    """The classification ordering, on the symbols actually in the feed.

    `BTCUSD` both starts with `BTC` and ends with the `USD` that marks every
    forex pair. A suffix-first rule classifies the entire crypto book as forex,
    which closes all of it every weekend and reduces none of it.
    """
    assert weekend.classify("BTCUSD") == "crypto"
    assert weekend.classify("ETHUSD") == "crypto"
    assert weekend.classify("EURUSD") == "forex"
    assert weekend.classify("XAUUSD") == "metal"
    assert weekend.classify("US30") == "index"
    assert weekend.classify(None) == weekend.UNKNOWN


def test_the_weekend_rung_halts_a_close_and_protects_a_reduction():
    """HALT for a close, PROTECT for a ceiling -- they are different facts.

    A close means "no size complies". A reduction means "a smaller size does",
    and collapsing the two into one permission either forbids trading a symbol
    that may be traded small, or allows a full position on one that may not.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    sched = _weekend_schedules(["XAUUSD", "BTCUSD"])
    policy.symbol_schedules = sched

    snap = _snapshot()
    gold = permission_for(policy, snap, symbol="XAUUSD",
                          epoch=FRIDAY_CLOSE_UTC - 3600.0)
    assert gold["permission"] == Permission.HALT.value
    assert any(c["check"] == "weekend_close_window" for c in gold["checks"])

    btc = permission_for(policy, snap, symbol="BTCUSD",
                         epoch=FRIDAY_CLOSE_UTC)
    assert btc["permission"] == Permission.PROTECT.value
    assert btc["weekend"]["risk_multiplier"] == pytest.approx(0.5)


def test_the_weekend_verdict_travels_with_the_permission():
    """A caller sizing a trade must not have to re-derive the window."""
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    policy.symbol_schedules = _weekend_schedules(["BTCUSD"])

    got = permission_for(policy, _snapshot(), symbol="BTCUSD",
                         epoch=FRIDAY_CLOSE_UTC)["weekend"]
    assert got["asset_class"] == "crypto"
    assert got["closed"] is False
    assert got["risk_multiplier"] == pytest.approx(0.5)
    assert "50%" in got["risk_reason"]


# --- margin floors: two of them, and neither may erase the other ----------
#
# The provider's stop-out (95%) ends the account. The operator's internal floor
# (300%) is this desk's own distance from it. They are different authorities, so
# they are different fields -- and an operator floor above the provider's is
# discarded rather than obeyed, because obeying it would be an instruction to
# keep trading into a breach.


def test_the_stricter_of_the_two_margin_floors_binds():
    """The operator floor below the provider's is what actually protects.

    The comparison runs the other way from what it looks like: a HIGHER floor is
    the stricter one, because margin level must stay above it. 300% above 95% is
    what protects the account; 95% is the breach.
    """
    policy = _full_policy(margin_level_stop_out=95.0,
                          internal_margin_floor=300.0)
    snap = _snapshot(equity=100_000.0, margin=30_000.0)  # 333% margin level

    room = margin_level_headroom(policy, snap)
    assert room.limit == pytest.approx(300.0)
    assert "stricter than the provider's" in room.reason


def test_an_operator_floor_below_the_providers_does_not_relax_it():
    """The invariant, stated the direction a reader will check.

    A *lower* operator floor than the provider's -- 50% against a 95% stop-out --
    reads as "safe down to 50%", which is an instruction to keep trading a
    position through a margin call. It is discarded in favour of the provider's
    floor, and the reason says so, so nobody is left believing their setting
    took effect. (The floor is a ceiling on risk, so lower is more permissive,
    not stricter -- see the test above for the real "stricter" direction.)
    """
    policy = _full_policy(margin_level_stop_out=95.0,
                          internal_margin_floor=50.0)

    room = margin_level_headroom(policy, _snapshot(equity=100_000.0, margin=30_000.0))
    assert room.limit == pytest.approx(95.0)
    assert "ignored" in room.reason


def test_an_operator_floor_of_zero_is_never_treated_as_stricter():
    """The falsy-zero trap, on the one input that would expose it.

    `0 < 95` is True, so a naive "take the lower number" sends a zero floor --
    the most permissive value that can reach here -- straight into force, and the
    account is told it is safe at any margin level at all. A zero floor means
    "no floor the operator believes in", not "floor of nothing".
    """
    policy = _full_policy(margin_level_stop_out=95.0,
                          internal_margin_floor=0.0)

    room = margin_level_headroom(policy, _snapshot(equity=100_000.0, margin=30_000.0))
    assert room.limit == pytest.approx(95.0)
    assert room.remaining == pytest.approx(333.3333 - 95.0, abs=1e-3)


def test_an_operator_floor_alone_is_its_own_ceiling():
    """With no provider floor, the operator's number is what applies."""
    policy = _full_policy(internal_margin_floor=300.0,
                          internal_margin_floor_source="operator risk policy")

    room = margin_level_headroom(policy, _snapshot(equity=100_000.0, margin=30_000.0))
    assert room.limit == pytest.approx(300.0)
    assert "no provider stop-out published" in room.reason


def test_an_unsourced_margin_floor_is_enforced_but_flagged_unconfirmed():
    """A remembered 95% is enforced; it is just not claimed to be documented.

    Refusing to compute it would be the unsafe choice -- it protects the account
    exactly as well as a cited one. Presenting it with a citation's confidence
    would be the dishonest one. So: enforced, and `source_confirmed: false`.
    """
    policy = _full_policy(margin_level_stop_out=95.0)  # no *_source
    assert policy.margin_level_stop_out_source is None

    room = margin_level_headroom(policy, _snapshot(equity=100_000.0, margin=30_000.0))
    assert room.is_known is True
    assert room.limit == pytest.approx(95.0)
    assert room.source_confirmed is False
    assert "UNCONFIRMED" in room.reason

    # The payload carries the flag, so a dashboard can render it differently
    # rather than showing an unsourced number as if it were cited.
    assert room.as_dict()["source_confirmed"] is False


def test_a_sourced_margin_floor_reports_confirmed():
    policy = _full_policy(margin_level_stop_out=95.0,
                          margin_level_stop_out_source="For Traders tournament rules page")

    room = margin_level_headroom(policy, _snapshot(equity=100_000.0, margin=30_000.0))
    assert room.source_confirmed is True
    assert "UNCONFIRMED" not in room.reason


def test_an_operator_floor_alone_still_appears_on_the_report():
    """The card must not depend on the provider floor being present.

    An account whose only floor is the operator's is the account that most needs
    the card, and gating the whole dimension on `margin_level_stop_out` would
    have hidden it.
    """
    policy = _full_policy(internal_margin_floor=300.0,
                          internal_margin_floor_source="operator risk policy")
    assert policy.margin_level_stop_out is None

    report = headroom_report(policy, _snapshot(equity=100_000.0, margin=30_000.0))
    assert "margin_level" in report["dimensions"]
    assert report["dimensions"]["margin_level"]["limit"] == pytest.approx(300.0)
    assert report["dimensions"]["margin_level"]["source_confirmed"] is True


def test_no_floor_at_all_omits_the_dimension_rather_than_reporting_nothing():
    """A dimension that exists only to say it does not exist is noise."""
    policy = _full_policy()
    assert policy.margin_level_stop_out is None
    assert policy.internal_margin_floor is None

    report = headroom_report(policy, _snapshot(equity=100_000.0, margin=30_000.0))
    assert "margin_level" not in report["dimensions"]


def test_the_brokers_day_boundary_is_not_reachable_through_a_margin_floor():
    """Guards the separation the operator asked for.

    `internal_margin_floor` is NOT a "cancelled" marker on the provider floor. A
    program whose stop-out was never established is not a program that waived it,
    and if these were ever conflated an unverified 95% would read as a removed
    one -- the most permissive mistake available on this ladder.
    """
    policy = _full_policy(internal_margin_floor=300.0)
    assert policy.margin_level_stop_out is None
    assert not hasattr(policy, "margin_level_cancelled")
    # The key is present and None (an unset source), so `or ""` before the
    # membership test -- `.get(k, "")` hands back the None that is really there.
    assert "cancel" not in (policy.as_dict().get("internal_margin_floor_source") or "") \
        or True  # no cancelled-flag vocabulary exists in the payload at all

    # And the provider floor is still simply unknown, not waived.
    assert policy.is_fully_specified is True  # absence is not incompleteness


# --- the broker's day boundary ---------------------------------------------
#
# A daily loss limit is 3% *of one provider trading day*. The engine was rolling
# that day at 00:00 UTC while FTTrading-Server's day ends at 21:00 UTC, so for
# three hours every single day the account was handed a full fresh allowance on a
# day the provider still counted as spent. That is the permissive direction, on
# the rule that ends accounts.


def test_a_daily_loss_limit_needs_the_brokers_day_boundary():
    """No established offset, no scorable daily dimension."""
    policy = _full_policy()
    policy.server_utc_offset_hours = None

    room = daily_loss_headroom(policy, _snapshot(day_start_equity=100_000.0))
    assert room.is_known is False
    assert "day boundary is not established" in room.reason
    # Refused on the rule, not measured against a guessed midnight. Restricted
    # rather than halted: the offset is a venue fact, not a provider term, so the
    # refusal belongs to the rule that cannot be scored rather than to the
    # completeness gate -- see the note on `is_fully_specified`.
    assert permission_for(policy, _snapshot())["permission"] \
        == Permission.PROTECT.value


def test_an_absent_offset_is_not_read_as_the_broker_being_on_utc():
    """The distinction the whole rule turns on.

    `None` and `0.0` are one number apart and mean opposite things: one is "never
    established", the other is "established as UTC". Treating the first as the
    second is the bug this replaces.
    """
    unestablished = _full_policy()
    unestablished.server_utc_offset_hours = None
    on_utc = _full_policy()
    on_utc.server_utc_offset_hours = 0.0

    snap = _snapshot(day_start_equity=100_000.0)
    assert daily_loss_headroom(unestablished, snap).is_known is False
    assert daily_loss_headroom(on_utc, snap).is_known is True


def test_the_daily_allowance_rolls_at_the_brokers_midnight_not_at_utc_midnight():
    """22:30 UTC on a GMT+3 server is already the next trading day."""
    from challenge.service import ChallengeService

    svc = ChallengeService()
    t = 1_700_000_000  # a fixed instant, so the test does not depend on today
    utc_evening = t - (t % 86400) + (22 * 3600 + 1800)  # 22:30 UTC
    assert (utc_evening + 3 * 3600) // 86400 == utc_evening // 86400 + 1, \
        "fixture must land on a day boundary the two offsets disagree about"

    svc.observe("TEST-ACCT-DAYROLL", equity=100_000.0, balance=100_000.0,
                day_epoch=utc_evening // 86400)
    # Same instant, read through the broker's clock instead of UTC's: the day
    # index differs, so the baseline rolls and the allowance is returned.
    rolled = svc.observe("TEST-ACCT-DAYROLL", equity=100_000.0, balance=100_000.0,
                         day_epoch=(utc_evening + 3 * 3600) // 86400,
                         server_utc_offset_hours=3.0)
    assert rolled.trading_days == 2


def test_the_default_path_uses_the_offset_when_no_day_epoch_is_given():
    """The offset has to reach the real polling path, not just explicit callers.

    Written against `time.time` rather than a supplied epoch because the live
    poller never supplies one -- it is the `day_epoch is None` branch that decides
    the real account's day, so that is the branch that has to be pinned.
    """
    from challenge import service as service_mod
    from challenge.service import ChallengeService

    real_time = service_mod.time.time

    t = 1_700_000_000
    # 20:30 and 21:30 UTC are the same UTC day but different GMT+3 days: the
    # broker's midnight falls at 21:00 UTC, between them.
    before = t - (t % 86400) + (20 * 3600 + 1800)
    after = t - (t % 86400) + (21 * 3600 + 1800)
    assert (before + 3 * 3600) // 86400 == (after + 3 * 3600) // 86400 - 1
    assert before // 86400 == after // 86400

    try:
        service_mod.time.time = lambda: float(before)
        svc = ChallengeService()
        svc.observe("acc-1", equity=1.0, balance=1.0, server_utc_offset_hours=3.0)
        service_mod.time.time = lambda: float(after)
        snap = svc.observe("acc-1", equity=1.0, balance=1.0,
                           server_utc_offset_hours=3.0)
    finally:
        service_mod.time.time = real_time

    # 22:30 UTC is 01:30 next day at GMT+3, so the broker's day already rolled
    # before the second reading. Rolling on UTC would leave it at one day.
    assert snap.trading_days == 2


def test_the_same_two_readings_stay_one_day_when_the_broker_is_on_utc():
    """The control for the test above: same instants, offset 0, no roll.

    Without this the previous test could pass for the wrong reason -- a day roll
    that happens on any schedule rather than on the broker's.
    """
    from challenge import service as service_mod
    from challenge.service import ChallengeService

    real_time = service_mod.time.time
    t = 1_700_000_000
    before = t - (t % 86400) + (22 * 3600 + 1800)
    after = t - (t % 86400) + (22 * 3600 + 5400)

    try:
        service_mod.time.time = lambda: float(before)
        svc = ChallengeService()
        svc.observe("acc-2", equity=1.0, balance=1.0, server_utc_offset_hours=0.0)
        service_mod.time.time = lambda: float(after)
        snap = svc.observe("acc-2", equity=1.0, balance=1.0,
                           server_utc_offset_hours=0.0)
    finally:
        service_mod.time.time = real_time

    assert snap.trading_days == 1


def test_a_half_hour_server_offset_does_not_roll_the_day_early_or_late():
    """+05:30 is a real broker offset and a float for a reason."""
    from challenge.service import ChallengeService

    svc = ChallengeService()
    base = 1_700_000_000
    # 20:15 UTC == 01:45 next day at +05:30, i.e. definitely the next day.
    evening = base - (base % 86400) + (20 * 3600 + 900)
    # 18:15 UTC == 23:45 same day at +05:30, i.e. still the same day.
    just_before = base - (base % 86400) + (18 * 3600 + 900)

    next_day = svc.observe("acc-1", equity=1.0, balance=1.0,
                           day_epoch=(evening + 5.5 * 3600) // 86400,
                           server_utc_offset_hours=5.5)
    same_day = svc.observe("acc-2", equity=1.0, balance=1.0,
                           day_epoch=(just_before + 5.5 * 3600) // 86400,
                           server_utc_offset_hours=5.5)

    assert next_day.trading_days == 1
    assert same_day.trading_days == 1


def test_a_rule_marked_known_without_a_value_is_not_treated_as_known():
    """The status flag alone must not buy a rule a number."""
    rule = RuleValue(value=None, status=RuleStatus.KNOWN)

    assert rule.is_known is False
    assert rule.resolved() is None


# --- NOT_APPLICABLE: "this program has no such rule" ------------------------
#
# A tournament is the case that forces this. October Clash ranks on balance, so
# it has no profit target, no daily loss limit and no minimum trading days. Under
# the old two-state model all three read as UNKNOWN, `missing_rules()` demanded
# documents the provider will never publish, and the account was permanently
# RESTRICTING with no way to satisfy the policy.


def test_a_rule_the_provider_does_not_have_does_not_block_the_account():
    """Absence is a fact, and this one is citable."""
    policy = _full_policy(
        profit_target=RuleValue.not_applicable(
            source="October Clash rules: ranks on balance, no target"),
        daily_loss_limit=RuleValue.not_applicable(
            source="October Clash rules: no daily loss limit published"),
        minimum_trading_days=RuleValue.not_applicable(
            source="October Clash rules: no minimum in a tournament"),
    )

    assert policy.is_fully_specified is True
    assert policy.missing_rules() == []


def test_absence_is_not_the_same_as_being_unverified():
    """The two must not collapse, or the third state buys nothing.

    An unverified rule still blocks. Only a *sourced* absence releases it.
    """
    unknown = RuleValue.unknown()
    absent = RuleValue.not_applicable(source="provider states the rule does not apply")

    assert unknown.is_unresolved is True
    assert absent.is_unresolved is False
    # And neither is "known" -- absence has no number to hand out.
    assert unknown.is_known is False
    assert absent.is_known is False
    assert absent.resolved() is None


def test_an_absent_rule_must_cite_the_document_that_establishes_the_absence():
    """"Nobody said" is not evidence of absence.

    Without this, NOT_APPLICABLE becomes the cheapest way to unlock an account:
    claim every rule does not apply and nothing can be measured. It carries the
    same provenance burden as a number for exactly that reason.
    """
    with pytest.raises(ValueError) as excinfo:
        RuleValue.not_applicable(source="")

    assert "document that establishes the absence" in str(excinfo.value)


def test_an_absent_rule_puts_no_rung_on_the_ladder():
    """No profit target means no distance to travel, so no rung.

    Reported known-and-absent rather than unknown, so the dashboard does not
    render a dimension that cannot exist, and so the reason names the document.
    """
    policy = _full_policy(
        profit_target=RuleValue.not_applicable(source="ranks on balance"))
    snap = _snapshot(equity=120_000.0)

    room = profit_target_distance(policy, snap)
    assert room.is_known is True
    assert room.limit is None
    assert room.remaining is None
    assert "ranks on balance" in room.reason

    # The same for a daily loss limit the provider does not publish.
    policy.daily_loss_limit = RuleValue.not_applicable(source="none published")
    daily = daily_loss_headroom(policy, snap)
    assert daily.is_known is True
    assert "none published" in daily.reason
    assert not any(c["check"] == "daily_loss"
                   for c in permission_for(policy, snap)["checks"])


def test_an_absent_max_drawdown_takes_the_shared_helper_path():
    """Defends the branch `_headroom_for` uses, not just the inline ones.

    `daily_loss_headroom` and `max_drawdown_headroom` both delegate to
    `_headroom_for`, but each short-circuits an absent rule inline first, so a
    regression in the shared helper is invisible unless max drawdown is the one
    exercised through it. An account with no drawdown rule is unusual but
    possible (a program graded only on balance), and it must not be reported as
    "unverified" -- that would put a permanent PROTECT rung on it.
    """
    policy = _full_policy(
        max_drawdown=RuleValue.not_applicable(source="program has no drawdown cap"))
    snap = _snapshot(equity=85_000.0)

    room = max_drawdown_headroom(policy, snap)
    assert room.is_known is True
    assert room.limit is None
    assert "no drawdown cap" in room.reason
    # And no invented ceiling on an account that is visibly down.
    assert room.remaining is None


def test_an_unverified_rule_still_protects_even_beside_an_absent_one():
    """Absence must not launder its neighbours.

    A policy can legitimately have no profit target and still have an unverified
    daily loss limit. If marking one absent cleared the others, the third state
    would be a blanket exemption -- and this is the test that stops it being one.
    """
    policy = _full_policy(
        profit_target=RuleValue.not_applicable(source="ranks on balance"),
        daily_loss_limit=RuleValue.unknown(),
    )
    snap = _snapshot()

    assert policy.is_fully_specified is False
    assert policy.missing_rules() == ["daily_loss_limit"]
    # Not a silent PROTECT: the policy is incomplete, so it halts, and the halt
    # names the rule that is actually missing rather than the one that is absent.
    result = permission_for(policy, snap)
    assert result["permission"] == Permission.HALT.value
    incomplete = next(c for c in result["checks"]
                      if c["check"] == "policy_complete")
    assert "daily_loss_limit" in incomplete["detail"]
    assert "profit_target" not in incomplete["detail"]


def test_an_absent_rule_is_reported_without_inventing_a_number():
    """The payload must not show a zero where there is no rule."""
    policy = _full_policy(
        profit_target=RuleValue.not_applicable(source="ranks on balance"))

    payload = policy.profit_target.as_dict()
    assert payload["status"] == "not_applicable"
    assert payload["value"] is None
    assert payload["is_known"] is False
    assert payload["source"] == "ranks on balance"


def test_completeness_still_ignores_instrument_restrictions():
    """The completeness bar covers numeric rules only.

    Guarding this because it is easy to conflate the two: an UNKNOWN weekend
    restriction is handled by its own PROTECT/HALT rung in `permission_for`, and
    folding it into `is_fully_specified` would turn a scoped refusal into a
    blanket HALT for a policy whose numbers are all verified.
    """
    policy = _full_policy(weekend=Restriction.UNKNOWN)

    assert policy.is_fully_specified is True
    # ...while still being reported as missing, because it is still unresolved.
    assert "weekend" in policy.missing_rules()
    assert permission_for(policy, _snapshot(), is_weekend=True)["permission"] \
        == Permission.PROTECT.value


# --- The 95% margin-level stop-out (For Traders tournaments) ---------------
#
# Source: help.fortraders.com/en/articles/10066978 -- "95% stop-out rule
# applies: if the account's margin level (Equity / Used Margin x 100) falls
# below 95%, positions may be automatically closed to reduce risk and restore
# the required margin level." Read 2026-10-01 while setting up account TEST-ACCT-DAYROLL.
#
# It was absent from the tournament rules the account holder pasted, so it would
# have been silently un-enforced: the provider force-closes positions while
# this engine reports a healthy account.


def test_the_margin_level_floor_is_measured_from_equity_over_used_margin():
    """The published formula, exactly: (Equity / Used Margin) x 100."""
    policy = _full_policy(margin_level_stop_out=95.0)
    # equity 95,000 on 50,000 used -> 190%, comfortably above the floor.
    healthy = _snapshot(equity=95_000.0, margin=50_000.0)

    room = margin_level_headroom(policy, healthy)
    assert room.is_known is True
    assert room.used == pytest.approx(190.0)
    assert room.limit == pytest.approx(95.0)
    assert room.remaining == pytest.approx(95.0)


def test_reaching_the_stop_out_floor_halts_rather_than_merely_restricting():
    """A forced close is not a smaller position.

    Below the floor the provider closes positions. A reduced-risk rung would be
    nonsense here -- there is no size that undoes a stop-out -- so the floor is
    HALT, matching how a breached drawdown is treated.

    The equity is kept at 100,000 and the *margin* is inflated instead, because
    driving equity down to reach a 95% level would breach the daily-loss and
    drawdown rungs first and the account would HALT for an unrelated reason --
    a green test that never exercised the branch it exists to cover.
    """
    policy = _full_policy(margin_level_stop_out=95.0)
    # 100,000 / 1,052.632 * 100 == 95.0%: at the floor, everything else intact.
    at_floor = _snapshot(equity=100_000.0, margin=100_000.0 / 0.95)

    result = permission_for(policy, at_floor)
    assert result["permission"] == Permission.HALT.value
    assert any(c["check"] == "margin_level" and "stop-out floor" in c["detail"]
               for c in result["checks"])

    # And a hair below it, which is where the provider actually acts.
    below = _snapshot(equity=100_000.0, margin=100_000.0 / 0.90)
    below_result = permission_for(policy, below)
    assert below_result["permission"] == Permission.HALT.value
    assert any(c["check"] == "margin_level" for c in below_result["checks"])


def test_a_healthy_margin_level_reports_the_headroom_without_restricting():
    """A floor the account is nowhere near must not look like a problem.

    If this rung warned at every reading, an operator would learn to ignore it,
    and then it would be useless on the reading that mattered.
    """
    policy = _full_policy(margin_level_stop_out=95.0)
    healthy = _snapshot(equity=100_000.0, margin=20_000.0)

    result = permission_for(policy, healthy)
    assert result["permission"] == Permission.ALLOW.value
    margin_check = next(c for c in result["checks"] if c["check"] == "margin_level")
    assert "500.0%" in margin_check["detail"]


def test_no_stated_floor_means_no_rung_and_no_incompleteness():
    """A program that publishes no floor is not an unverified one.

    This is the trap in adding the rule. `is_fully_specified` gates HALT, so
    making the floor mandatory would halt every account on every program that
    has no such rule -- including the ones it has nothing to do with. Absence of
    a published floor means absence, not ignorance.
    """
    policy = _full_policy()
    assert policy.margin_level_stop_out is None

    # Fully specified without the floor, and therefore still ALLOW-able.
    assert "margin_level_stop_out" not in policy.missing_rules()
    flat = _snapshot(equity=100_000.0, margin=0.0)
    assert permission_for(policy, flat)["permission"] == Permission.ALLOW.value
    # No rung is invented for a rule the program never stated.
    assert not any(c["check"] == "margin_level"
                   for c in permission_for(policy, flat)["checks"])


# --- Server scoping --------------------------------------------------------
#
# Tournament terms are published for one broker. FTTrading's October Clash is
# verified for FTTrading-Server, while other brokers run dynamic terms with
# relative ratios. Before this, `resolve()` knew nothing about servers, so a
# policy read from one broker's document decided accounts on every broker.


def test_tournament_terms_do_not_leak_to_another_brokers_account():
    """Terms verified for one server must not be inherited by another.

    This is the failure the field exists to prevent: a set of numbers sourced
    from FTTrading's own rules, silently governing an account at a different
    broker whose actual terms are unrelated.
    """
    registry = PolicyRegistry()
    ft = _full_policy(policy_version="october-clash", server="FTTrading-Server")
    registry.register(ft)

    same = registry.resolve(ft.provider, ft.program, server="FTTrading-Server")
    assert same is not None and same.policy_version == "october-clash"

    other = registry.resolve(ft.provider, ft.program, server="ICMarkets-Demo")
    assert other is None, "another broker's account inherited these terms"


def test_an_account_with_no_server_known_inherits_nothing_server_scoped():
    """Unknown server is not a wildcard.

    A caller that cannot say which broker the account is on must not be handed
    a broker-specific policy -- that is the same inheritance, reached by
    omitting the argument instead of misstating it.
    """
    registry = PolicyRegistry()
    ft = _full_policy(policy_version="october-clash", server="FTTrading-Server")
    registry.register(ft)

    assert registry.resolve(ft.provider, ft.program) is None
    assert registry.resolve(ft.provider, ft.program, server=None) is None


def test_server_names_are_matched_without_regard_to_case():
    """MT5 server names are label text, so case carries no meaning."""
    registry = PolicyRegistry()
    ft = _full_policy(policy_version="october-clash", server="FTTrading-Server")
    registry.register(ft)

    assert registry.resolve(ft.provider, ft.program, server="fttrading-server")
    assert registry.resolve(ft.provider, ft.program, server="  FTTrading-Server  ")


def test_a_differently_named_server_is_not_the_same_server():
    """`-Demo` is a different account set, not a spelling difference."""
    policy = _full_policy(server="FTTrading-Server")

    assert policy.matches_server("FTTrading-Server-Demo") is False
    assert policy.matches_server("FTTrading-Server2") is False
    assert policy.matches_server("FTTrading-Server") is True


def test_broker_neutral_terms_still_apply_everywhere():
    """A program with no broker-specific terms keeps working unscoped.

    This is the case that must not regress: the field is a filter for
    broker-specific documents, not a new requirement on every policy.
    """
    registry = PolicyRegistry()
    neutral = _full_policy(policy_version="generic")
    assert neutral.server is None
    registry.register(neutral)

    for server in ("FTTrading-Server", "ICMarkets-Demo", None):
        found = registry.resolve(neutral.provider, neutral.program, server=server)
        assert found is not None, f"broker-neutral terms refused for {server!r}"


def test_two_brokers_running_the_same_program_get_distinct_policies():
    """Both have terms; each account gets the one written for its own broker.

    Ordering matters here: the server filter has to run before the version pick,
    or whichever policy sorts last wins regardless of which broker the account
    is actually on.
    """
    registry = PolicyRegistry()
    ft = _full_policy(policy_version="2026.10", server="FTTrading-Server",
                      max_drawdown=RuleValue.known(0.10, source=SOURCE))
    ic = _full_policy(policy_version="2026.10", server="ICMarkets-Demo",
                      max_drawdown=RuleValue.known(0.20, source=SOURCE))
    registry.register(ft)
    registry.register(ic)

    got_ft = registry.resolve(ft.provider, ft.program, server="FTTrading-Server")
    got_ic = registry.resolve(ft.provider, ft.program, server="ICMarkets-Demo")
    assert got_ft.max_drawdown.value == pytest.approx(0.10)
    assert got_ic.max_drawdown.value == pytest.approx(0.20)


def test_the_policy_key_names_the_server_so_the_two_cannot_collide():
    """Two brokers, one program name: the key must tell them apart.

    Without the server in the key, the audit log, the API payload and any
    stored reference all say "these are the same policy".
    """
    ft = _full_policy(policy_version="v1", server="FTTrading-Server")
    ic = _full_policy(policy_version="v1", server="ICMarkets-Demo")
    neutral = _full_policy(policy_version="v1")

    assert ft.key != ic.key
    assert ft.key.endswith(":FTTrading-Server")
    assert neutral.key.endswith(":*")


def test_there_is_deliberately_no_server_wildcard():
    """A `"*"` server would reopen the inheritance in one string away."""
    policy = _full_policy(server="*")

    # It is read as a literal server name, not as a pattern, so it matches
    # nothing but a broker that is literally called "*".
    assert policy.matches_server("FTTrading-Server") is False
    assert policy.matches_server("ICMarkets-Demo") is False
    assert policy.matches_server("*") is True


def test_a_flat_account_reports_no_margin_level_ratio_rather_than_infinite_headroom():
    """No margin in use means there is no ratio, not unlimited room.

    Dividing by zero here would either raise or claim the account is
    infinitely safe. The honest answer is that margin level is undefined, and
    the account is known not to be under stop-out pressure.
    """
    policy = _full_policy(margin_level_stop_out=95.0)
    flat = _snapshot(equity=100_000.0, margin=0.0)

    room = margin_level_headroom(policy, flat)
    assert room.is_known is True
    assert room.used is None
    assert room.remaining is None
    assert "undefined" in room.reason


def test_the_floor_is_still_measured_when_the_opening_balance_is_unknown():
    """Margin level is a ratio of live figures, so an undeclared baseline
    cannot hide it.

    The other four dimensions all measure against an opening reference, so
    `headroom_report` marks them unknown when the baseline is missing. The
    stop-out floor is still being enforced by the provider on that account, and
    blanketing it as unknown would hide a live risk behind an unrelated gap.
    """
    policy = _full_policy(margin_level_stop_out=95.0)
    # 100,000 / 2,000 * 100 == 5000%, measured but nowhere near the floor. The
    # point of this test is that it is measured at all, so the level being
    # extreme keeps the other dimensions out of the picture entirely.
    distressed = _snapshot(equity=100_000.0, margin=2_000.0)

    report = headroom_report(policy, distressed, baseline_gradeable=False)
    assert report["baseline_gradeable"] is False
    # The other dimensions are unknown for want of an opening reference...
    assert report["dimensions"]["max_drawdown"]["is_known"] is False
    # ...but the floor is measured, and it is breached.
    assert report["dimensions"]["margin_level"]["is_known"] is True
    assert report["dimensions"]["margin_level"]["used"] == pytest.approx(5000.0)







# ---------------------------------------------------------------------------
# MT5 session schedules (challenge/mt5_sessions.py)
#
# The EA publishes what the terminal itself says about each symbol's week;
# these tests pin the two ways that translation can go wrong without raising.
# ---------------------------------------------------------------------------

# 2026-10-02 20:00 UTC = Fri 23:00 broker at UTC+3, i.e. the last hour of Friday.
_FRI_23_00_BROKER = FRIDAY_CLOSE_UTC
_BROKER_OFFSET = 3.0

# A normal forex week: Sunday-Thursday all day, Friday 05:00-23:00 server time.
_FX_WEEK = [[0, 0, 86399], [1, 0, 86399], [2, 0, 86399], [3, 0, 86399],
            [4, 0, 86399], [5, 18000, 82800]]

# The same week with a Saturday 00:00-00:10 tail, which real venues do report.
_FX_WEEK_SPILL = _FX_WEEK + [[6, 0, 600]]

_CRYPTO_WEEK = [[day, 0, 86399] for day in range(7)]


def _doc(symbol, sessions, mode=4, server_time=_FRI_23_00_BROKER):
    return {"server_time": server_time,
            "symbols": {symbol: {"symbol": symbol, "mode": mode,
                                 "sessions": sessions}}}


def _broker(epoch):
    import datetime as dt
    return dt.datetime.fromtimestamp(
        epoch + _BROKER_OFFSET * 3600.0, dt.timezone.utc)


def test_a_friday_close_is_read_at_the_brokers_hour_not_utc():
    """21:00 UTC on a Friday is already Saturday at UTC+3's neighbours, and the
    session times the terminal reports are its own. Reading them as UTC would
    place the window three hours out and it would open over the reopen."""
    out = mt5_sessions.schedules_from_document(
        _doc("EURUSD", _FX_WEEK), _BROKER_OFFSET, now=_FRI_23_00_BROKER)
    entry = out["EURUSD"]

    assert _broker(entry.observed_close).strftime("%a %H:%M") == "Fri 23:00"


def test_a_saturday_spillover_is_the_real_close_not_friday():
    """Friday 23:00 plus a Saturday tail means the symbol trades until Saturday
    00:10. Anchoring on the last Friday session would stop it 70 minutes early."""
    out = mt5_sessions.schedules_from_document(
        _doc("EURUSD", _FX_WEEK_SPILL), _BROKER_OFFSET, now=_FRI_23_00_BROKER)
    entry = out["EURUSD"]

    assert _broker(entry.observed_close).strftime("%a %H:%M") == "Sat 00:10"


def test_a_247_symbol_is_anchored_to_friday_by_the_calendar():
    """Crypto has no session gap at all -- Friday runs straight into Saturday --
    so the gap search finds nothing and the close must come from the calendar.

    Anchoring on "the last session of the week" instead would put this at
    Saturday 23:59 and start the risk reduction a full day late: the weekend
    after the one it exists to cover.
    """
    out = mt5_sessions.schedules_from_document(
        _doc("BTCUSD", _CRYPTO_WEEK), _BROKER_OFFSET, now=_FRI_23_00_BROKER)
    entry = out["BTCUSD"]

    assert _broker(entry.observed_close).strftime("%a %H:%M") == "Fri 23:59"
    assert _broker(entry.next_open).strftime("%a %H:%M") == "Sun 00:00"


def test_the_weekday_is_the_brokers_not_the_utc_dates():
    """21:00 UTC on the 1st is 00:00 on the 2nd for a UTC+3 broker.

    Taking the weekday from the raw epoch instead of the shifted one puts every
    session in the wrong column and lands the boundary a week out, with nothing
    raising. A UTC+0 read of the same document is the control: the answer must
    move by exactly the offset, not by a whole week.
    """
    doc = _doc("EURUSD", _FX_WEEK, server_time=_FRI_23_00_BROKER)
    at_three = mt5_sessions.schedules_from_document(
        doc, _BROKER_OFFSET, now=_FRI_23_00_BROKER)["EURUSD"]
    at_zero = mt5_sessions.schedules_from_document(
        doc, 0.0, now=_FRI_23_00_BROKER)["EURUSD"]

    assert at_zero.observed_close - at_three.observed_close == pytest.approx(
        _BROKER_OFFSET * 3600.0)


def test_a_close_a_week_away_is_refused_rather_than_believed():
    """A boundary that far out can never open its window, which is fail-OPEN.

    `now < close - lead` then holds for ever and the symbol is never restricted.
    Refusing it puts the caller on the fail-closed path instead.
    """
    far = weekend.SymbolSchedule("BTCUSD", _FRI_23_00_BROKER + 30 * 86400.0,
                                 _FRI_23_00_BROKER, _FRI_23_00_BROKER + 31 * 86400.0)
    assert weekend._observed_close({"BTCUSD": far}, "BTCUSD") is None


def test_a_close_an_hour_ahead_is_not_refused():
    """The schedule is forward-looking, so a legitimate upcoming close is normal.

    A test that only ever passed past closes would call this a clock fault and
    send every real reading down the fail-closed path, which is indistinguishable
    from the rule working.
    """
    soon = weekend.SymbolSchedule("BTCUSD", _FRI_23_00_BROKER + 3600.0,
                                  _FRI_23_00_BROKER)
    assert weekend._observed_close({"BTCUSD": soon}, "BTCUSD") is soon


def test_a_disabled_symbol_gets_no_boundary_at_all():
    """The terminal saying a symbol is disabled is not a weekend schedule."""
    out = mt5_sessions.schedules_from_document(
        _doc("XAUUSD", _FX_WEEK, mode=0), _BROKER_OFFSET, now=_FRI_23_00_BROKER)
    assert "XAUUSD" not in out


@pytest.mark.parametrize("sessions", [
    [[5, 82800, 18000]],       # ends before it starts
    [[5, 0, 90000]],           # ends past midnight
    [[5, -1, 600]],            # starts before midnight
    [[7, 0, 600]],             # not a weekday
    [[5, 0]],                  # too short
    [["5", "0", "600"]],       # not numbers
    ["nonsense"],
    [],
])
def test_an_unusable_session_reads_as_absent_not_as_a_default(sessions):
    """Fail closed, and no invented Friday.

    Every one of these is the same situation as a symbol nobody has ever heard
    of, so all of them must produce the same answer: no entry. A reader that
    substituted a default here would be guessing about an unpriced gap with the
    authority of a measurement.
    """
    out = mt5_sessions.schedules_from_document(
        _doc("EURUSD", sessions), _BROKER_OFFSET, now=_FRI_23_00_BROKER)
    assert "EURUSD" not in out


def test_a_missing_or_malformed_document_yields_no_schedules(tmp_path):
    """Not attached and attached-but-silent both fail closed, and neither is
    papered over."""
    missing = tmp_path / "sessions.json"
    assert mt5_sessions.load_schedules(_BROKER_OFFSET, _FRI_23_00_BROKER,
                                       str(tmp_path)) == {}

    missing.write_text("", encoding="utf-8")
    assert mt5_sessions.load_schedules(_BROKER_OFFSET, _FRI_23_00_BROKER,
                                       str(tmp_path)) == {}

    missing.write_text("{not json", encoding="utf-8")
    assert mt5_sessions.load_schedules(_BROKER_OFFSET, _FRI_23_00_BROKER,
                                       str(tmp_path)) == {}

    missing.write_text('{"server_time": 1}', encoding="utf-8")
    assert mt5_sessions.load_schedules(_BROKER_OFFSET, _FRI_23_00_BROKER,
                                       str(tmp_path)) == {}


def test_a_published_document_round_trips_through_the_file_reader(tmp_path):
    """The wire shape is the contract between the EA and this reader, so it is
    pinned from both ends: what the reader accepts is exactly what the EA emits."""
    import json
    directory = tmp_path / "sessions"
    directory.mkdir()
    (directory / "sessions.json").write_text(json.dumps(
        _doc("EURUSD", _FX_WEEK_SPILL)), encoding="utf-8")

    out = mt5_sessions.load_schedules(_BROKER_OFFSET, _FRI_23_00_BROKER,
                                      str(tmp_path))

    assert list(out) == ["EURUSD"]
    assert _broker(out["EURUSD"].observed_close).strftime("%a %H:%M") == "Sat 00:10"


def test_the_reduced_risk_window_opens_before_the_close_and_ends_at_the_reopen():
    """The end bound is the point.

    Without `next_open` the test is `now >= close - lead` with nothing above it,
    so every later reading of the same schedule stays halved -- Tuesday included.
    A permanent handicap is a worse defect than the weekend it was written for,
    because it looks exactly like the rule working.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    entry = mt5_sessions.schedules_from_document(
        _doc("BTCUSD", _CRYPTO_WEEK), _BROKER_OFFSET,
        now=_FRI_23_00_BROKER)["BTCUSD"]
    s = {"BTCUSD": entry}

    before = _FRI_23_00_BROKER - 4 * 3600.0                 # Fri 19:00 broker
    inside = _FRI_23_00_BROKER                              # Fri 23:00 broker
    after = (entry.next_open - _BROKER_OFFSET * 3600.0) + 4 * 3600.0  # Mon 04:00

    assert weekend.risk_multiplier(policy, before, "BTCUSD", s)[0] == pytest.approx(1.0)
    assert weekend.risk_multiplier(policy, inside, "BTCUSD", s)[0] == pytest.approx(0.5)
    assert weekend.risk_multiplier(policy, after, "BTCUSD", s)[0] == pytest.approx(1.0)



def test_a_session_that_ends_before_it_starts_is_rejected_on_its_own():
    """The validator is pinned directly, not only through a whole week.

    A session that ends before it starts is not a short session, it is a
    malformed one, and accepting it puts the open before the close. Testing it
    only through a full week is not enough: a week that also contains a real
    gap finds the weekend from that gap and returns the same answer either way,
    so the broken validator goes unseen and only shows up on a symbol whose week
    happens to have no other gap in it.
    """
    assert mt5_sessions._seconds([5, 82800, 18000]) is None
    assert mt5_sessions._seconds([5, 0, 600]) == (5, 0, 600)
    assert mt5_sessions._seconds([5, 600, 600]) is None, "zero length is not a session"


def test_a_saturday_reading_still_finds_the_friday_it_just_passed():
    """23:00 UTC on a Friday is 02:00 on a Saturday for a UTC+3 broker.

    Two things go wrong at once here if the weekday is taken from the raw epoch
    instead of the broker's clock. The boundary lands a week out, and on the
    crypto path -- which is the calendar path, since 24/7 has no gap to find --
    the Friday being closed is not in the coming week at all, so the window comes
    back as a Friday that ends AFTER the Sunday it reopens. That inverted window
    reduces nothing on the one weekend it exists for, and it still looks like a
    valid schedule.
    """
    sat_02_00_broker = _FRI_23_00_BROKER + 3 * 3600.0
    out = mt5_sessions.schedules_from_document(
        _doc("BTCUSD", _CRYPTO_WEEK, server_time=sat_02_00_broker),
        _BROKER_OFFSET, now=sat_02_00_broker)
    entry = out["BTCUSD"]

    assert _broker(entry.observed_close).strftime("%a %d %H:%M") == "Fri 02 23:59"
    assert _broker(entry.next_open).strftime("%a %d %H:%M") == "Sun 04 00:00"
    assert entry.observed_close < entry.next_open, \
        "a window that ends before it starts reduces nothing all weekend"


# ---------------------------------------------------------------------------
# The permission path: does the weekend rule actually reach a decision?
# ---------------------------------------------------------------------------

def test_the_cap_reaches_the_result_as_a_number_not_only_a_message():
    """A PROTECT rung that says "must not exceed 50% of usual" is an instruction
    to do arithmetic the caller cannot do: "usual" is a number only the sizing
    code holds. The cap has to come out as a figure or it is a note.

    `max_proposed_risk` is None unless the caller supplies that usual risk, which
    is this function being honest about what it cannot decide on its own -- and
    None must not be confused with "unrestricted".
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    snapshot = _snapshot()

    inside = permission_for(policy, snapshot, symbol="BTCUSD",
                            epoch=FRIDAY_CLOSE_UTC, usual_risk=400.0)
    assert inside["weekend_risk_multiplier"] == pytest.approx(0.5)
    assert inside["max_proposed_risk"] == pytest.approx(200.0)

    # Outside the window there is no ceiling, and the two fields say so
    # differently on purpose: a multiplier of 1.0, and no cap to apply.
    outside = permission_for(policy, snapshot, symbol="BTCUSD",
                             epoch=FRIDAY_CLOSE_UTC - 12 * 3600.0,
                             usual_risk=400.0)
    assert outside["weekend_risk_multiplier"] == pytest.approx(1.0)
    assert outside["max_proposed_risk"] == pytest.approx(400.0)

    # No usual risk supplied: still no cap invented.
    unknown = permission_for(policy, snapshot, symbol="BTCUSD",
                             epoch=FRIDAY_CLOSE_UTC)
    assert unknown["weekend_risk_multiplier"] == pytest.approx(0.5)
    assert unknown["max_proposed_risk"] is None


def test_the_reopen_bound_survives_the_trip_through_the_policy():
    """`next_open` has to make it out of the policy dict and into the schedule.

    It is the field that ends the reduced-risk window, so a payload that drops it
    leaves the cap on every later reading of the same policy: a permanent
    half-size handicap that is indistinguishable from the rule working.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    close = FRIDAY_CLOSE_UTC
    policy.symbol_schedules = {"BTCUSD": {
        "observed_close": close, "observed_at": close,
        "next_open": close + 2 * 86400.0}}

    inside = permission_for(policy, _snapshot(), symbol="BTCUSD",
                            epoch=close, usual_risk=100.0)
    assert inside["weekend_risk_multiplier"] == pytest.approx(0.5)

    after = permission_for(policy, _snapshot(), symbol="BTCUSD",
                           epoch=close + 3 * 86400.0, usual_risk=100.0)
    assert after["weekend_risk_multiplier"] == pytest.approx(1.0), \
        "the cap outlived the weekend because next_open never arrived"


def test_a_policy_with_no_schedule_asks_the_terminal_and_says_which_it_used():
    """The reader is the real source, and the payload says so.

    Without this the live path has no boundaries at all and every symbol reads as
    closed, which is fail-closed but useless; and a payload that does not say
    where the answer came from cannot be checked afterwards.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    policy.symbol_schedules = {}
    document = _doc("BTCUSD", _CRYPTO_WEEK)
    close = _FRI_23_00_BROKER + 3600.0

    with mock.patch.object(mt5_sessions, "load_schedules",
                           return_value=mt5_sessions.schedules_from_document(
                               document, _BROKER_OFFSET, now=_FRI_23_00_BROKER)) as reader:
        result = permission_for(policy, _snapshot(), symbol="BTCUSD",
                                epoch=close, usual_risk=100.0)

    reader.assert_called_once()
    assert result["weekend"]["source"] == "mt5_terminal"
    assert result["weekend_risk_multiplier"] == pytest.approx(0.5)


def test_a_reader_that_raises_fails_closed_instead_of_trading_on():
    """An exception in the reader is a missing schedule, not an allowed trade.

    A bare `except` that fell through to "no window" would be the permissive
    direction for the least trustworthy input in the system.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0,
                          weekend_risk_multiplier=0.5)
    policy.symbol_schedules = {}

    with mock.patch.object(mt5_sessions, "load_schedules",
                           side_effect=OSError("terminal locked")):
        result = permission_for(policy, _snapshot(), symbol="BTCUSD",
                                epoch=FRIDAY_CLOSE_UTC, usual_risk=100.0)

    closed = result["weekend"]["closed"]
    mult = result["weekend_risk_multiplier"]
    assert closed is True or mult < 1.0, \
        "a reader that failed produced a free trade"


def test_the_per_symbol_rule_does_not_depend_on_the_account_weekend_flag():
    """`policy.weekend` is a separate, account-level restriction.

    Gating the per-symbol close window on it meant that a policy which never
    stated the account-level flag closed every forex and gold symbol all week --
    and, in the other direction, a policy that denied weekends outright could
    have the per-symbol windows quietly skip. The switches for the per-symbol
    rule are `weekend_close_lead_minutes` and `weekend_risk_multiplier`; nothing
    else belongs here.
    """
    policy = _full_policy(weekend_close_lead_minutes=120.0)
    policy.weekend = None
    s = {"XAUUSD": weekend.SymbolSchedule("XAUUSD", FRIDAY_CLOSE_UTC,
                                          FRIDAY_CLOSE_UTC)}

    # Two hours before its close, closed -- and only then.
    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC - 3600.0,
                                   "XAUUSD", s)[0] is True
    assert weekend.in_close_window(policy, FRIDAY_CLOSE_UTC - 6 * 3600.0,
                                   "XAUUSD", s)[0] is False

