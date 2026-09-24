"""Governance Core: identity, subscriptions, entitlements, audit.

Handles who can do what, state transitions for subscriptions,
and an append-only audit trail of all accountable actions.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from research.strategy_lab.contracts import DrawdownPolicy

from core.logging import get_logger


log = get_logger("governance")


def _persist_user(user: "User", subscription: Optional["Subscription"] = None) -> None:
    """Best-effort persistence hook; never blocks or masks the main path."""
    try:
        from persistence.db import make_live_session, persistence_enabled
        from persistence.repositories import UserRepository

        if not persistence_enabled():
            return
        session = make_live_session()
        try:
            repo = UserRepository(session)
            repo.save(user, subscription=subscription)
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        log.debug(f"User persistence skipped for {getattr(user, 'user_id', '?')}")


class SubscriptionPlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    INSTITUTIONAL = "institutional"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    PENDING = "pending"


class Entitlement(str, Enum):
    CAN_TRADE = "can_trade"
    CAN_COPY = "can_copy"
    CAN_MANAGE_RISK = "can_manage_risk"
    READ_ONLY = "read_only"
    MULTI_ACCOUNT = "multi_account"
    API_ACCESS = "api_access"


# Plan -> set of entitlements
PLAN_ENTITLEMENTS: Dict[SubscriptionPlan, set[Entitlement]] = {
    SubscriptionPlan.FREE: {Entitlement.READ_ONLY},
    SubscriptionPlan.STARTER: {Entitlement.CAN_TRADE},
    SubscriptionPlan.PRO: {
        Entitlement.CAN_TRADE,
        Entitlement.CAN_COPY,
        Entitlement.MULTI_ACCOUNT,
    },
    SubscriptionPlan.INSTITUTIONAL: set(Entitlement),
}


@dataclass
class RiskPolicy:
    max_risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_drawdown: float = 0.10
    max_open_positions: int = 5
    max_leverage: float = 10.0
    require_stop_loss: bool = True
    drawdown_mode: str = "governed"           # DrawdownMode value
    drawdown_lab_cap_r: float = 3.0
    drawdown_gov_cap_r: float = 12.0
    drawdown_gov_override: bool = False


    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class User:
    user_id: str
    email: str
    display_name: str
    plan: SubscriptionPlan = SubscriptionPlan.FREE
    subscription_status: SubscriptionStatus = SubscriptionStatus.PENDING
    entitlements: set[Entitlement] = field(default_factory=set)
    risk_policy: RiskPolicy = field(default_factory=RiskPolicy)
    account_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def grant_plan_entitlements(self) -> None:
        self.entitlements = set(PLAN_ENTITLEMENTS.get(self.plan, set()))

    def has_entitlement(self, entitlement: Entitlement) -> bool:
        if self.subscription_status != SubscriptionStatus.ACTIVE:
            return False
        return entitlement in self.entitlements

    def as_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "plan": self.plan.value,
            "subscription_status": self.subscription_status.value,
            "entitlements": sorted(e.value for e in self.entitlements),
            "risk_policy": self.risk_policy.as_dict(),
            "account_ids": self.account_ids,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Subscription:
    subscription_id: str
    user_id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus
    started_at: float
    expires_at: float
    auto_renew: bool = False

    def is_active(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return (
            self.status == SubscriptionStatus.ACTIVE
            and self.expires_at > now
        )

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class AuditEntry:
    entry_id: str
    timestamp: float
    actor: str
    action: str
    object_type: str
    object_id: str
    details: Dict[str, Any] = field(default_factory=dict)
    success: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class IdentityService:
    """Manages users, subscriptions, entitlements, and audit log.

    In this version, state lives in-memory. A persistence layer
    (PostgreSQL) can be attached later by implementing the same contract.
    """

    def __init__(self) -> None:
        self._users: Dict[str, User] = {}
        self._subscriptions: Dict[str, Subscription] = {}
        self._audit: List[AuditEntry] = []

    # -- Users ----------------------------------------------------------
    def create_user(self, email: str, display_name: str,
                    plan: SubscriptionPlan = SubscriptionPlan.FREE,
                    risk_policy: Optional[RiskPolicy] = None) -> User:
        user_id = str(uuid.uuid4())
        user = User(
            user_id=user_id,
            email=email,
            display_name=display_name,
            plan=plan,
            risk_policy=risk_policy or RiskPolicy(),
        )
        user.grant_plan_entitlements()

        self._subscriptions[user_id] = Subscription(
            subscription_id=str(uuid.uuid4()),
            user_id=user_id,
            plan=plan,
            status=SubscriptionStatus.PENDING,
            started_at=time.time(),
            expires_at=time.time(),
            auto_renew=False,
        )
        self._users[user_id] = user
        self._log("system", "user.create", "User", user_id,
                  {"email": email, "plan": plan.value})
        log.info(f"User created {user_id} ({email})")
        _persist_user(user, self._subscriptions[user_id])
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> Optional[User]:
        for u in self._users.values():
            if u.email == email:
                return u
        return None

    def list_users(self) -> List[User]:
        return list(self._users.values())

    def rehydrate(self) -> int:
        """Reload users/subscription mirrors from persistence into memory."""
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.models import UserRecord
            from persistence.repositories import UserRepository

            if not persistence_enabled():
                return 0
            session = make_live_session()
            try:
                repo = UserRepository(session)
                stored_users = repo.list(limit=10_000)
                stored_rows = {
                    row.user_id: row for row in session.query(UserRecord).all()
                }
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Identity rehydrate skipped: {exc}")
            return 0

        self._users = {}
        self._subscriptions = {}
        for user in stored_users:
            self._users[user.user_id] = user
            row = stored_rows.get(user.user_id)
            self._subscriptions[user.user_id] = Subscription(
                subscription_id=f"rehydrated:{user.user_id}",
                user_id=user.user_id,
                plan=user.plan,
                status=user.subscription_status,
                started_at=user.created_at,
                expires_at=float(row.expires_at) if row is not None else 0.0,
                auto_renew=False,
            )
        return len(stored_users)

    def set_risk_policy(self, user_id: str, policy: RiskPolicy) -> None:
        user = self._get_or_raise(user_id)
        user.risk_policy = policy
        user.updated_at = time.time()
        self._log("user", "risk_policy.update", "User", user_id,
                  {"policy": policy.as_dict()})
        _persist_user(user)

    # -- Subscriptions --------------------------------------------------
    def activate_subscription(self, user_id: str, plan: SubscriptionPlan,
                              duration_seconds: float = 30 * 24 * 3600) -> Subscription:
        user = self._get_or_raise(user_id)
        sub = self._subscriptions[user_id]
        sub.plan = plan
        sub.status = SubscriptionStatus.ACTIVE
        sub.started_at = time.time()
        sub.expires_at = time.time() + duration_seconds

        user.plan = plan
        user.subscription_status = SubscriptionStatus.ACTIVE
        user.grant_plan_entitlements()
        user.updated_at = time.time()

        self._log("user", "subscription.activate", "Subscription", sub.subscription_id,
                  {"plan": plan.value, "expires_at": sub.expires_at})
        log.info(f"Subscription activated for {user_id}: {plan.value}")
        _persist_user(user, sub)
        return sub

    def expire_subscription(self, user_id: str) -> None:
        user = self._get_or_raise(user_id)
        sub = self._subscriptions[user_id]
        sub.status = SubscriptionStatus.EXPIRED
        user.subscription_status = SubscriptionStatus.EXPIRED
        user.entitlements = set()
        user.updated_at = time.time()
        self._log("system", "subscription.expire", "Subscription", sub.subscription_id,
                  {"reason": "expired"})
        log.warning(f"Subscription expired for {user_id}")
        _persist_user(user, sub)

    def check_expirations(self) -> List[str]:
        """Expire any subscriptions past their expiry. Returns impacted user_ids."""
        expired = []
        now = time.time()
        for user_id, sub in self._subscriptions.items():
            if sub.status == SubscriptionStatus.ACTIVE and sub.expires_at <= now:
                self.expire_subscription(user_id)
                expired.append(user_id)
        return expired

    # -- Entitlements ---------------------------------------------------
    def can(self, user_id: str, entitlement: Entitlement) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        return user.has_entitlement(entitlement)

    # -- Audit ----------------------------------------------------------
    def _log(self, actor: str, action: str, object_type: str,
             object_id: str, details: Optional[Dict[str, Any]] = None,
             success: bool = True) -> None:
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=time.time(),
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            details=details or {},
            success=success,
        )
        self._audit.append(entry)
        self._persist_audit(entry)

    def record_audit(self, actor: str, action: str, object_type: str,
                     object_id: str, details: Optional[Dict[str, Any]] = None,
                     success: bool = True) -> None:
        """Public append-only audit hook (used by lab endpoints)."""
        self._log(actor, action, object_type, object_id, details, success)

    def _persist_audit(self, entry: AuditEntry) -> None:
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.repositories import AuditRepository

            if not persistence_enabled():
                return
            session = make_live_session()
            try:
                AuditRepository(session).append(entry)
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            log.debug("Audit persistence skipped")

    def audit_log(self, limit: int = 100) -> List[AuditEntry]:
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.repositories import AuditRepository

            if persistence_enabled():
                session = make_live_session()
                try:
                    persisted = AuditRepository(session).list(limit)
                    if persisted:
                        return persisted
                finally:
                    session.close()
        except Exception:  # noqa: BLE001
            pass
        return list(reversed(self._audit))[:limit]

    # -- Helpers --------------------------------------------------------
    def _get_or_raise(self, user_id: str) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise KeyError(f"Unknown user: {user_id}")
        return user


_default_risk_policy: RiskPolicy = RiskPolicy()


def set_governance_drawdown(policy: "DrawdownPolicy") -> None:
    """Sync the governance default risk policy from a lab-applied choice.

    The lab stays WITH governance: whatever drawdown mode/caps the operator
    applies through the lab is pushed into the governance risk policy so
    subsequent sweeps and risk views inherit it.
    """
    _default_risk_policy.drawdown_mode = policy.mode.value
    _default_risk_policy.drawdown_lab_cap_r = policy.lab_cap_r
    _default_risk_policy.drawdown_gov_cap_r = policy.gov_cap_r
    _default_risk_policy.drawdown_gov_override = policy.gov_override


def drawdown_policy(risk: Optional[RiskPolicy] = None) -> "DrawdownPolicy":
    """Build a lab DrawdownPolicy from the current governance risk policy.

    DEFAULT IS GOVERNED: the lab science opens the drawdown gate and the
    governance risk policy holds the final cap (see DrawdownMode).
    """

    r = risk or _default_risk_policy
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy

    try:
        mode = DrawdownMode(r.drawdown_mode)
    except ValueError:
        mode = DrawdownMode.GOVERNED
    return DrawdownPolicy(
        mode=mode,
        lab_cap_r=r.drawdown_lab_cap_r,
        gov_cap_r=r.drawdown_gov_cap_r,
        gov_override=r.drawdown_gov_override,
    )


identity = IdentityService()
