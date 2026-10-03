"""The commercial gate for Challenge Management, read from the live path (§34.15).

There are two places that need the same answer — the API routes that mutate a
policy, and the risk governor that has to decide on a candidate with no request
in sight. There is exactly one answer, and it is computed here.

The resolver mirrors `operations.api._acting_actor()` (authenticated session
first, then the server principal) instead of importing it. `risk` importing
`operations` would invert the layering, and duplicating a one-line rule in two
places is how the two drift into disagreeing about who is acting. Both call this.

Deliberate difference from `api._guard()`: an unconfigured identity PASSES an
API guard, because with no principal there is no authority to check and nothing
exists yet to protect. Here it does not pass. The question is not "may this
operator change the rails" but "is anyone paying for the protection on an
account that has declared itself a challenge account", and an unconfigured system
has answered that question with silence. §34.15 and §34.20 both resolve silence
in the same direction: HALT.

`challenge_gate()` reports the two cases separately via `bootstrap`, so the API
can accept the first while the governor refuses the second. Both decisions are
deliberate; neither is the other one's bug.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.logging import get_logger
from governance.identity import Entitlement

log = get_logger("challenge.entitlement")


#: The one entitlement this service is sold behind (§34.2).
CHALLENGE_ENTITLEMENT = Entitlement.CHALLENGE_MANAGEMENT


def acting_principal() -> Optional[str]:
    """The single acting authority: authenticated caller, else server principal."""
    try:
        from governance.auth import current_caller
        from governance.identity import identity

        return current_caller() or identity.principal_user_id()
    except Exception:  # noqa: BLE001
        log.warning("acting principal resolution failed")
        return None


def owns_challenge_management(user_id: Optional[str] = None) -> bool:
    """True when `user_id` (default: the acting principal) has paid for it."""
    actor = user_id if user_id is not None else acting_principal()
    if not actor:
        return False
    try:
        from governance.products import products

        return products.has(actor, CHALLENGE_ENTITLEMENT)
    except Exception:  # noqa: BLE001
        log.exception(f"challenge entitlement read failed for {actor}")
        return False


def challenge_gate(user_id: Optional[str] = None) -> Dict[str, Any]:
    """The decision, plus enough state for the caller to explain itself.

    `bootstrap` is the field the two callers branch on, and it exists because
    they ask different questions:

      * the API asks "may this caller CONFIGURE the service?" With no principal
        there is nobody to charge and nothing yet to protect, so it passes --
        the same reasoning `_guard()` already records, and without it a fresh
        install could never seed a baseline or register a policy at all.
      * the Risk Governor asks "is anyone PAYING for protection on this
        account?" An unconfigured system has answered that with silence, and
        §34.15/§34.20 both resolve silence as HALT.

    Reporting both states explicitly is what stops the divergence from looking
    like a bug to whoever reads the next one of these two call sites.
    """
    actor = user_id if user_id is not None else acting_principal()
    if not actor:
        return {"active": False, "actor": None, "bootstrap": True,
                "reason": "no_principal",
                "detail": "no acting principal is configured, so payment for "
                          "challenge management cannot be established"}
    ent = owns_challenge_management(actor)
    if ent:
        return {"active": True, "actor": actor, "bootstrap": False,
                "reason": "", "detail": ""}
    return {
        "active": False, "actor": actor, "bootstrap": False,
        "reason": "not_purchased",
        "detail": f"no active {CHALLENGE_ENTITLEMENT.value} entitlement for "
                  f"{actor}; challenge protection is not paid for",
    }


def status(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Full commercial status for `/challenge/status` and the console."""
    from governance.products import get_product, products

    actor = user_id if user_id is not None else acting_principal()
    product = get_product("challenge_basic")
    record = products.get(actor, "challenge_basic") if actor else None
    return {
        "entitlement": CHALLENGE_ENTITLEMENT.value,
        "actor": actor,
        "gate": challenge_gate(actor),
        "price_usd": product.price_usd if product else None,
        "product_id": product.product_id if product else None,
        # None, not a default "active" record: never having bought the service
        # and holding a lapsed one are different situations and an operator
        # reading this panel should not have to guess which they are in.
        "record": record.as_dict() if record is not None else None,
        "grants_trade_permission": bool(
            product.grants_trade_permission) if product else None,
    }
