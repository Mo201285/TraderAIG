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

    `NOT_APPLICABLE` exists because "we do not know this rule" and "this
    program has no such rule" are different facts, and a tournament is the case
    that proves it. An FTTrading tournament has no profit target and no minimum
    trading days -- it ranks on balance -- so those rules are absent by design.
    Under the old two-state model both read as UNKNOWN, which made
    `missing_rules()` demand rules the provider will never publish, so a
    tournament could never reach `is_fully_specified` and every such account was
    permanently RESTRICTING. Demanding a document that does not exist is not
    caution; it is a rule the operator cannot satisfy.

    It is not a loophole. `NOT_APPLICABLE` carries the same provenance burden as
    `KNOWN` -- a `source` saying which document establishes the absence -- so
    asserting "no profit target" is itself a claim that has to be cited. What it
    removes is the requirement to invent a number for a rule that has none.
    """

    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"
    NOT_APPLICABLE = "not_applicable"


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


class RuleOrigin(str, Enum):
    """Who chose this rule's value, which decides whether it may be loosened.

    A number the provider published is a ceiling the trader cannot raise. A
    number an operator chose is their own risk appetite, which is a legitimate
    thing to want and is meaningless as a *substitute* for the provider's rule.

    They are distinguished because the dangerous case is mixing them. An
    operator who sets a 5% daily loss on a program whose terms say 3% has not
    chosen their risk; they have overwritten the provider's term with a worse
    one and the account still reports itself compliant. So an operator-set rule
    may tighten a verified rule and may not widen it (`tightest_daily_loss`).
    """

    PROVIDER = "provider"
    OPERATOR = "operator"


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
    origin: RuleOrigin = RuleOrigin.PROVIDER

    @classmethod
    def known(cls, value: float, *, source: str, verified_at: Optional[str] = None,
              note: Optional[str] = None, origin: RuleOrigin = RuleOrigin.PROVIDER) -> "RuleValue":
        return cls(value=float(value), status=RuleStatus.KNOWN, source=source,
                   verified_at=verified_at, note=note, origin=origin)

    @classmethod
    def unknown(cls, note: Optional[str] = None) -> "RuleValue":
        return cls(value=None, status=RuleStatus.UNKNOWN, note=note)

    @classmethod
    def operator_set(cls, value: float, *, source: str, verified_at: Optional[str] = None,
                     note: Optional[str] = None) -> "RuleValue":
        """A limit the operator chose as their own risk appetite.

        Distinct from `known` because this number did not come from a provider
        document, and `RuleOrigin` is what lets `tightest_daily_loss` refuse to
        let it override one that did. `source` is still required: it should name
        who set it and why, because an operator limit that outlives the operator
        who chose it is an unexplainable number guarding real money.
        """
        if not source:
            raise ValueError(
                "an operator_set rule must record who chose it and why; an "
                "unnamed operator limit cannot be reviewed or revoked")
        return cls(value=float(value), status=RuleStatus.KNOWN, source=source,
                   verified_at=verified_at, note=note, origin=RuleOrigin.OPERATOR)

    @classmethod
    def not_applicable(cls, *, source: str,
                       verified_at: Optional[str] = None,
                       note: Optional[str] = None) -> "RuleValue":
        """This program has no such rule, and here is the document saying so.

        `source` is required, not optional. The absence of a rule is a claim
        about a provider's terms, so it carries provenance exactly as a number
        would; the only thing that changes is that the honest value is None
        rather than a fabricated one.
        """
        if not source:
            raise ValueError(
                "a not_applicable rule must cite the document that establishes "
                "the absence; 'no profit target because nobody said' is the "
                "guess this status exists to avoid")
        return cls(value=None, status=RuleStatus.NOT_APPLICABLE, source=source,
                   verified_at=verified_at, note=note)

    @property
    def is_known(self) -> bool:
        return self.status == RuleStatus.KNOWN and self.value is not None

    @property
    def is_not_applicable(self) -> bool:
        """Whether this rule was established not to exist."""
        return self.status == RuleStatus.NOT_APPLICABLE

    @property
    def is_unresolved(self) -> bool:
        """Whether this rule must block trading: no number and not established absent.

        This is the predicate `missing_rules()` wants. It is deliberately not
        `not is_known`, which would also be true for a rule the provider
        established does not exist.
        """
        return not self.is_known and not self.is_not_applicable

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
            "is_not_applicable": self.is_not_applicable,
            "origin": self.origin.value,
        }

    def is_tighter_than(self, other: "RuleValue") -> Optional[bool]:
        """Whether this rule is stricter than `other`, or None if incomparable.

        None means one of the two has no number, and "stricter than a rule that
        does not exist" has no answer. Callers must not treat None as False --
        a provider publishing no daily loss limit does not make an operator's
        5% tighter than "nothing", and treating it that way is how an operator
        limit ends up ignored.
        """
        if not self.is_known or not other.is_known:
            return None
        return float(self.value) < float(other.value)


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
    # The symbols the provider's own document lists as tradeable. This is the
    # other half of the answer and it exists because a deny-list alone cannot
    # express a competition that permits three symbols: denying "the rest" means
    # writing down every symbol the venue has ever listed, including the ones
    # added after the rules were published, and each omission is a permitted
    # trade nobody decided to permit. An allow-list fails closed in the
    # opposite direction -- a symbol nobody named is simply not on it.
    #
    # When this list is non-empty it is the answer, and `default` is only the
    # answer for a program that published no list at all. An explicit deny
    # still beats an explicit allow, so a provider that bans EURUSD and another
    # that lists it still ends up with EURUSD refused.
    allowed_symbols: List[str] = field(default_factory=list)
    source: Optional[str] = None

    def verdict(self, symbol: str) -> Restriction:
        name = (symbol or "").upper()
        if name in {s.upper() for s in self.denied_symbols}:
            return Restriction.DENIED
        if self.allowed_symbols:
            # A published list is an enumeration, not a hint: being on it is
            # what permits a symbol, and everything the document did not name
            # is refused no matter what `default` says.
            if name in {s.upper() for s in self.allowed_symbols}:
                return Restriction.ALLOWED
            return Restriction.DENIED
        return self.default

    def as_dict(self) -> Dict[str, Any]:
        return {
            "denied_symbols": list(self.denied_symbols),
            "allowed_symbols": list(self.allowed_symbols),
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

    # The MT5 server these terms were read from. None means the terms are not
    # tied to a broker, which is a claim about the document rather than about
    # the account -- safe only for genuinely broker-neutral programs.
    #
    # This is load-bearing for tournaments. A published tournament (an FT
    # October Clash, say) is verified for exactly one server, while other
    # brokers run dynamic terms with relative ratios. A policy with no server
    # would be inherited by every account on every broker, so a set of terms
    # verified against one broker's document would silently start deciding
    # another broker's accounts. Matching is exact or case-insensitive; see
    # `matches_server` for why there is deliberately no wildcard.
    server: Optional[str] = None

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

    # Margin-level stop-out, as a percentage of used margin. Carried in
    # `custom_rules` rather than as a first-class field because it is specific
    # to some programs (For Traders tournaments state a 95% floor) and absent
    # from others. It is deliberately NOT part of `is_fully_specified`: absence
    # means the program states no floor, which is not the same as an unverified
    # rule, and treating it as a missing rule would HALT every account on every
    # program that does not have one. A floor that is stated but not a number
    # is a different case and does fail closed (see `margin_level_headroom`).
    #
    # Key: a margin level percentage, e.g. 95.0.
    # Source: help.fortraders.com/en/articles/10066978 -- "95% stop-out rule
    # applies: if the account's margin level (Equity / Used Margin x 100) falls
    # below 95%, positions may be automatically closed".
    margin_level_stop_out: Optional[float] = None

    # ...and the source for it. Kept separate from the number because the two can
    # disagree, and the disagreement is the whole point: a 95% floor read off a
    # provider page is a cited term, while a 95% floor somebody remembered is a
    # plausible number. `margin_level_stop_out_source` carries the provenance so
    # `margin_level_headroom` can report a value that is enforced but flagged as
    # unconfirmed, instead of presenting an unsourced number with the same
    # confidence as a documented one.
    margin_level_stop_out_source: Optional[str] = None

    # The operator's own margin-level floor, as a percentage. A *separate field*
    # from `margin_level_stop_out` rather than a second key in `custom_rules`,
    # because it is a different kind of thing with a different authority:
    #
    #   - `margin_level_stop_out` is the provider's term. Breaching it can end
    #     the account, and the engine can only observe it.
    #   - `internal_margin_floor` is this desk's own floor, chosen to keep a
    #     comfortable distance from the provider's rather than to be breached by
    #     accident. It is never raised by the provider and never replaces it.
    #
    # Deliberately NOT a "cancelled" flag on `margin_level_stop_out`. A program
    # that omits the provider floor is a program whose floor was never
    # established, and conflating the two would let an unverified term read as a
    # waived one -- the single most permissive mistake available here.
    internal_margin_floor: Optional[float] = None
    internal_margin_floor_source: Optional[str] = None

    # The broker's UTC offset in hours, and the reason it is not cosmetic: a
    # daily loss limit is measured against the *provider's* trading day. On a
    # GMT+3 server that day ends at 21:00 UTC, so rolling the daily allowance at
    # 00:00 UTC hands the account a full fresh 3% three hours before the provider
    # starts counting a new day -- the permissive direction, on the one rule
    # that ends accounts. Float rather than int because several brokers run
    # +05:30.
    #
    # None means unknown, and `daily_loss_headroom` scores that as UNKNOWN rather
    # than as offset zero. An absent offset must not read as "the broker is on
    # UTC": that is precisely the silence that turns an unknown rule into a
    # permissive one.
    server_utc_offset_hours: Optional[float] = None

    # --- weekend handling, per symbol -------------------------------------
    #
    # Both of these are minutes/multipliers applied to a per-symbol window
    # anchored on that symbol's own Friday close, read from MT5. Neither can be
    # applied to "the weekend" as a whole, because the closes differ by symbol
    # and a window keyed to the wrong close is a window that is either
    # permanently open or never open.
    #
    # `weekend_close_lead_minutes` is how far before that close trading stops.
    # A symbol whose close cannot be read is treated as already closed --
    # see `challenge/weekend.py` for why that is the fail-closed reading.
    weekend_close_lead_minutes: Optional[float] = None

    # The fraction of usual risk a weekend-risk class may carry. Less than 1.0
    # enables the rule; 1.0 or None means no reduction. Expressed as risk rather
    # than lots because "half size" is a risk statement and a lot multiplier
    # would be wrong for any symbol whose contract size differs from the
    # account's default.
    weekend_risk_multiplier: Optional[float] = None

    # Per-symbol Friday closes as read from MT5: {"XAUUSD": {"observed_close":
    # epoch, "observed_at": epoch}}. Carried in the policy so a resolved verdict
    # is reproducible -- a window computed from a reading that was never stored
    # cannot be re-checked later, and an unauditable risk control is not one.
    symbol_schedules: Dict[str, Dict[str, float]] = field(default_factory=dict)

    instruments: InstrumentPolicy = field(default_factory=InstrumentPolicy)
    news: NewsPolicy = field(default_factory=NewsPolicy)
    overnight: Restriction = Restriction.UNKNOWN
    weekend: Restriction = Restriction.UNKNOWN
    max_lot: Optional[float] = None

    custom_rules: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None

    @property
    def is_fully_specified(self) -> bool:
        """True when every *numeric* rule that governs risk has been verified.

        Anything short of this is POLICY_UNKNOWN, and the engine restricts. The
        bar is deliberately high: a half-known policy is the case where a
        plausible-looking number is most likely to be doing the work of a real
        one.

        The bar is the RuleValues, NOT `missing_rules()`. Those are two
        questions, and merging them is a mistake this repo has already made
        once: `missing_rules()` reports weekend/instruments/news as unresolved,
        and those are handled by their own scoped PROTECT/HALT rungs in
        `permission_for`. Folding them in here turns a scoped refusal on one
        dimension into a blanket HALT for a policy whose numbers are all
        verified -- strictly worse for the operator, and not what any caller
        means by "fully specified".

        A caller that wants the stricter reading reads `is_fully_resolved` below,
