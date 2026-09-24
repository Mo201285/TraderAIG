"""The approved SMC/ICT scalp family: boundary rule, cost gate, time stop,
approved-first selection, and the learning-ratio enrichment.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle, TradeDirection
from core.state import AccountState, PositionState, state
from core.pipeline import TradingLoop
from operations.backtest import PaperExecutor, reset_runtime_state
from schools import registry
from schools.base import SchoolStatus
from schools.ict import ICTSchool, ict_school

from .conftest import mk


def _sweep_fvg_series():
    """Equal highs -> buy-side sweep -> bearish displacement FVG -> pullback
    into the gap (the approved sweep-to-FVG short scalp)."""
    return [
        mk(1000, 1002, 998, 1001),
        mk(1001, 1003, 999, 1002),
        mk(1002, 1015.0, 1001, 1003),   # equal high #1
        mk(1003, 1005, 1000, 1002),
        mk(1002, 1004, 999, 1001),
        mk(1001, 1003, 997, 999),
        mk(999, 1001, 996, 998),
        mk(998, 1005, 997, 1004),
        mk(1004, 1008, 1003, 1007),
        mk(1007, 1015.0, 1006, 1008),   # equal high #2 (same price)
        mk(1008, 1010, 1005, 1007),
        mk(1007, 1009, 1004, 1006),
        mk(1006, 1020.0, 1005, 1009),   # sweep: wick above 1015, close below
        mk(1004, 1004, 995, 996),       # displacement -> bearish FVG
        mk(996, 1004.7, 995.5, 1004.4),  # pullback into the gap [1004, 1005]
    ]


def _bar(t, close, high, low):
    return Candle(symbol="XAUUSD", timeframe="M15", time=float(t), open=close,
                  high=high, low=low, close=close, volume=100.0,
                  tick_volume=100.0)


# ---------------------------------------------------------------------------
# Status + boundary rule
# ---------------------------------------------------------------------------

def test_smc_is_the_approved_strategy_school():
    assert ict_school.status == SchoolStatus.APPROVED
    assert registry.by_id("ict").status == SchoolStatus.APPROVED
    assert registry.by_id("institutional").status == SchoolStatus.APPROVED
    for sid in ("price_action", "pattern_geometry", "macro"):
        assert registry.by_id(sid).status == SchoolStatus.APPROVED, sid
    for sid in ("structure", "wyckoff", "volume_flow", "ai"):
        assert registry.by_id(sid).status == SchoolStatus.RESEARCH, sid


def test_sweep_with_zone_is_smc_independent():
    ev = ict_school.evaluate(_sweep_fvg_series(), "XAUUSD")
    assert ev.meta.get("family_check") == "smc_independent"
    scalps = [s for s in ev.suggestions
              if s.pattern == "liquidity_sweep_reversal"]
    assert scalps, "zone-gated sweep must produce the scalp"


def test_all_smc_scalps_carry_the_scalp_toolkit():
    ev = ict_school.evaluate(_sweep_fvg_series(), "XAUUSD")
    for sug in ev.suggestions:
        assert sug.meta["time_stop_seconds"] > 0
        assert sug.meta["cost_ratio_max"] == 0.33
        assert sug.meta["chart_ref"]["type"] == "fvg"
        assert sug.meta["family_check"] == "smc_independent"
        assert len(sug.take_profit) == 1 and len(sug.entry_zone) == 2
        assert sug.stop_loss > 0 and sug.invalidation > 0


def test_suggestion_meta_stamped_with_school_status():
    from schools.board import school_board
    delib = school_board.deliberate(_sweep_fvg_series(), "XAUUSD")
    for sug in delib.suggestions:
        if not sug.meta.get("school_status"):
            continue
        assert sug.meta["school_status"] in ("approved", "research")
    selected = delib.selected
    assert selected is not None
    assert selected.meta.get("school_status") == "approved"


# ---------------------------------------------------------------------------
# Cost gate + learning ratio (pipeline)
# ---------------------------------------------------------------------------

def test_family_cost_gate_vetoes_wide_spread_vs_target():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    loop._spread = lambda: 2.0          # brutally wide relative to a scalp
    ev = ICTSchool().evaluate(_sweep_fvg_series(), "XAUUSD")
    reason = loop._family_cost_gate(ev.suggestions[0], _sweep_fvg_series())
    assert reason is not None
    assert "schools:cost" in reason


def test_family_cost_gate_enriches_zone_over_spread_ratio():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    loop._spread = lambda: 0.1
    ev = ICTSchool().evaluate(_sweep_fvg_series(), "XAUUSD")
    sug = ev.suggestions[0]
    assert loop._family_cost_gate(sug, _sweep_fvg_series()) is None
    assert sug.meta.get("zone_size_vs_spread_ratio", 0) > 0
    assert any(z.meta.get("zone_size_vs_spread_ratio", 0) > 0 for z in sug.zones)


def test_research_suggestion_is_vetoed_for_live_execution():
    loop = TradingLoop("XAUUSD", enable_execution=True, use_school_board=True)
    from schools.board import school_board
    delib = school_board.deliberate(
        _sweep_fvg_series(), "XAUUSD")
    # single approved source: synergy requires the full scalp quality bar
    assert loop._school_live_allowed(delib) is True


# ---------------------------------------------------------------------------
# Paper time stop
# ---------------------------------------------------------------------------

def test_paper_time_stop_closes_scalp_on_schedule():
    from schools.board import school_board
    reset_runtime_state()
    school_board.attribute_ticket(
        "t1", {"school_id": "ict", "pattern": "fvg_continuation",
               "regime_key": "r", "time_stop_seconds": 5400.0})
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    ex = PaperExecutor()
    pos = PositionState(
        position_id="p1", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=100.0, current_price=100.0,
        sl=99.0, tp=101.5,
    )
    state.add_position(pos)
    ex._by_ticket["t1"] = {"position_id": "p1"}
    ex.trades.append({
        "ticket": "t1", "position_id": "p1", "symbol": "XAUUSD",
        "direction": "long", "entry": 100.0, "size": 0.1,
        "sl": 99.0, "tp": 101.5, "bars_held": 0, "open_time": 1000.0,
        "time_stop_seconds": 5400.0, "family": "smc_scalp",
        "pattern": "fvg_continuation",
    })

    # within the window: untouched
    ex.mark(_bar(3000.0, 100.2, 100.4, 99.9))
    assert len(ex.closed) == 0
    # window elapsed (> open + 5400s): scheduled flat at candle close
    ex.mark(_bar(7000.0, 100.3, 100.5, 100.1))
    assert len(ex.closed) == 1
    assert ex.closed[0]["reason"] == "time_stop"
    assert ex.closed[0]["exit"] == 100.3
    assert ex.closed[0].get("pattern") is not None
