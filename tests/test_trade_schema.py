"""Tests for the venue-neutral trade schema.

Grouped by the property under test rather than by class, because the properties
are the reason the schema exists:

* nothing is lost  -- a legitimate zero survives a round trip
* nothing is invented -- an unreported value is absent, not defaulted
* nothing is duplicated -- re-ingesting a fill does not double history
* nothing leaks -- a read cannot cross an account boundary
* nothing is unreachable from history -- a restart can rebuild from rows

The "nothing is invented" group is the important one. Every failure there would
look like a *correct* number, which is why each has a test that fails loudly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.normalize import (  # noqa: E402
    build_round_trip,
    canonical_order_status,
    canonical_order_type,
    canonical_position_status,
    canonical_side,
    normalize_deal,
    normalize_order,
    normalize_position,
    unmapped_venue_fields,
)
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_trades import (  # noqa: E402
    RoundTripRecord,
    TradeCycleRecord,
    TradeDealRecord,
    TradeOrderRecord,
    TradePositionRecord,
)
from persistence.repositories_trades import (  # noqa: E402
    RoundTripRepository,
    TradeCycleRepository,
    TradeDealRepository,
    TradeOrderRepository,
    TradePositionRepository,
    cycle_from_round_trips,
)


ACCOUNT = "acct-1"
OTHER = "acct-2"


@pytest.fixture
def session():
    s = bind_test_session()
    from sqlalchemy import delete

    for model in (TradeCycleRecord, RoundTripRecord, TradePositionRecord,
                  TradeDealRecord, TradeOrderRecord):
        s.execute(delete(model))
    s.commit()
    return s


@pytest.fixture
def orders(session):
    return TradeOrderRepository(session)


@pytest.fixture
def deals(session):
    return TradeDealRepository(session)


@pytest.fixture
def positions(session):
    return TradePositionRepository(session)


@pytest.fixture
def round_trips(session):
    return RoundTripRepository(session)


# -- schema ---------------------------------------------------------------


def test_trade_tables_exist():
    from sqlalchemy import inspect

    s = bind_test_session()
    tables = set(inspect(s.get_bind()).get_table_names())
    for expected in ("orders", "deals", "positions", "round_trips",
                     "trade_cycles"):
        assert expected in tables


def test_trade_tables_carry_no_foreign_keys():
    def fks(model):
        return [c.name for c in model.__table__.columns if list(c.foreign_keys)]

    for model in (TradeOrderRecord, TradeDealRecord, TradePositionRecord,
                  RoundTripRecord, TradeCycleRecord):
        assert fks(model) == []


# -- nothing is lost ------------------------------------------------------


def test_a_real_zero_survives_the_round_trip(orders):
    """Zero is a measurement. A truthiness filter turns it into NULL."""
    row = orders.save_order(dict(
        order_id="o1", account_id=ACCOUNT, venue="mt5", symbol="EURUSD",
        side="buy", order_type="market", status="filled",
        requested_qty=0.0, filled_qty=0.0, fee_amount=0.0,
        avg_fill_price=1.0850))
    assert row["requested_qty"] == 0.0
    assert row["fee_amount"] == 0.0
    assert row["avg_fill_price"] == 1.0850
    assert orders.get_order(ACCOUNT, "o1")["requested_qty"] == 0.0


def test_breakeven_round_trip_is_breakeven_not_missing(round_trips):
    saved = round_trips.save_round_trip(dict(
        round_trip_id="rt1", account_id=ACCOUNT, venue="mt5", symbol="EURUSD",
        side="buy", opened_at=100.0, closed_at=200.0, net_pnl=0.0,
        gross_pnl=0.0, quantity=0.1))
    assert saved["outcome"] == "breakeven"
    assert saved["net_pnl"] == 0.0


def test_partial_close_pnl_accumulates_rather_than_overwrites(positions):
    """Realized P&L is a running total, not a snapshot.

    Replacing it with the latest partial close is the same bug class as a
    regenerated challenge baseline: a restart or a resync loses history.
    """
    positions.save_position(dict(
        position_id="p1", account_id=ACCOUNT, venue="mt5", symbol="EURUSD",
        side="buy", status="open", realized_pnl=40.0))
    positions.save_position(dict(
        position_id="p1", account_id=ACCOUNT, venue="mt5", symbol="EURUSD",
        side="buy", status="open", realized_pnl=65.0))
    assert positions.list_positions(ACCOUNT)[0]["realized_pnl"] == 65.0


# -- nothing is invented --------------------------------------------------


def test_an_unreported_fee_is_absent_not_zero(orders):
    row = orders.save_order(dict(
        order_id="o2", account_id=ACCOUNT, venue="okx", symbol="BTC/USDT",
        side="buy", order_type="market", status="pending"))
    assert row["fee_amount"] is None


def test_a_venue_that_reports_no_pnl_does_not_get_zero(deals):
    row = deals.append_deal(dict(
        deal_id="d1", account_id=ACCOUNT, venue="okx", venue_deal_ref="55",
        symbol="BTC/USDT", side="buy", deal_kind="entry", qty=0.5, price=60.0))
    assert row["pnl"] is None


def test_unreported_excursion_stays_unknown(round_trips):
    saved = round_trips.save_round_trip(dict(
        round_trip_id="rt2", account_id=ACCOUNT, venue="mt5", symbol="X",
        side="buy", opened_at=1.0, closed_at=2.0, net_pnl=10.0))
    assert saved["mae"] is None
    assert saved["mfe"] is None


def test_unrecognised_side_is_not_guessed_to_flat():
    """Defaulting to FLAT removes a live exposure from every risk check."""
    assert canonical_side("long-ish") is None
    assert canonical_side("") is None


def test_unrecognised_status_is_not_a_confident_pending():
    assert canonical_order_status("queued-somehow") is None
    assert canonical_order_type("iceberg") is None
    assert canonical_position_status("draining") is None


def test_a_boolean_is_not_a_quantity():
    """`True` is a valid float in Python and a meaningless order size."""
    row = normalize_deal({"volume": True}, venue="okx", account_id=ACCOUNT)
    assert row["qty"] is None


def test_a_venue_alias_reporting_zero_is_not_read_as_absent():
    """`raw.get("qty") or raw.get("volume")` is not "prefer qty, else volume".

    Zero is a value these venues really do report: an order cancelled before it
    filled, a position closed flat, a deal booked at no fee. Truthiness sends
    those rows past the alias they came in on and lands on `None` -- the absence
    of a measurement -- so every breakeven trade reads as unpriced and every
    zero-fee deal reads as one whose fee was never disclosed.
    """
    order = normalize_order({"side": "buy", "qty": 0.0, "price": 0.0,
                             "filled_qty": 0.0, "filled_price": 0.0,
                             "commission": 0.0, "stop_price": 0.0},
                            venue="okx", account_id=ACCOUNT, order_id="o1")
    assert order["requested_qty"] == 0.0
    assert order["limit_price"] == 0.0
    assert order["filled_qty"] == 0.0
    assert order["avg_fill_price"] == 0.0
    assert order["fee_amount"] == 0.0
    assert order["stop_price"] == 0.0

    deal = normalize_deal({"side": "buy", "qty": 0.0, "price": 0.0,
                           "fee": 0.0, "pnl": 0.0},
                          venue="okx", account_id=ACCOUNT, deal_id="d1")
    assert (deal["qty"], deal["price"], deal["fee"], deal["pnl"]) == (
        0.0, 0.0, 0.0, 0.0)

    position = normalize_position({"side": "buy", "volume": 0.0,
                                   "entry_price": 0.0,
                                   "unrealized_pnl": 0.0,
                                   "realized_pnl": 0.0},
                                  venue="okx", account_id=ACCOUNT,
                                  position_id="p1")
    assert (position["volume"], position["entry_price"],
            position["unrealized_pnl"], position["realized_pnl"]) == (
        0.0, 0.0, 0.0, 0.0)


def test_an_absent_measurement_is_still_absent_after_the_alias_fix():
    """The other half: fixing zero must not invent a value either."""
    order = normalize_order({"side": "buy"}, venue="okx",
                            account_id=ACCOUNT, order_id="o1")
    assert order["requested_qty"] is None
    assert order["limit_price"] is None
    assert order["avg_fill_price"] is None
    assert order["fee_amount"] is None


def test_a_zero_quantity_leg_does_not_inherit_the_other_legs_size():
    """A zero-quantity fill is reported, not replaced by its counterparty."""
    trip = build_round_trip(
        normalize_deal({"side": "buy", "qty": 0.0, "price": 1.0},
                       venue="mt5", account_id=ACCOUNT, deal_id="e1"),
        normalize_deal({"side": "sell", "qty": 2.0, "price": 2.0},
                       venue="mt5", account_id=ACCOUNT, deal_id="x1"))
    assert trip["quantity"] == 0.0


def test_flat_fill_is_a_balance_movement_not_a_trade(deals):
    """A flat fill is money moving, not a position opened."""
    row = deals.append_deal(dict(
        deal_id="d2", account_id=ACCOUNT, venue="mt5", venue_deal_ref="56",
        symbol="BTC", side="flat", deal_kind="balance", qty=0.0))
    assert row["deal_kind"] == "balance"
    assert [d["deal_id"] for d in deals.list_deals(ACCOUNT)] == ["d2"]


def test_deal_kind_is_derived_from_the_venue_entry_flag():
    assert normalize_deal({"entry": 0}, venue="mt5", account_id=ACCOUNT)[
        "deal_kind"] == "entry"
    assert normalize_deal({"entry": 1}, venue="mt5", account_id=ACCOUNT)[
        "deal_kind"] == "exit"
    assert normalize_deal({"entry": 3}, venue="mt5", account_id=ACCOUNT)[
        "deal_kind"] == "exit"


# -- nothing is duplicated ------------------------------------------------


def test_reingesting_a_fill_does_not_duplicate_history(deals):
    """Reconciliation re-reads the same deal history every cycle."""
    payload = dict(account_id=ACCOUNT, venue="mt5", venue_deal_ref="77",
                   symbol="EURUSD", side="buy", deal_kind="entry", qty=0.1,
                   price=1.0850)
    first = deals.append_deal(dict(payload))
    second = deals.append_deal(dict(payload))
    assert first["created"] is True
    assert second["created"] is False
    assert second["deal_id"] == first["deal_id"]
    assert len(deals.list_deals(ACCOUNT)) == 1


def test_an_absent_venue_deal_id_does_not_deduplicate(deals):
    """Two fills with no venue id are two fills.

    Collapsing them on a NULL id would lose a trade the broker cannot re-send.
    """
    deals.append_deal(dict(deal_id="d3", account_id=ACCOUNT, venue="sim",
                           symbol="X", side="buy", qty=1.0))
    deals.append_deal(dict(deal_id="d4", account_id=ACCOUNT, venue="sim",
                           symbol="X", side="buy", qty=1.0))
    assert len(deals.list_deals(ACCOUNT)) == 2


def test_two_unsubmitted_orders_coexist(orders):
    """`''` is not a neutral placeholder in a uniqueness-constrained column.

    Treating absence as empty string would let exactly one simulated order exist
    per venue and reject the rest as duplicates.
    """
    orders.save_order(dict(order_id="s1", account_id=ACCOUNT, venue="sim",
                           symbol="X", side="buy", order_type="market",
                           status="pending", venue_order_ref=""))
    orders.save_order(dict(order_id="s2", account_id=ACCOUNT, venue="sim",
                           symbol="X", side="buy", order_type="market",
                           status="pending", venue_order_ref=""))
    assert orders.get_order(ACCOUNT, "s1")["venue_order_ref"] is None
    assert orders.get_order(ACCOUNT, "s2")["venue_order_ref"] is None
    assert len(orders.list_orders(ACCOUNT)) == 2


def test_a_venue_ticket_cannot_be_claimed_by_two_orders(orders):
    """One ticket is one order, and the refusal names both sides.

    The alternative -- letting the UNIQUE constraint raise -- surfaces a SQLite
    implementation message to a caller who passed two ordinary-looking order ids
    and needs to be told which one already holds the ticket.
    """
    orders.save_order(dict(order_id="t1", account_id=ACCOUNT, venue="mt5",
                           venue_order_ref="500", symbol="EURUSD", side="buy",
                           order_type="market", status="submitted"))
    with pytest.raises(ValueError) as excinfo:
        orders.save_order(dict(order_id="t2", account_id=ACCOUNT, venue="mt5",
                               venue_order_ref="500", symbol="EURUSD",
                               side="buy", order_type="market",
                               status="filled"))
    assert "t1" in str(excinfo.value)
    assert "500" in str(excinfo.value)
    assert len(orders.list_orders(ACCOUNT)) == 1


def test_resaving_the_same_order_id_advances_its_status(orders):
    """An order progresses; that is an update, not a new row."""
    orders.save_order(dict(order_id="t1", account_id=ACCOUNT, venue="mt5",
                           venue_order_ref="500", symbol="EURUSD", side="buy",
                           order_type="market", status="submitted"))
    updated = orders.save_order(dict(order_id="t1", account_id=ACCOUNT,
                                    venue="mt5", venue_order_ref="500",
                                    symbol="EURUSD", side="buy",
                                    order_type="market", status="filled"))
    assert updated["status"] == "filled"
    assert len(orders.list_orders(ACCOUNT)) == 1


def test_the_same_ticket_on_two_accounts_is_two_orders(orders):
    """An MT5 ticket is unique per server, not globally.

    Two brokers both issuing #1234 must not collide.
    """
    orders.save_order(dict(order_id="t1", account_id=ACCOUNT, venue="mt5",
                           venue_order_ref="1234", symbol="X", side="buy",
                           order_type="market", status="filled"))
    orders.save_order(dict(order_id="t2", account_id=OTHER, venue="mt5",
                           venue_order_ref="1234", symbol="X", side="buy",
                           order_type="market", status="filled"))
    assert len(orders.list_orders(ACCOUNT)) == 1
    assert len(orders.list_orders(OTHER)) == 1


# -- nothing leaks --------------------------------------------------------


def test_a_read_cannot_cross_an_account_boundary(orders):
    orders.save_order(dict(order_id="o1", account_id=ACCOUNT, venue="mt5",
                           symbol="EURUSD", side="buy", order_type="market",
                           status="filled"))
    assert orders.get_order(OTHER, "o1") is None


def test_listing_is_scoped(orders):
    orders.save_order(dict(order_id="o1", account_id=ACCOUNT, venue="mt5",
                           symbol="EURUSD", side="buy", order_type="market",
                           status="filled"))
    orders.save_order(dict(order_id="o2", account_id=OTHER, venue="mt5",
                           symbol="EURUSD", side="buy", order_type="market",
                           status="filled"))
    assert [o["order_id"] for o in orders.list_orders(ACCOUNT)] == ["o1"]


def test_positions_and_round_trips_are_scoped_too(session, positions,
                                                 round_trips):
    positions.save_position(dict(position_id="p1", account_id=ACCOUNT,
                                 venue="mt5", symbol="X", side="buy",
                                 status="open"))
    positions.save_position(dict(position_id="p2", account_id=OTHER,
                                 venue="mt5", symbol="X", side="buy",
                                 status="open"))
    assert len(positions.list_positions(ACCOUNT)) == 1

    round_trips.save_round_trip(dict(round_trip_id="r1", account_id=ACCOUNT,
                                     venue="mt5", symbol="X", side="buy",
                                     opened_at=1.0, closed_at=2.0,
                                     net_pnl=5.0))
    assert len(round_trips.list_round_trips(ACCOUNT)) == 1


def test_an_order_cannot_be_moved_between_accounts(orders):
    """The same isolation boundary the positions and round trips hold.

    An order update that could change `account_id` would let a row walk from one
    account's ledger into another's, which is the one thing account scoping
    exists to prevent, so the update is refused rather than applied.
    """
    orders.save_order(dict(order_id="o1", account_id=ACCOUNT, venue="mt5",
                           symbol="X", side="buy"))
    with pytest.raises(ValueError):
        orders.save_order(dict(order_id="o1", account_id=OTHER, venue="mt5",
                               symbol="X", side="buy"))
    assert orders.get_order(ACCOUNT, "o1")["account_id"] == ACCOUNT


def test_updating_an_order_keeps_the_fields_it_did_not_mention(orders):
    """A partial status sync must not blank out prices and quantities.

    The payload a progress update carries is a subset of the one that created
    the row, and writing `None` over every numeric column the update did not
    mention would erase the limit price and fill price the same row already had.
    """
    orders.save_order(dict(order_id="o1", account_id=ACCOUNT, venue="mt5",
                           symbol="EURUSD", side="buy", order_type="limit",
                           limit_price=1.0850, requested_qty=0.5,
                           submitted_at=100.0))
    updated = orders.save_order(dict(order_id="o1", account_id=ACCOUNT,
                                     status="filled"))
    assert updated["limit_price"] == 1.0850
    assert updated["requested_qty"] == 0.5
    assert updated["submitted_at"] == 100.0
    assert updated["status"] == "filled"


def test_a_position_sync_does_not_forget_its_entry_price(positions):
    """A live sync reports the current price; it does not restate the whole row.

    A position whose entry price was blanked cannot be turned back into a round
    trip, so the entry price has to survive a save that did not mention it.
    """
    positions.save_position(dict(position_id="p1", account_id=ACCOUNT,
                                 venue="mt5", symbol="EURUSD", side="buy",
                                 volume=0.5, entry_price=1.0850,
                                 unrealized_pnl=12.0))
    synced = positions.save_position(dict(position_id="p1",
                                          account_id=ACCOUNT,
                                          current_price=1.0900))
    assert synced["entry_price"] == 1.0850
    assert synced["volume"] == 0.5
    assert synced["current_price"] == 1.0900
    assert synced["unrealized_pnl"] == 12.0


def test_a_position_cannot_be_moved_between_accounts(positions):
    positions.save_position(dict(position_id="p1", account_id=ACCOUNT,
                                 venue="mt5", symbol="X", side="buy",
                                 status="open"))
    with pytest.raises(ValueError):
        positions.save_position(dict(position_id="p1", account_id=OTHER,
                                     venue="mt5", symbol="X", side="buy"))


def test_a_round_trip_cannot_be_moved_between_accounts(round_trips):
    round_trips.save_round_trip(dict(round_trip_id="r1", account_id=ACCOUNT,
                                     venue="mt5", symbol="X", side="buy"))
    with pytest.raises(ValueError):
        round_trips.save_round_trip(dict(round_trip_id="r1", account_id=OTHER,
                                         venue="mt5", symbol="X", side="buy"))


def test_removing_an_account_registration_leaves_its_history(session, orders):
    """Registration removal must not remove the record of what the account did.

    Lives here rather than in `test_account_registry.py` because it needs the
    trade tables. The invariant is the same from either side: deleting the
    registry row is a naming operation, and the orders, fills and round trips
    that happened under it are the account's history and outlive the name.
    """
    from persistence.repositories_accounts import AccountRegistryRepository

    registry = AccountRegistryRepository(session)
    account = registry.register(venue="mt5", venue_login="3",
                                venue_server="S", owner_user_id="op-1")
    orders.save_order(dict(order_id="o1", account_id=account["account_id"],
                           venue="mt5", symbol="EURUSD", side="buy",
                           order_type="market", status="filled"))
    assert registry.delete(account["account_id"]) is True
    assert registry.get(account["account_id"]) is None
    assert len(orders.list_orders(account["account_id"])) == 1


def test_an_order_without_an_account_is_refused(orders):
    with pytest.raises(ValueError):
        orders.save_order(dict(order_id="o1", venue="mt5", symbol="X",
                               side="buy", order_type="market"))


# -- round trips ----------------------------------------------------------


def test_attaching_an_exit_deal_does_not_unprice_a_closed_round_trip(round_trips):
    """A partial save may not erase the result an earlier save computed.

    Saving again to attach an `exit_deal_id` is the ordinary way reconciliation
    runs. Writing NULL over every numeric column the partial payload did not
    mention would leave a settled trade with `status='closed'`, `closed_at` set
    and `net_pnl` unknown -- which is precisely the row the status column exists
    to keep impossible.
    """
    round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, venue="mt5", symbol="EURUSD",
        side="buy", opened_at=1.0, closed_at=2.0, net_pnl=10.0, fees=1.0))
    again = round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, exit_deal_id="d9"))
    assert again["net_pnl"] == 10.0
    assert again["fees"] == 1.0
    assert again["outcome"] == "win"
    assert again["status"] == "closed"


def test_an_explicit_null_still_clears_a_round_trip_number(round_trips):
    """Absent means "not mentioned"; a present null means "forget it"."""
    round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, venue="mt5", symbol="X",
        side="buy", opened_at=1.0, net_pnl=5.0))
    cleared = round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, net_pnl=None))
    assert cleared["net_pnl"] is None


def test_a_round_trip_records_its_result(round_trips):
    saved = round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, venue="mt5", symbol="EURUSD",
        side="buy", opened_at=100.0, closed_at=160.0, net_pnl=42.0,
        gross_pnl=44.0, fees=2.0))
    assert saved["status"] == "closed"
    assert saved["outcome"] == "win"
    assert saved["duration_seconds"] == 60.0


def test_a_closed_round_trip_may_not_also_read_as_open(round_trips):
    """A finished trade that reads as open is skipped by every rollup."""
    with pytest.raises(ValueError):
        round_trips.save_round_trip(dict(
            round_trip_id="rt", account_id=ACCOUNT, venue="mt5", symbol="X",
            side="buy", closed_at=10.0, status="open", net_pnl=1.0))


def test_closing_twice_does_not_restate_pnl(round_trips):
    round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, venue="mt5", symbol="X",
        side="buy", opened_at=1.0, closed_at=2.0, net_pnl=10.0))
    again = round_trips.close_round_trip(
        "rt", exit_deal_id="d9", closed_at=999.0, exit_price=1.2, net_pnl=500.0)
    assert again["net_pnl"] == 10.0
    assert again["closed_at"] == 2.0


def test_outcome_is_derived_not_supplied(round_trips):
    saved = round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, venue="mt5", symbol="X",
        side="buy", opened_at=1.0, closed_at=2.0, net_pnl=-3.0))
    assert saved["outcome"] == "loss"


def test_an_open_round_trip_may_not_carry_an_outcome(round_trips):
    with pytest.raises(ValueError):
        round_trips.save_round_trip(dict(
            round_trip_id="rt", account_id=ACCOUNT, venue="mt5", symbol="X",
            side="buy", outcome="win"))


def test_an_unmeasurable_round_trip_has_no_outcome(round_trips):
    """A venue that never reported P&L has not reported breakeven."""
    saved = round_trips.save_round_trip(dict(
        round_trip_id="rt", account_id=ACCOUNT, venue="okx", symbol="X",
        side="buy", opened_at=1.0, closed_at=2.0))
    assert saved["outcome"] is None


# -- normaliser -----------------------------------------------------------


def test_venue_wording_maps_to_canonical_values():
    assert canonical_side("BUY").value == "long"
    assert canonical_side("open_short").value == "short"
    assert canonical_order_status("partially_filled").value == "partial"
    assert canonical_order_status("Partially Filled").value == "partial"
    assert canonical_order_type("LIMIT").value == "limit"


def test_a_short_round_trip_computes_the_right_sign():
    """(exit - entry) * qty is a loss on a short."""
    entry = normalize_deal(dict(deal_id="e", account_id=ACCOUNT, venue="mt5",
                                symbol="X", side="sell", qty=1.0, price=100.0,
                                entry=0, executed_at=1.0), venue="mt5",
                           account_id=ACCOUNT)
    exit_ = normalize_deal(dict(deal_id="x", account_id=ACCOUNT, venue="mt5",
                                symbol="X", side="buy", qty=1.0, price=90.0,
                                entry=1, executed_at=2.0), venue="mt5",
                           account_id=ACCOUNT)
    trip = build_round_trip(entry, exit_)
    assert trip["gross_pnl"] == 10.0
    assert trip["outcome"] == "win"


def test_round_trip_is_net_of_fees():
    """A gross-of-costs round trip makes every strategy look profitable."""
    entry = normalize_deal(dict(deal_id="e", account_id=ACCOUNT, venue="okx",
                                symbol="X", side="buy", qty=1.0, price=100.0,
                                fee=-2.0, entry=0, executed_at=1.0), venue="okx",
                           account_id=ACCOUNT)
    exit_ = normalize_deal(dict(deal_id="x", account_id=ACCOUNT, venue="okx",
                                symbol="X", side="sell", qty=1.0, price=102.0,
                                fee=-2.0, pnl=2.0, entry=1, executed_at=2.0),
                           venue="okx", account_id=ACCOUNT)
    trip = build_round_trip(entry, exit_)
    assert trip["gross_pnl"] == 2.0
    assert trip["fees"] == -4.0
    assert trip["net_pnl"] == 6.0


def test_an_incomplete_exit_yields_no_result():
    """Not a zero: a trip whose P&L is unknown has no outcome."""
    entry = normalize_deal(dict(deal_id="e", account_id=ACCOUNT, venue="mt5",
                                symbol="X", side="sell", qty=1.0, price=100.0,
                                entry=0, executed_at=1.0), venue="mt5",
                           account_id=ACCOUNT)
    exit_ = normalize_deal(dict(deal_id="x", account_id=ACCOUNT, venue="mt5",
                                symbol="X", side="buy", entry=1,
                                executed_at=2.0), venue="mt5",
                           account_id=ACCOUNT)
    trip = build_round_trip(entry, exit_)
    assert trip["gross_pnl"] is None
    assert trip["net_pnl"] is None
    assert trip["outcome"] is None


def test_normalised_values_round_trip_into_a_row(deals):
    row = deals.append_deal(normalize_deal(dict(
        deal_id="n1", venue_deal_ref="900", symbol="BTC/USDT", side="buy",
        qty=0.5, price=60000.0, fee=-1.25, entry=0, executed_at=1234.0),
        venue="okx", account_id=ACCOUNT))
    assert row["venue_deal_ref"] == "900"
    assert row["qty"] == 0.5
    assert row["fee"] == -1.25
    assert row["executed_at"] == 1234.0


def test_venue_native_ids_are_preserved_for_reconciliation():
    """A diff has to be able to get back to what the venue actually said."""
    order = normalize_order(dict(symbol="EURUSD", side="buy",
                                 order_type="market", status="filled",
                                 venue_order_ref="8811"), venue="mt5",
                            account_id=ACCOUNT, order_id="o1")
    assert order["venue_order_ref"] == "8811"
    position = normalize_position(dict(symbol="EURUSD", side="buy",
                                       venue_position_ref="9911"), venue="mt5",
                                  account_id=ACCOUNT, position_id="p1")
    assert position["venue_position_ref"] == "9911"


def test_a_normalised_position_never_recomputes_realized_pnl():
    """A resync that recomputes it would drop every earlier partial close."""
    position = normalize_position(dict(symbol="X", side="buy", volume=0.1,
                                       entry_price=1.0, current_price=1.2,
                                       realized_pnl=65.0), venue="mt5",
                                  account_id=ACCOUNT, position_id="p1")
    assert position["realized_pnl"] == 65.0
    assert position["current_price"] == 1.2


def test_unmapped_venue_fields_are_surfaced_for_the_adapter_author():
    """Silently dropping a field is how a venue's margin mode stops recording."""
    raw = dict(symbol="X", side="buy", margin_mode="isolated", tif="GTC")
    leftovers = unmapped_venue_fields(raw, ["symbol", "side"])
    assert "margin_mode" in leftovers
    assert "tif" in leftovers
    assert "symbol" not in leftovers


