"""Canonical State management for TraderAIG.

Single source of truth for all system state. Components read through
defined contracts, and only the owning component may write.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .contracts import (
    OrderStatus,
    OrderType,
    PositionStatus,
    RegimeSnapshot,
    TradeDirection,
)
from .logging import get_logger


log = get_logger("core.state")


@dataclass
class AccountState:
    login: int
    broker: str = ""
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    leverage: int = 100
    currency: str = "USD"
    server: str = ""
    status: str = "active"
    last_update: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class OrderState:
    order_id: str
    symbol: str
    order_type: OrderType
    direction: TradeDirection
    volume: float
    price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    candidate_id: Optional[str] = None
    filled_price: Optional[float] = None
    slippage: float = 0.0
    commission: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class PositionState:
    position_id: str
    symbol: str
    direction: TradeDirection
    volume: float
    entry_price: float
    current_price: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    status: PositionStatus = PositionStatus.OPEN
    order_id: Optional[str] = None
    open_time: float = field(default_factory=time.time)
    close_time: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    swap: float = 0.0
    last_update: float = field(default_factory=time.time)

    @property
    def risk(self) -> float:
        """Rough risk in account currency: SL distance * volume."""
        if self.sl is None:
            return 0.0
        if self.direction == TradeDirection.LONG:
            return max(0.0, self.entry_price - self.sl) * self.volume
        return max(0.0, self.sl - self.entry_price) * self.volume

    def market_value(self) -> float:
        return self.current_price * self.volume

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ThesisState:
    thesis_id: str
    symbol: str
    direction: TradeDirection
    entry_zone: List[float]
    stop_loss: float
    take_profit: List[float]
    confidence: float = 0.5
    status: str = "pending"
    regime_id: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class RiskState:
    timestamp: float = field(default_factory=time.time)
    open_positions: int = 0
    daily_pnl: float = 0.0
    current_drawdown: float = 0.0
    peak_equity: float = 0.0
    last_day_epoch: int = field(default_factory=lambda: int(time.time()) // 86400)
    exposure_by_symbol: Dict[str, float] = field(default_factory=dict)
    last_risk_check: float = field(default_factory=time.time)
    risk_score: float = 0.0
    vetoes: List[Dict[str, Any]] = field(default_factory=list)
    breaches: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class MarketState:
    symbol: str
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    last_price: float = 0.0
    last_tick_time: float = 0.0
    tick_size: float = 0.0
    tick_value: float = 0.0
    contract_size: float = 0.0
    volume_min: float = 0.0
    volume_step: float = 0.0
    volume_max: float = 0.0
    regime: Optional[RegimeSnapshot] = None
    candles: Dict[str, List[float]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class CanonicalState:
    """Thread-safe store of canonical truth.

    Uses a read-write lock so readers (analysis modules) can run in
    parallel while writers (execution/state sync) get exclusive access.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.account = AccountState(login=0)
        self.market: Dict[str, MarketState] = {}
        self.orders: Dict[str, OrderState] = {}
        self.positions: Dict[str, PositionState] = {}
        self.thesis: Dict[str, ThesisState] = {}
        self.risk = RiskState()

    # -- Account --------------------------------------------------------
    def get_account(self) -> AccountState:
        with self._lock:
            return self.account

    def set_account(self, account: AccountState) -> None:
        with self._lock:
            self.account = account
            if account.equity > self.risk.peak_equity:
                self.risk.peak_equity = account.equity
            log.info(
                f"Account state updated: balance={account.balance:.2f} "
                f"equity={account.equity:.2f} margin={account.margin:.2f} "
                f"free_margin={account.free_margin:.2f}"
            )

    # -- Market ---------------------------------------------------------
    def get_market(self, symbol: str) -> Optional[MarketState]:
        with self._lock:
            return self.market.get(symbol)

    def upsert_market(self, state: MarketState) -> None:
        with self._lock:
            self.market[state.symbol] = state

    # -- Orders ---------------------------------------------------------
    def add_order(self, order: OrderState) -> None:
        with self._lock:
            self.orders[order.order_id] = order
            log.info(f"Order {order.order_id} registered: {order.symbol} {order.direction}")

    def get_order(self, order_id: str) -> Optional[OrderState]:
        with self._lock:
            return self.orders.get(order_id)

    def update_order(self, order: OrderState) -> None:
        with self._lock:
            if order.order_id in self.orders:
                order.updated_at = time.time()
                self.orders[order.order_id] = order
                log.info(f"Order {order.order_id} status -> {order.status}")

    def orders_by_status(self, status: OrderStatus) -> List[OrderState]:
        with self._lock:
            return [o for o in self.orders.values() if o.status == status]

    # -- Positions ------------------------------------------------------
    def add_position(self, position: PositionState) -> None:
        with self._lock:
            self.positions[position.position_id] = position
            self.risk.open_positions = len([p for p in self.positions.values()
                                            if p.status == PositionStatus.OPEN])
            self._recompute_exposure()
            log.info(f"Position {position.position_id} opened: "
                     f"{position.symbol} {position.direction} vol={position.volume}")

    def get_position(self, position_id: str) -> Optional[PositionState]:
        with self._lock:
            return self.positions.get(position_id)

    def update_position(self, position: PositionState) -> None:
        with self._lock:
            position.last_update = time.time()
            self.positions[position.position_id] = position
            self._recompute_exposure()

    def settle_realized(self, position_id: str, amount: float) -> None:
        """Book a realized PnL increment from a partial close (E4 appendix B).

        Partial exits never touch the full-close path, so without this the
        daily-loss guard could not see mid-close realized results. The amount
        accumulates on the position and flows into ``risk.daily_pnl`` with the
        same day-roll discipline as a close. Financing swap is *not* settled
        here: it is reported by the broker sync and booked once at close, so
        it can never be double-counted.
        """
        with self._lock:
            self.roll_risk_day()
            pos = self.positions.get(position_id)
            if pos is None or pos.status == PositionStatus.CLOSED:
                log.warning(f"settle_realized skipped: no open position "
                            f"{position_id} ({amount:+.2f})")
                return
            pos.realized_pnl += amount
            pos.last_update = time.time()
            self.positions[position_id] = pos
            self.risk.daily_pnl += amount

    def close_position(self, position_id: str, close_price: float) -> None:
        with self._lock:
            self.roll_risk_day()
            pos = self.positions.get(position_id)
            if pos is None or pos.status == PositionStatus.CLOSED:
                return
            pos.status = PositionStatus.CLOSED
            pos.close_time = time.time()
            pos.current_price = close_price
            # Accumulate the final piece onto any partial-close realized PnL
            # instead of overwriting it (E4): a close after partial exits must
            # report the position's full realized result, not just the last
            # lot. Only the *final* piece is added to daily_pnl (partials were
            # already settled) plus the swap, which is booked exactly once.
            final = self._calc_pnl(pos)
            pos.realized_pnl += final
            pos.unrealized_pnl = 0.0
            self.risk.open_positions = len([p for p in self.positions.values()
                                            if p.status == PositionStatus.OPEN])
            self.risk.daily_pnl += final + pos.swap
            self._recompute_exposure()
            log.info(f"Position {position_id} closed: realized_pnl="
                     f"{pos.realized_pnl:.2f} swap={pos.swap:.2f}")

    def open_positions(self) -> List[PositionState]:
        with self._lock:
            return [p for p in self.positions.values() if p.status == PositionStatus.OPEN]

    def _calc_pnl(self, pos: PositionState) -> float:
        if pos.direction == TradeDirection.LONG:
            return (pos.current_price - pos.entry_price) * pos.volume
        return (pos.entry_price - pos.current_price) * pos.volume

    # -- Thesis ---------------------------------------------------------
    def add_thesis(self, thesis: ThesisState) -> None:
        with self._lock:
            self.thesis[thesis.thesis_id] = thesis

    def get_thesis(self, thesis_id: str) -> Optional[ThesisState]:
        with self._lock:
            return self.thesis.get(thesis_id)

    def update_thesis(self, thesis: ThesisState) -> None:
        with self._lock:
            thesis.updated_at = time.time()
            self.thesis[thesis.thesis_id] = thesis

    # -- Risk -----------------------------------------------------------
    def roll_risk_day(self, now: Optional[float] = None) -> bool:
        """Reset daily_pnl when the UTC trading day changes.

        Returns True when the day actually rolled over (daily_pnl zeroed).
        """
        with self._lock:
            epoch = int((now if now is not None else time.time()) // 86400)
            if epoch == self.risk.last_day_epoch:
                return False
            self.risk.last_day_epoch = epoch
            self.risk.daily_pnl = 0.0
            log.info(f"New trading day: daily_pnl reset to {self.risk.daily_pnl:.2f}")
            return True

    def _recompute_exposure(self) -> None:
        """Recompute exposure by symbol from open positions (single source)."""
        exposure: Dict[str, float] = {}
        for p in self.positions.values():
            if p.status == PositionStatus.OPEN and p.volume > 0:
                symbol = p.symbol or "UNKNOWN"
                exposure[symbol] = exposure.get(symbol, 0.0) + p.volume
        self.risk.exposure_by_symbol = exposure

    def record_veto(self, veto: Dict[str, Any]) -> None:
        with self._lock:
            if "recorded_at" not in veto:
                veto["recorded_at"] = time.time()
            self.risk.vetoes.append(veto)
        self._persist_veto(veto)

    @staticmethod
    def _persist_veto(veto: Dict[str, Any]) -> None:
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.repositories import RiskVetoRepository

            if not persistence_enabled():
                return
            RiskVetoRepository(make_live_session()).save(veto)
        except Exception:  # noqa: BLE001
            log.debug(f"Veto persistence skipped for {veto.get('decision_id', '?')}")

    def hydrate_risk_vetoes(self, limit: int = 300) -> int:
        """Load persisted vetoes into memory once (no-op if already populated).

        Returns how many records were loaded (0 when nothing/disabled/duplicate).
        """
        if self.risk.vetoes:
            return 0
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.repositories import RiskVetoRepository

            if not persistence_enabled():
                return 0
            rows = RiskVetoRepository(make_live_session()).list(limit)
            with self._lock:
                self.risk.vetoes = rows
            return len(rows)
        except Exception:  # noqa: BLE001
            return 0

    def record_breach(self, breach: Dict[str, Any]) -> None:
        with self._lock:
            self.risk.breaches.append(breach)


# Module-level singleton.
state = CanonicalState()
