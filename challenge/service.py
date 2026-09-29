"""Wiring the challenge layer to the account facts the rest of the system already has.

34.11 requires challenge accounts to use the same engine, risk and execution
architecture as live accounts, so this module opens nothing, places nothing, and
owns no account state. It reads the canonical state that the MT5 sync loop is
already maintaining and answers the policy questions over it.

**The restart hazard, stated up front because it is the sharpest edge here.**
The numbers that decide a static-drawdown account -- its opening equity and its
all-time low -- are a *history*, and a history held in memory does not survive
the watchdog restart that this 24/7 host performs routinely. An account that
breached 4% and recovered would come back after a restart with no memory of the
breach, be scored at zero used drawdown, and be handed ALLOW. That is precisely
the failure this layer exists to prevent, arriving through the memory subsystem.

So a baseline is required before any account may be graded. Until the service
has both an opening equity and an observed low, the account reads ONBOARDING
and the permission is not ALLOW. It fails toward refusing rather than toward
trading, which is the only safe direction for a control whose whole purpose is
to notice a breach that has already happened. `ChallengeService.baseline_status`
reports the gap so it is visible rather than inferred, and persisting the
baseline to SQLite is the next milestone -- the in-memory version is honest
about its own limits because a restart downgrades the account to ONBOARDING
instead of quietly clearing it.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from .headroom import AccountSnapshot, Permission, headroom_report, permission_for
from .policy import ChallengePolicy
from .registry import PolicyRegistry, registry as default_registry
from .state_machine import ChallengeState, ChallengeStateMachine, TransitionRefused


class _Baseline:
    """The account facts a policy decision needs and cannot recompute.

    Held per account so two accounts never share a baseline, which is 34.13's
    independence requirement expressed as a data-structure property rather than
    as a convention someone has to remember.
    """

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.start_equity: Optional[float] = None
        self.equity_low: Optional[float] = None
        self.day_epoch: Optional[int] = None
        self.day_start_equity: Optional[float] = None
        self.day_low_equity: Optional[float] = None
        self.last_seen: Optional[float] = None
        self.trading_days: int = 0

    def observe(self, equity: float, balance: float,
                margin: float = 0.0, open_risk: float = 0.0,
                day_epoch: Optional[int] = None) -> None:
        """Fold one reading in, rolling the day when the epoch changes.

        The day roll is what returns a floating account's room. Doing it here
        rather than in the calculator is deliberate: the calculator must be a
        pure function of its inputs, or "what is my headroom" becomes a
        question with side effects.
        """
        equity = float(equity or 0.0)
        today = int(day_epoch if day_epoch is not None else time.time() // 86400)
        if self.start_equity is None:
            self.start_equity = float(balance or equity)
            self.equity_low = equity
        if self.day_epoch is None or today != self.day_epoch:
            self.day_epoch = today
            self.day_start_equity = equity
            self.day_low_equity = equity
            self.trading_days += 1
        if self.equity_low is None or equity < self.equity_low:
            self.equity_low = equity
        if self.day_low_equity is None or equity < self.day_low_equity:
            self.day_low_equity = equity
        self.last_seen = time.time()
        self._margin = margin
        self._open_risk = open_risk

    def as_snapshot(self, equity: float, balance: float,
                    margin: float = 0.0, open_risk: float = 0.0) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=self.account_id,
            balance=float(balance or 0.0),
            equity=float(equity or 0.0),
            margin=float(margin or 0.0),
            open_risk=float(open_risk or 0.0),
            day_start_equity=self.day_start_equity,
            day_low_equity=self.day_low_equity,
            start_equity=self.start_equity,
            equity_low=self.equity_low,
            trading_days=self.trading_days,
        )

    @property
    def has_baseline(self) -> bool:
        """Whether the account can be graded at all.

        Requires a *positive* opening equity, not merely a recorded one. A
        terminal that is attached but reporting nothing gives a reading of
        equity=0, balance=0, and a baseline built from that would score every
        limit as fully available -- a disconnected account would look like the
        healthiest account on the platform. Refusing to grade a zero baseline
        is the only safe reading of "we have not actually seen this account".
        """
        return bool(self.start_equity) and self.equity_low is not None


class ChallengeService:
    """One account's challenge posture: its baseline, its policy, its state.

    Not a singleton here on purpose -- the module-level `challenge_service` is,
    but constructing one is cheap and takes an injected registry, so a test can
    give it an empty registry and never touch the process-wide one.
    """

    def __init__(self, registry: Optional[PolicyRegistry] = None) -> None:
        self._registry = registry or default_registry
        self._baselines: Dict[str, _Baseline] = {}
        self._machines: Dict[str, ChallengeStateMachine] = {}
        self._lock = threading.RLock()

    # -- account wiring -------------------------------------------------

    def machine(self, account_id: str) -> ChallengeStateMachine:
        with self._lock:
            machine = self._machines.get(account_id)
            if machine is None:
                machine = ChallengeStateMachine(account_id)
                self._machines[account_id] = machine
            return machine

    def observe(self, account_id: str, *, equity: float, balance: float,
                margin: float = 0.0, open_risk: float = 0.0,
                day_epoch: Optional[int] = None) -> AccountSnapshot:
        """Record one reading of the real account and return the snapshot.

        `day_epoch` is injectable so a replay or a backfill can drive the day
        roll deliberately rather than waiting for UTC midnight -- the roll is
        what returns a floating account's room, and a control that can only be
        tested at midnight is a control nobody tests.
        """
        with self._lock:
            baseline = self._baselines.get(account_id)
            if baseline is None:
                baseline = _Baseline(account_id)
                self._baselines[account_id] = baseline
            baseline.observe(equity, balance, margin, open_risk, day_epoch=day_epoch)
            return baseline.as_snapshot(equity, balance, margin, open_risk)

    def snapshot(self, account_id: str, *, equity: float, balance: float,
                 margin: float = 0.0, open_risk: float = 0.0) -> AccountSnapshot:
        """Snapshot for the current reading, without folding it into the baseline.

        `observe` is the only method that may change the baseline, so reading
        the current position cannot quietly advance the reference points a
        decision is measured from. An account with no baseline does not get one
        created here: grading a never-observed account would make `has_baseline`
        report a state the account was never in, and would list the account as
        known when nothing about it is.
        """
        with self._lock:
            baseline = self._baselines.get(account_id)
            if baseline is None:
                return AccountSnapshot(account_id=account_id,
                                       balance=float(balance or 0.0),
                                       equity=float(equity or 0.0),
                                       margin=float(margin or 0.0),
                                       open_risk=float(open_risk or 0.0))
            return baseline.as_snapshot(equity, balance, margin, open_risk)

    def baseline_status(self, account_id: str) -> Dict[str, Any]:
        """Whether this account can be graded, and why not if it cannot."""
        with self._lock:
            baseline = self._baselines.get(account_id)
        if baseline is None:
            return {"account_id": account_id, "has_baseline": False,
                    "reason": "no observation recorded yet; the opening equity "
                              "and low-water marks are unknown"}
        return {
            "account_id": account_id,
            "has_baseline": baseline.has_baseline,
            "start_equity": baseline.start_equity,
            "equity_low": baseline.equity_low,
            "day_start_equity": baseline.day_start_equity,
            "day_low_equity": baseline.day_low_equity,
            "trading_days": baseline.trading_days,
            "last_seen": baseline.last_seen,
            "reason": None if baseline.has_baseline else
                      "baseline incomplete; refusing to grade the account",
        }

    def forget(self, account_id: str) -> bool:
        with self._lock:
            had = self._baselines.pop(account_id, None) is not None
            self._machines.pop(account_id, None)
            return had

    # -- policy + decision ---------------------------------------------

    def policy_for(self, provider: str, program: str, *,
                   account_size: Optional[float] = None,
                   on: Optional[str] = None) -> Optional[ChallengePolicy]:
        return self._registry.resolve(provider, program, on=on,
                                      account_size=account_size)

    def evaluate(self, account_id: str, policy: Optional[ChallengePolicy], *,
                 equity: float, balance: float, margin: float = 0.0,
                 open_risk: float = 0.0, proposed_risk: float = 0.0,
                 symbol: Optional[str] = None, is_news_window: bool = False,
                 is_weekend: bool = False) -> Dict[str, Any]:
        """The 34.22 answer: state, headroom, permission -- and whether it counts.

        `counts` is the load-bearing field. It is False when the baseline is
        incomplete or the policy is unresolved, and the caller is expected to
        treat a permission of ALLOW as meaningless when it is False. That is
        what stops a restart from converting a breached account into an
        allowance.
        """
        snapshot = self.snapshot(account_id, equity=equity, balance=balance,
                                 margin=margin, open_risk=open_risk)
        status = self.baseline_status(account_id)
        report = headroom_report(policy, snapshot)
        decision = permission_for(policy, snapshot, proposed_risk=proposed_risk,
                                  symbol=symbol, is_news_window=is_news_window,
                                  is_weekend=is_weekend)
        machine = self.machine(account_id)
        counts = bool(status["has_baseline"]) and policy is not None
        reasons: List[str] = []
        if not status["has_baseline"]:
            reasons.append(status.get("reason") or "baseline incomplete")
        if policy is None:
            reasons.append("no challenge policy resolves for this account")
        elif not policy.is_fully_specified:
            reasons.append("policy unverified: "
                           + ", ".join(policy.missing_rules()))
        if reasons and decision["permission"] == Permission.ALLOW.value:
            decision["permission"] = Permission.PROTECT.value
        return {
            "account_id": account_id,
            "snapshot": snapshot.as_dict(),
            "baseline": status,
            "headroom": report,
            "decision": decision,
            "state": machine.as_dict(),
            "counts": counts,
            "blocking_reasons": reasons,
        }

    def register_policy(self, policy: ChallengePolicy) -> Dict[str, Any]:
        """Register a policy version and report whether it is usable yet.

        The completeness report comes back on the registration call itself.
        Registering half a policy is a legitimate first step -- the operator
        will often know the drawdown rule before the rest -- but it has to be
        visibly incomplete at the moment it is registered rather than at the
        moment a trade is refused days later.
        """
        registered = self._registry.register(policy)
        return {
            "registered": True,
            "key": registered.key,
            "policy_version": registered.policy_version,
            "is_fully_specified": registered.is_fully_specified,
            "missing_rules": registered.missing_rules(),
            "effect": "usable for trading" if registered.is_fully_specified else
                      "registered but RESTRICTING: the account cannot be graded "
                      "until these rules are verified",
        }

    def transition(self, account_id: str, target: ChallengeState, *,
                   reason: str, actor: str = "system") -> Dict[str, Any]:
        machine = self.machine(account_id)
        try:
            record = machine.transition(target, reason=reason, actor=actor)
        except TransitionRefused as exc:
            return {"applied": False, "reason": exc.reason,
                    "state": machine.state.value}
        return {"applied": True, "transition": record.as_dict(),
                "state": machine.state.value}

    def recover(self, account_id: str, *, reason: str, authorized_by: str,
                conditions_met: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        machine = self.machine(account_id)
        try:
            record = machine.recover(reason=reason, authorized_by=authorized_by,
                                     conditions_met=conditions_met)
        except TransitionRefused as exc:
            return {"applied": False, "reason": exc.reason,
                    "state": machine.state.value}
        return {"applied": True, "transition": record.as_dict(),
                "state": machine.state.value}

    def accounts(self) -> List[str]:
        with self._lock:
            return sorted(self._baselines)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "accounts": sorted(self._baselines),
                "registry": self._registry.as_dict(),
                "execution": "none — this layer reads account state and decides "
                             "permission; it never places or closes an order",
                "baseline_persistence": "in-memory; a restart downgrades an "
                                        "account to ONBOARDING rather than "
                                        "clearing its history",
            }


#: Process-wide service, matching the repo's one-process-one-state convention.
challenge_service = ChallengeService()
