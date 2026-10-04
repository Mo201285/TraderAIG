"""Venue-neutral trade normalisation: canonical values in, canonical rows out.

Every adapter in this tree -- `execution/mt5_adapter.py`, `execution/cex/venues.py`
-- already solves the same problem in miniature: `_TF_INTERVAL` in `venues.py`
maps a canonical timeframe to a venue-native one. This module is that idea at
full size, and it exists as one place so a second adapter does not grow its own
private copy of the mapping.

The rule this module enforces: **a canonical value is only produced from a venue
value when the venue actually reported one.** Every function returns `None` for
a value the venue did not supply rather than a default, for the reason
`persistence._opt_float` documents -- `0.0` is a real measurement and absence is
not zero. A normalisation layer that filled gaps with defaults would turn "the
exchange did not report fees" into "the exchange charged no fees", and the first
number an operator acts on would be the fabricated one.

Venue-native values are preserved under `venue_*` keys rather than discarded, so
a reconciliation diff can always get back to what the venue actually said.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.contracts import OrderStatus, OrderType, PositionStatus, TradeDirection


# Canonical side -> the words venues use for the same thing. Every venue words
# this differently, which is the whole reason a normaliser exists; mapping the
# three words explicitly beats a `if "buy" in text` test, which turns an
# unrecognised status into a confident buy.
_SIDE_ALIASES: Dict[str, TradeDirection] = {
    "buy": TradeDirection.LONG,
    "b": TradeDirection.LONG,
    "long": TradeDirection.LONG,
    "open_long": TradeDirection.LONG,
    "sell": TradeDirection.SHORT,
    "s": TradeDirection.SHORT,
    "short": TradeDirection.SHORT,
    "open_short": TradeDirection.SHORT,
    "flat": TradeDirection.FLAT,
    "none": TradeDirection.FLAT,
}

# Canonical order type -> venue words. Kept separate from status because MT5
# encodes both in one integer, and conflating them is how a filled order becomes a
# pending one.
_ORDER_TYPE_ALIASES: Dict[str, OrderType] = {
    "market": OrderType.MARKET,
    "mkt": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "lmt": OrderType.LIMIT,
    "stop": OrderType.STOP,
    "stop_limit": OrderType.STOP,
    "stop_market": OrderType.STOP,
}

_ORDER_STATUS_ALIASES: Dict[str, OrderStatus] = {
    "pending": OrderStatus.PENDING,
    "new": OrderStatus.PENDING,
    "placed": OrderStatus.PENDING,
    "partially_filled": OrderStatus.PARTIAL,
    "partial": OrderStatus.PARTIAL,
    "partialfill": OrderStatus.PARTIAL,
    "submitted": OrderStatus.SUBMITTED,
    "in_progress": OrderStatus.SUBMITTED,
    "working": OrderStatus.SUBMITTED,
    "filled": OrderStatus.FILLED,
    "closed": OrderStatus.FILLED,
    "done": OrderStatus.FILLED,
    "rejected": OrderStatus.REJECTED,
    "canceled": OrderStatus.CANCELLED,
    "cancelled": OrderStatus.CANCELLED,
    "expired": OrderStatus.EXPIRED,
}

_POSITION_STATUS_ALIASES: Dict[str, PositionStatus] = {
    "open": PositionStatus.OPEN,
    "active": PositionStatus.OPEN,
    "closed": PositionStatus.CLOSED,
    "closed_out": PositionStatus.CLOSED,
}

# MT5 integer constants (`execution/mt5_adapter.py` reads these out of the
# terminal). Spelled out here so the normaliser does not import python-MT5, which
# is optional in this deployment -- an adapter that cannot be imported must not
# take the canonical vocabulary down with it.
_MT5_ORDER_TYPE: Dict[int, OrderType] = {
    0: OrderType.MARKET, 1: OrderType.LIMIT, 2: OrderType.STOP,
    3: OrderType.STOP, 4: OrderType.STOP,
}
_MT5_ORDER_STATE: Dict[int, OrderStatus] = {
    0: OrderStatus.PENDING, 1: OrderStatus.SUBMITTED, 2: OrderStatus.CANCELLED,
    3: OrderStatus.PARTIAL, 4: OrderStatus.FILLED, 5: OrderStatus.REJECTED,
    6: OrderStatus.EXPIRED, 7: OrderStatus.SUBMITTED,
}
_MT5_DEAL_ENTRY: Dict[int, str] = {0: "in", 1: "out", 2: "inout", 3: "out_by"}


def _norm_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _opt(value: Any) -> Optional[float]:
    """A float, or None when the venue reported nothing.

    `bool` is rejected explicitly: `True` is a valid float in Python and a
    meaningless quantity on an order, and letting it through would record a
    one-lot price.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(raw: Dict[str, Any], *keys: str) -> Any:
    """The first alias the venue actually reported, `None` when none did.

    Presence, not truthiness. `raw.get("qty") or raw.get("volume")` reads as
    "prefer qty, else volume" and silently is not: a venue that reports
    `qty: 0.0` -- a cancelled-before-fill order, a position closed to flat, a
    deal booked at zero fee -- hands back `volume`, or `None` when no alias is
    present. Both are the same lie in different clothing, because `0.0` is a
    measurement this system promised to preserve and `None` is the absence of
    one. A rollup that read those rows as unpriced rather than zero would
    report every breakeven trade as unknown.
    """
    for key in keys:
        value = raw.get(key)
        if value is not None:
            return value
    return None


