"""A refusal must say *who* refused: governance, the venue, or the transport.

The two real broker refusals this was built for are "Invalid stops" and
"Market closed". Both arrive after the risk layer approved the idea, so
filing them as a rejected idea (or as a connectivity problem) teaches the
system the wrong thing. The contract under test:

* the class is recorded on the order, the ticket, the opportunity and the
  decision record;
* a refused order is never written to the MT5 bridge, because that file is an
  instruction to the EA, not a log;
* a real fill still publishes to the bridge and still marks the opportunity
  executed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import execution.mt5_adapter as adapter_mod  # noqa: E402
from core.contracts import TradeDirection  # noqa: E402
from core.pipeline import TradingLoop  # noqa: E402
from core.rejection import (RejectionClass, RejectionReason,  # noqa: E402
                            VenueReason, classify_venue_error)
from core.state import CanonicalState, state  # noqa: E402
from decision.opportunity import Opportunity, OpportunityStatus  # noqa: E402
from execution.engine import ExecutionStatus, OrderTicket  # noqa: E402
from execution.mt5_adapter import LiveMT5Executor  # noqa: E402
from learning.experience import ErrorType, ledger  # noqa: E402
from risk.governor import RiskDecision, RiskDecisionKind  # noqa: E402

ACCOUNT = "TEST-ACCT-A"


def _make_fake_mt5():
    mt5 = SimpleNamespace()
    mt5.TRADE_ACTION_DEAL = 1
    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.ORDER_TIME_GTC = 0
    mt5.ORDER_FILLING_IOC = 1
    mt5.ORDER_FILLING_FOK = 0
    mt5.ORDER_FILLING_RETURN = 2
    mt5.ORDER_FILLING_BOC = 3
    mt5.TIMEFRAME_M1 = 1
    mt5.TIMEFRAME_M5 = 5
    mt5.TIMEFRAME_M15 = 15
    mt5.TIMEFRAME_H1 = 16385
    mt5.TRADE_RETCODE_DONE = 10009
    mt5.last_error = lambda: (10011, "no error")
    mt5.initialize = lambda **kw: True
    mt5.shutdown = lambda: None
    mt5.symbol_select = lambda sym, select: True
    mt5.terminal_info = lambda: SimpleNamespace(name="fake",
                                                trade_allowed=True,
                                                connected=True)
    return mt5


class _PermissiveGate:
    """A local gate that approves, so the venue is the only thing left to refuse."""

    def veto_reason(self, candidate, policy=None):
        return RiskDecision(decision_id="gate-1",
                            candidate_id=candidate.candidate_id,
                            kind=RiskDecisionKind.APPROVED, reason="ok")


# -- taxonomy --------------------------------------------------------------


def test_venue_messages_map_onto_venue_codes():
    assert classify_venue_error("Invalid stops") == VenueReason.INVALID_STOPS
    assert classify_venue_error("Market closed") == VenueReason.MARKET_CLOSED
    assert classify_venue_error("Not enough money") == VenueReason.INSUFFICIENT_FUNDS
    assert classify_venue_error("Requote") == VenueReason.REQUOTE
    assert classify_venue_error("something else entirely") == VenueReason.UNKNOWN


def test_transport_wording_beats_venue_wording():
    """A dead terminal never reached the broker: that is a transport failure."""
    assert RejectionReason.from_error(
        "MT5 terminal not reachable").rejection_class == RejectionClass.TRANSPORT
    assert RejectionReason.from_error(
        "Invalid stops").rejection_class == RejectionClass.VENUE_SEND


def test_rejection_serialises_class_code_and_reason():
    payload = RejectionReason.venue_send("Invalid stops").as_dict()
    assert payload["class"] == "venue_send"
    assert payload["code"] == "invalid_stops"
    assert payload["reason"] == "Invalid stops"


# -- executor --------------------------------------------------------------


class _RefusingAdapter:
    """A terminal that answers and refuses, like a broker with a min-stop rule."""

    connected = True

    def __init__(self, reason: str = "Invalid stops") -> None:
        self.reason = reason
        self._last_rejection: RejectionReason | None = None
        self._last_error = reason

    def _lazy_connect_if_possible(self) -> bool:
        return True

    def place_position(self, candidate, decision_kind):
        self._last_rejection = RejectionReason.venue_send(self.reason)
        return None

    def status(self):
        return {"last_error": self._last_error}

    def sync_positions(self):
        return []


class _UnreachableAdapter(_RefusingAdapter):
    def _lazy_connect_if_possible(self) -> bool:
        return False


def _candidate():
    from decision.thesis import TradeCandidate

    return TradeCandidate(
        candidate_id="cand-1", thesis_id="thesis-1", symbol="BTCUSD",
        direction=TradeDirection.LONG, entry=100.0, stop_loss=99.0,
        take_profit=102.0, size=0.1, risk_reward=2.0, confidence=0.8)


def _approved() -> RiskDecision:
    return RiskDecision(decision_id="d1", candidate_id="cand-1",
                        kind=RiskDecisionKind.APPROVED, reason="ok")


@pytest.fixture(autouse=True)
def _clean_state():
    store = CanonicalState()
    state.__dict__.clear()
    state.__dict__.update(store.__dict__)
    yield
    state.__dict__.clear()
    state.__dict__.update(store.__dict__)


def test_venue_refusal_lands_on_the_order_and_the_ticket():
    adapter = _RefusingAdapter("Invalid stops")
    executor = LiveMT5Executor(adapter, account_id=ACCOUNT)

    ticket = executor.execute(_candidate(), _approved())

    assert ticket is not None
    assert ticket.status == ExecutionStatus.REJECTED
    assert ticket.rejection_class == "venue_send"
    assert ticket.rejection_code == "invalid_stops"
    assert "Invalid stops" in ticket.note

    order = list(state.orders.values())[0]
    assert order.status.value == "rejected"
    assert order.rejection_class == "venue_send"
    assert order.rejection_code == "invalid_stops"
    assert order.rejection_reason == "Invalid stops"


def test_transport_failure_is_not_reported_as_a_venue_refusal():
    executor = LiveMT5Executor(_UnreachableAdapter(), account_id=ACCOUNT)

    ticket = executor.execute(_candidate(), _approved())

    assert ticket is not None
    assert ticket.status == ExecutionStatus.ERROR
    assert ticket.rejection_class == "transport"

    order = list(state.orders.values())[0]
    assert order.rejection_class == "transport"


def test_venue_refusal_is_filed_as_a_venue_error_in_the_ledger(monkeypatch):
    """The real adapter path: a broker that answers and refuses."""
    fake = _make_fake_mt5()
    fake.symbol_info = lambda sym: SimpleNamespace(volume_min=0.01,
                                                   volume_max=10.0,
                                                   trade_stops_level=0)
    fake.symbol_info_tick = lambda sym: SimpleNamespace(ask=100.5, bid=100.0)
    fake.order_send = lambda request: SimpleNamespace(
        retcode=10019, comment="Market closed", order=0, price=0.0)
    monkeypatch.setattr(adapter_mod, "_mt5", lambda: fake)

    adapter = adapter_mod.MT5Adapter()
    adapter._initialized = True
    monkeypatch.setattr(adapter, "_gate", _PermissiveGate())

    before = len(ledger.all())
    assert adapter.place_position(_candidate(), RiskDecisionKind.APPROVED) is None
    new_records = ledger.all()[before:]

    assert new_records, "the attempt must be recorded"
    record = new_records[-1]
    assert record.error_classification == ErrorType.VENUE_REJECTION
    assert record.actual_result["rejection_class"] == "venue_send"
    assert record.actual_result["rejection_code"] == "market_closed"
    assert record.actual_result["filled"] is False
    assert adapter.status()["last_rejection"]["class"] == "venue_send"


def test_each_attempt_of_the_same_candidate_gets_its_own_record():
    """A retry is a second event, not an overwrite of the first refusal."""
    adapter = adapter_mod.MT5Adapter()
    candidate = _candidate()

    adapter._record_execution(candidate, error="Market closed")
    adapter._record_execution(candidate, error="Market closed")

    mine = [r for r in ledger.all()
            if r.candidate_id == candidate.candidate_id
            and str(r.record_id).startswith("exec:")]
    assert len(mine) >= 2
    assert len({r.record_id for r in mine}) == len(mine)


# -- pipeline --------------------------------------------------------------


class _Board:
    """A durable board stand-in that remembers what was written to it."""

    def __init__(self, opportunities=None) -> None:
        self._items = list(opportunities or [])
        self.updated = []

    def ready_to_execute(self, symbol=None):
        return list(self._items)

    def update(self, opp):
        self.updated.append(opp)
        return opp


class _Governor:
    def veto_reason(self, candidate, policy=None, spread_ratio_limit=None):
        return _approved()


class _Executor:
    BRIDGE_PUBLISH = True

    def __init__(self, ticket) -> None:
        self.ticket = ticket
        self.executed = []

    def execute(self, candidate, decision):
        self.executed.append(candidate)
        return self.ticket


class _Ledger:
    def __init__(self) -> None:
        self.records = []

    def record(self, record):
        self.records.append(record)


def _opportunity() -> Opportunity:
    opp = Opportunity(
        opportunity_id="OPP-TEST-1", symbol="BTCUSD", direction="long",
        source="schools:institutional", session_key="s",
        thesis_id="thesis-1", candidate_id="cand-1",
        strategy_id="btcusd:ict_liquidity_sweep_reversal:v7",
        strategy_stage="paper", entry=100.0, stop_loss=99.0, take_profit=102.0,
        size=0.1, risk_reward=2.0, confidence=0.8, priority=90, score=90.0)
    opp.approve(note="operator approved")
    return opp


def _rejected_ticket() -> OrderTicket:
    ticket = OrderTicket("t1", "o1", ExecutionStatus.REJECTED,
                          note="venue_send: Invalid stops")
    ticket.rejection_class = "venue_send"
    ticket.rejection_code = "invalid_stops"
    return ticket


def _loop(executor, board, ledger_ref, monkeypatch) -> TradingLoop:
    published = []
    loop = TradingLoop("BTCUSD", enable_execution=True, executor=executor,
                       opportunity_board_ref=board, governor_ref=_Governor(),
                       ledger_ref=ledger_ref, account_id=ACCOUNT)
    monkeypatch.setattr(loop, "_publish_mt5_signal",
                        lambda candidate: published.append(candidate))
    loop._published = published  # type: ignore[attr-defined]
    return loop


def test_a_refused_order_never_reaches_the_bridge(monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")
    board = _Board([_opportunity()])
    ledger_ref = _Ledger()
    executor = _Executor(_rejected_ticket())
    loop = _loop(executor, board, ledger_ref, monkeypatch)

    loop._execute_approved_opportunities(
        [], context=SimpleNamespace(user_policy=None))

    assert len(executor.executed) == 1
    assert loop._published == [], "a refused order must not become an EA command"
    assert board.updated and board.updated[0].status == OpportunityStatus.REJECTED
    assert board.updated[0].evidence["rejection_class"] == "venue_send"
    assert board.updated[0].evidence["rejection_code"] == "invalid_stops"
    assert ledger_ref.records
    meta = ledger_ref.records[0].metadata
    assert meta["rejection_class"] == "venue_send"
    assert meta["filled"] is False


def test_a_real_fill_still_publishes_to_the_bridge(monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")
    board = _Board([_opportunity()])
    ledger_ref = _Ledger()
    ticket = OrderTicket("t2", "o2", ExecutionStatus.FILLED, note="filled")
    executor = _Executor(ticket)
    loop = _loop(executor, board, ledger_ref, monkeypatch)

    loop._execute_approved_opportunities(
        [], context=SimpleNamespace(user_policy=None))

    assert len(loop._published) == 1
    assert board.updated[0].history[-1]["status"] == "executed"
    assert ledger_ref.records[0].metadata["filled"] is True
