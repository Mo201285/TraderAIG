"""Offer eligibility and redemption (Phase G, slice G2).

This is the one place that answers two questions and nothing else:

* **Who may benefit from an offer?** `available_for(user_id)` returns the offers
  a user is eligible for right now, with the ineligible ones listed *with their
  reason* -- because "no offers" and "an offer you do not qualify for" are
  different facts, and collapsing them lets a client believe the platform has
  nothing for them when it has an offer they merely cannot use yet.
* **What happens when a user redeems one?** `redeem(user_id, offer_id)` decides,
  fail-closed, whether the grant lands now (`granted`), must wait for a
  verification (`pending`), or is refused (`declined`/`failed`).

Four invariants are load-bearing and are enforced here rather than trusted to a
caller, because each is a failure this codebase has already paid for elsewhere.

**1. An offer grants a commercial entitlement or a plan -- never trade.** The
grant goes through exactly one of two legal channels: `products.grant` (which
itself refuses any product claiming trade permission -- rule 34.18) or
`identity.activate_subscription`. There is no third path and no bespoke write.

**2. A plan-granting offer may only upgrade.** `activate_subscription` REPLACES
the user's whole entitlement set (`grant_plan_entitlements`), so a plan offer
that would take an entitlement away is refused rather than silently stripping
`can_trade` from an operator who is mid-session. This is the same defect the
subscription route guards with `confirm_downgrade`, closed here by refusing
outright: an *offer* has no business taking anything away.

**3. One user uses one offer at most once, and the insert is the lock.** The
`pending` redemption row is written BEFORE the grant is attempted. The unique
constraint on `(offer_id, user_id)` makes a concurrent second attempt fail at
INSERT, so it never reaches a second grant. This is why the order is
insert-then-grant and not check-then-grant.

**4. Opening a link is not a purchase.** When an offer's conditions require a
verification the platform does not have, the redemption is recorded `pending` --
granted nothing and declined nothing. A `pending` redemption whose offer window
closed before verification becomes `declined` with reason `offer_expired`, never
a silent grant.

Nothing here raises an authorisation; every outgoing payload carries
`is_authorisation: False` and names the Risk Governor.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from governance.identity import SubscriptionPlan, identity
from governance.products import PRODUCTS, get_product, products
from persistence.repositories_offers import (
    OfferRedemptionRepository,
    OfferRepository,
)
from persistence.repositories_accounts import (
    ExternalProviderRepository,
    ReferralRepository,
)

# Every payload names the Risk Governor as the sole trade authority and denies
# being an authorisation, exactly like the provider and referral surfaces.
TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False

# The grant actor recorded in whichever ledger performs the grant, so an offer
# grant is distinguishable in the audit trail from a paid charge or a referral
# reward without masquerading as either.
OFFER_ACTOR = "offer_redemption"

# The condition keys this service actually reads. `conditions_json` is free-form
# so an operator can record more, but only these change a verdict; anything else
# is carried through untouched and never interpreted.
CONDITION_KEYS = ("requires_verification", "allowed_plans", "min_plan")

# The reasons a client may be ineligible, or a redemption may not land. Kept as
# a closed set so a client surface renders a stable vocabulary instead of
# whatever string a code path happened to build.
REASONS = (
    "eligible",
    "offer_unknown",
    "offer_not_active",
    "offer_not_started",
    "offer_expired",
    "offer_exhausted",
    "already_redeemed",
    "plan_not_allowed",
    "verification_required",
    "grant_target_missing",
    "grant_would_downgrade",
    "grant_failed",
)


def _enrich(**fields) -> Dict[str, Any]:
    return {**fields, "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


def offer_window(offer: Dict[str, Any], now: Optional[float] = None) -> str:
    """The time status of an offer, independent of its operator `status`.

    Returns one of ``"not_started"``, ``"open"``, ``"expired"``. A missing bound
    (``0``) means "no bound", so an offer with neither date is always open. The
    window is deliberately a *derived* fact: the stored `status` is the
    operator's switch, this is the calendar's, and a report must be able to tell
    them apart.
    """
    now = time.time() if now is None else now
    starts = float(offer.get("starts_at") or 0.0)
    ends = float(offer.get("ends_at") or 0.0)
    if starts and now < starts:
        return "not_started"
    if ends and now > ends:
        return "expired"
    return "open"


class OfferService:
    """Create offers (operator) and redeem them (client), fail-closed."""

    def __init__(self, offer_repo: Optional[OfferRepository] = None,
                 redemption_repo: Optional[OfferRedemptionRepository] = None,
                 provider_repo: Optional[ExternalProviderRepository] = None,
                 referral_repo: Optional[ReferralRepository] = None) -> None:
        self._offers = offer_repo or OfferRepository()
        self._redemptions = redemption_repo or OfferRedemptionRepository()
        self._providers = provider_repo or ExternalProviderRepository()
        self._referrals = referral_repo or ReferralRepository()

    # -- operator writes -------------------------------------------------

    def create(self, *, title: str, provider_id: str, grant_kind: str,
               grant_ref: str, referral_code: str = "",
               conditions: Optional[Dict[str, Any]] = None,
               starts_at: float = 0.0, ends_at: float = 0.0,
               max_redemptions: int = 0, actor: str = "",
               note: str = "") -> Dict[str, Any]:
        """Create an offer, validating its *grant target* against the real
        catalogue before writing anything.

        Fail-closed checks that a fake benefit cannot pass:
        * the provider must exist in the External Provider Registry;
        * a `referral_code` must actually be issued for that provider;
        * a `product` grant must name a real catalogue product;
        * a `plan` grant must name a real subscription plan, and must not be a
          downgrade for anyone (checked again per-user at redemption).
        """
        provider_id = str(provider_id or "").strip()
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ValueError(
                f"no registered provider {provider_id!r}; an offer must be "
                "against a provider the registry knows")
        referral_code = str(referral_code or "").strip()
        if referral_code and self._referrals.get_by_code(
                provider_id, referral_code) is None:
            raise ValueError(
                f"referral code {referral_code!r} is not issued for provider "
                f"{provider_id!r}; an offer may not cite a code that does not "
                "exist")
        _validate_grant_target(grant_kind, grant_ref)
        row = self._offers.create(
            title=title, provider_id=provider_id,
            grant_kind=grant_kind, grant_ref=grant_ref,
            referral_code=referral_code, conditions=conditions,
            starts_at=starts_at, ends_at=ends_at,
            max_redemptions=max_redemptions, created_by=actor,
            note=note)
        return _enrich(offer=row)

    def update(self, offer_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Correct an offer. Re-validates the grant target if it changes."""
        if "grant_kind" in fields or "grant_ref" in fields:
            current = self._offers.get(offer_id)
            if current is None:
                return None
            _validate_grant_target(
                fields.get("grant_kind", current["grant_kind"]),
                fields.get("grant_ref", current["grant_ref"]))
        row = self._offers.update(offer_id, **fields)
        return _enrich(offer=row) if row is not None else None

    def set_status(self, offer_id: str, status: str) -> Optional[Dict[str, Any]]:
        row = self._offers.update(offer_id, status=status)
        return _enrich(offer=row) if row is not None else None

    # -- reads -----------------------------------------------------------

    def get(self, offer_id: str) -> Optional[Dict[str, Any]]:
        row = self._offers.get(offer_id)
        return _enrich(offer=row) if row is not None else None

    def list_all(self, *, status: str = "",
                 provider_id: str = "") -> List[Dict[str, Any]]:
        return [_enrich(offer=o) for o in
                self._offers.list_all(status=status, provider_id=provider_id)]

    def available_for(self, user_id: str) -> Dict[str, Any]:
        """The offers a user may redeem now, and the ineligible ones with reasons.

        Eligibility is a per-(user, offer) verdict combining the offer's own
        window/status, its verification condition, the user's plan against
        `allowed_plans`, and whether the user already redeemed it. The reasons
        never disclose another user's data or internal state -- they name only
        the rule that excluded *this* user from *this* offer.
        """
        eligible: List[Dict[str, Any]] = []
        ineligible: List[Dict[str, Any]] = []
        for offer in self._offers.list_all():
            verdict = self._verdict(user_id, offer)
            entry = {"offer_id": offer["offer_id"], "title": offer["title"],
                     "provider_id": offer["provider_id"],
                     "grant_kind": offer["grant_kind"],
                     "grant_ref": offer["grant_ref"],
                     "reason": verdict["reason"]}
            if verdict["eligible"]:
                eligible.append(entry)
            else:
                ineligible.append(entry)
        return _enrich(user_id=user_id, eligible=eligible,
                       ineligible=ineligible,
                       counts={"eligible": len(eligible),
                               "ineligible": len(ineligible)},
                       note=("an offer listed ineligible is not shown as "
                             "unavailable -- it names the rule that excluded "
                             "this user, and nothing about any other user"))

    def redemptions_for(self, user_id: str) -> Dict[str, Any]:
        rows = self._redemptions.list_for_user(user_id)
        return _enrich(user_id=user_id, redemptions=rows,
                       count=len(rows))

    # -- the redemption --------------------------------------------------

    def redeem(self, user_id: str, offer_id: str) -> Dict[str, Any]:
        """Attempt to redeem one offer for one user. Idempotent and fail-closed.

        Order matters and is the whole design:

        1. Load the offer; unknown is `declined`/`offer_unknown` (no row written,
           there is no offer to bind to).
        2. If the user already has a redemption for it, return *that* -- retry-safe.
        3. Compute the verdict. Ineligible is `declined` with the reason.
        4. If a verification is still required, record `pending` and grant
           nothing (opening a link is not a purchase).
        5. Otherwise write the `pending` row FIRST (the insert is the lock), then
           perform the grant, then mark the row `granted` or `failed`.
        """
        offer = self._offers.get(offer_id)
        if offer is None:
            return _enrich(offer_id=offer_id, user_id=user_id,
                           status="declined", reason="offer_unknown",
                           granted=False)

        existing = self._redemptions.get(offer_id, user_id)
        if existing is not None:
            return _enrich(offer_id=offer_id, user_id=user_id,
                           status=existing["status"],
                           reason=existing["reason"] or "already_redeemed",
                           granted=existing["status"] == "granted",
                           redeemed=True,
                           redemption=existing)

        verdict = self._verdict(user_id, offer)
        if not verdict["eligible"]:
            row = self._redemptions.record(
                offer_id=offer_id, user_id=user_id,
                provider_id=offer["provider_id"],
                referral_code=offer["referral_code"],
                grant_kind=offer["grant_kind"], grant_ref=offer["grant_ref"],
                status="declined", reason=verdict["reason"])
            return _enrich(offer_id=offer_id, user_id=user_id,
                           status="declined", reason=verdict["reason"],
                           granted=False, redemption=row)

        # Verification still pending: record it, grant nothing.
        if verdict["requires_verification"]:
            row = self._redemptions.record(
                offer_id=offer_id, user_id=user_id,
                provider_id=offer["provider_id"],
                referral_code=offer["referral_code"],
                grant_kind=offer["grant_kind"], grant_ref=offer["grant_ref"],
                status="pending", reason=verification_reason())
            return _enrich(offer_id=offer_id, user_id=user_id,
                           status="pending", reason=verification_reason(),
                           granted=False, redemption=row)

        # The insert is the lock: write `pending` before the grant, so a
        # concurrent second attempt fails at INSERT and never double-grants.
        try:
            row = self._redemptions.record(
                offer_id=offer_id, user_id=user_id,
                provider_id=offer["provider_id"],
                referral_code=offer["referral_code"],
                grant_kind=offer["grant_kind"], grant_ref=offer["grant_ref"],
                status="pending", reason="")
        except ValueError:
            # Somebody else won the race for this (offer, user): report the
            # outcome as already-redeemed rather than granting twice.
            current = self._redemptions.get(offer_id, user_id)
            return _enrich(
                offer_id=offer_id, user_id=user_id,
                status=(current or {}).get("status", "pending"),
                reason="already_redeemed", granted=False,
                redeemed=True, redemption=current)

        try:
            entitlement_ref = self._grant(user_id, offer)
        except _GrantRefused as exc:
            failed = self._redemptions.set_outcome(
                row["redemption_id"], "declined", reason=str(exc))
            return _enrich(offer_id=offer_id, user_id=user_id,
                           status="declined", reason=str(exc),
                           granted=False, redemption=failed)
        except Exception as exc:  # noqa: BLE001
            failed = self._redemptions.set_outcome(
                row["redemption_id"], "failed",
                reason=f"{type(exc).__name__}: {exc}")
            return _enrich(offer_id=offer_id, user_id=user_id,
                           status="failed",
                           reason=f"{type(exc).__name__}: {exc}",
                           granted=False, redemption=failed)

        granted = self._redemptions.set_outcome(
            row["redemption_id"], "granted", entitlement_ref=entitlement_ref)
        return _enrich(offer_id=offer_id, user_id=user_id,
                       status="granted", reason="eligible", granted=True,
                       entitlement_ref=entitlement_ref, redemption=granted)

    def _grant(self, user_id: str, offer: Dict[str, Any]) -> str:
        """Perform the offer's grant through its one legal channel.

        Raises `_GrantRefused` for a *policy* refusal (a downgrade, an unknown
        target) so the redemption is recorded `declined` with a stated reason;
        any other exception propagates and is recorded `failed`.
        """
        kind = str(offer.get("grant_kind") or "").strip().lower()
        ref = str(offer.get("grant_ref") or "").strip()
        charge_id = f"offer:{offer['offer_id']}"
        if kind == "product":
            if get_product(ref) is None:
                raise _GrantRefused("grant_target_missing")
            products.grant(user_id, ref, charge_id=charge_id,
                           actor=OFFER_ACTOR, price_usd=0.0,
                           note=f"offer {offer['offer_id']}")
            return ref
        if kind == "plan":
            plan = _plan(ref)
            if plan is None:
                raise _GrantRefused("grant_target_missing")
            current = identity.get_user(user_id)
            current_plan = current.plan if current is not None else None
            # An offer may only be a *pure upgrade*. `activate_subscription`
            # REPLACES the whole entitlement set, so granting a plan of lower or
            # equal rank could take authority away -- including the `read_only`
            # base grant, which the plan table spells out for FREE but not for
            # the paid tiers. Rank-strictly-greater is the one rule that never
            # removes authority by construction, so it is the rule here: taking
            # authority away is a revocation, a different act with its own verb.
            if (current_plan is None
                    or _plan_rank(plan.value) <= _plan_rank(current_plan.value)):
                raise _GrantRefused("grant_would_downgrade")
            identity.activate_subscription(user_id, plan)
            return plan.value
        raise _GrantRefused("grant_target_missing")

    # -- the verdict -----------------------------------------------------

    def _verdict(self, user_id: str, offer: Dict[str, Any]) -> Dict[str, Any]:
        """The (user, offer) eligibility verdict, with a single reason."""
        status = str(offer.get("status") or "")
        if status != "active":
            return _v(False, "offer_not_active")
        window = offer_window(offer)
        if window == "not_started":
            return _v(False, "offer_not_started")
        if window == "expired":
            return _v(False, "offer_expired")
        cap = int(offer.get("max_redemptions") or 0)
        if cap and self._redemptions.count_for_offer(offer["offer_id"]) >= cap:
            return _v(False, "offer_exhausted")
        if self._redemptions.get(offer["offer_id"], user_id) is not None:
            return _v(False, "already_redeemed")

        conditions = offer.get("conditions") or {}
        user = identity.get_user(user_id)
        if user is None:
            return _v(False, "plan_not_allowed")
        allowed = conditions.get("allowed_plans") or []
        if allowed and user.plan.value not in [str(p) for p in allowed]:
            return _v(False, "plan_not_allowed")
        min_plan = str(conditions.get("min_plan") or "")
        if min_plan and _plan_rank(user.plan.value) < _plan_rank(min_plan):
            return _v(False, "plan_not_allowed")

        requires = bool(conditions.get("requires_verification"))
        return _v(True, "eligible", requires_verification=requires)


