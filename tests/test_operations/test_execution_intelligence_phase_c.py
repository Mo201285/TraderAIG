"""Phase C Execution Intelligence tests: per-venue execution truth (27.9/28.12).

The report measures the one thing internal intent cannot: the difference
between the price an order *meant* to get and the price it *actually* filled
at. It reports per venue, is honest when nothing has filled (measured: False,
slippage null), and never grants authority.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from core.config import settings
from core.contracts import OrderStatus, OrderType, TradeDirection
from core.state import AccountState, CanonicalState, OrderState
from execution.execution_truth import (
    ExecutionTruthReport,
    _adverse_slippage,
)
from execution.venue_score import MT5_VENUE


def make_state(broker="ICMarkets-Demo"):
    s = CanonicalState()
    s.set_account(AccountState(login=1, broker=broker,
                               balance=10_000.0, equity=10_000.0))
    return s


def add_order(s, venue, status, *, intended=2000.0, filled=None, sl=1990.0,
              direction=TradeDirection.LONG, commission=0.0, volume=0.1):
    oid = f"o{len(s.orders)}"
    s.orders[oid] = OrderState(
        order_id=oid, symbol="XAUUSD", order_type=OrderType.MARKET,
        direction=direction, volume=volume, price=intended, sl=sl, tp=None,
        status=status, venue=venue, filled_price=filled,
        commission=commission)
    return oid


# ---------------------------------------------------------------------------
# slippage measurement (the 27.9/28.12 core)
# ---------------------------------------------------------------------------

def test_long_fill_above_intent_is_adverse_positive():
    out = _adverse_slippage(2000.0, 2000.5, is_long=True, stop_distance=10.0)
    assert out["price"] == pytest.approx(0.5)
    assert out["r"] == pytest.approx(0.05)
    assert out["bps"] == pytest.approx(2.5)


def test_short_fill_below_intent_is_adverse_positive():
    out = _adverse_slippage(2000.0, 1999.5, is_long=False, stop_distance=10.0)
    assert out["price"] == pytest.approx(0.5)  # received less -> adverse


def test_favourable_fill_is_negative_slippage():
    out = _adverse_slippage(2000.0, 1999.8, is_long=True, stop_distance=10.0)
    assert out["price"] == pytest.approx(-0.2)


def test_no_stop_distance_has_no_r_but_still_measures_price():
    out = _adverse_slippage(2000.0, 2000.5, is_long=True, stop_distance=0.0)
    assert out["r"] is None and out["price"] == pytest.approx(0.5)


def test_unusable_prices_return_none():
    assert _adverse_slippage(None, 2000.0, is_long=True, stop_distance=1) is None
    assert _adverse_slippage(2000.0, None, is_long=True, stop_distance=1) is None
    assert _adverse_slippage(0.0, 2000.0, is_long=True, stop_distance=1) is None


# ---------------------------------------------------------------------------
# per-venue report
# ---------------------------------------------------------------------------

def test_report_measures_per_venue_and_lists_both_rails():
    s = make_state()
    add_order(s, "binance", OrderStatus.FILLED, intended=2000.0, filled=2000.05)
    add_order(s, "mt5", OrderStatus.FILLED, intended=2000.0, filled=2000.5)
    add_order(s, "mt5", OrderStatus.FILLED, intended=2000.0, filled=2000.3)
    out = ExecutionTruthReport(state_ref=s).report()
    venues = {v["venue"]: v for v in out["venues"]}
    assert MT5_VENUE in venues and settings.cex.venue in venues
    assert venues["mt5"]["measured"] is True
    assert venues["mt5"]["measured_fills"] == 2
    assert venues["mt5"]["avg_slippage_price"] == pytest.approx(0.4)
    assert venues["binance"]["avg_slippage_price"] == pytest.approx(0.05)
    assert out["measured_slippage"] is True
    assert out["read_only"] is True and out["is_authorisation"] is False
    assert out["trade_authority"] == "risk/governor.py"


def test_report_is_honest_when_nothing_filled():
    s = make_state()
    add_order(s, "mt5", OrderStatus.REJECTED)
    add_order(s, "mt5", OrderStatus.CANCELLED)
    out = ExecutionTruthReport(state_ref=s).report()
    venues = {v["venue"]: v for v in out["venues"]}
    # rejected/cancelled carry no fill -> unmeasured, not a zero slippage
    assert venues["mt5"]["measured"] is False
    assert venues["mt5"]["avg_slippage_price"] is None
    assert out["measured_slippage"] is False
    assert out["platform"] is None
    assert "not measured" in out["note"]


def test_filled_without_filled_price_is_not_measured():
    s = make_state()
    add_order(s, "mt5", OrderStatus.FILLED, intended=2000.0, filled=None)
    out = ExecutionTruthReport(state_ref=s).report()
    venues = {v["venue"]: v for v in out["venues"]}
    assert venues["mt5"]["filled"] == 1
    assert venues["mt5"]["measured"] is False


def test_unattributed_orders_counted_not_folded():
    s = make_state()
    add_order(s, "", OrderStatus.FILLED, intended=2000.0, filled=2000.2)
    out = ExecutionTruthReport(state_ref=s).report()
    assert out["unattributed_orders"] == 1
    assert out["measured_slippage"] is False


def test_platform_rolls_up_measured_fills():
    s = make_state()
    add_order(s, "mt5", OrderStatus.FILLED, intended=2000.0, filled=2000.5)
    add_order(s, "binance", OrderStatus.FILLED, intended=2000.0, filled=2000.1)
    out = ExecutionTruthReport(state_ref=s).report()
    assert out["platform"]["measured_fills"] == 2
    assert out["platform"]["avg_slippage_price"] == pytest.approx(0.3)


def test_empty_state_reports_unmeasured_and_invents_nothing():
    out = ExecutionTruthReport(state_ref=make_state()).report()
    assert out["measured_slippage"] is False
    assert out["platform"] is None
    assert all(v["measured"] is False for v in out["venues"])


# ---------------------------------------------------------------------------
# route + console
# ---------------------------------------------------------------------------

def test_route_registered_and_get_only():
    from fastapi.testclient import TestClient
    import operations.api as api
    paths = api.app.openapi()["paths"]
    assert "/execution/truth-by-venue" in paths
    assert set(paths["/execution/truth-by-venue"].keys()) == {"get"}
    client = TestClient(api.app)
    r = client.get("/execution/truth-by-venue")
    assert r.status_code == 200
    body = r.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False


def test_console_execution_command_registered():
    import tools.tradraig as console
    args = console._parser().parse_args(["execution", "truth"])
    assert args.fn is console.cmd_execution
    for act in ("truth", "recon", "venue-score"):
        parsed = console._parser().parse_args(["execution", act])
        assert parsed.action == act