which is the same question this boolean used to answer by accident.

        The server offset is deliberately NOT in this bar, though it is not a
        RuleValue and this check cannot see it. An unknown offset is handled
        where it is measured instead: `daily_loss_headroom` scores the daily
        dimension UNKNOWN and the account is RESTRICTED, which is the contract
        the durability and execution-gate tests encode. Folding the offset in
        here as well would convert that documented restrict into a halt on the
        completeness gate -- stricter, but a different rule, on the one path
        that ends accounts, and not a call for a change in this workstream.
        """
        return all(
            rule.is_known or rule.is_not_applicable
            for rule in (
                self.profit_target,
                self.daily_loss_limit,
                self.max_drawdown,
                self.minimum_trading_days,
                self.max_leverage,
            )
        )

    @property
    def is_fully_resolved(self) -> bool:
        """True when NOTHING is unresolved: numbers and restrictions alike.

        The strict reading, and the one that answers "may this account be
        graded against these terms at all". It is separate from
        `is_fully_specified` because the two answer different questions and
        merging them costs a scoped refusal its PROTECT:

          - `is_fully_specified` -- are the governing NUMBERS verified? This
            is the completeness gate, and an UNKNOWN weekend restriction must
            not fail it, because that restriction already has its own rung.
          - `is_fully_resolved` -- is anything at all still unknown? This is
            what a caller reporting on the policy's provenance wants, and it is
            what stops a payload from saying "complete" while listing what is
            missing.
        """
        return not self.missing_rules()

    @property
    def effective_daily_loss_limit(self) -> RuleValue:
        """The daily loss limit actually enforced: the strictest one in force.

        Three things can set this and they do not agree:
          - the provider's published terms,
          - an operator's own risk choice (`RuleValue.operator_set`),
          - both, when an operator has tightened a published limit.

        Enforcing the loosest of them would make the operator control useless and
        enforcing the provider's alone would make their own risk choice useless,
        so the rule is `min()`. The direction is deliberate: every path through
        this property moves the limit DOWN or leaves it alone, never up. That is
        what lets an operator add a personal limit without ever needing to be
        trusted not to delete the provider's -- a mistake that could only ever
        make the system more permissive is a mistake about `min`, and this is
        the one place `min` is the safety property rather than a convenience.

        A provider limit that is absent or unverified contributes nothing: an
        operator limit then stands alone. That is not a hole, because the
        provider's *account* terms (the ones that actually end a challenge) are
        enforced elsewhere by `permission_for`, which still refuses on an
        unverified drawdown.
        """
        provider = self.daily_loss_limit
        if provider.is_unresolved:
            # UNKNOWN outranks everything below, and the reason is subtle enough
            # to state: an unverified provider rule contributes no number, so a
            # plain min() over the numeric candidates would drop it and promote
            # the operator's value as though the provider had published nothing.
            # It has published nothing -- including nothing permitting this.
            # Comparing 20% against a term nobody has read is not a comparison.
            return provider
        candidates = [r for r in (
            provider,
            self.custom_rules.get("operator_daily_loss_limit"),
        ) if isinstance(r, RuleValue) and r.is_known]
        if not candidates:
            return provider
        return min(candidates, key=lambda r: float(r.value))

    def missing_rules(self) -> List[str]:
        """Names of the risk rules that are still unverified."""
        pairs = (
            ("profit_target", self.profit_target),
            ("daily_loss_limit", self.daily_loss_limit),
            ("max_drawdown", self.max_drawdown),
            ("minimum_trading_days", self.minimum_trading_days),
            ("max_leverage", self.max_leverage),
        )
        missing = [name for name, rule in pairs if rule.is_unresolved]
        if self.drawdown_type is None:
            missing.append("drawdown_type")
        if (self.instruments.default == Restriction.UNKNOWN
                and not self.instruments.allowed_symbols):
            # Only unresolved when the provider published no list. A policy that
            # DID publish one has already answered the question for every
            # symbol -- named is permitted, unnamed is refused -- so demanding a
            # separate reading of the default asks for a second answer to a
            # question the allow-list already settled, and an operator who
            # correctly set the default to `denied` was told it was still
            # missing.
            missing.append("instruments.default")
        if self.overnight == Restriction.UNKNOWN:
            missing.append("overnight")
        if self.weekend == Restriction.UNKNOWN:
            missing.append("weekend")
        return missing

    @property
    def key(self) -> str:
        # The server is part of the identity, not decoration: two brokers can
        # both run a program called "Classic 2-Step" with different numbers, and
        # a key that collided across them would make one broker's verified
        # terms look like the other's. `None` renders as `*`, which is only ever
        # produced by a deliberately broker-neutral policy.
        return (f"{self.provider}:{self.program}:{self.account_size:g}"
                f":{self.policy_version}:{self.server or '*'}")

    def matches_server(self, server: Optional[str]) -> bool:
        """Whether these terms were read from the account's MT5 server.

        Both sides must agree, exactly, modulo case -- MT5 server names are
        label text, so `FTTrading-Server` and `fttrading-server` are the same
        place, but `FTTrading-Server-Demo` is not.

        A broker-neutral policy (`server=None`) matches any server. That is a
        deliberate claim that the terms document is not broker-specific, and it
        is why a tournament policy must always name its server: a tournament's
        published numbers are that tournament's, not every tournament's.

        No wildcard exists, deliberately. A `"*"` server would be a way to
        re-introduce the inheritance this field exists to prevent, one string
        away from being typed.
        """
        if self.server is None:
            return True
        if server is None:
            return False
        return str(self.server).strip().casefold() == str(server).strip().casefold()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "program": self.program,
            "account_size": self.account_size,
            # The broker scope travels with the policy. It was missing here, so
            # a restored policy came back broker-neutral and resolved for an
            # account on ANY server -- one firm's verified terms deciding an
            # account they were never written for, which is the exact leak the
            # registry's server filter exists to prevent. Persistence that
            # drops a scope is worse than no persistence, because the operator
            # believes the scope is still in force.
            "server": self.server,
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
            "server_utc_offset_hours": self.server_utc_offset_hours,
            "weekend_close_lead_minutes": self.weekend_close_lead_minutes,
            "weekend_risk_multiplier": self.weekend_risk_multiplier,
            # These four were absent here, so a restored policy came back with no
            # margin floor at all: the operator's floor stopped being enforced and
            # the dimension dropped out of the report entirely, which is the
            # account most in need of the card. A floor that does not travel is
            # worse than one that was never set, because the report implies it.
            "margin_level_stop_out": self.margin_level_stop_out,
            "margin_level_stop_out_source": self.margin_level_stop_out_source,
            "internal_margin_floor": self.internal_margin_floor,
            "internal_margin_floor_source": self.internal_margin_floor_source,
            "symbol_schedules": dict(self.symbol_schedules),
            "instruments": self.instruments.as_dict(),
            "news": self.news.as_dict(),
            "overnight": self.overnight.value,
            "weekend": self.weekend.value,
            "max_lot": self.max_lot,
            "custom_rules": dict(self.custom_rules),
            "notes": self.notes,
            # Both booleans travel together on purpose. Reporting one without
            # the other is what let a caller read `is_fully_specified: true`
            # next to a non-empty `missing_rules` and conclude the policy was
            # complete; a payload that names what it does not know cannot be
            # half-read.
            "is_fully_specified": self.is_fully_specified,
            "is_fully_resolved": self.is_fully_resolved,
            "missing_rules": self.missing_rules(),
        }


def policy_from_dict(payload: Dict[str, Any]) -> ChallengePolicy:
    """Rebuild a policy from its own `as_dict()`, or refuse.

    This is the inverse of `as_dict()` and nothing else. It reads the persisted
    shape rather than the API's request shape on purpose: the two differ, and a
    reader that shared the request parser would have to keep both vocabularies
    alive forever, with the request one free to change under it.

    Unknown keys are ignored rather than rejected, so a policy stored by a newer
    build still loads the parts this build understands. A key it cannot
    interpret at all -- an unparseable rule, a restriction that is not a
    member -- raises, because a policy that silently loses a limit is worse
    than one that refuses to load.
    """

    def rule(name: str) -> RuleValue:
        raw = payload.get(name)
        if raw is None:
            return RuleValue.unknown("not persisted")
        if isinstance(raw, RuleValue):
            return raw
        if not isinstance(raw, dict):
            raise ValueError("%s is not a rule object" % name)
        status = str(raw.get("status") or RuleStatus.UNKNOWN.value)
        source = raw.get("source")
        note = raw.get("note")
        value = raw.get("value")
        origin = raw.get("origin") or RuleOrigin.PROVIDER.value
        if status == RuleStatus.NOT_APPLICABLE.value:
            # `source` is keyword-only, so the positional call raised
            # TypeError the first time a NOT_APPLICABLE rule was restored from
            # the database -- a state only reached after a restart, which is why
            # an in-memory round trip never saw it.
            return RuleValue.not_applicable(
                source=source or "restored from database", note=note)
        if status == RuleStatus.KNOWN.value and value is not None:
            return RuleValue(
                float(value), status=RuleStatus.KNOWN, source=source,
                verified_at=raw.get("verified_at"), note=note,
                origin=RuleOrigin(origin)
                if origin in {o.value for o in RuleOrigin}
                else RuleOrigin.PROVIDER)
        if status == RuleStatus.CONFLICTED.value:
            # No dedicated constructor exists for this status, and inventing one
            # here would give the persistence path a rule shape the rest of the
            # module cannot produce. Unknown is the honest landing: the value is
            # still unresolved, and `is_known` is False either way.
            # `unknown` takes only a note, so the conflicting-sources reason is
            # carried there rather than dropped.
            return RuleValue.unknown(note=note or "conflicting sources")
        return RuleValue.unknown(note=note or "unknown")

    def restriction(value: Any, name: str) -> Restriction:
        if value is None:
            return Restriction.UNKNOWN
        if isinstance(value, Restriction):
            return value
        try:
            return Restriction(str(value))
        except ValueError as exc:
            raise ValueError("%s is not a restriction: %r" % (name, value)) from exc

    instruments_raw = payload.get("instruments") or {}
    if not isinstance(instruments_raw, dict):
        raise ValueError("instruments is not an object")
    instruments = InstrumentPolicy(
        denied_symbols=[str(s) for s in (instruments_raw.get("denied_symbols") or [])],
        allowed_symbols=[str(s)
                         for s in (instruments_raw.get("allowed_symbols") or [])],
        default=restriction(instruments_raw.get("default"), "instruments.default"),
        source=instruments_raw.get("source"))

    news_raw = payload.get("news") or {}
    if not isinstance(news_raw, dict):
        raise ValueError("news is not an object")
    news = NewsPolicy(
        mode=restriction(news_raw.get("mode"), "news.mode"),
        minutes_before=news_raw.get("minutes_before"),
        minutes_after=news_raw.get("minutes_after"),
        source=news_raw.get("source"))

    drawdown_raw = payload.get("drawdown_type")
    drawdown = None
    if drawdown_raw is not None:
        try:
            drawdown = DrawdownType(str(drawdown_raw))
        except ValueError as exc:
            raise ValueError("drawdown_type is not a basis: %r" % drawdown_raw) from exc

    def opt_float(name: str) -> Optional[float]:
        raw = payload.get(name)
        return None if raw is None else float(raw)

    return ChallengePolicy(
        provider=str(payload.get("provider") or ""),
        program=str(payload.get("program") or ""),
        account_size=opt_float("account_size"),
        server=payload.get("server"),
        policy_version=str(payload.get("policy_version") or ""),
        effective_from=payload.get("effective_from"),
        effective_until=payload.get("effective_until"),
        profit_target=rule("profit_target"),
        daily_loss_limit=rule("daily_loss_limit"),
        max_drawdown=rule("max_drawdown"),
        minimum_trading_days=rule("minimum_trading_days"),
        max_leverage=rule("max_leverage"),
        drawdown_type=drawdown,
        consistency_rule=payload.get("consistency_rule"),
        server_utc_offset_hours=opt_float("server_utc_offset_hours"),
        weekend_close_lead_minutes=payload.get("weekend_close_lead_minutes"),
        weekend_risk_multiplier=payload.get("weekend_risk_multiplier"),
        symbol_schedules=dict(payload.get("symbol_schedules") or {}),
        instruments=instruments,
        news=news,
        overnight=restriction(payload.get("overnight"), "overnight"),
        weekend=restriction(payload.get("weekend"), "weekend"),
        max_lot=opt_float("max_lot"),
        margin_level_stop_out=opt_float("margin_level_stop_out"),
        margin_level_stop_out_source=payload.get("margin_level_stop_out_source"),
        internal_margin_floor=opt_float("internal_margin_floor"),
        internal_margin_floor_source=payload.get("internal_margin_floor_source"),
        custom_rules=dict(payload.get("custom_rules") or {}),
        notes=payload.get("notes"))
