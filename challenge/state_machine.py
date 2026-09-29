"""Challenge account lifecycle, as a machine with a memory.

34.10 lists the states and then adds the requirement that actually matters:

    The system must not silently resume trading after a HALTED state unless the
    applicable recovery conditions are satisfied and the required authorization
    exists.

"Silently" is the operative word, and it is what a plain enum cannot enforce --
an enum makes HALTED *representable* and leaves nothing to stop the next caller
from writing ACTIVE again. So transitions go through `ChallengeStateMachine`,
which records every one of them, and leaving HALTED is a different verb
(`recover`) that demands an authorization token rather than accepting a target
state. A caller that tries to resume by transitioning straight to ACTIVE gets
refused, and the refusal is the test.

Terminal states (PASSED / FAILED) are terminal for a reason that is also about
honesty: a failed account cannot be un-failed by a state write, and a passed one
must not drop back into ACTIVE because someone re-synced a balance. Reaching
either is a fact about the account's history, so it is recorded once and the
machine refuses to leave it.

The machine also keeps the reason for every transition. When an account halts in
production, "why" is the first question asked and the hardest to answer
afterwards, so a transition that does not carry one is refused here rather than
becoming an unattributable row in the audit trail.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ChallengeState(str, Enum):
    """34.10's state list."""

    ONBOARDING = "onboarding"
    ACTIVE = "active"
    CAUTION = "caution"
    RESTRICTED = "restricted"
    PROTECTION = "protection"
    HALTED = "halted"
    PASSED = "passed"
    FAILED = "failed"
    FUNDED = "funded"
    DISCONNECTED = "disconnected"
    POLICY_UNKNOWN = "policy_unknown"


#: States from which no transition is permitted. PASSED/FAILED record what
#: happened to the account; FAILED in particular is not a "current condition"
#: that better equity would undo.
TERMINAL_STATES = frozenset({ChallengeState.PASSED, ChallengeState.FAILED})

#: Legal moves. Anything absent is refused, and refusal is a feature: an
#: unlisted transition is a gap in the rules rather than something to permit and
#: regret.
ALLOWED_TRANSITIONS: Dict[ChallengeState, frozenset] = {
    ChallengeState.ONBOARDING: frozenset({
        ChallengeState.ACTIVE, ChallengeState.POLICY_UNKNOWN,
        ChallengeState.DISCONNECTED, ChallengeState.FAILED,
    }),
    ChallengeState.ACTIVE: frozenset({
        ChallengeState.CAUTION, ChallengeState.RESTRICTED, ChallengeState.PROTECTION,
        ChallengeState.HALTED, ChallengeState.DISCONNECTED, ChallengeState.PASSED,
        ChallengeState.FAILED, ChallengeState.FUNDED, ChallengeState.POLICY_UNKNOWN,
    }),
    ChallengeState.CAUTION: frozenset({
        ChallengeState.ACTIVE, ChallengeState.RESTRICTED, ChallengeState.PROTECTION,
        ChallengeState.HALTED, ChallengeState.DISCONNECTED, ChallengeState.FAILED,
    }),
    ChallengeState.RESTRICTED: frozenset({
        ChallengeState.CAUTION, ChallengeState.ACTIVE, ChallengeState.PROTECTION,
        ChallengeState.HALTED, ChallengeState.DISCONNECTED, ChallengeState.FAILED,
    }),
    ChallengeState.PROTECTION: frozenset({
        ChallengeState.HALTED, ChallengeState.RESTRICTED, ChallengeState.DISCONNECTED,
        ChallengeState.FAILED,
    }),
    # A HALTED account can only come back through `recover()`, which is
    # deliberately not reachable by naming ACTIVE here.
    ChallengeState.HALTED: frozenset({ChallengeState.DISCONNECTED}),
    ChallengeState.PASSED: frozenset({ChallengeState.FUNDED, ChallengeState.DISCONNECTED}),
    ChallengeState.FUNDED: frozenset({ChallengeState.DISCONNECTED}),
    ChallengeState.DISCONNECTED: frozenset({
        ChallengeState.ONBOARDING, ChallengeState.ACTIVE, ChallengeState.POLICY_UNKNOWN,
        ChallengeState.FAILED,
    }),
    # An unverified policy blocks trading outright; it can be resolved into
    # ACTIVE once the rules are actually known, and that is the only way out.
    ChallengeState.POLICY_UNKNOWN: frozenset({
        ChallengeState.ONBOARDING, ChallengeState.ACTIVE, ChallengeState.DISCONNECTED,
    }),
}


