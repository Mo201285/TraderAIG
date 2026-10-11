"""Risk headroom: how much room is left in this account, right now.

34.8 lays out the shape (limit -> used -> remaining -> proposed -> buffer ->
decision) and, more usefully, the rule that makes it a control rather than a
display: *a strategy signal cannot override insufficient account headroom.*

Two things make this hard to get right, and both are about honesty under
uncertainty.

**Floating vs static drawdown.** They are not the same limit with different
wording, and conflating them produces the worst error available here -- an
engine that reports headroom to an account that has already breached. On a
static account the floor is the opening equity and never moves; a trader can
lose 4%, recover it, and be finished. The used amount is therefore
`max(0, static_floor - equity)`, a high-water mark in reverse, and it never
decreases. On a floating account the floor is the running minimum of equity
since the day rolled, so recovery genuinely restores room. Reading `equity`
against `balance`, or against peak equity, gets a static account wrong in
exactly the situation where the answer matters.

**The buffer is not padding.** 34.8 ends with a safety buffer before the
governance decision. A buffer expressed as a fraction of the limit is the
difference between a rule that is technically satisfied and one that survives
the slippage of a real fill, so it is applied to the *remaining* room and the
result is what the trade is measured against.

Every method returns a `Headroom` whose `is_known` is False when the policy
rule behind it was never verified. That is the point: an unverified rule yields
no number at all, and `permission_for()` turns that into PROTECT.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .policy import ChallengePolicy, DrawdownType, Restriction, RuleValue

log = logging.getLogger("challenge.headroom")


class Permission(str, Enum):
    """The 34.7 permission ladder, most-permissive first.

    Kept as an ordered enum because 34.12 says the most restrictive valid
    constraint takes precedence, and "most restrictive" is only well defined if
    there is a total order to reduce with. Every evaluator contributes a
    permission and the minimum wins, so a new check cannot accidentally widen
    the decision by being written as an early return.
    """

    ALLOW = "allow"
    ALLOW_REDUCED_RISK = "allow_reduced_risk"
    ALLOW_ONLY_HIGH_QUALITY = "allow_only_high_quality"
    RESTRICT = "restrict"
    PROTECT = "protect"
    HALT = "halt"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]


_SEVERITY = {
    Permission.ALLOW: 0,
    Permission.ALLOW_REDUCED_RISK: 1,
    Permission.ALLOW_ONLY_HIGH_QUALITY: 2,
    Permission.RESTRICT: 3,
    Permission.PROTECT: 4,
    Permission.HALT: 5,
}


@dataclass
class Headroom:
    """Remaining room for one dimension, or the fact that it is unknown.

    `used` and `limit` are Optional because "we do not know the limit" has no
    numeric form. Reporting 0.0 would be a lie of a different kind -- it would
    claim the trader has already used their whole allowance.
    """

    limit: Optional[float] = None
    used: Optional[float] = None
    remaining: Optional[float] = None
    buffer: Optional[float] = None
    is_known: bool = False
    reason: Optional[str] = None
    # True when the limit this reports was read from a source we can name.
    # Not part of `is_known`: an unsourced limit is still a limit and is still
    # enforced. A remembered 95% stop-out protects the account exactly as well as
    # a documented one, so refusing to compute it would be the unsafe choice --
    # but presenting it with the same confidence as a cited term would be the
    # dishonest one. Enforced regardless, flagged either way.
    source_confirmed: Optional[bool] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "limit": self.limit,
            "used": self.used,
            "remaining": self.remaining,
            "buffer": self.buffer,
            "is_known": self.is_known,
            "reason": self.reason,
            "source_confirmed": self.source_confirmed,
        }

    @classmethod
    def unverified(cls, dimension: str, reason: str) -> "Headroom":
        """A dimension we refuse to compute, with the dimension named.

        The name is carried in the reason rather than as its own field so the
        payload shape stays identical to a computed dimension -- a dashboard
        adapter renders one of these without needing to know which branch it is
        looking at, and a reason that says which limit went unmeasured is more
        use to an operator than a bare `is_known: false`.
        """
        return cls(is_known=False,
                   reason=f"{dimension}: {reason}")


@dataclass
class AccountSnapshot:
    """The account facts the headroom math consumes.

    Deliberately a plain snapshot rather than a live read of `core.state`: the
    math must be testable against known numbers, and 34.11's requirement that
    challenge accounts use the same engines is satisfied by whoever *builds*
    this snapshot from the canonical state, not by the calculator reaching into
    it.
    """

    account_id: str
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    open_risk: float = 0.0
    day_start_equity: Optional[float] = None
    day_low_equity: Optional[float] = None
    start_equity: Optional[float] = None
    # The account's all-time equity low. This is the field that makes a STATIC
    # drawdown static, and it cannot be derived from any snapshot: a snapshot is
    # a moment, and the one number that decides a static account is what equity
    # was at its *worst* moment, possibly days ago. Reconstructing it from
    # `equity` at read time reports a fully recovered account as untouched --
    # which is precisely the account the rule exists to catch.
    equity_low: Optional[float] = None
    # The account's all-time equity PEAK. Like `equity_low` this cannot be
    # derived from a snapshot -- a snapshot is a moment, and the number that
    # decides a trailing account is where equity was at its *highest* moment,
    # possibly days before the day that breaches it. It is also monotonic in
    # the opposite direction: it only ever rises, and it must NOT be reset when
    # the day rolls, because a trailing floor that resets daily is not a
    # trailing rule, it is the floating rule wearing the wrong name.
    #
    # `equity_low` alone cannot stand in for it either. Their difference is
    # exactly what a trailing drawdown measures, so approximating the peak with
    # `day_start_equity` silently reports an account as having room whenever its
    # peak predates the day it breached on -- the most permissive possible
    # answer for the rule that exists to be the strictest.
    equity_peak: Optional[float] = None
    realized_pnl: float = 0.0
    trading_days: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def static_basis(self) -> float:
        """The equity the static drawdown rule measures down from.

        On a static-drawdown account this is the opening equity, and the amount
        "used" is `static_basis - equity_low`: the distance from where the
        account started to the worst point it has ever reached. It is not
        measured from current equity, which is the trap -- a trader who drops
        4% and recovers to flat has spent the whole allowance, and scoring it
        at `start - current` reports zero used on an account that is already
        finished.
        """
        for candidate in (self.start_equity, self.day_start_equity, self.balance):
            if candidate:
                return float(candidate)
        return float(self.equity or 0.0)

    @property
    def floating_basis(self) -> float:
        """The equity the daily/floating rule measures down from for the day."""
        for candidate in (self.day_start_equity, self.start_equity, self.balance):
            if candidate:
                return float(candidate)
        return float(self.equity or 0.0)

    @property
    def trailing_basis(self) -> float:
        """The equity the trailing rule measures down from: the high-water mark.

        Falls back to the widest plausible mark rather than to current equity,
        because every fallback here is at or above the current reading and the
        error direction of a drawdown limit must be the tight one. `balance` is
        last because it is the one figure that can sit above equity for reasons
        that have nothing to do with trader performance.
        """
        for candidate in (self.equity_peak, self.start_equity,
                          self.day_start_equity, self.balance):
            if candidate:
                return float(candidate)
        return float(self.equity or 0.0)

    @staticmethod
    def observe(snapshot: "AccountSnapshot") -> "AccountSnapshot":
        """Fold this observation into the snapshot's low- and high-water marks.

        The caller owns persistence of `equity_low`/`equity_peak` across
        snapshots; this only carries the current reading into the fields the
        calculator reads. Doing it here rather than inside the calculator is the
        whole point -- a calculator that tracks its own history has no history
        between calls.
        """
        equity = float(snapshot.equity or 0.0)
        if snapshot.equity_low is None or equity < float(snapshot.equity_low):
            snapshot.equity_low = equity
        if snapshot.day_low_equity is None or equity < float(snapshot.day_low_equity):
            snapshot.day_low_equity = equity
        if snapshot.equity_peak is None or equity > float(snapshot.equity_peak):
            snapshot.equity_peak = equity
        return snapshot

    def as_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "balance": self.balance,
            "equity": self.equity,
            "margin": self.margin,
            "open_risk": self.open_risk,
            "day_start_equity": self.day_start_equity,
            "day_low_equity": self.day_low_equity,
            "start_equity": self.start_equity,
            "equity_low": self.equity_low,
            "equity_peak": self.equity_peak,
            "realized_pnl": self.realized_pnl,
            "trading_days": self.trading_days,
            "timestamp": self.timestamp,
        }


# One row per `Restriction` member, so a member added later cannot fall through
# to "no rung" by omission. That omission was the defect: `permission_for`
# branched on UNKNOWN and DENIED only, so CONDITIONAL -- which the PUT handler
# accepts as a valid value -- matched neither branch and contributed nothing,
# and a policy reading "permitted subject to conditions" produced
# `permission: allow` on an instrument whose conditions nobody had evaluated.
#
# `None` therefore means exactly one thing: the program genuinely permits it.
# CONDITIONAL maps to PROTECT rather than ALLOW because the conditions are not
# evaluated anywhere in this engine, and a permission that depends on a
# condition we have not checked must not be reported as satisfied.
_RESTRICTION_RUNG: Dict[Restriction, Optional[Permission]] = {
    Restriction.ALLOWED: None,
    Restriction.DENIED: Permission.HALT,
    Restriction.UNKNOWN: Permission.PROTECT,
    Restriction.CONDITIONAL: Permission.PROTECT,
}


def _restriction_rung(value: Restriction) -> Optional[Permission]:
    """The rung a restriction contributes, or `None` if it permits outright.

    An unrecognised member fails closed. The permissive answer here is `None`,
    so anything that cannot be looked up must not return it -- otherwise the
    next member added to the enum repeats this bug exactly.
    """
    if not isinstance(value, Restriction):
        return Permission.PROTECT
    return _RESTRICTION_RUNG.get(value, Permission.PROTECT)


def _absent(rule: RuleValue, label: str) -> Headroom:
    """The `Headroom` for a rule the provider established does not exist.

    One place, because four callers each grew their own copy of this and a
    fifth unreachable copy ended up inside `_headroom_for` -- every caller
    short-circuits here before delegating, so that one looked load-bearing and
    was not. A branch nobody can reach is worse than no branch: it reads as
    handled, so the next person to change absence handling changes the wrong
    copy.

    `is_known=True` with every figure None is deliberate. The rule is not a
    mystery -- it is absent, and that is a stronger statement than unknown. The
    dashboard renders it as a named non-dimension instead of `--`, and no
    ceiling is fabricated for an account that has none.
    """
    return Headroom(is_known=True, limit=None, used=None, remaining=None,
                    reason=f"{label} not applicable to this program: "
                           f"{rule.source or 'no source recorded'}")


def _headroom_for(rule: RuleValue, used: float, *, buffer_fraction: float = 0.0,
                  limit_is_fraction: bool = False, reference: float = 0.0,
                  reason_if_unknown: str = "rule not verified") -> Headroom:
    """Shared headroom arithmetic, refusing to invent a limit.

    `limit_is_fraction` distinguishes the two ways these rules are published:
    "5% max drawdown" is a fraction of the reference equity, "3% daily loss" is
    usually a fraction of balance, and "10 trading days" is not a monetary
    quantity at all. Treating them all as plain amounts is how a headroom
    calculator starts comparing dollars to days.
    """
    if not rule.is_known:
        # Absence is handled by the caller via `_absent`, which runs before this
        # is ever reached. Left as a plain unknown so a not_applicable rule can
        # never be mistaken for a measurable one here.
        return Headroom(is_known=False, reason=reason_if_unknown)
    limit = float(rule.value)
    if limit_is_fraction:
        limit = limit * float(reference or 0.0)
    if limit <= 0:
        return Headroom(is_known=False,
                        reason="verified limit is not positive; refusing to score it")
    used = max(0.0, float(used))
    remaining = max(0.0, limit - used)
    return Headroom(
        limit=limit,
        used=used,
        remaining=remaining,
        buffer=remaining * float(buffer_fraction),
        is_known=True,
    )


def daily_loss_headroom(policy: ChallengePolicy, snapshot: AccountSnapshot, *,
                        buffer_fraction: float = 0.10) -> Headroom:
    """Room left under today's loss limit.

    Measured from the day's low, not from `equity`: a loss limit is about the
    worst point of the session, and a trader who dips and recovers has still
    spent the room. Measuring against current equity would hand the room back
    and invite exactly the behaviour the limit exists to prevent.
    """
    # `effective_daily_loss_limit`, not `policy.daily_loss_limit`: when the
    # operator has set a personal limit the strictest of the two is what is
    # actually enforced, and reading the provider's field directly here would
    # silently ignore it.
    limit = policy.effective_daily_loss_limit
    if not limit.is_known:
        if limit.is_not_applicable:
            return _absent(limit, "daily loss limit")
        return Headroom(is_known=False, reason="daily loss limit not verified")
    if policy.server_utc_offset_hours is None:
        # The limit itself is known, but the *day* it is measured against is
        # not, and the day is half the rule: a 3% allowance is a 3% of one
        # broker-day, and returning that allowance at the wrong midnight hands
        # back a full day of room every single day. Scored UNKNOWN rather than
        # defaulted to 0 because "we never established the offset" and "the
        # broker runs on UTC" are different facts and only one of them is safe.
        return Headroom(
            is_known=False,
            reason="daily loss limit cannot be scored: the broker's day "
                   "boundary is not established, so the allowance would reset "
                   "at an unknown hour")
    reference = snapshot.floating_basis
    # from the day's LOW, not from current equity: a trader who dips and
    # recovers has still spent the room, and measuring from current equity
    # hands it straight back -- inviting the behaviour the limit exists to stop
    low = float(snapshot.day_low_equity if snapshot.day_low_equity
                else snapshot.equity or 0.0)
    used = max(0.0, reference - low)
    return _headroom_for(limit, used,
                         buffer_fraction=buffer_fraction,
                         limit_is_fraction=True, reference=reference,
                         reason_if_unknown="daily loss limit not verified")


def max_drawdown_headroom(policy: ChallengePolicy, snapshot: AccountSnapshot, *,
                          buffer_fraction: float = 0.10) -> Headroom:
    """Room left under the drawdown limit, honouring how the provider measures it.

    Static accounts are scored against the opening equity and cannot regain
    room; floating accounts are scored against the day's low and can. Getting
    this backwards in the permissive direction is the specific failure that
    would let a breached account keep trading, so an unrecognised
    `drawdown_type` yields UNKNOWN rather than defaulting to either.
    """
    if not policy.max_drawdown.is_known:
        if policy.max_drawdown.is_not_applicable:
            # Before the basis, because with no cap there is nothing for a basis
            # to be measured against.
            return _absent(policy.max_drawdown, "max drawdown")
        return Headroom(is_known=False, reason="max drawdown not verified")
    if policy.drawdown_type is None:
        return Headroom(
            is_known=False,
            reason="drawdown basis unknown (static/floating/trailing); "
                   "scoring it would guess the rule that decides the account",
        )
    if policy.drawdown_type is DrawdownType.STATIC:
        # start -> worst point ever reached. Recovery does NOT restore it.
        reference = snapshot.static_basis
        low = float(snapshot.equity_low if snapshot.equity_low
                    else snapshot.equity or 0.0)
    elif policy.drawdown_type is DrawdownType.TRAILING:
        # highest point ever reached -> worst point ever reached. Like static,
        # recovery does NOT restore it, because the floor has already been set
        # at the peak and a breach is a breach. Unlike static, the floor itself
        # RISES with the peak, so the limit is a fraction of the high-water mark
        # rather than of the opening balance.
        #
        # Pairing the lifetime peak with the lifetime low is deliberate and
        # slightly conservative: the exact floor in force at the moment of the
        # low was the peak *as of that moment*, which this pair does not retain.
        # It can only ever overstate the loss -- a peak reached after the low
        # pulls the reference up -- and for a limit that decides whether an
        # account still exists, overstating is the direction to err in. The
        # alternative, persisting a peak/low pair, buys precision the rule does
        # not need at the price of a second number that can disagree with the
        # first.
        reference = snapshot.trailing_basis
        low = float(snapshot.equity_low if snapshot.equity_low
                    else snapshot.equity or 0.0)
    else:
        # day's start -> day's low. Recovery DOES restore this one.
        reference = snapshot.floating_basis
        low = float(snapshot.day_low_equity if snapshot.day_low_equity
                    else snapshot.equity or 0.0)
    used = max(0.0, reference - low)
    return _headroom_for(policy.max_drawdown, used,
                         buffer_fraction=buffer_fraction,
                         limit_is_fraction=True, reference=reference,
                         reason_if_unknown="max drawdown not verified")


def profit_target_distance(policy: ChallengePolicy, snapshot: AccountSnapshot, *,
                           buffer_fraction: float = 0.0) -> Headroom:
    """How far the account still has to travel to hit its profit target.

    `remaining` here is distance still to travel rather than room still
    available, so a positive value means "not there yet" -- the opposite
    polarity to the other two. That asymmetry is deliberate and the field is
    named `remaining` only because the API shape is shared; the sign is what
    tells a reader whether the target is ahead or behind.
    """
    if not policy.profit_target.is_known:
        if policy.profit_target.is_not_applicable:
            return _absent(policy.profit_target, "profit target")
        return Headroom(is_known=False, reason="profit target not verified")
    reference = snapshot.start_equity or snapshot.balance or snapshot.equity
    target = float(policy.profit_target.value) * float(reference or 0.0)
    achieved = float(snapshot.equity or 0.0) - float(reference or 0.0)
    return Headroom(
        limit=target,
        used=achieved,
        remaining=max(0.0, target - achieved),
        buffer=0.0,
        is_known=True,
    )


def _weekend_schedules(policy: ChallengePolicy, epoch: float
                       ) -> Dict[str, "Any"]:
    """Per-symbol weekend boundaries, preferring the terminal's own schedule.

    The policy's own `symbol_schedules` wins when it has one: an operator who
    states a boundary has said something the terminal cannot contradict. With
    none stated, the terminal is consulted through `challenge.mt5_sessions`, and
    if that is unreadable the result is EMPTY rather than a default.

    Empty is the whole point. A per-symbol close window with no boundary cannot
    be placed, and every symbol then reads as closed -- so a fallback that
    guessed a Friday would be the one thing able to make an unreadable schedule
    permissive. The empty mapping is what the weekend rules already know how to
    refuse.
    """
    from challenge import weekend as weekend_rules

    schedules = {k.upper(): weekend_rules.SymbolSchedule(
        symbol=k.upper(), observed_close=float(v.get("observed_close", 0.0)),
        observed_at=float(v.get("observed_at", 0.0)),
        # `next_open` is what ends the reduced-risk window. Dropping it here
        # would leave the risk cap with no upper bound, so it would still be
        # applied on Tuesday -- the same defect as having no cap at all, in the
        # direction of a permanent handicap rather than a missing protection.
        next_open=(None if v.get("next_open") is None
                   else float(v["next_open"])))
        for k, v in (policy.symbol_schedules or {}).items()}
    if schedules:
        return schedules

    try:
        from challenge import mt5_sessions

        offset = float(getattr(policy, "server_utc_offset_hours", 0.0) or 0.0)
        return mt5_sessions.load_schedules(offset, float(epoch))
    except Exception as exc:   # noqa: BLE001 - a reader failure must fail closed
        log.warning("MT5 session schedule unavailable (%s); weekend rules "
                    "fall back to closed", exc)
        return {}


def _weekend_terms_in_force(policy: ChallengePolicy) -> bool:
    """Whether this policy states per-symbol weekend behaviour at all.

    A policy that states none is not given one. That is the same reasoning as
    `configured_program`: inventing a Friday close for an account whose terms
    never mentioned a weekend would close every symbol at once, and the
    fail-closed reading of "no schedule can be read" is precisely "closed" --
    so the dimension has to be switched off, not merely left empty. An unknown
    weekend *term* is a different thing and is still reported by the
    completeness check, which restricts on its own.
    """
    return bool(policy.symbol_schedules
                or policy.weekend_close_lead_minutes is not None
                or policy.weekend_risk_multiplier is not None)


def _weekend_payload(policy: ChallengePolicy, epoch: float, symbol: str,
                     schedules: Optional[Dict[str, Any]] = None
                     ) -> Dict[str, Any]:
    """The weekend verdict for one symbol, as the payload carries it.

    `schedules` is passed in rather than re-derived: reading the terminal's
    published document is a file read and a parse, and doing it twice per
    permission check means every proposed trade reads it twice. `None` falls
    back to deriving it, so the function still stands alone for callers that
    only want the payload.
    """
    from challenge import weekend as weekend_rules

    if not _weekend_terms_in_force(policy):
        # No weekend behaviour is stated, so there is no window to place and
        # nothing to reduce. Reported as not-applicable rather than as an open
        # window, because "the policy says nothing" and "the policy permits the
        # weekend" are different facts and the payload is what a caller reads.
        return {"symbol": symbol,
                "asset_class": weekend_rules.classify(symbol),
                "closed": False,
                "risk_multiplier": 1.0,
                "close_reason": "policy states no per-symbol weekend behaviour",
                "risk_reason": "policy states no per-symbol weekend behaviour",
                "source": "not_applicable"}

    if schedules is None:
        schedules = _weekend_schedules(policy, epoch)
    closed, why = weekend_rules.in_close_window(policy, epoch, symbol, schedules)
    mult, mwhy = weekend_rules.risk_multiplier(policy, epoch, symbol, schedules)
    return {"symbol": symbol,
            "asset_class": weekend_rules.classify(symbol),
            "closed": closed,
            "risk_multiplier": mult,
            "close_reason": why,
            "risk_reason": mwhy,
            "source": "policy" if policy.symbol_schedules else "mt5_terminal"}


def _margin_floor_in_force(policy: ChallengePolicy) -> bool:
    """Whether this policy states any margin-level floor at all.

    Two independent floors can bind -- the provider's stop-out and the
    operator's internal one -- so "is there a floor" cannot be a test of
    `margin_level_stop_out` alone. Getting this wrong omits the dimension from
    the report for an account whose only floor is the operator's, which is the
    account most in need of the card.
    """
    return (policy.margin_level_stop_out is not None
            or policy.internal_margin_floor is not None)


def margin_level_headroom(policy: ChallengePolicy,
                          snapshot: AccountSnapshot) -> Headroom:
    """Margin level against a stated stop-out floor, in percent.

    For Traders tournaments publish a "95% stop-out rule": if margin level
    (Equity / Used Margin x 100) falls below 95%, positions may be closed to
    restore the requirement. That floor is a real, published constraint on the
    account, so ignoring it would let this engine report healthy headroom on an
    account the provider is about to force-close.

    Percent, not dollars, so `limit`/`used`/`remaining` are percentage points.
    This is a *floor*, not a drawdown budget, and it is only enforced when the
    policy states one -- an absent floor means the program publishes none, which
    is not the same as an unverified rule, so this reports known-with-no-limit
    rather than unknown and does not make a policy incomplete.

    With no margin in use there is no ratio to form. That is reported as known
    and unlimited rather than unknown, because refusing every flat account
    would make the ladder disbelieved exactly when there is genuinely nothing
    to fear.
    """
    provider_floor = policy.margin_level_stop_out
    internal_floor = policy.internal_margin_floor

    if provider_floor is None and internal_floor is None:
        # Neither published. The caller omits this dimension entirely rather
        # than reporting a known dimension whose limit, used and remaining are
        # all None. A dimension that exists only to say it does not exist is
        # noise on a dashboard that renders one card per dimension, and it
        # would break the report's own contract that every reported dimension
        # carries a number or an explicit unknown.
        return Headroom(is_known=True, limit=None, used=None, remaining=None,
                        reason="no stop-out floor published by this program")

    # The strictest floor in force, and the strictest is always the one that
    # binds. An operator floor below the provider's protects the account earlier;
    # an operator floor ABOVE the provider's would be an instruction to keep
    # trading into a breach, so it is discarded rather than min'd away silently.
    # A margin floor is a CEILING on how much margin may be used: margin level
    # must stay ABOVE it, so a HIGHER number is the stricter rule. The strictest
    # floor is therefore `max()`, not `min()` -- which is the opposite of every
    # other limit on this ladder, where smaller is tighter. Getting that backwards
    # would let a 300% internal floor be discarded in favour of the provider's
    # 95%, leaving the account to be margin-called at a level the operator
    # specifically set out to stop well short of.
    #
    # So: take the higher floor, and when the operator's is lower than the
    # provider's, discard it explicitly rather than letting it win by default.
    if provider_floor is None:
        floor = float(internal_floor)
        floor_note = "operator internal floor (no provider stop-out published)"
    elif internal_floor is None:
        floor = float(provider_floor)
        floor_note = "provider stop-out"
    elif internal_floor != 0.0 and float(internal_floor) > float(provider_floor):
        floor = float(internal_floor)
        floor_note = "operator internal floor (stricter than the provider's)"
    elif internal_floor != 0.0:
        floor = float(provider_floor)
        floor_note = "provider stop-out (operator floor is below it and ignored)"
    else:
        # `== 0.0` means "no floor the operator believes in", never "floor of
        # nothing". A falsy zero would otherwise win a naive `max()` and certify
        # the account as safe at any margin level whatsoever.
        floor = float(provider_floor)
        floor_note = "provider stop-out (operator floor of 0 treated as unset)"

    # An unsourced floor is enforced but flagged, rather than being reported with
    # the same confidence as a documented one. The number is still used -- a
    # remembered 95% is worth far more as an enforced floor than as a caveat --
    # but `source_confirmed` is False so a reader can tell it apart from a term
    # read off the provider's page.
    confirmed = bool(policy.margin_level_stop_out_source) if provider_floor is not None \
        else bool(policy.internal_margin_floor_source)

    margin = snapshot.margin or 0.0
    if margin <= 0.0:
        return Headroom(is_known=True, limit=floor, used=None,
                        remaining=None, source_confirmed=confirmed,
                        reason=f"no margin in use; margin level undefined [{floor_note}]")
    level = (snapshot.equity / margin) * 100.0
    unconfirmed = "" if confirmed else "; floor is UNCONFIRMED (no source recorded)"
    return Headroom(
        limit=floor,
        used=level,
        remaining=level - floor,
        is_known=True,
        source_confirmed=confirmed,
        reason=f"{floor_note}{unconfirmed}",
    )


def trading_days_headroom(policy: ChallengePolicy, snapshot: AccountSnapshot) -> Headroom:
    """Days still required before the account can be evaluated.

    A day count is not money, so it is returned as a plain remaining integer
    rather than pushed through the currency-shaped `Headroom`. Treating it as
    one produced a limit in "dollars" and a buffer in "dollars", which is
    exactly the sort of unit confusion that makes a number look authoritative
    while meaning nothing.
    """
    if not policy.minimum_trading_days.is_known:
        if policy.minimum_trading_days.is_not_applicable:
            return _absent(policy.minimum_trading_days, "minimum trading days")
        return Headroom(is_known=False, reason="minimum trading days not verified")
    required = int(policy.minimum_trading_days.value or 0)
    return Headroom(
        limit=float(required),
        used=float(max(0, int(snapshot.trading_days))),
        remaining=float(max(0, required - int(snapshot.trading_days))),
        is_known=True,
    )


def _fit_rung(dimension: str, proposed: float, remaining: float,
              buffer: float) -> Tuple[Permission, str]:
    """Â§34.8 + Â§34.9 + Â§34.23: which kind of "no" is this?

    The two refusals are not the same refusal, and collapsing them into one is
    what makes `ALLOW_REDUCED_RISK` dead code. Â§34.23's worked example is
    explicit about the boundary: strategy risk $700, "challenge allows only
    $420 remaining risk", "Resize to â‰¤ $420", then Governance decides. The
    safety buffer is the whole distance between $500 of proposed risk and $420
    of safe room, and Â§34.23's answer to that gap is a smaller position, not a
    refused account.

    PROTECT is reserved for the case where no size helps: the proposal is larger
    than the remaining headroom itself, so even 0.01 lots breaches the limit.
    Refusing there is the only honest answer. Refusing the resizable case as
    well freezes an account the rules would have traded, and a protection layer
    that refuses more than the rules require is one the operator switches off.
    """
    safe = max(0.0, remaining - buffer)
    if proposed <= remaining:
        return (Permission.ALLOW_REDUCED_RISK,
                f"proposed {proposed:.2f} exceeds the {safe:.2f} safe "
                f"{dimension} room but fits the {remaining:.2f} remaining "
                f"room; resize to {safe:.2f} (34.9/34.23)")
    return (Permission.PROTECT,
            f"proposed {proposed:.2f} exceeds the {remaining:.2f} remaining "
            f"{dimension} room; resize to {safe:.2f} will not help")


def permission_for(policy: Optional[ChallengePolicy], snapshot: AccountSnapshot, *,
                   proposed_risk: float = 0.0, symbol: Optional[str] = None,
is_news_window: bool = False, is_weekend: bool = False,
                     buffer_fraction: float = 0.10,
                     epoch: float = 0.0,
                     usual_risk: Optional[float] = None) -> Dict[str, Any]:
    """Reduce every check to one permission: 34.7 and 34.12 together.

    Each check returns a permission and the most restrictive one wins, so a
    single check can never widen the outcome. An unverified policy is HALT, not
    ALLOW: 34.6's arrow is `UNKNOWN -> DO NOT ASSUME -> RESTRICT`, and this is
    where that arrow lands.
    """
    checks: List[Dict[str, Any]] = []
    # The weekend risk ceiling for the proposed symbol, and the largest risk that
    # still complies with it. Carried out of the function rather than left as a
    # message: a PROTECT rung that only says "must not exceed 50% of usual" is an
    # instruction to do arithmetic the caller has to guess at, and the usual risk
    # is a number only the sizing code holds. `max_proposed_risk` is therefore
    # `None` unless the caller supplied that usual figure, which is honest about
    # what this function can and cannot decide.
    weekend_mult = 1.0
    weekend_schedules: Optional[Dict[str, Any]] = None

    def add(name: str, permission: Permission, detail: Optional[str] = None) -> None:
        checks.append({"check": name, "permission": permission.value,
                       "detail": detail})

    if policy is None:
        add("policy", Permission.HALT, "no challenge policy loaded")
        return {"permission": Permission.HALT.value, "checks": checks,
                "policy_key": None, "policy_verified": False}

    if not policy.is_fully_specified:
        add("policy_complete", Permission.HALT,
            "unverified rules: " + ", ".join(policy.missing_rules()))

    daily = daily_loss_headroom(policy, snapshot, buffer_fraction=buffer_fraction)
    drawdown = max_drawdown_headroom(policy, snapshot, buffer_fraction=buffer_fraction)
    days = trading_days_headroom(policy, snapshot)

    if not daily.is_known:
        add("daily_loss", Permission.PROTECT, daily.reason)
    elif daily.remaining is not None and daily.remaining <= 0:
        add("daily_loss", Permission.HALT, "daily loss limit consumed")
    elif proposed_risk > 0 and daily.remaining is not None \
            and proposed_risk > daily.remaining - (daily.buffer or 0.0):
        add("daily_loss", *_fit_rung("daily loss", proposed_risk,
                                      daily.remaining, daily.buffer or 0.0))

    if not drawdown.is_known:
        add("max_drawdown", Permission.PROTECT, drawdown.reason)
    elif drawdown.remaining is not None and drawdown.remaining <= 0:
        add("max_drawdown", Permission.HALT, "max drawdown breached")
    elif proposed_risk > 0 and drawdown.remaining is not None \
            and proposed_risk > drawdown.remaining - (drawdown.buffer or 0.0):
        add("max_drawdown", *_fit_rung("drawdown", proposed_risk,
                                       drawdown.remaining,
                                       drawdown.buffer or 0.0))

    if not days.is_known:
        add("trading_days", Permission.RESTRICT, days.reason)
    elif days.remaining is not None and days.remaining > 0:
        # Not yet satisfied, but days are not a risk measure either -- this
        # stops the account being *evaluated*, it does not stop it trading, so
        # it stays informational rather than becoming a blocker.
        add("trading_days", Permission.ALLOW,
            f"{int(days.remaining)} more trading day(s) required")
    else:
        add("trading_days", Permission.ALLOW, "minimum trading days satisfied")

    # Only evaluated when a symbol is actually proposed. An account-level
    # question ("how much room is left") has no instrument, and treating that
    # absence as UNKNOWN would PROTECT every such query -- which trains people
    # to ignore the ladder, and the ladder is only useful if it is believed.
    if symbol:
        verdict = policy.instruments.verdict(symbol)
        rung = _restriction_rung(verdict)
        if rung is not None:
            if verdict is Restriction.DENIED:
                detail = f"{symbol} is not permitted by this program"
            elif verdict is Restriction.CONDITIONAL:
                detail = (f"{symbol} is permitted only under conditions this "
                          "engine cannot evaluate")
            else:
                detail = "instrument policy unknown; refusing an unlisted symbol"
            add("instruments", rung, detail)

    # The stop-out floor is a provider-side forced close, not a drawdown the
    # trader spends, so it is HALT rather than a reduced-risk rung: past the
    # floor the account is being closed out, and a smaller position does not
    # un-close it. Ahead of the floor it stays ALLOW-with-detail, because the
    # floor is a cliff that an existing position is not required to stay away
    # from -- only to be sized so it is not reached.
    margin_level = margin_level_headroom(policy, snapshot)
    if margin_level.remaining is not None and margin_level.remaining <= 0:
        add("margin_level", Permission.HALT,
            f"margin level {margin_level.used:.1f}% is at or below the "
            f"{margin_level.limit:.0f}% stop-out floor; positions may be closed")
    elif margin_level.used is not None:
        add("margin_level", Permission.ALLOW,
            f"margin level {margin_level.used:.1f}% against a "
            f"{margin_level.limit:.0f}% stop-out floor")

    if is_news_window:
        rung = _restriction_rung(policy.news.mode)
        if rung is not None:
            add("news", rung,
                "news trading denied by this program" if policy.news.mode
                is Restriction.DENIED else
                "news policy is conditional on terms this engine cannot evaluate"
                if policy.news.mode is Restriction.CONDITIONAL else
                "news policy unknown during a news window")

    # Per-symbol weekend handling. Evaluated whenever a symbol is proposed AND
    # the policy actually states per-symbol weekend behaviour, whether or not the
    # caller flagged `is_weekend`: the window is anchored on each symbol's own
    # Friday close and two of them close hours apart, so trusting a single boolean
    # would reintroduce exactly the "which weekend is it" ambiguity the per-symbol
    # design exists to remove.
    #
    # The `_weekend_terms_in_force` half is load-bearing, not an optimisation. An
    # unreadable schedule correctly reads as "closed", so a policy stating no
    # weekend rules would otherwise halt every symbol at once -- the fail-closed
    # reading applied where there is nothing to be closed *for*.
    if symbol and _weekend_terms_in_force(policy):
        from challenge import weekend as weekend_rules

        schedules = _weekend_schedules(policy, epoch)
        weekend_schedules = schedules
        closed, why = weekend_rules.in_close_window(policy, epoch, symbol, schedules)
        if closed:
            # HALT rather than PROTECT: the symbol is not tradable in this window
            # at any size, and a reduced size would read as "a little is allowed".
            add("weekend_close_window", Permission.HALT, why)
        else:
            add("weekend_close_window", Permission.ALLOW, why)
        mult, mwhy = weekend_rules.risk_multiplier(policy, epoch, symbol, schedules)
        weekend_mult = mult
        if mult < 1.0:
            # PROTECT, not HALT: this is a ceiling, and there is a size that
            # complies. The rung carries the multiplier so the caller can apply
            # it instead of merely being told no.
            add("weekend_risk_window", Permission.PROTECT,
                f"{mwhy}; proposed risk must not exceed {mult:.0%} of usual")

    if is_weekend:
        rung = _restriction_rung(policy.weekend)
        if rung is not None:
            add("weekend", rung,
                "weekend trading denied by this program" if policy.weekend
                is Restriction.DENIED else
                "weekend policy is conditional on terms this engine cannot evaluate"
                if policy.weekend is Restriction.CONDITIONAL else
                "weekend policy unknown")

    if policy.max_lot is not None and symbol and snapshot.margin:
        add("max_lot", Permission.ALLOW, f"lot cap {policy.max_lot}")

    # An empty list is not "no opinion" -- it means every applicable check
    # passed, which is ALLOW. Defaulting to the most permissive outcome here is
    # only safe because reaching an empty list requires a fully-specified
    # policy (otherwise policy_complete already added a HALT), so this cannot
    # turn an unverified policy into an allowance.
    worst = max(
        (Permission(c["permission"]) for c in checks),
        key=lambda p: p.severity,
        default=Permission.ALLOW,
    )
    return {
        "permission": worst.value,
        "checks": checks,
        "policy_key": policy.key,
        "policy_verified": policy.is_fully_specified,
        # Per-symbol weekend verdicts alongside the account-level ones, so a
        # caller sizing a trade sees the symbol's multiplier without having to
        # re-derive the window. Empty when no symbol was proposed, for the same
        # reason the instrument check is skipped there.
        **({"weekend": _weekend_payload(policy, epoch, symbol, weekend_schedules)}
           if symbol else {}),
        # The cap as a number, so a caller sizing a trade can apply it rather
        # than re-derive the window. `1.0` means no ceiling is in force, which is
        # the same answer a caller needs on Monday as on Saturday.
        "weekend_risk_multiplier": weekend_mult,
        "max_proposed_risk": (None if usual_risk is None
                              else round(float(usual_risk) * weekend_mult, 2)),
        "headroom": {
            "daily_loss": daily.as_dict(),
            "max_drawdown": drawdown.as_dict(),
            "trading_days": days.as_dict(),
            "margin_level": margin_level.as_dict(),
        },
    }


def headroom_report(policy: Optional[ChallengePolicy], snapshot: AccountSnapshot, *,
                    buffer_fraction: float = 0.10,
                    baseline_gradeable: bool = True) -> Dict[str, Any]:
    """The 34.22 dashboard payload: every dimension, unknowns shown as unknowns.

    Anything the policy cannot answer reports `is_known: false` with a reason
    rather than a zero. A dashboard that renders an unverified limit as `0.00`
    is worse than one that renders `--`, because `0.00` invites the reader to
    reason about a number the system invented.

    `baseline_gradeable` is the same argument applied one level down. Every
    dimension here is measured against the snapshot's opening equity, so if that
    figure was inferred from the first reading rather than declared by the
    provider, then a known limit and a known policy still produce numbers that
    are wrong -- an account 4% down reads as untouched. The dimensions are
    reported as unknown rather than computed, because a precise figure built on
    an invented baseline is the most convincing lie this report could tell.
    """
    if policy is None:
        return {
            "account_id": snapshot.account_id,
            "policy_known": False,
            "reason": "no challenge policy loaded",
            "dimensions": {},
            "permission": Permission.HALT.value,
        }
    if not baseline_gradeable:
        return {
            "account_id": snapshot.account_id,
            "policy_known": True,
            "policy_key": policy.key,
            "policy_verified": policy.is_fully_specified,
            "missing_rules": policy.missing_rules(),
            "dimensions": {
                # The four currency/day dimensions all measure against an
                # opening reference, so an undeclared baseline makes them
                # unanswerable. Margin level does not: it is a ratio of live
                # equity to live used margin, and it stays true whatever the
                # opening balance was. Blanket-marking it unknown here would
                # hide a floor the provider is still enforcing.
                **{name: Headroom.unverified(
                    name,
                    "opening equity was not declared, so no limit can be "
                    "measured against a trustworthy reference").as_dict()
                   for name in ("daily_loss", "max_drawdown",
                                "profit_target", "trading_days")},
                **({"margin_level": margin_level_headroom(
                    policy, snapshot).as_dict()}
                   if _margin_floor_in_force(policy) else {}),
            },
            "baseline_gradeable": False,
            "permission": Permission.HALT.value,
        }
    return {
        "account_id": snapshot.account_id,
        "policy_known": True,
        "policy_key": policy.key,
        "policy_verified": policy.is_fully_specified,
        "missing_rules": policy.missing_rules(),
        "baseline_gradeable": True,
        "dimensions": {
            "daily_loss": daily_loss_headroom(
                policy, snapshot, buffer_fraction=buffer_fraction).as_dict(),
            "max_drawdown": max_drawdown_headroom(
                policy, snapshot, buffer_fraction=buffer_fraction).as_dict(),
            "profit_target": profit_target_distance(policy, snapshot).as_dict(),
            "trading_days": trading_days_headroom(policy, snapshot).as_dict(),
            # Present only when the program states a floor: absent means there
            # is no such rule, which is different from an unmeasured one, and
            # the report's dimensions are the set of rules actually in force.
            **({"margin_level": margin_level_headroom(
                policy, snapshot).as_dict()}
               if _margin_floor_in_force(policy) else {}),
        },
        "permission": permission_for(
            policy, snapshot, buffer_fraction=buffer_fraction)["permission"],
    }


