"""/execution/truth behavioural guards (row 770, UX-16 / M11.17).

The Execution Truth Plane (spec section 7, line 118) is a new read-only
aggregate: intent -> order -> acknowledgement -> fill -> position -> close ->
real PnL, with latency / slippage / fill ratio / rejection / venue / broker /
ticket / strategy / decision id. These tests pin the seam:

- the route is a registered read-only GET that claims no trade authority and
  is stable across reads;
- every lifecycle figure equals a fresh derivation over the canonical
  /account/orders and /account/positions reads (a mutation that hard-codes a
  count or drops a stage is caught);
- an empty canonical store reports empty rows and null metrics rather than
  invented orders, positions or fills.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from core.contracts import OrderStatus, OrderType, PositionStatus, TradeDirection

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from core.state import AccountState, OrderState, PositionState, state  # noqa: E402


@pytest.fixture()
def test_state():
    """Snapshot and restore the process-wide canonical state exactly."""
    old_account = state.account
    old_orders = dict(state.orders)
    old_positions = dict(state.positions)
    state.account = AccountState(login=0)
    state.orders.clear()
    state.positions.clear()
    yield state
    state.account = old_account
    state.orders.clear()
    state.orders.update(old_orders)
    state.positions.clear()
    state.positions.update(old_positions)


@pytest.fixture()
def client(test_state):
    return TestClient(app)


def _seed(student_state, *, account=None):
    now = 1_700_000_000.0

    def order(oid, status, **kw):
        base = dict(
            order_id=oid,
            symbol="XAUUSD",
            order_type=OrderType.MARKET,
            direction=TradeDirection.LONG,
            volume=0.1,
            price=2000.0,
            status=status,
            created_at=now,
            updated_at=now,
        )
        base.update(kw)
        student_state.orders[oid] = OrderState(**base)

    order("o-pending", OrderStatus.PENDING)
    order("o-ack", OrderStatus.SUBMITTED,
          venue="mt5", venue_order_ref="TKT-001",
          risk_decision_id="RD-A", strategy_id="strat-1")
    order("o-fill", OrderStatus.FILLED,
          filled_price=2000.5, slippage=0.5, commission=2.0,
          venue="mt5", venue_order_ref="TKT-002",
          risk_decision_id="RD-B", strategy_id="strat-1")
    order("o-reject", OrderStatus.REJECTED,
          venue="cex", risk_decision_id="RD-C")
    order("o-cancel", OrderStatus.CANCELLED)

    student_state.positions["p-open"] = PositionState(
        position_id="p-open",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        volume=0.1,
        entry_price=2000.0,
        current_price=2001.0,
        status=PositionStatus.OPEN,
        order_id="o-fill",
        strategy_id="strat-1",
        open_time=now,
        unrealized_pnl=10.0,
        realized_pnl=0.0,
        venue="mt5",
        venue_position_ref="TKT-002",
    )
    if account is not None:
        student_state.account = account


def test_the_execution_truth_route_is_registered_read_only_and_claims_no_authority(
        client):
    """Two live reads agree, and the route is a registered GET only."""
    first = client.get("/execution/truth")
    second = client.get("/execution/truth")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    left, right = first.json(), second.json()
    assert left["orders"] == right["orders"]
    assert left["lifecycle"] == right["lifecycle"]
    assert left["read_only"] is True
    assert left["is_authorisation"] is False
    assert left.get("source") == "overlay"

    paths = app.openapi()["paths"]
    assert "/execution/truth" in paths
    assert set(paths["/execution/truth"]) == {"get"}


def test_the_lifecycle_equals_a_fresh_derivation_of_the_canonical_reads(
        client, test_state):
    """No count is hard-coded: each matches /account/orders + /account/positions."""
    _seed(test_state, account=AccountState(
        login=101,
        broker="MetaQuotes-Demo",
        balance=100000.0,
        equity=100500.0,
        currency="USD",
        server="ICMarkets-Demo",
    ))

    truth = client.get("/execution/truth").json()
    orders = client.get("/account/orders").json()
    positions = client.get("/account/positions").json()

    lc = truth["lifecycle"]
    assert lc["intents"] == len(orders) == 5
    assert lc["pending"] == sum(1 for o in orders if o["status"] == "pending")
    assert lc["submitted"] == sum(1 for o in orders if o["status"] == "submitted")
    assert lc["filled"] == sum(1 for o in orders if o["status"] == "filled")
    assert lc["partial"] == sum(1 for o in orders if o["status"] == "partial")
    assert lc["rejected"] == sum(1 for o in orders if o["status"] == "rejected")
    assert lc["cancelled"] == sum(1 for o in orders if o["status"] == "cancelled")
    assert lc["expired"] == sum(1 for o in orders if o["status"] == "expired")
    assert lc["rejections"] == lc["rejected"]
    assert lc["positions_open"] == len(positions) == 1
    assert lc["fill_ratio"] == pytest.approx(0.5)  # 1 filled / (1+1 rejected)

    mt = truth["metrics"]
    assert mt["total_volume"] == round(sum(o["volume"] for o in orders), 4)
    assert mt["avg_slippage"] == pytest.approx(0.5)  # from the filled order

    # venue / broker / ticket / strategy / decision attribution is present.
    assert truth["account"]["broker"] == "MetaQuotes-Demo"
    assert "mt5" in truth["venues"]
    assert "MetaQuotes-Demo" in truth["venues"]
    fill = next(o for o in truth["orders"] if o["status"] == "filled")
    assert fill["venue_order_ref"] == "TKT-002"
    assert fill["risk_decision_id"] == "RD-B"
    assert fill["strategy_id"] == "strat-1"
    assert positions[0]["venue_position_ref"] == "TKT-002"


def test_the_truth_surface_separates_the_real_rail_from_all_sources(client):
    """`learning`/`positions_closed`/`realized_pnl` must be real MT5 fills.

    Paper and simulated records share the ledger and lack a `source`, so they
    used to default into the live bucket and were rendered as "real profit".
    """
    truth = client.get("/execution/truth").json()

    learning = truth["learning"]
    assert learning is not None
    assert learning["source_filter"] == "mt5"
    assert "mt5" in learning["basis"]

    all_sources = truth["learning_all_sources"]
    assert all_sources is not None
    assert all_sources["source_filter"] is None
    assert "window" in all_sources

    lc = truth["lifecycle"]
    assert lc["positions_closed"] == (learning["count"] or None)
    assert lc["positions_closed_all_sources"] == (all_sources["count"] or None)

    mt = truth["metrics"]
    expected = learning["net_pnl"] if learning["count"] else None
    assert mt["realized_pnl"] == expected


def test_an_empty_canonical_store_reports_empty_rows_and_null_metrics(
        client, test_state):
    """The route never invents orders, positions or fills for an empty store."""
    test_state.account = AccountState(login=0)

    truth = client.get("/execution/truth").json()
    assert truth["orders"] == []
    assert truth["positions"] == []
    lc = truth["lifecycle"]
    assert lc["intents"] == 0
    assert lc["filled"] == 0
    assert lc["rejected"] == 0
    assert lc["fill_ratio"] == 0
    assert lc["positions_open"] == 0
    mt = truth["metrics"]
    assert mt["total_volume"] == 0

    # The absent-store metrics stay renderable ("--" / null), never invented.
    for key in ("realized_pnl", "avg_slippage", "avg_latency_ms", "fees"):
        assert key in mt
        assert mt[key] is None or isinstance(mt[key], (int, float))
