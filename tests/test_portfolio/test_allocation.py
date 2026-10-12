"""S4 Capital Allocation Engine tests (row 779).

The engine is advisory and read-only: it proposes cross-strategy weights from
the same realised-PnL series the correlation matrix uses, and it is honest when
there is not enough evidence to size anything.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from learning.experience import ExperienceLedger, ExperienceRecord
from portfolio.allocation import METHODS, PortfolioAllocationEngine
from portfolio.investment import CapitalAllocationBoard


def _record(sid, pnl, seq):
    return ExperienceRecord(
        record_id=f"{sid}-{seq}", decision_id="d", timestamp=float(seq),
        metadata={"strategy_id": sid},
        actual_result={"pnl": pnl},
    )


def _ledger(series_by_strategy):
    led = ExperienceLedger()
    seq = 0
    for sid, series in series_by_strategy.items():
        for pnl in series:
            led.record(_record(sid, pnl, seq))
            seq += 1
    return led


def _board(tmp_path, caps=None, allow_override=True):
    board = CapitalAllocationBoard(path=str(tmp_path / "alloc.json"))
    for sid, cap in (caps or {}).items():
        board.set_cap(sid, cap, allow_override=allow_override)
    return board


def test_methods_are_pinned():
    assert set(METHODS) == {"risk_parity", "equal_weight"}


def test_unknown_method_fails_closed():
    engine = PortfolioAllocationEngine()
    with pytest.raises(ValueError):
        engine.propose(method="magic")


def test_no_history_is_unavailable_and_invents_nothing():
    engine = PortfolioAllocationEngine(ledger_ref=ExperienceLedger())
    proposal = engine.propose().as_dict()
    assert proposal["status"] == "unavailable"
    assert proposal["weights"] == {}
    assert proposal["cash"] == 1.0
    assert proposal["universe"] == []


def test_insufficient_samples_are_not_sized():
    led = _ledger({"solo": [1.0, 2.0]})  # below MIN_SAMPLES
    engine = PortfolioAllocationEngine(ledger_ref=led)
    proposal = engine.propose().as_dict()
    assert proposal["status"] == "unavailable"
    assert proposal["weights"] == {}
    assert proposal["insufficient_data"] == ["solo"]


def test_risk_parity_favours_the_lower_volatility_strategy(tmp_path):
    led = _ledger({
        "calm": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],        # vol 0.5
        "wild": [10.0, -10.0, 10.0, -10.0, 10.0, -10.0],  # vol 10
    })
    board = _board(tmp_path, {"calm": 1.0, "wild": 1.0})
    proposal = PortfolioAllocationEngine(board=board, ledger_ref=led).propose().as_dict()
    assert proposal["status"] == "proposed"
    assert proposal["weights"]["calm"] > proposal["weights"]["wild"]
    assert proposal["weights"]["calm"] + proposal["weights"]["wild"] == pytest.approx(1.0, abs=1e-6)
    assert proposal["cash"] == pytest.approx(0.0, abs=1e-6)


def test_weights_never_exceed_a_strategy_cap_and_rest_is_cash(tmp_path):
    led = _ledger({
        "a": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        "b": [2.0, 0.0, 2.0, 0.0, 2.0, 0.0],
    })
    board = _board(tmp_path, {"a": 0.10, "b": 0.10})
    proposal = PortfolioAllocationEngine(board=board, ledger_ref=led).propose().as_dict()
    assert proposal["weights"]["a"] <= 0.10 + 1e-9
    assert proposal["weights"]["b"] <= 0.10 + 1e-9
    assert proposal["cash"] == pytest.approx(0.80, abs=1e-6)


def test_concentrated_pair_is_damped(tmp_path):
    led = _ledger({
        "x": [1.0, 2.0, 3.0, 4.0, 5.0],
        "y": [1.0, 2.0, 3.0, 4.0, 5.0],   # identical to x => concentrated
        "z": [10.0, 0.0, 10.0, 0.0, 10.0],  # not concentrated with x/y
    })
    board = _board(tmp_path, {"x": 1.0, "y": 1.0, "z": 1.0})
    proposal = PortfolioAllocationEngine(board=board, ledger_ref=led).propose().as_dict()
    detail = {row["strategy_id"]: row for row in proposal["detail"]}
    assert detail["x"]["correlation_penalty"] == 1
    assert detail["y"]["correlation_penalty"] == 1
    assert detail["z"]["correlation_penalty"] == 0
    # Damped: the concentrated participants end below their unpenalised base.
    assert proposal["weights"]["x"] < detail["x"]["base_weight"]


def test_equal_weight_method_is_available(tmp_path):
    led = _ledger({
        "a": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        "b": [10.0, -10.0, 10.0, -10.0, 10.0, -10.0],
    })
    board = _board(tmp_path, {"a": 1.0, "b": 1.0})
    proposal = PortfolioAllocationEngine(board=board, ledger_ref=led).propose(method="equal_weight").as_dict()
    assert proposal["method"] == "equal_weight"
    assert proposal["weights"]["a"] == pytest.approx(0.5, abs=1e-6)
    assert proposal["weights"]["b"] == pytest.approx(0.5, abs=1e-6)


def test_proposal_is_advisory_not_an_authorisation(tmp_path):
    led = _ledger({"a": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]})
    board = _board(tmp_path, {"a": 1.0})
    proposal = PortfolioAllocationEngine(board=board, ledger_ref=led).propose().as_dict()
    assert proposal["read_only"] is True
    assert proposal["is_authorisation"] is False
    assert proposal["trade_authority"] == "risk/governor.py"
