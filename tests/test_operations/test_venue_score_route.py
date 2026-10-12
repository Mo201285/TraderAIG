"""S5 venue-score route over the real app (row 780).

The read-only surface: it resolves through the canonical state, advertises
itself as advisory (not an authorisation), lists both execution rails and
recommends the best-scoring venue only from real evidence.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import OrderStatus, OrderType, TradeDirection  # noqa: E402
from core.state import AccountState, OrderState, state  # noqa: E402
from operations.api import app  # noqa: E402


@pytest.fixture()
def test_state():
    old_account = state.account
    old_orders = dict(state.orders)
    state.account = AccountState(login=0)
    state.orders.clear()
    yield state
    state.account = old_account
    state.orders.clear()
    state.orders.update(old_orders)


@pytest.fixture()
def client(test_state):
    return TestClient(app)


def _order(s, oid, status, venue, slippage=0.0):
    s.orders[oid] = OrderState(
        order_id=oid, symbol="XAUUSD", order_type=OrderType.MARKET,
        direction=TradeDirection.LONG, volume=0.1, price=2000.0,
        status=status, venue=venue, slippage=slippage)


def test_route_is_registered_read_only_and_advisory(client):
    res = client.get("/execution/venue-score")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    assert body["recommended"] is None

    paths = app.openapi()["paths"]
    assert "/execution/venue-score" in paths
    assert set(paths["/execution/venue-score"]) == {"get"}


def test_route_recommends_from_real_evidence(client, test_state):
    for i in range(4):
        _order(test_state, f"b{i}", OrderStatus.FILLED, "binance", slippage=0.1)
    _order(test_state, "b-rej", OrderStatus.REJECTED, "binance")
    for i in range(4):
        _order(test_state, f"m{i}", OrderStatus.FILLED, "mt5", slippage=5.0)
    _order(test_state, "m-rej", OrderStatus.REJECTED, "mt5")

    body = client.get("/execution/venue-score").json()
    venues = {v["venue"]: v for v in body["venues"]}
    assert venues["binance"]["scored"] is True
    assert body["recommended"] == "binance"