# -- cycles ---------------------------------------------------------------


def _trip(repo, rid, net, closed_at, *, strategy="s1"):
    repo.save_round_trip(dict(
        round_trip_id=rid, account_id=ACCOUNT, venue="mt5", symbol="X",
        side="buy", strategy_id=strategy, opened_at=closed_at - 60,
        closed_at=closed_at, net_pnl=net, gross_pnl=net, quantity=0.1,
        duration_seconds=60.0))


def test_cycle_counts_wins_and_losses(round_trips):
    _trip(round_trips, "a", 50.0, 100.0)
    _trip(round_trips, "b", -20.0, 200.0)
    _trip(round_trips, "c", 10.0, 300.0)
    _trip(round_trips, "d", -5.0, 400.0)
    rows = round_trips.list_round_trips(ACCOUNT, closed_only=True)
    cycle = cycle_from_round_trips(rows, account_id=ACCOUNT, strategy_id="s1",
                                   period_start=0.0, period_end=1000.0)
    assert (cycle["wins"], cycle["losses"]) == (2, 2)
    assert cycle["net_pnl"] == 35.0
    assert cycle["win_rate"] == pytest.approx(0.5)
    assert cycle["profit_factor"] == pytest.approx(60.0 / 25.0)


def test_cycle_drawdown_measures_the_curve_not_the_worst_trade(round_trips):
    _trip(round_trips, "a", 100.0, 100.0)
    _trip(round_trips, "b", -40.0, 200.0)
    _trip(round_trips, "c", -40.0, 300.0)
    rows = round_trips.list_round_trips(ACCOUNT, closed_only=True)
    cycle = cycle_from_round_trips(rows, account_id=ACCOUNT, strategy_id="s1",
                                   period_start=0.0, period_end=1000.0)
    # 100 then -40 then -40: peak 100, trough 20, so the drawdown is 80 -- not
    # 40, which is what a per-trade reading would report.
    assert cycle["max_drawdown"] == pytest.approx(80.0)
    assert cycle["max_consecutive_losses"] == 2


