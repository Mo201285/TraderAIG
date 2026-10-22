"""Rejection taxonomy: who refused a trade, and why.

A refusal has to be attributable to its source, otherwise an execution
problem is read as a broken strategy (and a strategy problem is read as a
connectivity problem). Three sources exist, and only three:

* ``GOVERNANCE`` -- the Risk Governor, a user risk policy, or the local hard
  gate refused the idea. The analysis is intact; the risk said no.
* ``VENUE_SEND``  -- the order reached the broker and the broker refused it
  ("Invalid stops", "Market closed", "Not enough money"). The idea may be
  perfectly sound; the *order* was malformed or the market was shut.
* ``TRANSPORT``   -- the order never reached a venue at all (terminal not
  reachable, worker unreachable, no tick). Nothing was ever tried.

The class is deliberately coarse and the venue *code* is deliberately fine:
the coarse class decides what the system is allowed to do next (retry?
re-evaluate? ask the operator?), and the fine code says what has to change
before a retry is even meaningful.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class RejectionClass(str, Enum):
    """The source of a refusal."""

    NONE = "none"
    GOVERNANCE = "governance"
    VENUE_SEND = "venue_send"
    TRANSPORT = "transport"


class VenueReason(str, Enum):
    """Why the broker refused an order that reached it."""

    UNKNOWN = "unknown"
    INVALID_STOPS = "invalid_stops"
    INVALID_PRICE = "invalid_price"
    MARKET_CLOSED = "market_closed"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    TRADE_DISABLED = "trade_disabled"
    REQUOTE = "requote"
    INVALID_VOLUME = "invalid_volume"
    SYMBOL_NOT_SELECTED = "symbol_not_selected"
    NO_MONEY = "no_money"


# Ordered longest-first: "not enough money" must win over "money".
_VENUE_PATTERNS = (
    ("invalid stops", VenueReason.INVALID_STOPS),
    ("invalid stop", VenueReason.INVALID_STOPS),
    ("invalid price", VenueReason.INVALID_PRICE),
    ("invalid volume", VenueReason.INVALID_VOLUME),
    ("market closed", VenueReason.MARKET_CLOSED),
    ("no quotes", VenueReason.MARKET_CLOSED),
    ("quote is invalid", VenueReason.INVALID_PRICE),
    ("requote", VenueReason.REQUOTE),
    ("trade disabled", VenueReason.TRADE_DISABLED),
    ("not enough money", VenueReason.INSUFFICIENT_FUNDS),
    ("no money", VenueReason.NO_MONEY),
    ("symbol not selected", VenueReason.SYMBOL_NOT_SELECTED),
)

_TRANSPORT_PATTERNS = (
    "not reachable",
    "not connected",
    "terminal",
    "timeout",
    "timed out",
    "connection",
    "unreachable",
    "no tick",
    "unknown symbol",
    "worker",
)


def classify_venue_error(text: Optional[str]) -> VenueReason:
    """Map a broker refusal message onto a venue reason code."""
    raw = str(text or "").strip().lower()
    if not raw:
        return VenueReason.UNKNOWN
    for needle, reason in _VENUE_PATTERNS:
        if needle in raw:
            return reason
    return VenueReason.UNKNOWN


def looks_like_transport_error(text: Optional[str]) -> bool:
    """True when a failure message describes a transport problem."""
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    return any(needle in raw for needle in _TRANSPORT_PATTERNS)


class RejectionReason:
    """A structured refusal: the class, the human reason, and details."""

    __slots__ = ("reason", "rejection_class", "code", "details")

    def __init__(self,
                 reason: str = "",
                 rejection_class: RejectionClass = RejectionClass.NONE,
                 code: str = "",
                 details: Optional[Dict[str, Any]] = None) -> None:
        self.reason = reason or ""
        self.rejection_class = rejection_class
        self.code = code or ""
        self.details: Dict[str, Any] = dict(details or {})

    def as_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "class": self.rejection_class.value,
            "code": self.code,
            "details": dict(self.details),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"RejectionReason(class={self.rejection_class.value}, "
                f"code={self.code!r}, reason={self.reason!r})")

    @classmethod
    def governance(cls, reason: str,
                   code: str = "policy_veto",
                   details: Optional[Dict[str, Any]] = None) -> "RejectionReason":
        return cls(reason=reason, rejection_class=RejectionClass.GOVERNANCE,
                   code=code, details=details)

    @classmethod
    def venue_send(cls, reason: str,
                   code: Optional[str] = None,
                   details: Optional[Dict[str, Any]] = None) -> "RejectionReason":
        """A refusal by the broker; the code is derived from the message."""
        resolved = code or classify_venue_error(reason).value
        return cls(reason=reason, rejection_class=RejectionClass.VENUE_SEND,
                   code=resolved, details=details)

    @classmethod
    def transport(cls, reason: str,
                  code: str = "unreachable",
                  details: Optional[Dict[str, Any]] = None) -> "RejectionReason":
        return cls(reason=reason, rejection_class=RejectionClass.TRANSPORT,
                   code=code, details=details)

    @classmethod
    def from_error(cls, reason: str,
                   details: Optional[Dict[str, Any]] = None) -> "RejectionReason":
        """Classify a free-form error message without a caller hint.

        Transport wording wins over venue wording because "not connected"
        means nothing was tried, while "market closed" means the broker
        answered and refused.
        """
        text = str(reason or "")
        if looks_like_transport_error(text):
            return cls.transport(text, details=details)
        return cls.venue_send(text, details=details)
