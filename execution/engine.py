"""Execution & Operations: order construction and execution engine.

The ExecutionEngine converts an approved candidate into concrete orders
and routes them through the platform adapter (MT5 bridge).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

from core.contracts import OrderStatus, OrderType, TradeDirection
from core.events import Event, EventType, bus
from core.logging import get_logger
from core.state import OrderState, PositionState, state
from decision.candidate import TradeCandidate
from risk.governor import RiskDecision, RiskDecisionKind


log = get_logger("execution")


class ExecutionStatus(str, Enum):
    NOT_STARTED = "not_started"
    CONSTRUCTED = "constructed"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class OrderTicket:
    ticket: str
    order_id: str
    status: ExecutionStatus
    note: str = ""
    timestamp: float = field(default_factory=time.time)


class ExecutionEngine:
    """Builds order flows from approved candidates and issues them."""

    def __init__(self) -> None:
        self._tickets: Dict[str, OrderTicket] = {}
        self._last_error: Optional[str] = None

    def execute(self, candidate: TradeCandidate,
                decision: RiskDecision) -> Optional[OrderTicket]:
        if decision.kind != RiskDecisionKind.APPROVED:
            log.warning(f"execute() called with non-approved decision "
                        f"({decision.kind.value}); abort")
            return None

        order = OrderState(
            order_id=str(uuid.uuid4()),
            symbol=candidate.symbol,
            order_type=OrderType.MARKET,
            direction=candidate.direction,
            volume=candidate.size,
            price=candidate.entry,
            sl=candidate.stop_loss,
            tp=candidate.take_profit,
            candidate_id=candidate.candidate_id,
            status=OrderStatus.SUBMITTED,
        )
        state.add_order(order)

        bus.emit(Event(
            type=EventType.ORDER_SUBMITTED,
            source="execution.engine",
            payload={"order": order.as_dict(), "candidate": candidate.as_dict()},
        ))
        log.info(f"Order submitted {order.order_id[:8]} {order.symbol} "
                 f"{order.direction.value} vol={order.volume} @ {order.price}")

        return self._market_submit(order)

    def _market_submit(self, order: OrderState) -> OrderTicket:
        """Route order to MT5 (in production) or simulate fill (demo)."""

        # ATTENTION: MT5 bridge lives here. In this version, we simulate a
        # deterministic fill using current market state, which keeps the
        # flow testable end-to-end without a terminal connection.
        mk = state.get_market(order.symbol)
        fill_price = None
        if mk:
            fill_price = mk.ask if order.direction == TradeDirection.LONG else mk.bid
        if fill_price is None:
            # No market data: park as pending, do not fabricate an execution.
            ticket = OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                                 status=ExecutionStatus.SUBMITTED,
                                 note="waiting for market data")
            self._tickets[order.order_id] = ticket
            return ticket

        # Deterministic simulated fill (no randomness in tests).
        slippage = 0.0
        commission = abs(fill_price * order.volume) * 0.0001

        position = PositionState(
            position_id=str(uuid.uuid4()),
            symbol=order.symbol,
            direction=order.direction,
            volume=order.volume,
            entry_price=round(fill_price, 5),
            current_price=round(fill_price, 5),
            sl=order.sl,
            tp=order.tp,
            order_id=order.order_id,
        )
        state.add_position(position)

        order.status = OrderStatus.FILLED
        order.filled_price = round(fill_price, 5)
        order.slippage = slippage
        order.commission = commission
        state.update_order(order)

        bus.emit(Event(
            type=EventType.ORDER_FILLED,
            source="execution.engine",
            payload={"order": order.as_dict(), "position": position.as_dict()},
        ))
        bus.emit(Event(
            type=EventType.POSITION_OPENED,
            source="execution.engine",
            payload={"position": position.as_dict()},
        ))
        log.info(f"Order {order.order_id[:8]} filled @ {fill_price:.5f} "
                 f"(slip={slippage:.5f}, fee={commission:.2f})")

        ticket = OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                             status=ExecutionStatus.FILLED,
                             note=f"filled at {fill_price:.5f}")
        self._tickets[order.order_id] = ticket
        return ticket

    # -- Close helpers ----------------------------------------------------
    def close_position(self, position_id: str, price: Optional[float] = None) -> bool:
        pos = state.get_position(position_id)
        if pos is None:
            log.warning(f"close_position: unknown {position_id}")
            return False

        mk = state.get_market(pos.symbol)
        close_price = price
        if close_price is None and mk:
            close_price = mk.bid if pos.direction == TradeDirection.LONG else mk.ask
        if close_price is None:
            log.warning(f"close_position {position_id}: no market data to close")
            return False

        state.close_position(position_id, close_price)
        bus.emit(Event(
            type=EventType.POSITION_CLOSED,
            source="execution.engine",
            payload={"position": pos.as_dict(), "close_price": close_price},
        ))
        log.info(f"Position {position_id[:8]} closed @ {close_price:.5f}")
        return True


execution_engine = ExecutionEngine()
