"""Tests for the AccountSupervisor: port planning and runtime bookkeeping.

The subject is the pure planning half of per-account engine processes (F5a) --
which account may start, on which port, and what runtime is recorded -- tested
without spawning anything. The assertions are about facts that would be silently
wrong: an account started with half its credentials, two accounts handed the same
port, a stopped account still advertising a worker, an orphaned pid never
reconciled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from accounts.registry import (  # noqa: E402
    MT5_TERMINAL,
    AccountRegistry,
    CredentialService,
)
from accounts.supervisor import (  # noqa: E402
    AccountSupervisor,
    LaunchPlan,
    SupervisorError,
    default_spawn,
    port_range,
)
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    AccountConnectionRepository,
    AccountRegistryRepository,
)


class _FakeVault:
    """A dict-backed stand-in for SecretsVault.

    The real vault is DPAPI-backed and Windows-only; the supervisor's job is to
    *ask* for a complete credential set, not to encrypt, so the test injects a
    store that answers `exists`/`resolve` without touching the platform. It still
    enforces the one rule that matters here: only known slot names are accepted,
    mirroring what the vault would reject.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, slot: str, value: str) -> None:
        from core.secrets_vault import is_known_slot

        if not is_known_slot(slot):
            raise KeyError(f"unknown slot {slot!r}")
        self._store[slot] = value

    def resolve(self, slot: str) -> str:
        return self._store.get(slot, "")

    def exists(self, slot: str) -> bool:
        return slot in self._store

    def delete_account_slots(self, kind: str, account_id: str,
                             venue: str = "") -> int:
        from core.secrets_vault import account_slots

        slots = account_slots(kind, account_id, venue) if kind == "cex" \
            else account_slots(kind, account_id)
        n = 0
        for slot in slots.values():
            if slot in self._store:
                del self._store[slot]
                n += 1
        return n


@pytest.fixture
def session():
    s = bind_test_session()
    from sqlalchemy import delete

    for model in (AccountConnectionRecord, AccountIdentityRecord,
                  AccountRecord):
        s.execute(delete(model))
    s.commit()
    return s


@pytest.fixture
def vault():
    return _FakeVault()


@pytest.fixture
def stack(session, vault, monkeypatch):
    """(registry, connections, credentials) sharing one session and vault."""
    registry = AccountRegistry(AccountRegistryRepository(session))
    connections = AccountConnectionRepository(session)
    # AccountRegistry builds its own connections repo off the injected session;
    # point both at the same one so the supervisor's writes are visible to the
    # test's reads.
    registry._connections = connections
    credentials = CredentialService(vault_obj=vault)
    return registry, connections, credentials


def _mt5_account(registry, vault, credentials, *, login="TEST-ACCT-1",
                 complete=True):
    account = registry.register(venue="mt5", venue_login=login,
                                venue_server="FTTrading-Server",
                                owner_user_id="op-1")
    if complete:
        credentials.set_credentials("mt5", account["account_id"], {
            "login": login, "password": "pw", "server": "FTTrading-Server"})
    return account


# -- planning -------------------------------------------------------------


def test_plan_refuses_an_account_it_does_not_know(stack):
    registry, _, credentials = stack
    sup = AccountSupervisor(registry=registry,
                            connections=stack[1], credentials=credentials)
    with pytest.raises(SupervisorError) as exc:
        sup.plan("no-such-account")
    assert "no account" in str(exc.value)


def test_plan_refuses_a_non_mt5_account(stack):
    registry, connections, credentials = stack
    cex = registry.register_cex(venue="binance", venue_login="binance-main",
                                owner_user_id="op-1")
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    with pytest.raises(SupervisorError) as exc:
        sup.plan(cex["account_id"])
    assert "only 'mt5'" in str(exc.value)


def test_plan_refuses_a_half_credentialled_account(stack):
    """A half-set MT5 account attaches to whatever terminal is running.

    That is the worse failure: it connects by attach and can trade on the wrong
    login. The supervisor must refuse to start it, not start it hopefully.
    """
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials, complete=False)
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    with pytest.raises(SupervisorError) as exc:
        sup.plan(account["account_id"])
    assert "missing" in str(exc.value)


