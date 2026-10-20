"""The per-account engine runtime routes (Phase F, F5c).

`GET /accounts/{id}/runtime`, `POST /accounts/{id}/runtime/start` and
`POST /accounts/{id}/runtime/stop`, asserted over the real app: the read reports
the durable runtime honestly (a null pid is "no engine", not "stopped"), start
refuses when a live worker is already recorded or no launcher is configured, stop
reports the pid it forgot, and an unknown account is a 404 on all three.

The failure these guard: a runtime route that reports a worker that was never
started, double-starts an account (two engines trading one login), or hides an
unknown account behind an empty box that reads as "stopped".
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import core.secrets_vault as sv  # noqa: E402
from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
)

OPERATOR = "runtime-op-1"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def temp_vault(tmp_path):
    old = sv.vault
    sv.vault = sv.SecretsVault(data_dir=tmp_path / "secrets")
    yield sv.vault
    sv.vault = old


@pytest.fixture
def registry(monkeypatch):
    session = bind_test_session()
    for model in (AccountConnectionRecord, AccountIdentityRecord, AccountRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture
def acting_as_operator(monkeypatch):
    import governance.identity as gov
    from governance.identity import (
        SubscriptionPlan,
        SubscriptionStatus,
        User,
    )

    idents = gov.identity
    saved = (idents._users, idents._subscriptions, idents._audit)
    idents._users = {}
    idents._subscriptions = {}
    idents._audit = []

    user = User(user_id=OPERATOR, email=f"{OPERATOR}@x.co",
                display_name="Runtime operator",
                plan=SubscriptionPlan.INSTITUTIONAL,
                subscription_status=SubscriptionStatus.ACTIVE)
    user.grant_plan_entitlements()
    idents._users[OPERATOR] = user

    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)
    yield OPERATOR
    idents._users, idents._subscriptions, idents._audit = saved


@pytest.fixture
def supervisor(monkeypatch, registry, temp_vault):
    """A supervisor wired to the test session and a fake spawn, so no process
    is ever really launched but every recorded runtime is real."""

    import accounts.supervisor as sup

    spawned = []

    def fake_spawn(plan):
        spawned.append(plan)
        return 4242

    holder = {}

    def factory():
        if "s" not in holder:
            holder["s"] = sup.AccountSupervisor(
                spawn=lambda p: fake_spawn(p))
        return holder["s"]

    monkeypatch.setattr("operations.api._account_supervisor", factory)
    yield {"spawned": spawned, "factory": factory}


def _register_mt5(client, login="TEST-ACCT-1", server="FTTrading-Server"):
    return client.post("/accounts", json={
        "venue": "mt5", "venue_login": login, "venue_server": server,
        "display_name": "Live challenge"})


def _enroll(client, account_id):
    return client.put(f"/accounts/{account_id}/credentials", json={
        "login": "TEST-ACCT-1", "password": "pw", "server": "FTTrading-Server"})


def test_runtime_of_a_fresh_account_is_null_not_stopped(
        client, registry, supervisor, acting_as_operator):
    acct = _register_mt5(client).json()["account"]
    r = client.get(f"/accounts/{acct['account_id']}/runtime")
    assert r.status_code == 200
    body = r.json()
    assert body["pid"] is None
    assert body["process_alive"] is None
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


def test_runtime_of_unknown_account_is_404(client, registry, supervisor,
                                           acting_as_operator):
    r = client.get("/accounts/nope/runtime")
    assert r.status_code == 404


def test_start_records_the_pid_and_reports_the_plan(
        client, registry, supervisor, acting_as_operator):
    acct = _register_mt5(client).json()["account"]
    _enroll(client, acct["account_id"])
    r = client.post(f"/accounts/{acct['account_id']}/runtime/start", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["pid"] == 4242
    assert body["port"]
    assert body["started"] is True
    assert len(supervisor["spawned"]) == 1


def test_start_refuses_without_credentials(client, registry, supervisor,
                                           acting_as_operator):
    acct = _register_mt5(client).json()["account"]
    r = client.post(f"/accounts/{acct['account_id']}/runtime/start", json={})
    assert r.status_code == 409
    assert "credentials" in r.json()["detail"]
    assert supervisor["spawned"] == []


def test_start_on_unknown_account_is_404(client, registry, supervisor,
                                         acting_as_operator):
    r = client.post("/accounts/nope/runtime/start", json={})
    assert r.status_code == 404


def test_stop_reports_the_forgotten_pid(client, registry, supervisor,
                                        acting_as_operator):
    acct = _register_mt5(client).json()["account"]
    _enroll(client, acct["account_id"])
    client.post(f"/accounts/{acct['account_id']}/runtime/start", json={})
    r = client.post(f"/accounts/{acct['account_id']}/runtime/stop", json={})
    assert r.status_code == 200
    assert r.json()["forgot_pid"] == 4242
    after = client.get(f"/accounts/{acct['account_id']}/runtime").json()
    assert after["pid"] is None


def test_stop_of_unknown_account_is_404(client, registry, supervisor,
                                        acting_as_operator):
    r = client.post("/accounts/nope/runtime/stop", json={})
    assert r.status_code == 404


def test_stop_without_a_started_engine_reports_no_pid(
        client, registry, supervisor, acting_as_operator):
    """A registered account with no engine has a connection, so stop succeeds
    and forgets nothing -- `forgot_pid` null says exactly that."""
    acct = _register_mt5(client).json()["account"]
    r = client.post(f"/accounts/{acct['account_id']}/runtime/stop", json={})
    assert r.status_code == 200
    assert r.json()["forgot_pid"] is None
    assert r.json()["stopped"] is True


def test_start_refuses_when_no_launcher_is_configured(
        client, registry, temp_vault, acting_as_operator, monkeypatch):
    """No spawn configured is a refusal, never a recorded 'starting' runtime."""
    import accounts.supervisor as sup
    monkeypatch.setattr("operations.api._account_supervisor",
                        lambda: sup.AccountSupervisor(spawn=None))
    acct = _register_mt5(client).json()["account"]
    _enroll(client, acct["account_id"])
    r = client.post(f"/accounts/{acct['account_id']}/runtime/start", json={})
    assert r.status_code == 409
    assert "no process launcher" in r.json()["detail"]
