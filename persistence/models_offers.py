"""ORM models for the Commercial Offer Registry (Phase G, slice G1).

This module is separate from `models.py` and `models_accounts.py` for the same
reason those two are separate from each other: a reader who has finished
`models_accounts.py` believes they have read the whole tenancy model, and
appending a commercial-offer lifecycle to it would bury the new concept inside a
file they think they already know.

**What already exists, and what this adds.** The platform already has a full
partner/referral subsystem and this module does not duplicate any of it:

* the External Provider Registry (`external_providers`) says *who* a partner is
  and what its referral programme, tracking method and verification method are;
* the referral attribution lifecycle (`referrals`, `referral_events`) records
  which account came from which issued code, through
  `accounts/referral_attribution.py`;
* `providers/network.py` records the operator's onboarding attestation.

None of those can express the one thing an operator actually runs: **a
time-boxed offer** -- "ForTraders partners get the $9.99 Challenge Management
package free, through this referral code, between these dates, subject to these
conditions". That is a *commercial campaign*, and it lives here as data.

**Two decisions are load-bearing and are stated here rather than only in a design
doc, because the next person to touch this file will otherwise reasonably undo
them.**

**First: an offer names a grant target, never a trade permission.** An offer may
grant a *product* entitlement (`governance/products.py`) or activate a
*subscription plan* (`governance/identity.py`), chosen by `grant_kind`. It
deliberately carries **no `grants_trade_permission` column, no `may_trade`, no
`can_trade`** -- whether an account may trade is the Risk Governor's verdict
alone (rows 741/742/744/745). A granted subscription plan is a commercial fact;
a granted product is a paid service. Neither is a licence to trade, and the
grant path enforces that: `products.grant` refuses any product that claims trade
permission, and a plan activation goes through the one legal `activate_subscription`
entry point, never a bespoke write.

**Second: an offer is created by an operator, never by a client.** This codebase
has no role system -- authorisation is entitlement-based and the acting
principal is resolved server-side (`operations/api.py::owner_scope`). So the
"admin" of this platform is the acting principal (or a service token) and the
gating of offer writes is done in the API layer, *not* by hiding a page. A client
surface reads `available_for()` and calls `redeem()`; it never creates, edits or
deletes an offer.

**No foreign keys and absence is NULL**, matching the account-family rule: a
de-listed provider must not break an offer read, and a redemptions column that
has not been filled yet is `None` rather than `''` so it is SQL-distinguishable
from a real value.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


class CommercialOfferRecord(Base):
    """One operator-authored commercial offer, time-boxed and condition-gated.

    An offer is the campaign object the platform was missing: it binds a
    `provider_id` and a `referral_code` (both already part of the partner
    subsystem) to a **grant target** and a window.

    `grant_kind` is ``"product"`` or ``"plan"`` and `grant_ref` is the product id
    (`challenge_basic`) or the plan value (`pro`/`institutional`). The two kinds
    are deliberately a single column pair rather than two nullable columns so an
    offer cannot claim to grant both at once -- one offer, one grant, one
    ledger entry.

    `conditions_json` is the operator's stated eligibility contract -- e.g.
    ``{"requires_verification": true, "allowed_plans": ["free"]}`` -- kept as
    JSON so the *policy* can grow without a schema migration while the *shape*
    the code reads is fixed by `offers/eligibility.py`. What is stored is the
    operator's claim; what is enforced is the code's, and the code is the one
    that decides an eligibility verdict.

    `starts_at` / `ends_at` are unix seconds. An offer outside its window is
    `inactive` by *date*, independently of its `status` -- a campaign that
    expired at midnight is not the same fact as one an operator switched off, and
    the service reports them under different reasons.

    `max_redemptions` is ``0`` for "no cap"; a positive cap is enforced against
    the redemption count, fail-closed (a raced redemption that would exceed the
    cap is refused, not written).

    `status` is the operator lifecycle: `active` / `paused` / `retired`. It is
    never a permission and never a trade authority.
    """

    __tablename__ = "commercial_offers"

    offer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    referral_code: Mapped[str] = mapped_column(String(128), default="", index=True)
    grant_kind: Mapped[str] = mapped_column(String(16), default="product", index=True)
    grant_ref: Mapped[str] = mapped_column(String(64), default="")
    conditions_json: Mapped[str] = mapped_column(Text, default="{}")
    starts_at: Mapped[float] = mapped_column(Float, default=0.0)
    ends_at: Mapped[float] = mapped_column(Float, default=0.0)
    max_redemptions: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)


class OfferRedemptionRecord(Base):
    """One user's attempt to use one offer, and what came of it.

    A redemption is a *durable fact* with a lifecycle, not a transient action:
    `pending` means the offer's conditions require verification the platform does
    not yet have (the operator's own rule: *opening a referral link does not
    prove a purchase*), `granted` means the grant landed, `declined`/`failed`
    are recorded with a stated reason.

    `(offer_id, user_id)` is unique: one user uses one offer at most once. That
    is the idempotency that makes `redeem()` safe to retry -- a second call
    returns the first outcome rather than double-granting.

    `grant_kind` / `grant_ref` are **snapshots** of the offer at redemption time,
    exactly like a referral snapshots its tracking method: the offer row is the
    live contract and may be edited, but what a given redemption *was promised*
    is fixed at the moment it was made.

    `entitlement_ref` records the concrete ledger key the grant produced (a
    product entitlement id, or the plan value for a subscription), so a
    redemption can be tied back to the thing it created without a join.

    **No trade-permission column, ever**, for the same reason as the offer: a
    redemption grants a commercial entitlement or a plan, never the right to
    trade (rows 741/742/744/745).
    """

    __tablename__ = "offer_redemptions"

    redemption_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offer_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    referral_code: Mapped[str] = mapped_column(String(128), default="")
    grant_kind: Mapped[str] = mapped_column(String(16), default="")
    grant_ref: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    entitlement_ref: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    __table_args__ = (
        UniqueConstraint(
            "offer_id", "user_id",
            name="uq_offer_redemption_offer_user",
        ),
    )
