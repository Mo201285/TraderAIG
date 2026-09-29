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
from datetime import datetime
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
            if any(p.policy_version == policy.policy_version for p in existing):
                raise ValueError(
                    f"version {policy.policy_version} of {slot} is already "
                    "registered; register a new version rather than replacing one")
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

    def resolve(self, provider: str, program: str, *,
                on: Optional[str] = None,
                account_size: Optional[float] = None) -> Optional[ChallengePolicy]:
        """The policy in force for this account on this date, or None.

        None means "no policy applies", and callers must treat that as
        POLICY_UNKNOWN. It is not a default policy and it is not an error to be
        swallowed -- 34.6's chain starts there.
        """
        slot = self._slot(provider, program)
        moment = _parse_iso(on) or datetime.now()
        with self._lock:
            candidates = list(self._policies.get(slot, []))
        if account_size is not None:
            sized = [p for p in candidates
                     if abs(float(p.account_size) - float(account_size)) < 1e-6]
            if sized:
                candidates = sized
        applicable = []
        for policy in candidates:
            start = _parse_iso(policy.effective_from)
            end = _parse_iso(policy.effective_until)
            if start and moment < start:
                continue
            if end and moment >= end:
                continue
            applicable.append(policy)
        if not applicable:
            return None
        return sorted(applicable,
                      key=lambda p: (p.effective_from or "", p.policy_version))[-1]

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