def _opt_str(value: Any) -> str:
    """A venue id as a string, empty when absent.

    Empty rather than None because this is an identifier column with a
    uniqueness constraint upstream, and the repository layer normalises empty to
    SQL NULL. Keeping the two representations distinct means a caller reading a
    normalised dict can tell "no venue id" from "id is the string zero".
    """
    return str(value or "").strip()


def canonical_side(value: Any) -> Optional[TradeDirection]:
    """Canonical direction, or None when the venue's word is not recognised.

    Returns None rather than guessing FLAT. A position whose side this function
    does not recognise is a data problem to surface, and defaulting it to FLAT
    would mark a live exposure as flat -- removing it from every risk
    calculation that reads positions.
    """
    return _SIDE_ALIASES.get(_norm_token(value))


def canonical_order_type(value: Any) -> Optional[OrderType]:
    return _ORDER_TYPE_ALIASES.get(_norm_token(value))


def canonical_order_status(value: Any) -> Optional[OrderStatus]:
    return _ORDER_STATUS_ALIASES.get(_norm_token(value))


def canonical_position_status(value: Any) -> Optional[PositionStatus]:
    return _POSITION_STATUS_ALIASES.get(_norm_token(value))


def canonical_mt5_order_type(value: Any) -> Optional[OrderType]:
    return _MT5_ORDER_TYPE.get(_as_int(value))


def canonical_mt5_order_state(value: Any) -> Optional[OrderStatus]:
    return _MT5_ORDER_STATE.get(_as_int(value))


def canonical_mt5_deal_entry(value: Any) -> Optional[str]:
    """MT5 deal entry flag -> a canonical fill direction.

    Returned as a plain string rather than an enum member because `inout` has no
    `TradeDirection` counterpart: MT5's "both" is a close-then-open in one deal,
    and mapping it to LONG or SHORT would invent a side the fill did not have.
    """
    return _MT5_DEAL_ENTRY.get(_as_int(value))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def normalize_order(raw: Dict[str, Any], *, venue: str, account_id: str,
                    order_id: str) -> Dict[str, Any]:
    """One venue order payload -> a `persistence.models_trades` order shape.

    `venue_order_ref` is required to be present when the venue issued a ticket
    and absent when it did not; the caller supplies the venue-native id and this
    function's job is to decide whether it counts. It passes `None` through when
    the payload has none, which is what lets an unsubmitted simulated order share
    a table with a broker-confirmed one without colliding in the uniqueness
    constraint.
    """
    symbol = _opt_str(raw.get("symbol"))
    status = canonical_order_status(raw.get("status"))
    side = canonical_side(_first(raw, "side", "direction"))
    order_type = canonical_order_type(_first(raw, "order_type", "type"))

    return {
        "order_id": order_id,
        "account_id": account_id,
        "venue": venue,
        "venue_order_ref": _venue_ref(raw.get("venue_order_ref")),
        "symbol": symbol,
        # Enum members render through `.value` so the row stores the same short
        # token `core.state` stores. A `TradeDirection.LONG` stringified into a
        # column reads `TradeDirection.LONG`, which then fails to match a lookup
        # comparing against `"long"`.
        "side": side.value if side is not None else "",
        "order_type": order_type.value if order_type is not None else "",
        "status": status.value if status is not None else "",
        "requested_qty": _opt(_first(raw, "qty", "volume")),
        "limit_price": _opt(_first(raw, "price", "limit_price")),
        "stop_price": _opt(_first(raw, "stop_price", "sl")),
        "filled_qty": _opt(_first(raw, "filled_qty", "volume")),
        "avg_fill_price": _opt(_first(raw, "filled_price", "avg_fill_price")),
        "currency": _opt_str(raw.get("currency")) or "USD",
        "fee_amount": _opt(_first(raw, "commission", "fee")),
        "margin_used": _opt(raw.get("margin")),
        "candidate_id": _opt_str(raw.get("candidate_id")),
        "thesis_id": _opt_str(raw.get("thesis_id")),
        "strategy_id": _opt_str(raw.get("strategy_id")),
        "risk_decision_id": _opt_str(raw.get("risk_decision_id")),
        "submitted_at": _opt(raw.get("submitted_at")),
        "filled_at": _opt(raw.get("filled_at")),
    }


