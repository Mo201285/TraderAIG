"""Tests for the account-worker execution bridge (F5c).

The subject is the seam, not MT5: a worker may execute only a well-formed,
pre-approved frame for its own account; a retried frame is idempotent; an
account's worker is never bypassed by the local terminal when it is recorded;
and account-scoped reconciliation cannot close another account's live position.
"""
from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import execution.mt5_adapter as mt5_module  # noqa: E402
from accounts.worker_auth import worker_token  # noqa: E402
from core.contracts import Candle, TradeDirection  # noqa: E402
from core.state import CanonicalState, MarketState, PositionState  # noqa: E402
from decision.candidate import TradeCandidate  # noqa: E402
from execution.engine import ExecutionStatus  # noqa: E402
from execution.mt5_adapter import LiveMT5Executor, MT5Adapter  # noqa: E402
from execution.worker_client import (  # noqa: E402
    WorkerClient,
    WorkerEndpoint,
    WorkerError,
    endpoint_for,
)
from risk.governor import RiskDecisionKind  # noqa: E402
from scripts.account_worker import (  # noqa: E402
    WorkerState,
    _validate_order_frame,
    build_handler,
)

ACCOUNT_A = "TEST-ACCT-A"
ACCOUNT_B = "TEST-ACCT-B"


class FakeAdapter:
    """A terminal stand-in: records calls, returns a fixed open position."""

    connected = True

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = []
        self.candle_calls = []
        self.quote_calls = []
        self.fail = fail
        self.positions_ = []
        self._last_error = None
        self._strategy_by_position = {}

    def connect(self) -> bool:
        return True

    def place_position(self, candidate, decision_kind):
        self.calls.append((candidate, decision_kind))
        if self.fail:
            self._last_error = "no money"
            return None
        return PositionState(
            position_id="555",
            symbol=candidate.symbol,
            direction=candidate.direction,
            volume=candidate.size,
            entry_price=100.0,
            current_price=100.0,
            sl=candidate.stop_loss,
            tp=candidate.take_profit,
            strategy_id=candidate.strategy_id,
        )

    def status(self):
        return {"last_error": self._last_error}

    def sync_positions(self):
        return list(self.positions_)

    def fetch_candles(self, symbol, timeframe="M15", count=300):
        self.candle_calls.append((symbol, timeframe, count))
        return [Candle(symbol=symbol, timeframe=timeframe, time=1000.0 + i,
                       open=100.0 + i, high=101.0 + i, low=99.0 + i,
                       close=100.5 + i, volume=10.0, tick_volume=5.0)
                for i in range(2)]

    def sync_market_all(self, symbols):
        self.quote_calls.append(list(symbols))
        return [MarketState(symbol=s, bid=100.0, ask=100.1, spread=0.1,
                            last_price=100.0, last_tick_time=1000.0,
                            contract_size=1.0)
                for s in symbols]


def _frame(**overrides):
    frame = {
        "candidate_id": "cand-1",
        "thesis_id": "thesis-1",
        "symbol": "BTCUSD",
        "direction": "long",
        "volume": 0.1,
        "entry": 100.0,
        "stop_loss": 99.0,
        "take_profit": 102.0,
        "risk_reward": 2.0,
        "confidence": 0.8,
        "priority": 83,
        "strategy_id": "btcusd:ict_liquidity_sweep_reversal:v7",
        "account_id": "",
    }
    frame.update(overrides)
    return frame


def _candidate(**overrides):
    data = dict(
        candidate_id="cand-exec-1",
        thesis_id="thesis-exec-1",
        symbol="BTCUSD",
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        size=0.1,
        risk_reward=2.0,
        confidence=0.8,
        strategy_id="btcusd:ict_liquidity_sweep_reversal:v7",
    )
    data.update(overrides)
    return TradeCandidate(**data)


@pytest.fixture
def fresh_state(monkeypatch):
    store = CanonicalState()
    monkeypatch.setattr(mt5_module, "state", store)
    return store


@pytest.fixture
def worker_server():
    servers = []

    def start(state: WorkerState, token: str = "") -> int:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                    build_handler(state, token=token))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return int(httpd.server_address[1])

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