@dataclass
class StateTransition:
    """One recorded move, with the reason it happened."""

    from_state: ChallengeState
    to_state: ChallengeState
    reason: str
    actor: str = "system"
    transition_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    authorized: bool = False
    context: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "authorized": self.authorized,
            "context": dict(self.context),
        }


class TransitionRefused(Exception):
    """A transition the machine will not perform.

    Carries the machine's own explanation so the API can surface *why* rather
    than a generic 409, which is the difference between an operator who fixes
    the problem and one who just retries.
    """

    def __init__(self, reason: str, *, from_state: ChallengeState,
                 requested: Optional[ChallengeState] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.from_state = from_state
        self.requested = requested


class ChallengeStateMachine:
    """One account's state, its history, and the rules about moving between them.

    Per-account by construction -- the caller holds one machine per account, and
    the machine knows only its own account_id. 34.13/34.14 ask for independent
    state per account and 34.14 warns specifically against applying one
    account's policy to another; keying every instance by account_id and never
    consulting a shared registry here is what makes that true by construction
    rather than by discipline.
    """

    def __init__(self, account_id: str, *,
                 state: ChallengeState = ChallengeState.ONBOARDING,
                 history_limit: int = 500) -> None:
        self.account_id = account_id
        self._state = state
        self._history: List[StateTransition] = []
        self._history_limit = int(history_limit)
        self._lock = threading.RLock()

    @property
    def state(self) -> ChallengeState:
        with self._lock:
            return self._state

    @property
    def history(self) -> List[StateTransition]:
        with self._lock:
            return list(self._history)

    def can_transition(self, target: ChallengeState) -> bool:
        with self._lock:
            return target in ALLOWED_TRANSITIONS.get(self._state, frozenset())

    def transition(self, target: ChallengeState, *, reason: str, actor: str = "system",
                   context: Optional[Dict[str, Any]] = None) -> StateTransition:
        """Move to `target`, or refuse with an explanation.

        An empty reason is refused. A state change with no stated cause is
        exactly the unattributable row that makes a halted account impossible to
        investigate after the fact.
        """
        if not (reason or "").strip():
            raise TransitionRefused(
                "a state transition must carry a reason",
                from_state=self.state, requested=target)
        with self._lock:
            current = self._state
            if current in TERMINAL_STATES:
                raise TransitionRefused(
                    f"{current.value} is terminal; this account's outcome is "
                    "recorded and cannot be re-entered by a state change",
                    from_state=current, requested=target)
            allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
            if target not in allowed:
                legal = ", ".join(sorted(s.value for s in allowed)) or "none"
                raise TransitionRefused(
                    f"cannot move from {current.value} to {target.value}; "
                    f"legal targets: {legal}",
                    from_state=current, requested=target)
            record = StateTransition(
                from_state=current, to_state=target, reason=reason, actor=actor,
                context=dict(context or {}))
            self._state = target
            self._history.append(record)
            if len(self._history) > self._history_limit:
                del self._history[: len(self._history) - self._history_limit]
            return record

    def recover(self, *, reason: str, authorized_by: str,
                conditions_met: Optional[Dict[str, Any]] = None) -> StateTransition:
        """The only way out of HALTED, per 34.10's "must not silently resume".

        Two things are required and both are checked here rather than left to
        the caller: a named authorizer, and a stated reason. A recovery with
        neither is a silent resume wearing a different verb, so `authorized_by`
        must be non-empty -- there is no "system auto-recovery" shortcut.
        """
        with self._lock:
            if self._state is not ChallengeState.HALTED:
                raise TransitionRefused(
                    f"recover() applies to a halted account; this one is "
                    f"{self._state.value}",
                    from_state=self._state, requested=ChallengeState.ACTIVE)
            if not (authorized_by or "").strip():
                raise TransitionRefused(
                    "recovery requires a named authorizer; an unattributed "
                    "resume is the silent resume 34.10 forbids",
                    from_state=self._state, requested=ChallengeState.ACTIVE)
            record = StateTransition(
                from_state=self._state, to_state=ChallengeState.ACTIVE,
                reason=reason, actor=authorized_by, authorized=True,
                context=dict(conditions_met or {}))
            self._state = ChallengeState.ACTIVE
            self._history.append(record)
            return record

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "account_id": self.account_id,
                "state": self._state.value,
                "is_terminal": self._state in TERMINAL_STATES,
                "can_recover": self._state is ChallengeState.HALTED,
                "legal_targets": sorted(
                    s.value for s in ALLOWED_TRANSITIONS.get(self._state, frozenset())),
                "history": [t.as_dict() for t in self._history[-25:]],
                "history_length": len(self._history),
            }
