"""The AI Action Gateway (S3, MASTER_ARCHITECTURE section 8).

Every agent acts only through this gateway. Four actions are forbidden to any
seat, without exception, and route instead to the Risk Governor and Governance
OS:

* Promote Live        -> risk/governor.py + governance (promotion is governed)
* Change Risk         -> risk/governor.py
* Execute a Trade     -> risk/governor.py
* Modify Production   -> governance

The gateway is the live form of the UX-13 banner: the banner says no agent may
do these; this module is what refuses them when a seat actually asks. Silence --
"unknown action, assume allowed" -- would be the fabricated-control failure this
project keeps deleting, so an action the gateway does not explicitly allow is
refused, not waved through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

# action -> {label, routed_to, authority}
FORBIDDEN_ACTIONS: Dict[str, Dict[str, str]] = {
    "promote_live": {
        "label": "Promote Live",
        "routed_to": "governance + risk/governor.py",
        "authority": "the governed ReviewLoop promotes; a seat never does",
    },
    "change_risk": {
        "label": "Change Risk",
        "routed_to": "risk/governor.py",
        "authority": "the Risk Governor is the sole risk authority",
    },
    "execute_trade": {
        "label": "Execute a Trade",
        "routed_to": "risk/governor.py",
        "authority": "only the Risk Governor may authorise execution",
    },
    "modify_production": {
        "label": "Modify Production",
        "routed_to": "governance",
        "authority": "production changes are governed change requests",
    },
}

# The only act a seat may take through the gateway.
ALLOWED_ACTIONS = frozenset({"propose"})

# Alias map so a caller naming a capability rather than a verb still lands on
# the same refusal (e.g. "promote" for "promote_live"). Deliberately explicit:
# anything not here and not in ALLOWED_ACTIONS is refused as unknown.
_ACTION_ALIASES = {
    "promote": "promote_live",
    "go_live": "promote_live",
    "trade": "execute_trade",
    "place_trade": "execute_trade",
    "risk": "change_risk",
    "set_risk": "change_risk",
    "deploy": "modify_production",
    "production": "modify_production",
}


def _normalise(action: str) -> str:
    key = str(action or "").strip().lower()
    return _ACTION_ALIASES.get(key, key)


@dataclass
class AIActionDecision:
    seat_id: str
    action: str
    allowed: bool
    reason: str
    detail: str
    routed_to: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "seat_id": self.seat_id,
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "detail": self.detail,
            "routed_to": self.routed_to,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


class AIActionGateway:
    """Evaluates an action a seat wants to take; refuses the four forbidden ones."""

    def request(self, seat_id: str, action: str, *,
                target: str = "") -> AIActionDecision:
        seat = str(seat_id or "").strip()
        normalised = _normalise(action)
        if normalised in FORBIDDEN_ACTIONS:
            rule = FORBIDDEN_ACTIONS[normalised]
            return AIActionDecision(
                seat_id=seat, action=normalised, allowed=False,
                reason="forbidden_gateway_action",
                detail=(f"'{rule['label']}' is forbidden to every agent "
                        f"({rule['authority']}); it routes to {rule['routed_to']}"
                        + (f" for {target}" if target else "")),
                routed_to=rule["routed_to"])
        if normalised in ALLOWED_ACTIONS:
            return AIActionDecision(
                seat_id=seat, action=normalised, allowed=True,
                reason="allowed_gateway_action",
                detail="a seat may propose; the proposal is advisory and the "
                       "governed authority decides")
        return AIActionDecision(
            seat_id=seat, action=str(action or ""), allowed=False,
            reason="unknown_gateway_action",
            detail=("an action the gateway does not explicitly allow is "
                    "refused, not waved through"))


AI_ACTION_GATEWAY = AIActionGateway()

__all__ = [
    "AI_ACTION_GATEWAY",
    "ALLOWED_ACTIONS",
    "AIActionDecision",
    "AIActionGateway",
    "FORBIDDEN_ACTIONS",
]