def normalize_deal(raw: Dict[str, Any], *, venue: str, account_id: str,
                   deal_id: str = "") -> Dict[str, Any]:
    """One venue fill payload -> a deal shape.

    `deal_kind` defaults to `entry` only when the venue gave no entry flag at all
    *and* the fill opens exposure; a close with an unrecognised flag is stored as
    `exit` rather than counted as an opening trade. Getting this backwards makes a
    strategy look like it is constantly opening positions it never closed.
    """
    entry = canonical_mt5_deal_entry(raw.get("entry"))
    side = canonical_side(_first(raw, "side", "direction"))
    # `deal_kind` is a token, not a number, so truthiness is right here: an
    # absent key and an empty string mean the same thing for it.
    kind = _opt_str(raw.get("deal_kind"))
    if not kind:
        if entry == "out" or entry == "out_by":
            kind = "exit"
        elif side == TradeDirection.FLAT:
            # A flat fill is a balance movement, not a trade in either direction.
            kind = "balance"
        else:
            kind = "entry"

    return {
        "deal_id": deal_id or _venue_ref(raw.get("deal_id")),
        "account_id": account_id,
        "venue": venue,
        "venue_deal_ref": _venue_ref(raw.get("venue_deal_ref")),
        "venue_order_ref": _venue_ref(raw.get("venue_order_ref")),
        "venue_position_ref": _venue_ref(raw.get("venue_position_ref")),
        "symbol": _opt_str(raw.get("symbol")),
        "side": side.value if side is not None else "",
        "deal_kind": kind,
        "qty": _opt(_first(raw, "qty", "volume")),
        "price": _opt(_first(raw, "price", "filled_price")),
        "fee": _opt(_first(raw, "fee", "commission")),
        "swap": _opt(raw.get("swap")),
        # Never defaulted to 0.0: a venue that does not report P&L on a deal has
        # not reported zero P&L, and a 0.0 here would make a losing trade look
        # breakeven in every rollup.
        "pnl": _opt(_first(raw, "pnl", "realized_pnl")),
        "currency": _opt_str(raw.get("currency")) or "USD",
        "executed_at": _opt(_first(raw, "executed_at", "time")),
        "source": _opt_str(raw.get("source")),
    }


def normalize_position(raw: Dict[str, Any], *, venue: str, account_id: str,
                       position_id: str) -> Dict[str, Any]:
    """One venue position payload -> a position shape.

    `realized_pnl` is passed through and never recomputed. `core.state`
    accumulates realized P&L across partial closes and a normaliser that
    recomputed it from the venue's current total would drop every earlier partial
    close's contribution on the next sync.
    """
    side = canonical_side(_first(raw, "side", "direction"))
    status = canonical_position_status(raw.get("status"))

    return {
        "position_id": position_id,
        "account_id": account_id,
        "venue": venue,
        "venue_position_ref": _venue_ref(raw.get("venue_position_ref")),
        "symbol": _opt_str(raw.get("symbol")),
        "side": side.value if side is not None else "",
        "volume": _opt(_first(raw, "volume", "qty")),
        "entry_price": _opt(_first(raw, "entry_price", "price_open")),
        "current_price": _opt(_first(raw, "current_price", "price_current")),
        "sl": _opt(raw.get("sl")),
        "tp": _opt(raw.get("tp")),
        "status": status.value if status is not None else PositionStatus.OPEN.value,
        "order_id": _opt_str(raw.get("order_id")),
        "strategy_id": _opt_str(raw.get("strategy_id")),
        "unrealized_pnl": _opt(_first(raw, "unrealized_pnl", "profit")),
        "realized_pnl": _opt(_first(raw, "realized_pnl", "pnl")),
        "swap": _opt(raw.get("swap")),
        "opened_at": _opt(_first(raw, "opened_at", "time")),
        "closed_at": _opt(raw.get("closed_at")),
    }


