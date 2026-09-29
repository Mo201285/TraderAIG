"""Challenge account policy: the versioned rule set a prop account is held to.

34.6 is the constraint that shapes this whole module:

    Rules must be based on authoritative documentation available to the system.
    If a rule cannot be verified: UNKNOWN -> DO NOT ASSUME -> RESTRICT.

That last arrow is the dangerous one, and it is dangerous in a specific, ordinary
way. Every numeric limit here has an obvious-looking default -- `max_drawdown =
0.10` is a plausible-looking number, and a dataclass that defaults it would let
an unverified provider term silently become a *permissive* limit. A trader who
then breaches the real 4% rule has been told the whole time that 10% was the
rule, because the system invented it and said so with a straight face.

So an unknown rule is `None`, and `None` propagates all the way to a refusal.
It is never coerced to 0.0 (which would mean "no limit") and never to a default
(which would mean "a limit nobody verified"). `RuleValue` exists to make that
distinction impossible to skip by accident: it carries the value AND whether it
was ever verified, and `resolved()` refuses to produce a number for an
unverified rule.

The registry ships with no policies. A fresh install therefore reports
POLICY_UNKNOWN and RESTRICTS, which is the correct state for a system that has
not been told the rules yet, and it is why this module is safe to deploy before
anyone has supplied provider terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RuleStatus(str, Enum):
    """How much we actually know about one rule.

    `UNKNOWN` is not an error state to be cleared later in a hurry. It is the
    state that must block trading.
    """

    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"


class DrawdownType(str, Enum):
    """How a provider measures drawdown. These are genuinely different rules.

    The type matters more than the number: a static-drawdown account that loses
    4% then recovers 4% has breached permanently, while a floating-drawdown
    account has not. Encoding only the percentage would make the engine
    report PASSED for an account that is already dead, so the type is part of
    the policy rather than a note beside it.
    """

    STATIC = "static"
    FLOATING = "floating"
    TRAILING = "trailing"


class Restriction(str, Enum):
    """Named trade restrictions, resolved rather than assumed.

    `UNKNOWN` is a member here on purpose. "We do not know whether this program
    allows XAUUSD" and "this program forbids XAUUSD" must not collapse into the
    same value, because only one of them is a reason to refuse.
    """

    UNKNOWN = "unknown"
    ALLOWED = "allowed"
    DENIED = "denied"
    CONDITIONAL = "conditional"


@dataclass
class RuleValue:
    """A single rule plus the provenance needed to trust it.

    `source` is not decoration. 34.6 says rules come from authoritative
    documentation, and a number with no document behind it is a guess wearing
    a decimal point. Recording where each rule came from is what lets a later
    review tell a verified term from a plausible one.
    """

    value: Optional[float] = None
    status: RuleStatus = RuleStatus.UNKNOWN
    source: Optional[str] = None
    verified_at: Optional[str] = None
    note: Optional[str] = None

    @classmethod
    def known(cls, value: float, *, source: str, verified_at: Optional[str] = None,
              note: Optional[str] = None) -> "RuleValue":
        return cls(value=float(value), status=RuleStatus.KNOWN, source=source,
                   verified_at=verified_at, note=note)

    @classmethod
    def unknown(cls, note: Optional[str] = None) -> "RuleValue":
        return cls(value=None, status=RuleStatus.UNKNOWN, note=note)

    @property
    def is_known(self) -> bool:
        return self.status == RuleStatus.KNOWN and self.value is not None

    def resolved(self) -> Optional[float]:
        """The numeric value, or None when it was never verified.

        Returning None rather than a default is the entire point. A caller that
        cannot cope with None has a bug, and that bug is caught here rather
        than as a fabricated limit on a live account.
        """
        return float(self.value) if self.is_known else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status.value,
            "source": self.source,
            "verified_at": self.verified_at,
            "note": self.note,
            "is_known": self.is_known,
        }


@dataclass
class InstrumentPolicy:
    """Which instruments a program allows.

    `denied` is an explicit deny-list rather than an allow-list because a
    provider's published list of banned symbols is short and enumerable, while
    its list of permitted symbols is long, changes, and is not something we can
    reconstruct from documentation. Building on a deny-list means a symbol the
    system has never heard of is refused, which is the correct default for an
    instrument list we cannot fully verify.
    """

    denied_symbols: List[str] = field(default_factory=list)
    # A symbol not on the deny-list is still refused unless this is explicitly
    # ALLOWED, because "not in our deny-list" is not the same as "permitted".
    default: Restriction = Restriction.UNKNOWN
    source: Optional[str] = None

    def verdict(self, symbol: str) -> Restriction:
        if (symbol or "").upper() in {s.upper() for s in self.denied_symbols}:
            return Restriction.DENIED
        return self.default

    def as_dict(self) -> Dict[str, Any]:
        return {
            "denied_symbols": list(self.denied_symbols),
            "default": self.default.value,
            "source": self.source,
        }


@dataclass
class NewsPolicy:
    """High-impact-news trading restriction."""

    mode: Restriction = Restriction.UNKNOWN
    minutes_before: Optional[int] = None
    minutes_after: Optional[int] = None
    source: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "minutes_before": self.minutes_before,
            "minutes_after": self.minutes_after,
            "source": self.source,
        }


@dataclass
class ChallengePolicy:
    """A versioned rule set for one provider/program/account-size combination.

    Every numeric rule is a `RuleValue`, never a bare float, so "we know the
    profit target" and "we did not look" cannot look alike in memory, in the
    API, or in a log line.
    """

    provider: str = ""
    program: str = ""
    account_size: float = 0.0
    policy_version: str = ""

    effective_from: Optional[str] = None   # ISO date; policies are versioned in time
    effective_until: Optional[str] = None

    profit_target: RuleValue = field(default_factory=RuleValue.unknown)
    daily_loss_limit: RuleValue = field(default_factory=RuleValue.unknown)
    max_drawdown: RuleValue = field(default_factory=RuleValue.unknown)
    minimum_trading_days: RuleValue = field(default_factory=RuleValue.unknown)
    max_leverage: RuleValue = field(default_factory=RuleValue.unknown)

    # None means the provider did not specify a drawdown basis. That is
    # different from specifying one, so it stays None rather than defaulting.
    drawdown_type: Optional[DrawdownType] = None

    # A consistency rule caps the share of total profit that may come from one
    # day. It is common in funded programs and absent in others; absent is not
    # the same as unlimited.
    consistency_rule: Optional[float] = None

    instruments: InstrumentPolicy = field(default_factory=InstrumentPolicy)
    news: NewsPolicy = field(default_factory=NewsPolicy)
    overnight: Restriction = Restriction.UNKNOWN
    weekend: Restriction = Restriction.UNKNOWN
    max_lot: Optional[float] = None

    custom_rules: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None

    @property
    def is_fully_specified(self) -> bool:
        """True only when every rule that governs risk has been verified.

        Anything short of this is POLICY_UNKNOWN, and the engine restricts. The
        bar is deliberately high: a half-known policy is the case where a
        plausible-looking number is most likely to be doing the work of a real
        one.
        """
        return all(
            rule.is_known
            for rule in (
                self.profit_target,
                self.daily_loss_limit,
                self.max_drawdown,
                self.minimum_trading_days,
                self.max_leverage,
            )
        )

    def missing_rules(self) -> List[str]:
        """Names of the risk rules that are still unverified."""
        pairs = (
            ("profit_target", self.profit_target),
            ("daily_loss_limit", self.daily_loss_limit),
            ("max_drawdown", self.max_drawdown),
            ("minimum_trading_days", self.minimum_trading_days),
            ("max_leverage", self.max_leverage),
        )
        missing = [name for name, rule in pairs if not rule.is_known]
        if self.drawdown_type is None:
            missing.append("drawdown_type")
        if self.instruments.default == Restriction.UNKNOWN:
            missing.append("instruments.default")
        if self.overnight == Restriction.UNKNOWN:
            missing.append("overnight")
        if self.weekend == Restriction.UNKNOWN:
            missing.append("weekend")
        return missing

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.program}:{self.account_size:g}:{self.policy_version}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "program": self.program,
            "account_size": self.account_size,
            "policy_version": self.policy_version,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "profit_target": self.profit_target.as_dict(),
            "daily_loss_limit": self.daily_loss_limit.as_dict(),
            "max_drawdown": self.max_drawdown.as_dict(),
            "minimum_trading_days": self.minimum_trading_days.as_dict(),
            "max_leverage": self.max_leverage.as_dict(),
            "drawdown_type": self.drawdown_type.value if self.drawdown_type else None,
            "consistency_rule": self.consistency_rule,
            "instruments": self.instruments.as_dict(),
            "news": self.news.as_dict(),
            "overnight": self.overnight.value,
            "weekend": self.weekend.value,
            "max_lot": self.max_lot,
            "custom_rules": dict(self.custom_rules),
            "notes": self.notes,
            "is_fully_specified": self.is_fully_specified,
            "missing_rules": self.missing_rules(),
        }