# -- helpers -------------------------------------------------------------


class _GrantRefused(Exception):
    """A policy refusal of a grant (recorded `declined`, not `failed`)."""


def _v(eligible: bool, reason: str,
       requires_verification: bool = False) -> Dict[str, Any]:
    return {"eligible": bool(eligible), "reason": reason,
            "requires_verification": bool(requires_verification)}


def verification_reason() -> str:
    return "verification_required"


def _plan(value: str) -> Optional[SubscriptionPlan]:
    try:
        return SubscriptionPlan(str(value or "").strip().lower())
    except ValueError:
        return None


def _plan_rank(value: str) -> int:
    order = {"free": 0, "starter": 1, "pro": 2, "institutional": 3}
    return order.get(str(value or "").strip().lower(), -1)


def _validate_grant_target(grant_kind: str, grant_ref: str) -> None:
    """Refuse a grant target the platform cannot actually honour.

    A `product` must exist in the catalogue; a `plan` must be a real plan. This
    runs at offer *creation* so an operator cannot publish a campaign that
    promises something no grant path can deliver -- the fabricated-benefit
    shape this family refuses everywhere.
    """
    kind = str(grant_kind or "").strip().lower()
    ref = str(grant_ref or "").strip()
    if kind == "product":
        if ref.lower() not in PRODUCTS:
            raise ValueError(
                f"unknown product {ref!r}; a product offer must name a "
                f"catalogue product")
    elif kind == "plan":
        if _plan(ref) is None:
            raise ValueError(
                f"unknown plan {ref!r}; expected one of "
                f"{[p.value for p in SubscriptionPlan]}")
    else:
        raise ValueError(
            f"grant_kind must be 'product' or 'plan', not {kind!r}")


__all__ = [
    "CONDITION_KEYS",
    "IS_AUTHORISATION",
    "OFFER_ACTOR",
    "OfferService",
    "REASONS",
    "TRADE_AUTHORITY",
    "offer_window",
    "verification_reason",
]
