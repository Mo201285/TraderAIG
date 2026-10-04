"""The policy registry: which rule set applies to this account, right now.

34.6 calls for a *versioned* policy, and the versioning is the point rather
than bookkeeping. Providers change terms -- a drawdown rule gets tightened, a
profit target is revised -- and an account is judged against the rules that were
in force when it started, not the rules that happen to be current when someone
looks at it. A registry that kept only "the latest" policy would retroactively
declare a running account failed for breaking a limit that did not exist when it
opened, which is not a data problem, it is the system overruling a fact.

So `register()` refuses to replace a version already in force, and `resolve()`
takes a date. `effective_until` on a superseded version is what makes "the rules
at the time" answerable; without it the history is unrecoverable and a policy
change becomes irreversible in effect.

**The registry is empty on purpose.** It ships with no policies, so a fresh
install resolves to POLICY_UNKNOWN and restricts. That is the honest starting
state for a system that has not been told any provider's terms, and it is
strictly safer than shipping plausible-looking sample rules that a deployment
might quietly keep using. 34.6 is unambiguous that an unverifiable rule must
restrict, and sample data is unverifiable by definition.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .policy import ChallengePolicy


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text + "T00:00:00")
        except ValueError:
            return None


def broker_local_now(offset_hours: float) -> datetime:
    """The broker's wall clock right now, as a naive local datetime.

    A provider's tournament window is written in the broker's own time: "starts
    13:00 server time" means 13:00 on the server, and comparing that to the host's
    wall clock is a bug that only shows up in the hours around a boundary -- and a
    tournament boundary is precisely where being an hour out decides whether the
    account may trade at all.

    Naive on purpose, so it compares against the same naive wall-clock values
    `effective_from`/`effective_until` are parsed into. Converting one side to UTC
    instead would be equally correct and would make every stored window wrong by
    the offset, which is a much worse place to keep a mistake.
    """
    return (datetime.now(timezone.utc)
            + timedelta(hours=float(offset_hours))).replace(tzinfo=None)


#: Why a resolve landed where it did. The console and the operator need to tell
#: "the tournament ended" from "you never registered its clock", which are the
#: same None from the outside and opposite problems at the keyboard.
RESOLVED = "resolved"
NO_CANDIDATES = "no_candidates"
WINDOW_CLOSED = "window_closed"
CLOCK_UNKNOWN = "clock_unknown"


def _window_open(policy: Any, moment: Optional[datetime],
                 offset_hours: Optional[float]) -> tuple:
    """Whether `policy` is open at `moment`, and whether that was knowable.

    Start is inclusive and end exclusive: a tournament that ends at 13:00 is not
    in force at 13:00, so the last tradable instant is the one before. An account
    that is refused entry in the minute it would have completed is the correct
    reading of a closed window, not an off-by-one.

    `(False, False)` means "cannot be evaluated": the window is bounded and no
    broker offset is registered. Callers must treat that as not-open, never as
    open-by-default.
    """
    start = _parse_iso(getattr(policy, "effective_from", None))
    end = _parse_iso(getattr(policy, "effective_until", None))
    bounded = start is not None or end is not None
    if moment is None:
        if bounded and offset_hours is None:
            return False, False
        moment = broker_local_now(0.0 if offset_hours is None else offset_hours)
    if start is not None and moment < start:
        return False, True
    if end is not None and moment >= end:
        return False, True
    return True, True


@dataclass(frozen=True)
class PolicyResolution:
    """A resolution and the sentence explaining it.

    Carries the window state as well as the policy, because "which terms govern
    this account" and "is the tournament open right now" are two different
    questions that happen to be answerable from the same record. Collapsing them
    is what made a closed window read as an unmanaged account.
    """

    policy: Optional[ChallengePolicy]
    reason: str
    detail: str
    clock_known: bool = True
    window_open: bool = True
    opens_at: Optional[str] = None
    closes_at: Optional[str] = None
    candidates: List[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.policy is not None

    def as_dict(self) -> Dict[str, Any]:
        return {"policy_version": getattr(self.policy, "policy_version", None),
                "reason": self.reason, "detail": self.detail,
                "resolved": self.resolved, "clock_known": self.clock_known,
                "window_open": self.window_open, "opens_at": self.opens_at,
                "closes_at": self.closes_at, "candidates": list(self.candidates)}


class PolicyRegistry:
    """In-memory, versioned store of challenge policies, keyed by provider/program.

    Deliberately not persisted in this milestone. A policy that survives a
    restart is a policy an operator can rely on, but a policy that silently
    reverts to a previous version after a crash is worse than one that is
    visibly missing -- so the durable half of this lands with the account
    persistence rather than shipping as a half-remembered version history.
    """

    def __init__(self) -> None:
        self._policies: Dict[str, List[ChallengePolicy]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _same_server(a: Optional[str], b: Optional[str]) -> bool:
        """Whether two policies claim the same broker, for uniqueness only.

    Not `matches_server`: that is deliberately asymmetric (a broker-neutral
        policy matches every server) because it answers "does this apply here".
        Uniqueness needs the stricter question "are these the same claim", where
        `None` and `"FTTrading-Server"` are different claims and may coexist.
        """
        if a is None or b is None:
            return a is None and b is None
        return str(a).strip().casefold() == str(b).strip().casefold()

    @staticmethod
    def _slot(provider: str, program: str) -> str:
        return f"{(provider or '').strip().lower()}::{(program or '').strip().lower()}"

    def register(self, policy: ChallengePolicy) -> ChallengePolicy:
        """Add a policy version. Refuses to overwrite one already in force.

        Registering the same version twice is a caller bug that would otherwise
        rewrite history in place: the account that was judged against the old
        terms would silently be judged against new ones with the same version
        label, and nothing in the audit trail would show it.
        """
        if not policy.provider or not policy.program:
            raise ValueError("a policy needs a provider and a program to be registered")
        if not policy.policy_version:
            raise ValueError("a policy needs a version label; unversioned rules "
                             "cannot be audited against the account that ran them")
        slot = self._slot(policy.provider, policy.program)
        with self._lock:
            existing = self._policies.setdefault(slot, [])
            # Version-uniqueness is per server, not per slot. Two brokers can
            # each publish a "2026.10" of the same program with different
            # numbers, and those are legitimately different documents. Refusing
            # the second one would push an operator towards `supersede()` on a
            # version that is not superseded -- which is precisely how one
            # broker's terms end up replacing another's.
            if any(p.policy_version == policy.policy_version
                   and PolicyRegistry._same_server(p.server, policy.server)
                   for p in existing):
                raise ValueError(
                    f"version {policy.policy_version} of {slot}"
                    + (f" on {policy.server}" if policy.server else
                       " (broker-neutral)")
                    + " is already registered; register a new version rather "
                    "than replacing one")
            existing.append(policy)
            # newest effective_from first, so resolve() can stop at the first match
            existing.sort(key=lambda p: (p.effective_from or "", p.policy_version))
            return policy

    def supersede(self, provider: str, program: str, version: str,
                  effective_until: str) -> bool:
        """Close out a version so history stays answerable by date."""
        slot = self._slot(provider, program)
        with self._lock:
            for policy in self._policies.get(slot, []):
                if policy.policy_version == version:
                    if _parse_iso(policy.effective_until) is not None:
                        return False
                    policy.effective_until = effective_until
                    return True
            return False

    def resolve_ex(self, provider: str, program: str, *,
                   on: Optional[str] = None,
                   account_size: Optional[float] = None,
                   server: Optional[str] = None,
                   ignore_window: bool = False,
                   now_offset_hours: Optional[float] = None
                   ) -> PolicyResolution:
        """Resolve, and say why -- including when the window is the reason.

        `on` is a *broker-local* moment. Passing one means the caller has already
        decided which clock it is asking about (a test, or an operator replaying a
        past date), so no offset is needed. Omitting it means "now", and "now" on
        a broker's tournament is only knowable with that broker's offset; a
        window-bounded policy with no offset registered is therefore NOT in force
        here, and says so with `clock_unknown`.

        That is the restrictive direction on purpose. The alternative -- assuming
        the host's wall clock is the broker's -- is a coin flip whose losing side
        is an account judged against a window it never entered, or worse, an
        account that stops being judged at all the moment the assumption goes the
        wrong way near a boundary.
        """
        slot = self._slot(provider, program)
        explicit_moment = _parse_iso(on)
        with self._lock:
            candidates = list(self._policies.get(slot, []))
        names = sorted({p.policy_version for p in candidates})
        if account_size is not None:
            sized = [p for p in candidates
                     if abs(float(p.account_size) - float(account_size)) < 1e-6]
            if sized:
                candidates = sized
        # Terms verified for one broker's document must not decide another
        # broker's account. Filtered *before* the version pick, so a tournament
        # scoped to FTTrading-Server cannot be overtaken by, or overtake, a
        # policy written for a different server.
        matching = [p for p in candidates if p.matches_server(server)]
        if matching:
            candidates = matching
        elif candidates:
            # Policies exist for this provider/program but none is written for
            # this server. Falling back to the nearest one would be exactly the
            # inheritance `matches_server` refuses, so this resolves to nothing
            # and the caller treats it as POLICY_UNKNOWN.
            return PolicyResolution(
                None, NO_CANDIDATES,
                "policies exist for %s but none is written for %s, so none of "
                "their terms may decide this account"
                % (slot, server or "this server"),
                candidates=names)

        def _newest(rows: List[ChallengePolicy]) -> ChallengePolicy:
            return sorted(rows,
                          key=lambda p: (p.effective_from or "", p.policy_version))[-1]

        # Governing terms ignore the clock entirely. An account is judged against
        # the rules it was entered under, so a tournament that ends on schedule
        # must not stop being graded on the rules it was entered under -- that is
        # how enforcement disappears at exactly the moment it is still needed.
        if ignore_window:
            if not candidates:
                return PolicyResolution(
                    None, NO_CANDIDATES,
                    "no policy is registered for %s, so this account is governed "
                    "by no terms at all" % slot, candidates=names)
            chosen = _newest(candidates)
            return PolicyResolution(
                chosen, RESOLVED,
                "%s governs this account from its recorded terms; its window is "
                "not consulted for enforcement" % chosen.policy_version,
                window_open=_window_open(chosen, explicit_moment, now_offset_hours)[0],
                opens_at=chosen.effective_from, closes_at=chosen.effective_until,
                candidates=names)

        if not candidates:
            return PolicyResolution(
                None, NO_CANDIDATES,
                "no policy is registered for %s" % slot, candidates=names)

        applicable: List[ChallengePolicy] = []
        clock_unknown: List[ChallengePolicy] = []
        for policy in candidates:
            start = _parse_iso(policy.effective_from)
            end = _parse_iso(policy.effective_until)
            bounded = start is not None or end is not None
            offset = now_offset_hours
            if offset is None:
                offset = getattr(policy, "server_utc_offset_hours", None)
            moment = explicit_moment
            if moment is None:
                if bounded and offset is None:
                    clock_unknown.append(policy)
                    continue
                moment = broker_local_now(0.0 if offset is None else offset)
            is_open, known = _window_open(policy, moment, offset)
            if not known:
                clock_unknown.append(policy)
                continue
            if is_open:
                applicable.append(policy)

        if applicable:
            chosen = _newest(applicable)
            return PolicyResolution(
                chosen, RESOLVED,
                "%s is in force for %s" % (chosen.policy_version, slot),
                window_open=True, opens_at=chosen.effective_from,
                closes_at=chosen.effective_until, candidates=names)

        if clock_unknown:
            listed = ", ".join(p.policy_version for p in clock_unknown)
            return PolicyResolution(
                None, CLOCK_UNKNOWN,
                "%s carries a start/end window but no broker UTC offset is "
                "registered for it, so this system cannot tell whether it is "
                "open and is refusing to assume; register "
                "server_utc_offset_hours and the question becomes answerable"
                % listed,
                clock_known=False, window_open=False,
                opens_at=clock_unknown[0].effective_from,
                closes_at=clock_unknown[0].effective_until, candidates=names)

        newest = _newest(candidates)
        return PolicyResolution(
            None, WINDOW_CLOSED,
            "no version of %s is open right now (%s opens %s, closes %s)"
            % (slot, newest.policy_version, newest.effective_from or "open-ended",
               newest.effective_until or "open-ended"),
            window_open=False, opens_at=newest.effective_from,
            closes_at=newest.effective_until, candidates=names)

    def resolve(self, provider: str, program: str, *,
                on: Optional[str] = None,
                account_size: Optional[float] = None,
                server: Optional[str] = None) -> Optional[ChallengePolicy]:
        """The policy in force for this account on this date, or None.

        None means "no policy applies", and callers must treat that as
        POLICY_UNKNOWN. It is not a default policy and it is not an error to be
        swallowed -- 34.6's chain starts there.

        `resolve_ex` is the same answer with the reason attached; use it wherever
        an operator or the console will read the outcome.
        """
        return self.resolve_ex(provider, program, on=on,
                               account_size=account_size, server=server).policy

    def versions(self, provider: str, program: str) -> List[Dict[str, Any]]:
        """Every registered version, newest first, with its verification state.

        Surfacing `missing_rules` here is deliberate: an operator registering a
        policy needs to see that it is still incomplete at the moment they
        register it, not discover it when a trade is refused three days later.
        """
        slot = self._slot(provider, program)
        with self._lock:
            policies = sorted(
                self._policies.get(slot, []),
                key=lambda p: (p.effective_from or "", p.policy_version), reverse=True)
        return [
            {
                "policy_version": p.policy_version,
                "effective_from": p.effective_from,
                "effective_until": p.effective_until,
                "account_size": p.account_size,
                "is_fully_specified": p.is_fully_specified,
                "is_fully_resolved": p.is_fully_resolved,
                "missing_rules": p.missing_rules(),
                "key": p.key,
            }
            for p in policies
        ]

    def all_policies(self) -> List[ChallengePolicy]:
        with self._lock:
            return [p for slot in self._policies.values() for p in slot]

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "registered": len(self.all_policies()),
                "note": "the registry ships empty on purpose: an unresolved policy "
                        "restricts trading rather than assuming provider terms",
            }


#: Process-wide registry, matching the repo's one-process-one-state convention.
registry = PolicyRegistry()
