"""S5 venue scorecard tests (row 780).

The scorecard is evidence-only and advisory: it scores a venue only from the
canonical orders attributed to it, reports ``unproven`` (score null) rather
than inventing a number from too little history, and counts unattributed
orders instead of folding them into a rail.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from core.config import settings
from core.contracts import OrderStatus, OrderType, TradeDirection
from core.state import AccountState, CanonicalState, OrderState
from execution.venue_score import (
    MIN_SAMPLES,
    MT5_VENUE,
    DefaultVenueScoreModel,
    VenueMetrics,
    VenueScorecard,
)


def make_state(broker="ICMarkets-Demo"):
    s = CanonicalState()
    s.set_account(AccountState(login=1, broker=broker,
                               balance=10_000.0, equity=10_000.0))
    return s


def add_order(s, venue, status, slippage=0.0, commission=0.0, volume=0.1):
    oid = f"o{len(s.orders)}"
    s.orders[oid] = OrderState(
        order_id=oid, symbol="XAUUSD", order_type=OrderType.MARKET,
        direction=TradeDirection.LONG, volume=volume, price=2000.0,
        status=status, venue=venue, slippage=slippage, commission=commission)
    return oid


def test_metrics_derive_from_orders():
    m = VenueMetrics(venue="x", orders=4, filled=2, partial=1, rejected=1)
    assert m.terminal == 4
    assert m.fill_ratio == pytest.approx(0.5)
    assert m.reject_rate == pytest.approx(0.25)
    # no slippage evidence -> None, never a fabricated 0.0 average
    assert m.avg_slippage is None


def test_below_min_samples_is_unproven_and_invents_nothing():
    m = VenueMetrics(venue="x", orders=2, filled=1, rejected=1)
    assert m.terminal < MIN_SAMPLES
    sc = DefaultVenueScoreModel().score(m)
    assert sc.scored is False
    assert sc.score is None
    assert sc.components is None
    assert sc.tier == "unproven"


def test_scoring_is_a_weighted_average_of_named_components():
    m = VenueMetrics(venue="x", orders=10, filled=8, partial=1, rejected=1)
    m._slips[:] = [0.5] * 9
    sc = DefaultVenueScoreModel().score(m)
    assert sc.scored is True
    assert sc.components["fill_quality"] == pytest.approx(0.8)
    assert sc.components["slippage_quality"] == pytest.approx(1.0 / 1.5, abs=1e-4)
    assert sc.components["reliability"] == pytest.approx(0.9)
    expected = 0.4 * 0.8 + 0.3 * (1.0 / 1.5) + 0.3 * 0.9
    assert sc.score == pytest.approx(expected, abs=1e-3)


def test_flawless_venue_scores_one_and_is_strong():
    m = VenueMetrics(venue="x", orders=5, filled=5)
    m._slips[:] = [0.0] * 5
    sc = DefaultVenueScoreModel().score(m)
    assert sc.score == pytest.approx(1.0)
    assert sc.tier == "strong"


def test_scorecard_lists_both_rails_unproven_with_no_evidence():
    card = VenueScorecard(state_ref=make_state()).scorecard()
    venues = {v["venue"]: v for v in card["venues"]}
    assert MT5_VENUE in venues
    assert settings.cex.venue in venues
    assert venues[MT5_VENUE]["scored"] is False
    assert card["recommended"] is None
    assert card["read_only"] is True
    assert card["is_authorisation"] is False
    assert card["trade_authority"] == "risk/governor.py"


def test_scorecard_recommends_the_best_scored_venue_and_counts_unattributed():
    s = make_state()
    for _ in range(4):
        add_order(s, "binance", OrderStatus.FILLED, slippage=0.1, commission=0.5)
    add_order(s, "binance", OrderStatus.REJECTED)
    for _ in range(4):
        add_order(s, "mt5", OrderStatus.FILLED, slippage=5.0)
    add_order(s, "mt5", OrderStatus.REJECTED)
    add_order(s, "", OrderStatus.FILLED)  # unattributed

    card = VenueScorecard(state_ref=s).scorecard()
    assert card["unattributed_orders"] == 1
    venues = {v["venue"]: v for v in card["venues"]}
    assert venues["binance"]["scored"] is True
    assert venues["mt5"]["scored"] is True
    assert venues["binance"]["score"] > venues["mt5"]["score"]
    assert card["recommended"] == "binance"