def test_plan_carries_the_resolved_credentials_and_a_port(stack):
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    plan = sup.plan(account["account_id"])
    assert isinstance(plan, LaunchPlan)
    assert plan.venue == "mt5"
    assert plan.env["MT5_LOGIN"] == "TEST-ACCT-1"
    assert plan.env["MT5_PASSWORD"] == "pw"
    assert plan.env["MT5_SERVER"] == "FTTrading-Server"
    base, count = port_range()
    assert base <= plan.port < base + count


def test_public_plan_never_leaks_the_password(stack):
    """A plan may be logged or returned; the env holds secrets."""
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    plan = sup.plan(account["account_id"])
    public = plan.as_public()
    assert "env" not in public
    assert "pw" not in str(public)
    assert "MT5_PASSWORD" in public["env_keys"]


# -- port allocation ------------------------------------------------------


def test_two_accounts_never_share_a_port(stack):
    registry, connections, credentials = stack
    a = _mt5_account(registry, None, credentials, login="TEST-ACCT-1")
    b = _mt5_account(registry, None, credentials, login="TEST-ACCT-2")
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    pa = sup.plan(a["account_id"]).port
    # Record a's runtime so b must avoid a's port.
    connections.set_runtime(a["account_id"], MT5_TERMINAL, pid=1111, port=pa)
    pb = sup.plan(b["account_id"]).port
    assert pa != pb


def test_recorded_port_is_reused_when_free(stack):
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    first = sup.plan(account["account_id"]).port
    connections.set_runtime(account["account_id"], MT5_TERMINAL, pid=2222,
                            port=first)
    again = sup.plan(account["account_id"]).port
    assert again == first


def test_port_allocation_is_bounded_and_fails_loudly(stack, monkeypatch):
    """When every port is taken, refuse -- never reuse and collide."""
    registry, connections, credentials = stack
    monkeypatch.setenv("TRADERAIG_ACCOUNT_PORT_BASE", "8200")
    monkeypatch.setenv("TRADERAIG_ACCOUNT_PORT_COUNT", "1")
    account = _mt5_account(registry, None, credentials)
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    # A different account holds the one port in range.
    other = _mt5_account(registry, None, credentials, login="TEST-ACCT-3")
    connections.set_runtime(other["account_id"], MT5_TERMINAL, pid=3333,
                            port=8200)
    with pytest.raises(SupervisorError) as exc:
        sup.plan(account["account_id"])
    assert "no free port" in str(exc.value)


# -- runtime --------------------------------------------------------------


def test_start_without_a_launcher_refuses_rather_than_lie(stack):
    """No spawn configured -> refuse. Never record a worker that did not start."""
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials, spawn=None)
    with pytest.raises(SupervisorError) as exc:
        sup.start(account["account_id"])
    assert "no process launcher" in str(exc.value)
    # And nothing was recorded.
    assert sup.runtime(account["account_id"])["pid"] is None


def test_start_records_the_runtime_the_launcher_returned(stack):
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    seen = {}

    def fake_spawn(plan):
        seen["plan"] = plan
        return 4242

    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials, spawn=fake_spawn)
    result = sup.start(account["account_id"])
    assert result["started"] is True
    assert result["pid"] == 4242
    assert result["port"] == seen["plan"].port
    assert result["status"] == "starting"
    assert result["is_authorisation"] is False


def test_start_refuses_a_second_engine_on_a_live_pid(stack, monkeypatch):
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials, spawn=lambda p: 5555)
    # Pretend the recorded pid is alive.
    monkeypatch.setattr("accounts.supervisor.pid_alive", lambda pid: True)
    connections.set_runtime(account["account_id"], MT5_TERMINAL, pid=5555,
                            port=8150)
    with pytest.raises(SupervisorError) as exc:
        sup.start(account["account_id"])
    assert "already has a running engine" in str(exc.value)