# -- frame validation -----------------------------------------------------


def test_frame_requires_its_own_account_and_a_positive_volume():
    """A worker must refuse a frame addressed to a different login."""
    with pytest.raises(ValueError, match="does not match"):
        _validate_order_frame(_frame(account_id=ACCOUNT_A), ACCOUNT_B)
    with pytest.raises(ValueError, match="volume"):
        _validate_order_frame(_frame(volume=0), ACCOUNT_A)
    with pytest.raises(ValueError, match="direction"):
        _validate_order_frame(_frame(direction="sideways"), ACCOUNT_A)
    with pytest.raises(ValueError, match="idempotency"):
        _validate_order_frame(_frame(candidate_id=""), ACCOUNT_A)
    with pytest.raises(ValueError, match="finite"):
        _validate_order_frame(_frame(volume=float("nan")), ACCOUNT_A)


def test_frame_normalises_but_does_not_invent_policy():
    frame = _validate_order_frame(_frame(symbol=" btcusd ", direction="SHORT"),
                                  ACCOUNT_A)
    assert frame["symbol"] == "BTCUSD"
    assert frame["direction"] == "short"
    # No sizing, no veto: the volume is carried through verbatim.
    assert frame["volume"] == 0.1


# -- worker order route ---------------------------------------------------


def test_place_is_idempotent_by_candidate_id():
    adapter = FakeAdapter()
    state = WorkerState(ACCOUNT_A)
    assert state.attach(adapter)

    first = state.place(_frame())
    second = state.place(_frame())

    assert first["ok"] is True and first["duplicate"] is False
    assert second["ok"] is True and second["duplicate"] is True
    assert second["position"]["position_id"] == first["position"]["position_id"]
    assert len(adapter.calls) == 1
    assert state.orders == 1


def test_place_tags_the_returned_position_with_its_account():
    state = WorkerState(ACCOUNT_A)
    state.attach(FakeAdapter())
    result = state.place(_frame())
    assert result["position"]["account_id"] == ACCOUNT_A
    assert result["position"]["venue"] == "mt5"


def test_place_refuses_when_no_terminal_is_attached():
    state = WorkerState(ACCOUNT_A)
    result = state.place(_frame())
    assert result["ok"] is False and result["status"] == 503


def test_place_reports_a_rejected_fill_and_allows_a_retry():
    adapter = FakeAdapter(fail=True)
    state = WorkerState(ACCOUNT_A)
    state.attach(adapter)

    failed = state.place(_frame())
    adapter.fail = False
    retried = state.place(_frame())

    assert failed["ok"] is False and failed["status"] == 502
    assert failed["duplicate"] is False
    assert retried["ok"] is True and retried["duplicate"] is False
    assert len(adapter.calls) == 2


def test_http_order_route_requires_the_bearer_and_is_idempotent(worker_server):
    adapter = FakeAdapter()
    state = WorkerState(ACCOUNT_A)
    state.attach(adapter)
    port = worker_server(state, token="tok")
    good = WorkerClient(WorkerEndpoint(ACCOUNT_A, port, "tok"), timeout=5)
    bad = WorkerClient(WorkerEndpoint(ACCOUNT_A, port, "wrong"), timeout=5)

    with pytest.raises(WorkerError) as exc:
        bad.place_order(_frame())
    assert exc.value.status == 401

    first = good.place_order(_frame())
    second = good.place_order(_frame())
    assert first["ok"] and not first["duplicate"]
    assert second["duplicate"] is True
    assert len(adapter.calls) == 1

    health = good.health()
    assert health["orders"] == 1
    assert health["trade_authority"] == "risk/governor.py"


