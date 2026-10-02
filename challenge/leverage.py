"""Effective leverage and margin-derived size, measured rather than declared.

MT5 has no leverage property on a symbol. `AccountInfo.leverage` is an account
field, and on this deployment it reads `1` on a funded 100k tournament account
-- so the number the policy records as `max_leverage` (1:500, the tournament's
published allowance) and the number that actually governs how much margin a
position consumes are different quantities, and the second is the binding one.

The effective leverage of a symbol is therefore *derived*: notional divided by
the margin MT5 itself requires for that position. `order_calc_margin` is the
only way to read it, because it is the broker's own margin model -- including
the parts that no public field exposes, such as a per-symbol multiplier applied
on top of the account setting.

Measured on FTTrading-Server for account 1400167, 2026-10-02:

    EURUSD  1 lot -> 112,415 notional /  2,810 margin = 40:1
    XAUUSD  1 lot -> 415,536 notional / 41,554 margin = 10:1
    BTCUSD  1 lot ->  84,992 notional / 16,998 margin =  5:1

The gap is the whole reason this module exists. Sizing from the tournament's
1:500 rather than from 40/10/5 overstates affordable size by more than an order
of magnitude on gold, which is a larger position than the daily loss and the
drawdown were sized for.

Everything here fails closed: an unmeasurable symbol yields no size, never an
unlimited one. The safe failure is "refuse", because the unsafe one is a
position sized off a number the broker never agreed to.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.logging import get_logger

log = get_logger("challenge.leverage")

# Margin level is margin/equity as a percentage, so 300% means margin may not
# exceed equity/3. This is the engine's own floor, independent of any stop-out
# the provider states: the stricter of the two binds.
DEFAULT_INTERNAL_MARGIN_FLOOR_PCT = 300.0

_CACHE_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class SymbolLeverage:
    """One symbol's measured margin economics."""

    symbol: str
    effective_leverage: float
    margin_per_lot: float
    notional_per_lot: float
    measured_at: float

    def as_dict(self) -> Dict[str, Any]:
        return {"symbol": self.symbol,
                "effective_leverage": round(self.effective_leverage, 2),
                "margin_per_lot": round(self.margin_per_lot, 2),
                "notional_per_lot": round(self.notional_per_lot, 2),
                "measured_at": self.measured_at}


def _terminal():
    """The MT5 module, or None when the terminal is not reachable.

    Optional by design: a deployment with no terminal (CI, a paper account, a
    unit test) must degrade to "no size" rather than raise, or every consumer
    of this module becomes terminal-dependent.
    """
    try:
        import MetaTrader5 as mt5  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    return mt5


def measure_symbol(symbol: str, *,
                   volume: float = 1.0) -> Optional[SymbolLeverage]:
    """Measure one symbol's margin economics from the broker's own model.

    `volume` defaults to 1.0 lot because that is the unit the broker quotes
    margin in, and a per-lot figure is what a size calculation multiplies. Any
    other volume is divided back out, so the caller can measure at a size the
    account can actually afford rather than at a size it cannot.

    `order_calc_margin` is used rather than `SymbolInfo.margin_initial`, which
    reads 0.0 on every symbol of this account -- the field is not populated, so
    anything built on it would divide by zero and read as unlimited margin.

    None means "cannot state this symbol's economics". Never a default, never
    an estimate, and never the tournament's declared leverage: those are three
    different numbers and only one of them is the broker's.
    """
    mt5 = _terminal()
    if mt5 is None:
        return None
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or info.trade_contract_size <= 0:
        return None
    price = (float(tick.bid) + float(tick.ask)) / 2.0
    if price <= 0:
        return None
    try:
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, float(volume), price)
    except Exception:  # noqa: BLE001
        log.debug(f"margin calc raised for {symbol}", exc_info=True)
        return None
    if not margin or margin <= 0:
        return None
    notional = float(info.trade_contract_size) * price * float(volume)
    if notional <= 0:
        return None
    return SymbolLeverage(
        symbol=symbol,
        effective_leverage=notional / float(margin),
        margin_per_lot=float(margin) / float(volume),
        notional_per_lot=notional / float(volume),
        measured_at=time.time())


