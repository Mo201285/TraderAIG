"""CEX Gateway: routes approved candidates to a centralized exchange.

Mirrors the ExecutionEngine contract (execute -> OrderTicket) and the
LiveMT5Executor discipline: live money only when the operator explicitly
arms the gate. Default is paper/testnet; real capital requires
`CEX_MODE=live` + `CEX_LIVE_ALLOWED=1` + live API keys.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from core.config import settings
from core.contracts import OrderStatus, OrderType, TradeDirection
from core.events import Event, EventType, bus
from core.logging import get_logger
from core.state import OrderState, PositionState, state
from decision.candidate import TradeCandidate
from execution.cex.venues import VenueAdapter, VenueLockedError, build_venue
from risk.governor import RiskDecision, RiskDecisionKind


log = get_logger("execution.cex.gateway")


class CexGateway:
    """Single facade over the selected CEX venue.

    paper  -> deterministic fills from canonical market state (no network)
    testnet/live -> real signed orders through the venue adapter
    """

    def __init__(self, venue: Optional[VenueAdapter] = None) -> None:
        self._venue = venue or build_venue(settings.cex.venue, settings.cex.mode)
        self._tickets: Dict[str, Any] = {}
        self._last_error: str = ""

    def refresh(self) -> None:
        """Re-derive the venue from the Secrets Vault (28.18) so a rotated
        key applies to the running singleton without a restart. Keeps the
        in-flight ticket registry; only the credential-bound venue is rebuilt."""
        old = self._venue
        try:
            self._venue = build_venue(settings.cex.venue, settings.cex.mode)
        except Exception:  # noqa: BLE001
            self._venue = old
            log.warning("CEX gateway refresh failed; keeping previous venue")
        if self._venue is not old:
            log.info("CEX gateway refreshed credentials from the vault")

    # -- Public execution contract --------------------------------------
    def execute(self, candidate: TradeCandidate,
                decision: RiskDecision) -> Optional[Any]:
        """Execute an approved candidate against the configured venue."""
        if decision.kind != RiskDecisionKind.APPROVED:
            log.warning(f"CEX execute() with non-approved decision "
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
            strategy_id=getattr(candidate, "strategy_id", None),
            venue=self._venue.name,
            status=OrderStatus.SUBMITTED,
        )
        state.add_order(order)
        bus.emit(Event(
            type=EventType.ORDER_SUBMITTED,
            source="execution.cex",
            payload={"order": order.as_dict(), "candidate": candidate.as_dict()},
        ))

        if self._venue.mode == self._venue.PAPER:
            ticket = self._paper_submit(order)
        else:
            ticket = self._venue_submit(order)
        self._tickets[order.order_id] = ticket
        return ticket

    def close_position(self, position_id: str, price: Optional[float] = None) -> bool:
        """Close an open position (paper or venue)."""
        pos = state.get_position(position_id)
        if pos is None:
            log.warning(f"CEX close_position: unknown {position_id}")
            return False

        if self._venue.mode == self._venue.PAPER:
            mk = state.get_market(pos.symbol)
            close_price = price
            if close_price is None and mk:
                close_price = mk.bid if pos.direction == TradeDirection.LONG else mk.ask
            if close_price is None:
                log.warning(f"CEX close_position {position_id}: no market data")
                return False
            state.close_position(position_id, close_price)
            bus.emit(Event(
                type=EventType.POSITION_CLOSED,
                source="execution.cex",
                payload={"position": pos.as_dict(), "close_price": close_price},
            ))
            log.info(f"CEX paper close {position_id} @ {close_price:.5f}")
            return True

        side = "sell" if pos.direction == TradeDirection.LONG else "buy"
        try:
            result = self._venue.close_market_position(pos.symbol, side, pos.volume)
        except VenueLockedError as exc:
            self._last_error = str(exc)
            log.warning(f"CEX close denied: {self._last_error}")
            return False
        if not result.get("ok"):
            self._last_error = result.get("error", "close failed")
            return False
        state.close_position(position_id, pos.current_price or pos.entry_price)
        bus.emit(Event(
            type=EventType.POSITION_CLOSED,
            source="execution.cex",
            payload={"position": pos.as_dict(), "venue_result": result},
        ))
        return True

    # -- Paper path (deterministic, mirror of ExecutionEngine) ----------
    def _paper_submit(self, order: OrderState) -> Any:
        from execution.engine import ExecutionStatus, OrderTicket
        mk = state.get_market(order.symbol)
        if mk is None or mk.ask <= 0 or mk.bid <= 0:
            ticket = OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                                 status=ExecutionStatus.SUBMITTED,
                                 note="waiting for market data")
            return ticket

        fill_price = mk.ask if order.direction == TradeDirection.LONG else mk.bid
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
            strategy_id=getattr(order, "strategy_id", None),
            venue=self._venue.name,
        )
        state.add_position(position)

        order.status = OrderStatus.FILLED
        order.filled_price = round(fill_price, 5)
        order.slippage = 0.0
        order.commission = commission
        state.update_order(order)

        bus.emit(Event(type=EventType.ORDER_FILLED, source="execution.cex",
                       payload={"order": order.as_dict(),
                                "position": position.as_dict()}))
        bus.emit(Event(type=EventType.POSITION_OPENED, source="execution.cex",
                       payload={"position": position.as_dict()}))
        log.info(f"CEX paper FILLED {order.symbol} vol={order.volume} "
                 f"@ {fill_price:.5f}")

        return OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                           status=ExecutionStatus.FILLED,
                           note=f"paper filled at {fill_price:.5f}")

    # -- Venue path (real signed orders) ---------------------------------
    def _venue_submit(self, order: OrderState) -> Any:
        from execution.engine import ExecutionStatus, OrderTicket
        side = "buy" if order.direction == TradeDirection.LONG else "sell"
        try:
            result = self._venue.place_market_order(order.symbol, side, order.volume)
        except VenueLockedError as exc:
            self._last_error = str(exc)
            return self._reject(order, self._last_error)

        if not result.get("ok"):
            self._last_error = result.get("error", "venue rejected order")
            return self._reject(order, self._last_error)

        fill_price = 0.0
        if result.get("price"):
            fill_price = float(result["price"])
        elif result.get("filled"):
            fill_price = float(result["filled"])  # fallback estimate
        if fill_price <= 0:
            # No execution price (e.g. OKX async submit): keep as submitted
            # rather than fabricate a fill.
            return self._pending(order, result)

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
            strategy_id=getattr(order, "strategy_id", None),
            venue=self._venue.name,
        )
        state.add_position(position)
        order.status = OrderStatus.FILLED
        order.filled_price = round(fill_price, 5)
        order.commission = abs(fill_price * order.volume) * 0.0001
        state.update_order(order)

        bus.emit(Event(type=EventType.ORDER_FILLED, source="execution.cex",
                       payload={"order": order.as_dict(), "position":
                                position.as_dict(), "venue": result}))
        bus.emit(Event(type=EventType.POSITION_OPENED, source="execution.cex",
                       payload={"position": position.as_dict()}))
        log.info(f"CEX FILLED {order.symbol} vol={order.volume} @ {fill_price:.5f} "
                 f"(venue={self._venue.name} id={result.get('order_id')})")
        return OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                           status=ExecutionStatus.FILLED,
                           note=f"venue filled at {fill_price:.5f}")

    def _reject(self, order: OrderState, error: str) -> Any:
        from execution.engine import ExecutionStatus, OrderTicket
        order.status = OrderStatus.REJECTED
        state.update_order(order)
        bus.emit(Event(type=EventType.ORDER_REJECTED, source="execution.cex",
                       payload={"order": order.as_dict(), "error": error}))
        log.warning(f"CEX order {order.order_id[:8]} REJECTED: {error}")
        return OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                           status=ExecutionStatus.REJECTED, note=error)

    def _pending(self, order: OrderState, result: Dict[str, Any]) -> Any:
        from execution.engine import ExecutionStatus, OrderTicket
        bus.emit(Event(type=EventType.ORDER_SUBMITTED, source="execution.cex",
                       payload={"order": order.as_dict(), "venue": result}))
        return OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                           status=ExecutionStatus.SUBMITTED,
                           note=f"submitted to {self._venue.name}")

    # -- Status ---------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        base = self._venue.health()
        base.update({
            "venue": self._venue.name,
            "mode_requested": settings.cex.mode,
            "gate_live_allowed": settings.cex.live_allowed,
            "last_error": self._last_error or self._venue._last_error,
            "open_orders": len(state.orders),
        })
        return base


cex_gateway = CexGateway()


def build_cex_executor(venue: Optional[VenueAdapter] = None) -> CexGateway:
    """Factory for the API / live-engine wiring."""
    return CexGateway(venue=venue)