def test_stop_forgets_the_pid_and_reports_it(stack):
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    connections.set_runtime(account["account_id"], MT5_TERMINAL, pid=6001,
                            port=8160, status="connected")
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    result = sup.stop(account["account_id"], reason="operator stop")
    assert result["stopped"] is True
    assert result["forgot_pid"] == 6001
    after = sup.runtime(account["account_id"])
    assert after["pid"] is None
    assert after["port"] is None
    assert after["status"] == "disconnected"


def test_runtime_reports_no_connection_honestly(stack):
    registry, connections, credentials = stack
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    status = sup.runtime("never-registered")
    assert status["known_connection"] is False
    assert status["is_authorisation"] is False


# -- reconcile ------------------------------------------------------------


def test_reconcile_clears_an_orphaned_pid(stack, monkeypatch):
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    connections.set_runtime(account["account_id"], MT5_TERMINAL, pid=7007,
                            port=8170, status="connected")
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    monkeypatch.setattr("accounts.supervisor.pid_alive", lambda pid: False)
    report = sup.reconcile()
    assert report["orphan_count"] == 1
    assert report["orphans"][0]["pid"] == 7007
    assert sup.runtime(account["account_id"])["pid"] is None


def test_reconcile_keeps_a_live_pid(stack, monkeypatch):
    registry, connections, credentials = stack
    account = _mt5_account(registry, None, credentials)
    connections.set_runtime(account["account_id"], MT5_TERMINAL, pid=8008,
                            port=8180, status="connected")
    sup = AccountSupervisor(registry=registry, connections=connections,
                            credentials=credentials)
    monkeypatch.setattr("accounts.supervisor.pid_alive", lambda pid: True)
    report = sup.reconcile()
    assert report["live_count"] == 1
    assert report["orphan_count"] == 0
    assert sup.runtime(account["account_id"])["pid"] == 8008


# -- schema ---------------------------------------------------------------


def test_connection_row_carries_the_runtime_columns(session):
    """The runtime columns exist and are additive/nullable."""
    cols = {c.name for c in AccountConnectionRecord.__table__.columns}
    assert {"pid", "port", "instance"} <= cols
    for name in ("pid", "port", "instance"):
        assert AccountConnectionRecord.__table__.columns[name].nullable is True


# -- launcher wiring ------------------------------------------------------


def test_with_launcher_wires_the_project_launcher(stack):
    registry, connections, credentials = stack
    sup = AccountSupervisor.with_launcher(
        registry=registry, connections=connections, credentials=credentials)
    assert sup._spawn is default_spawn


def test_default_spawn_uses_the_project_detached_launcher(monkeypatch, tmp_path):
    """`default_spawn` must delegate to `_start_detached`, not re-implement it.

    A second process model is the drift this wiring exists to avoid, so the test
    asserts the delegation and the shape of the arguments: argv carries only the
    port, the credential env is passed as an overlay, and the log name is
    account-derived.
    """
    captured = {}

    def fake_start_detached(cmd, cwd, log_name, extra_env=None):
        captured["cmd"] = cmd
        captured["log_name"] = log_name
        captured["env"] = extra_env or {}
        return 9090

    import tools.tradraig as tradraig
    monkeypatch.setattr(tradraig, "_start_detached", fake_start_detached)

    plan = LaunchPlan(account_id="acct-abcdef123456", venue="mt5", port=8150,
                      instance="mt5-acct-abc",
                      command=["python", "-m", "scripts.account_worker",
                               "--port", "8150"],
                      env={"MT5_LOGIN": "TEST-ACCT-1", "MT5_PASSWORD": "pw",
                           "MT5_SERVER": "S"})
    pid = default_spawn(plan)
    assert pid == 9090
    assert captured["cmd"][-1] == "8150"
    assert "pw" not in captured["log_name"]
    assert captured["env"]["MT5_PASSWORD"] == "pw"
    assert captured["env"]["TRADERAIG_ACCOUNT_PORT"] == "8150"
    assert captured["log_name"] == "account-acct-abcdef1"
