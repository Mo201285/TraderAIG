"""Portfolio Intelligence & Capital Allocation tests (Phase A)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from core.contracts import TradeDirection
from core.state import AccountState, CanonicalState, MarketState, PositionState
from decision.candidate import TradeCandidate
from learning.experience import ExperienceLedger, ExperienceRecord
from portfolio.correlation import strategy_correlation
from portfolio.investment import (
    INSTITUTIONAL_STRATEGY_CAP,
    CapitalAllocationBoard,
    PortfolioIntelligence,
)
from risk.governor import RiskDecisionKind, RiskGovernor


def make_state(equity: float = 10000.0):
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=equity, equity=equity))
    s.upsert_market(MarketState(symbol="BTCUSD", bid=60000.0, ask=60001.0,
                                spread=1.0, last_price=60000.5,
                                last_tick_time=1.0, tick_size=0.01,
                                tick_value=1.0, volume_min=0.01,
                                volume_step=0.01, volume_max=100.0))
    s.upsert_market(MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5,
                                spread=0.5, last_price=2000.25, last_tick_time=1.0,
                                tick_size=0.01, tick_value=1.0,
                                volume_min=0.01, volume_step=0.01, volume_max=100.0))
    return s


def open_position(s, symbol, direction, volume, price, strategy_id=None):
    pos = PositionState(
        position_id=f"p{len(s.positions) + 1}",
        symbol=symbol,
        direction=direction,
        volume=volume,
        entry_price=price,
        current_price=price,
        strategy_id=strategy_id,
    )
    s.add_position(pos)
    return pos


def make_candidate(strategy_id=None, size=0.1):
    return TradeCandidate(
        candidate_id="c1", thesis_id="t1", symbol="BTCUSD",
        direction=TradeDirection.LONG, entry=60000.0, stop_loss=59000.0,
        take_profit=63000.0, size=size, risk_reward=2.0, confidence=0.8,
        strategy_id=strategy_id,
        strategy_stage="production" if strategy_id else None,
    )


def make_board(tmp_path, caps=None, allow_override=False):
    board = CapitalAllocationBoard(path=str(tmp_path / "alloc.json"))
    for sid, cap in (caps or {}).items():
        board.set_cap(sid, cap, allow_override=allow_override)
    return board


def test_snapshot_aggregates_gross_net_long_short():
    s = make_state()
    open_position(s, "BTCUSD", TradeDirection.LONG, 1.0, 60000.0,
                  strategy_id="s1")
    open_position(s, "BTCUSD", TradeDirection.SHORT, 0.5, 60000.0,
                  strategy_id="s2")
    open_position(s, "XAUUSD", TradeDirection.LONG, 2.0, 2000.0,
                  strategy_id="s1")
    snap = PortfolioIntelligence(s).snapshot()

    assert snap.gross_exposure == pytest.approx(60000 + 30000 + 4000)
    assert snap.net_exposure == pytest.approx(60000 - 30000 + 4000)
    assert snap.long_exposure == pytest.approx(60000 + 4000)
    assert snap.short_exposure == pytest.approx(30000)
    assert snap.open_positions == 3
    assert snap.by_strategy["s1"]["gross"] == pytest.approx(64000)
    assert snap.by_strategy["s2"]["gross"] == pytest.approx(30000)
    assert snap.by_strategy["s2"]["net"] == pytest.approx(-30000)
    assert snap.concentration_top_symbol == "BTCUSD"
    assert round(snap.concentration_top_share, 3) == pytest.approx(0.957)


def test_snapshot_unattributed_positions_are_not_dropped():
    s = make_state()
    open_position(s, "BTCUSD", TradeDirection.LONG, 1.0, 60000.0)
    snap = PortfolioIntelligence(s).snapshot()
    assert "unattributed" in snap.by_strategy
    assert snap.by_strategy["unattributed"]["gross"] == pytest.approx(60000)


def test_snapshot_ignores_closed_positions():
    s = make_state()
    p = open_position(s, "BTCUSD", TradeDirection.LONG, 1.0, 60000.0,
                      strategy_id="s1")
    s.close_position(p.position_id, 61000.0)
    snap = PortfolioIntelligence(s).snapshot()
    assert snap.open_positions == 0
    assert snap.gross_exposure == 0.0
    assert snap.by_strategy == {}


def test_allocation_gate_blocks_strategy_above_explicit_cap(tmp_path):
    s = make_state(equity=10000.0)
    board = make_board(tmp_path, {"s1": 0.15})
    open_position(s, "BTCUSD", TradeDirection.LONG, 0.02, 60000.0,
                  strategy_id="s1")  # 1200 => 12% consumed
    gate = _gate_with(s, board)
    # candidate notional = 60000*0.1 = 6000 => +60% => 72% > 15% cap.
    decision = gate.decide_candidate(make_candidate(strategy_id="s1"))
    assert decision.ok is False
    assert "budget" in decision.reason


def test_allocation_gate_passes_within_budget(tmp_path):
    s = make_state(equity=10000.0)
    board = make_board(tmp_path, {"s1": 0.70}, allow_override=True)
    open_position(s, "BTCUSD", TradeDirection.LONG, 0.01, 60000.0,
                  strategy_id="s1")  # 600 => 6% consumed
    gate = _gate_with(s, board)
    # candidate notional = 60000*0.1 = 6000 => +60% => 66% <= 70% cap.
    decision = gate.decide_candidate(make_candidate(strategy_id="s1"))
    assert decision.ok is True


def _gate_with(state_ref, board):
    from portfolio.investment import AllocationGate
    return AllocationGate(state_ref=state_ref, board=board)


def test_board_set_cap_clamps_to_institutional_default(tmp_path):
    board = CapitalAllocationBoard(path=str(tmp_path / "alloc.json"))
    stored = board.set_cap("s1", 0.90)
    assert stored == INSTITUTIONAL_STRATEGY_CAP
    stored = board.set_cap("s2", 0.10, allow_override=True)
    assert stored == pytest.approx(0.10)
    assert board.cap_for("s1") == INSTITUTIONAL_STRATEGY_CAP
    assert board.clear_cap("s1") is True
    assert board.has_cap("s1") is False


def test_governor_allocation_gate_is_hard_when_cap_set(tmp_path, monkeypatch):
    s = make_state(equity=10000.0)
    board = make_board(tmp_path, {"s1": 0.10})
    open_position(s, "BTCUSD", TradeDirection.LONG, 0.01, 60000.0,
                  strategy_id="s1")  # 600 => 6%
    import portfolio.investment as pmod
    monkeypatch.setattr(pmod, "allocation_board", board)
    monkeypatch.setattr(pmod, "allocation_gate", _gate_with(s, board))

    g = RiskGovernor(s)
    d = g.veto_reason(make_candidate(strategy_id="s1"))
    # 6% used + ~600 proposed (+6%) = ~12% > 10% cap => veto.
    assert d.kind == RiskDecisionKind.VETOED
    alloc_check = next(c for c in d.checks if c["name"] == "portfolio_allocation")
    assert alloc_check["passed"] is False


def test_governor_allocation_gate_pass_without_explicit_cap(tmp_path, monkeypatch):
    s = make_state(equity=10000.0)
    board = CapitalAllocationBoard(path=str(tmp_path / "alloc.json"))
    import portfolio.investment as pmod
    monkeypatch.setattr(pmod, "allocation_board", board)
    monkeypatch.setattr(pmod, "allocation_gate", _gate_with(s, board))

    g = RiskGovernor(s)
    d = g.veto_reason(make_candidate(strategy_id="s1"))
    assert d.kind == RiskDecisionKind.APPROVED
    alloc_check = next(c for c in d.checks if c["name"] == "portfolio_allocation")
    assert alloc_check["passed"] is True
    assert alloc_check["active"] is False


def test_governor_allocation_gate_ignores_candidates_without_strategy():
    s = make_state(equity=10000.0)
    g = RiskGovernor(s)
    d = g.veto_reason(make_candidate())
    assert d.kind == RiskDecisionKind.APPROVED


def _record(sid, pnl, seq):
    return ExperienceRecord(
        record_id=f"{sid}-{seq}", decision_id="d", timestamp=float(seq),
        metadata={"strategy_id": sid},
        actual_result={"pnl": pnl},
    )


def test_correlation_tracks_diversifying_pairs():
    led = ExperienceLedger()
    for i in range(3):
        led.record(_record("a", 10.0 * (i + 1), 2 * i))
        led.record(_record("b", -10.0 * (i + 1), 2 * i + 1))
    result = strategy_correlation(ledger_ref=led)
    pairs = result["pairs"]
    assert len(pairs) == 1
    assert pairs[0]["a"] == "a" and pairs[0]["b"] == "b"
    assert pairs[0]["diversifying"] is True
    assert pairs[0]["concentrated"] is False
    assert pairs[0]["correlation"] == pytest.approx(-1.0)
    assert pairs[0]["samples"] == 3


def test_correlation_flags_concentrated_pair():
    led = ExperienceLedger()
    for i in range(5):
        led.record(_record("x", float(i), i))
        led.record(_record("y", float(i), i))
    result = strategy_correlation(ledger_ref=led)
    pairs = result["pairs"]
    assert pairs[0]["concentrated"] is True
    assert pairs[0]["correlation"] == pytest.approx(1.0)


def test_correlation_reports_insufficient_data_honestly():
    led = ExperienceLedger()
    led.record(_record("z", 5.0, 1))
    led.record(_record("w", 5.0, 2))
    result = strategy_correlation(ledger_ref=led)
    assert result["pairs"] == []
    assert "z" in result["insufficient_data"]
    assert "w" in result["insufficient_data"]


def test_empty_ledger_correlation_no_crash():
    led = ExperienceLedger()
    result = strategy_correlation(ledger_ref=led)
    assert result["pairs"] == []
    assert result["strategies_tracked"] == 0
