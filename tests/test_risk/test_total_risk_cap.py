"""The 2% book-wide cap and the margin-derived size limit.

Both are tested against the numbers actually measured on FTTrading-Server for
account 1400167, because the behaviour under test IS those numbers: a 2% cap
that nets instead of summing, or a size that trusts the tournament's declared
1:500 instead of the broker's 10:1 on gold, passes every abstract test and then
over-sizes the first live trade.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from challenge.leverage import SymbolLeverage, size_for_candidate
from challenge.portfolio_risk import (
    DEFAULT_TOTAL_RISK_CAP_FRACTION,
    account_currency_risk,
    book_risk,
    check_portfolio_risk,
    portfolio_risk_room,
    total_open_risk,
)
from core.contracts import TradeDirection
from core.state import AccountState, CanonicalState, MarketState, PositionState
from decision.candidate import TradeCandidate
from risk.governor import RiskGovernor


# The measured economics of this account, 2026-10-02. Not invented: EURUSD is
# 40:1, gold 10:1, BTC 5:1, against a tournament that publishes 1:500.
MEASURED = {
    "EURUSD": {"margin_per_lot": 2810.14, "effective_leverage": 40.0},
    "XAUUSD": {"margin_per_lot": 41574.00, "effective_leverage": 10.0},
    "BTCUSD": {"margin_per_lot": 16997.57, "effective_leverage": 5.0},
}

TICK = {
    "EURUSD": {"tick_size": 1e-05, "tick_value": 1.0, "price": 1.08650},
    "XAUUSD": {"tick_size": 0.01, "tick_value": 1.0, "price": 4155.36},
    "BTCUSD": {"tick_size": 0.1, "tick_value": 0.1, "price": 84992.0},
}


def market(symbol):
    spec = TICK[symbol]
    price = spec["price"]
    return MarketState(symbol=symbol, bid=price, ask=price + 0.01,
                       last_price=price, last_tick_time=1.0,
                       tick_size=spec["tick_size"],
                       tick_value=spec["tick_value"],
                       contract_size=100000.0 if symbol == "EURUSD" else 1.0,
                       volume_min=0.01, volume_step=0.01, volume_max=100.0)


def position(symbol, volume, stop_distance):
    spec = TICK[symbol]
    return PositionState(position_id=f"p-{symbol}", symbol=symbol,
                         direction=TradeDirection.LONG, volume=volume,
                         entry_price=spec["price"],
                         current_price=spec["price"],
                         sl=spec["price"] - stop_distance)


# -- Summing, not netting ------------------------------------------------
def test_total_open_risk_sums_across_symbols():
    assert total_open_risk({"EURUSD": 500.0, "XAUUSD": 700.0,
                            "BTCUSD": 300.0}) == pytest.approx(1500.0)


def test_inverse_exposure_does_not_reduce_the_total():
    """The case netting would get wrong, and the reason for the whole module.

    Long EURUSD and long XAUUSD are both dollar exposure, so a 2%-cap operator
    asked for the sum. A net figure would report 0 here and the cap would have
    no maximum.
    """
    assert total_open_risk({"EURUSD": 2000.0, "XAUUSD": 2000.0}) == pytest.approx(4000.0)


def test_negative_risk_is_not_credit_against_the_cap():
    assert total_open_risk({"EURUSD": 1000.0, "XAUUSD": -1000.0}) == pytest.approx(1000.0)


def test_room_is_the_cap_minus_the_summed_total():
    room = portfolio_risk_room({"EURUSD": 500.0, "XAUUSD": 300.0}, equity=100000.0)
    assert room["cap_usd"] == pytest.approx(2000.0)
    assert room["room"] == pytest.approx(1200.0)


def test_room_accounts_for_risk_already_proposed_this_pass():
    room = portfolio_risk_room({"XAUUSD": 1000.0}, equity=100000.0,
                               already_proposed=1500.0)
    assert room["room"] == pytest.approx(-500.0 + 500.0) or room["room"] == 0.0
    assert room["total"] == pytest.approx(2500.0)


def test_default_cap_is_two_percent():
    assert DEFAULT_TOTAL_RISK_CAP_FRACTION == 0.02


def test_unmeasurable_equity_yields_no_room_not_full_room():
    room = portfolio_risk_room({"XAUUSD": 100.0}, equity=0.0)
    assert room["known"] is False
    assert room["room"] is None


# -- Account-currency risk ----------------------------------------------
def test_position_risk_is_measured_in_account_currency():
    """50 pips on 0.02 lots of EURUSD is $10, not the 0.0001 PositionState gives.

    `PositionState.risk` is SL distance times volume with no tick economics,
    which is a price difference rather than money. Summing that across a book
    reports a total of essentially zero, and a 2% cap built on it never binds.
    """
    p = position("EURUSD", volume=0.02, stop_distance=0.0050)
    assert account_currency_risk(p, market("EURUSD")) == pytest.approx(10.0)


def test_position_risk_uses_each_symbols_own_ticks():
    # $10 stop on 0.5 lots of gold: 1000 ticks at $1/tick.
    assert account_currency_risk(position("XAUUSD", 0.5, 10.0),
                                 market("XAUUSD")) == pytest.approx(500.0)
    # $100 stop on 1 lot of BTC: 1000 ticks at $0.10/tick.
    assert account_currency_risk(position("BTCUSD", 1.0, 100.0),
                                 market("BTCUSD")) == pytest.approx(100.0)


def test_position_without_a_stop_is_unmeasurable_not_zero():
    p = position("XAUUSD", 0.5, 10.0)
    p.sl = None
    assert account_currency_risk(p, market("XAUUSD")) is None


def test_book_risk_names_the_unmeasurable_position():
    good = position("EURUSD", 0.02, 0.0050)
    bad = position("XAUUSD", 0.5, 10.0)
    bad.sl = None
    book = book_risk([good, bad], lambda s: market(s))
    assert book["risk_by_symbol"] == {"EURUSD": pytest.approx(10.0)}
    assert book["unmeasurable"] == ["XAUUSD"]


# -- The check ----------------------------------------------------------
def test_proposal_within_room_passes():
    r = check_portfolio_risk({"XAUUSD": 1200.0}, 100000.0, 500.0)
    assert r["passed"] is True
    assert r["verdict"] == "allow"


def test_proposal_over_cap_is_resized():
    r = check_portfolio_risk({"XAUUSD": 1200.0}, 100000.0, 1500.0)
    assert r["passed"] is False
    assert r["verdict"] == "resize"
    assert r["room"] == pytest.approx(800.0)
    assert "without netting" in r["decision_reason"]


def test_contributors_are_listed_largest_first():
    r = check_portfolio_risk({"EURUSD": 300.0, "XAUUSD": 900.0, "BTCUSD": 100.0},
                             100000.0, 10.0)
    assert [c["symbol"] for c in r["contributors"]] == ["XAUUSD", "EURUSD", "BTCUSD"]


# -- Measured margin ----------------------------------------------------
def test_margin_derived_size_uses_measured_not_declared_leverage(monkeypatch):
    """Gold is the test case that matters: 1:500 declared, 10:1 measured.

    At a 300% margin floor a 100k account may hold $33,333 of margin, which at
    gold's measured $41,574/lot is 0.80 lots. Sizing from the tournament's 1:500
    would propose roughly 12.5 lots -- 12x what the account can carry.
    """
    import challenge.leverage as lev
    monkeypatch.setattr(lev, "symbol_leverage", lambda symbol: SymbolLeverage(
        symbol=symbol, effective_leverage=10.0, margin_per_lot=41574.0,
        notional_per_lot=415536.0, measured_at=0.0))
    result = size_for_candidate("XAUUSD", risk_budget=1_000_000.0,
                                risk_per_lot=1000.0, equity=100000.0)
    assert result["size"] == pytest.approx(0.80, abs=0.01)
    assert result["binding_limit"] == "margin_floor"
    assert result["effective_leverage"] == 10.0


def test_the_smaller_of_risk_and_margin_wins(monkeypatch):
    """EURUSD inverts gold: the risk budget binds first, by a wide margin."""
    import challenge.leverage as lev
    monkeypatch.setattr(lev, "symbol_leverage", lambda symbol: SymbolLeverage(
        symbol=symbol, effective_leverage=40.0, margin_per_lot=2810.14,
        notional_per_lot=112400.0, measured_at=0.0))
    result = size_for_candidate("EURUSD", risk_budget=2000.0,
                                risk_per_lot=100000.0, equity=100000.0)
    assert result["size"] == pytest.approx(0.02)
    assert result["binding_limit"] == "risk_budget"


def test_unmeasurable_symbol_gets_no_size():
    import challenge.leverage as lev
    lev._default_cache.invalidate()
    result = size_for_candidate("NOSUCH", risk_budget=2000.0, risk_per_lot=100.0,
                                equity=100000.0)
    assert result["size"] == 0.0
    assert "not measurable" in result["reason"]


def test_used_margin_comes_off_the_budget_first(monkeypatch):
    import challenge.leverage as lev
    monkeypatch.setattr(lev, "symbol_leverage", lambda symbol: SymbolLeverage(
        symbol=symbol, effective_leverage=10.0, margin_per_lot=10000.0,
        notional_per_lot=100000.0, measured_at=0.0))
    free = size_for_candidate("XAUUSD", risk_budget=1e9, risk_per_lot=1.0,
                              equity=100000.0, used_margin=0.0)
    used = size_for_candidate("XAUUSD", risk_budget=1e9, risk_per_lot=1.0,
                              equity=100000.0, used_margin=23333.0)
    assert free["size"] == pytest.approx(3.33, abs=0.01)
    assert used["size"] == pytest.approx(1.00, abs=0.01)


def test_btc_binds_on_margin_not_risk(monkeypatch):
    import challenge.leverage as lev
    monkeypatch.setattr(lev, "symbol_leverage", lambda symbol: SymbolLeverage(
        symbol=symbol, effective_leverage=5.0, margin_per_lot=16997.57,
        notional_per_lot=84992.0, measured_at=0.0))
    result = size_for_candidate("BTCUSD", risk_budget=2000.0, risk_per_lot=1.0,
                                equity=100000.0)
    assert result["binding_limit"] == "margin_floor"
    assert result["size"] == pytest.approx(1.96, abs=0.01)


def test_rounding_never_pushes_back_over_the_limit(monkeypatch):
    """A size below the minimum is 0.0, never stretched up to meet it.

    Rounding 0.003 up to volume_min would restore exactly the margin the cap
    just removed, and the caller would read a compliant size.
    """
    import challenge.leverage as lev
    monkeypatch.setattr(lev, "symbol_leverage", lambda symbol: SymbolLeverage(
        symbol=symbol, effective_leverage=10.0, margin_per_lot=10_000_000.0,
        notional_per_lot=100_000_000.0, measured_at=0.0))
    result = size_for_candidate("XAUUSD", risk_budget=1e9, risk_per_lot=1.0,
                                equity=100000.0)
    assert result["lots_by_margin_floor"] == pytest.approx(0.0033, abs=0.0001)
    assert result["size"] == 0.0
    assert "minimum volume" in result["reason"]


def test_the_margin_cap_is_scoped_to_a_real_venue_account(monkeypatch):
    """A simulated account must not be capped by a broker it never joined.

    `order_calc_margin` answers for whichever terminal is connected. When one is,
    the backtester -- a synthetic account on login 42000 with a 10k equity --
    was having its gold positions capped at ~0.08 lots by FTTrading-Server's
    margin model, which changed the outcome of a historical replay. A paper or
    backtest account has no broker relationship, so it has no broker margin
    model to apply.
    """
    import challenge.leverage as lev
    monkeypatch.setattr(lev, "symbol_leverage", lambda symbol: SymbolLeverage(
        symbol=symbol, effective_leverage=10.0, margin_per_lot=41574.0,
        notional_per_lot=415536.0, measured_at=0.0))

    class Venue:
        login = 1400167

    class NoTerminal:
        def account_info(self):
            return Venue()

    monkeypatch.setitem(sys.modules, "MetaTrader5", NoTerminal())

    g, _ = make_governor(equity=100000.0, symbols=("XAUUSD",))
    g._state.account.login = 1400167
    assert g._account_is_at_venue() is True
    assert g._margin_lot_cap(make_candidate()) is not None

    # The same live terminal, but a state belonging to a different account.
    simulated, _ = make_governor(equity=10000.0, symbols=("XAUUSD",))
    simulated._state.account.login = 42000
    assert simulated._account_is_at_venue() is False
    assert simulated._margin_lot_cap(make_candidate()) is None


def test_no_terminal_means_no_margin_cap(monkeypatch):
    """Without a connected terminal there is no broker margin model to read."""
    class NoTerminal:
        def account_info(self):
            return None

    monkeypatch.setitem(sys.modules, "MetaTrader5", NoTerminal())
    g, _ = make_governor()
    assert g._account_is_at_venue() is False
    assert g._margin_lot_cap(make_candidate()) is None


def test_a_legal_margin_capped_size_is_kept(monkeypatch):
    """The clamp is not all-or-nothing: 0.03 lots is tradeable and must survive."""
    import challenge.leverage as lev
    monkeypatch.setattr(lev, "symbol_leverage", lambda symbol: SymbolLeverage(
        symbol=symbol, effective_leverage=10.0, margin_per_lot=1_000_000.0,
        notional_per_lot=10_000_000.0, measured_at=0.0))
    result = size_for_candidate("XAUUSD", risk_budget=1e9, risk_per_lot=1.0,
                                equity=100000.0)
    assert result["size"] == pytest.approx(0.03)
    assert result["binding_limit"] == "margin_floor"


# -- Governor wiring ----------------------------------------------------
def make_governor(equity=100000.0, positions=(), symbols=("XAUUSD",)):
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=equity, equity=equity, margin=0.0))
    for sym in symbols:
        s.upsert_market(market(sym))
    for p in positions:
        s.add_position(p)
    return RiskGovernor(state_ref=s), s


@pytest.fixture
def managed(monkeypatch):
    """A governor on an account a challenge policy actually governs.

    The 2% cap is a registered challenge term, so it is deliberately inactive on
    an unmanaged account. Testing it therefore means making the account managed
    AND leaving behind the verdict `_check_challenge_policy` would have set --
    otherwise these tests would pass while asserting only the inactive path,
    which asserts nothing at all.
    """
    import challenge.live as live
    monkeypatch.setattr(live, "is_managed", lambda state_ref=None: True)

    def build(equity=100000.0, positions=(), symbols=("XAUUSD",)):
        g, s = make_governor(equity, positions, symbols)
        g._challenge_verdict = {"candidate_id": "c1",
                                "result": {"policy": None,
                                           "decision": {"permission": "allow"}}}
        return g, s

    return build


def make_candidate(symbol="XAUUSD", size=0.02, stop_distance=10.0):
    price = TICK[symbol]["price"]
    return TradeCandidate(candidate_id="c1", thesis_id="t1", symbol=symbol,
                          direction=TradeDirection.LONG, entry=price,
                          stop_loss=price - stop_distance,
                          take_profit=price + stop_distance * 2, size=size,
                          risk_reward=2.0, confidence=0.8)


def test_governor_refuses_a_book_it_cannot_measure(managed):
    """A stopless open position makes the book total unknown, so the gate halts.

    The unsafe alternative is to total only what is computable: the cap would
    then be judged against a book that silently excludes the position most
    likely to be the large one.

    Asserted on the cap check itself rather than through `veto_reason`, because
    on an unentitled account the entitlement gate vetoes first and the reason
    reported would be that one -- which would make this test pass for the wrong
    reason.
    """
    stopless = position("XAUUSD", 0.5, 10.0)
    stopless.sl = None
    g, _ = managed(positions=[stopless])
    reasons: list = []
    check = g._check_total_risk_cap(make_candidate(), reasons)
    assert check["passed"] is False
    assert check["detail"]["unmeasurable"] == ["XAUUSD"]
    assert "not measurable" in reasons[0]


def test_governor_allows_a_flat_book_under_the_cap(managed):
    g, _ = managed()
    assert g._check_total_risk_cap(make_candidate(), [])["passed"] is True


def test_the_cap_is_inactive_on_an_unmanaged_account():
    """A 2% term is not invented for accounts that were never given one.

    Without this, the gate would silently change the default risk behaviour of
    every demo and unmanaged account in the system.
    """
    held = position("XAUUSD", 0.5, 10.0)  # $500, inside a 2% cap anyway
    g, _ = make_governor(positions=[held])
    check = g._check_total_risk_cap(make_candidate(), [])
    assert check["detail"]["active"] is False
    assert check["passed"] is True


def test_governor_evaluates_the_cap_in_account_currency(managed):
    """EURUSD at 50 pips on 0.02 lots is $10, well inside the 2% cap.

    Priced with PositionState.risk instead of tick economics the same position
    would contribute 0.0001, and a book holding several of them would read as
    empty no matter how large it actually was.
    """
    held = position("EURUSD", volume=0.02, stop_distance=0.0050)  # $10
    g, _ = managed(positions=[held], symbols=("EURUSD",))
    new = make_candidate("EURUSD", size=0.02, stop_distance=0.0050)  # $10
    assert g._check_total_risk_cap(new, [])["passed"] is True


def test_governor_refuses_when_the_sum_breaks_the_cap(managed):
    """Two positions that each pass, whose SUM does not.

    This is the case netting hides: $1,500 of EURUSD and $1,500 of XAUUSD is a
    $3,000 book against a $2,000 cap, and neither leg is over on its own.
    """
    held_fx = position("EURUSD", volume=3.0, stop_distance=0.0050)   # $1,500
    held_xau = position("XAUUSD", volume=1.5, stop_distance=10.0)     # $1,500
    g, _ = managed(positions=[held_fx, held_xau],
                   symbols=("EURUSD", "XAUUSD"))
    new = make_candidate("XAUUSD", size=0.01, stop_distance=10.0)      # $50
    reasons: list = []
    result = g._check_total_risk_cap(new, reasons)
    assert result["passed"] is False
    assert result["detail"]["held_total"] == pytest.approx(3000.0)
    assert "without netting" in reasons[0]
    # Both legs carry $1,500, so the ordering between them is a float-precision
    # tie; what matters is that both are named as contributors.
    assert {c["symbol"] for c in result["detail"]["contributors"]} == {
        "EURUSD", "XAUUSD"}


def test_governor_cap_detail_reports_the_summed_total(managed):
    held = position("EURUSD", volume=0.02, stop_distance=0.0050)  # $10
    g, _ = managed(positions=[held], symbols=("EURUSD",))
    detail = g._check_total_risk_cap(make_candidate("EURUSD", size=0.0), [])["detail"]
    assert detail["held_total"] == pytest.approx(10.0)
    assert detail["cap_usd"] == pytest.approx(2000.0)
    assert detail["aggregation"] == "summed across symbols, not netted"
