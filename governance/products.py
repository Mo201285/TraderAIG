"""Commercial products: paid service entitlements that are NOT subscription plans.

§34.2 puts a $9.99 Challenge Management service in front of the same engine, and
§34.18 is the constraint that decides how it is modelled here: commercial access
must be represented independently from trading logic, and a product entitlement
must never grant trade permission.

The tempting implementation is a new `SubscriptionPlan.CHALLENGE`. It is wrong,
and wrong in a way this codebase has already paid for. `grant_plan_entitlements`
REPLACES the user's whole entitlement set, so routing a $9.99 purchase through the
plan field would take `can_trade` away from an operator who is actively trading.
A product purchase is therefore its own record with its own lifecycle, granted by
`payments` against a verified charge and read through its own accessor. A plan can
never take one of these away, and one of these can never grant a plan right.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from governance.identity import Entitlement, identity

log = get_logger("governance")


class ProductState(str, Enum):
    """§34.20 lifecycle. Deliberately not the subscription statuses."""

    ACTIVE = "active"
    GRACE_PERIOD = "grace_period"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


#: States in which the service is still owed to the buyer. GRACE_PERIOD counts:
#: a card that fails to renew at midnight should not halt a challenge account in
#: the middle of its session, and §34.20 lists it as a distinct state for exactly
#: that reason. SUSPENDED deliberately does NOT count — a suspended entitlement
#: is an operator decision to stop serving, not a billing delay.
EFFECTIVE_STATES = (ProductState.ACTIVE, ProductState.GRACE_PERIOD)


@dataclass(frozen=True)
class Product:
    """A thing that can be bought, with the exact entitlement it buys.

    The price lives HERE, on the server, and never travels from a request. The
    caller names a `product_id`; that is the whole input. A caller that could
    post its own amount would make the charge a suggestion.
    """

    product_id: str
    name: str
    price_usd: float
    entitlement: Entitlement
    duration_days: int = 30
    grace_days: int = 3
    grants_trade_permission: bool = False
    description: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "price_usd": self.price_usd,
            "entitlement": self.entitlement.value,
            "duration_days": self.duration_days,
            "grace_days": self.grace_days,
            "grants_trade_permission": self.grants_trade_permission,
            "description": self.description,
        }


#: The §34.2 catalogue. One product today.
#:
#: `grants_trade_permission=False` is the §34.18 promise encoded as a field rather
#: than a comment: buying challenge management on an account does not license
#: that account to trade, and `charge_product` refuses to activate a product that
#: claims otherwise.
PRODUCTS: Dict[str, Product] = {
    "challenge_basic": Product(
        product_id="challenge_basic",
        name="Challenge Account Management",
        price_usd=9.99,
        entitlement=Entitlement.CHALLENGE_MANAGEMENT,
        duration_days=30,
        grace_days=3,
        grants_trade_permission=False,
        description=(
            "Challenge account policy, live position/order sync, drawdown "
            "headroom, breach detection and fail-closed protection for a "
            "connected MT5 account. Does not grant trade permission."),
    ),
}


def get_product(product_id: str) -> Optional[Product]:
    return PRODUCTS.get(str(product_id or "").strip().lower())


@dataclass
class ProductEntitlement:
    """One buyer's claim on one product."""

    user_id: str
    product_id: str
    entitlement: str
    state: str = ProductState.ACTIVE.value
    price_usd: float = 0.0
    currency: str = "USD"
    charge_id: str = ""
    started_at: float = 0.0
    expires_at: float = 0.0
    grace_until: float = 0.0
    entitlement_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    note: str = ""

    def is_effective(self, now: Optional[float] = None) -> bool:
        return self.state in (s.value for s in EFFECTIVE_STATES)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entitlement_id": self.entitlement_id,
            "user_id": self.user_id,
            "product_id": self.product_id,
            "entitlement": self.entitlement,
            "state": self.state,
            "price_usd": self.price_usd,
            "currency": self.currency,
            "charge_id": self.charge_id,
            "started_at": self.started_at,
            "expires_at": self.expires_at,
            "grace_until": self.grace_until,
            "note": self.note,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ProductEntitlement":
        return cls(
            user_id=str(row.get("user_id") or ""),
            product_id=str(row.get("product_id") or ""),
            entitlement=str(row.get("entitlement") or ""),
            state=str(row.get("state") or ProductState.ACTIVE.value),
            price_usd=float(row.get("price_usd") or 0.0),
            currency=str(row.get("currency") or "USD"),
            charge_id=str(row.get("charge_id") or ""),
            started_at=float(row.get("started_at") or 0.0),
            expires_at=float(row.get("expires_at") or 0.0),
            grace_until=float(row.get("grace_until") or 0.0),
            entitlement_id=str(row.get("entitlement_id") or uuid.uuid4()),
            note=str(row.get("note") or ""),
        )


