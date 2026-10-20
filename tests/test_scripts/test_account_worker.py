"""Tests for the per-account MT5 worker (F5b).

The subject is the worker's *pure and quasi-pure* surface: which environment it
sets from an account's vault, what its health and sync report, and how its HTTP
handler routes. The terminal attach itself is the adapter's job and is covered
by the adapter tests; what matters here is that the worker never trades, never
claims to be attached when it is not, and never leaks a credential.

No real MT5, no real socket to an external host: the handler is exercised through
a loopback `ThreadingHTTPServer` on port 0 (an OS-picked free port), and the
adapter is a fake.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import account_worker as aw  # noqa: E402


class _FakeAdapter:
    def __init__(self, connect_ok=True):
        self._connect_ok = connect_ok
        self.connected = False
        self.attach_mode = None
        self._last_error = None
        self.syncs = []

    def connect(self):
        self.connected = bool(self._connect_ok)
        self.attach_mode = "credentials" if self._connect_ok else None
        if not self._connect_ok:
            self._last_error = "MT5_LOCKED: nope"
        return self._connect_ok

    def run_sync_cycle(self, symbols=None):
        self.syncs.append(symbols)
        return {"account": 1, "positions": 2}

    def disconnect(self):
        self.connected = False


# -- apply_account_env ----------------------------------------------------


def test_apply_account_env_is_a_noop_when_env_is_complete(monkeypatch):
    """The supervisor already passed credentials; do not re-read the vault."""
    monkeypatch.setenv("MT5_LOGIN", "1")
    monkeypatch.setenv("MT5_PASSWORD", "p")
    monkeypatch.setenv("MT5_SERVER", "s")

    def _boom(*_a, **_k):
        raise AssertionError("must not touch the registry when env is set")

    monkeypatch.setattr("accounts.registry.AccountRegistry", _boom)
    result = aw.apply_account_env("acct-x")
    assert result["set"] == []


def test_apply_account_env_fills_only_missing_keys(monkeypatch):
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.delenv(k, raising=False)

    class _Registry:
        def by_id(self, account_id):
            return {"account_id": account_id, "venue": "mt5"}

    class _Creds:
        def resolve_for_account(self, venue, account_id):
            return {"login": "TEST-ACCT-1", "password": "pw", "server": "S"}

    monkeypatch.setattr("accounts.registry.AccountRegistry", _Registry)
    monkeypatch.setattr("accounts.registry.CredentialService", _Creds)

    result = aw.apply_account_env("acct-1")
    assert set(result["set"]) == {"MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"}
    assert aw.os.environ["MT5_LOGIN"] == "TEST-ACCT-1"
    # And the returned map carries keys, never values.
    assert "pw" not in str(result)


def test_apply_account_env_refuses_a_non_mt5_account(monkeypatch):
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.delenv(k, raising=False)

    class _Registry:
        def by_id(self, account_id):
            return {"account_id": account_id, "venue": "binance"}

    monkeypatch.setattr("accounts.registry.AccountRegistry", _Registry)
    with pytest.raises(SystemExit) as exc:
        aw.apply_account_env("acct-cex")
    assert "MT5 only" in str(exc.value)


def test_apply_account_env_refuses_an_unknown_account(monkeypatch):
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.delenv(k, raising=False)

    class _Registry:
        def by_id(self, account_id):
            return None

    monkeypatch.setattr("accounts.registry.AccountRegistry", _Registry)
    with pytest.raises(SystemExit):
        aw.apply_account_env("ghost")


# -- WorkerState ----------------------------------------------------------


def test_health_is_honest_before_and_after_attach():
    state = aw.WorkerState("acct-1")
    assert state.health()["attached"] is False
    assert state.health()["account_id"] == "acct-1"
    assert state.health()["is_authorisation"] is False

    adapter = _FakeAdapter(connect_ok=True)
    assert state.attach(adapter) is True
    h = state.health()
    assert h["attached"] is True
    assert h["attach_mode"] == "credentials"
    assert h["role"] == "mt5_account_worker"


def test_attach_failure_is_reported_not_raised():
    state = aw.WorkerState("acct-1")
    adapter = _FakeAdapter(connect_ok=False)
    assert state.attach(adapter) is False
    assert "MT5_LOCKED" in state.health()["last_error"]
    assert state.health()["attached"] is False


def test_sync_without_an_attachment_refuses():
    state = aw.WorkerState("acct-1")
    result = state.sync()
    assert result["ok"] is False
    assert "no terminal" in result["error"]


def test_sync_counts_and_reports_no_trade():
    state = aw.WorkerState("acct-1")
    state.attach(_FakeAdapter(connect_ok=True))
    result = state.sync(["XAUUSD"])
    assert result["ok"] is True
    assert result["cycles"] == 1
    # The report is counts; it carries no order result and no is_authorisation.
    assert "order" not in json.dumps(result).lower()


def test_sync_swallows_adapter_error_into_the_report(monkeypatch):
    state = aw.WorkerState("acct-1")
    adapter = _FakeAdapter(connect_ok=True)

    def boom(symbols=None):
        raise RuntimeError("terminal went away")

    adapter.run_sync_cycle = boom
    state.attach(adapter)
    result = state.sync()
    assert result["ok"] is False
    assert "terminal went away" in result["error"]
    assert state.health()["last_error"] == "terminal went away"


# -- HTTP handler ---------------------------------------------------------


@pytest.fixture
def live_worker():
    """A real ThreadingHTTPServer on a free port, with a fake adapter."""
    from http.server import ThreadingHTTPServer

    state = aw.WorkerState("acct-1")
    state.attach(_FakeAdapter(connect_ok=True))
    handler = aw.build_handler(state, token="")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port, state
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def test_handler_health_route(live_worker):
    port, _ = live_worker
    status, body = _get(f"http://127.0.0.1:{port}/worker/health")
    assert status == 200
    assert body["role"] == "mt5_account_worker"
    assert body["attached"] is True


def test_handler_sync_route(live_worker):
    port, state = live_worker
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/worker/sync", method="POST",
        data=json.dumps({"symbols": ["XAUUSD"]}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        body = json.loads(r.read().decode())
    assert body["ok"] is True
    assert state.cycles == 1


def test_handler_unknown_route_is_404(live_worker):
    port, _ = live_worker
    try:
        _get(f"http://127.0.0.1:{port}/worker/trade")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:  # pragma: no cover
        pytest.fail("there must be no trade route on a worker")


def test_handler_requires_the_token_when_set():
    from http.server import ThreadingHTTPServer

    state = aw.WorkerState("acct-1")
    state.attach(_FakeAdapter(connect_ok=True))
    handler = aw.build_handler(state, token="s3cret")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        try:
            _get(f"http://127.0.0.1:{port}/worker/health")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            pytest.fail("a token-protected worker must refuse an anonymous read")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/worker/health",
            headers={"Authorization": "Bearer s3cret"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


# -- main -----------------------------------------------------------------


def test_main_requires_a_port(capsys):
    assert aw.main(["--account-id", "acct-1"]) == 2
    assert "--port is required" in capsys.readouterr().err


def test_main_rejects_an_unknown_account(monkeypatch, capsys):
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.delenv(k, raising=False)

    class _Registry:
        def by_id(self, account_id):
            return None

    monkeypatch.setattr("accounts.registry.AccountRegistry", _Registry)
    rc = aw.main(["--port", "8123", "--account-id", "ghost"])
    assert rc == 2
    assert "no account" in capsys.readouterr().err