class LeverageCache:
    """Short-lived measurements, because margin economics move with the clock.

    Cached rather than measured per call because `order_calc_margin` is a
    round trip to the terminal, and the governor asks about several symbols per
    decision. The TTL is short enough that a margin hike is picked up within
    the same session rather than after a restart, and long enough that a burst
    of candidates is not one round trip each.
    """

    def __init__(self, ttl_seconds: float = _CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: Dict[str, SymbolLeverage] = {}

    def get(self, symbol: str) -> Optional[SymbolLeverage]:
        cached = self._entries.get(symbol)
        if cached is not None and (time.time() - cached.measured_at) < self._ttl:
            return cached
        measured = measure_symbol(symbol)
        if measured is not None:
            self._entries[symbol] = measured
        return measured

    def invalidate(self, symbol: Optional[str] = None) -> None:
        if symbol is None:
            self._entries.clear()
        else:
            self._entries.pop(symbol, None)

    def as_dict(self) -> Dict[str, Any]:
        return {s: v.as_dict() for s, v in self._entries.items()}


_default_cache = LeverageCache()


def symbol_leverage(symbol: str) -> Optional[SymbolLeverage]:
    return _default_cache.get(symbol)


def max_lots_by_margin(symbol: str, *, equity: float,
                       margin_floor_pct: float = DEFAULT_INTERNAL_MARGIN_FLOOR_PCT,
                       used_margin: float = 0.0) -> Optional[float]:
    """Lots this symbol can carry without breaching the internal margin floor.

    The floor is a *margin level*: at 300% the account may hold at most
    `equity / 3` in margin, and whatever is already committed comes off the top
    first. On a 100k account that is 33,333 USD of margin, which at gold's
    measured 41,554 per lot is 0.80 lots -- the number that actually binds,
    far below anything the tournament's 1:500 suggests.

    None when the symbol's economics cannot be measured or the equity is not
    positive. Both are refusals to state a size, and neither is a permission.
    """
    if equity <= 0:
        return None
    measured = symbol_leverage(symbol)
    if measured is None or measured.margin_per_lot <= 0:
        return None
    if margin_floor_pct <= 0:
        return None
    budget = (equity * 100.0 / float(margin_floor_pct)) - float(used_margin or 0.0)
    if budget <= 0:
        return 0.0
    return budget / measured.margin_per_lot


def size_for_candidate(symbol: str, *, risk_budget: float, risk_per_lot: float,
                       equity: float,
                       margin_floor_pct: float = DEFAULT_INTERNAL_MARGIN_FLOOR_PCT,
                       used_margin: float = 0.0,
                       volume_min: float = 0.01,
                       volume_step: float = 0.01) -> Dict[str, Any]:
    """Size a position as the smaller of what the risk budget and margin allow.

    Two independent constraints, and the smaller wins:

      * the risk budget -- what a stop-loss loss may cost the account, which is
        what the challenge rules are written against;
      * the margin floor -- what the broker will actually carry at the
        account's own margin level.

    Sizing on the first alone produces positions the account cannot carry; on
    the second alone produces positions whose stop is far outside the daily
    loss. Neither is a substitute for the other, and the policy's declared
    `max_leverage` is deliberately not consulted here: it is a tournament term
    recorded for audit, and the broker's margin model is what actually binds.

    The result is rounded DOWN to the volume step, because rounding up would
    put the position back over whichever limit it was just fitted to, and it is
    reported as 0.0 rather than refused so the caller can distinguish "too
    small to trade" from "not measurable".
    """
    by_risk = 0.0
    if risk_per_lot and risk_per_lot > 0 and risk_budget > 0:
        by_risk = float(risk_budget) / float(risk_per_lot)
    by_margin = max_lots_by_margin(symbol, equity=equity,
                                   margin_floor_pct=margin_floor_pct,
                                   used_margin=used_margin)
    measured = symbol_leverage(symbol)
    step = float(volume_step) if volume_step and volume_step > 0 else 0.01
    vmin = float(volume_min) if volume_min and volume_min > 0 else 0.01

    if measured is None or by_margin is None:
        # Refuse rather than fall back to the risk budget alone. Sizing on risk
        # when the broker's margin is unknown is the fail-open direction: the
        # result is a position sized off a number the account may not be able to
        # carry, and it is returned as a confident size rather than as a refusal.
        return {"symbol": symbol, "size": 0.0,
                "binding_limit": "margin_floor",
                "lots_by_risk_budget": round(by_risk, 6),
                "lots_by_margin_floor": None,
                "effective_leverage": None,
                "margin_per_lot": None,
                "margin_floor_pct": float(margin_floor_pct),
                "margin_budget_usd": round(equity * 100.0 / float(margin_floor_pct), 2)
                if margin_floor_pct > 0 else None,
                "reason": "symbol margin economics not measurable"}

    binding = "risk_budget" if by_risk <= by_margin else "margin_floor"
    raw = by_risk if binding == "risk_budget" else float(by_margin)
    stepped = math.floor(raw / step) * step
    # Never rounded up to reach the minimum: a size below the minimum is not a
    # trade, and stretching it to `volume_min` would breach the very limit that
    # produced it.
    size = stepped if stepped >= vmin else 0.0
    return {
        "symbol": symbol,
        "size": round(size, 6),
        "binding_limit": binding,
        "lots_by_risk_budget": round(by_risk, 6),
        "lots_by_margin_floor": round(by_margin, 6),
        "effective_leverage": round(measured.effective_leverage, 2),
        "margin_per_lot": round(measured.margin_per_lot, 2),
        "margin_floor_pct": float(margin_floor_pct),
        "margin_budget_usd": round(equity * 100.0 / float(margin_floor_pct), 2)
        if margin_floor_pct > 0 else None,
        "reason": ("below the broker's minimum volume" if size == 0.0
                   else f"bounded by {binding}"),
    }