def test_the_first_loss_counts_as_a_drawdown(round_trips):
    """The curve starts at zero, not at its own minimum."""
    _trip(round_trips, "a", -25.0, 100.0)
    rows = round_trips.list_round_trips(ACCOUNT, closed_only=True)
    cycle = cycle_from_round_trips(rows, account_id=ACCOUNT, strategy_id="s1",
                                   period_start=0.0, period_end=1000.0)
    assert cycle["max_drawdown"] == pytest.approx(25.0)


def test_profit_factor_is_undefined_with_no_losses(round_trips):
    """Dividing by zero is not infinity, it is 'cannot tell you'.

    And `0.0` here would read as "did not profit" for a period where nothing was
    lost -- the optimistic reading of a degenerate case.
    """
    _trip(round_trips, "a", 10.0, 100.0)
    _trip(round_trips, "b", 5.0, 200.0)
    rows = round_trips.list_round_trips(ACCOUNT, closed_only=True)
    cycle = cycle_from_round_trips(rows, account_id=ACCOUNT, strategy_id="s1",
                                   period_start=0.0, period_end=1000.0)
    assert cycle["profit_factor"] is None


def test_an_empty_period_yields_nothing_rather_than_zeroes():
    """`0.0` would say 'no winning trades' instead of 'no trades to judge'."""
    cycle = cycle_from_round_trips([], account_id=ACCOUNT, strategy_id="s1",
                                   period_start=0.0, period_end=1.0)
    assert cycle["trades"] == 0
    for field in ("win_rate", "profit_factor", "expectancy", "net_pnl",
                  "gross_pnl", "max_drawdown", "max_consecutive_losses"):
        assert cycle[field] is None