def test_http_positions_route_returns_the_terminal_rows(worker_server):
    adapter = FakeAdapter()
    adapter.positions_ = [PositionState(
        position_id="777", symbol="BTCUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=100.0, current_price=101.0)]
    state = WorkerState(ACCOUNT_A)
    state.attach(adapter)
    port = worker_server(state)

    payload = WorkerClient(WorkerEndpoint(ACCOUNT_A, port)).positions()
    assert payload["ok"] is True
    assert [p["position_id"] for p in payload["positions"]] == ["777"]


def test_http_candles_route_returns_the_workers_own_window(worker_server):
    adapter = FakeAdapter()
    state = WorkerState(ACCOUNT_A)
    state.attach(adapter)
    port = worker_server(state)
    client = WorkerClient(WorkerEndpoint(ACCOUNT_A, port), timeout=5)

    payload = client.candles("btcusd", "M15", 2)
    assert payload["ok"] is True
    assert payload["account_id"] == ACCOUNT_A
    assert payload["symbol"] == "BTCUSD"
    assert [c["close"] for c in payload["candles"]] == [100.5, 101.5]
    assert adapter.candle_calls == [("BTCUSD", "M15", 2)]

    with pytest.raises(WorkerError) as exc:
        client.candles("BTCUSD", "M15", 0)
    assert exc.value.status == 400


def test_http_quotes_route_returns_only_the_market_fields(worker_server):
    adapter = FakeAdapter()
    state = WorkerState(ACCOUNT_A)
    state.attach(adapter)
    port = worker_server(state)
    client = WorkerClient(WorkerEndpoint(ACCOUNT_A, port), timeout=5)

    payload = client.quotes(["btcusd", "XAUUSD"])
    assert payload["ok"] is True
    assert [q["symbol"] for q in payload["quotes"]] == ["BTCUSD", "XAUUSD"]
    assert set(payload["quotes"][0]) == {
        "symbol", "bid", "ask", "spread", "last_price", "last_tick_time",
        "tick_size", "tick_value", "contract_size", "volume_min",
        "volume_step", "volume_max"}
    assert adapter.quote_calls == [["BTCUSD", "XAUUSD"]]


# -- routing --------------------------------------------------------------


def test_executor_routes_to_the_worker_and_never_touches_the_local_terminal(
        fresh_state, worker_server):
    worker_adapter = FakeAdapter()
    worker = WorkerState(ACCOUNT_B)
    worker.attach(worker_adapter)
    port = worker_server(worker)
    endpoint = WorkerEndpoint(ACCOUNT_B, port)

    class LocalMustNotTrade(FakeAdapter):
        def place_position(self, candidate, decision_kind):  # pragma: no cover
            raise AssertionError("local terminal must not trade for ACCOUNT_B")

        def _lazy_connect_if_possible(self):
            raise AssertionError("local terminal must not be used for ACCOUNT_B")

    executor = LiveMT5Executor(LocalMustNotTrade(), account_id=ACCOUNT_B,
                               endpoint_resolver=lambda _aid: endpoint)
    ticket = executor.execute(_candidate(),
                              SimpleNamespace(kind=RiskDecisionKind.APPROVED))

    assert ticket.status == ExecutionStatus.FILLED
    assert len(worker_adapter.calls) == 1
    pos = fresh_state.get_position("555")
    assert pos is not None and pos.account_id == ACCOUNT_B
    assert ACCOUNT_B in executor._workers


def test_worker_failure_is_an_error_not_a_fallback(
        fresh_state, worker_server):
    worker = WorkerState(ACCOUNT_B)
    worker.attach(FakeAdapter(fail=True))
    port = worker_server(worker)

    class LocalMustNotTrade(FakeAdapter):
        def place_position(self, candidate, decision_kind):  # pragma: no cover
            raise AssertionError("must not fall back to the local terminal")

        def _lazy_connect_if_possible(self):
            raise AssertionError("must not fall back to the local terminal")

    executor = LiveMT5Executor(LocalMustNotTrade(), account_id=ACCOUNT_B,
                               endpoint_resolver=lambda _aid: WorkerEndpoint(
                                   ACCOUNT_B, port))
    ticket = executor.execute(_candidate(),
                              SimpleNamespace(kind=RiskDecisionKind.APPROVED))
    assert ticket.status == ExecutionStatus.REJECTED
    assert fresh_state.open_positions() == []


def test_remote_sync_closes_only_positions_owned_by_that_account(
        fresh_state, worker_server):
    worker_adapter = FakeAdapter()
    worker_adapter.positions_ = [PositionState(
        position_id="888", symbol="BTCUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=100.0, current_price=101.0)]
    worker = WorkerState(ACCOUNT_B)
    worker.attach(worker_adapter)
    port = worker_server(worker)

    fresh_state.add_position(PositionState(
        position_id="777", symbol="BTCUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=100.0, current_price=100.0,
        account_id=ACCOUNT_B))
    other = PositionState(
        position_id="999", symbol="XAUUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=2000.0, current_price=2001.0,
        account_id=ACCOUNT_A)
    fresh_state.add_position(other)

    executor = LiveMT5Executor(FakeAdapter(), account_id=ACCOUNT_B)
    executor._workers[ACCOUNT_B] = WorkerEndpoint(ACCOUNT_B, port)
    executor.sync_remote_accounts()

    assert fresh_state.get_position("777").status.value == "closed"
    assert fresh_state.get_position("999").status.value == "open"
    assert fresh_state.get_position("888") is not None


# -- adapter and router scoping ------------------------------------------


def test_adapter_sync_does_not_close_another_accounts_position(fresh_state,
                                                              monkeypatch):
    class NoPositions:
        @staticmethod
        def positions_get():
            return []

    monkeypatch.setattr(mt5_module, "_mt5", lambda: NoPositions())
    adapter = MT5Adapter()
    monkeypatch.setattr(adapter, "account_id", lambda: ACCOUNT_A)

    fresh_state.add_position(PositionState(
        position_id="A1", symbol="EURUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=1.0, current_price=1.0, account_id=ACCOUNT_A))
    fresh_state.add_position(PositionState(
        position_id="B1", symbol="BTCUSD", direction=TradeDirection.LONG,
        volume=0.1, entry_price=100.0, current_price=100.0,
        account_id=ACCOUNT_B))

    adapter.sync_positions()
    assert fresh_state.get_position("A1").status.value == "closed"
    assert fresh_state.get_position("B1").status.value == "open"


def test_adapter_resolves_its_account_from_the_registry(monkeypatch):
    """The live process must find its own registry row by (login, server)."""
    from accounts import registry as registry_module

    class Registry:
        def for_login(self, venue, login, server):
            assert (venue, login, server) == (
                "mt5", "99887766", "FTTrading-Server")
            return {"account_id": ACCOUNT_A}

    monkeypatch.setattr(registry_module, "AccountRegistry", Registry)
    monkeypatch.setattr(mt5_module, "settings", SimpleNamespace(
        mt5=SimpleNamespace(login=99887766, server="FTTrading-Server")))

    adapter = MT5Adapter()
    assert adapter.account_id() == ACCOUNT_A
    assert adapter.account_id() == ACCOUNT_A
    adapter.forget_account_identity()
    assert adapter.account_id() == ACCOUNT_A


def test_worker_token_is_per_account_and_deterministic(monkeypatch):
    monkeypatch.setenv("TRADERAIG_WORKER_SECRET", "test-secret")
    a = worker_token(ACCOUNT_A)
    assert a == worker_token(ACCOUNT_A)
    assert a != worker_token(ACCOUNT_B)
    assert len(a) == 64


def test_endpoint_for_reads_the_recorded_runtime(monkeypatch):
    from accounts import supervisor as supervisor_module

    monkeypatch.setenv("TRADERAIG_WORKER_SECRET", "test-secret")
    monkeypatch.setattr(
        supervisor_module.AccountSupervisor, "runtime",
        lambda self, account_id: {
            "known_connection": True, "port": 8123, "status": "connected",
            "pid": 4242, "process_alive": True})
    endpoint = endpoint_for(ACCOUNT_A)
    assert endpoint is not None and endpoint.port == 8123
    assert endpoint.token == worker_token(ACCOUNT_A)

    monkeypatch.setattr(
        supervisor_module.AccountSupervisor, "runtime",
        lambda self, account_id: {
            "known_connection": True, "port": 8123, "status": "connected",
            "pid": 4242, "process_alive": False})
    assert endpoint_for(ACCOUNT_A) is None

    monkeypatch.setattr(
        supervisor_module.AccountSupervisor, "runtime",
        lambda self, account_id: {"known_connection": False})
    assert endpoint_for(ACCOUNT_A) is None
