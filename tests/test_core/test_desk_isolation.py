"""Two account desks in one process must not share decision state.

The default `TradingLoop` still resolves the process singletons. These tests pin
the injected contract that a second account desk depends on: its own canonical
state, boards, screener, governor and ledger, and records that say which
account produced them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import TradeDirection  # noqa: E402
from core.pipeline import TradingLoop  # noqa: E402
from core.state import CanonicalState, MarketState  # noqa: E402
from decision.candidate import CandidateBoard  # noqa: E402
from decision.opportunity import OpportunityBoard, OpportunityEngine  # noqa: E402
from decision.thesis import TradeCandidate  # noqa: E402
from learning.experience import ExperienceLedger  # noqa: E402
from risk.governor import RiskDecision, RiskDecisionKind, RiskGovernor  # noqa: E402
from schools.board import SchoolBoard  # noqa: E402

ACCOUNT_A = "TEST-ACCT-A"
ACCOUNT_B = "TEST-ACCT-B"


def _desk(account_id: str, spread: float, price: float, tmp_path: Path):
    store = CanonicalState()
    store.upsert_market(MarketState(symbol="BTCUSD", bid=price, ask=price + spread,
                                    spread=spread, last_price=price,
                                    last_tick_time=1000.0))
    board = OpportunityBoard(path=tmp_path / f"{account_id}.json")
    loop = TradingLoop(
        "BTCUSD", enable_execution=False,
        state_ref=store,
        candidate_board_ref=CandidateBoard(),
        opportunity_board_ref=board,
        opportunity_engine_ref=OpportunityEngine(board=board),
        school_board_ref=SchoolBoard(),
        governor_ref=RiskGovernor(store),
        ledger_ref=ExperienceLedger(),
        account_id=account_id,
    )
    return store, loop


def _candidate(account_id: str) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=f"cand-{account_id}", thesis_id=f"thesis-{account_id}",
        symbol="BTCUSD", direction=TradeDirection.LONG, entry=100.0,
        stop_loss=99.0, take_profit=102.0, size=0.1, risk_reward=2.0,
        confidence=0.8)


def test_two_desks_keep_their_own_market_and_boards(tmp_path):
    store_a, loop_a = _desk(ACCOUNT_A, 1.0, 100.0, tmp_path)
    store_b, loop_b = _desk(ACCOUNT_B, 2.0, 200.0, tmp_path)

    assert loop_a._spread() == 1.0
    assert loop_b._spread() == 2.0
    assert loop_a._volume() == 100.0
    assert loop_b._volume() == 200.0

    assert loop_a._state is store_a and loop_b._state is store_b
    assert loop_a._candidates is not loop_b._candidates
    assert loop_a._opportunities is not loop_b._opportunities
    assert loop_a._schools is not loop_b._schools
    assert loop_a._governor is not loop_b._governor
    assert loop_a._ledger is not loop_b._ledger


def test_records_are_read_from_the_desks_own_market(tmp_path):
    _, loop_a = _desk(ACCOUNT_A, 1.0, 100.0, tmp_path)
    _, loop_b = _desk(ACCOUNT_B, 2.0, 200.0, tmp_path)
    decision = RiskDecision(decision_id="d", candidate_id="c",
                            kind=RiskDecisionKind.VETOED, reason="test")

    record_a = loop_a._decision_record(_candidate(ACCOUNT_A), decision)
    record_b = loop_b._decision_record(_candidate(ACCOUNT_B), decision)

    assert record_a.market_snapshot.bid == 100.0
    assert record_b.market_snapshot.bid == 200.0
    assert record_a.metadata["account_id"] == ACCOUNT_A
    assert record_b.metadata["account_id"] == ACCOUNT_B
