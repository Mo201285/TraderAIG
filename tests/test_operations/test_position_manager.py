"""Tests for the live position manager (breakeven + ladder partial close)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle, TradeDirection
from core.state import state
from operations.position_manager import PositionManager


def _candle(open_, high, low, close):
    return Candle(symbol="XAUUSD", timeframe="M15", time=1.0,
                  open=open_, high=high, low=low, close=close,
                  volume=100.0, tick_volume=100.0)


def _fresh_state():
    from core.state import CanonicalState
    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)


class _FakeAdapter:
    """Record the broker calls made by the manager."""

    def __init__(self):
        self.modify_calls = []
        self.partial_calls = []
        self.modify_ok = True
        self.partial_ok = True

    def modify_position(self, position_id, new_sl=None, new_tp=None):
        self.modify_calls.append((position_id, new_sl, new_tp))
        return self.modify_ok

    def close_partial(self, position_id, volume):
        self.partial_calls.append((position_id, volume))
        return self.partial_ok


class _FakeAttribution:
    def __init__(self, ladder=None):
        self.ladder = ladder or []

    def attribution_for(self, ticket):
        return {"ladder": self.ladder}


def _pos(position_id, direction=TradeDirection.LONG, entry=100.0,
         sl=99.0, tp=103.0, volume=0.2):
    from core.state import PositionState
    state.add_position(PositionState(
        position_id=position_id, symbol="XAUUSD", direction=direction,
        volume=volume, entry_price=entry, current_price=entry,
        sl=sl, tp=tp))


def test_manager_moves_stop_to_breakeven_live():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False)
    _pos("p1", entry=100.0, sl=99.0, tp=103.0)
    candle = _candle(100.2, 101.2, 100.1, 101.0)  # CLOSE >= entry + 1R
    mgr.tick({"XAUUSD": candle}, attribution=_FakeAttribution())
    assert adapter.modify_calls == [("p1", 100.0, None)]
    assert state.get_position("p1").sl == 100.0
    assert mgr._managed["p1"]["be_done"] is True


def test_manager_breakeven_not_triggered_early():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False)
    _pos("p1", entry=100.0, sl=99.0, tp=103.0)
    mgr.tick({"XAUUSD": _candle(100.1, 100.4, 99.9, 100.3)},
             attribution=_FakeAttribution())
    assert adapter.modify_calls == []
    assert state.get_position("p1").sl == 99.0


def test_manager_breakeven_short_direction():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False)
    _pos("p1", direction=TradeDirection.SHORT, entry=100.0, sl=101.0, tp=97.0)
    mgr.tick({"XAUUSD": _candle(99.8, 100.2, 99.0, 99.0)},
             attribution=_FakeAttribution())
    assert adapter.modify_calls == [("p1", 100.0, None)]


def test_manager_breakeven_paper_updates_state_only():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=True)
    _pos("p1", entry=100.0, sl=99.0, tp=103.0)
    mgr.tick({"XAUUSD": _candle(100.2, 101.2, 100.1, 101.0)},
             attribution=_FakeAttribution())
    assert adapter.modify_calls == []           # no broker call in paper
    assert state.get_position("p1").sl == 100.0


def test_manager_partial_close_at_ladder_tp2():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False)
    ladder = [{"price": 101.0, "source": "liquidity_pool"},
              {"price": 103.0, "source": "swing_high"}]
    _pos("p1", entry=100.0, sl=99.0, tp=103.0, volume=0.2)
    candle = _candle(102.9, 103.2, 102.8, 103.1)   # HIGH >= ladder[1] = 103
    mgr.tick({"XAUUSD": candle}, attribution=_FakeAttribution(ladder))
    # The manager delegates the fill to the broker adapter (which mutates
    # canonical volume); here we only assert the delegation.
    assert adapter.partial_calls == [("p1", 0.1)]
    assert mgr._managed["p1"]["tp2_done"] is True


def test_manager_paper_partial_books_daily_pnl():
    """E4 (appendix B): the paper TP2 partial uses the same settlement path as
    live, so the daily-loss guard sees the partial in paper accounts too."""
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=True)
    ladder = [{"price": 101.0, "source": "liquidity_pool"},
              {"price": 103.0, "source": "swing_high"}]
    _pos("p1", entry=100.0, sl=99.0, tp=103.0, volume=0.2)
    mgr.tick({"XAUUSD": _candle(102.9, 103.2, 102.8, 103.1)},
             attribution=_FakeAttribution(ladder))

    assert adapter.partial_calls == []  # paper never touches the venue
    pos = state.get_position("p1")
    assert pos.volume == pytest.approx(0.1)
    assert pos.realized_pnl == pytest.approx(0.3)   # (103-100)*0.1
    assert state.risk.daily_pnl == pytest.approx(0.3)  # guard sees the partial


def test_manager_tp2_requires_two_ladder_levels():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False)
    ladder = [{"price": 101.0, "source": "liquidity_pool"}]
    _pos("p1", entry=100.0, sl=99.0, tp=103.0, volume=0.2)
    mgr.tick({"XAUUSD": _candle(102.9, 104.0, 102.8, 103.1)},
             attribution=_FakeAttribution(ladder))
    assert adapter.partial_calls == []


def test_manager_ledger_survives_restart(tmp_path):
    _fresh_state()
    ledger = str(tmp_path / "position_manager.json")
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False, ledger_path=ledger)
    _pos("p1", entry=100.0, sl=99.0, tp=103.0, volume=0.2)
    mgr.tick({"XAUUSD": _candle(100.2, 101.2, 100.1, 101.0)},
             attribution=_FakeAttribution())
    assert adapter.modify_calls == [("p1", 100.0, None)]

    # Simulated process restart: fresh instance rehydrates from the ledger.
    adapter2 = _FakeAdapter()
    mgr2 = PositionManager(adapter=adapter2, paper=False, ledger_path=ledger)
    assert mgr2._managed["p1"]["be_done"] is True
    mgr2.tick({"XAUUSD": _candle(100.2, 101.2, 100.1, 101.0)},
              attribution=_FakeAttribution())
    assert adapter2.modify_calls == []


def test_manager_never_double_partials_after_restart(tmp_path):
    _fresh_state()
    ledger = str(tmp_path / "position_manager.json")
    ladder = [{"price": 101.0, "source": "liquidity_pool"},
              {"price": 103.0, "source": "swing_high"}]
    mgr = PositionManager(adapter=_FakeAdapter(), paper=False, ledger_path=ledger)
    _pos("p1", entry=100.0, sl=99.0, tp=103.0, volume=0.2)
    mgr.tick({"XAUUSD": _candle(102.9, 103.2, 102.8, 103.1)},
             attribution=_FakeAttribution(ladder))

    # Broker filled the partial: canonical volume shrank to the remainder.
    pos = state.get_position("p1")
    pos.volume = 0.1
    state.update_position(pos)

    # Restart: fresh manager would otherwise see tp2_done=False again.
    adapter2 = _FakeAdapter()
    mgr2 = PositionManager(adapter=adapter2, paper=False, ledger_path=ledger)
    mgr2.tick({"XAUUSD": _candle(102.9, 103.2, 102.8, 103.1)},
              attribution=_FakeAttribution(ladder))
    assert adapter2.partial_calls == []
    assert mgr2._managed["p1"]["tp2_done"] is True


def test_manager_recovers_breakeven_from_broker_sl():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False)
    _pos("p1", entry=100.0, sl=100.0, tp=103.0, volume=0.2)
    # SL already at entry (moved while offline) but candle never reached 1R.
    mgr.tick({"XAUUSD": _candle(100.2, 100.4, 100.1, 100.3)},
             attribution=_FakeAttribution())
    assert adapter.modify_calls == []
    assert mgr._managed["p1"]["be_done"] is True


def test_manager_derives_partial_done_from_volume_deficit():
    _fresh_state()
    adapter = _FakeAdapter()
    mgr = PositionManager(adapter=adapter, paper=False)
    ladder = [{"price": 101.0, "source": "liquidity_pool"},
              {"price": 103.0, "source": "swing_high"}]
    _pos("p1", entry=100.0, sl=99.0, tp=103.0, volume=0.2)
    mgr.tick({"XAUUSD": _candle(100.4, 100.6, 100.3, 100.5)},
             attribution=_FakeAttribution(ladder))
    assert "entry_volume" in mgr._managed["p1"]

    # Broker halved the size without consulting the manager (e.g. manual close).
    pos = state.get_position("p1")
    pos.volume = 0.1
    state.update_position(pos)

    mgr.tick({"XAUUSD": _candle(102.9, 103.2, 102.8, 103.1)},
             attribution=_FakeAttribution(ladder))
    assert adapter.partial_calls == []
    assert mgr._managed["p1"]["tp2_done"] is True


class _ManagementlessAdapter:
    """Venue adapter that can close the full position but NOT manage it
    (no modify_position / close_partial) - the CEX live contract gap (E2)."""

    def close_position(self, position_id, price):
        return True


def test_live_manager_survives_incomplete_adapter_contract():
    _fresh_state()
    mgr = PositionManager(adapter=_ManagementlessAdapter(), paper=False)
    _pos("p1", entry=100.0, sl=99.0, tp=103.0)
    mgr.tick({"XAUUSD": _candle(100.2, 101.2, 100.1, 101.0)},
             attribution=_FakeAttribution())
    # no AttributeError; breakeven rule recorded locally even though the
    # adapter cannot push the SL to the venue
    assert state.get_position("p1").sl == 100.0
    assert mgr._managed["p1"]["be_done"] is True


def test_live_manager_ladder_partial_survives_incomplete_adapter_contract():
    _fresh_state()
    mgr = PositionManager(adapter=_ManagementlessAdapter(), paper=False)
    _pos("p1", entry=100.0, sl=99.0, tp=110.0, volume=0.2)
    ladder = [{"price": 103.0}, {"price": 108.0}]
    mgr.tick({"XAUUSD": _candle(100.0, 109.0, 99.9, 108.5)},
             attribution=_FakeAttribution(ladder))
    # both management operations are skipped without crashing; the position
    # stays open and the manager remembers both rules fired
    assert state.get_position("p1") is not None
    assert state.get_position("p1").volume == 0.2
    assert mgr._managed["p1"]["be_done"] is True
    assert mgr._managed["p1"]["tp2_done"] is True
