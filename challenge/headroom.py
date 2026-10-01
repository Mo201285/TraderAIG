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

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .policy import ChallengePolicy, DrawdownType, Restriction, RuleValue


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

    def as_dict(self) -> Dict[str, Any]:
        return {
            "limit": self.limit,
            "used": self.used,
            "remaining": self.remaining,
            "buffer": self.buffer,
            "is_known": self.is_known,
            "reason": self.reason,
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
    if not policy.daily_loss_limit.is_known:
        return Headroom(is_known=False, reason="daily loss limit not verified")
    reference = snapshot.floating_basis
    # from the day's LOW, not from current equity: a trader who dips and
    # recovers has still spent the room, and measuring from current equity
    # hands it straight back -- inviting the behaviour the limit exists to stop
    low = float(snapshot.day_low_equity if snapshot.day_low_equity
                else snapshot.equity or 0.0)
    used = max(0.0, reference - low)
    return _headroom_for(policy.daily_loss_limit, used,
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


def trading_days_headroom(policy: ChallengePolicy, snapshot: AccountSnapshot) -> Headroom:
    """Days still required before the account can be evaluated.

    A day count is not money, so it is returned as a plain remaining integer
    rather than pushed through the currency-shaped `Headroom`. Treating it as
    one produced a limit in "dollars" and a buffer in "dollars", which is
    exactly the sort of unit confusion that makes a number look authoritative
    while meaning nothing.
    """
    if not policy.minimum_trading_days.is_known:
        return Headroom(is_known=False, reason="minimum trading days not verified")
    required = int(policy.minimum_trading_days.value or 0)
    return Headroom(
        limit=float(required),
        used=float(max(0, int(snapshot.trading_days))),
        remaining=float(max(0, required - int(snapshot.trading_days))),
        is_known=True,
    )


def permission_for(policy: Optional[ChallengePolicy], snapshot: AccountSnapshot, *,
                   proposed_risk: float = 0.0, symbol: Optional[str] = None,
                   is_news_window: bool = False, is_weekend: bool = False,
                   buffer_fraction: float = 0.10) -> Dict[str, Any]:
    """Reduce every check to one permission: 34.7 and 34.12 together.

    Each check returns a permission and the most restrictive one wins, so a
    single check can never widen the outcome. An unverified policy is HALT, not
    ALLOW: 34.6's arrow is `UNKNOWN -> DO NOT ASSUME -> RESTRICT`, and this is
    where that arrow lands.
    """
    checks: List[Dict[str, Any]] = []

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
        add("daily_loss", Permission.PROTECT,
            f"proposed {proposed_risk:.2f} exceeds safe daily room "
            f"{max(0.0, daily.remaining - (daily.buffer or 0.0)):.2f}")

    if not drawdown.is_known:
        add("max_drawdown", Permission.PROTECT, drawdown.reason)
    elif drawdown.remaining is not None and drawdown.remaining <= 0:
        add("max_drawdown", Permission.HALT, "max drawdown breached")
    elif proposed_risk > 0 and drawdown.remaining is not None \
            and proposed_risk > drawdown.remaining - (drawdown.buffer or 0.0):
        add("max_drawdown", Permission.PROTECT,
            f"proposed {proposed_risk:.2f} exceeds safe drawdown room "
            f"{max(0.0, drawdown.remaining - (drawdown.buffer or 0.0)):.2f}")

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
        if verdict is Restriction.UNKNOWN:
            add("instruments", Permission.PROTECT,
                "instrument policy unknown; refusing an unlisted symbol")
        elif verdict is Restriction.DENIED:
            add("instruments", Permission.HALT,
                f"{symbol} is not permitted by this program")

    if is_news_window:
        if policy.news.mode is Restriction.UNKNOWN:
            add("news", Permission.PROTECT, "news policy unknown during a news window")
        elif policy.news.mode is Restriction.DENIED:
            add("news", Permission.HALT, "news trading denied by this program")

    if is_weekend:
        if policy.weekend is Restriction.UNKNOWN:
            add("weekend", Permission.PROTECT, "weekend policy unknown")
        elif policy.weekend is Restriction.DENIED:
            add("weekend", Permission.HALT, "weekend trading denied by this program")

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
        "headroom": {
            "daily_loss": daily.as_dict(),
            "max_drawdown": drawdown.as_dict(),
            "trading_days": days.as_dict(),
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
                name: Headroom.unverified(
                    name,
                    "opening equity was not declared, so no limit can be "
                    "measured against a trustworthy reference").as_dict()
                for name in ("daily_loss", "max_drawdown",
                             "profit_target", "trading_days")
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
        },
        "permission": permission_for(
            policy, snapshot, buffer_fraction=buffer_fraction)["permission"],
    }
