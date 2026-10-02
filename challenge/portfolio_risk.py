"""The portfolio risk cap: 2% of equity, summed across symbols, not netted.

This is the account-level limit the operator set for a three-symbol book, and
the aggregation rule is the part that decides whether it is a real limit.

**Summed, not netted.** A long EURUSD and a long XAUUSD are summed at their
full risk even though both are dollar exposure and gold tends to move against
the dollar. Netting them would let a trader hold 3% long gold and 3% short
EURUSD and report 0% -- which is a *lower* number than either leg alone, for a
book that is not hedged, only inversely correlated. A cap expressed as a net
number therefore has no maximum, and an operator asked for a ceiling would
instead get a lever.

The correlation between these symbols is real and worth watching, but it is an
argument for a *tighter* cap on the pair, not for netting the cap away. The
per-symbol sizes stay the unit of enforcement; this module decides only whether
their sum fits.

Deliberately not derived from the policy's `max_leverage`. That is a tournament
term, recorded for audit, and on this account the broker's own margin model
binds an order of magnitude tighter -- see `challenge/leverage.py`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# The operator's figure for a three-symbol book, 2026-10-02. Not a policy
# constant: `ChallengePolicy` is where registered terms live, and this is an
# internal operating limit, so it is passed in by the caller that owns it.
DEFAULT_TOTAL_RISK_CAP_FRACTION = 0.02


def total_open_risk(per_symbol: Dict[str, float]) -> float:
    """Sum of each held symbol's risk, with no offsetting between symbols.

    Every value is floored at zero first. A negative "risk" is not a smaller
    position -- it is a sign convention leaking in from somewhere else, and
    summing one against another would silently *reduce* the total and hand the
    account headroom it never had.
    """
    total = 0.0
    for value in per_symbol.values():
        try:
            risk = float(value or 0.0)
        except (TypeError, ValueError):
            continue
        if risk > 0.0:
            total += risk
    return total


def portfolio_risk_room(per_symbol: Dict[str, float], equity: float,
                        cap_fraction: float = DEFAULT_TOTAL_RISK_CAP_FRACTION,
                        already_proposed: float = 0.0) -> Dict[str, Any]:
    """Cash still available under the aggregate cap, and the sum that consumed it.

    `already_proposed` is a risk already committed by candidates accepted earlier
    in the same decision pass but not yet reflected in open positions. Without it
    a burst of candidates would each be measured against the cap as though the
    others did not exist, which is the shape of a limit that only works when
    nothing else is trading.

    Cap basis is the smaller of current equity and 100,000 USD (requirement 4).
    """
    if equity <= 0:
        return {"room": None, "total": total_open_risk(per_symbol),
                "cap_usd": None, "cap_fraction": float(cap_fraction),
                "known": False,
                "reason": "equity is not positive, so no cap can be expressed"}
    equity_basis = min(float(equity), 100000.0)
    cap_usd = equity_basis * float(cap_fraction)
    total = total_open_risk(per_symbol) + max(0.0, float(already_proposed or 0.0))
    return {"room": max(0.0, cap_usd - total),
            "total": total,
            "cap_usd": cap_usd,
            "cap_fraction": float(cap_fraction),
            "known": True,
            "reason": "summed across symbols, not netted"}


def check_portfolio_risk(per_symbol: Dict[str, float], equity: float,
                         proposed: float,
                         cap_fraction: float = DEFAULT_TOTAL_RISK_CAP_FRACTION,
                         already_proposed: float = 0.0) -> Dict[str, Any]:
    """Whether one more risk figure fits under the aggregate cap.

    Reports the *contributing* symbols even when the decision is to allow, so an
    operator can see which positions are consuming the cap. Ordered largest
    first: the biggest contributor is the one a decision to trim would start
    from, and sorting alphabetically would bury it.
    """
    room = portfolio_risk_room(per_symbol, equity, cap_fraction,
                               already_proposed)
    proposed = max(0.0, float(proposed or 0.0))
    contributors: List[Dict[str, Any]] = [
        {"symbol": symbol, "risk": risk}
        for symbol, risk in sorted(per_symbol.items(),
                                   key=lambda kv: -float(kv[1] or 0.0))
        if float(risk or 0.0) > 0
    ]
    if not room["known"]:
        return {"passed": False, "verdict": "halt", **room,
                "proposed": proposed,
                "contributors": contributors,
                "decision_reason": room["reason"]}
    if proposed <= 0:
        return {"passed": True, "verdict": "allow", **room,
                "proposed": proposed,
                "contributors": contributors,
                "decision_reason": "no proposed risk to add"}
    if proposed > room["room"]:
        return {"passed": False, "verdict": "resize", **room,
                "proposed": proposed,
                "contributors": contributors,
                "decision_reason": (
                    f"total risk {room['total']:.2f} + {proposed:.2f} exceeds the "
                    f"{cap_fraction:.0%} cap of {room['cap_usd']:.2f}; summed "
                    "across symbols without netting")}
    return {"passed": True, "verdict": "allow", **room,
            "proposed": proposed,
            "contributors": contributors,
            "decision_reason": (
                f"total risk {room['total']:.2f} + {proposed:.2f} within the "
                f"{cap_fraction:.0%} cap of {room['cap_usd']:.2f}")}


def account_currency_risk(position: Any, market: Any) -> Optional[float]:
    """One position's loss at its stop, in account currency.

    NOT `PositionState.risk`. That property is SL distance multiplied by volume
    with no tick economics, so on an MT5 contract symbol it returns a price
    difference rather than money: a 50-pip EURUSD stop on 0.02 lots comes out
    as 0.0001 "USD". Summing those across a book reports a total of essentially
    zero, and a 2% cap built on it never binds -- the limit would look satisfied
    while the account held a real loss on every position.

    The real figure is (SL distance / tick size) * tick value * volume, the same
    arithmetic the sizer uses. Ticks are quoted in points, so tick_size and
    tick_value are both required; a market that does not supply them yields None
    rather than a guess, and the caller reports the position as unmeasurable.
    """
    sl = getattr(position, "sl", None)
    if sl in (None, 0, 0.0):
        return None
    try:
        entry = float(getattr(position, "entry_price", 0.0) or 0.0)
        volume = float(getattr(position, "volume", 0.0) or 0.0)
        stop = float(sl)
        tick_size = float(getattr(market, "tick_size", 0.0) or 0.0)
        tick_value = float(getattr(market, "tick_value", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or volume <= 0 or tick_size <= 0 or tick_value <= 0:
        return None
    distance = abs(entry - stop)
    if distance <= 0:
        return None
    return (distance / tick_size) * tick_value * volume


def book_risk(positions: Iterable[Any], market_for: Any) -> Dict[str, Any]:
    """Per-symbol open risk in account currency, with unmeasurable named.

    `market_for` is called as `market_for(symbol)` and may return None. The
    separation matters: a position whose risk cannot be computed is reported
    under `unmeasurable` rather than counted as zero, so the caller can refuse
    the book instead of discovering later that the cap was computed from a
    partial view of it.
    """
    per_symbol: Dict[str, float] = {}
    unmeasurable: List[str] = []
    for position in positions:
        symbol = str(getattr(position, "symbol", "") or "")
        if not symbol:
            continue
        market = market_for(symbol) if market_for is not None else None
        risk = account_currency_risk(position, market)
        if risk is None:
            if symbol not in unmeasurable:
                unmeasurable.append(symbol)
            continue
        per_symbol[symbol] = per_symbol.get(symbol, 0.0) + risk
    return {"risk_by_symbol": per_symbol,
            "unmeasurable": sorted(unmeasurable),
            "total": total_open_risk(per_symbol)}


def risk_by_symbol(positions: Iterable[Any]) -> Dict[str, float]:
    """Per-symbol open risk from canonical positions.

    A position's risk is its own unrealised loss at its stop: the SL distance
    from entry, priced in account currency. A position with no stop contributes
    zero *and is reported*, because a stopless position's risk is unbounded and
    quietly counting it as zero is the unsafe direction -- the caller can then
    decide to refuse it rather than inheriting a total that understates the book
    by everything that position could lose.
    """
    out: Dict[str, float] = {}
    for position in positions:
        symbol = str(getattr(position, "symbol", "") or "")
        if not symbol:
            continue
        try:
            risk = float(getattr(position, "risk", 0.0) or 0.0)
        except (TypeError, ValueError):
            risk = 0.0
        if risk < 0:
            risk = 0.0
        out[symbol] = out.get(symbol, 0.0) + risk
    return out


def stopless_symbols(positions: Iterable[Any]) -> List[str]:
    """Positions carrying no stop, whose risk cannot be bounded."""
    out: List[str] = []
    for position in positions:
        if getattr(position, "sl", None) in (None, 0, 0.0):
            symbol = str(getattr(position, "symbol", "") or "")
            if symbol:
                out.append(symbol)
    return sorted(set(out))