def _persist(ent: ProductEntitlement) -> None:
    """Best-effort durable write; same posture as `identity._persist_user`.

    A product entitlement that is only in RAM is a paid service that evaporates
    on restart, so the write matters more than the log line. It still may not
    raise: losing durability is recoverable by re-charging, while taking the API
    down over a storage hiccup is not.
    """
    try:
        from persistence.db import make_live_session, persistence_enabled
        from persistence.repositories import ProductRepository

        if not persistence_enabled():
            return
        session = make_live_session()
        try:
            ProductRepository(session).save(ent)
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        log.debug(f"Product entitlement persistence skipped for {ent.user_id}")


def _load_all() -> List[ProductEntitlement]:
    try:
        from persistence.db import make_live_session, persistence_enabled
        from persistence.repositories import ProductRepository

        if not persistence_enabled():
            return []
        session = make_live_session()
        try:
            return [ProductEntitlement.from_row(r)
                    for r in ProductRepository(session).load_all()]
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        log.debug("Product entitlement load skipped")
        return []


class ProductService:
    """The one authority for "has this user bought this service".

    Deliberately separate from `IdentityService`. A plan answers "what may this
    operator do to the platform"; a product answers "has this operator paid for
    challenge management, and until when". Conflating them is how a $9.99 receipt
    becomes a permission change.
    """

    def __init__(self) -> None:
        self._entitlements: Dict[str, ProductEntitlement] = {}
        for ent in _load_all():
            self._entitlements[self._key(ent.user_id, ent.product_id)] = ent

    @staticmethod
    def _key(user_id: str, product_id: str) -> str:
        return f"{user_id}::{product_id}"

    # -- reads ----------------------------------------------------------

    def catalog(self) -> List[Dict[str, Any]]:
        return [p.as_dict() for p in PRODUCTS.values()]

    def get(self, user_id: str, product_id: str) -> Optional[ProductEntitlement]:
        self._roll(user_id, product_id)
        return self._entitlements.get(self._key(user_id, product_id))

    def entitlements_for(self, user_id: str) -> List[ProductEntitlement]:
        self._roll_all(user_id)
        return [e for e in self._entitlements.values() if e.user_id == user_id]

    def has(self, user_id: str, entitlement: Entitlement | str) -> bool:
        """True only for a live, paid-for entitlement.

        Absence of a user, an unknown entitlement or a rolled-out record all
        answer False. This is the read the risk governor asks on every
        candidate, so it must be cheap and must never raise.

        Accepts the enum or its plain value: the governor passes
        `Entitlement.CHALLENGE_MANAGEMENT`, while a console or a stored row can
        only hand over the string. A string used to hit `.value` on a `str`,
        raise AttributeError, and be swallowed into a False -- a correctly
        granted, paid-for service reported as absent.
        """
        if not user_id:
            return False
        wanted = str(getattr(entitlement, "value", entitlement) or "").strip().lower()
        if not wanted:
            return False
        try:
            for ent in self.entitlements_for(user_id):
                if ent.entitlement == wanted and ent.is_effective():
                    return True
        except Exception:  # noqa: BLE001
            # Answering False here is the safe direction, but a swallowed
            # exception would also hide a plain bug in this file -- which is
            # exactly what happened the first time: `has()` returned False for a
            # correctly granted entitlement and the failure surfaced three files
            # away as a confusing 403. The traceback is what makes that visible.
            log.exception(f"product entitlement read failed for {user_id}")
        return False

    def status(self, user_id: str) -> Dict[str, Any]:
        rows = self.entitlements_for(user_id)
        return {
            "user_id": user_id,
            "challenge_management": self.has(user_id,
                                             Entitlement.CHALLENGE_MANAGEMENT),
            "entitlements": [e.as_dict() for e in rows],
            "catalog": self.catalog(),
        }

    # -- writes ---------------------------------------------------------

    def grant(self, user_id: str, product_id: str, *, charge_id: str,
              actor: str = "billing", price_usd: Optional[float] = None,
              duration_days: Optional[int] = None,
              note: str = "") -> ProductEntitlement:
        """Activate a paid product. Only ever called from a confirmed charge.

        `price_usd` and `duration_days` are recorded, not trusted: the catalogue
        decides. They are parameters so a *promotion* (a longer free trial) can
        be recorded faithfully in the ledger, but an unknown value cannot
        shorten or cheapen what the server says the product costs.
        """
        product = get_product(product_id)
        if product is None:
            raise ValueError(f"unknown product: {product_id!r}")
        if product.grants_trade_permission:
            # §34.18 is enforced here rather than trusted to review. A product
            # that claimed trade permission is a policy violation, and granting
            # it would be the violation.
            raise ValueError(
                f"product {product.product_id!r} claims trade permission; "
                "a product entitlement may never grant trading (34.18)")
        if identity.get_user(user_id) is None:
            raise ValueError(f"unknown user: {user_id!r}")

        now = time.time()
        days = int(duration_days if duration_days is not None
                   else product.duration_days)
        ent = ProductEntitlement(
            user_id=user_id,
            product_id=product.product_id,
            entitlement=product.entitlement.value,
            state=ProductState.ACTIVE.value,
            price_usd=float(product.price_usd if price_usd is None else price_usd),
            currency="USD",
            charge_id=str(charge_id or ""),
            started_at=now,
            expires_at=now + days * 86400.0,
            grace_until=now + (days + product.grace_days) * 86400.0,
            note=note,
        )
        self._entitlements[self._key(user_id, product.product_id)] = ent
        _persist(ent)
        self._audit(actor, "product.grant", ent)
        log.info(f"Product granted: {user_id} {product.product_id} "
                 f"({ent.entitlement}) charge={ent.charge_id} "
                 f"expires={ent.expires_at:.0f}")
        return ent

    def revoke(self, user_id: str, product_id: str, *, reason: str,
               actor: str = "operator") -> Optional[ProductEntitlement]:
        """Take a paid service away. Audited and explicit (like `revoke_subscription`).

        The consequence is NOT that trading stops: it is that the challenge
        protection for a managed account stops being paid for, and §34.15's
        fail-closed governor answers that by halting new entries on the account
        rather than by silently leaving it unmanaged.
        """
        key = self._key(user_id, product_id)
        ent = self._entitlements.get(key)
        if ent is None:
            return None
        ent.state = ProductState.CANCELLED.value
        ent.note = reason or ent.note
        _persist(ent)
        self._audit(actor, "product.revoke", ent,
                    {"reason": reason or "unspecified"})
        log.warning(f"Product revoked: {user_id} {product_id} ({reason})")
        return ent

    def suspend(self, user_id: str, product_id: str, *, reason: str,
                actor: str = "operator") -> Optional[ProductEntitlement]:
        ent = self._entitlements.get(self._key(user_id, product_id))
        if ent is None:
            return None
        ent.state = ProductState.SUSPENDED.value
        ent.note = reason or ent.note
        _persist(ent)
        self._audit(actor, "product.suspend", ent,
                    {"reason": reason or "unspecified"})
        return ent

    def reinstate(self, user_id: str, product_id: str, *, reason: str,
                  actor: str = "operator") -> Optional[ProductEntitlement]:
        ent = self._entitlements.get(self._key(user_id, product_id))
        if ent is None:
            return None
        ent.state = ProductState.ACTIVE.value
        ent.note = reason or ent.note
        _persist(ent)
        self._audit(actor, "product.reinstate", ent,
                    {"reason": reason or "unspecified"})
        return ent

    def check_expirations(self, now: Optional[float] = None) -> List[str]:
        """Roll every due entitlement. Returns the user_ids that lost access."""
        now = time.time() if now is None else now
        lost: List[str] = []
        for ent in list(self._entitlements.values()):
            before = ent.state
            self._transition(ent, now)
            if before != ent.state:
                self._audit("system", "product.state", ent,
                            {"from": before, "to": ent.state})
                if ent.state not in (s.value for s in EFFECTIVE_STATES):
                    lost.append(ent.user_id)
        return sorted(set(lost))

    # -- internals ------------------------------------------------------

    def _roll(self, user_id: str, product_id: str) -> None:
        ent = self._entitlements.get(self._key(user_id, product_id))
        if ent is not None:
            self._transition(ent, time.time())

    def _roll_all(self, user_id: str) -> None:
        now = time.time()
        for ent in list(self._entitlements.values()):
            if ent.user_id == user_id:
                self._transition(ent, now)

    def _transition(self, ent: ProductEntitlement, now: float) -> None:
        """Time-only transitions. `revoke`/`suspend` are operator decisions and
        never happen here — expiry must not be able to resurrect or bury a
        deliberate revocation."""
        if ent.state == ProductState.CANCELLED.value:
            return
        if ent.state == ProductState.SUSPENDED.value:
            return
        if ent.expires_at <= 0:
            return
        if ent.state == ProductState.ACTIVE.value and now > ent.expires_at:
            new = (ProductState.GRACE_PERIOD if now <= ent.grace_until
                   else ProductState.EXPIRED)
        elif ent.state == ProductState.GRACE_PERIOD.value and now > ent.grace_until:
            new = ProductState.EXPIRED
        else:
            return
        if new.value != ent.state:
            ent.state = new.value
            _persist(ent)

    def _audit(self, actor: str, action: str, ent: ProductEntitlement,
               extra: Optional[Dict[str, Any]] = None) -> None:
        try:
            identity.record_audit(
                actor, action, "ProductEntitlement", ent.entitlement_id,
                {"user_id": ent.user_id, "product_id": ent.product_id,
                 "entitlement": ent.entitlement, "state": ent.state,
                 "price_usd": ent.price_usd, "charge_id": ent.charge_id,
                 **(extra or {})})
        except Exception:  # noqa: BLE001
            pass


products = ProductService()