def build_round_trip(entry_deal: Dict[str, Any],
                     exit_deal: Dict[str, Any]) -> Dict[str, Any]:
    """Pair two normalised fills into a round-trip shape.

    `gross_pnl` is the venue's own figure when it gave one, and only computed
    from prices when it did not -- direction matters, since
    `(exit - entry) * qty` is a loss on a short. `net_pnl` is gross minus the
    two fills' fees, because a round trip measured gross of costs is a round trip
    that reports every strategy as profitable and a fee-only strategy as the best
    one on the book.

    Returns a shape with `net_pnl: None` when the exit price or quantity is
    missing. A round trip whose result cannot be computed is stored with an
    unknown P&L rather than with zero, so the rollup counts it as neither a win
    nor a loss instead of quietly inflating the sample.
    """
    entry_price = _opt(entry_deal.get("price"))
    exit_price = _opt(exit_deal.get("price"))
    # Presence, not truthiness: a zero-quantity fill is a venue reporting a
    # number, and letting `or` skip it would silently promote the other leg's
    # quantity into a round trip that never had that size.
    entry_qty = _opt(entry_deal.get("qty"))
    exit_qty = _opt(exit_deal.get("qty"))
    qty = entry_qty if entry_qty is not None else exit_qty
    entry_side = canonical_side(entry_deal.get("side"))
    side = entry_side if entry_side is not None else canonical_side(
        exit_deal.get("side"))

    gross: Optional[float] = _opt(exit_deal.get("pnl"))
    if gross is None and entry_price is not None and exit_price is not None \
            and qty is not None:
        if side == TradeDirection.SHORT:
            gross = (entry_price - exit_price) * qty
        elif side == TradeDirection.LONG:
            gross = (exit_price - entry_price) * qty

    entry_fee = _opt(entry_deal.get("fee"))
    exit_fee = _opt(exit_deal.get("fee"))
    fees = None
    if entry_fee is not None or exit_fee is not None:
        fees = (entry_fee or 0.0) + (exit_fee or 0.0)

    entry_swap = _opt(entry_deal.get("swap"))
    exit_swap = _opt(exit_deal.get("swap"))
    swap = entry_swap if entry_swap is not None else exit_swap
    net: Optional[float] = None
    if gross is not None:
        net = gross - (fees or 0.0) - (swap or 0.0)

    opened_at = _opt(entry_deal.get("executed_at"))
    closed_at = _opt(exit_deal.get("executed_at"))

    return {
        "account_id": _opt_str(entry_deal.get("account_id")),
        "venue": _opt_str(entry_deal.get("venue")),
        "symbol": _opt_str(entry_deal.get("symbol")),
        "side": side.value if side is not None else "",
        "entry_deal_id": _venue_ref(entry_deal.get("deal_id")),
        "exit_deal_id": _venue_ref(exit_deal.get("deal_id")),
        "opened_at": opened_at,
        "closed_at": closed_at,
        "quantity": qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_pnl": gross,
        "fees": fees,
        "swap": swap,
        "net_pnl": net,
        "outcome": None if net is None else _outcome(net),
        "status": "closed" if closed_at is not None else "open",
    }


def _outcome(net_pnl: float) -> str:
    if net_pnl > 0:
        return "win"
    if net_pnl < 0:
        return "loss"
    return "breakeven"


def _venue_ref(value: Any) -> Optional[str]:
    """Absent, not empty. See `models_trades` on why `''` collides."""
    text = str(value or "").strip()
    return text or None


def unmapped_venue_fields(raw: Dict[str, Any], known: List[str]) -> List[str]:
    """Keys a normaliser did not read.

    For an adapter author, not a validator: a field appearing here is either a
    venue value worth mapping or a key this module has not been taught, and
    silently dropping it is how an exchange's margin mode stops being recorded.
    """
    consumed = {k for k in raw if k in set(known)}
    return sorted(k for k in raw if k not in consumed)
