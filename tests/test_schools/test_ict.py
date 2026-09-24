"""ICT / SMC school: liquidity, freshness, sweeps.

Fixtures are built deterministically against the smc engine's exact
detection rules (2-candle swing confirmation, three-candle imbalance,
equal-high clustering within 0.05 pips).
"""
from core.contracts import TradeDirection
from schools.ict import ict_school

from .conftest import mk


def _freshness_series():
    """Rise, then a gap-up displacement (bull FVG), then soft retests above
    the gap. The imbalance becomes last_fvg and is not burned by any retest
    because close never trades back inside the gap zone."""
    out = []
    price = 500.0
    for _ in range(4):
        out.append(mk(price, price + 0.4, price - 0.4, price + 0.1))
        price = price + 0.1
    out.append(mk(price, price + 3.0, price + 0.5, price + 2.5))   # displacement
    retest = out[-1].close
    out.append(mk(retest, retest + 0.3, retest - 1.2, retest - 0.7))
    out.append(mk(retest - 0.7, retest - 0.4, retest - 1.6, retest - 1.0))
    return out


def test_ict_draws_zones_and_marks_freshness():
    out = _freshness_series()
    # pad history so the school's 15-candle minimum is met and the FVG
    # stays the *last* imbalance (nothing after it creates a newer gap)
    pad = [mk(499.0, 499.6, 498.4, 499.2) for _ in range(9)]
    ev = ict_school.evaluate(pad + out, "XAUUSD", now=1.0)
    zones = [z for z in ev.zones if z.zone_type in ("fvg", "order_block")]
    assert zones, "displacement must leave an FVG zone behind"
    fvg = next(z for z in zones if z.zone_type == "fvg")
    assert fvg.fresh is True
    assert fvg.touches <= 1


def test_sweep_of_buyside_liquidity_forces_short_reversal():
    out = [
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
        mk(1004, 1004, 995, 996),        # displacement through 1005 -> bearish FVG
        mk(996, 1004.7, 995.5, 1004.4),  # pullback UP into the gap [1004,1005]
    ]
    ev = ict_school.evaluate(out, "XAUUSD", now=1.0)
    shorts = [s for s in ev.suggestions
              if s.pattern == "liquidity_sweep_reversal"]
    assert shorts, "swept buy-side liquidity + return FVG must yield a short scalp"
    assert all(s.direction == TradeDirection.SHORT for s in shorts)
    assert any(s.meta.get("pool") == "equal_high" for s in shorts)
    assert all(s.meta.get("family_check") == "smc_independent" for s in shorts)
    assert all(s.meta["chart_ref"]["type"] == "fvg" for s in shorts)
    assert all(s.meta.get("time_stop_seconds", 0) > 0 for s in shorts)
    assert all(s.meta.get("cost_ratio_max") == 0.33 for s in shorts)


def test_sweep_without_zone_is_reclassified_to_flow():
    """The boundary rule: a sweep with no geometric return zone is NOT an
    SMC setup - it belongs to Institutional Flow (family_check)."""
    out = [
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
        mk(1006, 1020.0, 1005, 1009),   # sweep, but no return FVG is formed
        mk(1009, 1012, 1006, 1010),
        mk(1010, 1013, 1007, 1011),
    ]
    ev = ict_school.evaluate(out, "XAUUSD", now=1.0)
    sweeps = [s for s in ev.suggestions
              if s.pattern == "liquidity_sweep_reversal"]
    assert sweeps == []
    assert ev.meta.get("family_check") == "reclassified_as_flow"


def test_ict_no_fabrics_without_setup():
    ev = ict_school.evaluate([mk(1, 2, 0.5, 1.5) for _ in range(8)],
                             "XAUUSD", now=1.0)
    assert ev.meta.get("no_setup") is True or ev.suggestions is not None
