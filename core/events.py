"""Event-driven architecture for TraderAIG.

Events flow between components through a central dispatch bus.
Each component subscribes to the events it cares about, keeping
the system decoupled and responsive only to meaningful changes.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Union

from .logging import get_logger


log = get_logger("core.events")


class EventType(str, Enum):
    # Market
    MARKET_DATA_UPDATED = "market.data_updated"
    REGIME_CHANGED = "market.regime_changed"

    # Research
    EVIDENCE_GATHERED = "research.evidence_gathered"
    SCHOOL_EVIDENCE = "research.school_evidence"
    SCHOOL_DELIBERATED = "research.school_deliberated"
    THESIS_CONSTRUCTED = "research.thesis_constructed"
    THESIS_INVALIDATED = "research.thesis_invalidated"

    # Decision
    CANDIDATE_SELECTED = "decision.candidate_selected"
    PORTFOLIO_UPDATED = "decision.portfolio_updated"

    # Risk
    RISK_DECISION_MADE = "risk.decision_made"
    RISK_VETO = "risk.veto"
    RISK_LIMIT_BREACH = "risk.limit_breach"
    SCHOOL_VETO = "decision.school_veto"
    POLICY_UPDATED = "learning.school_policy_updated"

    # Execution
    ORDER_SUBMITTED = "execution.order_submitted"
    ORDER_FILLED = "execution.order_filled"
    ORDER_REJECTED = "execution.order_rejected"
    POSITION_OPENED = "execution.position_opened"
    POSITION_CLOSED = "execution.position_closed"

    # Subscriptions / Governance
    SUBSCRIPTION_EXPIRED = "governance.subscription_expired"
    ENTITLEMENT_REVOKED = "governance.entitlement_revoked"
    USER_CREATED = "governance.user_created"

    # System
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    ERROR_DETECTED = "system.error"


@dataclass
class Event:
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None

    def __repr__(self) -> str:
        return f"Event({self.type.value}, src={self.source}, id={self.event_id[:8]})"


HandlerCB = Callable[[Event], Union[None, Awaitable[None]]]


class EventBus:
    """Central async event dispatch bus.

    Handlers can be sync or async. Async handlers are awaited; sync
    handlers are invoked on the caller thread. Fire-and-forget is
    supported via the `schedule_event` method that runs in the background.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[EventType, Set[HandlerCB]] = {}
        self._wildcard: Set[HandlerCB] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = asyncio.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, event_type: EventType, handler: HandlerCB) -> None:
        self._subscribers.setdefault(event_type, set()).add(handler)
        log.debug(f"Subscribed {handler.__qualname__} to {event_type.value}")

    def subscribe_all(self, handler: HandlerCB) -> None:
        """Subscribe to every event (e.g. audit trail / learning ledger)."""
        self._wildcard.add(handler)

    def unsubscribe(self, event_type: EventType, handler: HandlerCB) -> None:
        self._subscribers.get(event_type, set()).discard(handler)

    async def publish(self, event: Event) -> None:
        """Publish an event and await all its handlers."""
        handlers: List[HandlerCB] = list(self._subscribers.get(event.type, set()))
        handlers.extend(self._wildcard)

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception(f"Handler {handler.__qualname__} failed for {event}")

    def emit(self, event: Event) -> None:
        """Fire-and-forget publish from sync context.

        Uses the bound event loop if running, else runs synchronously
        by creating a temporary loop. Should be used from trading threads.
        """
        if self._loop and self._loop.is_running():
            self._loop.create_task(self.publish(event))
        else:
            asyncio.run(self.publish(event))


# Module-level singleton bus.
bus = EventBus()