def test_an_incomplete_period_is_not_rolled_up_as_a_total(round_trips):
    """A partial sum in a column that reads like a total is a silent overstatement."""
    round_trips.save_round_trip(dict(
        round_trip_id="a", account_id=ACCOUNT, venue="mt5", symbol="X",
        side="buy", opened_at=1.0, closed_at=2.0, net_pnl=10.0))
    round_trips.save_round_trip(dict(
        round_trip_id="b", account_id=ACCOUNT, venue="okx", symbol="X",
        side="buy", opened_at=1.0, closed_at=2.0))
    rows = round_trips.list_round_trips(ACCOUNT, closed_only=True)
    cycle = cycle_from_round_trips(rows, account_id=ACCOUNT, strategy_id="s1",
                                   period_start=0.0, period_end=1000.0)
    assert cycle["net_pnl"] is None
    assert cycle["trades"] == 2


def test_cycles_are_reproducible_from_round_trips_alone(round_trips, session):
    """A rollup that cannot be rebuilt cannot be checked."""
    _trip(round_trips, "a", 50.0, 100.0)
    _trip(round_trips, "b", -20.0, 200.0)
    rows = round_trips.list_round_trips(ACCOUNT, closed_only=True)
    first = cycle_from_round_trips(rows, account_id=ACCOUNT, strategy_id="s1",
                                   period_start=0.0, period_end=1000.0)
    second = cycle_from_round_trips(
        round_trips.list_round_trips(ACCOUNT, closed_only=True),
        account_id=ACCOUNT, strategy_id="s1", period_start=0.0,
        period_end=1000.0)
    for field in ("trades", "wins", "losses", "net_pnl", "gross_pnl",
                  "win_rate", "expectancy", "profit_factor", "max_drawdown",
                  "max_consecutive_losses", "avg_duration_seconds"):
        assert first[field] == second[field]


def test_a_cycle_row_is_replaced_rather_than_duplicated(session, round_trips):
    cycles = TradeCycleRepository(session)
    cycles.upsert_cycle(dict(account_id=ACCOUNT, strategy_id="s1",
                             period_start=0.0, period_end=10.0, trades=3,
                             net_pnl=30.0, win_rate=0.66))
    cycles.upsert_cycle(dict(account_id=ACCOUNT, strategy_id="s1",
                             period_start=0.0, period_end=10.0, trades=4,
                             net_pnl=35.0, win_rate=0.75))
    stored = cycles.list_cycles(ACCOUNT)
    assert len(stored) == 1
    assert stored[0]["trades"] == 4
    assert stored[0]["net_pnl"] == 35.0


def test_cycles_are_listed_per_account(session):
    cycles = TradeCycleRepository(session)
    cycles.upsert_cycle(dict(account_id=ACCOUNT, strategy_id="s1",
                             period_start=0.0, period_end=10.0))
    cycles.upsert_cycle(dict(account_id=OTHER, strategy_id="s1",
                             period_start=0.0, period_end=10.0))
    assert len(cycles.list_cycles(ACCOUNT)) == 1
